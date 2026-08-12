"""orgh list: runs配下の全ミッションを一覧するための集計。

report.py と同様、RunStore.load()(実行中系ステータスの巻き戻し等の副作用を持つ)
は使わず、mission.json を直接読む。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_MAX_INTENT_LEN = 60


def _summarize_intent(intent: str) -> str:
    flat = intent.replace("\n", " ")
    if len(flat) > _MAX_INTENT_LEN:
        return flat[:_MAX_INTENT_LEN] + "…"
    return flat


def _derive_status(tasks: list[dict]) -> str:
    # status_json.status_payload と同一の導出規則を保つこと(GUIが両方を表示する)
    if not tasks:
        return "empty"
    statuses = [t.get("status") for t in tasks]
    terminal = ("done", "failed", "cancelled", "skipped")
    if all(s == "done" for s in statuses):
        return "done"
    if any(s == "failed" for s in statuses):
        return "failed"
    # status_json.status_payload と同一の優先順位(awaiting_approval優先)を保つ
    if any(s == "awaiting_approval" for s in statuses):
        return "awaiting_approval"
    if any(s == "awaiting_human" for s in statuses):
        return "awaiting_human"
    if all(s in terminal for s in statuses):
        return "cancelled"
    return "running"


# 完了扱いとするミッション状態(finished_tsを出す対象)
_FINISHED_STATUSES = ("done", "failed", "cancelled")

# finished_ts探索でledger末尾から遡るバイト数。mission.finishedは末尾近くに
# あるのが通常のため、この範囲で見つからなければ全読みにフォールバックする
_TAIL_BYTES = 64 * 1024


def _event_ts(line: str) -> tuple[str | None, float | None]:
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(ev, dict):
        return None, None
    ts = ev.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None, None
    return ev.get("event"), float(ts)


def _mission_times(d: Path, status: str) -> tuple[float | None, float | None]:
    """(起票ts, 完了ts) をledger.jsonlから導出する。

    起票=最初の有効イベントのts。完了=状態が終端のときの最後のmission.finishedのts
    (自己改変ガード停止時にも同イベントが残るため「最後」を採る。report.pyと同じ規則)。
    """
    lp = d / "ledger.jsonl"
    if not lp.exists():
        return None, None
    created = None
    try:
        with open(lp, errors="replace") as f:
            for line in f:
                if line.strip():
                    _, created = _event_ts(line)
                    if created is not None:
                        break
    except OSError:
        return None, None
    if status not in _FINISHED_STATUSES:
        return created, None
    finished = None
    try:
        size = lp.stat().st_size
        with open(lp, "rb") as f:
            f.seek(max(0, size - _TAIL_BYTES))
            lines = f.read().decode("utf-8", errors="replace").splitlines()
        if size > _TAIL_BYTES:
            lines = lines[1:]  # 先頭は途中からの行の可能性
        for line in reversed(lines):
            name, ts = _event_ts(line)
            if name == "mission.finished" and ts is not None:
                finished = ts
                break
        if finished is None and size > _TAIL_BYTES:
            for line in reversed(lp.read_text(errors="replace").splitlines()):
                name, ts = _event_ts(line)
                if name == "mission.finished" and ts is not None:
                    finished = ts
                    break
    except OSError:
        finished = None
    return created, finished


def list_missions(runs_dir: str | Path) -> list[dict]:
    return list_missions_report(runs_dir)["missions"]


def _dir_signature(d: Path) -> str:
    """mission.json と ledger.jsonl の mtime/size からキャッシュ鍵を作る。
    どちらかが変われば鍵が変わり、キャッシュは自動失効する。"""
    parts = []
    for name in ("mission.json", "ledger.jsonl"):
        try:
            st = (d / name).stat()
            parts.append(f"{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append("-")
    return "|".join(parts)


def _summarize_mission(d: Path) -> dict:
    """1ミッションディレクトリの一覧用サマリを組み立てる(全読み経路)。"""
    mission = json.loads((d / "mission.json").read_text())
    tasks = mission.get("tasks", [])
    budget = mission.get("budget")
    status = _derive_status(tasks)
    created_ts, finished_ts = _mission_times(d, status)
    return {
        "mission_id": mission["id"],
        "intent": _summarize_intent(mission.get("intent", "")),
        "status": status,
        "cost_usd": (budget or {}).get("spent_usd", 0.0) or 0.0,
        "tasks_done": sum(1 for t in tasks if t.get("status") == "done"),
        "tasks_total": len(tasks),
        "created_ts": created_ts,
        "finished_ts": finished_ts,
    }


# 終端(以降サマリが変わらない)ミッションのみキャッシュ対象にする。
# 実行中・承認待ちは毎回集計(件数が少なく、鍵も変わり続けるため)
_CACHEABLE = ("done", "failed", "cancelled", "empty")


def _load_index(root: Path) -> dict:
    try:
        data = json.loads((root / "_index.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_index(root: Path, index: dict) -> None:
    # ベストエフォート: 索引は高速化のためだけの派生データ。書けなくても
    # 一覧自体は成立する(次回また全読みするだけ)。atomicに置換する
    try:
        # pid付きtmpで並行writer(GUIポーリング+watch)のクロバーを避ける
        tmp = root / f"._index.json.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(index, ensure_ascii=False))
        tmp.replace(root / "_index.json")
    except OSError:
        pass


def list_missions_report(runs_dir: str | Path) -> dict:
    """一覧に加え、読めなかったミッションを skipped として明示的に返す。

    破損mission.jsonを黙って読み飛ばすと、GUI/CLIが「0件」と「データ破損」を
    区別できず、データ消失を「まだミッションがありません」と誤表示する。

    runs/_index.json に終端ミッションのサマリをmtime署名つきで永続キャッシュし、
    GUIの数秒ポーリング(サブプロセス起動のため毎回全読み)での全runs線形走査を
    避ける(ヘルスレビュー deferred: list/report線形走査)。索引は派生データで、
    壊れても/消えても一覧は全読みで正しく再構築される。
    """
    root = Path(runs_dir)
    if not root.exists():
        return {"missions": [], "skipped": []}

    old_index = _load_index(root)
    new_index: dict = {}
    out: list[dict] = []
    skipped: list[dict] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue  # _archive 等の内部ディレクトリは対象外
        mp = d / "mission.json"
        if not mp.exists():
            continue
        sig = _dir_signature(d)
        cached = old_index.get(d.name)
        if cached and cached.get("sig") == sig and "summary" in cached:
            summary = cached["summary"]  # 署名一致: 再読込しない
        else:
            try:
                summary = _summarize_mission(d)
            except Exception as e:
                skipped.append({"path": str(mp),
                                "reason": f"{type(e).__name__}: {e}"})
                continue
        out.append(summary)
        if summary["status"] in _CACHEABLE:
            new_index[d.name] = {"sig": sig, "summary": summary}

    _save_index(root, new_index)

    # 起票日時の新しい順(idは16進乱数で並び順に意味が無い)。
    # ledgerが無くcreated_ts不明のものは末尾、同点はid順で安定させる
    out.sort(key=lambda m: (m["created_ts"] is None,
                            -(m["created_ts"] or 0.0),
                            m["mission_id"]))
    return {"missions": out, "skipped": skipped}

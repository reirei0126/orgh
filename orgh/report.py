"""orgh report: ledgerからの集計(HANDOFF タスク7a)。

- 初回attempt合格率と差し戻し率の週次時系列(増幅の実在を示す最重要メトリクス)
- ミッション別コスト・所要時間
- worker別の失敗率

runs/<mission_id>/{mission.json,ledger.jsonl} を直接読む(RunStore.load()は
実行中系ステータスの巻き戻しなど実行用の副作用を持つため、集計では素のJSONを
読む)。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path


def _load_missions(runs_dir: str | Path) -> tuple[list[tuple[dict, list[dict]]], list[dict]]:
    """mission.json を持つ各ミッションディレクトリから (mission, events) を集める。

    壊れたmission.json/ledger行はミッション単位で隔離してskippedへ回す
    (1件の破損でレポート全体が閲覧不能になるのを防ぐ。listのskipped方式と同じ)。
    ledgerの壊れた行は読める行だけ採用する。
    """
    root = Path(runs_dir)
    if not root.exists():
        return [], []
    out = []
    skipped: list[dict] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        mp = d / "mission.json"
        if not mp.exists():
            continue
        try:
            mission = json.loads(mp.read_text(errors="replace"))
            # 構文上正しいJSONでも形が不正(配列など)だと後段の.get()で
            # レポート全体が停止するため、ここで形まで検証して隔離する
            if not isinstance(mission, dict) or \
                    not isinstance(mission.get("id"), str) or \
                    not isinstance(mission.get("tasks", []), list):
                raise ValueError("mission.jsonの形が不正(dict/id/tasksを満たさない)")
            events = []
            bad_lines = 0
            lp = d / "ledger.jsonl"
            if lp.exists():
                for line in lp.read_text(errors="replace").splitlines():
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        bad_lines += 1
                        continue
                    # ts欠落・非数値イベントは後段のe["ts"]比較で停止するため除外
                    ts = ev.get("ts") if isinstance(ev, dict) else None
                    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
                        bad_lines += 1
                        continue
                    events.append(ev)
            if bad_lines:
                # 部分採用は黙殺しない: 欠損があった事実をskippedで可視化する
                skipped.append({"path": str(d / "ledger.jsonl"),
                                "reason": f"解釈できないledger行を{bad_lines}行除外"
                                          "(集計は読めた行のみ)"})
        except Exception as e:
            skipped.append({"path": str(mp),
                            "reason": f"{type(e).__name__}: {e}"})
            continue
        out.append((mission, events))
    return out, skipped


def _weekly_stats(missions: list[tuple[dict, list[dict]]]) -> dict[str, dict]:
    """タスク単位で最初のレビュー系イベントから週次の初回合格・差し戻しを集計する。

    task.review(通常レビュー)とtask.persona_review(ペルソナ検収)の両方を
    集計対象にする。どちらも task/passed を持つ同形イベントで、直列ゲート
    (reviewer合格後にペルソナが裁定し、いずれかがfailすれば即差し戻し→再attempt
    という構造)の下では「ペルソナ差し戻し」も「初回attemptの不合格」に他ならない
    (フォローアップ1: ペルソナ差し戻しがreviewerだけ見ると初回合格に見えていた)。
    """
    weekly: dict[str, dict] = {}
    for mission, events in missions:
        by_task: dict[str, list[dict]] = {}
        for e in events:
            if e.get("event") in ("task.review", "task.persona_review"):
                task_id = e.get("task")
                if not isinstance(task_id, str):
                    # ts/eventが妥当でもtask欠落の破損行はありうる。
                    # 直接参照で全レポートを落とさずスキップする(p2r3指摘)
                    continue
                by_task.setdefault(task_id, []).append(e)
        for revs in by_task.values():
            first = revs[0]
            week = datetime.fromtimestamp(first["ts"]).strftime("%G-W%V")
            bucket = weekly.setdefault(
                week, {"total": 0, "first_pass": 0, "rework": 0})
            bucket["total"] += 1
            # 「全イベント合格」で判定する: 直列ゲートの構造上
            # 「初回attempt完全合格 ⟺ 失敗イベントが1件も存在しない」なので、
            # reviewer-onlyの過去履歴(ペルソナ未使用)では
            # 旧判定(first.get("passed"))と完全に一致する(数値の遡及変化なし)。
            # 直感: 最初のイベントがfailならこの時点でfirst.get("passed")もFalse。
            # 最初のイベントがpassなら、その時点でタスクはdone確定するため
            # reviewer-onlyの履歴に後続イベントは存在せず、結局1件のpassのみ。
            if all(e.get("passed") for e in revs):
                bucket["first_pass"] += 1
            if any(not r.get("passed") for r in revs):
                bucket["rework"] += 1
    return weekly


def _mission_cost(mission: dict) -> float:
    budget = mission.get("budget")
    return budget["spent_usd"] if budget else 0.0


def _mission_duration(events: list[dict]) -> int:
    if not events:
        return 0
    first_ts = events[0]["ts"]
    # mission.finishedは複数回残りうる(自己改変ガード停止時にも記録される)。
    # 最初のものを拾うとapprove経由の実行時間が0sになるため、最後を採用する
    finished = next(
        (e for e in reversed(events)
         if e.get("event") == "mission.finished"), None)
    last_ts = finished["ts"] if finished else events[-1]["ts"]
    return int(last_ts - first_ts)


def _mission_line(mission: dict, events: list[dict]) -> str:
    mission_id = mission["id"]
    intent = mission.get("intent", "")[:30]
    cost = _mission_cost(mission)
    duration = _mission_duration(events)
    tasks = mission.get("tasks", [])
    done = sum(1 for t in tasks if t.get("status") == "done")
    return (f"- {mission_id}: {intent} cost={cost:.2f} USD "
            f"duration={duration}s done={done}/{len(tasks)}")


def _worker_stats(missions: list[tuple[dict, list[dict]]]) -> dict[str, tuple[int, int]]:
    stats: dict[str, tuple[int, int]] = {}
    for mission, _events in missions:
        for t in mission.get("tasks", []):
            worker = t.get("worker")
            failed, n = stats.get(worker, (0, 0))
            n += 1
            if t.get("status") == "failed":
                failed += 1
            stats[worker] = (failed, n)
    return stats


def build_report(cfg: dict, days: int | None = None) -> str:
    missions, skipped = _load_missions(cfg.get("runs_dir", "runs"))

    if days is not None:
        cutoff = time.time() - days * 86400
        missions = [(m, e) for m, e in missions if e and e[0]["ts"] >= cutoff]

    scope = "all time" if days is None else f"last {days} days"
    lines = [f"# orgh report ({scope})", ""]

    lines.append("## 週次: 初回attempt合格率と差し戻し率")
    weekly = _weekly_stats(missions)
    for week in sorted(weekly):
        s = weekly[week]
        total = s["total"]
        fp_pct = round(s["first_pass"] / total * 100) if total else 0
        rw_pct = round(s["rework"] / total * 100) if total else 0
        lines.append(
            f"- {week}: 初回合格 {s['first_pass']}/{total} ({fp_pct}%) / "
            f"差し戻し {s['rework']}/{total} ({rw_pct}%)")
    lines.append("")

    lines.append("## ミッション別コスト・所要時間")
    for mission, events in missions:
        lines.append(_mission_line(mission, events))
    lines.append("")

    lines.append("## worker別失敗率")
    worker_stats = _worker_stats(missions)
    for worker in sorted(worker_stats):
        failed, n = worker_stats[worker]
        pct = round(failed / n * 100) if n else 0
        lines.append(f"- {worker}: {failed}/{n} failed ({pct}%)")

    if skipped:
        lines.append("")
        lines.append("## 集計から除外した壊れたデータ")
        for sk in skipped:
            lines.append(f"- {sk['path']} ({sk['reason']})")

    return "\n".join(lines)


def report_payload(cfg: dict, days: int | None = None) -> dict:
    """orgh report --json 用のペイロード(desktop/API.md §1.6)。

    build_report と同じ集計関数(_load_missions/_weekly_stats/_worker_stats/
    _mission_cost/_mission_duration)を再利用し、テキスト版と数値が食い違わない
    ようにする。パーセンテージも同じ計算式(round(x/total*100) if total else 0)
    を使う。
    """
    missions, skipped = _load_missions(cfg.get("runs_dir", "runs"))
    if days is not None:
        cutoff = time.time() - days * 86400
        missions = [(m, e) for m, e in missions if e and e[0]["ts"] >= cutoff]

    weekly = _weekly_stats(missions)
    weekly_json = []
    for week in sorted(weekly):
        s = weekly[week]
        total = s["total"]
        weekly_json.append({
            "week": week,
            "total": total,
            "first_pass": s["first_pass"],
            "first_pass_pct": round(s["first_pass"] / total * 100) if total else 0,
            "rework": s["rework"],
            "rework_pct": round(s["rework"] / total * 100) if total else 0,
        })

    missions_json = []
    for mission, events in missions:
        tasks = mission.get("tasks", [])
        missions_json.append({
            "mission_id": mission["id"],
            "intent": mission.get("intent", ""),
            "cost_usd": _mission_cost(mission),
            "duration_sec": _mission_duration(events),
            "tasks_done": sum(1 for t in tasks if t.get("status") == "done"),
            "tasks_total": len(tasks),
        })

    # テキスト版の _worker_stats はworker未割当(None)も辞書に含めてしまい
    # sorted()がNoneと文字列の比較でTypeErrorになりうる潜在バグがあるが、
    # JSON版はこれを踏襲せず除外する(新規追加分のみのバグ修正。テキスト版
    # の出力・sorted(worker_stats)の挙動は変更しない)。
    worker_stats = _worker_stats(missions)
    workers_json = []
    for worker in sorted(w for w in worker_stats if w is not None):
        failed, n = worker_stats[worker]
        workers_json.append({
            "worker": worker,
            "failed": failed,
            "total": n,
            "failed_pct": round(failed / n * 100) if n else 0,
        })

    return {"days": days, "weekly": weekly_json, "missions": missions_json,
            "workers": workers_json, "skipped": skipped}

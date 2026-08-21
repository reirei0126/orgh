"""orgh status --json 用のペイロード組み立て(機械可読)。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import lease
from .guard import approval_reason
from .state import TERMINAL

# 実行中系タスクステータス。state._INFLIGHT_STATUSESと同期を保つこと
# (listing._INFLIGHT_TASK_STATUSESと同じ理由で複製している)。
_INFLIGHT_TASK_STATUSES = ("queued", "running", "review")


def _mission_dir(cfg: dict | None, mission_id: str) -> Path:
    """RunStoreと同じ既定(cfg.get("runs_dir", "runs"))でミッションdirを解決する。"""
    return Path((cfg or {}).get("runs_dir", "runs")) / mission_id


def _lease_expired(d: Path) -> bool:
    """listing._lease_expiredと同一規則(orgh/lease.py の公開APIのみ使用)。
    leaseが一度も取得されていない場合はFalse(判定材料が無いだけ)。
    表示専用のis_alive_lenient()を使う理由はlisting._lease_expiredの
    docstring参照(pidの生死は見ずheartbeat鮮度のみで判定する)。"""
    return lease.read(d) is not None and not lease.is_alive_lenient(d)


def _read_human_request_body(mission_dir: Path, task_id: str) -> str | None:
    try:
        return (mission_dir / "artifacts" / f"human_request_{task_id}.md").read_text()
    except OSError:
        return None


def _read_verdicts(mission_dir: Path) -> list[dict]:
    fp = mission_dir / "verdicts.jsonl"
    if not fp.is_file():
        return []
    out: list[dict] = []
    for line in fp.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _flatten(text: str) -> str:
    """改行を空白へ畳む。LLM生成のtitleに改行(例: "\\nORGH_APPROVED=evil")が
    混じると、CLIのブリーフ出力(orgh/cli.py)がそのまま複数行printし、
    `ORGH_APPROVED=`で始まる行を偽造されてしまう(cli.rsのstrip_prefix検知が
    APPROVED作成前に「承認成功」と誤認する)。信頼できない文字列を1行に
    強制正規化してから出力へ回す(呼び出し側の対策ではなく生成元で防ぐ)。"""
    return " ".join(text.splitlines())


def status_payload(mission: Any, cfg: dict | None = None) -> dict:
    """mission オブジェクトから json.dumps 可能な dict を組み立てる純関数。

    cfg を渡し、かつ awaiting_approval タスクが1件以上あるときのみ
    approval_brief キーを追加する(オーナー裁定 PROD-001: 承認接点は詳細を
    探させず一文で先に提示する)。cfg=None(既存呼び出し)や awaiting なしの
    ときはキー自体を省略し、旧GUI/旧呼び出しとの後方互換を保つ。"""
    mission_dir = _mission_dir(cfg, mission.id)
    # 実行中系タスク(queued/running/review)を抱えているのにleaseが失効して
    # いる場合の表示用フラグ。mission-level/task-level両方の"unknown"上書きで
    # 共有する(orgh/lease.py の公開APIのみ使用、定数はここで再定義しない)
    lease_dead = _lease_expired(mission_dir)

    statuses = [t.status for t in mission.tasks]
    # listing._derive_status と同一の導出規則を保つこと(GUIが両方を表示する)
    if not statuses:
        # listは"empty"を返すのにstatusが"running"だと同一ミッションが
        # 画面間で食い違う
        mission_status = "empty"
    elif all(s == "done" for s in statuses):
        mission_status = "done"
    elif any(s == "failed" for s in statuses):
        mission_status = "failed"
    # awaiting_approval と awaiting_human が同時に存在する場合は
    # awaiting_approval を優先する: 承認待ちは orgh 自身への変更を止めている
    # 自己改変ガードであり、放置するとセキュリティ上のリスクがあるため、
    # 人間への作業依頼(awaiting_human)より先に目に入るべき
    elif any(s == "awaiting_approval" for s in statuses):
        mission_status = "awaiting_approval"
    elif any(s == "awaiting_human" for s in statuses):
        mission_status = "awaiting_human"
    elif statuses and all(s in TERMINAL for s in statuses):
        # 全タスク終端でdone以外を含む(cancel/budget stop後)。runningのままだと
        # 停止済みミッションへ再キャンセルを誘発する
        mission_status = "cancelled"
    else:
        mission_status = "running"
    # 投入済み・executor未着手(全タスクpending+キューエントリ存在)は
    # runningではなくqueued(listing._derive_statusと導出規則を揃えること)。
    # cfg=None(旧呼び出し)はキュー位置が分からないため従来どおりrunning
    if (mission_status == "running" and cfg is not None
            and statuses and all(s == "pending" for s in statuses)
            and (Path(cfg.get("runs_dir", "runs")) / "_queue"
                 / f"{mission.id}.json").exists()):
        mission_status = "queued"
    # listing._summarize_mission と同一規則: 実行中系タスクを抱えたまま
    # プロセスのleaseが失効していれば、pending/failedに丸めず「unknown」を
    # 出す(判別不能を判別不能のまま出す。丸めると二重実行/成果喪失を誘発する)
    if (mission_status == "running"
            and any(s in _INFLIGHT_TASK_STATUSES for s in statuses)
            and lease_dead):
        mission_status = "unknown"

    budget = getattr(mission, "budget", None)
    cost_usd = budget.spent_usd if budget else 0.0
    budget_usd = budget.limit_usd if budget else None

    payload = {
        "mission_id": mission.id,
        "intent": mission.intent,
        "status": mission_status,
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "status": ("unknown" if (lease_dead and
                                          t.status in _INFLIGHT_TASK_STATUSES)
                           else t.status),
                "attempts": t.attempts,
                "worker": t.worker,
                "deps": list(t.deps),
                "human_request": _flatten(t.human_request) if t.human_request else "",
                "human_request_body": (
                    _read_human_request_body(mission_dir, t.id)
                    if t.status == "awaiting_human" else None
                ),
            }
            for t in mission.tasks
        ],
        "cost_usd": cost_usd,
        "budget_usd": budget_usd,
        "verdicts": _read_verdicts(mission_dir),
    }

    if cfg is not None:
        awaiting = [t for t in mission.tasks if t.status == "awaiting_approval"]
        if awaiting:
            decision_gates = getattr(mission, "decision_gates", None) or []
            gated_tasks = [
                {
                    "id": t.id,
                    "title": _flatten(t.title),
                    "workdir": _flatten(t.workdir),
                    "reason": approval_reason(cfg, t.workdir) or (
                        "決定ゲート(人間判断が必要な値)への回答待ち"
                        if decision_gates else "(理由不明)"),
                }
                for t in awaiting
            ]
            pending_task_count = sum(
                1 for t in mission.tasks
                if t.status in ("awaiting_approval", "pending"))
            first = gated_tasks[0]
            others = "" if len(gated_tasks) == 1 else f"ほか{len(gated_tasks) - 1}件"
            summary = (
                f"タスク「{first['title']}」{others}が{first['reason']}ため停止中。"
                f"承認すると残り{pending_task_count}件のタスクが実行される"
                f"(消費済み {cost_usd:.2f} USD)。"
            )
            payload["approval_brief"] = {
                "summary": summary,
                "gated_tasks": gated_tasks,
                "pending_task_count": pending_task_count,
            }
            if decision_gates:
                payload["approval_brief"]["decision_gates"] = [
                    {
                        "id": g["id"],
                        "question": g["question"],
                        "options": list(g["options"]),
                        "default": g["default"],
                        "why_human": g["why_human"],
                    }
                    for g in decision_gates
                ]

    # awaiting_human タスクが1件以上あるときのみ human_requests キーを追加する
    # (approval_brief と同じく、対象なしのときはキー自体を省いて後方互換を保つ)。
    # cfgを読まずに済む(依頼一文はplanner.build_human_requestが既にtaskへ
    # 埋め込み済みで、artifactパスもstore.artifact()の命名規則から機械的に
    # 導けるため)、cfg=Noneの呼び出しでもこのキーは出す
    human_waiting = [t for t in mission.tasks if t.status == "awaiting_human"]
    if human_waiting:
        payload["human_requests"] = [
            {
                "task": t.id,
                "title": _flatten(t.title),
                "request": _flatten(t.human_request),
                "artifact": f"artifacts/human_request_{t.id}.md",
            }
            for t in human_waiting
        ]

    return payload

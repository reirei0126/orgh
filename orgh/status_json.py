"""orgh status --json 用のペイロード組み立て(機械可読)。"""
from __future__ import annotations

from typing import Any

from .guard import approval_reason


def status_payload(mission: Any, cfg: dict | None = None) -> dict:
    """mission オブジェクトから json.dumps 可能な dict を組み立てる純関数。

    cfg を渡し、かつ awaiting_approval タスクが1件以上あるときのみ
    approval_brief キーを追加する(オーナー裁定 PROD-001: 承認接点は詳細を
    探させず一文で先に提示する)。cfg=None(既存呼び出し)や awaiting なしの
    ときはキー自体を省略し、旧GUI/旧呼び出しとの後方互換を保つ。"""
    statuses = [t.status for t in mission.tasks]
    # listing._derive_status と同一の導出規則を保つこと(GUIが両方を表示する)
    terminal = ("done", "failed", "cancelled", "skipped")
    if not statuses:
        # listは"empty"を返すのにstatusが"running"だと同一ミッションが
        # 画面間で食い違う
        mission_status = "empty"
    elif all(s == "done" for s in statuses):
        mission_status = "done"
    elif any(s == "failed" for s in statuses):
        mission_status = "failed"
    elif any(s == "awaiting_approval" for s in statuses):
        mission_status = "awaiting_approval"
    elif statuses and all(s in terminal for s in statuses):
        # 全タスク終端でdone以外を含む(cancel/budget stop後)。runningのままだと
        # 停止済みミッションへ再キャンセルを誘発する
        mission_status = "cancelled"
    else:
        mission_status = "running"

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
                "status": t.status,
                "attempts": t.attempts,
                "worker": t.worker,
                "deps": list(t.deps),
            }
            for t in mission.tasks
        ],
        "cost_usd": cost_usd,
        "budget_usd": budget_usd,
    }

    if cfg is not None:
        awaiting = [t for t in mission.tasks if t.status == "awaiting_approval"]
        if awaiting:
            gated_tasks = [
                {
                    "id": t.id,
                    "title": t.title,
                    "workdir": t.workdir,
                    "reason": approval_reason(cfg, t.workdir) or "(理由不明)",
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

    return payload

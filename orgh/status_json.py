"""orgh status --json 用のペイロード組み立て(機械可読)。"""
from __future__ import annotations

from typing import Any


def status_payload(mission: Any) -> dict:
    """mission オブジェクトから json.dumps 可能な dict を組み立てる純関数。"""
    statuses = [t.status for t in mission.tasks]
    if statuses and all(s == "done" for s in statuses):
        mission_status = "done"
    elif any(s == "failed" for s in statuses):
        mission_status = "failed"
    else:
        mission_status = "running"

    budget = getattr(mission, "budget", None)
    cost_usd = budget.spent_usd if budget else 0.0
    budget_usd = budget.limit_usd if budget else None

    return {
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

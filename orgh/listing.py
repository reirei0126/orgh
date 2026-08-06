"""orgh list: runs配下の全ミッションを一覧するための集計。

report.py と同様、RunStore.load()(実行中系ステータスの巻き戻し等の副作用を持つ)
は使わず、mission.json を直接読む。
"""
from __future__ import annotations

import json
from pathlib import Path

_MAX_INTENT_LEN = 60


def _summarize_intent(intent: str) -> str:
    flat = intent.replace("\n", " ")
    if len(flat) > _MAX_INTENT_LEN:
        return flat[:_MAX_INTENT_LEN] + "…"
    return flat


def _derive_status(tasks: list[dict]) -> str:
    if not tasks:
        return "empty"
    statuses = [t.get("status") for t in tasks]
    if any(s == "failed" for s in statuses):
        return "failed"
    if all(s == "done" for s in statuses):
        return "done"
    return "running"


def list_missions(runs_dir: str | Path) -> list[dict]:
    root = Path(runs_dir)
    if not root.exists():
        return []

    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        mp = d / "mission.json"
        if not mp.exists():
            continue
        try:
            mission = json.loads(mp.read_text())
            tasks = mission.get("tasks", [])
            budget = mission.get("budget")
            out.append({
                "mission_id": mission["id"],
                "intent": _summarize_intent(mission.get("intent", "")),
                "status": _derive_status(tasks),
                "cost_usd": (budget or {}).get("spent_usd", 0.0) or 0.0,
                "tasks_done": sum(1 for t in tasks if t.get("status") == "done"),
                "tasks_total": len(tasks),
            })
        except Exception:
            continue

    out.sort(key=lambda m: m["mission_id"])
    return out

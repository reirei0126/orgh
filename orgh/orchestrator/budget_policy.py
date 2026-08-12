"""予算の横断ポリシー: ミッション予算プールの用意と超過時の停止。"""
from __future__ import annotations

from ..state import Budget, Mission, RunStore


def setup_budget(cfg: dict, mission: Mission) -> Budget:
    """ミッションの予算プールを用意する。初回はconfigから確保、resume時は
    消費(spent)を引き継ぎつつ上限だけconfigから更新する(予算を上げて続行
    できるように)。split()で割当を受けた子ミッションは上限を上書きしない。"""
    lcfg = cfg.get("loop", {})
    if mission.budget is None:
        mission.budget = Budget(limit_usd=lcfg.get("budget_usd"),
                                task_budget_usd=lcfg.get("task_budget_usd"))
    elif mission.budget._parent is None:
        mission.budget.limit_usd = lcfg.get("budget_usd")
        mission.budget.task_budget_usd = lcfg.get("task_budget_usd")
    return mission.budget


def initiate_budget_stop(mission: Mission, store: RunStore,
                         budget: Budget) -> None:
    """予算超過: 実行中タスクの完了は待つが、未着手はdispatchせずskippedに。"""
    with store.lock:
        for t in mission.tasks:
            if t.status == "pending":
                t.status = "skipped"
    store.save(mission)
    store.log("mission.budget_exceeded", spent=budget.spent_usd,
              limit=budget.limit_usd)
    print(f"  mission {store.dir.name} budget exceeded "
          f"({budget.spent_usd:.4f}/{budget.limit_usd} USD) — 未着手をskip")

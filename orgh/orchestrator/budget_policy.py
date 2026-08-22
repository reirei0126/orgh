"""予算の横断ポリシー: ミッション予算プールの用意と超過時の停止。"""
from __future__ import annotations

from ..state import Budget, Mission, RunStore


def setup_budget(cfg: dict, mission: Mission,
                 store: RunStore | None = None) -> Budget:
    """ミッションの予算プールを用意する。

    優先順位(ミッション固有宣言 > config既定):
    - mission.budget が未設定(初回)なら config値で新規確保する(source="config")。
    - 既にある場合(split()で割当を受けた子=_parentがある場合を除く):
      - source が "note"(ノート宣言)/"manual"(手動設定)なら、config値で
        無条件に上書きしない。config値が現在値より大きい場合のみ引き上げる
        (resume時に予算を上げて続行できるように)。config値がNone(無制限)
        や現在値以下の場合は据え置く(宣言済みの上限を無制限へ緩めたり、
        下げたりしない)。task_budget_usdも同じ規則。
        引き上げてもsourceは"note"/"manual"のまま変えない(ここで
        source="config"に書き換えると、次回以降のconfig=None(無指定既定)な
        通常resumeが「宣言なし」と誤認され46-49行目の無条件上書き分岐に落ち、
        無制限化してしまう — 元の断線=mission 8b435cc4の再発。監査上「今回
        configが引き上げた」事実はledgerの mission.budget_setup イベント側に
        残るため、sourceフィールド自体を上書きする必要はない)。
      - source が それ以外("config"/None、= ノート宣言のない従来ミッション)
        なら、従来どおりconfig値を無条件に反映する(挙動不変。configの
        変更が縮小方向でもそのまま追従する)。
    - split()で割当を受けた子ミッション(_parent is not None)は上限を
      上書きしない(従来どおり)。

    storeを渡すとledgerへ mission.budget_setup イベント(source含む)を記録する
    (予算の出所の監査可能性)。
    """
    lcfg = cfg.get("loop", {})
    cfg_limit = lcfg.get("budget_usd")
    cfg_task_limit = lcfg.get("task_budget_usd")
    if mission.budget is None:
        mission.budget = Budget(limit_usd=cfg_limit,
                                task_budget_usd=cfg_task_limit,
                                source="config")
    elif mission.budget._parent is None:
        b = mission.budget
        if b.source in ("note", "manual"):
            if cfg_limit is not None and (
                    b.limit_usd is None or cfg_limit > b.limit_usd):
                b.limit_usd = cfg_limit
            if cfg_task_limit is not None and (
                    b.task_budget_usd is None
                    or cfg_task_limit > b.task_budget_usd):
                b.task_budget_usd = cfg_task_limit
        else:
            b.limit_usd = cfg_limit
            b.task_budget_usd = cfg_task_limit
            b.source = "config"
    if store is not None:
        store.log("mission.budget_setup", limit_usd=mission.budget.limit_usd,
                  task_budget_usd=mission.budget.task_budget_usd,
                  source=mission.budget.source)
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

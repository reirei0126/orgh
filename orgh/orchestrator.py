"""Orchestrator: DAGに従いWorkerを並列起動。
task: pending -> running -> review -> done / (feedback付きで再実行) -> failed
Claude Codeタスクは session_id を保持し --resume でフィードバックを渡す(文脈を捨てない)。

キャンセル(HANDOFF タスク4): runs/<mission_id>/CANCEL フラグファイルが唯一の
停止信号。orgh cancel(別プロセス)はフラグを置くだけで、ミッションを実行中の
プロセス自身がループごとにフラグを検知し、実行中subprocessをterminate・
未着手タスクをcancelledにして停止する。poll_cancel(watcherが渡す結果ノートの
#cancel検知)がTrueを返した場合もフラグを置いて同じ経路に合流する。
"""
from __future__ import annotations

import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from . import procreg
from .adapters.base import get_adapter
from .guard import needs_approval
from .planner import review, worker_prompt
from .state import Budget, Mission, RunStore, Task
from .worktree import ensure_task_worktree

# 終端ステータス(これ以外は実行中系としてresume時にpendingへ巻き戻される)
TERMINAL = ("done", "failed", "cancelled", "skipped")

# キャンセル検知のポーリング間隔(秒)。タスク完了イベントもこの粒度で拾う
_POLL_INTERVAL = 0.5


def _ready(m: Mission) -> list[Task]:
    done = {t.id for t in m.tasks if t.status == "done"}
    return [t for t in m.tasks
            if t.status == "pending" and all(d in done for d in t.deps)]


def _blocked_forever(m: Mission) -> bool:
    dead = {t.id for t in m.tasks if t.status in ("failed", "cancelled")}
    pend = [t for t in m.tasks if t.status == "pending"]
    return bool(dead) and all(
        any(d in dead for d in t.deps) for t in pend) if pend else False


def _cancel_flag(store: RunStore):
    return store.dir / "CANCEL"


def _run_task(cfg: dict, store: RunStore, t: Task, budget: Budget) -> Task:
    """最外周の薄いラッパ: 実処理(_attempt_loop)の全例外を1タスクのfailedに閉じ込め、
    ミッション全体を道連れにしない。"""
    try:
        return _attempt_loop(cfg, store, t, budget)
    except Exception as e:
        with store.lock:
            t.status = "failed"
            t.review_notes = f"internal error: {e!r}"
        store.log("task.error", task=t.id, error=repr(e),
                  trace=traceback.format_exc()[-2000:])
        return t


def _attempt_loop(cfg: dict, store: RunStore, t: Task, budget: Budget) -> Task:
    wt_cfg = cfg.get("worktree") or {}
    if wt_cfg.get("enabled"):
        got = ensure_task_worktree(wt_cfg, store.dir.name, t)
        if got:
            path, branch = got
            with store.lock:
                t.workdir, t.branch = str(path), branch
            store.log("task.worktree", task=t.id, path=str(path), branch=branch)

    adapter = get_adapter(t.worker, cfg["workers"])
    max_attempts = cfg.get("loop", {}).get("max_attempts", 3)
    cancel_flag = _cancel_flag(store)

    prompt = worker_prompt(cfg, t)
    while t.attempts < max_attempts:
        if cancel_flag.exists():
            with store.lock:
                t.status = "cancelled"
            return t
        with store.lock:
            t.attempts += 1
            t.status = "running"
        store.log("task.start", task=t.id, worker=t.worker, attempt=t.attempts)
        res = adapter.run(prompt, workdir=t.workdir,
                          resume=t.session_id,
                          timeout=cfg.get("loop", {}).get("task_timeout", 3600),
                          registry_key=store.dir.name,
                          allowed_tools=t.tools)
        with store.lock:
            t.last_output = res.output
            t.session_id = res.session_id or t.session_id
            t.cost_usd += res.cost_usd or 0.0
        budget.charge(res.cost_usd)
        store.artifact(f"{t.id}_attempt{t.attempts}.md", res.output)
        store.log("task.output", task=t.id, ok=res.ok, cost=res.cost_usd)

        # タスク上限超過: 次のattemptにもレビューにも進まない
        if (budget.task_budget_usd is not None
                and t.cost_usd >= budget.task_budget_usd):
            with store.lock:
                t.status = "failed"
                t.review_notes = (f"task予算超過: {t.cost_usd:.4f} USD >= "
                                  f"{budget.task_budget_usd} USD")
            store.log("task.budget_exceeded", task=t.id, cost=t.cost_usd,
                      limit=budget.task_budget_usd)
            return t

        if not res.ok:
            if cancel_flag.exists():
                # terminateによる異常終了は失敗ではなくキャンセル扱い
                with store.lock:
                    t.status = "cancelled"
                return t
            prompt = f"前回の実行がエラーで終了した。原因を特定して完了させろ。\n---\n{res.output[:4000]}"
            continue

        with store.lock:
            t.status = "review"
        passed, feedback = review(cfg, t, workdir=t.workdir, budget=budget)
        with store.lock:
            t.review_notes = feedback
        store.log("task.review", task=t.id, passed=passed)
        if passed:
            with store.lock:
                t.status = "done"
            return t
        # 改善ループ: レビューのフィードバックをそのままresumeセッションへ
        prompt = (f"レビューで差し戻し。以下を修正して受け入れ条件を満たせ。\n"
                  f"## Feedback\n{feedback}")

    with store.lock:
        t.status = "failed"
    return t


def _initiate_cancel(mission: Mission, store: RunStore) -> None:
    """キャンセル開始: フラグを確定し、実行中subprocessをterminate、
    未着手タスクをcancelledにする。実行中タスクの完了(cancelled化)は
    _attempt_loop側がフラグを見て行う。"""
    _cancel_flag(store).touch()
    n = procreg.terminate(store.dir.name)
    with store.lock:
        for t in mission.tasks:
            if t.status == "pending":
                t.status = "cancelled"
    store.save(mission)
    store.log("mission.cancelled", terminated=n)
    print(f"  mission {store.dir.name} cancelling... ({n} proc terminated)")


def _setup_budget(cfg: dict, mission: Mission) -> Budget:
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


def _initiate_budget_stop(mission: Mission, store: RunStore,
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


def run_mission(cfg: dict, mission: Mission, store: RunStore,
                on_update=None, poll_cancel=None) -> Mission:
    workers = cfg.get("loop", {}).get("parallel", 3)
    budget = _setup_budget(cfg, mission)
    store.save(mission)
    store.artifact("context_digest.md", mission.context_digest)
    cancelling = False
    budget_stopped = False
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        while True:
            if not cancelling and (
                    _cancel_flag(store).exists()
                    or (poll_cancel and poll_cancel())):
                cancelling = True
                _initiate_cancel(mission, store)
            if not cancelling and not budget_stopped and budget.exceeded():
                budget_stopped = True
                _initiate_budget_stop(mission, store, budget)
            if not cancelling and not budget_stopped:
                for t in _ready(mission):
                    if t.id in futures:
                        continue
                    # 自己改変ガード: orgh自身を指すworkdirは承認なしに実行しない
                    # (watcher経由でもスキップ不可。configでも無効化不可)
                    if (needs_approval(cfg, t.workdir)
                            and not (store.dir / "APPROVED").exists()):
                        with store.lock:
                            t.status = "awaiting_approval"
                        store.log("task.awaiting_approval", task=t.id,
                                  workdir=t.workdir)
                        print(f"  [awaiting_approval] {t.title} — "
                              f"orgh approve {store.dir.name} で続行")
                        continue
                    with store.lock:
                        t.status = "queued"
                    futures[t.id] = pool.submit(_run_task, cfg, store, t,
                                                budget)
            if not futures:
                break
            done, _ = wait(list(futures.values()), timeout=_POLL_INTERVAL,
                           return_when=FIRST_COMPLETED)
            for fut in done:
                finished = fut.result()
                futures = {k: v for k, v in futures.items() if v is not fut}
                store.save(mission)
                if on_update:
                    on_update(mission)
                print(f"  [{finished.status}] {finished.title}")
            if not done:
                continue
            if all(t.status in TERMINAL for t in mission.tasks) and not futures:
                break
            if _blocked_forever(mission) and not futures:
                break
    store.save(mission)
    store.log("mission.finished",
              done=[t.id for t in mission.tasks if t.status == "done"],
              failed=[t.id for t in mission.tasks if t.status == "failed"],
              cancelled=[t.id for t in mission.tasks
                         if t.status == "cancelled"])
    return mission

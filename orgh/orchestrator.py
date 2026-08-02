"""Orchestrator: DAGに従いWorkerを並列起動。
task: pending -> running -> review -> done / (feedback付きで再実行) -> failed
Claude Codeタスクは session_id を保持し --resume でフィードバックを渡す(文脈を捨てない)。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from .adapters.base import get_adapter
from .planner import review, worker_prompt
from .state import Mission, RunStore, Task


def _ready(m: Mission) -> list[Task]:
    done = {t.id for t in m.tasks if t.status == "done"}
    return [t for t in m.tasks
            if t.status == "pending" and all(d in done for d in t.deps)]


def _blocked_forever(m: Mission) -> bool:
    failed = {t.id for t in m.tasks if t.status == "failed"}
    pend = [t for t in m.tasks if t.status == "pending"]
    return bool(failed) and all(
        any(d in failed for d in t.deps) for t in pend) if pend else False


def _run_task(cfg: dict, store: RunStore, t: Task) -> Task:
    adapter = get_adapter(t.worker, cfg["workers"])
    max_attempts = cfg.get("loop", {}).get("max_attempts", 3)

    prompt = worker_prompt(t)
    while t.attempts < max_attempts:
        t.attempts += 1
        t.status = "running"
        store.log("task.start", task=t.id, worker=t.worker, attempt=t.attempts)
        res = adapter.run(prompt, workdir=t.workdir,
                          resume=t.session_id,
                          timeout=cfg.get("loop", {}).get("task_timeout", 3600))
        t.last_output = res.output
        t.session_id = res.session_id or t.session_id
        store.artifact(f"{t.id}_attempt{t.attempts}.md", res.output)
        store.log("task.output", task=t.id, ok=res.ok, cost=res.cost_usd)

        if not res.ok:
            prompt = f"前回の実行がエラーで終了した。原因を特定して完了させろ。\n---\n{res.output[:4000]}"
            continue

        t.status = "review"
        passed, feedback = review(cfg, t, workdir=t.workdir)
        t.review_notes = feedback
        store.log("task.review", task=t.id, passed=passed)
        if passed:
            t.status = "done"
            return t
        # 改善ループ: レビューのフィードバックをそのままresumeセッションへ
        prompt = (f"レビューで差し戻し。以下を修正して受け入れ条件を満たせ。\n"
                  f"## Feedback\n{feedback}")

    t.status = "failed"
    return t


def run_mission(cfg: dict, mission: Mission, store: RunStore) -> Mission:
    workers = cfg.get("loop", {}).get("parallel", 3)
    store.save(mission)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        while True:
            for t in _ready(mission):
                if t.id not in futures:
                    t.status = "queued"
                    futures[t.id] = pool.submit(_run_task, cfg, store, t)
            if not futures:
                break
            done_iter = as_completed(list(futures.values()), timeout=None)
            fut = next(done_iter)
            finished = fut.result()
            futures = {k: v for k, v in futures.items() if v is not fut}
            store.save(mission)
            print(f"  [{finished.status}] {finished.title}")
            if all(t.status in ("done", "failed") for t in mission.tasks) and not futures:
                break
            if _blocked_forever(mission) and not futures:
                break
    store.save(mission)
    store.log("mission.finished",
              done=[t.id for t in mission.tasks if t.status == "done"],
              failed=[t.id for t in mission.tasks if t.status == "failed"])
    return mission

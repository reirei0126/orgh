"""ペルソナ検収ゲート(戦略設計書 柱1)。final_task割り当てと検収ループ。"""
from __future__ import annotations

from orgh.orchestrator import _assign_personas, run_mission
from orgh.state import Mission, RunStore


def _task(id: str, deps=None, **kw) -> dict:
    return {"id": id, "title": f"task {id}", "prompt": f"作業 [[MARK:{id}]]",
            "worker": "claude_code", "deps": deps or [],
            "acceptance": ["mock acceptance"], "workdir": ".", **kw}


class TestAssign:
    def test_final_task_gets_personas(self):
        m = Mission.new(intent="x", context_digest="",
                        tasks=[_task("t1"), _task("t2", deps=["t1"])])
        _assign_personas({"personas": {"enabled": ["consumer"]}}, m)
        assert m.tasks[0].personas == []          # 中間タスクは対象外
        assert m.tasks[1].personas == ["consumer"]

    def test_disabled_is_noop(self):
        m = Mission.new(intent="x", context_digest="", tasks=[_task("t1")])
        _assign_personas({}, m)
        assert m.tasks[0].personas == []

    def test_planner_explicit_wins(self):
        m = Mission.new(intent="x", context_digest="",
                        tasks=[_task("t1", personas=["designer"])])
        _assign_personas({"personas": {"enabled": ["consumer"]}}, m)
        assert m.tasks[0].personas == ["designer"]

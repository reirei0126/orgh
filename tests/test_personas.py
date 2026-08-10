"""ペルソナ検収ゲート(戦略設計書 柱1)。final_task割り当てと検収ループ。"""
from __future__ import annotations

import pytest

from orgh.orchestrator import _assign_personas, run_mission
from orgh.planner import persona_review
from orgh.state import Mission, RunStore, Task


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


def _t(id="p1") -> Task:
    return Task(id=id, title="UI", prompt=f"作業 [[MARK:{id}]]",
                acceptance=["a"], last_output="done")


class TestPersonaReview:
    def test_pass_with_evidence(self, cfg, mock_state_dir):
        ok, fb = persona_review(cfg, "consumer", _t(), workdir=".")
        assert ok and fb == ""

    def test_no_evidence_pass_is_invalid(self, cfg, mock_state_dir,
                                         monkeypatch):
        monkeypatch.setenv("MOCK_PERSONA_NO_EVIDENCE", "p1")
        with pytest.raises(ValueError, match="証拠"):
            persona_review(cfg, "consumer", _t(), workdir=".")

    def test_fail_without_evidence_is_valid(self, cfg, mock_state_dir,
                                            monkeypatch):
        monkeypatch.setenv("MOCK_PERSONA_ALWAYS_FAIL", "p1")
        ok, fb = persona_review(cfg, "designer", _t(), workdir=".")
        assert not ok and "MARK" in fb

"""差し戻しfeedbackとowner_replanのledger収集層(criteria_feedback)。

collect_normative_feedback() が ledger.jsonl から
(a) 不合格 task.review の feedback と (b) owner.interrupt(kind=owner_replan)
の detail を出現順に集めることを検証する。後続タスクのLLM蒸留・retro配線は
対象外(このテストはledger収集の純関数だけを見る)。
"""
from __future__ import annotations

from orgh.criteria_feedback import collect_normative_feedback
from orgh.state import RunStore


class TestCollectNormativeFeedback:
    def test_collects_failed_review_and_owner_replan(self, cfg, mock_state_dir):
        store = RunStore(cfg["runs_dir"], "m1")
        store.log("task.review", task="t1", passed=False,
                  criteria_cited=[], feedback="acceptanceを満たしていない")
        store.log("owner.interrupt", kind="owner_replan", task="t2",
                  detail="計画自体が曖昧だった")

        result = collect_normative_feedback(cfg, "m1")

        assert result == [
            {"kind": "review", "task": "t1", "text": "acceptanceを満たしていない"},
            {"kind": "owner_replan", "task": "t2", "text": "計画自体が曖昧だった"},
        ]

    def test_passed_review_is_excluded(self, cfg, mock_state_dir):
        store = RunStore(cfg["runs_dir"], "m2")
        store.log("task.review", task="t1", passed=True,
                  criteria_cited=[], feedback="")

        assert collect_normative_feedback(cfg, "m2") == []

    def test_missing_or_blank_feedback_is_excluded(self, cfg, mock_state_dir):
        store = RunStore(cfg["runs_dir"], "m3")
        store.log("task.review", task="t1", passed=False, criteria_cited=[])
        store.log("task.review", task="t2", passed=False,
                  criteria_cited=[], feedback="   ")
        store.log("owner.interrupt", kind="owner_replan", task="t3", detail="")

        assert collect_normative_feedback(cfg, "m3") == []

    def test_missing_ledger_returns_empty_list(self, cfg, mock_state_dir):
        assert collect_normative_feedback(cfg, "no-such-mission") == []

    def test_non_owner_replan_interrupt_is_excluded(self, cfg, mock_state_dir):
        store = RunStore(cfg["runs_dir"], "m4")
        store.log("owner.interrupt", kind="awaiting_human", task="t1",
                  detail="人間の判断待ち")

        assert collect_normative_feedback(cfg, "m4") == []

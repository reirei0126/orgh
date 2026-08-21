"""差し戻しfeedbackとowner_replanのledger収集層(criteria_feedback)。

collect_normative_feedback() が ledger.jsonl から
(a) 不合格 task.review の feedback と (b) owner.interrupt(kind=owner_replan)
の detail を出現順に集めることを検証する。distill_mission_feedback() は
それをLLMで一般則へ蒸留し台帳下書きを生成する層で、retroへの配線自体は
後続タスクの担当(このテストではmission_id/intentを直接渡して呼ぶ)。
"""
from __future__ import annotations

import json

from orgh import planner
from orgh.criteria import append_entry
from orgh.criteria_feedback import (collect_normative_feedback,
                                    distill_mission_feedback)
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


def _fake_ask(response: dict, calls: list):
    def fake(cfg, role, prompt, **kwargs):
        calls.append({"role": role, "prompt": prompt})
        return response
    return fake


class TestDistillMissionFeedback:
    def test_generates_drafts_with_project_slug_hint(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        store = RunStore(cfg["runs_dir"], "m1")
        store.log("task.review", task="t1", passed=False,
                  criteria_cited=[], feedback="acceptanceを満たしていない")
        store.log("owner.interrupt", kind="owner_replan", task="t2",
                  detail="計画自体が曖昧だった")
        calls: list = []
        monkeypatch.setattr(planner, "_ask_json", _fake_ask({
            "proposals": [
                {"category": "design", "prefix": "DESIGN", "strength": "norm",
                 "text": "一般則その1"},
                {"category": "design", "prefix": "DESIGN", "strength": "pref",
                 "text": "一般則その2"},
            ]}, calls))
        workdir = str(tmp_path / "myproj")

        drafts = distill_mission_feedback(cfg, "m1", "筐体UI刷新",
                                          workdir=workdir)

        assert len(drafts) == 2
        for i, fp in enumerate(sorted(drafts)):
            assert fp == tmp_path / "criteria" / "_drafts" / f"m1-{i + 1}.json"
            body = json.loads(fp.read_text())
            assert body["project_slug_hint"] == "myproj"
        assert len(calls) == 1
        assert "acceptanceを満たしていない" in calls[0]["prompt"]
        assert "計画自体が曖昧だった" in calls[0]["prompt"]

    def test_empty_proposals_writes_nothing(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        store = RunStore(cfg["runs_dir"], "m2")
        store.log("task.review", task="t1", passed=False,
                  criteria_cited=[], feedback="この行を直せ")
        monkeypatch.setattr(planner, "_ask_json",
                            _fake_ask({"proposals": []}, []))

        assert distill_mission_feedback(cfg, "m2", "x") == []

    def test_duplicate_of_existing_criteria_is_excluded(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        cdir = tmp_path / "criteria"
        append_entry(cdir, "design", "DESIGN", "norm",
                     "視覚検証なしの合格を信用しない", src="prior")
        cfg["criteria_dir"] = str(cdir)
        store = RunStore(cfg["runs_dir"], "m3")
        store.log("task.review", task="t1", passed=False,
                  criteria_cited=[], feedback="レビュー差し戻し理由")
        monkeypatch.setattr(planner, "_ask_json", _fake_ask({
            "proposals": [
                {"category": "design", "prefix": "DESIGN", "strength": "norm",
                 "text": "  視覚検証なしの合格を信用しない  "},
            ]}, []))

        assert distill_mission_feedback(cfg, "m3", "x") == []

    def test_truncates_to_two_drafts(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        store = RunStore(cfg["runs_dir"], "m4")
        store.log("task.review", task="t1", passed=False,
                  criteria_cited=[], feedback="差し戻し理由")
        monkeypatch.setattr(planner, "_ask_json", _fake_ask({
            "proposals": [
                {"category": "design", "prefix": "DESIGN", "strength": "norm",
                 "text": "一般則A"},
                {"category": "design", "prefix": "DESIGN", "strength": "norm",
                 "text": "一般則B"},
                {"category": "design", "prefix": "DESIGN", "strength": "norm",
                 "text": "一般則C"},
            ]}, []))

        drafts = distill_mission_feedback(cfg, "m4", "x")

        assert len(drafts) == 2
        texts = {json.loads(fp.read_text())["text"] for fp in drafts}
        assert texts == {"一般則A", "一般則B"}

    def test_no_feedback_skips_llm_call(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        calls: list = []
        monkeypatch.setattr(planner, "_ask_json", _fake_ask({
            "proposals": [{"category": "design", "prefix": "DESIGN",
                          "strength": "norm", "text": "呼ばれないはず"}]},
            calls))

        assert distill_mission_feedback(cfg, "no-such-mission", "x") == []
        assert calls == []

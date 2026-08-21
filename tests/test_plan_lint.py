"""計画契約の拡張(visual_quality/decision_gates/kind)とplan lint(機械検査)。

判定はPythonのコードのみで行う(LLMには問い合わせない)。visual_quality=true
なのに先頭タスクが kind="reference"(DESIGN-005の参照=正解仕様作成タスク)で
ない計画は、orgh側で機械的に差し戻す(1回だけ再計画要求)。それでも直らない
場合はミッションを止めて人間へ回す(scheduler側のゲート)。
"""
from __future__ import annotations

import json

from orgh import planner
from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore, build_task

from .conftest import read_ledger


def _plan_json(visual_quality: bool = True, first_kind: str | None = None) -> dict:
    task = {"id": "t1", "title": "x", "prompt": "y",
           "worker": "claude_code", "deps": [], "acceptance": ["z"]}
    if first_kind is not None:
        task["kind"] = first_kind
    return {"tasks": [task], "visual_quality": visual_quality}


class TestLintPlanPureFunction:
    def test_visual_quality_without_reference_head_is_a_violation(self):
        v = planner.lint_plan(_plan_json(visual_quality=True))
        assert len(v) == 1
        assert "DESIGN-005" in v[0]

    def test_visual_quality_with_reference_head_is_clean(self):
        assert planner.lint_plan(
            _plan_json(visual_quality=True, first_kind="reference")) == []

    def test_visual_quality_false_is_always_clean(self):
        assert planner.lint_plan(_plan_json(visual_quality=False)) == []

    def test_empty_tasks_is_not_a_violation(self):
        assert planner.lint_plan({"visual_quality": True, "tasks": []}) == []

    def test_malformed_tasks_is_not_a_violation(self):
        assert planner.lint_plan({"visual_quality": True, "tasks": "oops"}) == []

    def test_missing_visual_quality_key_is_clean(self):
        assert planner.lint_plan({"tasks": [{"id": "t1"}]}) == []


class TestPlanReplanOnViolation:
    def test_ac1_replans_once_then_all_tasks_await_human_on_repeat_violation(
            self, cfg, monkeypatch):
        """AC-1: visual_quality=trueかつ先頭タスクのkindが"reference"でない
        計画は再計画要求が1回行われ、再要求の応答も違反した場合は全タスクが
        awaiting_humanへ遷移する。"""
        calls: list[str] = []

        def fake_ask(cfg_, role, prompt, **kw):
            calls.append(prompt)
            return _plan_json(visual_quality=True)  # 常に違反し続ける
        monkeypatch.setattr(planner, "_ask_json", fake_ask)

        mission = planner.plan(cfg, intent="i", context_digest="c")

        assert len(calls) == 2  # 初回 + 再計画1回のみ(それ以上は要求しない)
        assert "x" in calls[1] and "再計画要求" in calls[1]
        assert mission.plan_lint_violations  # 違反が保持されている

        store = RunStore(cfg["runs_dir"], mission.id)
        run_mission(cfg, mission, store)
        assert all(t.status == "awaiting_human" for t in mission.tasks)
        assert all(t.human_request for t in mission.tasks)
        events = [e["event"] for e in read_ledger(cfg["runs_dir"], mission.id)]
        assert "task.awaiting_human" in events

    def test_ac3_compliant_plan_from_the_start_has_no_violations_no_replan(
            self, cfg, monkeypatch):
        """visual_quality=trueかつ先頭に kind="reference" がある計画は
        違反ゼロで通り、再計画も行われない。"""
        calls: list[str] = []

        def fake_ask(cfg_, role, prompt, **kw):
            calls.append(prompt)
            return _plan_json(visual_quality=True, first_kind="reference")
        monkeypatch.setattr(planner, "_ask_json", fake_ask)

        mission = planner.plan(cfg, intent="i", context_digest="c")

        assert len(calls) == 1
        assert mission.plan_lint_violations == []
        assert mission.tasks[0].kind == "reference"

    def test_replan_that_fixes_the_violation_stops_retrying(
            self, cfg, monkeypatch):
        calls: list[str] = []

        def fake_ask(cfg_, role, prompt, **kw):
            calls.append(prompt)
            if len(calls) == 1:
                return _plan_json(visual_quality=True)  # 初回は違反
            return _plan_json(visual_quality=True, first_kind="reference")
        monkeypatch.setattr(planner, "_ask_json", fake_ask)

        mission = planner.plan(cfg, intent="i", context_digest="c")

        assert len(calls) == 2
        assert mission.plan_lint_violations == []
        assert mission.tasks[0].kind == "reference"


class TestSchedulerGateNoOpWhenClean:
    def test_ac_gate_is_inert_when_no_violations(self, cfg, mock_state_dir,
                                                 tmp_path):
        """plan_lint_violationsが空のときはゲートが一切挙動を変えない
        (通常どおりworkerが起動し完走する)。"""
        mission = Mission.new(
            intent="i", context_digest="c",
            tasks=[{"id": "t1", "title": "x", "prompt": "y[[MARK:t1]]",
                   "worker": "claude_code", "deps": [],
                   "acceptance": ["z"], "workdir": str(tmp_path)}])
        assert mission.plan_lint_violations == []
        store = RunStore(cfg["runs_dir"], mission.id)
        run_mission(cfg, mission, store)
        assert mission.tasks[0].status == "done"


class TestBackwardCompatibility:
    """AC-2: visual_quality/decision_gates/kindを持たない旧形式が例外なく読める。"""

    def test_old_format_plan_json_has_no_new_fields_but_works(
            self, cfg, monkeypatch):
        calls: list[str] = []

        def fake_ask(cfg_, role, prompt, **kw):
            calls.append(prompt)
            # 旧形式: visual_quality/decision_gates/kind を一切含まない
            return {"tasks": [{"id": "t1", "title": "x", "prompt": "y",
                               "worker": "claude_code", "deps": [],
                               "acceptance": ["z"]}]}
        monkeypatch.setattr(planner, "_ask_json", fake_ask)

        mission = planner.plan(cfg, intent="i", context_digest="c")

        assert len(calls) == 1  # 違反なし判定でも再計画は行われない
        assert mission.visual_quality is False
        assert mission.decision_gates == []
        assert mission.plan_lint_violations == []
        assert mission.tasks[0].kind is None

    def test_old_mission_json_without_new_keys_loads_unchanged(
            self, cfg, tmp_path):
        runs_dir = cfg["runs_dir"]
        mission_id = "legacy01"
        old_data = {
            "id": mission_id,
            "intent": "旧形式ミッション",
            "context_digest": "(test)",
            "tasks": [
                {"id": "t1", "title": "旧タスク", "prompt": "p",
                 "worker": "claude_code", "deps": [],
                 "acceptance": ["ok"], "workdir": ".", "status": "done"},
            ],
            "created_at": 0.0,
            "budget": None,
            # visual_quality / decision_gates / plan_lint_violations は無い
        }
        store = RunStore(runs_dir, mission_id)
        (store.dir / "mission.json").write_text(
            json.dumps(old_data, ensure_ascii=False))

        loaded = store.load()

        assert loaded.id == mission_id
        assert loaded.visual_quality is False
        assert loaded.decision_gates == []
        assert loaded.plan_lint_violations == []
        assert loaded.tasks[0].kind is None
        assert loaded.tasks[0].status == "done"


class TestTaskKindCoercion:
    def test_reference_kind_is_preserved(self):
        t = build_task({"id": "t1", "title": "x", "prompt": "y",
                        "kind": "reference"})
        assert t.kind == "reference"

    def test_other_kind_values_are_coerced_to_none(self):
        t = build_task({"id": "t1", "title": "x", "prompt": "y",
                        "kind": "bogus"})
        assert t.kind is None

    def test_missing_kind_defaults_to_none(self):
        t = build_task({"id": "t1", "title": "x", "prompt": "y"})
        assert t.kind is None


class TestDecisionGatesNormalization:
    def test_non_list_input_yields_empty_list(self):
        m = Mission.new(intent="i", context_digest="c",
                        tasks=[{"id": "t1", "title": "x", "prompt": "y"}],
                        decision_gates="not-a-list")
        assert m.decision_gates == []

    def test_valid_gate_is_normalized_and_ids_are_assigned(self):
        m = Mission.new(
            intent="i", context_digest="c",
            tasks=[{"id": "t1", "title": "x", "prompt": "y"}],
            decision_gates=[
                {"question": "どちらにする?", "options": ["A", "B"],
                 "default": "A", "why_human": "好みの問題"},
                {"question": "無ID2件目"},  # id無し→G-2が採番される
            ])
        assert len(m.decision_gates) == 2
        assert m.decision_gates[0]["id"] == "G-1"
        assert m.decision_gates[0]["options"] == ["A", "B"]
        assert m.decision_gates[1]["id"] == "G-2"
        assert m.decision_gates[1]["options"] == []
        assert m.decision_gates[1]["default"] is None

    def test_element_without_question_is_dropped_silently(self):
        m = Mission.new(
            intent="i", context_digest="c",
            tasks=[{"id": "t1", "title": "x", "prompt": "y"}],
            decision_gates=[{"options": ["A"]}, "not-a-dict",
                            {"question": "残る"}])
        assert len(m.decision_gates) == 1
        assert m.decision_gates[0]["question"] == "残る"

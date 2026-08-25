"""計画契約の拡張(model/model_reason)とplan lintでの機械強制。

タスクごとにworkerモデル等級(haiku/sonnet/opus)をPlannerが選べるようにする。
判定はPythonのコードのみで行う(LLMには問い合わせない)。model未指定タスクの
挙動は完全不変(config既定のまま)。実行系(実際のモデル起動)は本タスクの範囲外。
"""
from __future__ import annotations

from pathlib import Path

from orgh import planner

REPO = Path(__file__).resolve().parent.parent


def _plan_json(model: str | None = None, model_reason: str = "") -> dict:
    task = {"id": "t1", "title": "x", "prompt": "y",
           "worker": "claude_code", "deps": [], "acceptance": ["z"]}
    if model is not None:
        task["model"] = model
    if model_reason:
        task["model_reason"] = model_reason
    return {"tasks": [task]}


class TestLintPlanModelReasonRequired:
    def test_model_without_reason_is_a_violation(self):
        v = planner.lint_plan(_plan_json(model="haiku"))
        assert len(v) >= 1
        assert any("model_reason" in x for x in v)

    def test_model_with_reason_is_clean(self):
        assert planner.lint_plan(
            _plan_json(model="haiku", model_reason="定型的な機械編集")) == []

    def test_model_unspecified_is_clean(self):
        assert planner.lint_plan(_plan_json()) == []


class TestLintPlanModelAllowlist:
    def test_model_outside_allowlist_is_a_violation(self):
        v = planner.lint_plan(
            _plan_json(model="gpt-5", model_reason="理由あり"))
        assert len(v) >= 1

    def test_model_in_default_allowlist_is_clean(self):
        for m in ("haiku", "sonnet", "opus"):
            assert planner.lint_plan(
                _plan_json(model=m, model_reason="理由あり")) == []

    def test_custom_allowlist_overrides_default(self):
        v = planner.lint_plan(
            _plan_json(model="opus", model_reason="理由あり"),
            model_allowlist=["haiku", "sonnet"])
        assert len(v) >= 1

    def test_malformed_tasks_is_not_a_violation(self):
        assert planner.lint_plan({"tasks": "oops"}) == []

    def test_empty_tasks_is_not_a_violation(self):
        assert planner.lint_plan({"tasks": []}) == []


class TestPlannerPromptContract:
    def test_prompt_mentions_model_reason_and_note_override(self):
        text = (REPO / "prompts" / "planner.md").read_text()
        assert "model_reason" in text
        assert "worker: haiku" in text

"""A6最小版: acceptanceのAC最小構造化(方向性文書2026-08 §3.1 A6)。

- 文字列配列は {id, text, verify=None, evidence=None} へ正規化される
- 構造化AC(id/text/verify/evidence)は値を保持したまま通る
- id欠落・verify不正値・未知キー混在は矯正される(例外にしない)
- str/dict以外の要素はValueError
- acceptance_lines()は旧形式ACを従来どおり `- <text>` の1行で出す
"""
from __future__ import annotations

import pytest

from orgh.state import Task, acceptance_lines, build_task


def _base(**kw):
    return {"id": "t1", "title": "task t1", "prompt": "do it",
           "worker": "claude_code", "deps": [], "workdir": ".", **kw}


class TestNormalizeStringAcceptance:
    def test_string_array_normalizes_to_ac_struct(self):
        task = build_task(_base(acceptance=["pytestが通る"]))
        assert task.acceptance == [
            {"id": "AC-1", "text": "pytestが通る", "verify": None, "evidence": None}
        ]

    def test_string_array_numbers_ids_from_one(self):
        task = build_task(_base(acceptance=["条件1", "条件2", "条件3"]))
        assert [ac["id"] for ac in task.acceptance] == ["AC-1", "AC-2", "AC-3"]
        assert [ac["text"] for ac in task.acceptance] == ["条件1", "条件2", "条件3"]


class TestStructuredAcceptancePreserved:
    def test_full_struct_keeps_values(self):
        task = build_task(_base(acceptance=[
            {"id": "AC-7", "text": "reportが存在する", "verify": "command",
             "evidence": "`ls report.md`が終了コード0"},
        ]))
        assert task.acceptance == [
            {"id": "AC-7", "text": "reportが存在する", "verify": "command",
             "evidence": "`ls report.md`が終了コード0"},
        ]


class TestCoercion:
    def test_missing_id_gets_numbered(self):
        task = build_task(_base(acceptance=[
            {"text": "条件A"},
            {"text": "条件B"},
        ]))
        assert task.acceptance[0]["id"] == "AC-1"
        assert task.acceptance[1]["id"] == "AC-2"

    def test_invalid_verify_coerced_to_none(self):
        task = build_task(_base(acceptance=[
            {"id": "AC-1", "text": "条件", "verify": "not-a-real-verify"},
        ]))
        assert task.acceptance[0]["verify"] is None

    def test_unknown_keys_dropped(self):
        task = build_task(_base(acceptance=[
            {"id": "AC-1", "text": "条件", "priority": "high", "owner": "x"},
        ]))
        assert task.acceptance == [
            {"id": "AC-1", "text": "条件", "verify": None, "evidence": None}
        ]

    def test_missing_evidence_and_verify_default_to_none(self):
        task = build_task(_base(acceptance=[{"id": "AC-1", "text": "条件"}]))
        assert task.acceptance[0]["verify"] is None
        assert task.acceptance[0]["evidence"] is None

    def test_mixed_str_and_dict_elements(self):
        task = build_task(_base(acceptance=[
            "旧形式の条件",
            {"id": "AC-x", "text": "新形式の条件", "verify": "doc",
             "evidence": "docに記載あり"},
        ]))
        assert task.acceptance == [
            {"id": "AC-1", "text": "旧形式の条件", "verify": None, "evidence": None},
            {"id": "AC-x", "text": "新形式の条件", "verify": "doc",
             "evidence": "docに記載あり"},
        ]

    def test_valid_verify_values_pass_through(self):
        for v in ("test", "command", "visual", "doc"):
            task = build_task(_base(acceptance=[
                {"id": "AC-1", "text": "条件", "verify": v},
            ]))
            assert task.acceptance[0]["verify"] == v


class TestInvalidElements:
    def test_non_str_non_dict_element_raises(self):
        with pytest.raises(ValueError):
            build_task(_base(acceptance=[123]))

    def test_dict_missing_text_raises(self):
        with pytest.raises(ValueError):
            build_task(_base(acceptance=[{"id": "AC-1"}]))


class TestAcceptanceLinesHelper:
    def test_old_string_form_renders_as_dash_text(self):
        task = build_task(_base(acceptance=["旧形式1", "旧形式2"]))
        assert acceptance_lines(task) == "- 旧形式1\n- 旧形式2"

    def test_ac_without_verify_or_evidence_renders_as_dash_text(self):
        task = build_task(_base(acceptance=[{"id": "AC-1", "text": "条件のみ"}]))
        assert acceptance_lines(task) == "- 条件のみ"

    def test_ac_with_verify_renders_id_and_verify(self):
        task = build_task(_base(acceptance=[
            {"id": "AC-1", "text": "条件", "verify": "test", "evidence": "証拠一文"},
        ]))
        line = acceptance_lines(task)
        assert "AC-1" in line
        assert "test" in line
        assert "証拠一文" in line
        assert "条件" in line

    def test_raw_string_acceptance_without_build_task_still_renders(self):
        # REPLAN再設計はbuild_taskを経由せずtask.acceptanceへ直接代入されうる
        # (task_executor.pyのREPLAN分岐)ため、文字列要素も許容する
        task = Task(id="t1", title="t", prompt="p", acceptance=["生の文字列"])
        assert acceptance_lines(task) == "- 生の文字列"

    def test_empty_acceptance_renders_empty_string(self):
        task = build_task(_base(acceptance=[]))
        assert acceptance_lines(task) == ""

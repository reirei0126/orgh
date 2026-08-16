"""Reviewer裁定のAC対応表(ac_verdicts)をledgerへ記録する(b44a7b94/t3)。

- 構造化AC(verify/evidenceを持つAC)を含むタスクでは task.review イベントに
  ac_verdicts が記録され、各要素が id/verdict(pass|fail|not_applicable)/reason
  を持つ
- 文字列配列由来の旧形式ACのみのタスクでは ac_verdicts キー自体が付かない
  (旧形式タスクのledger形状を1バイトも変えないため)
- Reviewerが不正な ac_verdicts(未知のAC ID・verdict値不正・reason欠落)を
  返しても例外にならず、不正要素だけが除去される
"""
from __future__ import annotations

import json

from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore

from .conftest import read_ledger


def _mission(tasks):
    return Mission.new(intent="ac_verdicts試験", context_digest="(test)",
                       tasks=tasks)


def _structured_task(id: str) -> dict:
    return {
        "id": id, "title": f"task {id}",
        "prompt": f"作業せよ [[MARK:{id}]]",
        "worker": "claude_code", "deps": [], "workdir": ".",
        "acceptance": [
            {"id": "AC-1", "text": "pytestが通る", "verify": "command",
             "evidence": "`pytest`が終了コード0"},
            {"id": "AC-2", "text": "READMEを更新する", "verify": "doc",
             "evidence": "README.mdに追記あり"},
        ],
    }


def _legacy_task(id: str) -> dict:
    return {
        "id": id, "title": f"task {id}",
        "prompt": f"作業せよ [[MARK:{id}]]",
        "worker": "claude_code", "deps": [], "workdir": ".",
        "acceptance": ["mock acceptance"],
    }


def _review_events(cfg, mission_id, task_id):
    return [e for e in read_ledger(cfg["runs_dir"], mission_id)
            if e["event"] == "task.review" and e["task"] == task_id]


class TestStructuredAcceptanceRecordsVerdicts:
    def test_ac_verdicts_recorded_for_structured_task(
            self, cfg, mock_state_dir, monkeypatch):
        monkeypatch.setenv("MOCK_REVIEWER_AC_VERDICTS", json.dumps([
            {"id": "AC-1", "verdict": "pass",
             "reason": "pytestを実行し0件失敗を確認した"},
            {"id": "AC-2", "verdict": "pass",
             "reason": "READMEの差分を確認した"},
        ]))
        m = _mission([_structured_task("sv")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "done"
        events = _review_events(cfg, m.id, "sv")
        assert len(events) == 1
        verdicts = events[0]["ac_verdicts"]
        assert len(verdicts) == 2
        for v in verdicts:
            assert set(v) == {"id", "verdict", "reason"}
            assert v["verdict"] in ("pass", "fail", "not_applicable")
            assert v["reason"]
        assert "ac_verdicts_dropped" not in events[0]


class TestLegacyAcceptanceOmitsKey:
    def test_no_ac_verdicts_key_for_string_only_acceptance(
            self, cfg, mock_state_dir):
        m = _mission([_legacy_task("lg")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "done"
        events = _review_events(cfg, m.id, "lg")
        assert len(events) == 1
        assert "ac_verdicts" not in events[0]
        assert "ac_verdicts_dropped" not in events[0]


class TestInvalidAcVerdictsAreSanitized:
    def test_invalid_elements_dropped_without_exception(
            self, cfg, mock_state_dir, monkeypatch):
        monkeypatch.setenv("MOCK_REVIEWER_AC_VERDICTS", json.dumps([
            {"id": "AC-1", "verdict": "pass", "reason": "実際に確認した"},
            {"id": "AC-does-not-exist", "verdict": "pass",
             "reason": "存在しないID"},
            {"id": "AC-2", "verdict": "maybe", "reason": "不正なverdict値"},
            {"id": "AC-2", "verdict": "fail"},  # reason欠落
        ]))
        m = _mission([_structured_task("iv")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "done"  # サニタイズで例外にならずタスクは完了する
        events = _review_events(cfg, m.id, "iv")
        assert len(events) == 1
        assert events[0]["ac_verdicts"] == [
            {"id": "AC-1", "verdict": "pass", "reason": "実際に確認した"},
        ]
        assert events[0]["ac_verdicts_dropped"] == 3

"""mission.settledイベントとagency設定の土台(記帳自動化の第1段階)。

- mission_settled_eventが必須フィールド+outcome/cost_usdを持つこと
- outcomeがdone/failed以外ならValueError
- 同一ミッションから2回イベントを生成するとevent_idが同一になること(冪等)
- scheduler: 全task done終端でoutcome=doneが1件、failedタスクを含む終端で
  outcome=failedが1件発行されること(cancelled/skippedのみの終端では発行しない)
- config.example.yamlにagencyセクションがあり、dry_runの既定がtrue
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orgh import notify
from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore, Task, validate_config

from .conftest import read_ledger

REQUIRED_FIELDS = {"event_type", "event_id", "schema_version", "mission_id",
                   "summary", "ts"}
REPO = Path(__file__).resolve().parent.parent


def _task(id: str = "t1", status: str = "done") -> Task:
    t = Task(id=id, title=f"task {id}", prompt="do it", workdir=".",
             acceptance=["ok"])
    t.status = status
    return t


def _mission(tasks: list[Task], mission_id: str = "m1") -> Mission:
    return Mission(id=mission_id, intent="試験ミッション", context_digest="(test)",
                   tasks=tasks)


class TestEventShape:
    def test_mission_settled_has_required_fields(self):
        m = _mission([_task("t1", "done")])
        event = notify.mission_settled_event(m, "done", 1.234)
        assert REQUIRED_FIELDS <= event.keys()
        assert event["event_type"] == "mission.settled"
        assert event["mission_id"] == "m1"
        assert event["outcome"] == "done"
        assert event["cost_usd"] == 1.234
        assert "task_id" not in event
        assert event["summary"]

    def test_mission_settled_failed_outcome(self):
        m = _mission([_task("t1", "failed")])
        event = notify.mission_settled_event(m, "failed", 0.5)
        assert event["outcome"] == "failed"

    def test_invalid_outcome_raises(self):
        m = _mission([_task("t1", "done")])
        with pytest.raises(ValueError):
            notify.mission_settled_event(m, "cancelled", 0.0)


class TestIdempotency:
    def test_same_mission_settled_event_id_is_stable(self):
        m = _mission([_task("t1", "done")])
        e1 = notify.mission_settled_event(m, "done", 1.0)
        e2 = notify.mission_settled_event(m, "done", 1.0)
        assert e1["event_id"] == e2["event_id"]

    def test_different_missions_have_different_event_ids(self):
        m1 = _mission([_task("t1", "done")], mission_id="ma")
        m2 = _mission([_task("t1", "done")], mission_id="mb")
        e1 = notify.mission_settled_event(m1, "done", 1.0)
        e2 = notify.mission_settled_event(m2, "done", 1.0)
        assert e1["event_id"] != e2["event_id"]


class TestSchedulerIntegration:
    def test_all_done_mission_emits_settled_done(self, cfg, mock_state_dir):
        m = _mission([_task("t1", "pending")], mission_id="msd1")
        m.tasks[0].prompt = "作業せよ [[MARK:t1]]"
        store = RunStore(cfg["runs_dir"], m.id)

        run_mission(cfg, m, store)

        assert all(t.status == "done" for t in m.tasks)
        events = read_ledger(cfg["runs_dir"], m.id)
        settled = [e for e in events if e.get("event_type") == "mission.settled"]
        assert len(settled) == 1
        assert settled[0]["outcome"] == "done"

    def test_failed_task_mission_emits_settled_failed(self, cfg, mock_state_dir,
                                                        monkeypatch):
        # codex(session resume不可)を使う: claude_codeはresumeでフィードバックのみ
        # 再送するため、retry時にMARKが失われMOCK_WORKER_FAILが効かなくなる
        # (retry_prompt()参照)。既存テスト(test_st_scenarios.py)と同じ回避策。
        monkeypatch.setenv("MOCK_WORKER_FAIL", "t1")
        t = _task("t1", "pending")
        t.worker = "codex"
        t.prompt = "作業せよ [[MARK:t1]]"
        m = _mission([t], mission_id="msd2")
        store = RunStore(cfg["runs_dir"], m.id)

        run_mission(cfg, m, store)

        assert any(t.status == "failed" for t in m.tasks)
        events = read_ledger(cfg["runs_dir"], m.id)
        settled = [e for e in events if e.get("event_type") == "mission.settled"]
        assert len(settled) == 1
        assert settled[0]["outcome"] == "failed"

    def test_settlement_outcome_none_for_cancelled_only_mission(self):
        # cancelledのみで終端したミッションは、記帳の対象になる決着が無いため
        # settlement_outcomeがNoneを返し、scheduler側はmission.settledを
        # 発行しない(挙動不変)
        from orgh.orchestrator.scheduler import settlement_outcome

        m = _mission([_task("t1", "cancelled")], mission_id="msd3")
        assert settlement_outcome(m) is None

    def test_settlement_outcome_done_and_failed(self):
        from orgh.orchestrator.scheduler import settlement_outcome

        assert settlement_outcome(_mission([_task("t1", "done"),
                                            _task("t2", "done")])) == "done"
        assert settlement_outcome(_mission([_task("t1", "done"),
                                            _task("t2", "failed")])) == "failed"


class TestAgencyConfig:
    def test_config_example_has_agency_section_with_dry_run_true(self):
        data = yaml.safe_load((REPO / "config.example.yaml").read_text())
        assert "agency" in data
        assert data["agency"]["dry_run"] is True

    def test_agency_section_is_accepted_by_config_validation(self, cfg):
        cfg = {**cfg, "agency": {"dry_run": True, "agents_dir": "private/agents",
                                 "salary_usd": 3.0}}
        validate_config(cfg)  # 例外(未知キー扱い)が出ないこと自体が検証点

    def test_unknown_agency_key_warns_not_raises(self, cfg):
        cfg = {**cfg, "agency": {"dry_run": True, "unknown_key": "x"}}
        with pytest.warns(UserWarning):
            validate_config(cfg)

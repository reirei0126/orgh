"""orgh status <mission_id> --json: 機械可読ペイロードの検証。"""
from __future__ import annotations

import json
import sys

from orgh import cli
from orgh.state import Budget, Mission, RunStore, Task
from orgh.status_json import status_payload

from .conftest import write_config

REQUIRED_KEYS = {"mission_id", "intent", "status", "tasks",
                 "cost_usd", "budget_usd"}
REQUIRED_TASK_KEYS = {"id", "title", "status", "attempts", "worker", "deps"}


def _task(id: str, status: str, worker: str = "claude_code",
          deps: list[str] | None = None, attempts: int = 1) -> Task:
    return Task(id=id, title=f"task {id}", prompt="p", worker=worker,
                deps=deps or [], status=status, attempts=attempts)


def _mission(tasks: list[Task], budget: Budget | None = None) -> Mission:
    return Mission(id="mabc123", intent="status --json試験",
                   context_digest="(test)", tasks=tasks, budget=budget)


class TestStatusPayload:
    def test_payload_is_json_dumpable_with_required_keys(self):
        m = _mission([_task("t1", "done")], budget=Budget(limit_usd=1.0, spent_usd=0.02))
        payload = status_payload(m)
        dumped = json.dumps(payload, ensure_ascii=False)
        reloaded = json.loads(dumped)
        assert REQUIRED_KEYS <= reloaded.keys()
        assert len(payload["tasks"]) == 1
        assert REQUIRED_TASK_KEYS <= payload["tasks"][0].keys()

    def test_status_done_when_all_tasks_done(self):
        m = _mission([_task("t1", "done"), _task("t2", "done")])
        assert status_payload(m)["status"] == "done"

    def test_status_failed_when_any_task_failed(self):
        m = _mission([_task("t1", "done"), _task("t2", "failed")])
        assert status_payload(m)["status"] == "failed"

    def test_status_running_when_neither_all_done_nor_failed(self):
        m = _mission([_task("t1", "done"), _task("t2", "pending")])
        assert status_payload(m)["status"] == "running"

    def test_cost_usd_reflects_budget_spent(self):
        m = _mission([_task("t1", "done")], budget=Budget(limit_usd=5.0, spent_usd=1.23))
        payload = status_payload(m)
        assert payload["cost_usd"] == 1.23
        assert payload["budget_usd"] == 5.0

    def test_cost_usd_defaults_to_zero_without_budget(self):
        m = _mission([_task("t1", "done")], budget=None)
        payload = status_payload(m)
        assert payload["cost_usd"] == 0.0
        assert payload["budget_usd"] is None


class TestStatusJsonCli:
    def test_cli_status_json_outputs_parseable_json(self, cfg, mock_state_dir,
                                                     tmp_path, monkeypatch, capsys):
        m = _mission([_task("t1", "done"), _task("t2", "failed")],
                     budget=Budget(limit_usd=2.0, spent_usd=0.5))
        store = RunStore(cfg["runs_dir"], m.id)
        store.save(m)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "status", m.id, "--json"])
        cli.main()

        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["mission_id"] == m.id
        assert payload["status"] == "failed"
        assert REQUIRED_KEYS <= payload.keys()

    def test_cli_status_without_json_flag_prints_human_summary(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        m = _mission([_task("t1", "done")])
        store = RunStore(cfg["runs_dir"], m.id)
        store.save(m)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "status", m.id])
        cli.main()

        out = capsys.readouterr().out
        assert "mission" in out
        assert out.strip().startswith("mission") or "mission" in out.splitlines()[1]

"""orgh events <mission_id> --json: ledger.jsonlを機械可読で返す契約の検証。"""
from __future__ import annotations

import json
import sys

import pytest

from orgh import cli
from orgh.events_json import events_payload
from orgh.state import Mission, RunStore, Task

from .conftest import write_config


def _mission(mission_id: str) -> Mission:
    return Mission(id=mission_id, intent="events試験", context_digest="(test)",
                   tasks=[Task(id="t1", title="t", prompt="p")])


class TestEventsPayload:
    """events_payload() 単体の純関数としての振る舞い。"""

    def test_returns_all_events_when_under_tail(self, tmp_path):
        store = RunStore(tmp_path / "runs", "m1")
        store.log("task.start", task="t1")
        store.log("task.output", task="t1", ok=True)

        payload = events_payload(tmp_path / "runs", "m1", tail=100)
        assert payload["mission_id"] == "m1"
        assert [e["event"] for e in payload["events"]] == \
            ["task.start", "task.output"]

    def test_tail_limits_to_last_n_events(self, tmp_path):
        store = RunStore(tmp_path / "runs", "m1")
        for i in range(5):
            store.log("task.output", task=f"t{i}")

        payload = events_payload(tmp_path / "runs", "m1", tail=2)
        assert [e["task"] for e in payload["events"]] == ["t3", "t4"]

    def test_default_tail_is_100(self, tmp_path):
        store = RunStore(tmp_path / "runs", "m1")
        for i in range(150):
            store.log("task.output", task=f"t{i}")

        payload = events_payload(tmp_path / "runs", "m1")
        assert len(payload["events"]) == 100
        assert payload["events"][0]["task"] == "t50"
        assert payload["events"][-1]["task"] == "t149"

    def test_broken_lines_are_skipped(self, tmp_path):
        store = RunStore(tmp_path / "runs", "m1")
        store.log("task.start", task="t1")
        ledger = tmp_path / "runs" / "m1" / "ledger.jsonl"
        with open(ledger, "a") as f:
            f.write("{not valid json\n")
        store.log("task.output", task="t1", ok=True)

        payload = events_payload(tmp_path / "runs", "m1")
        assert len(payload["events"]) == 2
        assert [e["event"] for e in payload["events"]] == \
            ["task.start", "task.output"]

    def test_missing_ledger_returns_empty_events(self, tmp_path):
        payload = events_payload(tmp_path / "runs", "no-such-mission")
        assert payload == {"mission_id": "no-such-mission", "events": []}


class TestEventsJsonCli:
    """orgh events <mission_id> --json のCLI経由の契約検証。"""

    def test_cli_events_json_outputs_parseable_json(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        m = _mission("m1")
        store = RunStore(cfg["runs_dir"], m.id)
        store.save(m)
        store.log("task.start", task="t1", worker="claude_code")
        store.log("task.output", task="t1", ok=True, cost=0.01)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "events", m.id, "--json"])
        cli.main()

        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["mission_id"] == m.id
        assert [e["event"] for e in payload["events"]] == \
            ["task.start", "task.output"]

    def test_cli_events_json_respects_tail_option(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        m = _mission("m1")
        store = RunStore(cfg["runs_dir"], m.id)
        store.save(m)
        for i in range(5):
            store.log("task.output", task=f"t{i}")

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "events", m.id,
            "--json", "--tail", "2"])
        cli.main()

        payload = json.loads(capsys.readouterr().out)
        assert [e["task"] for e in payload["events"]] == ["t3", "t4"]

    def test_cli_events_json_errors_on_unknown_mission(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "events", "no-such",
            "--json"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code != 0

        payload = json.loads(capsys.readouterr().out)
        assert "error" in payload

    def test_cli_events_without_json_flag_prints_human_summary(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        m = _mission("m1")
        store = RunStore(cfg["runs_dir"], m.id)
        store.save(m)
        store.log("task.start", task="t1")

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "events", m.id])
        cli.main()

        out = capsys.readouterr().out
        assert "task.start" in out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)


class TestEventShapeValidation:
    """JSONとして妥当でもイベント形でない行(null/[]/{}等)を通さない。
    1行混じるだけでGUI側のLedgerEventデシリアライズが全件失敗するため。"""

    def test_non_event_json_lines_are_skipped(self, tmp_path):
        d = tmp_path / "m1"
        d.mkdir()
        (d / "ledger.jsonl").write_text("\n".join([
            '{"ts": 1.0, "event": "task.start", "task": "t1"}',
            "null",
            "[]",
            "{}",
            '{"ts": "not-a-number", "event": "x"}',
            '{"ts": 2.0, "event": 123}',
            '{"ts": 3.0, "event": "task.output", "ok": true}',
        ]))
        payload = events_payload(tmp_path, "m1")
        assert [e["event"] for e in payload["events"]] == \
            ["task.start", "task.output"]

    def test_tail_on_large_ledger_returns_last_events(self, tmp_path):
        d = tmp_path / "m1"
        d.mkdir()
        lines = [json.dumps({"ts": float(i), "event": f"e{i}", "pad": "x" * 500})
                 for i in range(3000)]
        (d / "ledger.jsonl").write_text("\n".join(lines))
        payload = events_payload(tmp_path, "m1", tail=100)
        assert len(payload["events"]) == 100
        assert payload["events"][-1]["event"] == "e2999"
        assert payload["events"][0]["event"] == "e2900"

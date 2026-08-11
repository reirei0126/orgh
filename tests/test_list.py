"""orgh list: runs配下の全ミッションをid/intent要約/状態/累計コストで一覧する。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from orgh import cli, listing
from orgh.listing import list_missions
from orgh.state import Budget, Mission, RunStore, Task

from .conftest import write_config

REQUIRED_MISSION_KEYS = {"mission_id", "intent", "status", "cost_usd",
                         "tasks_done", "tasks_total"}


def _task(id: str, status: str) -> Task:
    return Task(id=id, title=f"task {id}", prompt="p", worker="claude_code",
                status=status)


def _mk_mission(runs_dir, mission_id: str, intent: str, tasks: list[Task],
                 spent: float = 0.0) -> RunStore:
    m = Mission(id=mission_id, intent=intent, context_digest="(test)",
                tasks=tasks, budget=Budget(limit_usd=None, spent_usd=spent))
    store = RunStore(runs_dir, mission_id)
    store.save(m)
    return store


class TestListMissions:
    def test_returns_all_missions_sorted_by_id(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m2", "二番目", [_task("t1", "done")])
        _mk_mission(runs_dir, "m1", "一番目", [_task("t1", "done")])
        out = list_missions(runs_dir)
        assert [m["mission_id"] for m in out] == ["m1", "m2"]

    def test_status_done_when_all_tasks_done(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "全部完了",
                    [_task("t1", "done"), _task("t2", "done")])
        out = list_missions(runs_dir)
        assert out[0]["status"] == "done"
        assert out[0]["tasks_done"] == 2
        assert out[0]["tasks_total"] == 2

    def test_status_failed_when_any_task_failed(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "一部失敗",
                    [_task("t1", "done"), _task("t2", "failed")])
        out = list_missions(runs_dir)
        assert out[0]["status"] == "failed"

    def test_status_running_when_in_progress(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "進行中",
                    [_task("t1", "done"), _task("t2", "pending")])
        out = list_missions(runs_dir)
        assert out[0]["status"] == "running"

    def test_status_empty_when_no_tasks(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "タスクなし", [])
        out = list_missions(runs_dir)
        assert out[0]["status"] == "empty"

    def test_intent_truncated_over_60_chars(self, tmp_path):
        runs_dir = tmp_path / "runs"
        long_intent = "あ" * 80
        _mk_mission(runs_dir, "m1", long_intent, [_task("t1", "done")])
        out = list_missions(runs_dir)
        assert len(out[0]["intent"]) == 61  # 60文字 + "…"
        assert out[0]["intent"].endswith("…")
        assert out[0]["intent"][:60] == long_intent[:60]

    def test_intent_short_not_truncated(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "短い意図", [_task("t1", "done")])
        out = list_missions(runs_dir)
        assert out[0]["intent"] == "短い意図"
        assert "…" not in out[0]["intent"]

    def test_intent_newlines_replaced_with_space(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "一行目\n二行目", [_task("t1", "done")])
        out = list_missions(runs_dir)
        assert "\n" not in out[0]["intent"]
        assert out[0]["intent"] == "一行目 二行目"

    def test_cost_usd_from_budget(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "コスト確認", [_task("t1", "done")],
                    spent=1.2345)
        out = list_missions(runs_dir)
        assert out[0]["cost_usd"] == 1.2345

    def test_cost_usd_zero_when_no_budget(self, tmp_path):
        runs_dir = tmp_path / "runs"
        m = Mission(id="m1", intent="予算なし", context_digest="(test)",
                    tasks=[_task("t1", "done")], budget=None)
        store = RunStore(runs_dir, "m1")
        store.save(m)
        out = list_missions(runs_dir)
        assert out[0]["cost_usd"] == 0.0

    def test_missing_runs_dir_returns_empty_list(self, tmp_path):
        assert list_missions(tmp_path / "does-not-exist") == []

    def test_broken_mission_dir_is_skipped_others_returned(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "正常ミッション", [_task("t1", "done")])
        broken = runs_dir / "m0-broken"
        broken.mkdir(parents=True)
        (broken / "mission.json").write_text("{not valid json")
        out = list_missions(runs_dir)
        assert [m["mission_id"] for m in out] == ["m1"]

    def test_broken_mission_reported_in_skipped(self, tmp_path):
        # 破損mission.jsonの黙殺は「0件」とデータ消失を区別不能にするため、
        # skippedとしてパスと理由が返る契約
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "正常ミッション", [_task("t1", "done")])
        broken = runs_dir / "m0-broken"
        broken.mkdir(parents=True)
        (broken / "mission.json").write_text("{not valid json")
        payload = listing.list_missions_report(runs_dir)
        assert [m["mission_id"] for m in payload["missions"]] == ["m1"]
        assert len(payload["skipped"]) == 1
        assert payload["skipped"][0]["path"].endswith("m0-broken/mission.json")
        assert payload["skipped"][0]["reason"]

    def test_status_awaiting_approval_when_any_task_awaiting(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "承認待ち",
                    [_task("t1", "awaiting_approval"), _task("t2", "pending")])
        out = list_missions(runs_dir)
        assert out[0]["status"] == "awaiting_approval"

    def test_status_cancelled_when_all_terminal_but_not_all_done(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "キャンセル済み",
                    [_task("t1", "done"), _task("t2", "cancelled"),
                     _task("t3", "skipped")])
        out = list_missions(runs_dir)
        assert out[0]["status"] == "cancelled"

    def test_status_awaiting_human_when_any_task_awaiting(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "人間対応待ち",
                    [_task("t1", "awaiting_human"), _task("t2", "pending")])
        out = list_missions(runs_dir)
        assert out[0]["status"] == "awaiting_human"

    def test_status_awaiting_approval_takes_precedence_over_awaiting_human(
            self, tmp_path):
        # status_json.status_payload と同一の優先順位規則(awaiting_approval優先)
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "両方待ち",
                    [_task("t1", "awaiting_approval"),
                     _task("t2", "awaiting_human")])
        out = list_missions(runs_dir)
        assert out[0]["status"] == "awaiting_approval"

    def test_dir_without_mission_json_is_skipped(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "正常ミッション", [_task("t1", "done")])
        (runs_dir / "not-a-mission").mkdir(parents=True)
        out = list_missions(runs_dir)
        assert [m["mission_id"] for m in out] == ["m1"]


class TestListJsonCli:
    """GUI連携用: orgh list --json が単一JSONをstdoutへ出す契約の検証。"""

    def test_cli_list_json_outputs_parseable_json_with_required_keys(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        m = Mission(id="m1", intent="一覧試験", context_digest="(test)",
                    tasks=[_task("t1", "done")],
                    budget=Budget(limit_usd=None, spent_usd=0.5))
        RunStore(cfg["runs_dir"], m.id).save(m)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "list", "--json"])
        cli.main()

        out = capsys.readouterr().out
        payload = json.loads(out)
        assert "missions" in payload
        assert len(payload["missions"]) == 1
        assert REQUIRED_MISSION_KEYS <= payload["missions"][0].keys()
        assert payload["missions"][0]["mission_id"] == "m1"

    def test_cli_list_json_empty_when_no_missions(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "list", "--json"])
        cli.main()

        payload = json.loads(capsys.readouterr().out)
        assert payload == {"missions": [], "skipped": []}

    def test_cli_list_without_json_flag_prints_human_summary(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        m = Mission(id="m1", intent="一覧試験", context_digest="(test)",
                    tasks=[_task("t1", "done")])
        RunStore(cfg["runs_dir"], m.id).save(m)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "list"])
        cli.main()

        out = capsys.readouterr().out
        assert "m1" in out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)


class TestDateOrderAndTimestamps:
    """一覧は起票日時の新しい順(id順はランダム16進で意味が無い)。
    起票=ledger最初のイベントts、完了=終端ミッションの最後のmission.finished ts。"""

    def _mk_with_ledger(self, runs_dir, mid, status, events):
        import json as _json
        d = runs_dir / mid
        d.mkdir(parents=True)
        (d / "mission.json").write_text(_json.dumps({
            "id": mid, "intent": mid, "context_digest": "",
            "tasks": [{"id": "t1", "title": "x", "prompt": "p",
                       "worker": "claude_code", "deps": [],
                       "status": status, "attempts": 1}],
            "budget": None}))
        (d / "ledger.jsonl").write_text(
            "\n".join(_json.dumps(e) for e in events))

    def test_sorted_by_created_desc(self, tmp_path):
        runs = tmp_path / "runs"
        self._mk_with_ledger(runs, "aaa-old", "done", [
            {"ts": 1000.0, "event": "task.start", "task": "t1"},
            {"ts": 1500.0, "event": "mission.finished", "done": ["t1"]}])
        self._mk_with_ledger(runs, "zzz-new", "done", [
            {"ts": 9000.0, "event": "task.start", "task": "t1"},
            {"ts": 9500.0, "event": "mission.finished", "done": ["t1"]}])
        out = list_missions(runs)
        assert [m["mission_id"] for m in out] == ["zzz-new", "aaa-old"]
        assert out[0]["created_ts"] == 9000.0
        assert out[0]["finished_ts"] == 9500.0

    def test_finished_ts_uses_last_mission_finished(self, tmp_path):
        # ガード停止時の早期mission.finishedではなく最後を採る(report.pyと同一規則)
        runs = tmp_path / "runs"
        self._mk_with_ledger(runs, "mguard", "done", [
            {"ts": 100.0, "event": "task.awaiting_approval", "task": "t1"},
            {"ts": 101.0, "event": "mission.finished", "done": []},
            {"ts": 200.0, "event": "task.start", "task": "t1"},
            {"ts": 900.0, "event": "mission.finished", "done": ["t1"]}])
        out = list_missions(runs)
        assert out[0]["created_ts"] == 100.0
        assert out[0]["finished_ts"] == 900.0

    def test_running_mission_has_null_finished(self, tmp_path):
        runs = tmp_path / "runs"
        self._mk_with_ledger(runs, "mrun", "running", [
            {"ts": 100.0, "event": "task.start", "task": "t1"},
            {"ts": 101.0, "event": "mission.finished", "done": []}])
        out = list_missions(runs)
        assert out[0]["finished_ts"] is None

    def test_missing_ledger_sorts_last(self, tmp_path):
        import json as _json
        runs = tmp_path / "runs"
        self._mk_with_ledger(runs, "with-ledger", "done", [
            {"ts": 50.0, "event": "task.start", "task": "t1"},
            {"ts": 60.0, "event": "mission.finished", "done": ["t1"]}])
        d = runs / "no-ledger"
        d.mkdir(parents=True)
        (d / "mission.json").write_text(_json.dumps({
            "id": "no-ledger", "intent": "x", "context_digest": "",
            "tasks": [], "budget": None}))
        out = list_missions(runs)
        assert [m["mission_id"] for m in out] == ["with-ledger", "no-ledger"]
        assert out[1]["created_ts"] is None

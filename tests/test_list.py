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

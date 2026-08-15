"""orgh verdict <id> --fail による escape イベント記録。

機械ゲート(全タスクdone)を通過したミッションが後からownerに不合格判定された
事例を、集計可能な生データとして ledger に残す
(docs/strategy/direction-2026-08.md §3.4 A4 / §10 Done when A4)。

記録するのは件数の元データ(mission_id/reason/対象タスク/category)のみ。
率の算出・失効候補の提示・抜き打ち検査は行わない(§3.4 の「当面やらない」)。
"""
from __future__ import annotations

import json
import sys

from orgh import cli
from orgh.state import Mission, RunStore, Task

from .conftest import read_ledger, write_config


def _task(id: str, status: str) -> Task:
    return Task(id=id, title=f"task {id}", prompt="p", worker="claude_code",
                status=status)


def _mk_mission(runs_dir, mission_id: str, intent: str,
                tasks: list[Task]) -> RunStore:
    m = Mission(id=mission_id, intent=intent, context_digest="(test)",
                tasks=tasks)
    store = RunStore(runs_dir, mission_id)
    store.save(m)
    return store


def _run_fail_verdict(cfg, tmp_path, monkeypatch, mission_id: str,
                       reason: str, category: str | None = None) -> None:
    cfg_path = write_config(tmp_path, cfg)
    argv = ["orgh", "--config", str(cfg_path), "verdict", mission_id,
            "--fail", "--reason", reason]
    if category is not None:
        argv += ["--category", category]
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()


def _escape_events(cfg, mission_id: str) -> list[dict]:
    return [e for e in read_ledger(cfg["runs_dir"], mission_id)
            if e["event"] == "escape"]


class TestEscapeRecordedOnGatePassedFail:
    def test_all_done_mission_fail_records_escape_with_category(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        monkeypatch.setenv("MOCK_CRITERIA_JSON", json.dumps({"proposals": []}))
        _mk_mission(cfg["runs_dir"], "m1", "検収通過後に差し戻し",
                    [_task("t1", "done"), _task("t2", "done")])

        _run_fail_verdict(cfg, tmp_path, monkeypatch, "m1",
                          reason="配色が仕様と違う", category="visual")

        events = _escape_events(cfg, "m1")
        assert len(events) == 1
        ev = events[0]
        assert ev["mission_id"] == "m1"
        assert ev["reason"] == "配色が仕様と違う"
        assert sorted(ev["tasks"]) == ["t1", "t2"]
        assert ev["category"] == "visual"

    def test_category_omitted_defaults_to_other(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        monkeypatch.setenv("MOCK_CRITERIA_JSON", json.dumps({"proposals": []}))
        _mk_mission(cfg["runs_dir"], "m1", "検収通過後に差し戻し",
                    [_task("t1", "done")])

        _run_fail_verdict(cfg, tmp_path, monkeypatch, "m1",
                          reason="前提が崩れていた")

        events = _escape_events(cfg, "m1")
        assert len(events) == 1
        assert events[0]["category"] == "other"


class TestEscapeNotRecordedWhenGateNotPassed:
    def test_undone_task_remaining_does_not_record_escape(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        monkeypatch.setenv("MOCK_CRITERIA_JSON", json.dumps({"proposals": []}))
        _mk_mission(cfg["runs_dir"], "m1", "未完了タスクあり",
                    [_task("t1", "done"), _task("t2", "failed")])

        _run_fail_verdict(cfg, tmp_path, monkeypatch, "m1",
                          reason="そもそも未完了", category="premise")

        assert _escape_events(cfg, "m1") == []
        # 既存挙動(mission.owner_verdict自体は記録される)は変わらない
        ledger = read_ledger(cfg["runs_dir"], "m1")
        assert any(e["event"] == "mission.owner_verdict" for e in ledger)

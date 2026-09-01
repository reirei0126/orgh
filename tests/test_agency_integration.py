"""mission.settledから記帳(agency)への配線の受け入れテスト(このタスクの対象)。

配線点は orgh/orchestrator/scheduler.py の mission.settled 発行直後
(agency.on_settled呼び出し)。ここでは実際に run_mission() を回し、
scheduler → notify.mission_settled_event → agency.on_settled の配線全体を
検証する(agency.on_settled単体の挙動は tests/test_agency_ledger.py が
既に持っているため、ここでは重複させない)。

台帳は cwd(=tmp_path。tests/conftest.py の _isolate_cwd で隔離済み)配下の
private/agents/agent-001/economy-ledger.md に作る偽物であり、
リポジトリ本物の private/agents/ には一切触れない
(agency.on_settledのrepo_root既定=Path.cwd())。

ミッション受け入れ条件との対応:
- AC-1: TestDryRun
- AC-2: TestWrite
- AC-3: TestIdempotent
- AC-4: TestNoDrafter, TestFailed
"""
from __future__ import annotations

import pathlib

import pytest

from orgh import agency, notify
from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore, Task

from .conftest import read_ledger

LEDGER_SAMPLE = """# 試験用経済台帳

| 日付 | 種別 | 金額 | 残高 | 摘要 |
|---|---|---|---|---|
| 2026-08-24 | 付与 | +30.0 | 30.000 | 初期残高 |
"""


def _task(id: str = "t1", worker: str = "claude_code") -> Task:
    return Task(id=id, title=f"task {id}", prompt=f"作業せよ [[MARK:{id}]]",
               worker=worker, workdir=".", acceptance=["ok"])


def _mission(tasks: list[Task], mission_id: str,
            drafter_line: str | None = "起案: 田中和臣(agent-001)\n") -> Mission:
    digest = "# ミッション\n" + (drafter_line or "") + "本文...\n"
    return Mission(id=mission_id, intent="試験ミッション", context_digest=digest,
                  tasks=tasks)


def _agency_cfg(cfg: dict, dry_run: bool, salary_usd: float = 3.0) -> dict:
    return {**cfg, "agency": {"dry_run": dry_run, "agents_dir": "private/agents",
                              "salary_usd": salary_usd}}


def _write_ledger(agent_id: str = "agent-001") -> pathlib.Path:
    d = pathlib.Path("private") / "agents" / agent_id
    d.mkdir(parents=True)
    p = d / "economy-ledger.md"
    p.write_text(LEDGER_SAMPLE, encoding="utf-8")
    return p


def _settled_event(events: list[dict]) -> dict:
    settled = [e for e in events if e.get("event_type") == "mission.settled"]
    assert len(settled) == 1, f"mission.settledがちょうど1件発行されること: {settled}"
    return settled[0]


def _by_event(events: list[dict], name: str) -> list[dict]:
    return [e for e in events if e.get("event") == name]


class TestDryRun:
    """AC-1: done遷移でmission.settledが発行され、dry_run=trueならledgerに
    agency.would_writeのみが記録され台帳ファイルが変化しない。"""

    def test_done_dry_run_would_write_only_and_ledger_unchanged(
            self, cfg, mock_state_dir):
        path = _write_ledger()
        before = path.read_bytes()
        cfg2 = _agency_cfg(cfg, dry_run=True)
        m = _mission([_task("t1")], "aidry1")
        store = RunStore(cfg2["runs_dir"], m.id)

        run_mission(cfg2, m, store)

        assert all(t.status == "done" for t in m.tasks)
        events = read_ledger(cfg2["runs_dir"], m.id)
        settled = _settled_event(events)

        would = _by_event(events, "agency.would_write")
        recorded = _by_event(events, "agency.recorded")
        assert len(would) == 1
        assert recorded == []
        assert would[0]["event_id"] == settled["event_id"]
        assert would[0]["agent"] == "agent-001"
        assert len(would[0]["rows"]) == 2  # 支出行+給料行(done)

        assert path.read_bytes() == before  # 台帳ファイルは1バイトも変わらない

    def test_dry_run_default_true_when_agency_key_missing(
            self, cfg, mock_state_dir):
        """agency.dry_runキー欠落時もfail-safeでtrue扱い(挙動不変)。"""
        path = _write_ledger()
        before = path.read_bytes()
        m = _mission([_task("t1")], "aidry2")
        store = RunStore(cfg["runs_dir"], m.id)

        run_mission(cfg, m, store)

        events = read_ledger(cfg["runs_dir"], m.id)
        assert len(_by_event(events, "agency.would_write")) == 1
        assert _by_event(events, "agency.recorded") == []
        assert path.read_bytes() == before


class TestWrite:
    """AC-2: dry_run=falseで支出行+給料行(+3.0)が正しい残高計算で追記される。"""

    def test_done_dry_run_false_appends_spend_and_salary_rows(
            self, cfg, mock_state_dir):
        path = _write_ledger()
        cfg2 = _agency_cfg(cfg, dry_run=False, salary_usd=3.0)
        m = _mission([_task("t1")], "aiwrite1")
        store = RunStore(cfg2["runs_dir"], m.id)

        run_mission(cfg2, m, store)

        events = read_ledger(cfg2["runs_dir"], m.id)
        settled = _settled_event(events)
        recorded = _by_event(events, "agency.recorded")
        assert len(recorded) == 1
        assert len(recorded[0]["rows"]) == 2

        text = path.read_text(encoding="utf-8")
        assert text.startswith(LEDGER_SAMPLE)  # 既存行・ヘッダは不変(追記のみ)

        cost_usd = settled["cost_usd"]
        after_spend = round(30.0 - cost_usd, 3)
        after_salary = round(after_spend + 3.0, 3)
        new_rows = text.splitlines()[-2:]
        assert "| 支出 |" in new_rows[0]
        assert "| 給料 |" in new_rows[1]
        assert agency.parse_last_balance(text) == after_salary
        assert new_rows == recorded[0]["rows"]


class TestIdempotent:
    """AC-3: 同一event_idの再発火(on_settledの再呼び出し)で行数が増えない。"""

    def test_same_event_id_replay_does_not_duplicate_rows(
            self, cfg, mock_state_dir):
        path = _write_ledger()
        cfg2 = _agency_cfg(cfg, dry_run=False)
        m = _mission([_task("t1")], "aiidem1")
        store = RunStore(cfg2["runs_dir"], m.id)

        run_mission(cfg2, m, store)
        after_first = path.read_bytes()
        events_after_first = read_ledger(cfg2["runs_dir"], m.id)
        assert len(_by_event(events_after_first, "agency.recorded")) == 1

        cost_usd = _settled_event(events_after_first)["cost_usd"]
        replay_event = notify.mission_settled_event(m, "done", cost_usd)
        agency.on_settled(store, cfg2, m, replay_event, date="2026-09-02")

        assert path.read_bytes() == after_first  # 台帳ファイルは変化しない

        events = read_ledger(cfg2["runs_dir"], m.id)
        assert len(_by_event(events, "agency.recorded")) == 1  # 増えない
        dup_skips = [e for e in _by_event(events, "agency.skipped")
                    if e.get("reason") == "duplicate"]
        assert len(dup_skips) == 1


class TestNoDrafter:
    """AC-4a: 起案行のないミッションでは台帳ファイルが変化しない。"""

    def test_no_drafter_mission_leaves_ledger_untouched(
            self, cfg, mock_state_dir):
        path = _write_ledger()
        before = path.read_bytes()
        cfg2 = _agency_cfg(cfg, dry_run=False)  # dry_run=falseでも起案者未解決なら不変
        m = _mission([_task("t1")], "aidraft1", drafter_line=None)
        store = RunStore(cfg2["runs_dir"], m.id)

        run_mission(cfg2, m, store)

        assert path.read_bytes() == before
        events = read_ledger(cfg2["runs_dir"], m.id)
        _settled_event(events)  # mission.settled自体は発行される
        no_drafter = [e for e in _by_event(events, "agency.skipped")
                     if e.get("reason") == "no_drafter"]
        assert len(no_drafter) == 1
        assert _by_event(events, "agency.would_write") == []
        assert _by_event(events, "agency.recorded") == []


class TestFailed:
    """AC-4b: failed時は支出行のみが追記され、給料行が追記されない。"""

    def test_failed_mission_appends_spend_row_only(
            self, cfg, mock_state_dir, monkeypatch):
        path = _write_ledger()
        before_balance = agency.parse_last_balance(LEDGER_SAMPLE)
        # codex(session resume不可)を使う: retry時にMARKが失われる
        # claude_code+resumeのケースを避ける(test_agency_settled.pyと同じ回避策)
        monkeypatch.setenv("MOCK_WORKER_FAIL", "t1")
        cfg2 = _agency_cfg(cfg, dry_run=False)
        m = _mission([_task("t1", worker="codex")], "aifail1")
        store = RunStore(cfg2["runs_dir"], m.id)

        run_mission(cfg2, m, store)

        assert any(t.status == "failed" for t in m.tasks)
        events = read_ledger(cfg2["runs_dir"], m.id)
        settled = _settled_event(events)
        assert settled["outcome"] == "failed"

        recorded = _by_event(events, "agency.recorded")
        assert len(recorded) == 1
        assert len(recorded[0]["rows"]) == 1
        assert "| 支出 |" in recorded[0]["rows"][0]
        assert "給料" not in recorded[0]["rows"][0]

        text = path.read_text(encoding="utf-8")
        expected = round(before_balance - settled["cost_usd"], 3)
        assert agency.parse_last_balance(text) == expected

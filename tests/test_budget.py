"""HANDOFF タスク2: 予算ガード。

- Budget: ルートで確保した共有プールを親から子へ分割して参照渡しするモデル
  (将来のサブミッション再帰の前提)。charge()は親へ伝播する
- ミッション上限超過: 実行中の完了は待つが未着手はdispatchせずskippedにして停止
- タスク上限超過: そのタスクをfailedにして次のattemptに進まない
- 予算を上げれば orgh resume で続行できる
- Planner/Reviewer/Retro のコストも累計に含める(モックは1呼び出し0.01 USD)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from orgh import executor, cli, watcher
from orgh.orchestrator import run_mission
from orgh.state import Budget, Mission, RunStore

from .conftest import age, mission_dirs, read_calls, read_ledger, write_config


def _task(id: str, deps: list[str] | None = None) -> dict:
    return {"id": id, "title": f"task {id}",
            "prompt": f"作業せよ [[MARK:{id}]]",
            "worker": "claude_code", "deps": deps or [],
            "acceptance": ["mock acceptance"], "workdir": "."}


def _mission(tasks: list[dict]) -> Mission:
    return Mission.new(intent="budget試験", context_digest="(test)",
                       tasks=tasks)


class TestBudgetObject:
    """再帰前提の共有プール契約。"""

    def test_charge_and_exceeded(self):
        b = Budget(limit_usd=1.0)
        b.charge(0.4)
        assert not b.exceeded()
        b.charge(0.6)
        assert b.exceeded()
        assert b.spent_usd == 1.0

    def test_child_charge_propagates_to_parent(self):
        root = Budget(limit_usd=1.0)
        child = root.split(limit_usd=0.4)
        child.charge(0.5)
        assert root.spent_usd == 0.5   # 親プールから減る(掛け算にならない)
        assert child.exceeded()        # 子の割当を超過
        assert not root.exceeded()

    def test_parent_exhaustion_stops_child(self):
        root = Budget(limit_usd=1.0)
        child = root.split(limit_usd=0.8)
        root.charge(1.0)               # 兄弟等がプールを使い切った
        assert not child.spent_usd
        assert child.exceeded()        # 親経由で停止する

    def test_unlimited_by_default(self):
        b = Budget()
        b.charge(9999)
        assert not b.exceeded()
        assert b.remaining() is None


class TestMissionBudget:
    def test_exceeded_skips_undispatched_and_stops(self, cfg, mock_state_dir):
        # モックは1呼び出し0.01 USD。t1完走で worker+review=0.02 >= 0.015
        cfg["loop"]["budget_usd"] = 0.015
        m = _mission([_task("t1"), _task("t2", deps=["t1"])])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        by_id = {t.id: t for t in m.tasks}
        assert by_id["t1"].status == "done"       # 実行中の完了は待つ
        assert by_id["t2"].status == "skipped"    # 未着手はdispatchしない
        assert not any(c["marker"] == "t2" for c in read_calls(mock_state_dir))
        assert any(e["event"] == "mission.budget_exceeded"
                   for e in read_ledger(cfg["runs_dir"], m.id))
        # 消費が永続化されている
        data = json.loads((store.dir / "mission.json").read_text())
        assert data["budget"]["spent_usd"] >= 0.015

    def test_resume_with_raised_budget_continues(self, cfg, mock_state_dir,
                                                 tmp_path, monkeypatch):
        cfg["loop"]["budget_usd"] = 0.015
        m = _mission([_task("t1"), _task("t2", deps=["t1"])])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert {t.status for t in m.tasks} == {"done", "skipped"}

        cfg["loop"]["budget_usd"] = 1.0            # 予算を上げてresume
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "resume", m.id])
        cli.main()

        reloaded = store.load()
        assert [t.status for t in reloaded.tasks] == ["done", "done"]

    def test_no_budget_keys_keeps_current_behavior(self, cfg, mock_state_dir):
        m = _mission([_task("t1"), _task("t2")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))
        assert all(t.status == "done" for t in m.tasks)


class TestTaskBudget:
    def test_task_over_budget_fails_without_next_attempt(self, cfg,
                                                         mock_state_dir,
                                                         monkeypatch):
        # attempt1のworkerコスト0.01が上限0.005を超過 → review前にfailed
        cfg["loop"]["task_budget_usd"] = 0.005
        monkeypatch.setenv("MOCK_REJECT_ONCE", "t1")  # 本来なら2周するタスク
        m = _mission([_task("t1")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        t = m.tasks[0]
        assert t.status == "failed"
        assert t.attempts == 1                     # 次のattemptに進まない
        assert "予算" in t.review_notes
        calls = read_calls(mock_state_dir)
        assert not any(c["role"] == "reviewer" for c in calls)
        assert any(e["event"] == "task.budget_exceeded"
                   for e in read_ledger(cfg["runs_dir"], m.id))


class TestRoleCostsCounted:
    def test_planner_reviewer_retro_costs_in_total(self, wcfg, vault,
                                                   one_pass, mock_state_dir):
        wcfg["loop"]["budget_usd"] = 10.0
        note = vault / "inbox" / "ミッション.md"
        note.write_text("やること #go\n")
        age(note)
        watcher.watch(wcfg)          # 検知・計画・投入(R-1分離)
        executor.drain(wcfg)         # キュー消化=ミッション実行

        [mdir] = mission_dirs(wcfg["runs_dir"])
        data = json.loads((mdir / "mission.json").read_text())
        # planner 0.01 + worker 0.01 + reviewer 0.01 + retro 0.01
        assert abs(data["budget"]["spent_usd"] - 0.04) < 1e-9


class TestStatusShowsBudget:
    def test_status_prints_cost_and_ratio(self, cfg, mock_state_dir, tmp_path,
                                          monkeypatch, capsys):
        cfg["loop"]["budget_usd"] = 1.0
        m = _mission([_task("t1")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "status", m.id])
        cli.main()
        out = capsys.readouterr().out
        assert "USD" in out
        assert "%" in out       # 予算消化率

"""HANDOFF タスク7a: orgh report(ledger集計)と context_digest の保存。

- 初回attempt合格率と差し戻し率の週次時系列(増幅の実在を示す最重要メトリクス)
- ミッション別コスト・所要時間
- worker別の失敗率
- --vault で vault/orgh/reports/<date>.md にも書き出す
- Plannerに渡した context_digest を runs/<id>/artifacts/context_digest.md に必ず保存
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

from orgh import cli, report
from orgh.orchestrator import run_mission
from orgh.state import Budget, Mission, RunStore, Task

from .conftest import write_config


# 2026-07-06(W28月曜)/ 2026-07-13(W29月曜)12:00 のts(ローカルtz非依存の週判定)
_W28 = datetime(2026, 7, 6, 12, 0).timestamp()
_W29 = datetime(2026, 7, 13, 12, 0).timestamp()


def _write_ledger(store: RunStore, events: list[dict]) -> None:
    with open(store.dir / "ledger.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _mk_mission(cfg, mission_id: str, tasks: list[Task], created_at: float,
                spent: float) -> RunStore:
    m = Mission(id=mission_id, intent=f"試験ミッション{mission_id}",
                context_digest="(test)", tasks=tasks, created_at=created_at,
                budget=Budget(limit_usd=None, spent_usd=spent))
    store = RunStore(cfg["runs_dir"], mission_id)
    store.save(m)
    return store


def _task(id: str, worker: str, status: str) -> Task:
    return Task(id=id, title=f"task {id}", prompt="p", worker=worker,
                status=status)


def _seed_runs(cfg) -> None:
    """2ミッション分の合成データ。
    W28: t1初回合格 / t2一度差し戻し→合格(codex側worker) → 初回合格率50%
    W29: t3初回合格(codexはfailed) → claude初回合格率100%
    """
    s1 = _mk_mission(cfg, "m1", [_task("t1", "claude_code", "done"),
                                 _task("t2", "claude_code", "done")],
                     created_at=_W28, spent=0.04)
    _write_ledger(s1, [
        {"ts": _W28, "event": "watch.triggered"},
        {"ts": _W28 + 1, "event": "task.start", "task": "t1", "worker": "claude_code", "attempt": 1},
        {"ts": _W28 + 5, "event": "task.review", "task": "t1", "passed": True},
        {"ts": _W28 + 1, "event": "task.start", "task": "t2", "worker": "claude_code", "attempt": 1},
        {"ts": _W28 + 6, "event": "task.review", "task": "t2", "passed": False},
        {"ts": _W28 + 7, "event": "task.start", "task": "t2", "worker": "claude_code", "attempt": 2},
        {"ts": _W28 + 9, "event": "task.review", "task": "t2", "passed": True},
        {"ts": _W28 + 60, "event": "mission.finished", "done": ["t1", "t2"], "failed": []},
    ])
    s2 = _mk_mission(cfg, "m2", [_task("t3", "claude_code", "done"),
                                 _task("t4", "codex", "failed")],
                     created_at=_W29, spent=0.02)
    _write_ledger(s2, [
        {"ts": _W29, "event": "watch.triggered"},
        {"ts": _W29 + 1, "event": "task.start", "task": "t3", "worker": "claude_code", "attempt": 1},
        {"ts": _W29 + 4, "event": "task.review", "task": "t3", "passed": True},
        {"ts": _W29 + 1, "event": "task.start", "task": "t4", "worker": "codex", "attempt": 1},
        {"ts": _W29 + 30, "event": "mission.finished", "done": ["t3"], "failed": ["t4"]},
    ])


class TestReport:
    def test_weekly_first_pass_and_rework_rates(self, cfg, mock_state_dir):
        _seed_runs(cfg)
        out = report.build_report(cfg)
        # W28: 初回合格1/2=50%、差し戻し1/2=50%。W29: 初回合格1/1=100%
        assert "2026-W28" in out and "2026-W29" in out
        w28 = next(l for l in out.splitlines() if "2026-W28" in l)
        assert "50%" in w28
        w29 = next(l for l in out.splitlines() if "2026-W29" in l)
        assert "100%" in w29

    def test_mission_cost_and_duration(self, cfg, mock_state_dir):
        _seed_runs(cfg)
        out = report.build_report(cfg)
        m1 = next(l for l in out.splitlines() if "m1" in l)
        assert "0.04" in m1 and "USD" in m1
        assert "60" in m1  # 所要時間(最初のイベント〜mission.finished = 60s)

    def test_worker_failure_rates(self, cfg, mock_state_dir):
        _seed_runs(cfg)
        out = report.build_report(cfg)
        codex = next(l for l in out.splitlines()
                     if l.strip().startswith("- codex"))
        assert "100%" in codex        # codexは1/1 failed
        claude = next(l for l in out.splitlines()
                      if l.strip().startswith("- claude_code"))
        assert "0%" in claude

    def test_days_filter_excludes_old_missions(self, cfg, mock_state_dir):
        _seed_runs(cfg)
        # 現在からdays日以内のみ。W28/W29は過去日付なので0件になる
        out = report.build_report(cfg, days=1)
        assert "m1" not in out and "m2" not in out

    def test_cli_vault_option_writes_note(self, cfg, mock_state_dir, tmp_path,
                                          monkeypatch):
        _seed_runs(cfg)
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg["vault"] = {"path": str(vault)}
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "report", "--vault"])
        cli.main()

        reports = list((vault / "orgh" / "reports").glob("*.md"))
        assert len(reports) == 1
        body = reports[0].read_text()
        assert "2026-W28" in body and "m1" in body


class TestContextDigestSaved:
    def test_run_mission_persists_context_digest(self, cfg, mock_state_dir):
        m = Mission.new(intent="digest試験", context_digest="監査用ダイジェスト本文",
                        tasks=[{"id": "t1", "title": "task t1",
                                "prompt": "作業せよ [[MARK:t1]]",
                                "worker": "claude_code", "deps": [],
                                "acceptance": ["a"], "workdir": "."}])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        fp = store.dir / "artifacts" / "context_digest.md"
        assert fp.exists()
        assert "監査用ダイジェスト本文" in fp.read_text()

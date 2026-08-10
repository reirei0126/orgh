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

import pytest
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


class TestDurationWithGuardStop:
    def test_duration_uses_last_mission_finished(self, cfg, mock_state_dir):
        # 自己改変ガード停止時にもmission.finishedが記録されるため、最初の
        # イベントを拾うとapprove経由の実行時間が0sになる回帰テスト
        import json as _json
        from pathlib import Path as _P
        from orgh import report as _report
        runs = _P(cfg["runs_dir"])
        d = runs / "mg1"
        d.mkdir(parents=True)
        (d / "mission.json").write_text(_json.dumps({
            "id": "mg1", "intent": "ガード停止→approve", "context_digest": "",
            "tasks": [{"id": "t1", "title": "x", "prompt": "p",
                       "worker": "claude_code", "deps": [], "status": "done",
                       "attempts": 1}],
            "budget": {"limit_usd": None, "spent_usd": 1.0}}))
        (d / "ledger.jsonl").write_text("\n".join([
            _json.dumps({"ts": 1000.0, "event": "watch.triggered"}),
            _json.dumps({"ts": 1001.0, "event": "task.awaiting_approval", "task": "t1"}),
            _json.dumps({"ts": 1002.0, "event": "mission.finished", "done": []}),
            _json.dumps({"ts": 2000.0, "event": "task.start", "task": "t1"}),
            _json.dumps({"ts": 4600.0, "event": "mission.finished", "done": ["t1"]}),
        ]))
        out = _report.build_report(cfg)
        line = next(l for l in out.splitlines() if "mg1" in l)
        assert "duration=3600s" in line


class TestReportJson:
    """P1-2(desktop/API.md §1.6): orgh report --days N --json。

    テキスト版と同じ集計関数(_load_missions/_weekly_stats/_worker_stats)を
    再利用し、数値が食い違わないことを担保する。
    """

    def test_report_payload_is_json_dumpable_with_days_echoed(self, cfg,
                                                               mock_state_dir):
        _seed_runs(cfg)
        payload = report.report_payload(cfg, days=30)
        json.dumps(payload, ensure_ascii=False)  # 例外を出さない
        assert payload["days"] == 30

    def test_weekly_matches_text_report_values(self, cfg, mock_state_dir):
        _seed_runs(cfg)
        payload = report.report_payload(cfg, days=None)
        w28 = next(w for w in payload["weekly"] if w["week"] == "2026-W28")
        assert w28["total"] == 2
        assert w28["first_pass"] == 1 and w28["first_pass_pct"] == 50
        assert w28["rework"] == 1 and w28["rework_pct"] == 50
        w29 = next(w for w in payload["weekly"] if w["week"] == "2026-W29")
        assert w29["first_pass_pct"] == 100
        # テキスト版と同じ昇順
        assert [w["week"] for w in payload["weekly"]] == sorted(
            w["week"] for w in payload["weekly"])

    def test_missions_full_intent_not_truncated(self, cfg, mock_state_dir):
        _seed_runs(cfg)
        payload = report.report_payload(cfg, days=None)
        m1 = next(m for m in payload["missions"] if m["mission_id"] == "m1")
        assert m1["intent"] == "試験ミッションm1"
        assert m1["cost_usd"] == 0.04
        assert m1["duration_sec"] == 60
        assert m1["tasks_done"] == 2 and m1["tasks_total"] == 2

    def test_workers_sorted_and_pct_matches_text(self, cfg, mock_state_dir):
        _seed_runs(cfg)
        payload = report.report_payload(cfg, days=None)
        assert [w["worker"] for w in payload["workers"]] == ["claude_code", "codex"]
        codex = next(w for w in payload["workers"] if w["worker"] == "codex")
        assert codex["failed"] == 1 and codex["total"] == 1
        assert codex["failed_pct"] == 100

    def test_worker_none_excluded_and_no_typeerror(self, cfg, mock_state_dir):
        """テキスト版 _worker_stats はworker未割当(None)も辞書に入れるため
        sorted()がNoneと文字列の比較でTypeErrorになりうる既知の潜在バグが
        あるが、JSON版はこれを踏襲せず除外して正しく動作する。"""
        d = Path(cfg["runs_dir"]) / "m3"
        d.mkdir(parents=True)
        (d / "mission.json").write_text(json.dumps({
            "id": "m3", "intent": "worker未割当タスクを含む", "context_digest": "",
            "tasks": [{"id": "t1", "title": "x", "prompt": "p", "worker": None,
                      "deps": [], "status": "pending", "attempts": 0}],
            "budget": {"limit_usd": None, "spent_usd": 0.0}}))
        (d / "ledger.jsonl").write_text(json.dumps(
            {"ts": 1000.0, "event": "watch.triggered"}) + "\n")

        payload = report.report_payload(cfg, days=None)  # 例外を出さない
        assert None not in [w["worker"] for w in payload["workers"]]

    def test_empty_when_no_missions_in_range(self, cfg, mock_state_dir):
        _seed_runs(cfg)
        payload = report.report_payload(cfg, days=1)
        assert payload == {"days": 1, "weekly": [], "missions": [], "workers": []}

    def test_cli_report_json_outputs_single_json_object(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        _seed_runs(cfg)
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "report", "--days", "365",
            "--json"])
        cli.main()
        out = capsys.readouterr().out
        payload = json.loads(out)  # stdoutは単一JSONオブジェクトのみ
        assert payload["days"] == 365
        assert any(m["mission_id"] == "m1" for m in payload["missions"])

    def test_cli_report_without_json_flag_unchanged(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        _seed_runs(cfg)
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "report"])
        cli.main()
        out = capsys.readouterr().out
        assert "# orgh report" in out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)

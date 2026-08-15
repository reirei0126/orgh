"""done だが owner verdict (orgh verdict) が未実施のミッションを再発見する導線。

通知が届かなくても人間が拾えるように、一覧・専用CLIサブコマンドの両方から
確認できることを検証する(docs/strategy/direction-2026-08.md §7 Phase 1 完了条件④)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from orgh import cli, listing
from orgh.listing import list_pending_verdicts
from orgh.state import Budget, Mission, RunStore, Task

from .conftest import write_config


def _task(id: str, status: str) -> Task:
    return Task(id=id, title=f"task {id}", prompt="p", worker="claude_code",
                status=status)


def _mk_mission(runs_dir, mission_id: str, intent: str,
                 tasks: list[Task]) -> RunStore:
    m = Mission(id=mission_id, intent=intent, context_digest="(test)",
                tasks=tasks, budget=Budget(limit_usd=None, spent_usd=0.0))
    store = RunStore(runs_dir, mission_id)
    store.save(m)
    return store


def _mk_done_mission_with_ledger(runs_dir, mission_id: str, intent: str,
                                   spent: float, created_ts: float,
                                   finished_ts: float) -> RunStore:
    """cost_usd / tasks_done / created_ts / finished_ts が全て埋まる
    doneミッションを作る(orgh list と orgh verdict --pending の情報密度を
    比較するテスト用)。"""
    d = Path(runs_dir) / mission_id
    d.mkdir(parents=True)
    (d / "mission.json").write_text(json.dumps({
        "id": mission_id, "intent": intent, "context_digest": "",
        "tasks": [{"id": "t1", "title": "x", "prompt": "p",
                   "worker": "claude_code", "deps": [],
                   "status": "done", "attempts": 1}],
        "budget": {"limit_usd": None, "spent_usd": spent}}))
    (d / "ledger.jsonl").write_text("\n".join(json.dumps(e) for e in [
        {"ts": created_ts, "event": "task.start", "task": "t1"},
        {"ts": finished_ts, "event": "mission.finished", "done": ["t1"]}]))
    return RunStore(runs_dir, mission_id)


def _record_verdict(store: RunStore, passed: bool, reason: str) -> None:
    with open(store.dir / "verdicts.jsonl", "a") as f:
        f.write(json.dumps({"ts": 1.0, "passed": passed, "reason": reason},
                            ensure_ascii=False) + "\n")


class TestListPendingVerdicts:
    def test_done_mission_without_verdict_is_pending(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "検収待ち", [_task("t1", "done")])
        out = list_pending_verdicts(runs_dir)
        assert [m["mission_id"] for m in out["missions"]] == ["m1"]
        assert out["missions"][0]["verdict_pending"] is True

    def test_done_mission_with_verdict_is_not_pending(self, tmp_path):
        runs_dir = tmp_path / "runs"
        store = _mk_mission(runs_dir, "m1", "検収済み", [_task("t1", "done")])
        _record_verdict(store, passed=True, reason="良い")
        out = list_pending_verdicts(runs_dir)
        assert out["missions"] == []

    def test_non_done_mission_is_not_pending(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "進行中", [_task("t1", "pending")])
        out = list_pending_verdicts(runs_dir)
        assert out["missions"] == []

    def test_failed_mission_is_not_pending(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "失敗",
                    [_task("t1", "done"), _task("t2", "failed")])
        out = list_pending_verdicts(runs_dir)
        assert out["missions"] == []

    def test_mixed_missions_only_pending_done_returned(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "検収待ち", [_task("t1", "done")])
        verdicted = _mk_mission(runs_dir, "m2", "検収済み", [_task("t1", "done")])
        _record_verdict(verdicted, passed=False, reason="やり直し")
        _mk_mission(runs_dir, "m3", "進行中", [_task("t1", "pending")])
        out = list_pending_verdicts(runs_dir)
        assert [m["mission_id"] for m in out["missions"]] == ["m1"]

    def test_missing_runs_dir_returns_empty(self, tmp_path):
        out = list_pending_verdicts(tmp_path / "does-not-exist")
        assert out["missions"] == []


class TestVerdictPendingCli:
    def test_cli_json_lists_pending_and_excludes_verdicted(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        _mk_mission(cfg["runs_dir"], "m1", "検収待ち", [_task("t1", "done")])
        verdicted = _mk_mission(cfg["runs_dir"], "m2", "検収済み",
                                 [_task("t1", "done")])
        _record_verdict(verdicted, passed=True, reason="良い")

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "verdict", "--pending",
            "--json"])
        cli.main()

        payload = json.loads(capsys.readouterr().out)
        ids = [m["mission_id"] for m in payload["missions"]]
        assert ids == ["m1"]

    def test_cli_text_output_shows_mission_id_and_pending_marker(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        _mk_mission(cfg["runs_dir"], "m1", "検収待ち", [_task("t1", "done")])

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "verdict", "--pending"])
        cli.main()

        out = capsys.readouterr().out
        assert "m1" in out
        assert "verdict" in out.lower() or "未実施" in out

    def test_cli_text_output_matches_list_info_density(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        """レビュー指摘対応: cost_usd/tasks/起票/完了の情報密度を orgh list と
        揃え、優先順位付けに必要な情報が --pending 出力から欠落しないこと。"""
        _mk_done_mission_with_ledger(cfg["runs_dir"], "m1", "密度確認",
                                      spent=1.2345, created_ts=1000.0,
                                      finished_ts=1500.0)
        cfg_path = write_config(tmp_path, cfg)

        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "list"])
        cli.main()
        list_out = capsys.readouterr().out

        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "verdict", "--pending"])
        cli.main()
        pending_out = capsys.readouterr().out

        for token in ("1.2345 USD", "1/1 tasks", "起票", "完了"):
            assert token in list_out, f"{token!r} missing from `orgh list`"
            assert token in pending_out, (
                f"{token!r} missing from `orgh verdict --pending`")
        assert "未実施" in pending_out
        # 角括弧内の状況ラベルだけがlistと異なる(statusが"done"のまま
        # 出るのはverdict未実施という主目的を隠してしまうため)
        assert "[done]" in list_out
        assert "[verdict未実施]" in pending_out

    def test_cli_text_output_empty_when_no_pending(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "verdict", "--pending"])
        cli.main()

        out = capsys.readouterr().out
        assert "m1" not in out

    def test_existing_verdict_pass_fail_flow_still_works(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        """--pending 追加が既存の orgh verdict <id> --pass/--fail を壊さないこと。"""
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        m = Mission.new(intent="回帰確認", context_digest="(test)", tasks=[])
        store = RunStore(cfg["runs_dir"], m.id)
        store.save(m)
        monkeypatch.setenv("MOCK_CRITERIA_JSON", json.dumps({"proposals": []}))

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "verdict", m.id,
            "--pass", "--reason", "問題なし"])
        cli.main()

        verdicts = [json.loads(l) for l in
                    (store.dir / "verdicts.jsonl").read_text().splitlines()]
        assert len(verdicts) == 1
        assert verdicts[0]["passed"] is True

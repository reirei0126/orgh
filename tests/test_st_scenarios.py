"""STシナリオ固定化(HANDOFF タスク0a)。

①正常系(並列+依存) ②改善ループ(1差し戻し→resume合格)
③失敗系(上限超過→failed、依存タスクはpending停止) ④resume --retry-failed
モックバイナリ(tests/mocks/)でclaude/codexのheadless契約を模す。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from orgh import cli
from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore

from .conftest import read_calls, read_ledger, write_config


def _mission(tasks: list[dict]) -> Mission:
    return Mission.new(intent="STテスト", context_digest="(test)", tasks=tasks)


def _store(cfg: dict, mission: Mission) -> RunStore:
    return RunStore(cfg["runs_dir"], mission.id)


def _task(id: str, worker: str = "claude_code", deps: list[str] | None = None) -> dict:
    return {
        "id": id, "title": f"task {id}",
        "prompt": f"作業せよ [[MARK:{id}]]",
        "worker": worker, "deps": deps or [],
        "acceptance": ["mock acceptance"], "workdir": ".",
    }


class TestNormalParallelWithDeps:
    """① 並列2タスク + 依存1タスクが全て完走する。"""

    def test_all_done(self, cfg, mock_state_dir):
        m = _mission([_task("t1"), _task("t2", worker="codex"),
                      _task("t3", deps=["t1", "t2"])])
        store = _store(cfg, m)
        run_mission(cfg, m, store)

        assert [t.status for t in m.tasks] == ["done", "done", "done"]
        assert all(t.attempts == 1 for t in m.tasks)

    def test_dependent_starts_after_deps_done(self, cfg, mock_state_dir):
        m = _mission([_task("t1"), _task("t2", worker="codex"),
                      _task("t3", deps=["t1", "t2"])])
        run_mission(cfg, m, _store(cfg, m))

        ledger = read_ledger(cfg["runs_dir"], m.id)
        start_idx = {e["task"]: i for i, e in enumerate(ledger)
                     if e["event"] == "task.start"}
        review_idx = {e["task"]: i for i, e in enumerate(ledger)
                      if e["event"] == "task.review" and e["passed"]}
        # t3の着手はt1/t2の合格より後
        assert start_idx["t3"] > review_idx["t1"]
        # t2(codex)はレビューなし経路ではなくreview通過を経る
        assert start_idx["t3"] > review_idx["t2"]

    def test_persisted_mission_json_matches(self, cfg, mock_state_dir):
        m = _mission([_task("t1")])
        run_mission(cfg, m, _store(cfg, m))

        data = json.loads(
            (Path(cfg["runs_dir"]) / m.id / "mission.json").read_text())
        assert data["id"] == m.id
        assert [t["status"] for t in data["tasks"]] == ["done"]

    def test_both_adapters_invoked(self, cfg, mock_state_dir):
        m = _mission([_task("t1"), _task("t2", worker="codex")])
        run_mission(cfg, m, _store(cfg, m))

        calls = read_calls(mock_state_dir)
        assert any(c.get("worker") == "codex" and c["marker"] == "t2"
                   for c in calls)
        assert any(c["role"] == "worker" and c["marker"] == "t1" for c in calls)


class TestImprovementLoop:
    """② レビュー1差し戻し → 同一セッションにresumeして合格。"""

    def test_reject_once_then_pass(self, cfg, mock_state_dir, monkeypatch):
        monkeypatch.setenv("MOCK_REJECT_ONCE", "tr")
        m = _mission([_task("tr")])
        run_mission(cfg, m, _store(cfg, m))

        t = m.tasks[0]
        assert t.status == "done"
        assert t.attempts == 2

        reviews = [e["passed"] for e in read_ledger(cfg["runs_dir"], m.id)
                   if e["event"] == "task.review"]
        assert reviews == [False, True]

    def test_second_attempt_resumes_same_session(self, cfg, mock_state_dir,
                                                 monkeypatch):
        monkeypatch.setenv("MOCK_REJECT_ONCE", "tr")
        m = _mission([_task("tr")])
        run_mission(cfg, m, _store(cfg, m))

        worker_calls = [c for c in read_calls(mock_state_dir)
                        if c["role"] == "worker" and c["marker"] == "tr"]
        assert len(worker_calls) == 2
        assert worker_calls[0]["resume"] is None
        assert worker_calls[1]["resume"] == worker_calls[0]["session_id"]


class TestFailurePath:
    """③ 差し戻し上限超過 → failed。依存タスクはpendingのまま停止。"""

    def test_exhausts_attempts_then_failed(self, cfg, mock_state_dir,
                                           monkeypatch):
        monkeypatch.setenv("MOCK_REVIEW_ALWAYS_FAIL", "ta")
        m = _mission([_task("ta"), _task("tb"), _task("tc", deps=["ta"])])
        run_mission(cfg, m, _store(cfg, m))

        by_id = {t.id: t for t in m.tasks}
        assert by_id["ta"].status == "failed"
        assert by_id["ta"].attempts == cfg["loop"]["max_attempts"]
        assert by_id["tb"].status == "done"      # 兄弟は完走
        assert by_id["tc"].status == "pending"   # 依存は着手されず停止

        finished = [e for e in read_ledger(cfg["runs_dir"], m.id)
                    if e["event"] == "mission.finished"]
        assert finished and finished[-1]["failed"] == ["ta"]

    def test_dependent_never_dispatched(self, cfg, mock_state_dir, monkeypatch):
        monkeypatch.setenv("MOCK_REVIEW_ALWAYS_FAIL", "ta")
        m = _mission([_task("ta"), _task("tc", deps=["ta"])])
        run_mission(cfg, m, _store(cfg, m))

        assert not any(c["marker"] == "tc" for c in read_calls(mock_state_dir))


class TestResumeRetryFailed:
    """④ orgh resume --retry-failed で failed タスクが再実行され完走する。"""

    def test_cli_resume_retry_failed(self, cfg, mock_state_dir, monkeypatch,
                                     tmp_path, capsys):
        monkeypatch.setenv("MOCK_REVIEW_ALWAYS_FAIL", "ta")
        m = _mission([_task("ta"), _task("tc", deps=["ta"])])
        store = _store(cfg, m)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "failed"

        # 原因(常時fail)を解消してCLI経由でresume
        monkeypatch.delenv("MOCK_REVIEW_ALWAYS_FAIL")
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "resume", m.id, "--retry-failed"])
        cli.main()

        reloaded = RunStore(cfg["runs_dir"], m.id).load()
        assert [t.status for t in reloaded.tasks] == ["done", "done"]
        # attemptsリセット後の再実行が1回で通っている
        assert reloaded.tasks[0].attempts == 1

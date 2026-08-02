"""HANDOFF 0b: 耐障害性コアの受け入れテスト。

- resume時の状態正規化(running/queued/review → pending)
- タイムアウト捕捉(TimeoutExpired → failed、兄弟タスクは完走)
- 例外隔離(1タスクの異常がミッションを道連れにしない)
- アトミック永続化 + kill -9 → mission.json破損なし → resumeで完走
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore

from .conftest import read_ledger

REPO = Path(__file__).resolve().parent.parent
CHILD = str(REPO / "tests" / "helpers" / "run_mission_child.py")


def _task(id: str, worker: str = "claude_code", deps: list[str] | None = None,
          prompt: str | None = None) -> dict:
    return {
        "id": id, "title": f"task {id}",
        "prompt": prompt or f"作業せよ [[MARK:{id}]]",
        "worker": worker, "deps": deps or [],
        "acceptance": ["mock acceptance"], "workdir": ".",
    }


def _mission(tasks: list[dict]) -> Mission:
    return Mission.new(intent="resilience試験", context_digest="(test)",
                       tasks=tasks)


class TestLoadNormalization:
    """クラッシュ後のロードで実行中系ステータスがpendingに巻き戻る。"""

    def test_inflight_statuses_rollback_to_pending(self, cfg, mock_state_dir):
        m = _mission([_task("a"), _task("b"), _task("c"), _task("d")])
        m.tasks[0].status = "running"
        m.tasks[1].status = "queued"
        m.tasks[2].status = "review"
        m.tasks[3].status = "done"
        store = RunStore(cfg["runs_dir"], m.id)
        store.save(m)

        loaded = store.load()
        assert [t.status for t in loaded.tasks] == [
            "pending", "pending", "pending", "done"]


class TestTimeout:
    """タイムアウトするタスクがfailedになり、兄弟タスクは完走する。"""

    def test_timeout_task_failed_sibling_done(self, cfg, mock_state_dir,
                                              monkeypatch):
        monkeypatch.setenv("MOCK_SLEEP_ALL", "5")  # claudeワーカーのみ5秒眠る
        cfg["loop"]["task_timeout"] = 1
        m = _mission([_task("tt", worker="claude_code"),
                      _task("tb", worker="codex")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        by_id = {t.id: t for t in m.tasks}
        assert by_id["tt"].status == "failed"
        assert "timeout" in by_id["tt"].last_output
        assert by_id["tb"].status == "done"

        outs = [e for e in read_ledger(cfg["runs_dir"], m.id)
                if e["event"] == "task.output" and e["task"] == "tt"]
        assert outs and all(not e["ok"] for e in outs)


class TestExceptionIsolation:
    """アダプタ例外(存在しないバイナリ等)が該当タスクのfailedに閉じる。"""

    def test_bad_binary_isolated_to_task(self, cfg, mock_state_dir):
        cfg["workers"]["claude_code"]["bin"] = "/nonexistent/claude-mock-xyz"
        m = _mission([_task("te", worker="claude_code"),
                      _task("tb", worker="codex")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        by_id = {t.id: t for t in m.tasks}
        assert by_id["te"].status == "failed"
        assert by_id["tb"].status == "done"
        # ledgerに異常記録が残る
        assert any(e["event"] == "task.error" and e["task"] == "te"
                   for e in read_ledger(cfg["runs_dir"], m.id))


class TestAtomicPersistence:
    def test_save_leaves_no_tmp_files(self, cfg, mock_state_dir):
        m = _mission([_task("t1")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        leftovers = [p for p in store.dir.iterdir() if ".tmp" in p.name]
        assert leftovers == []


class TestKillNineResume:
    """実行中プロセスをkill -9 → mission.jsonが破損せず、resumeで完走する。"""

    def test_kill9_then_resume_completes(self, cfg, mock_state_dir, tmp_path,
                                         monkeypatch):
        mission_id = "killtest"
        tasks = [
            _task("k1"),
            _task("k2", prompt="長い作業 [[MARK:k2]] [[SLEEP:30]]"),
            _task("k3", deps=["k2"]),
        ]
        spec = tmp_path / "spec.json"
        spec.write_text(json.dumps(
            {"cfg": cfg, "mission_id": mission_id, "tasks": tasks},
            ensure_ascii=False))

        # cwdはリポ外(tmp)にする: workdir "." がorghリポを指すと自己改変ガード対象
        proc = subprocess.Popen([sys.executable, CHILD, str(spec)],
                                cwd=str(tmp_path),
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        try:
            # k1が完了しk2が実行中(SLEEP中)になるまで待つ
            deadline = time.time() + 20
            while time.time() < deadline:
                ledger = read_ledger(cfg["runs_dir"], mission_id)
                k1_passed = any(e["event"] == "task.review"
                                and e["task"] == "k1" and e["passed"]
                                for e in ledger)
                k2_started = any(e["event"] == "task.start"
                                 and e["task"] == "k2" for e in ledger)
                if k1_passed and k2_started:
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("child process never reached k2 start")
            time.sleep(0.2)  # k1完了後のsave(mission.json更新)を確実に跨ぐ
        finally:
            proc.send_signal(signal.SIGKILL)
            proc.wait(timeout=10)

        # mission.jsonが破損していない
        mission_json = Path(cfg["runs_dir"]) / mission_id / "mission.json"
        data = json.loads(mission_json.read_text())
        assert data["id"] == mission_id

        # resume: 実行中だったk2はpendingに巻き戻り、完走できる
        store = RunStore(cfg["runs_dir"], mission_id)
        loaded = store.load()
        by_id = {t.id: t for t in loaded.tasks}
        assert by_id["k1"].status == "done"
        assert by_id["k2"].status == "pending"

        monkeypatch.setenv("MOCK_NO_SLEEP", "1")
        run_mission(cfg, loaded, store)
        assert all(t.status == "done" for t in loaded.tasks)

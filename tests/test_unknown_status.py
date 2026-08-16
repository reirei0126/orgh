"""実行中系タスク(queued/running/review)を抱えたままleaseが失効している
ミッションの表示: orgh/lease.py の失効判定に基づき、orgh list / orgh status
(JSON・テキストいずれも)で "unknown" として出ることの単体試験。

pending/failedへ丸めない(二重実行・成果喪失の誤誘導を防ぐ)ことと、
lease生存中は実状態(running等)のまま表示され、決してpendingへ偽装
されないことを併せて固定する。時刻はすべてnow=引数で注入し、実時間の
sleepには依存しない。
"""
from __future__ import annotations

import json
import sys
import time

from orgh import cli, lease, listing
from orgh.listing import list_missions
from orgh.state import Budget, Mission, RunStore, Task
from orgh.status_json import status_payload

from .conftest import write_config


def _task(id: str, status: str) -> Task:
    return Task(id=id, title=f"task {id}", prompt="p", worker="claude_code",
                status=status)


def _mission(mission_id: str, tasks: list[Task]) -> Mission:
    return Mission(id=mission_id, intent="unknown表示試験",
                   context_digest="(test)", tasks=tasks,
                   budget=Budget(limit_usd=None, spent_usd=0.0))


class TestListShowsUnknownForExpiredLease:
    def test_running_mission_with_expired_lease_is_unknown(self, tmp_path):
        runs_dir = tmp_path / "runs"
        store = RunStore(runs_dir, "m1")
        store.save(_mission("m1", [_task("t1", "running"),
                                    _task("t2", "pending")]))
        stale = time.time() - lease.LEASE_EXPIRY_SEC - 1
        lease.acquire(store.dir, now=stale)

        out = list_missions(runs_dir)
        assert out[0]["status"] == "unknown"

    def test_review_task_with_expired_lease_is_unknown(self, tmp_path):
        runs_dir = tmp_path / "runs"
        store = RunStore(runs_dir, "m1")
        store.save(_mission("m1", [_task("t1", "review")]))
        stale = time.time() - lease.LEASE_EXPIRY_SEC - 1
        lease.acquire(store.dir, now=stale)

        out = list_missions(runs_dir)
        assert out[0]["status"] == "unknown"

    def test_alive_lease_keeps_running_not_pending(self, tmp_path):
        runs_dir = tmp_path / "runs"
        store = RunStore(runs_dir, "m1")
        store.save(_mission("m1", [_task("t1", "running"),
                                    _task("t2", "pending")]))
        now = time.time()
        lease.acquire(store.dir, now=now)

        out = list_missions(runs_dir)
        assert out[0]["status"] == "running"
        assert out[0]["status"] != "pending"

    def test_no_lease_at_all_is_not_forced_to_unknown(self, tmp_path):
        # lease.py導入前の旧ミッション等、lease自体が無い場合は判定材料が
        # 無いだけであり、rawステータス由来の導出結果(running)をそのまま通す
        runs_dir = tmp_path / "runs"
        store = RunStore(runs_dir, "m1")
        store.save(_mission("m1", [_task("t1", "running")]))

        out = list_missions(runs_dir)
        assert out[0]["status"] == "running"

    def test_queued_mission_with_no_inflight_task_is_not_unknown(
            self, tmp_path):
        # 全タスクpending+キューエントリ = "queued"。実際にはまだ何も
        # 動いていないのでleaseが無くても/失効していてもunknownにしない
        runs_dir = tmp_path / "runs"
        store = RunStore(runs_dir, "m1")
        store.save(_mission("m1", [_task("t1", "pending")]))
        (runs_dir / "_queue").mkdir(parents=True)
        (runs_dir / "_queue" / "m1.json").write_text("{}")

        out = list_missions(runs_dir)
        assert out[0]["status"] == "queued"

    def test_cli_list_json_shows_unknown(self, cfg, mock_state_dir, tmp_path,
                                          monkeypatch, capsys):
        store = RunStore(cfg["runs_dir"], "m1")
        store.save(_mission("m1", [_task("t1", "running")]))
        stale = time.time() - lease.LEASE_EXPIRY_SEC - 1
        lease.acquire(store.dir, now=stale)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "list", "--json"])
        cli.main()

        payload = json.loads(capsys.readouterr().out)
        assert payload["missions"][0]["status"] == "unknown"

    def test_cli_list_text_shows_unknown(self, cfg, mock_state_dir, tmp_path,
                                          monkeypatch, capsys):
        store = RunStore(cfg["runs_dir"], "m1")
        store.save(_mission("m1", [_task("t1", "running")]))
        stale = time.time() - lease.LEASE_EXPIRY_SEC - 1
        lease.acquire(store.dir, now=stale)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "list"])
        cli.main()

        out = capsys.readouterr().out
        assert "[unknown]" in out


class TestStatusJsonShowsUnknownForExpiredLease:
    def test_mission_and_task_status_become_unknown(self, cfg, mock_state_dir):
        store = RunStore(cfg["runs_dir"], "m1")
        m = _mission("m1", [_task("t1", "running"), _task("t2", "pending")])
        store.save(m)
        stale = time.time() - lease.LEASE_EXPIRY_SEC - 1
        lease.acquire(store.dir, now=stale)

        reloaded = store.load(reset_inflight=False)
        payload = status_payload(reloaded, cfg)
        assert payload["status"] == "unknown"
        assert payload["tasks"][0]["status"] == "unknown"
        # 未着手のt2はそのままpending(丸めない)
        assert payload["tasks"][1]["status"] == "pending"

    def test_alive_lease_keeps_running_not_pending(self, cfg, mock_state_dir):
        store = RunStore(cfg["runs_dir"], "m1")
        m = _mission("m1", [_task("t1", "running")])
        store.save(m)
        now = time.time()
        lease.acquire(store.dir, now=now)

        reloaded = store.load(reset_inflight=False)
        payload = status_payload(reloaded, cfg)
        assert payload["status"] == "running"
        assert payload["tasks"][0]["status"] == "running"
        assert payload["status"] != "pending"
        assert payload["tasks"][0]["status"] != "pending"

    def test_no_lease_at_all_is_not_forced_to_unknown(self, cfg,
                                                       mock_state_dir):
        # レガシー動作の固定: cfg付きでもlease自体が無ければrawのrunningを
        # そのまま通す(TestStatusShowsInflightTruthfullyの既存契約と同一)
        store = RunStore(cfg["runs_dir"], "m1")
        m = _mission("m1", [_task("t1", "running")])
        store.save(m)

        reloaded = store.load(reset_inflight=False)
        payload = status_payload(reloaded, cfg)
        assert payload["status"] == "running"
        assert payload["tasks"][0]["status"] == "running"

    def test_cli_status_json_shows_unknown(self, cfg, mock_state_dir,
                                            tmp_path, monkeypatch, capsys):
        store = RunStore(cfg["runs_dir"], "m1")
        store.save(_mission("m1", [_task("t1", "running")]))
        stale = time.time() - lease.LEASE_EXPIRY_SEC - 1
        lease.acquire(store.dir, now=stale)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "status", "m1", "--json"])
        cli.main()

        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "unknown"
        assert payload["tasks"][0]["status"] == "unknown"

    def test_cli_status_text_shows_unknown(self, cfg, mock_state_dir,
                                            tmp_path, monkeypatch, capsys):
        store = RunStore(cfg["runs_dir"], "m1")
        store.save(_mission("m1", [_task("t1", "running")]))
        stale = time.time() - lease.LEASE_EXPIRY_SEC - 1
        lease.acquire(store.dir, now=stale)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "status", "m1"])
        cli.main()

        out = capsys.readouterr().out
        assert "[unknown]" in out

    def test_cli_status_text_keeps_running_when_lease_alive(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        store = RunStore(cfg["runs_dir"], "m1")
        store.save(_mission("m1", [_task("t1", "running")]))
        now = time.time()
        lease.acquire(store.dir, now=now)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "status", "m1"])
        cli.main()

        out = capsys.readouterr().out
        assert "[running]" in out
        assert "[unknown]" not in out
        assert "[pending]" not in out

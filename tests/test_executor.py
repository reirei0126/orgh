"""R-1: watch/executor分離のST。

- watch は検知・計画・キュー投入のみ(workerを起動しない=長時間ミッションに
  ブロックされない)
- executor(drain)がキューを消化してミッションを完走させる
- キュー満杯時は着火を見送り、空きができた次パスで再試行する
- 他プロセスが実行中(mission lock衝突)のエントリは落として続行する
"""
from __future__ import annotations

import json

from orgh import executor, watcher
from orgh.orchestrator import acquire_mission_lock
from orgh.queue import enqueue, pending
from orgh.state import Mission, RunStore

from .conftest import age, mission_dirs, read_calls, read_ledger


def _post(vault, body: str, name: str = "テストミッション.md"):
    note = vault / "inbox" / name
    note.write_text(body)
    age(note)
    return note


class TestWatchExecutorSeparation:
    def test_watch_enqueues_without_running_worker(self, wcfg, vault,
                                                   one_pass, mock_state_dir):
        _post(vault, "やること #go\n")
        watcher.watch(wcfg)

        calls = read_calls(mock_state_dir)
        assert [c for c in calls if c["role"] == "planner"], "計画は行われる"
        assert not [c for c in calls if c["role"] == "worker"], \
            "watchパス内でworkerが起動した(R-1分離の退行)"
        [mdir] = mission_dirs(wcfg["runs_dir"])
        # 計画済みミッションが保存され、キューに載っている
        data = json.loads((mdir / "mission.json").read_text())
        assert all(t["status"] == "pending" for t in data["tasks"])
        assert [e["mission_id"] for e in pending(wcfg["runs_dir"])] == [mdir.name]
        events = [e["event"] for e in read_ledger(wcfg["runs_dir"], mdir.name)]
        assert "watch.enqueued" in events

    def test_drain_completes_queued_mission(self, wcfg, vault, one_pass,
                                            mock_state_dir):
        _post(vault, "やること #go\n")
        watcher.watch(wcfg)
        assert executor.drain(wcfg) == 1

        [mdir] = mission_dirs(wcfg["runs_dir"])
        data = json.loads((mdir / "mission.json").read_text())
        assert all(t["status"] == "done" for t in data["tasks"])
        assert pending(wcfg["runs_dir"]) == []            # エントリ消化済み
        events = [e["event"] for e in read_ledger(wcfg["runs_dir"], mdir.name)]
        assert "mission.finished" in events

    def test_queue_full_defers_trigger_until_next_pass(self, wcfg, vault,
                                                       one_pass,
                                                       mock_state_dir):
        wcfg["watch"]["queue_limit"] = 1
        _post(vault, "やること1 #go\n", "ノート1.md")
        _post(vault, "やること2 #go\n", "ノート2.md")
        watcher.watch(wcfg)
        # 1件目で満杯 → 2件目は見送り(mark_processedされない)
        assert len(mission_dirs(wcfg["runs_dir"])) == 1
        assert len(pending(wcfg["runs_dir"])) == 1

        executor.drain(wcfg)                    # キューに空きができる
        watcher.watch(wcfg)                     # 次パスで2件目が着火する
        assert len(mission_dirs(wcfg["runs_dir"])) == 2

    def test_entry_for_mission_running_elsewhere_is_dropped(self, cfg,
                                                            mock_state_dir):
        m = Mission.new(intent="lock試験", context_digest="(t)",
                        tasks=[{"id": "t1", "title": "x",
                                "prompt": "p [[MARK:t1]]",
                                "worker": "claude_code", "deps": [],
                                "acceptance": ["a"], "workdir": "."}])
        store = RunStore(cfg["runs_dir"], m.id)
        store.save(m)
        assert enqueue(cfg["runs_dir"], m.id)
        lock_fp = acquire_mission_lock(store)   # 他プロセスの実行を模す
        try:
            assert executor.drain(cfg) == 1     # 例外で止まらず消化扱い
        finally:
            lock_fp.close()
        assert pending(cfg["runs_dir"]) == []   # エントリは落とされた
        data = json.loads((store.dir / "mission.json").read_text())
        assert data["tasks"][0]["status"] == "pending"   # 実行はしていない

    def test_queued_mission_shows_queued_not_running(self, wcfg, vault,
                                                     one_pass,
                                                     mock_state_dir):
        # 投入済み・executor未着手のミッションはrunningではなくqueued表示
        # (キュー滞留時にオーナーが「実行中」と誤認しないため)
        from orgh.listing import list_missions
        from orgh.state import RunStore
        from orgh.status_json import status_payload
        _post(vault, "やること #go\n")
        watcher.watch(wcfg)

        [row] = list_missions(wcfg["runs_dir"])
        assert row["status"] == "queued"
        [mdir] = mission_dirs(wcfg["runs_dir"])
        mission = RunStore(wcfg["runs_dir"], mdir.name).load()
        assert status_payload(mission, wcfg)["status"] == "queued"

        executor.drain(wcfg)                    # 消化後は通常の導出に戻る
        [row] = list_missions(wcfg["runs_dir"])
        assert row["status"] == "done"

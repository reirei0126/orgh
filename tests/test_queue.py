"""R-1: 永続有界ミッションキュー(orgh/queue.py)のST。

- watch(プロデューサ)とexecutor(コンシューマ)が別プロセスでも安全に
  受け渡せること(flock claim・rename原子性)
- executor再起動・クラッシュでキュー内容やclaimが失われない/固着しないこと
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from orgh.queue import claim_next, enqueue, pending

REPO = Path(__file__).resolve().parent.parent


class TestEnqueue:
    def test_enqueue_and_pending_fifo(self, tmp_path):
        runs = tmp_path / "runs"
        assert enqueue(runs, "m1", note_path="/v/n1.md")
        time.sleep(0.01)
        assert enqueue(runs, "m2", note_path=None)
        ids = [e["mission_id"] for e in pending(runs)]
        assert ids == ["m1", "m2"]

    def test_enqueue_is_idempotent_for_same_id(self, tmp_path):
        runs = tmp_path / "runs"
        assert enqueue(runs, "m1")
        assert enqueue(runs, "m1")          # 二重投入は冪等にTrue
        assert len(pending(runs)) == 1

    def test_enqueue_rejects_when_full(self, tmp_path):
        runs = tmp_path / "runs"
        assert enqueue(runs, "m1", limit=2)
        assert enqueue(runs, "m2", limit=2)
        assert not enqueue(runs, "m3", limit=2)   # 満杯: 見送り(watchが再試行)
        assert enqueue(runs, "m1", limit=2)       # 既存IDは満杯でも冪等True

    def test_enqueue_rejects_bad_mission_id(self, tmp_path):
        with pytest.raises(ValueError):
            enqueue(tmp_path / "runs", "../evil")


class TestClaim:
    def test_claim_next_fifo_and_done_removes(self, tmp_path):
        runs = tmp_path / "runs"
        enqueue(runs, "m1")
        time.sleep(0.01)
        enqueue(runs, "m2")
        entry, release = claim_next(runs)
        assert entry["mission_id"] == "m1"
        release(done=True)
        assert [e["mission_id"] for e in pending(runs)] == ["m2"]

    def test_claimed_entry_is_skipped_by_others(self, tmp_path):
        runs = tmp_path / "runs"
        enqueue(runs, "m1")
        time.sleep(0.01)
        enqueue(runs, "m2")
        e1, r1 = claim_next(runs)
        e2, r2 = claim_next(runs)             # claim中のm1をスキップしてm2
        assert (e1["mission_id"], e2["mission_id"]) == ("m1", "m2")
        assert claim_next(runs) is None       # 全部claim中
        r2(done=False)                        # claim解除(失敗: 再試行可能に残す)
        e3, r3 = claim_next(runs)
        assert e3["mission_id"] == "m2"
        r1(done=True)
        r3(done=True)
        assert pending(runs) == []

    def test_claim_next_empty_returns_none(self, tmp_path):
        assert claim_next(tmp_path / "runs") is None

    def test_claim_released_when_holder_process_dies(self, tmp_path):
        # executorクラッシュでclaimが固着しない(flock特性)
        runs = tmp_path / "runs"
        enqueue(runs, "m1")
        child = subprocess.Popen(
            [sys.executable, "-c", (
                "import sys, time; sys.path.insert(0, sys.argv[1])\n"
                "from orgh.queue import claim_next\n"
                "entry, release = claim_next(sys.argv[2])\n"
                "print(entry['mission_id'], flush=True)\n"
                "time.sleep(60)\n"
            ), str(REPO), str(runs)],
            stdout=subprocess.PIPE, text=True)
        try:
            assert child.stdout.readline().strip() == "m1"
            assert claim_next(runs) is None   # 子がclaim中
            child.kill()
            child.wait()
            got = claim_next(runs)            # 子の死で自動解除→再claim可能
            assert got is not None and got[0]["mission_id"] == "m1"
            got[1](done=True)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()

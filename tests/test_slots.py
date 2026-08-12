"""R-2: クロスプロセス計数セマフォ(orgh/slots.py)のST。

flockの性質(fd保持中のみ占有・プロセス死で自動解放)を使うため、
プロセス横断の検証は実subprocessで行う。
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from contextlib import ExitStack
from pathlib import Path

import pytest

from orgh.slots import SlotAborted, acquire_slot

REPO = Path(__file__).resolve().parent.parent


class TestAcquireSlot:
    def test_unlimited_when_limit_none_or_zero(self, tmp_path):
        # 未設定(None)・0以下は制限なし: 即時に通り、スロットファイルも作らない
        for limit in (None, 0, -1):
            with acquire_slot(tmp_path / "runs", limit):
                pass
        assert not (tmp_path / "runs" / "_slots").exists()

    def test_limit_allows_up_to_n_concurrent(self, tmp_path):
        runs = tmp_path / "runs"
        with ExitStack() as stack:
            for _ in range(3):
                stack.enter_context(acquire_slot(runs, 3, poll=0.05))
            # 3枠すべて取得できている(例外なくここまで来る)

    def test_limit_blocks_over_n_and_unblocks_on_release(self, tmp_path):
        runs = tmp_path / "runs"
        acquired = threading.Event()

        def try_third():
            with acquire_slot(runs, 2, poll=0.05):
                acquired.set()

        with ExitStack() as stack:
            stack.enter_context(acquire_slot(runs, 2, poll=0.05))
            held = stack.enter_context(acquire_slot(runs, 2, poll=0.05))  # noqa: F841
            th = threading.Thread(target=try_third, daemon=True)
            th.start()
            time.sleep(0.3)
            assert not acquired.is_set(), "上限2で3つ目が取得できてしまった"
        # ExitStackを抜けてスロット解放 → 3つ目が取得できる
        assert acquired.wait(timeout=5), "解放後もスロットが取得できない"

    def test_should_abort_raises_slot_aborted(self, tmp_path):
        runs = tmp_path / "runs"
        with acquire_slot(runs, 1, poll=0.05):
            with pytest.raises(SlotAborted):
                with acquire_slot(runs, 1, poll=0.05,
                                  should_abort=lambda: True):
                    pytest.fail("満枠なのに取得できてしまった")

    def test_pools_are_independent(self, tmp_path):
        runs = tmp_path / "runs"
        with acquire_slot(runs, 1, pool="workers", poll=0.05):
            # workersが満枠でもrolesは取れる
            with acquire_slot(runs, 1, pool="roles", poll=0.05):
                pass

    def test_slot_released_when_holder_process_dies(self, tmp_path):
        # flock特性: kill -9 でもOSがスロットを解放する(受け入れ基準)
        runs = tmp_path / "runs"
        child = subprocess.Popen(
            [sys.executable, "-c", (
                "import sys, time; sys.path.insert(0, sys.argv[1])\n"
                "from orgh.slots import acquire_slot\n"
                "with acquire_slot(sys.argv[2], 1, poll=0.05):\n"
                "    print('held', flush=True)\n"
                "    time.sleep(60)\n"
            ), str(REPO), str(runs)],
            stdout=subprocess.PIPE, text=True)
        try:
            assert child.stdout.readline().strip() == "held"
            # 子がスロット占有中は取れない
            with pytest.raises(SlotAborted):
                deadline = time.time() + 1
                with acquire_slot(runs, 1, poll=0.05,
                                  should_abort=lambda: time.time() > deadline):
                    pytest.fail("子プロセス占有中に取得できてしまった")
            child.kill()
            child.wait()
            # 子の死でOSが解放 → 取得できる
            with acquire_slot(runs, 1, poll=0.05,
                              should_abort=lambda: False):
                pass
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()

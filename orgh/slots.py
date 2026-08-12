"""クロスプロセスの計数セマフォ(R-2: グローバル並行数制御)。

runs/_slots/<pool>/slot_<i>.lock (i < limit) への flock(EX|NB) で、全orghプロセス
(watch/executor/GUI起動run/手動CLI)横断の同時subprocess数を上限Nに制限する。
スロットはfd保持中のみ占有され、プロセス終了・クラッシュ(kill -9含む)で
OSが自動解放する(受け入れ基準: docs/refactor/execution-architecture.md R-2)。

limit が None/0以下なら制限なし(即時yield・ファイルも作らない)。既定configは
未設定=無効なので、configで明示しない限り従来挙動と完全に同一。
"""
from __future__ import annotations

import fcntl
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable


class SlotAborted(Exception):
    """スロット待機中に should_abort が真になった(キャンセル等)。
    adapter側で「workerの失敗ではない中断」として扱う。"""


@contextmanager
def acquire_slot(runs_dir: str | Path, limit: int | None, *,
                 pool: str = "workers", poll: float = 0.5,
                 should_abort: Callable[[], bool] | None = None):
    """スロットを1つ確保できるまで待つ context manager。

    確保待ちのビジーウェイトは poll 秒間隔。走査のたびに should_abort を
    確認し、真なら SlotAborted を送出する(CANCELフラグの検知窓は最大poll秒)。
    """
    if not limit or limit <= 0:
        yield None
        return
    d = Path(runs_dir) / "_slots" / pool
    d.mkdir(parents=True, exist_ok=True)
    while True:
        if should_abort and should_abort():
            raise SlotAborted(f"aborted while waiting for '{pool}' slot")
        for i in range(limit):
            fp = open(d / f"slot_{i}.lock", "w")
            try:
                fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fp.close()
                continue
            try:
                yield i
                return
            finally:
                fp.close()   # closeでflockも解放される
        time.sleep(poll)

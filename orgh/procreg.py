"""プロセスレジストリ: mission_id → 実行中subprocessの対応を保持する(cancelの前提)。

アダプタがworker subprocessをPopenで起動するたびに register し、終了時に
unregister する。orgh cancel(CANCELフラグ)を検知した orchestrator が
terminate(mission_id) で実行中プロセスへSIGTERMを送る。

レジストリはプロセス内メモリ。別プロセスからの orgh cancel はCANCELフラグ
ファイル経由で伝わり、ミッションを実行中のプロセス自身がここを使って止める。
"""
from __future__ import annotations

import subprocess
import threading

_lock = threading.Lock()
_procs: dict[str, set[subprocess.Popen]] = {}


def register(key: str, proc: subprocess.Popen) -> None:
    with _lock:
        _procs.setdefault(key, set()).add(proc)


def unregister(key: str, proc: subprocess.Popen) -> None:
    with _lock:
        procs = _procs.get(key)
        if procs:
            procs.discard(proc)
            if not procs:
                _procs.pop(key, None)


def pids(key: str) -> list[int]:
    """keyに登録中のprocのpid一覧を返す(生死は問わない、読み取り専用)。

    スリープ復帰後のハングworker検知(orgh/orchestrator/sleep_recovery.py)が、
    生死判定(lease.pid_alive、既存APIを流用)の材料としてここから取得する
    pidを使う。terminate()と違い一切プロセスへ触れないため、schedulerの
    ポーリングループから安全に何度呼んでもよい。"""
    with _lock:
        return [p.pid for p in _procs.get(key, ())]


def terminate(key: str) -> int:
    """keyに登録された実行中プロセスへSIGTERMを送る。送った数を返す。"""
    with _lock:
        procs = list(_procs.get(key, ()))
    count = 0
    for p in procs:
        if p.poll() is None:
            try:
                p.terminate()
                count += 1
            except OSError:
                pass
    return count

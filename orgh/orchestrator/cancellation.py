"""キャンセルの横断ポリシー(HANDOFF タスク4)。

runs/<mission_id>/CANCEL フラグファイルが唯一の停止信号。orgh cancel
(別プロセス)はフラグを置くだけで、ミッションを実行中のプロセス自身が
ループごとにフラグを検知し、実行中subprocessをterminate・未着手タスクを
cancelledにして停止する。poll_cancel(watcherが渡す結果ノートの#cancel検知)
がTrueを返した場合もフラグを置いて同じ経路に合流する。
"""
from __future__ import annotations

import time
from pathlib import Path

from .. import procreg
from ..state import Mission, RunStore


def cancel_flag(store: RunStore) -> Path:
    return store.dir / "CANCEL"


def cancellable_sleep(store: RunStore, seconds: float) -> bool:
    """リトライ待機。CANCEL検知で早期復帰しTrueを返す。

    素のtime.sleepだと待機中のキャンセルが最大でinfra_wait(既定60秒)止まらない
    (停止対象subprocessが存在しない区間のため、terminateでは中断できない)。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if cancel_flag(store).exists():
            return True
        time.sleep(min(1.0, max(0.0, deadline - time.time())))
    return cancel_flag(store).exists()


class CancelledDuringRole(Exception):
    """キャンセルのterminateがreviewer/planner subprocessを落とした際の内部信号。
    包括エラーハンドラでfailedに化けさせず、cancelledとして確定させる。"""


def initiate_cancel(mission: Mission, store: RunStore) -> None:
    """キャンセル開始: フラグを確定し、実行中subprocessをterminate、
    未着手タスクをcancelledにする。実行中タスクの完了(cancelled化)は
    attempt_loop側がフラグを見て行う。"""
    cancel_flag(store).touch()
    n = procreg.terminate(store.dir.name)
    with store.lock:
        for t in mission.tasks:
            if t.status == "pending":
                t.status = "cancelled"
    store.save(mission)
    store.log("mission.cancelled", terminated=n)
    print(f"  mission {store.dir.name} cancelling... ({n} proc terminated)")

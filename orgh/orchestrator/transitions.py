"""タスク状態遷移の単一経路。

保存(store.save)はスケジューラのタスク完了時に一括して行われるため、ここでは
行わない。attempts / human_request 等の付随フィールドを同一lock内で原子的に
更新する必要がある遷移は対象外(呼び出し側が自前のlockブロックで行う)。
"""
from __future__ import annotations

from .. import notify
from ..planner import build_human_request
from ..state import RunStore, Task


def transition(store: RunStore, t: Task, status: str, *,
               notes: str | None = None, event: str | None = None,
               **payload) -> None:
    """lock下でstatus(と任意でreview_notes)を更新し、event指定時はledgerへ
    記録する。イベント名・payloadは呼び出し側が従来と同一のものを渡す
    (このモジュールは経路の共通化のみを担い、遷移の意味づけを持たない)。"""
    with store.lock:
        t.status = status
        if notes is not None:
            t.review_notes = notes
    if event:
        store.log(event, task=t.id, **payload)


def enter_awaiting_human(store: RunStore, cfg: dict, t: Task, reason: str, *,
                         refund_attempt: bool = False) -> None:
    """awaiting_human への遷移一式(依頼書生成・状態/human_request更新・
    artifact・ledger記録・表示)。planner指定(worker: human)と検収
    エスカレーション(HUMAN:)の両経路が使い、依頼書artifact名やledger
    payloadの形を片側だけ変えてしまう乖離を防ぐ。
    refund_attempt: HUMAN:転換はattemptを消費しない(REPLANと同型)。"""
    brief, body = build_human_request(store.dir.name, t, reason)
    with store.lock:
        t.status = "awaiting_human"
        t.human_request = brief
        if refund_attempt:
            t.attempts -= 1
    store.artifact(f"human_request_{t.id}.md", body)
    store.log("task.awaiting_human", task=t.id, brief=brief)
    print(f"  [awaiting_human] {t.title} — {brief}")
    try:
        event = notify.human_task_requested_event(store.dir.name, t, reason)
        notify.emit(store, cfg, event)
    except Exception:
        pass  # 通知処理の失敗でミッション進行を止めない

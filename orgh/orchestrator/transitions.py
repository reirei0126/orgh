"""タスク状態遷移の単一経路。

保存(store.save)はスケジューラのタスク完了時に一括して行われるため、ここでは
行わない。attempts / human_request 等の付随フィールドを同一lock内で原子的に
更新する必要がある遷移は対象外(呼び出し側が自前のlockブロックで行う)。
"""
from __future__ import annotations

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

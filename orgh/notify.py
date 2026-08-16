"""人間接点イベント通知(A1out。方向性文書 2026-08 §3.1)。

イベント生成(冪等) → ledgerへの発行(必須・正本) → webhook送信(best-effort)。
配送保証(outbox/再送/順序/署名/dead-letter)は持たない
(外部基盤へ委譲。ARCH-003: 制御意味論=orgh所有/実行メカニズム=委譲可)。

発火点(scheduler/transitions等)への差し込みは別タスクで行う。ここでは
イベント構築・ledger記録・webhook送信の3関数のみを提供する。
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from typing import Any

from .guard import approval_reason
from .planner import build_human_request
from .state import Mission, RunStore, Task

SCHEMA_VERSION = "1"
_DEFAULT_TIMEOUT = 5.0


def _event_id(event_type: str, mission_id: str, task_id: str | None) -> str:
    """(event_type, mission_id, task_id)から決定的に導出する冪等性キー。

    乱数・現在時刻を使わないため、同一事象が resume 等で再発行されても
    常に同じ値になる。"""
    key = "|".join((event_type, mission_id, task_id or ""))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _build_event(event_type: str, mission_id: str, task_id: str | None,
                  summary: str) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event_type": event_type,
        "event_id": _event_id(event_type, mission_id, task_id),
        "schema_version": SCHEMA_VERSION,
        "mission_id": mission_id,
        "summary": summary,
        "ts": time.time(),
    }
    if task_id is not None:
        event["task_id"] = task_id
    return event


def approval_requested_event(cfg: dict, mission_id: str, task: Task) -> dict:
    """orgh approve待ち(自己改変ガード)。理由はguard.approval_reasonを再利用する。"""
    reason = approval_reason(cfg, task.workdir) or "承認が必要"
    summary = f"タスク「{task.title}」の承認が必要: {reason}"
    return _build_event("approval.requested", mission_id, task.id, summary)


def human_task_requested_event(mission_id: str, task: Task, reason: str) -> dict:
    """awaiting_human。一文はplanner.build_human_requestの依頼一文をそのまま使う
    (awaiting_human遷移・GUIのhuman_requestsキーと同一の文言)。"""
    brief, _body = build_human_request(mission_id, task, reason)
    return _build_event("human_task.requested", mission_id, task.id, brief)


def mission_completed_event(mission: Mission,
                             pending_verdict_count: int | None = None) -> dict:
    """全タスク終端後のミッション完了通知。

    pending_verdict_count指定時は「verdict未実施のdoneミッションがN件ある」
    ことを一言添える(通知が届かずverdictされないまま埋もれる事態への
    再発見導線。docs/strategy/direction-2026-08.md §3.4 A4)。強制はしない
    (裁定なしでの完了自体は止めない)。"""
    done = sum(1 for t in mission.tasks if t.status == "done")
    total = len(mission.tasks)
    summary = f"ミッション「{mission.intent}」完了: done {done}/{total}"
    if pending_verdict_count is not None:
        summary += f"。未裁定のミッションが{pending_verdict_count}件あります"
    return _build_event("mission.completed", mission.id, None, summary)


def _post_webhook(url: str, event: dict, timeout: float) -> None:
    # "text" はSlack Incoming Webhook互換のための別名(無いと400 no_textで拒否される。
    # 2026-08-16 実URLで確認)。汎用コンシューマにはsummaryと同値の冗長キーであり無害。
    # ledger(notify.emitted)には元のevent形のみを記録し、この別名は送信時にだけ付ける
    body = json.dumps({**event, "text": event.get("summary", "")},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


def emit(store: RunStore, cfg: dict | None, event: dict) -> None:
    """eventをledgerへ記録し(notify.emitted。監査の正本・必ず実行)、
    config の notify.webhook_url が設定されていればbest-effortでPOSTする。

    webhook_url未設定(既定null)ならPOSTは一切行わない。POST失敗は例外を
    呼び出し元へ伝播させず、notify.failedとしてledgerに記録するだけに留める
    (ミッション進行を止めない)。"""
    store.log("notify.emitted", **event)

    notify_cfg = (cfg or {}).get("notify") or {}
    webhook_url = notify_cfg.get("webhook_url")
    if not webhook_url:
        return

    timeout = notify_cfg.get("timeout", _DEFAULT_TIMEOUT)
    try:
        _post_webhook(webhook_url, event, timeout)
    except Exception as exc:
        store.log("notify.failed", event_id=event["event_id"],
                   event_type=event["event_type"], mission_id=event["mission_id"],
                   error=str(exc)[:300])

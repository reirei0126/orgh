"""差し戻しfeedbackとowner_replanのledger収集(criteria蒸留の入力層)。

検収の差し戻し理由(task.review, passed=False の feedback)とオーナーの
修正指示(owner.interrupt, kind=owner_replan の detail)をミッションの
ledgerから出現順に集める純関数のみを提供する。LLMによる規範候補の蒸留や
retroへの配線は後続タスクの担当であり、ここでは行わない。
"""
from __future__ import annotations

from .events_json import events_payload


def collect_normative_feedback(cfg: dict, mission_id: str) -> list[dict]:
    """mission_id の ledger から規範候補の元ネタになりうる本文を集める。

    対象は (a) task.review イベントのうち passed が偽のものの feedback、
    (b) owner.interrupt イベントのうち kind が owner_replan のものの detail。
    本文が欠落・空白のみのイベントは除外する。ledgerが存在しないミッション
    では空リストを返す(例外は投げない)。
    """
    payload = events_payload(cfg.get("runs_dir", "runs"), mission_id, tail=None)
    out: list[dict] = []
    for ev in payload["events"]:
        event = ev.get("event")
        if event == "task.review" and not ev.get("passed"):
            text = ev.get("feedback")
            kind = "review"
        elif event == "owner.interrupt" and ev.get("kind") == "owner_replan":
            text = ev.get("detail")
            kind = "owner_replan"
        else:
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        out.append({"kind": kind, "task": ev.get("task"), "text": text})
    return out

"""差し戻しfeedbackとowner_replanのledger収集・LLM蒸留(criteria蒸留の入力層)。

検収の差し戻し理由(task.review, passed=False の feedback)とオーナーの
修正指示(owner.interrupt, kind=owner_replan の detail)をミッションの
ledgerから出現順に集める collect_normative_feedback() と、それをLLMで
「別ミッションでも適用可能な一般則」へ蒸留し台帳下書き(_drafts/)を生成する
distill_mission_feedback() を提供する。retroへの配線(いつ呼ぶか)は
後続タスクの担当であり、ここでは行わない。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .criteria import (_next_draft_start, criteria_context, criteria_dir,
                       project_slug)
from .events_json import events_payload

_LEDGER_LINE_RE = re.compile(r"^- [A-Z]+-\d{3} \[(?:norm|pref)\]: (.*)$")


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


def _normalize_text(text: str) -> str:
    """重複判定用: 空白を全て除去した比較キー。"""
    return "".join(text.split())


def _existing_criteria_texts(cfg: dict, workdir: str | Path | None) -> set[str]:
    """criteria_context(cfg, workdir=workdir)が実際に注入する各エントリ行から
    基準本文(srcメタコメントを除いた部分)を正規化して集める。"""
    texts: set[str] = set()
    for line in criteria_context(cfg, workdir=workdir).splitlines():
        m = _LEDGER_LINE_RE.match(line)
        if not m:
            continue
        body = m.group(1).split(" <!--", 1)[0]
        texts.add(_normalize_text(body))
    return texts


def _format_feedback(items: list[dict]) -> str:
    return "\n".join(f"- [{item['kind']}] {item['text']}" for item in items)


def distill_mission_feedback(cfg: dict, mission_id: str, intent: str,
                             workdir: str | Path | None = None) -> list[Path]:
    """ミッションの差し戻しfeedback/owner_replanから台帳下書きを生成する
    (本台帳には書かない)。

    collect_normative_feedback()が空(feedbackが1件も無い)ならLLMを呼ばずに
    即 [] を返す(コスト増を抑えるため)。LLM呼び出しは1回のみ、応答の
    proposalsは (1) 既存台帳(criteria_context(cfg, workdir=workdir))と正規化
    後に完全一致する候補を除外し、(2) 残りを先頭2件までに切り詰めてから
    _drafts/ へ書く。workdirを渡すと project_slug(cfg, workdir) が導出する
    slug候補を各下書きの "project_slug_hint" に付記する(distill_verdict()と
    同じ形。承認時に `orgh criteria approve <name> --project <slug>` の
    ヒントとして使う)。
    """
    feedback = collect_normative_feedback(cfg, mission_id)
    if not feedback:
        return []

    from .planner import _ask_json, _read_prompt, role_with_default
    cfg = role_with_default(cfg, "criteria_feedback_distill", {
        "model": "sonnet", "max_turns": 5, "allowed_tools": "Read"})
    tmpl = _read_prompt(cfg, "criteria_feedback_distill.md")
    prompt = tmpl.format(intent=intent, feedback=_format_feedback(feedback),
                         criteria=criteria_context(cfg, workdir=workdir))
    data = _ask_json(cfg, "criteria_feedback_distill", prompt)

    existing = _existing_criteria_texts(cfg, workdir)
    proposals = [p for p in (data.get("proposals") or [])
                if _normalize_text(p.get("text", "")) not in existing]
    proposals = proposals[:2]

    drafts_dir = criteria_dir(cfg) / "_drafts"
    slug = project_slug(cfg, workdir)
    out: list[Path] = []
    if proposals:
        drafts_dir.mkdir(parents=True, exist_ok=True)
        start = _next_draft_start(drafts_dir, mission_id)
        for i, p in enumerate(proposals, start):
            if slug is not None:
                p = {**p, "project_slug_hint": slug}
            fp = drafts_dir / f"{mission_id}-{i}.json"
            fp.write_text(json.dumps(p, ensure_ascii=False, indent=1))
            out.append(fp)
    return out

"""Planner / Reviewer / Retro。
すべて claude -p (headless) を1発叩いてJSONを返させる薄いラッパ。
プロンプト本文は prompts/*.md に外出し(ユーザーが育てる部分)。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .adapters.base import get_adapter
from .state import Mission, Task

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
PLAYBOOKS = Path(__file__).resolve().parent.parent / "playbooks"


def _playbook_context(max_chars: int = 8000) -> str:
    """過去のRetroで蒸留された組織知をPlanner/Workerに注入する(増幅の核)。"""
    chunks = []
    for p in sorted(PLAYBOOKS.glob("*.md")):
        chunks.append(f"## {p.stem}\n{p.read_text()}")
    return "\n".join(chunks)[:max_chars] or "(no playbooks yet)"


def _ask_json(cfg: dict, role: str, prompt: str, workdir: str = ".") -> dict:
    adapter = get_adapter("claude_code", {**cfg["workers"],
                          "claude_code": cfg["roles"][role]})
    res = adapter.run(prompt, workdir=workdir)
    if not res.ok:
        raise RuntimeError(f"{role} failed: {res.output[:500]}")
    m = re.search(r"\{.*\}", res.output, re.S)
    if not m:
        raise ValueError(f"{role} returned no JSON:\n{res.output[:800]}")
    return json.loads(m.group(0))


def plan(cfg: dict, intent: str, context_digest: str) -> Mission:
    tmpl = (PROMPTS / "planner.md").read_text()
    prompt = tmpl.format(intent=intent, context=context_digest,
                         playbooks=_playbook_context(),
                         workers=", ".join(cfg["workers"]["enabled"]))
    data = _ask_json(cfg, "planner", prompt)
    return Mission.new(intent=intent, context_digest=context_digest,
                       tasks=data["tasks"])


def review(cfg: dict, task: Task, workdir: str) -> tuple[bool, str]:
    tmpl = (PROMPTS / "reviewer.md").read_text()
    prompt = tmpl.format(title=task.title, prompt=task.prompt,
                         acceptance="\n".join(f"- {a}" for a in task.acceptance),
                         output=task.last_output[:12000])
    data = _ask_json(cfg, "reviewer", prompt, workdir=workdir)
    return bool(data.get("pass")), data.get("feedback", "")


def retro(cfg: dict, mission: Mission) -> str:
    """完了ミッションから学びを抽出して playbooks/ に追記 → 次回以降の全員が賢くなる。"""
    tmpl = (PROMPTS / "retro.md").read_text()
    summary = "\n".join(
        f"- [{t.status}] {t.title} (attempts={t.attempts}) "
        f"review: {t.review_notes[:200]}"
        for t in mission.tasks
    )
    prompt = tmpl.format(intent=mission.intent, summary=summary)
    data = _ask_json(cfg, "retro", prompt)
    name = data.get("playbook_name", "general")
    body = data.get("lessons", "")
    if body:
        fp = PLAYBOOKS / f"{name}.md"
        with open(fp, "a") as f:
            f.write(f"\n<!-- mission {mission.id} -->\n{body}\n")
        return str(fp)
    return ""


def worker_prompt(task: Task) -> str:
    tmpl = (PROMPTS / "worker_preamble.md").read_text()
    return tmpl.format(title=task.title, prompt=task.prompt,
                       acceptance="\n".join(f"- {a}" for a in task.acceptance),
                       playbooks=_playbook_context(4000))

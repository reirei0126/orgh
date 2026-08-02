"""Planner / Reviewer / Retro。
すべて claude -p (headless) を1発叩いてJSONを返させる薄いラッパ。
プロンプト本文は prompts/*.md に外出し(ユーザーが育てる部分)。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .adapters.base import get_adapter
from .state import Budget, Mission, Task


def _prompts_dir(cfg: dict) -> Path:
    return Path(cfg.get("prompts_dir", "prompts")).expanduser()


def _playbooks_dir(cfg: dict) -> Path:
    return Path(cfg.get("playbooks_dir", "playbooks")).expanduser()


def _read_prompt(cfg: dict, name: str) -> str:
    fp = _prompts_dir(cfg) / name
    try:
        return fp.read_text()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"prompt template not found: {fp}. config の prompts_dir を確認せよ")


def _playbook_context(cfg: dict, max_chars: int = 8000) -> str:
    """過去のRetroで蒸留された組織知をPlanner/Workerに注入する(増幅の核)。"""
    playbooks_dir = _playbooks_dir(cfg)
    if not playbooks_dir.is_dir():
        return "(no playbooks yet)"
    chunks = []
    for p in sorted(playbooks_dir.glob("*.md")):
        chunks.append(f"## {p.stem}\n{p.read_text()}")
    return "\n".join(chunks)[:max_chars] or "(no playbooks yet)"


def _ask_json(cfg: dict, role: str, prompt: str, workdir: str = ".",
              budget: Budget | None = None) -> dict:
    adapter = get_adapter("claude_code", {**cfg["workers"],
                          "claude_code": cfg["roles"][role]})
    res = adapter.run(prompt, workdir=workdir)
    if not res.ok:
        raise RuntimeError(f"{role} failed: {res.output[:500]}")
    if budget is not None:
        budget.charge(res.cost_usd)
    m = re.search(r"\{.*\}", res.output, re.S)
    if not m:
        raise ValueError(f"{role} returned no JSON:\n{res.output[:800]}")
    return json.loads(m.group(0))


def plan(cfg: dict, intent: str, context_digest: str,
        budget: Budget | None = None) -> Mission:
    if budget is None:
        lcfg = cfg.get("loop", {})
        budget = Budget(limit_usd=lcfg.get("budget_usd"),
                        task_budget_usd=lcfg.get("task_budget_usd"))
    tmpl = _read_prompt(cfg, "planner.md")
    prompt = tmpl.format(intent=intent, context=context_digest,
                         playbooks=_playbook_context(cfg),
                         workers=", ".join(cfg["workers"]["enabled"]))
    data = _ask_json(cfg, "planner", prompt, budget=budget)
    mission = Mission.new(intent=intent, context_digest=context_digest,
                          tasks=data["tasks"])
    mission.budget = budget
    return mission


def review(cfg: dict, task: Task, workdir: str,
          budget: Budget | None = None) -> tuple[bool, str]:
    tmpl = _read_prompt(cfg, "reviewer.md")
    prompt = tmpl.format(title=task.title, prompt=task.prompt,
                         acceptance="\n".join(f"- {a}" for a in task.acceptance),
                         output=task.last_output[:12000])
    data = _ask_json(cfg, "reviewer", prompt, workdir=workdir, budget=budget)
    return bool(data.get("pass")), data.get("feedback", "")


def retro(cfg: dict, mission: Mission) -> str:
    """完了ミッションから学びを抽出して playbooks/ に追記 → 次回以降の全員が賢くなる。"""
    tmpl = _read_prompt(cfg, "retro.md")
    summary = "\n".join(
        f"- [{t.status}] {t.title} (attempts={t.attempts}) "
        f"review: {t.review_notes[:200]}"
        for t in mission.tasks
    )
    prompt = tmpl.format(intent=mission.intent, summary=summary)
    data = _ask_json(cfg, "retro", prompt, budget=mission.budget)
    name = data.get("playbook_name", "general")
    body = data.get("lessons", "")
    if body:
        _playbooks_dir(cfg).mkdir(parents=True, exist_ok=True)
        fp = _playbooks_dir(cfg) / f"{name}.md"
        with open(fp, "a") as f:
            f.write(f"\n<!-- mission {mission.id} -->\n{body}\n")
        return str(fp)
    return ""


def worker_prompt(cfg: dict, task: Task) -> str:
    tmpl = _read_prompt(cfg, "worker_preamble.md")
    return tmpl.format(title=task.title, prompt=task.prompt,
                       acceptance="\n".join(f"- {a}" for a in task.acceptance),
                       playbooks=_playbook_context(cfg, 4000))

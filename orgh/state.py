"""Run state & ledger. Everything the org knows lives on disk, restartable."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml


def load_config(path: str | Path = "config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{p} not found. copy config.example.yaml -> config.yaml")
    return yaml.safe_load(p.read_text())


@dataclass
class Task:
    id: str
    title: str
    prompt: str
    worker: str = "claude_code"          # adapter name
    deps: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    workdir: str = "."
    status: str = "pending"              # pending -> running -> review -> done / failed
    attempts: int = 0
    session_id: str | None = None        # for claude --resume
    last_output: str = ""
    review_notes: str = ""


@dataclass
class Mission:
    id: str
    intent: str
    context_digest: str
    tasks: list[Task]
    created_at: float = field(default_factory=time.time)

    @staticmethod
    def new(intent: str, context_digest: str, tasks: list[dict]) -> "Mission":
        return Mission(
            id=uuid.uuid4().hex[:8],
            intent=intent,
            context_digest=context_digest,
            tasks=[Task(**t) for t in tasks],
        )


class RunStore:
    """runs/<mission_id>/ に mission.json と ledger.jsonl を永続化。"""

    def __init__(self, root: str | Path, mission_id: str):
        self.dir = Path(root) / mission_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, mission: Mission) -> None:
        data = asdict(mission)
        (self.dir / "mission.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2)
        )

    def load(self) -> Mission:
        data = json.loads((self.dir / "mission.json").read_text())
        data["tasks"] = [Task(**t) for t in data["tasks"]]
        return Mission(**data)

    def log(self, event: str, **kw: Any) -> None:
        rec = {"ts": time.time(), "event": event, **kw}
        with open(self.dir / "ledger.jsonl", "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def artifact(self, name: str, content: str) -> Path:
        p = self.dir / "artifacts"
        p.mkdir(exist_ok=True)
        fp = p / name
        fp.write_text(content)
        return fp

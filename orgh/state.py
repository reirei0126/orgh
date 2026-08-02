"""Run state & ledger. Everything the org knows lives on disk, restartable.

- config: 起動時にdataclassスキーマで検証(未知キー警告・必須キー欠落エラー)
- mission.json: tmp書き込み→os.replace のアトミック永続化
- ledger追記とmission状態の変更は RunStore.lock(単一ロック)で保護
- ロード時に実行中系ステータス(running/queued/review)をpendingへ巻き戻す
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
import warnings
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """必須キー欠落・型不一致など、続行不能なconfig欠陥。"""


class ConfigWarning(UserWarning):
    """未知キーなど、無視して続行できるconfigの疑義。"""


# ---------------------------------------------------------------- config schema
@dataclass
class VaultCfg:
    path: str = ""
    inbox: str = "inbox"
    mission_tag: str = "mission"


@dataclass
class LoopCfg:
    parallel: int = 3
    max_attempts: int = 3
    task_timeout: int = 3600


@dataclass
class WatchCfg:
    interval: float = 5
    stabilize_seconds: float = 20
    writeback: bool = True


@dataclass
class ConfigSchema:
    """既知のトップレベルキー。workers/rolesは名前が自由なため深掘りしない。"""
    workers: dict | None = None          # 必須
    roles: dict | None = None
    vault: VaultCfg | None = None
    loop: LoopCfg | None = None
    watch: WatchCfg | None = None
    runs_dir: str = "runs"
    prompts_dir: str = "prompts"
    playbooks_dir: str = "playbooks"


_REQUIRED_KEYS = ("workers",)
_SECTION_SCHEMAS = {"vault": VaultCfg, "loop": LoopCfg, "watch": WatchCfg}
# from __future__ import annotations により field.type は文字列
_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "int": int, "float": (int, float), "str": str, "bool": bool,
}


def _check_section(name: str, value: Any, schema_cls: type) -> None:
    if not isinstance(value, dict):
        raise ConfigError(f"config: {name} はマップで指定すること")
    known = {f.name: f for f in fields(schema_cls)}
    for k, v in value.items():
        if k not in known:
            warnings.warn(ConfigWarning(
                f"config: 未知のキー {name}.{k} を無視する"))
            continue
        expected = _TYPE_MAP.get(known[k].type)
        if expected and v is not None and not isinstance(v, expected):
            raise ConfigError(
                f"config: {name}.{k} の型が不正 "
                f"(期待 {known[k].type}, 実際 {type(v).__name__}: {v!r})")


def validate_config(data: Any) -> dict:
    if not isinstance(data, dict):
        raise ConfigError("config全体がマップになっていない")
    for k in _REQUIRED_KEYS:
        if k not in data:
            raise ConfigError(f"config: 必須キー {k} がない")

    top = {f.name: f for f in fields(ConfigSchema)}
    for k in data:
        if k not in top:
            warnings.warn(ConfigWarning(f"config: 未知のキー {k} を無視する"))
    for name, cls in _SECTION_SCHEMAS.items():
        if data.get(name) is not None:
            _check_section(name, data[name], cls)
    for name in ("workers", "roles"):
        if data.get(name) is not None and not isinstance(data[name], dict):
            raise ConfigError(f"config: {name} はマップで指定すること")
    for name in ("runs_dir", "prompts_dir", "playbooks_dir"):
        if data.get(name) is not None and not isinstance(data[name], str):
            raise ConfigError(f"config: {name} は文字列で指定すること")
    return data


def load_config(path: str | Path = "config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found. copy config.example.yaml -> config.yaml")
    return validate_config(yaml.safe_load(p.read_text()) or {})


# ------------------------------------------------------------------- run state
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


# 実行中にクラッシュした場合、ロード時にpendingへ巻き戻す(デッドロック解消)
_INFLIGHT_STATUSES = ("queued", "running", "review")


class RunStore:
    """runs/<mission_id>/ に mission.json と ledger.jsonl を永続化。

    lock はミッション状態の変更・保存・ledger追記を守る単一ロック。
    orchestrator はタスクのフィールドを書き換える際に `with store.lock:` で囲む。
    """

    def __init__(self, root: str | Path, mission_id: str):
        self.dir = Path(root) / mission_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def save(self, mission: Mission) -> None:
        with self.lock:
            data = asdict(mission)
            tmp = self.dir / ".mission.json.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            os.replace(tmp, self.dir / "mission.json")

    def load(self) -> Mission:
        data = json.loads((self.dir / "mission.json").read_text())
        data["tasks"] = [Task(**t) for t in data["tasks"]]
        mission = Mission(**data)
        for t in mission.tasks:
            if t.status in _INFLIGHT_STATUSES:
                t.status = "pending"
        return mission

    def log(self, event: str, **kw: Any) -> None:
        rec = {"ts": time.time(), "event": event, **kw}
        with self.lock:
            with open(self.dir / "ledger.jsonl", "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def artifact(self, name: str, content: str) -> Path:
        p = self.dir / "artifacts"
        p.mkdir(exist_ok=True)
        fp = p / name
        fp.write_text(content)
        return fp

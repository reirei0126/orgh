"""Worker adapters: どのCLIエージェントも「prompt in -> WorkerResult out」に正規化する。"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass
class WorkerResult:
    ok: bool
    output: str
    session_id: str | None = None
    cost_usd: float | None = None
    raw: str = ""


class BaseAdapter:
    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def run(self, prompt: str, workdir: str, resume: str | None = None,
            timeout: int = 3600) -> WorkerResult:
        raise NotImplementedError

    @staticmethod
    def _exec(cmd: list[str], workdir: str, stdin: str | None,
              timeout: int) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd, cwd=workdir, input=stdin, capture_output=True,
            text=True, timeout=timeout,
        )


class ClaudeCodeAdapter(BaseAdapter):
    """claude -p headless. --output-format json で result / session_id / cost を取得。"""
    name = "claude_code"

    def run(self, prompt: str, workdir: str, resume: str | None = None,
            timeout: int = 3600) -> WorkerResult:
        c = self.cfg
        cmd = [c.get("bin", "claude"), "-p", "--output-format", "json",
               "--max-turns", str(c.get("max_turns", 40))]
        if c.get("model"):
            cmd += ["--model", c["model"]]
        if c.get("allowed_tools"):
            cmd += ["--allowedTools", c["allowed_tools"]]
        if c.get("permission_mode"):
            cmd += ["--permission-mode", c["permission_mode"]]
        if resume:
            cmd += ["--resume", resume]
        proc = self._exec(cmd, workdir, stdin=prompt, timeout=timeout)
        try:
            data = json.loads(proc.stdout.strip().splitlines()[-1])
            return WorkerResult(
                ok=proc.returncode == 0 and not data.get("is_error", False),
                output=data.get("result", ""),
                session_id=data.get("session_id"),
                cost_usd=data.get("total_cost_usd"),
                raw=proc.stdout,
            )
        except (json.JSONDecodeError, IndexError):
            return WorkerResult(ok=False, output=proc.stdout + proc.stderr,
                                raw=proc.stdout)


class CodexAdapter(BaseAdapter):
    """codex exec 非対話モード。フラグは config で調整可能にしてある。"""
    name = "codex"

    def run(self, prompt: str, workdir: str, resume: str | None = None,
            timeout: int = 3600) -> WorkerResult:
        c = self.cfg
        cmd = [c.get("bin", "codex"), "exec"] + c.get("extra_args", [])
        cmd.append(prompt)
        proc = self._exec(cmd, workdir, stdin=None, timeout=timeout)
        return WorkerResult(ok=proc.returncode == 0,
                            output=proc.stdout, raw=proc.stdout + proc.stderr)


class ShellAdapter(BaseAdapter):
    """任意のCLI LLM(gemini, llm 等)を config の template で叩く汎用アダプタ。"""
    name = "shell"

    def run(self, prompt: str, workdir: str, resume: str | None = None,
            timeout: int = 3600) -> WorkerResult:
        cmd = [a if a != "{prompt}" else prompt for a in self.cfg["argv"]]
        proc = self._exec(cmd, workdir, stdin=None, timeout=timeout)
        return WorkerResult(ok=proc.returncode == 0,
                            output=proc.stdout, raw=proc.stdout + proc.stderr)


REGISTRY = {a.name: a for a in (ClaudeCodeAdapter, CodexAdapter, ShellAdapter)}


def get_adapter(name: str, cfg: dict) -> BaseAdapter:
    if name not in REGISTRY:
        raise KeyError(f"unknown worker '{name}'. available: {list(REGISTRY)}")
    return REGISTRY[name](cfg.get(name, {}))

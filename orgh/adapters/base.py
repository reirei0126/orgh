"""Worker adapters: どのCLIエージェントも「prompt in -> WorkerResult out」に正規化する。

- タイムアウト(subprocess.TimeoutExpired)はここで捕捉し
  WorkerResult(ok=False, output="timeout") に変換する。それ以外の例外
  (バイナリ不在等)は orchestrator 側の例外隔離に委ねる
- subprocessはPopenで起動し、registry_key(mission_id)が渡された場合は
  procreg に登録する(orgh cancel がterminate対象を特定できるようにする)
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .. import procreg


@dataclass
class WorkerResult:
    ok: bool
    output: str
    session_id: str | None = None
    cost_usd: float | None = None
    raw: str = ""


class BaseAdapter:
    """テンプレート: サブクラスは _command()(引数列とstdin)と _parse() を実装する。"""
    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def run(self, prompt: str, workdir: str, resume: str | None = None,
            timeout: int = 3600, registry_key: str | None = None,
            allowed_tools: str | None = None) -> WorkerResult:
        cmd, stdin = self._command(prompt, resume, allowed_tools)
        proc = subprocess.Popen(
            cmd, cwd=workdir,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if registry_key:
            procreg.register(registry_key, proc)
        try:
            try:
                out, err = proc.communicate(stdin, timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return WorkerResult(ok=False, output="timeout")
        finally:
            if registry_key:
                procreg.unregister(registry_key, proc)
        return self._parse(
            subprocess.CompletedProcess(cmd, proc.returncode, out, err))

    def _command(self, prompt: str, resume: str | None,
                 allowed_tools: str | None = None) -> tuple[list[str], str | None]:
        raise NotImplementedError

    def _parse(self, proc: subprocess.CompletedProcess) -> WorkerResult:
        raise NotImplementedError


class ClaudeCodeAdapter(BaseAdapter):
    """claude -p headless. --output-format json で result / session_id / cost を取得。"""
    name = "claude_code"

    def _command(self, prompt: str, resume: str | None,
                 allowed_tools: str | None = None) -> tuple[list[str], str | None]:
        c = self.cfg
        cmd = [c.get("bin", "claude"), "-p", "--output-format", "json",
               "--max-turns", str(c.get("max_turns", 40))]
        if c.get("model"):
            cmd += ["--model", c["model"]]
        # タスク単位のtools(Planner明示付与)がworker既定より優先
        if allowed_tools or c.get("allowed_tools"):
            cmd += ["--allowedTools", allowed_tools or c["allowed_tools"]]
        if c.get("permission_mode"):
            cmd += ["--permission-mode", c["permission_mode"]]
        if resume:
            cmd += ["--resume", resume]
        return cmd, prompt

    def _parse(self, proc: subprocess.CompletedProcess) -> WorkerResult:
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

    def _command(self, prompt: str, resume: str | None,
                 allowed_tools: str | None = None) -> tuple[list[str], str | None]:
        cmd = [self.cfg.get("bin", "codex"), "exec"] + self.cfg.get("extra_args", [])
        cmd.append(prompt)
        return cmd, None

    def _parse(self, proc: subprocess.CompletedProcess) -> WorkerResult:
        return WorkerResult(ok=proc.returncode == 0,
                            output=proc.stdout, raw=proc.stdout + proc.stderr)


class ShellAdapter(BaseAdapter):
    """任意のCLI LLM(gemini, llm 等)を config の template で叩く汎用アダプタ。"""
    name = "shell"

    def _command(self, prompt: str, resume: str | None,
                 allowed_tools: str | None = None) -> tuple[list[str], str | None]:
        return [a if a != "{prompt}" else prompt for a in self.cfg["argv"]], None

    def _parse(self, proc: subprocess.CompletedProcess) -> WorkerResult:
        return WorkerResult(ok=proc.returncode == 0,
                            output=proc.stdout, raw=proc.stdout + proc.stderr)


REGISTRY = {a.name: a for a in (ClaudeCodeAdapter, CodexAdapter, ShellAdapter)}


def get_adapter(name: str, cfg: dict) -> BaseAdapter:
    if name not in REGISTRY:
        raise KeyError(f"unknown worker '{name}'. available: {list(REGISTRY)}")
    return REGISTRY[name](cfg.get(name, {}))

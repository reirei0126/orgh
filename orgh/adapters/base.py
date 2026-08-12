"""Worker adapters: どのCLIエージェントも「prompt in -> WorkerResult out」に正規化する。

- タイムアウト(subprocess.TimeoutExpired)はここで捕捉し
  WorkerResult(ok=False, output="timeout") に変換する。それ以外の例外
  (バイナリ不在等)は orchestrator 側の例外隔離に委ねる
- subprocessはPopenで起動し、registry_key(mission_id)が渡された場合は
  procreg に登録する(orgh cancel がterminate対象を特定できるようにする)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass

from .. import procreg

# worker/roleに継承させない秘密情報の変数名パターン。prompt注入されたworkerが
# 環境変数からシークレットを読み出し出力(artifact/ledger/結果ノート)へ流す
# 経路を塞ぐ(ヘルスレビュー deferred: worker env)
_SECRET_ENV_RE = re.compile(
    r"(?i)(secret|token|password|passwd|credential|"
    r"api[_-]?key|access[_-]?key|private[_-]?key|session[_-]?key)")

# 秘密パターンに一致しても、worker/role自身の認証に必要な可能性があるため
# 既定で通す変数(誤ってstripするとAPIキー認証のworkerが起動不能になる)。
# 追加はconfigの workers.<name>.env_secret_allow / roles.<r>.env_secret_allow で
_DEFAULT_AUTH_KEEP = frozenset({
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY",
})


def filtered_env(cfg: dict) -> dict:
    """秘密情報パターンの環境変数を除いたenvを返す。認証用の既定keep集合と
    config指定(env_secret_allow)は通す。それ以外は従来どおり継承する
    (default-allow + secret strip: 認証を壊さず漏洩面だけ絞る安全側の設計)。"""
    keep = _DEFAULT_AUTH_KEEP | set(cfg.get("env_secret_allow") or [])
    return {k: v for k, v in os.environ.items()
            if k in keep or not _SECRET_ENV_RE.search(k)}


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
    # セッション継続(resume)でプロンプト間の文脈を保持できるか。Falseの
    # workerには再試行時に自己完結プロンプトを渡す必要がある(orchestrator参照)
    supports_resume = False

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def run(self, prompt: str, workdir: str, resume: str | None = None,
            timeout: int = 3600, registry_key: str | None = None,
            allowed_tools: str | None = None) -> WorkerResult:
        cmd, stdin = self._command(prompt, resume, allowed_tools)
        proc = subprocess.Popen(
            cmd, cwd=workdir, env=filtered_env(self.cfg),
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
    supports_resume = True

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
        # 役割呼び出しはsetting_sources="user"でcwd内のCLAUDE.md/.claude設定
        # (project/localソース=worktree内のworker生成物)を無視する。
        # 信頼境界の防御(planner._ask_json が注入)
        if c.get("setting_sources"):
            cmd += ["--setting-sources", c["setting_sources"]]
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

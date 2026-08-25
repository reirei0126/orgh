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
            allowed_tools: str | None = None,
            task_key: str | None = None) -> WorkerResult:
        cmd, stdin = self._command(prompt, resume, allowed_tools)
        proc = subprocess.Popen(
            cmd, cwd=workdir, env=filtered_env(self.cfg),
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if registry_key:
            procreg.register(registry_key, proc)
        # task_key: registry_key(mission単位、orgh cancelのterminate対象特定用)
        # とは別に、タスク単位でも同じprocを登録する。スリープ復帰後のハング
        # worker検知(orgh/orchestrator/sleep_recovery.py)が「このタスクに
        # 紐づくworker」だけを特定してpid生死を確認する必要があり、mission
        # 単位のregistry_keyだけでは並列実行中の他タスクのprocと区別できない
        # ため新設した(procregの既存キー方式・登録/解除の作法はそのまま流用)
        if task_key:
            procreg.register(task_key, proc)
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
            if task_key:
                procreg.unregister(task_key, proc)
        return self._parse(
            subprocess.CompletedProcess(cmd, proc.returncode, out, err))

    def _command(self, prompt: str, resume: str | None,
                 allowed_tools: str | None = None) -> tuple[list[str], str | None]:
        raise NotImplementedError

    def _parse(self, proc: subprocess.CompletedProcess) -> WorkerResult:
        raise NotImplementedError


def build_allowed_tools(base_tools: str | None,
                        capability_allowlist: list | None) -> str | None:
    """--allowedTools へ capability_allowlist(固定Bashパターン等)を追記結合する。

    capability_allowlist が空/未設定なら base_tools をそのまま返す(既存挙動を
    1バイトも変えない)。設定がある場合のみカンマ区切りで末尾に追記する。

    ⚠ これはセキュリティ境界ではない/セキュリティ保証ではない: 同じargvでも
    PATH差し替え・cwd・設定ファイル・git hook・symlink・環境変数によって実際の
    書き込み/外部通信は変わりうる(sandbox/egressの強制も無い)。ここでの許可は
    「能力不足を誤ってawaiting_humanへ変換しない」ための能力宣言というUX改善で
    あって、実行環境そのものを隔離する保証ではない(方向性文書2026-08 §3.1 A2)。
    """
    if not capability_allowlist:
        return base_tools
    injected = ",".join(capability_allowlist)
    return f"{base_tools},{injected}" if base_tools else injected


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
        # タスク単位のtools(Planner明示付与)がworker既定より優先。
        # capability_allowlist(config)はその上へさらに追記注入する
        tools = build_allowed_tools(allowed_tools or c.get("allowed_tools"),
                                    c.get("capability_allowlist"))
        if tools:
            cmd += ["--allowedTools", tools]
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


def get_adapter(name: str, cfg: dict, model: str | None = None) -> BaseAdapter:
    """model が非Noneの場合のみ、そのworkerのcfgへ {"model": model} を上書き注入する。
    Noneのときはcfg.get(name, {})をそのまま渡し、既存挙動を1バイトも変えない。"""
    if name not in REGISTRY:
        raise KeyError(f"unknown worker '{name}'. available: {list(REGISTRY)}")
    worker_cfg = cfg.get(name, {})
    if model is not None:
        worker_cfg = {**worker_cfg, "model": model}
    return REGISTRY[name](worker_cfg)

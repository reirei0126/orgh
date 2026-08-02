"""orgh doctor: 実行前の疎通確認(HANDOFF タスク7)。

外部CLIのフラグ非互換・パス設定ミスを「全タスク謎のfailed」より前に検知する。
- worker/roles の各バイナリに --version で疎通
- prompts_dir のテンプレート存在
- vault の到達性と書き込み権限
- runs_dir の書き込み権限
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

_REQUIRED_PROMPTS = ("planner.md", "reviewer.md", "retro.md",
                     "worker_preamble.md", "replan.md")


def _check_binary(name: str, bin_path: str) -> tuple[bool, str]:
    try:
        r = subprocess.run([bin_path, "--version"], capture_output=True,
                           text=True, timeout=15, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return False, f"NG {name}: {bin_path} が見つからない"
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"NG {name}: {bin_path} 実行失敗 ({e!r})"
    if r.returncode != 0:
        return False, f"NG {name}: {bin_path} --version がrc={r.returncode}"
    ver = (r.stdout or r.stderr).strip().splitlines()
    return True, f"OK {name}: {ver[0][:60] if ver else bin_path}"


def _binaries(cfg: dict) -> dict[str, str]:
    """検査対象バイナリ(worker/roles)を名前→パスで列挙。重複パスは1回だけ。"""
    bins: dict[str, str] = {}
    workers = cfg.get("workers", {})
    defaults = {"claude_code": "claude", "codex": "codex"}
    for name in workers.get("enabled", []):
        wcfg = workers.get(name, {}) or {}
        if name == "shell":
            argv = wcfg.get("argv") or []
            if argv:
                bins[f"worker:{name}"] = argv[0]
            continue
        bins[f"worker:{name}"] = wcfg.get("bin", defaults.get(name, name))
    for role, rcfg in (cfg.get("roles") or {}).items():
        bins[f"role:{role}"] = (rcfg or {}).get("bin", "claude")
    return bins


def run_doctor(cfg: dict) -> tuple[list[str], bool]:
    lines: list[str] = []
    ok = True

    seen: dict[str, tuple[bool, str]] = {}
    for name, bin_path in _binaries(cfg).items():
        if bin_path in seen:
            good, _ = seen[bin_path]
            lines.append(f"{'OK' if good else 'NG'} {name}: (= {bin_path})")
        else:
            good, line = _check_binary(name, bin_path)
            seen[bin_path] = (good, line)
            lines.append(line)
        ok &= seen[bin_path][0]

    lines.append("OK config: 検証済み")  # ここに到達した時点でスキーマ検証は通過

    prompts = Path(cfg.get("prompts_dir", "prompts")).expanduser()
    missing = [n for n in _REQUIRED_PROMPTS if not (prompts / n).exists()]
    if missing:
        ok = False
        lines.append(f"NG prompts_dir: {prompts} に不足 {missing}")
    else:
        lines.append(f"OK prompts_dir: {prompts}")

    vault = (cfg.get("vault") or {}).get("path")
    if vault:
        vp = Path(vault).expanduser()
        if not vp.is_dir():
            ok = False
            lines.append(f"NG vault: {vp} に到達できない")
        elif not os.access(vp, os.W_OK):
            ok = False
            lines.append(f"NG vault: {vp} に書き込めない")
        else:
            lines.append(f"OK vault: {vp}")
    else:
        lines.append("-- vault: 未設定(watch/scanを使わないなら問題なし)")

    runs = Path(cfg.get("runs_dir", "runs")).expanduser()
    try:
        runs.mkdir(parents=True, exist_ok=True)
        probe = runs / ".doctor_probe"
        probe.write_text("ok")
        probe.unlink()
        lines.append(f"OK runs_dir: {runs}")
    except OSError as e:
        ok = False
        lines.append(f"NG runs_dir: {runs} に書き込めない ({e!r})")

    return lines, ok

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
                     "worker_preamble.md", "replan.md", "gc.md")


def _check_binary(name: str, bin_path: str) -> dict:
    """1バイナリの疎通確認結果を {name, ok, detail} で返す。

    detail は OK/NG 判定文言を含まない、名前を除いた説明部分のみ
    (run_doctor のテキスト行・doctor_payload の両方から共有するため)。
    """
    try:
        r = subprocess.run([bin_path, "--version"], capture_output=True,
                           text=True, timeout=15, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return {"name": name, "ok": False, "detail": f"{bin_path} が見つからない"}
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"name": name, "ok": False,
                "detail": f"{bin_path} 実行失敗 ({e!r})"}
    if r.returncode != 0:
        return {"name": name, "ok": False,
                "detail": f"{bin_path} --version がrc={r.returncode}"}
    ver = (r.stdout or r.stderr).strip().splitlines()
    return {"name": name, "ok": True,
            "detail": ver[0][:60] if ver else bin_path}


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


def _run_checks(cfg: dict) -> list[dict]:
    """全チェックを {name, ok, detail, prefix?} のリストで返す。

    prefix はテキスト行の先頭記号(OK/NG以外、例: 未設定を示す "--")を
    明示したいチェックにのみ付く。省略時は ok から "OK"/"NG" を導出する。
    run_doctor(テキスト) と doctor_payload(JSON) が同じ結果を共有する。
    """
    checks: list[dict] = []

    seen: dict[str, dict] = {}
    for name, bin_path in _binaries(cfg).items():
        if bin_path in seen:
            prev = seen[bin_path]
            checks.append({"name": name, "ok": prev["ok"],
                           "detail": f"(= {bin_path})"})
        else:
            c = _check_binary(name, bin_path)
            seen[bin_path] = c
            checks.append(c)

    # ここに到達した時点でスキーマ検証は通過
    checks.append({"name": "config", "ok": True, "detail": "検証済み"})

    # rolesはスキーマ上は任意だが、planning/review/retroの実行時に必須
    # (欠けているとdoctor全OKでも初回planでKeyErrorになる)
    roles = cfg.get("roles") or {}
    # キーが在るだけでは足りない: roles.planner: null のような値も実行時に落ちる
    bad_roles = [r for r in ("planner", "reviewer", "retro")
                 if not isinstance(roles.get(r), dict)]
    if bad_roles:
        checks.append({"name": "roles", "ok": False,
                       "detail": f"必須roleが未定義または設定が空 {bad_roles}"
                                 "(plan/review/retroの実行時に失敗する)"})
    else:
        checks.append({"name": "roles", "ok": True,
                       "detail": "planner/reviewer/retro 定義あり"})

    prompts = Path(cfg.get("prompts_dir", "prompts")).expanduser()
    missing = [n for n in _REQUIRED_PROMPTS if not (prompts / n).exists()]
    if missing:
        checks.append({"name": "prompts_dir", "ok": False,
                       "detail": f"{prompts} に不足 {missing}"})
    else:
        checks.append({"name": "prompts_dir", "ok": True, "detail": str(prompts)})

    vault = (cfg.get("vault") or {}).get("path")
    if vault:
        vp = Path(vault).expanduser()
        if not vp.is_dir():
            checks.append({"name": "vault", "ok": False,
                           "detail": f"{vp} に到達できない"})
        elif not os.access(vp, os.W_OK):
            checks.append({"name": "vault", "ok": False,
                           "detail": f"{vp} に書き込めない"})
        else:
            checks.append({"name": "vault", "ok": True, "detail": str(vp)})
    else:
        checks.append({"name": "vault", "ok": True, "prefix": "--",
                       "detail": "未設定(watch/scanを使わないなら問題なし)"})

    runs = Path(cfg.get("runs_dir", "runs")).expanduser()
    try:
        runs.mkdir(parents=True, exist_ok=True)
        probe = runs / ".doctor_probe"
        probe.write_text("ok")
        probe.unlink()
        checks.append({"name": "runs_dir", "ok": True, "detail": str(runs)})
    except OSError as e:
        checks.append({"name": "runs_dir", "ok": False,
                       "detail": f"{runs} に書き込めない ({e!r})"})

    return checks


def _format_line(check: dict) -> str:
    prefix = check.get("prefix") or ("OK" if check["ok"] else "NG")
    return f"{prefix} {check['name']}: {check['detail']}"


def run_doctor(cfg: dict) -> tuple[list[str], bool]:
    checks = _run_checks(cfg)
    lines = [_format_line(c) for c in checks]
    ok = all(c["ok"] for c in checks)
    return lines, ok


def doctor_payload(cfg: dict) -> dict:
    """orgh doctor --json 用のペイロード(機械可読)。"""
    checks = _run_checks(cfg)
    return {
        "ok": all(c["ok"] for c in checks),
        "checks": [{"name": c["name"], "ok": c["ok"], "detail": c["detail"]}
                   for c in checks],
    }

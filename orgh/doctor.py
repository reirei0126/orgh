"""orgh doctor: 実行前の疎通確認(HANDOFF タスク7)。

外部CLIのフラグ非互換・パス設定ミスを「全タスク謎のfailed」より前に検知する。
- worker/roles の各バイナリに --version で疎通
- prompts_dir のテンプレート存在
- vault の到達性と書き込み権限
- runs_dir の書き込み権限
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_REQUIRED_PROMPTS = ("planner.md", "reviewer.md", "retro.md",
                     "worker_preamble.md", "replan.md", "gc.md")

_AUTH_CHECK_TIMEOUT = 15


def _check_worker_auth(worker_kind: str, bin_path: str) -> tuple[str, str]:
    """ワーカー種別ごとの非対話認証状態確認。(auth_state, detail断片) を返す。

    第2期P0-1(G-07)調査結果(2026-08-10、実機のclaude/codex CLIで個別調査):
    - claude_code: `claude auth status --json` が対話ログインを要求せず、
      課金対象のAPI呼び出しも発生させずに(実測 <0.2秒で返る、ローカルの
      認証情報を読むだけと見られる)ローカル認証状態を返す非対話サブコマンド
      として存在する(`claude auth --help` で確認)。`{"loggedIn": bool, ...}`
      を返すのでこれで判定する。
    - codex: `codex login status` が同様に非対話・即時(実測 <0.1秒)。
      `--json` 相当のオプションは無い(`codex login status --help` で確認済み、
      機械可読フラグは存在しない)ためテキスト出力を判定する。終了コード0かつ
      出力に "logged in" を含む場合のみ認証済みとみなす。未ログイン時の実際の
      出力文言は、実機の認証状態を破壊せずには確認できなかった(ログアウトは
      破壊的操作のため本調査では実施しない) — それ以外は安全側に倒して
      「認証切れ」として扱う(疎通は取れるのに黙って"OK"と表示する方が
      G-07が問題視した「嘘をつくUI」を再生産するため)。
    - shell: 任意のCLI(gemini/llm等)をargvテンプレートで叩く汎用アダプタで
      あり、ワーカーごとに認証確認コマンドの形式が異なるため統一的な
      非対話確認手段が無い。技術的に確認不可能と判断し、無条件で
      unverified を返す(無条件のOK表示にしないことがG-07対応の要件)。
    """
    if worker_kind == "claude_code":
        try:
            r = subprocess.run([bin_path, "auth", "status", "--json"],
                               capture_output=True, text=True,
                               timeout=_AUTH_CHECK_TIMEOUT,
                               stdin=subprocess.DEVNULL)
        except (subprocess.TimeoutExpired, OSError) as e:
            return "unverified", f"認証未確認(認証確認コマンド実行失敗: {e!r})"
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            return ("unverified",
                    "認証未確認(auth status --json の出力を解釈できない)")
        if data.get("loggedIn"):
            return "ok", "認証: 確認済み"
        return "failed", "認証切れ(claude auth login での再ログインが必要)"

    if worker_kind == "codex":
        try:
            r = subprocess.run([bin_path, "login", "status"],
                               capture_output=True, text=True,
                               timeout=_AUTH_CHECK_TIMEOUT,
                               stdin=subprocess.DEVNULL)
        except (subprocess.TimeoutExpired, OSError) as e:
            return "unverified", f"認証未確認(認証確認コマンド実行失敗: {e!r})"
        out = f"{r.stdout}\n{r.stderr}".lower()
        if r.returncode == 0 and "logged in" in out:
            return "ok", "認証: 確認済み"
        return "failed", "認証切れ(codex login での再ログインが必要)"

    return ("unverified",
            "認証未確認(このワーカー種別は非対話的な認証確認手段に非対応)")


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
        if not isinstance(wcfg, dict):
            # workers.claude_code: "invalid" のような値でdoctor自体が
            # AttributeErrorで死なないよう、NGチェック(binが不正)へ流す
            bins[f"worker:{name}"] = None
            continue
        if name == "shell":
            # argvが欠落・空・非文字列要素なら黙って検査対象から外すのではなく
            # NGにする(enabledなのに実行時TypeErrorになる構成をdoctorが見逃す)
            argv = wcfg.get("argv")
            if (isinstance(argv, list) and argv
                    and all(isinstance(a, str) for a in argv)):
                bins[f"worker:{name}"] = argv[0]
            else:
                bins[f"worker:{name}"] = None
            continue
        bins[f"worker:{name}"] = wcfg.get("bin", defaults.get(name, name))
    for role, rcfg in (cfg.get("roles") or {}).items():
        rcfg = rcfg if isinstance(rcfg, dict) else {}
        bins[f"role:{role}"] = rcfg.get("bin", "claude")
    return bins


def _augment_worker_auth(check: dict, worker_kind: str, bin_path: str) -> None:
    """worker:<name> チェックに auth_state を付与し、detail に認証状態を追記する。

    auth_state=="failed" のときは疎通が取れていても ok を False に落とす
    (認証切れを「OK」と表示しない — G-07が問題視した「嘘をつくUI」の解消)。
    """
    auth_state, auth_detail = _check_worker_auth(worker_kind, bin_path)
    check["auth_state"] = auth_state
    check["detail"] = f"{check['detail']} / {auth_detail}"
    if auth_state == "failed":
        check["ok"] = False


def _run_checks(cfg: dict) -> list[dict]:
    """全チェックを {name, ok, detail, kind, auth_state, prefix?} のリストで返す。

    prefix はテキスト行の先頭記号(OK/NG以外、例: 未設定を示す "--")を
    明示したいチェックにのみ付く。省略時は ok から "OK"/"NG" を導出する。
    run_doctor(テキスト) と doctor_payload(JSON) が同じ結果を共有する。

    kind は全チェック共通で常に "connectivity"(第2期P0-1・API.md §1.3。
    "auth" は疎通を介さない専用チェック行を将来追加する場合の予約値で、
    第2期時点では出力しない)。auth_state は worker:<name> のみ意味を持ち
    ("ok"/"unverified"/"failed")、それ以外は常に "n/a"。
    """
    checks: list[dict] = []

    seen: dict[str, dict] = {}
    for name, bin_path in _binaries(cfg).items():
        is_worker = name.startswith("worker:")
        worker_kind = name.split(":", 1)[1] if is_worker else None
        # bin: null や数値のような壊れた値をsubprocessへ渡すと、doctor自体が
        # 未捕捉TypeErrorで死んで診断表を返せなくなる。NGチェックに変換する
        if not isinstance(bin_path, str) or not bin_path.strip():
            c = {"name": name, "ok": False,
                 "detail": f"binが不正な値 ({bin_path!r})",
                 "auth_state": "n/a"}
            if is_worker:
                c["auth_state"] = "unverified"
                c["detail"] += " / 認証未確認(疎通確認自体が失敗しているため確認できない)"
            checks.append(c)
            continue
        if bin_path in seen:
            prev = seen[bin_path]
            c = {"name": name, "ok": prev["ok"], "detail": f"(= {bin_path})",
                 "auth_state": "n/a"}
            if is_worker:
                _augment_worker_auth(c, worker_kind, bin_path)
            checks.append(c)
        else:
            c = _check_binary(name, bin_path)
            c["auth_state"] = "n/a"
            if is_worker:
                _augment_worker_auth(c, worker_kind, bin_path)
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

    for c in checks:
        c.setdefault("auth_state", "n/a")
        c["kind"] = "connectivity"

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
        "checks": [{"name": c["name"], "ok": c["ok"], "detail": c["detail"],
                    "kind": c["kind"], "auth_state": c["auth_state"]}
                   for c in checks],
    }

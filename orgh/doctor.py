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
from datetime import datetime
from pathlib import Path

from . import lease, listing

_REQUIRED_PROMPTS = ("planner.md", "reviewer.md", "retro.md",
                     "worker_preamble.md", "replan.md", "gc.md")

_AUTH_CHECK_TIMEOUT = 15

# unknown_mission診断のledger末尾に含める件数(全読みを避ける目安)
_LEDGER_TAIL_LINES = 5


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


def _read_ledger_tail(mission_dir: Path, n: int = _LEDGER_TAIL_LINES) -> list[dict]:
    """ledger.jsonl末尾n件を人間の突合材料として返す。壊れた行は無視する。"""
    fp = mission_dir / "ledger.jsonl"
    if not fp.exists():
        return []
    try:
        lines = [ln for ln in fp.read_text(errors="replace").splitlines()
                 if ln.strip()]
    except OSError:
        return []
    out: list[dict] = []
    for ln in lines[-n:]:
        try:
            ev = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict):
            out.append(ev)
    return out


def _branch_exists(workdir: str | None, branch: str) -> bool | None:
    """workdir(gitリポ)にbranchが存在するか。判定不能(workdir欠損等)はNone。"""
    if not workdir or not Path(workdir).is_dir():
        return None
    try:
        r = subprocess.run(
            ["git", "-C", workdir, "rev-parse", "--verify", "--quiet",
             f"refs/heads/{branch}"],
            capture_output=True, text=True, timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode not in (0, 1):
        return None
    return r.returncode == 0


def _unknown_mission_checks(cfg: dict) -> list[dict]:
    """unknown(実行中系タスクを抱えたままleaseが失効)ミッションの復旧導線。

    orgh/listing.py(orgh list と同一の"unknown"導出規則)が拾ったミッション
    それぞれについて、人間が復旧を判断するための突合情報 — 成果物(タスク
    ブランチ)の有無、ledger末尾のイベント、leaseに記録されたpid/generation
    のプロセスが実在するか — を並べて提示するだけの読み取り専用チェック。
    自動での再実行・状態変更は一切行わない(判断と実行は人間が行う)。
    """
    runs_dir = cfg.get("runs_dir", "runs")
    try:
        report = listing.list_missions_report(runs_dir)
    except OSError:
        return []

    checks: list[dict] = []
    for m in report["missions"]:
        if m["status"] != "unknown":
            continue
        mission_id = m["mission_id"]
        mission_dir = Path(runs_dir) / mission_id
        try:
            mission_json = json.loads(
                (mission_dir / "mission.json").read_text())
        except (OSError, json.JSONDecodeError):
            mission_json = {}

        tasks_info = []
        for t in mission_json.get("tasks", []):
            branch = t.get("branch")
            tasks_info.append({
                "id": t.get("id"), "status": t.get("status"),
                "branch": branch,
                "branch_exists": (_branch_exists(t.get("workdir"), branch)
                                  if branch else None),
            })

        lease_rec = lease.read(mission_dir)
        lease_info = None
        if lease_rec is not None:
            lease_info = {
                "pid": lease_rec.pid,
                "generation": lease_rec.generation,
                "heartbeat_at": lease_rec.heartbeat_at,
                "process_alive": lease.pid_alive(lease_rec.pid),
            }

        checks.append({
            "name": f"unknown_mission:{mission_id}",
            # 環境異常(認証切れ・バイナリ欠損等)と同列の"NG"にはしない:
            # これは復旧要否を人間が判断するための情報提示であって、doctor
            # 自体が失敗しているわけではない。vaultチェックの「未設定」と
            # 同じ prefix="--" 規約(ok=Trueのまま非OK/NGの中立表示)を使う
            # (designerペルソナ実機レビュー2026-08-15: "NG"表示だと本当の
            # 環境異常と見分けがつかないという指摘の是正)
            "ok": True,
            "prefix": "--",
            "detail": (
                "実行中系タスクを抱えたままleaseが失効(unknown)。"
                "自動再実行はしない — diagnosticsの成果物・ledger・"
                "lease pidを見て人間が復旧を判断すること"),
            "kind": "recovery",
            "auth_state": "n/a",
            "diagnostics": {
                "tasks": tasks_info,
                "ledger_tail": _read_ledger_tail(mission_dir),
                "lease": lease_info,
            },
        })
    return checks


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
        # role(planner/reviewer/retro)はClaudeCodeAdapter経由で実行されるため、
        # workerと同じ認証チェックを適用する。roleだけ認証切れのCLIを指す構成で
        # doctorが全OKを返すと、実ミッションのplan/reviewで初めて認証エラーになる
        is_role = name.startswith("role:")
        worker_kind = (name.split(":", 1)[1] if is_worker
                       else "claude_code" if is_role else None)
        # bin: null や数値のような壊れた値をsubprocessへ渡すと、doctor自体が
        # 未捕捉TypeErrorで死んで診断表を返せなくなる。NGチェックに変換する
        if not isinstance(bin_path, str) or not bin_path.strip():
            c = {"name": name, "ok": False,
                 "detail": f"binが不正な値 ({bin_path!r})",
                 "auth_state": "n/a"}
            if is_worker or is_role:
                c["auth_state"] = "unverified"
                c["detail"] += " / 認証未確認(疎通確認自体が失敗しているため確認できない)"
            checks.append(c)
            continue
        if bin_path in seen:
            prev = seen[bin_path]
            c = {"name": name, "ok": prev["ok"], "detail": f"(= {bin_path})",
                 "auth_state": "n/a"}
            if is_worker or is_role:
                _augment_worker_auth(c, worker_kind, bin_path)
            checks.append(c)
        else:
            c = _check_binary(name, bin_path)
            c["auth_state"] = "n/a"
            if is_worker or is_role:
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

    # unknown状態ミッションの復旧導線は上のconnectivity一括設定の対象外
    # (kind="recovery"のまま出す)なので、ループの後に追加する
    checks.extend(_unknown_mission_checks(cfg))

    return checks


def _format_line(check: dict) -> str:
    prefix = check.get("prefix") or ("OK" if check["ok"] else "NG")
    return f"{prefix} {check['name']}: {check['detail']}"


def _fmt_ts(ts) -> str:
    """epoch秒を人間可読な日時へ整形する。orgh/cli.py の `list` テキスト出力
    (`_dt()`、`%m-%d %H:%M`)と表記を揃えること — 同一CLI内で時刻表示の
    書式が割れていると読み手が混乱する(designerペルソナ実機レビューで指摘)。
    ts欠損・型不正はraw値そのままを返す(隠さず見せる)。"""
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return str(ts)
    try:
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return str(ts)


def _format_diagnostics_lines(check: dict) -> list[str]:
    """unknown_missionチェックの突合情報をテキスト出力向けに整形する。
    人間が復旧を判断するための材料を並べるだけで、判断や実行はしない。

    --json では生epoch秒(diagnostics.lease.heartbeat_at / ledger_tail[].ts)
    をそのまま返すが、ここ(テキスト表示)では人間可読な日時に整形する。
    """
    diag = check.get("diagnostics")
    if not diag:
        return []
    lines = []
    lease_info = diag.get("lease")
    if lease_info is None:
        lines.append("    lease: なし(記録が残っていない)")
    else:
        lines.append(
            f"    lease: pid={lease_info['pid']} "
            f"generation={lease_info['generation']} "
            f"heartbeat_at={_fmt_ts(lease_info['heartbeat_at'])} "
            f"process_alive={lease_info['process_alive']}")
    for t in diag.get("tasks", []):
        if t.get("branch"):
            lines.append(
                f"    task {t['id']} [{t['status']}]: "
                f"branch={t['branch']} exists={t['branch_exists']}")
        else:
            lines.append(f"    task {t['id']} [{t['status']}]: "
                         "branch=(worktree未使用)")
    tail = diag.get("ledger_tail") or []
    if tail:
        lines.append("    ledger末尾:")
        for ev in tail:
            lines.append(
                f"      {ev.get('event')} task={ev.get('task', '-')} "
                f"ts={_fmt_ts(ev.get('ts'))}")
    return lines


def run_doctor(cfg: dict) -> tuple[list[str], bool]:
    checks = _run_checks(cfg)
    lines: list[str] = []
    for c in checks:
        lines.append(_format_line(c))
        lines.extend(_format_diagnostics_lines(c))
    ok = all(c["ok"] for c in checks)
    return lines, ok


def _check_to_json(c: dict) -> dict:
    """checkをJSON出力形式へ。既存キー(name/ok/detail/kind/auth_state)は
    従来どおり固定で出す。diagnostics(unknown_mission復旧情報)は存在する
    checkのみ追加で含める(既存checkの形は変えない、追加のみ)。"""
    out = {"name": c["name"], "ok": c["ok"], "detail": c["detail"],
           "kind": c["kind"], "auth_state": c["auth_state"]}
    if "diagnostics" in c:
        out["diagnostics"] = c["diagnostics"]
    return out


def doctor_payload(cfg: dict) -> dict:
    """orgh doctor --json 用のペイロード(機械可読)。"""
    checks = _run_checks(cfg)
    return {
        "ok": all(c["ok"] for c in checks),
        "checks": [_check_to_json(c) for c in checks],
    }

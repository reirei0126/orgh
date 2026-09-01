"""箱庭事務局の記帳(agency)。economy-ledger.md へ決着行を追記する純粋モジュール。

notify.mission_settled_event が作る mission.settled イベントを入力に、
起案者の経済台帳(private/agents/<agent_id>/economy-ledger.md)へ
「支出(実費)」と「給料」の行を追記する。

設計上の約束:
- 列構成(日付|種別|金額|残高|摘要)・ヘッダ・既存行は一切変更しない(追記のみ)
- 現在時刻を読まない(dateは引数)。同じ入力なら常に同じ行を返す
- 摘要末尾に短縮event_id(8桁)を必ず含め、それを冪等性キーに使う
  (同一イベントの二重記帳を already_recorded で弾く)
- dry_run既定はTrue。cfgにキーが無いときもTrue扱い(fail-safe。
  配線ミスで実台帳が勝手に書き換わることを防ぐ)

スケジューラ等の発火点への配線は別タスクで行う。ここでは解決・生成・
追記の関数のみを提供する。
"""
from __future__ import annotations

import datetime
import pathlib
import re

from .state import Mission, RunStore

DEFAULT_AGENTS_DIR = "private/agents"
DEFAULT_SALARY_USD = 3.0
LEDGER_FILENAME = "economy-ledger.md"

_SUMMARY_MAX = 40
_SHORT_ID_LEN = 8

# 「起案: 田中和臣(agent-001)」「起案者: 森本縁(agent-002・採用担当)」の双方に当たる。
# 括弧は全角「()」・半角「()」の両方を受理し、括弧内の先頭に来る agent-<数字> を拾う。
_DRAFTER_RE = re.compile(
    r"起案(?:者)?\s*[::]\s*[^\n(()]*[((]\s*(agent-\d+)")

_BALANCE_COLUMN = 3  # 日付|種別|金額|残高|摘要 の0始まり列位置
_HEADER_CELLS = {"日付", "種別", "金額", "残高", "摘要"}


def resolve_drafter(context_digest: str) -> str | None:
    """ミッションノート本文から起案者の agent_id を機械的に解決する。

    「起案: <氏名>(<agent_id>)」行(全角・半角括弧の双方)を探し、
    agent_id(例 "agent-003")を返す。行が無い場合や、複数行が別々の
    agent_id を指していて一意に決められない場合は None を返す
    (記帳先を誤るくらいなら記帳しない、という側に倒す)。例外は投げない。"""
    if not context_digest:
        return None
    found = {m.group(1) for m in _DRAFTER_RE.finditer(context_digest)}
    if len(found) != 1:
        return None
    return found.pop()


def _table_rows(text: str) -> list[tuple[int, list[str]]]:
    """(行番号, セル列) の一覧。ヘッダ行・区切り行(|---|---|)は含まない。"""
    rows: list[tuple[int, list[str]]] = []
    for i, line in enumerate(text.split("\n")):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells and all(set(c) <= {"-", ":"} and c for c in cells):
            continue          # |---|---| の区切り行
        if _HEADER_CELLS <= set(cells):
            continue          # ヘッダ行
        rows.append((i, cells))
    return rows


def parse_last_balance(text: str) -> float:
    """Markdown表の最終データ行の「残高」列を返す。表が無ければ ValueError。"""
    rows = _table_rows(text)
    if not rows:
        raise ValueError("経済台帳に表のデータ行が見つからない")
    _, cells = rows[-1]
    if len(cells) <= _BALANCE_COLUMN:
        raise ValueError(f"最終データ行の列数が足りない: {cells!r}")
    raw = cells[_BALANCE_COLUMN].replace("+", "")
    try:
        return float(raw)
    except ValueError as e:
        raise ValueError(f"残高列を数値として読めない: {cells[_BALANCE_COLUMN]!r}") from e


def _amount(value: float) -> str:
    """符号付き金額表記(-1.234 / +3.000)。小数第3位で丸める。"""
    return f"{round(value, 3):+.3f}"


def _balance(value: float) -> str:
    return f"{round(value, 3):.3f}"


def _note(mission_id: str, kind: str, summary: str, event_id: str) -> str:
    """摘要列。末尾の #<短縮event_id> が二重記帳の検出キーになる。"""
    head = (summary or "")[:_SUMMARY_MAX]
    # 表を壊さないための最小限の無害化(切り出し後に行う。字数はsummary基準)
    head = head.replace("\n", " ").replace("|", "/")
    return f"{mission_id} {kind}({head}) #{short_event_id(event_id)}"


def short_event_id(event_id: str) -> str:
    return (event_id or "")[:_SHORT_ID_LEN]


def build_rows(*, event: dict, salary_usd: float, date: str,
               last_balance: float) -> list[str]:
    """決着イベントから台帳へ追記する行(Markdown表の1行文字列)を作る。

    outcome=done なら [支出行, 給料行] の2行、failed なら [支出行] の1行。
    残高は行間で連鎖する(給料行の残高 = 支出行の残高 + salary_usd)。"""
    outcome = event.get("outcome")
    if outcome not in ("done", "failed"):
        raise ValueError(f"不正なoutcome: {outcome!r}(doneまたはfailedのみ許可)")

    mission_id = event.get("mission_id", "")
    event_id = event.get("event_id", "")
    summary = event.get("summary", "")
    cost = float(event.get("cost_usd", 0.0))

    balance = round(last_balance - cost, 3)
    rows = [
        f"| {date} | 支出 | {_amount(-cost)} | {_balance(balance)} | "
        f"{_note(mission_id, '実費', summary, event_id)} |"
    ]
    if outcome == "done":
        balance = round(balance + salary_usd, 3)
        rows.append(
            f"| {date} | 給料 | {_amount(salary_usd)} | {_balance(balance)} | "
            f"{_note(mission_id, '給料', summary, event_id)} |")
    return rows


def already_recorded(text: str, event_id: str) -> bool:
    """同一イベントの行が既に台帳にあるか(摘要末尾の #<短縮event_id> で判定)。"""
    short = short_event_id(event_id)
    if not short:
        return False
    return f"#{short}" in text


def ledger_path(*, cfg: dict, agent_id: str,
                repo_root: pathlib.Path) -> pathlib.Path:
    agency = (cfg or {}).get("agency") or {}
    agents_dir = agency.get("agents_dir") or DEFAULT_AGENTS_DIR
    return pathlib.Path(repo_root) / agents_dir / agent_id / LEDGER_FILENAME


def _append_rows(text: str, rows: list[str]) -> str:
    """表の最終データ行の直後に行を差し込む(表より後ろの本文は壊さない)。"""
    lines = text.split("\n")
    table = _table_rows(text)
    if not table:
        raise ValueError("経済台帳に表のデータ行が見つからない")
    insert_at = table[-1][0] + 1
    return "\n".join(lines[:insert_at] + rows + lines[insert_at:])


def record(*, event: dict, cfg: dict, agent_id: str, date: str,
           repo_root: pathlib.Path) -> dict:
    """決着イベントを agent_id の経済台帳へ記帳する。

    返り値の action:
      - "skipped"     : 台帳が無い(reason=no_ledger)/ 記帳済み(reason=duplicate)
      - "would_write" : dry_run(既定)。ファイルは1バイトも変更しない
      - "written"     : 追記した
    """
    path = ledger_path(cfg=cfg, agent_id=agent_id, repo_root=repo_root)
    if not path.is_file():
        return {"action": "skipped", "reason": "no_ledger", "path": str(path)}

    text = path.read_text(encoding="utf-8")
    if already_recorded(text, event.get("event_id", "")):
        return {"action": "skipped", "reason": "duplicate", "path": str(path)}

    agency = (cfg or {}).get("agency") or {}
    salary_usd = agency.get("salary_usd", DEFAULT_SALARY_USD)
    rows = build_rows(event=event, salary_usd=float(salary_usd), date=date,
                      last_balance=parse_last_balance(text))

    # dry_runはキー欠落時もTrue扱い(fail-safe)
    if agency.get("dry_run", True):
        return {"action": "would_write", "rows": rows, "path": str(path)}

    path.write_text(_append_rows(text, rows), encoding="utf-8")
    return {"action": "written", "rows": rows, "path": str(path)}


def on_settled(store: RunStore, cfg: dict, mission: Mission, event: dict, *,
               date: str | None = None,
               repo_root: pathlib.Path | None = None) -> None:
    """mission.settledの発行直後にscheduler側から1行で呼ぶ配線点。

    起案者(resolve_drafter)を解決できないミッションは記帳対象外とし、
    台帳ファイルには一切触れない(agency.skipped reason=no_drafter のみ記録)。
    それ以外はrecord()の結果に応じて ledger.jsonl へ
    agency.would_write / agency.recorded / agency.skipped のいずれかを記録する。
    記帳処理の例外はミッション進行を止めない(notify.emitのwebhook失敗時と
    同じ方針。agency.failedに留める)。"""
    try:
        agent_id = resolve_drafter(mission.context_digest)
        if agent_id is None:
            store.log("agency.skipped", reason="no_drafter",
                      event_id=event.get("event_id"), mission_id=mission.id)
            return

        result = record(
            event=event, cfg=cfg, agent_id=agent_id,
            date=date or datetime.date.today().isoformat(),
            repo_root=repo_root or pathlib.Path.cwd())

        action = result["action"]
        if action == "would_write":
            store.log("agency.would_write", event_id=event.get("event_id"),
                      agent=agent_id, rows=result["rows"], path=result["path"])
        elif action == "written":
            store.log("agency.recorded", event_id=event.get("event_id"),
                      agent=agent_id, rows=result["rows"], path=result["path"])
        else:  # skipped(no_ledger / duplicate)
            store.log("agency.skipped", reason=result["reason"],
                      event_id=event.get("event_id"), agent=agent_id,
                      path=result.get("path"))
    except Exception as exc:
        store.log("agency.failed", error=str(exc)[:300],
                  event_id=event.get("event_id"), mission_id=mission.id)

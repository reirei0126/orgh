"""箱庭事務局の記帳モジュール(orgh/agency.py)の単体テスト。

- 起案行の解決(全角括弧・半角括弧・行なし・複数解釈)
- 最終残高のパース
- done時2行・failed時1行と、行間での残高連鎖
- 摘要末尾の短縮event_id(8桁)と5列構成
- 同一event_idでの追記スキップ(duplicate)
- dry_run時にファイルが1バイトも変わらないこと

実台帳(private/agents/)は一切触らない。tmp_path に同形式のコピーを作って検証する。
"""
from __future__ import annotations

import pathlib

import pytest

from orgh import agency, notify
from orgh.state import Mission, Task

# private/agents/agent-001/economy-ledger.md と同じ形式(列構成・ヘッダ)のコピー
LEDGER_SAMPLE = """# 田中和臣 経済台帳(記帳者: セッションAI・手動箱庭)

| 日付 | 種別 | 金額 | 残高 | 摘要 |
|---|---|---|---|---|
| 2026-08-24 | 付与 | +30.0 | 30.0 | 初期残高(雇用契約§3) |
| 2026-08-25 | 支出 | -6.378 | 23.622 | 初ミッションdf1a8a35実費(devenv復旧・上限8.0内) |
| 2026-08-25 | 給料 | +3.0 | 26.622 | df1a8a35 verdict合格(雇用契約§2・初給料) |
"""

# 表の後ろに本文が続く台帳(追記が後続本文を壊さないことの確認用)
LEDGER_WITH_TRAILER = LEDGER_SAMPLE + """
## 備考
- 残高の正本はこの表。tick費はインフラ費として帳簿外(設計§1)
"""


def _event(outcome: str = "done", *, cost_usd: float = 1.5,
           mission_id: str = "abcd1234") -> dict:
    m = Mission(id=mission_id, intent="試験ミッション", context_digest="(test)",
                tasks=[Task(id="t1", title="t", prompt="p", workdir=".",
                            acceptance=["ok"])])
    return notify.mission_settled_event(m, outcome, cost_usd)


def _write_ledger(tmp_path: pathlib.Path, text: str = LEDGER_SAMPLE,
                  agent_id: str = "agent-001") -> pathlib.Path:
    d = tmp_path / "private" / "agents" / agent_id
    d.mkdir(parents=True)
    p = d / "economy-ledger.md"
    p.write_text(text, encoding="utf-8")
    return p


def _cfg(dry_run: bool = True, salary_usd: float = 3.0) -> dict:
    return {"agency": {"dry_run": dry_run, "agents_dir": "private/agents",
                       "salary_usd": salary_usd}}


class TestResolveDrafter:
    def test_全角括弧の起案行を解決する(self):
        note = "# ミッション\n起案: 与謝野問(agent-003)\n本文...\n"
        assert agency.resolve_drafter(note) == "agent-003"

    def test_半角括弧の起案行を解決する(self):
        note = "# ミッション\n起案: 田中和臣(agent-001)\n本文...\n"
        assert agency.resolve_drafter(note) == "agent-001"

    def test_起案者表記と括弧内の付記も受理する(self):
        note = "起案者: 森本縁(agent-002・採用担当)。#goは付けない。\n"
        assert agency.resolve_drafter(note) == "agent-002"

    def test_起案行が無ければNone(self):
        assert agency.resolve_drafter("# ミッション\n本文だけ\n") is None
        assert agency.resolve_drafter("") is None

    def test_agent_idの無い起案行はNone(self):
        assert agency.resolve_drafter("起案: 田中和臣(記帳者)\n") is None

    def test_複数の起案者が食い違えばNone(self):
        note = "起案: 田中和臣(agent-001)\n起案: 森本縁(agent-002)\n"
        assert agency.resolve_drafter(note) is None

    def test_同一起案者が複数行にあっても解決する(self):
        note = "起案: 田中和臣(agent-001)\n再掲 起案者: 田中和臣(agent-001)\n"
        assert agency.resolve_drafter(note) == "agent-001"


class TestParseLastBalance:
    def test_最終データ行の残高を返す(self):
        assert agency.parse_last_balance(LEDGER_SAMPLE) == 26.622

    def test_表の後ろに本文があっても最終データ行を見る(self):
        assert agency.parse_last_balance(LEDGER_WITH_TRAILER) == 26.622

    def test_表が無ければValueError(self):
        with pytest.raises(ValueError):
            agency.parse_last_balance("# 台帳\n表がまだ無い\n")


class TestBuildRows:
    def test_done時は支出行と給料行の2行で残高が連鎖する(self):
        rows = agency.build_rows(event=_event("done", cost_usd=1.5),
                                 salary_usd=3.0, date="2026-09-01",
                                 last_balance=26.622)
        assert len(rows) == 2
        spend, salary = rows
        assert "| 支出 |" in spend and "| 給料 |" in salary
        assert "-1.500" in spend
        assert "+3.000" in salary
        # 残高: 26.622 - 1.5 = 25.122 → +3.0 = 28.122(行間で連鎖)
        assert _cells(spend)[3] == "25.122"
        assert _cells(salary)[3] == "28.122"

    def test_failed時は支出行のみ1行(self):
        rows = agency.build_rows(event=_event("failed", cost_usd=0.75),
                                 salary_usd=3.0, date="2026-09-01",
                                 last_balance=10.0)
        assert len(rows) == 1
        assert _cells(rows[0])[1] == "支出"
        assert _cells(rows[0])[2] == "-0.750"
        assert _cells(rows[0])[3] == "9.250"

    def test_丸めは小数第3位(self):
        rows = agency.build_rows(event=_event("done", cost_usd=1.23456),
                                 salary_usd=3.0, date="2026-09-01",
                                 last_balance=5.0)
        assert _cells(rows[0])[2] == "-1.235"
        assert _cells(rows[0])[3] == "3.765"
        assert _cells(rows[1])[3] == "6.765"

    def test_dateは引数のものがそのまま日付列になる(self):
        rows = agency.build_rows(event=_event("done"), salary_usd=3.0,
                                 date="2026-12-31", last_balance=1.0)
        assert all(_cells(r)[0] == "2026-12-31" for r in rows)

    def test_不正なoutcomeはValueError(self):
        with pytest.raises(ValueError):
            agency.build_rows(event={"outcome": "cancelled"}, salary_usd=3.0,
                              date="2026-09-01", last_balance=1.0)


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


class TestRowShape:
    def test_行は5列で摘要末尾に短縮event_idを含む_suffix(self):
        event = _event("done", cost_usd=1.5, mission_id="mid-suffix")
        rows = agency.build_rows(event=event, salary_usd=3.0,
                                 date="2026-09-01", last_balance=26.622)
        short = event["event_id"][:8]
        assert len(short) == 8
        for row in rows:
            cells = _cells(row)
            assert len(cells) == 5, f"5列(日付|種別|金額|残高|摘要)でない: {row}"
            摘要 = cells[4]
            assert 摘要.endswith(f"#{short}"), 摘要
            assert 摘要.startswith("mid-suffix ")

    def test_摘要はsummaryの先頭40字までに収める(self):
        event = _event("done")
        event["summary"] = "あ" * 100
        rows = agency.build_rows(event=event, salary_usd=3.0,
                                 date="2026-09-01", last_balance=1.0)
        摘要 = _cells(rows[0])[4]
        assert "あ" * 40 in 摘要
        assert "あ" * 41 not in 摘要

    def test_摘要のパイプは表を壊さないよう置換される(self):
        event = _event("done")
        event["summary"] = "a|b|c"
        rows = agency.build_rows(event=event, salary_usd=3.0,
                                 date="2026-09-01", last_balance=1.0)
        assert len(_cells(rows[0])) == 5


class TestAlreadyRecorded:
    def test_短縮event_idが本文にあればTrue(self):
        event = _event("done")
        short = event["event_id"][:8]
        assert agency.already_recorded(f"| ... | x #{short} |", event["event_id"])

    def test_無ければFalse(self):
        assert not agency.already_recorded(LEDGER_SAMPLE, "0123456789abcdef")


class TestRecord:
    def test_台帳が無ければ書かずにskipped_no_ledger(self, tmp_path):
        res = agency.record(event=_event("done"), cfg=_cfg(dry_run=False),
                            agent_id="agent-999", date="2026-09-01",
                            repo_root=tmp_path)
        assert res["action"] == "skipped"
        assert res["reason"] == "no_ledger"
        assert not (tmp_path / "private").exists()

    def test_dry_runではファイルが1バイトも変わらない(self, tmp_path):
        path = _write_ledger(tmp_path)
        before = path.read_bytes()

        res = agency.record(event=_event("done"), cfg=_cfg(dry_run=True),
                            agent_id="agent-001", date="2026-09-01",
                            repo_root=tmp_path)

        assert res["action"] == "would_write"
        assert len(res["rows"]) == 2
        assert path.read_bytes() == before

    def test_dry_runはagencyキー欠落時も既定で有効(self, tmp_path):
        path = _write_ledger(tmp_path)
        before = path.read_bytes()

        res = agency.record(event=_event("done"), cfg={}, agent_id="agent-001",
                            date="2026-09-01", repo_root=tmp_path)

        assert res["action"] == "would_write"
        assert path.read_bytes() == before

    def test_dry_run_falseなら表の末尾に追記する(self, tmp_path):
        path = _write_ledger(tmp_path)

        res = agency.record(event=_event("done", cost_usd=1.5),
                            cfg=_cfg(dry_run=False), agent_id="agent-001",
                            date="2026-09-01", repo_root=tmp_path)

        assert res["action"] == "written"
        text = path.read_text(encoding="utf-8")
        # ヘッダ・既存行は不変(先頭からの一致)
        assert text.startswith(LEDGER_SAMPLE)   # ヘッダ・既存行は不変
        assert agency.parse_last_balance(text) == 28.122
        assert text.splitlines()[-2:] == res["rows"]

    def test_表より後ろの本文を壊さない(self, tmp_path):
        path = _write_ledger(tmp_path, LEDGER_WITH_TRAILER)

        agency.record(event=_event("done"), cfg=_cfg(dry_run=False),
                      agent_id="agent-001", date="2026-09-01",
                      repo_root=tmp_path)

        text = path.read_text(encoding="utf-8")
        assert "## 備考" in text
        assert text.index("| 2026-09-01 | 給料") < text.index("## 備考")

    def test_同一event_idの再記帳はduplicateでskipされる(self, tmp_path):
        path = _write_ledger(tmp_path)
        event = _event("done")

        first = agency.record(event=event, cfg=_cfg(dry_run=False),
                              agent_id="agent-001", date="2026-09-01",
                              repo_root=tmp_path)
        assert first["action"] == "written"
        after_first = path.read_bytes()

        second = agency.record(event=event, cfg=_cfg(dry_run=False),
                               agent_id="agent-001", date="2026-09-02",
                               repo_root=tmp_path)

        assert second["action"] == "skipped"
        assert second["reason"] == "duplicate"
        assert path.read_bytes() == after_first

    def test_duplicate判定はdry_runより先に効く(self, tmp_path):
        path = _write_ledger(tmp_path)
        event = _event("done")
        agency.record(event=event, cfg=_cfg(dry_run=False),
                      agent_id="agent-001", date="2026-09-01",
                      repo_root=tmp_path)

        res = agency.record(event=event, cfg=_cfg(dry_run=True),
                            agent_id="agent-001", date="2026-09-01",
                            repo_root=tmp_path)

        assert res == {"action": "skipped", "reason": "duplicate",
                       "path": str(path)}

    def test_failedは支出行だけを追記する(self, tmp_path):
        path = _write_ledger(tmp_path)

        res = agency.record(event=_event("failed", cost_usd=2.0),
                            cfg=_cfg(dry_run=False), agent_id="agent-001",
                            date="2026-09-01", repo_root=tmp_path)

        assert res["action"] == "written" and len(res["rows"]) == 1
        assert agency.parse_last_balance(path.read_text(encoding="utf-8")) == 24.622

    def test_agents_dirはcfgから解決される(self, tmp_path):
        d = tmp_path / "sandbox" / "agent-007"
        d.mkdir(parents=True)
        (d / "economy-ledger.md").write_text(LEDGER_SAMPLE, encoding="utf-8")
        cfg = {"agency": {"dry_run": True, "agents_dir": "sandbox"}}

        res = agency.record(event=_event("done"), cfg=cfg, agent_id="agent-007",
                            date="2026-09-01", repo_root=tmp_path)

        assert res["action"] == "would_write"
        assert res["path"] == str(d / "economy-ledger.md")

    def test_salary_usdはcfgの値を使う(self, tmp_path):
        _write_ledger(tmp_path)

        res = agency.record(event=_event("done", cost_usd=1.0),
                            cfg=_cfg(dry_run=True, salary_usd=5.0),
                            agent_id="agent-001", date="2026-09-01",
                            repo_root=tmp_path)

        assert _cells(res["rows"][1])[2] == "+5.000"
        assert _cells(res["rows"][1])[3] == "30.622"

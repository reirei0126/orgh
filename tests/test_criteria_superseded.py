"""台帳の注入をエントリ行に限定し、superseded_by メタタグを扱う。

実害: 2026-08-15のARCH-001/002失効時、台帳に取り消し線付きの旧文言を
残せず docs/ への退避を強いられた(criteria_context が空行以外の全行を
無差別に注入していたため)。詳細: docs/strategy/arch-001-002-superseded.md
"""
from __future__ import annotations

from pathlib import Path

from orgh.criteria import (append_entry, criteria_context, criteria_dir,
                           criteria_list_payload, criteria_list_text,
                           criteria_usage, next_id)


class TestNonEntryLinesIgnored:
    def test_heading_and_annotation_lines_not_injected(self, tmp_path):
        cdir = tmp_path / "criteria"
        cdir.mkdir()
        (cdir / "arch.md").write_text(
            "# ARCH台帳\n"
            "この台帳はアーキテクチャ判断を記録する。\n"
            "- ARCH-001 [norm]: 実在エントリ <!-- src:m1 d:2026-08-15 -->\n"
            "- 備考: これはエントリではない\n")
        ctx = criteria_context({"criteria_dir": str(cdir)})
        assert "実在エントリ" in ctx
        assert "ARCH台帳" not in ctx
        assert "この台帳はアーキテクチャ判断を記録する" not in ctx
        assert "備考" not in ctx

    def test_heading_and_annotation_lines_excluded_from_list_text(self, tmp_path):
        cdir = tmp_path / "criteria"
        cdir.mkdir()
        (cdir / "arch.md").write_text(
            "# 見出し\n"
            "- ARCH-001 [norm]: 実在エントリ <!-- src:m1 d:2026-08-15 -->\n")
        out = criteria_list_text({"criteria_dir": str(cdir)})
        assert "見出し" not in out
        assert "実在エントリ" in out


class TestSupersededMetaTag:
    def _cdir(self, tmp_path, extra_line: str = "") -> Path:
        cdir = tmp_path / "criteria"
        cdir.mkdir()
        (cdir / "arch.md").write_text(
            "- ARCH-001 [norm]: 旧文言 <!-- src:m1 d:2026-08-14 --> "
            "<!-- superseded_by:ARCH-003 -->\n"
            "- ARCH-003 [norm]: 新文言 <!-- src:m2 d:2026-08-15 -->\n"
            + extra_line)
        return cdir

    def test_superseded_entry_excluded_from_context(self, tmp_path):
        cdir = self._cdir(tmp_path)
        ctx = criteria_context({"criteria_dir": str(cdir)})
        assert "旧文言" not in ctx
        assert "新文言" in ctx

    def test_superseded_entry_shown_in_list_with_marker(self, tmp_path):
        cdir = self._cdir(tmp_path)
        out = criteria_list_text({"criteria_dir": str(cdir)})
        assert "[superseded → ARCH-003]" in out
        assert "旧文言" in out          # 履歴として本文自体は残る
        assert "新文言" in out

    def test_superseded_entry_included_in_next_id_scan(self, tmp_path):
        cdir = self._cdir(tmp_path)
        # ARCH-001とARCH-003が既にあるので、次はARCH-004(ARCH-002を
        # 飛ばして再利用しない=supersededでもnext_id走査に含まれる証拠)
        assert next_id(cdir, "ARCH") == "ARCH-004"

    def test_superseded_entry_id_not_reissued_even_if_gap(self, tmp_path):
        """supersededエントリのIDが走査から漏れていたら、空き番号として
        再発行されてしまう(ID重複の実害)。ここではARCH-002を意図的に
        飛ばした状態でnext_idがARCH-002を再発行しないことを確認する。"""
        cdir = tmp_path / "criteria"
        cdir.mkdir()
        (cdir / "arch.md").write_text(
            "- ARCH-001 [norm]: a <!-- src:m1 d:2026-08-14 -->\n"
            "- ARCH-002 [norm]: b (失効) <!-- src:m2 d:2026-08-14 --> "
            "<!-- superseded_by:ARCH-003 -->\n"
            "- ARCH-003 [norm]: c <!-- src:m3 d:2026-08-15 -->\n")
        assert next_id(cdir, "ARCH") == "ARCH-004"

    def test_superseded_entry_stays_in_citation_usage(self, tmp_path, cfg):
        """引用回数集計(criteria_usage)はミッションの裁定履歴から集計され、
        supersededになった後もそのIDへの過去の引用実績を保持し続ける
        (過去の裁定履歴の解釈を壊さないため)。"""
        import json

        cdir = self._cdir(tmp_path)
        cfg["criteria_dir"] = str(cdir)
        run_dir = Path(cfg["runs_dir"]) / "m1"
        run_dir.mkdir(parents=True)
        (run_dir / "ledger.jsonl").write_text(
            json.dumps({"ts": 1755200000.0, "event": "task.review",
                       "criteria_cited": ["ARCH-001"]}) + "\n")

        usage = criteria_usage(cfg)
        assert usage["ARCH-001"]["citation_count"] == 1

    def test_superseded_entry_present_in_list_payload(self, tmp_path):
        cdir = self._cdir(tmp_path)
        payload = criteria_list_payload({"criteria_dir": str(cdir)})
        ids = {e["id"] for e in payload["entries"]}
        assert {"ARCH-001", "ARCH-003"} <= ids


class TestBackwardCompatibleWithRealLedger:
    """既存の criteria/*.md (現33件)を一切変更せずに読める(後方互換)。"""

    def _real_criteria_dir(self) -> Path:
        return Path(__file__).resolve().parent.parent / "criteria"

    def test_real_ledger_parses_without_exception_and_all_injected(self):
        cdir = self._real_criteria_dir()
        cfg = {"criteria_dir": str(cdir)}

        expected_ids = []
        for p in sorted(cdir.glob("*.md")):
            if p.name.startswith("_"):
                continue
            for line in p.read_text().splitlines():
                if not line.strip():
                    continue
                import re
                m = re.match(r"^- ([A-Z]+-\d{3}) \[(norm|pref)\]:", line)
                if m:
                    expected_ids.append(m.group(1))

        assert len(expected_ids) == 33

        ctx = criteria_context(cfg, max_chars=1_000_000)
        for entry_id in expected_ids:
            assert entry_id in ctx

        payload = criteria_list_payload(cfg)
        assert {e["id"] for e in payload["entries"]} == set(expected_ids)


def test_criteria_context_max_chars_from_config(tmp_path):
    """注入上限はconfig `criteria_max_inject_chars` で拡大できる(既定4000)。"""
    from orgh.criteria import criteria_context
    cdir = tmp_path / "criteria"
    cdir.mkdir()
    # 1行約100字のエントリを60件 → 全量約6,000字(既定4000字を超える)
    lines = []
    for i in range(1, 61):
        pad = "x" * 70
        lines.append(f"- QA-{i:03d} [norm]: {pad} <!-- src:m d:2026-01-{(i % 28) + 1:02d} -->")
    (cdir / "qa.md").write_text("\n".join(lines) + "\n")

    base = {"criteria_dir": str(cdir)}
    injected_default = criteria_context(base).splitlines()
    assert len(injected_default) < 60  # 既定4000字では全件入らない前提の題材

    widened = criteria_context({**base, "criteria_max_inject_chars": 100000})
    assert len(widened.splitlines()) == 60  # config拡大で全件注入

    # 明示引数はconfigより優先(既存呼び出しの互換)
    narrowed = criteria_context({**base, "criteria_max_inject_chars": 100000},
                                max_chars=500)
    assert len(narrowed.splitlines()) < 10

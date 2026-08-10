"""基準台帳(criteria)の読み書きと文脈注入。戦略設計書 柱2の最小版。"""
from __future__ import annotations

from pathlib import Path

from orgh.criteria import append_entry, criteria_context, criteria_dir, next_id


class TestLedger:
    def test_empty_dir_returns_placeholder(self, tmp_path):
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        assert criteria_context(cfg) == "(no criteria yet)"

    def test_append_and_next_id(self, tmp_path):
        cdir = tmp_path / "criteria"
        line = append_entry(cdir, "design", "DESIGN", "norm",
                            "視覚検証なしの合格を信用しない", src="7307189e")
        assert "DESIGN-001 [norm]:" in line
        assert "src:7307189e" in line
        assert (cdir / "design.md").read_text().count("DESIGN-001") == 1
        assert next_id(cdir, "DESIGN") == "DESIGN-002"

    def test_next_id_scans_across_files(self, tmp_path):
        cdir = tmp_path / "criteria"
        append_entry(cdir, "design", "DESIGN", "norm", "a", src="m1")
        append_entry(cdir, "general", "DESIGN", "pref", "b", src="m2")
        assert next_id(cdir, "DESIGN") == "DESIGN-003"

    def test_context_packs_newest_first(self, tmp_path):
        cdir = tmp_path / "criteria"
        (cdir).mkdir()
        (cdir / "design.md").write_text(
            "- DESIGN-001 [norm]: 古い基準 <!-- src:m1 d:2020-01-01 -->\n"
            "- DESIGN-002 [norm]: 新しい基準 <!-- src:m2 d:2026-08-10 -->\n")
        ctx = criteria_context({"criteria_dir": str(cdir)}, max_chars=60)
        assert "新しい基準" in ctx      # 新しい行が優先で生き残る
        assert "古い基準" not in ctx

    def test_drafts_dir_excluded_from_context(self, tmp_path):
        cdir = tmp_path / "criteria"
        (cdir / "_drafts").mkdir(parents=True)
        (cdir / "_drafts" / "x.md").write_text("- FAKE-001 [norm]: 下書き\n")
        (cdir / "design.md").write_text(
            "- DESIGN-001 [norm]: 本採用 <!-- src:m1 d:2026-08-10 -->\n")
        ctx = criteria_context({"criteria_dir": str(cdir)})
        assert "本採用" in ctx and "下書き" not in ctx

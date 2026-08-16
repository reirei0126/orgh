"""`orgh criteria supersede <旧ID> <新ID>`: superseded_by メタタグの書き込み側。

読み取り側(criteria_context除外/list表示の`[superseded → ...]`/next_id走査に残存)
は tests/test_criteria_superseded.py で検証済み。本ファイルは「書き込み」操作
(supersede_entry と `orgh criteria supersede` サブコマンド)を検証する。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from orgh import cli
from orgh.criteria import (criteria_context, criteria_list_text, next_id,
                           supersede_entry)

from .conftest import write_config


def _write_ledger(cdir: Path) -> None:
    cdir.mkdir(parents=True)
    (cdir / "arch.md").write_text(
        "# ARCH台帳\n"
        "この台帳はアーキテクチャ判断を記録する。\n"
        "- ARCH-001 [norm]: 旧文言 <!-- src:m1 d:2026-08-14 -->\n"
        "- ARCH-002 [norm]: 無関係の文言 <!-- src:m2 d:2026-08-14 -->\n"
        "- ARCH-003 [norm]: 新文言 <!-- src:m3 d:2026-08-15 -->\n")


class TestSupersedeEntryFunction:
    def test_appends_superseded_by_tag_to_old_entry_line(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg = {"criteria_dir": str(cdir)}

        supersede_entry(cfg, "ARCH-001", "ARCH-003")

        target = next(l for l in (cdir / "arch.md").read_text().splitlines()
                      if l.startswith("- ARCH-001 "))
        assert "<!-- superseded_by:ARCH-003 -->" in target

    def test_old_entry_excluded_from_criteria_context(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg = {"criteria_dir": str(cdir)}

        supersede_entry(cfg, "ARCH-001", "ARCH-003")

        ctx = criteria_context(cfg)
        assert "旧文言" not in ctx
        assert "新文言" in ctx

    def test_old_entry_shown_in_list_with_superseded_marker(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg = {"criteria_dir": str(cdir)}

        supersede_entry(cfg, "ARCH-001", "ARCH-003")

        out = criteria_list_text(cfg)
        assert "[superseded → ARCH-003]" in out

    def test_old_id_stays_in_next_id_scan_and_is_not_reissued(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg = {"criteria_dir": str(cdir)}

        supersede_entry(cfg, "ARCH-001", "ARCH-003")

        assert next_id(cdir, "ARCH") == "ARCH-004"  # ARCH-001の再発行はしない

    def test_only_target_entry_line_changes_rest_byte_identical(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg = {"criteria_dir": str(cdir)}
        before = (cdir / "arch.md").read_text().split("\n")

        supersede_entry(cfg, "ARCH-001", "ARCH-003")

        after = (cdir / "arch.md").read_text().split("\n")
        assert len(before) == len(after)
        changed = [i for i, (b, a) in enumerate(zip(before, after)) if b != a]
        assert changed == [2]  # ARCH-001の行のみ
        assert before[2].startswith("- ARCH-001 ")

    def test_success_message_reports_old_and_new_id(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg = {"criteria_dir": str(cdir)}

        msg = supersede_entry(cfg, "ARCH-001", "ARCH-003")

        assert "ARCH-001" in msg
        assert "ARCH-003" in msg


class TestSupersedeEntryErrors:
    def test_nonexistent_new_id_raises_and_ledger_unchanged(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg = {"criteria_dir": str(cdir)}
        before = (cdir / "arch.md").read_text()

        with pytest.raises(ValueError):
            supersede_entry(cfg, "ARCH-001", "ARCH-999")

        assert (cdir / "arch.md").read_text() == before

    def test_nonexistent_old_id_raises_and_ledger_unchanged(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg = {"criteria_dir": str(cdir)}
        before = (cdir / "arch.md").read_text()

        with pytest.raises(ValueError):
            supersede_entry(cfg, "ARCH-999", "ARCH-003")

        assert (cdir / "arch.md").read_text() == before

    def test_double_supersede_raises_and_ledger_unchanged(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg = {"criteria_dir": str(cdir)}
        supersede_entry(cfg, "ARCH-001", "ARCH-003")
        before = (cdir / "arch.md").read_text()

        with pytest.raises(ValueError):
            supersede_entry(cfg, "ARCH-001", "ARCH-002")

        assert (cdir / "arch.md").read_text() == before

    def test_self_reference_raises_and_ledger_unchanged(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg = {"criteria_dir": str(cdir)}
        before = (cdir / "arch.md").read_text()

        with pytest.raises(ValueError):
            supersede_entry(cfg, "ARCH-001", "ARCH-001")

        assert (cdir / "arch.md").read_text() == before


class TestCriteriaSupersedeCli:
    def test_help_exits_zero_and_documents_two_id_args(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "criteria", "supersede", "--help"])

        try:
            cli.main()
            raise AssertionError("SystemExitが発生するはず")
        except SystemExit as e:
            assert e.code == 0

        out = capsys.readouterr().out
        assert "old_id" in out
        assert "new_id" in out

    def test_cli_supersede_success_writes_ledger(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg["criteria_dir"] = str(cdir)
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "criteria", "supersede",
            "ARCH-001", "ARCH-003"])

        cli.main()

        target = next(l for l in (cdir / "arch.md").read_text().splitlines()
                      if l.startswith("- ARCH-001 "))
        assert "<!-- superseded_by:ARCH-003 -->" in target
        out = capsys.readouterr().out
        assert "ARCH-001" in out and "ARCH-003" in out

    def test_cli_nonexistent_new_id_exits_nonzero_and_ledger_unchanged(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg["criteria_dir"] = str(cdir)
        before = (cdir / "arch.md").read_text()
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "criteria", "supersede",
            "ARCH-001", "ARCH-999"])

        try:
            cli.main()
            raise AssertionError("SystemExitが発生するはず")
        except SystemExit as e:
            assert e.code != 0
        assert (cdir / "arch.md").read_text() == before

    def test_cli_double_supersede_exits_nonzero_and_ledger_unchanged(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg["criteria_dir"] = str(cdir)
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "criteria", "supersede",
            "ARCH-001", "ARCH-003"])
        cli.main()
        capsys.readouterr()
        before = (cdir / "arch.md").read_text()

        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "criteria", "supersede",
            "ARCH-001", "ARCH-002"])
        try:
            cli.main()
            raise AssertionError("SystemExitが発生するはず")
        except SystemExit as e:
            assert e.code != 0
        assert (cdir / "arch.md").read_text() == before

    def test_cli_self_reference_exits_nonzero_and_ledger_unchanged(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cdir = tmp_path / "criteria"
        _write_ledger(cdir)
        cfg["criteria_dir"] = str(cdir)
        before = (cdir / "arch.md").read_text()
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "criteria", "supersede",
            "ARCH-001", "ARCH-001"])

        try:
            cli.main()
            raise AssertionError("SystemExitが発生するはず")
        except SystemExit as e:
            assert e.code != 0
        assert (cdir / "arch.md").read_text() == before

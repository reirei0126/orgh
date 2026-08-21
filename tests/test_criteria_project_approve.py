"""--project付き承認CLIと接頭辞採番・下書きslug候補(書き込み側の二層化)。

読取・注入側の二層化はtest_criteria_projects.pyで検証済み。本ファイルは
書き込み側(approve_draft/derive_project_prefix/supersede/distill_verdict)
を対象にする。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from orgh import cli
from orgh.criteria import (approve_draft, criteria_context, criteria_dir,
                           criteria_list_payload, derive_project_prefix,
                           distill_verdict, supersede_entry)

from .conftest import write_config


def _make_draft(cdir: Path, name: str, **overrides) -> Path:
    body = {"category": "design", "prefix": "DESIGN", "strength": "norm",
            "text": "原則X"}
    body.update(overrides)
    d = cdir / "_drafts"
    d.mkdir(parents=True, exist_ok=True)
    fp = d / f"{name}.json"
    fp.write_text(json.dumps(body, ensure_ascii=False))
    return fp


class TestDeriveProjectPrefix:
    def test_deterministic_and_shape(self, tmp_path):
        cdir = tmp_path / "criteria"
        p1 = derive_project_prefix(cdir, "agentmenu")
        p2 = derive_project_prefix(cdir, "agentmenu")
        assert p1 == p2
        assert re.match(r"^[A-Z]{3,4}$", p1)

    def test_no_collision_with_global_reserved_prefixes(self, tmp_path):
        cdir = tmp_path / "criteria"
        reserved = {"ARCH", "DESIGN", "DOMAIN", "ENG", "PROD", "QA", "SAFETY"}
        for slug in ["arch", "design", "domain", "eng", "prod", "qa", "safety"]:
            assert derive_project_prefix(cdir, slug) not in reserved

    def test_no_collision_with_other_project_prefix(self, tmp_path):
        cdir = tmp_path / "criteria"
        pdir = cdir / "projects"
        pdir.mkdir(parents=True)
        # agentmenu が既にAGMを使っている前提を作り、似た別slugが
        # ずらされることを確認する
        (pdir / "agentmenu.md").write_text(
            "- AGM-001 [norm]: x <!-- src:m d:2026-01-01 -->\n")
        other = derive_project_prefix(cdir, "agentmenu2")
        assert other != "AGM"
        assert re.match(r"^[A-Z]{3,4}$", other)


class TestApproveDraftWithProject:
    def test_project_approve_appends_to_project_ledger_with_derived_prefix(
            self, tmp_path):
        cdir = tmp_path / "criteria"
        _make_draft(cdir, "m1-1")
        cfg = {"criteria_dir": str(cdir)}
        prefix = derive_project_prefix(cdir, "agentmenu")

        line = approve_draft(cfg, "m1-1", project="agentmenu")

        assert f"{prefix}-001" in line
        pfile = cdir / "projects" / "agentmenu.md"
        assert pfile.is_file()
        assert f"{prefix}-001" in pfile.read_text()
        assert "原則X" in pfile.read_text()

    def test_global_ledger_unchanged_by_project_approve(self, tmp_path):
        cdir = tmp_path / "criteria"
        _make_draft(cdir, "m1-1")
        cfg = {"criteria_dir": str(cdir)}
        assert not (cdir / "design.md").exists()

        approve_draft(cfg, "m1-1", project="agentmenu")

        assert not (cdir / "design.md").exists()
        assert criteria_context(cfg) == "(no criteria yet)"

    def test_two_approvals_to_same_slug_are_sequential(self, tmp_path):
        cdir = tmp_path / "criteria"
        _make_draft(cdir, "m1-1", text="第一原則")
        _make_draft(cdir, "m1-2", text="第二原則")
        cfg = {"criteria_dir": str(cdir)}
        prefix = derive_project_prefix(cdir, "agentmenu")

        first = approve_draft(cfg, "m1-1", project="agentmenu")
        second = approve_draft(cfg, "m1-2", project="agentmenu")

        assert f"{prefix}-001" in first
        assert f"{prefix}-002" in second

    def test_nonexistent_slug_creates_ledger_and_announces(
            self, tmp_path, capsys):
        cdir = tmp_path / "criteria"
        _make_draft(cdir, "m1-1")
        cfg = {"criteria_dir": str(cdir)}

        approve_draft(cfg, "m1-1", project="brandnew")

        out = capsys.readouterr().out
        assert "brandnew" in out
        assert (cdir / "projects" / "brandnew.md").is_file()

    def test_project_field_validation_reuses_existing_checks(self, tmp_path):
        cdir = tmp_path / "criteria"
        _make_draft_with = _make_draft
        _make_draft_with(cdir, "m1-1", strength="強制")
        cfg = {"criteria_dir": str(cdir)}
        with pytest.raises(ValueError, match="strength"):
            approve_draft(cfg, "m1-1", project="agentmenu")

    def test_unsafe_project_slug_rejected(self, tmp_path):
        cdir = tmp_path / "criteria"
        _make_draft(cdir, "m1-1")
        cfg = {"criteria_dir": str(cdir)}
        with pytest.raises(ValueError, match="project"):
            approve_draft(cfg, "m1-1", project="../../ESCAPED")
        assert not (tmp_path / "ESCAPED.md").exists()
        assert not (tmp_path.parent / "ESCAPED.md").exists()


class TestBackwardCompatGlobalApprove:
    def test_draft_without_slug_hint_approves_globally_unchanged(self, tmp_path):
        """slug候補フィールドの無い既存形式の下書きも --project 無しで
        従来どおりグローバル承認できる。"""
        cdir = tmp_path / "criteria"
        _make_draft(cdir, "m1-1")  # project_slug_hint フィールド無し
        cfg = {"criteria_dir": str(cdir)}

        line = approve_draft(cfg, "m1-1")

        assert "DESIGN-001" in line
        assert "原則X" in criteria_context(cfg)
        assert not (cdir / "projects").exists()


class TestSupersedeAndUsageAcrossProjectLayer:
    def test_supersede_project_entry_succeeds_and_excludes_from_injection(
            self, tmp_path):
        cdir = tmp_path / "criteria"
        _make_draft(cdir, "m1-1", text="旧原則")
        _make_draft(cdir, "m1-2", text="新原則")
        cfg = {"criteria_dir": str(cdir)}
        prefix = derive_project_prefix(cdir, "agentmenu")
        approve_draft(cfg, "m1-1", project="agentmenu")
        approve_draft(cfg, "m1-2", project="agentmenu")
        old_id, new_id = f"{prefix}-001", f"{prefix}-002"

        msg = supersede_entry(cfg, old_id, new_id)
        assert old_id in msg and new_id in msg

        ctx = criteria_context(cfg, workdir=str(tmp_path / "agentmenu"))
        assert "旧原則" not in ctx
        assert "新原則" in ctx

    def test_project_entry_citation_stats_appear_in_list_payload(
            self, tmp_path, cfg):
        cdir = tmp_path / "criteria"
        _make_draft(cdir, "m1-1", text="監査対象原則")
        real_cfg = {"criteria_dir": str(cdir)}
        prefix = derive_project_prefix(cdir, "agentmenu")
        approve_draft(real_cfg, "m1-1", project="agentmenu")
        entry_id = f"{prefix}-001"

        cfg["criteria_dir"] = str(cdir)
        run_dir = Path(cfg["runs_dir"]) / "m9"
        run_dir.mkdir(parents=True)
        (run_dir / "ledger.jsonl").write_text(
            json.dumps({"ts": 1755200000.0, "event": "task.review",
                       "criteria_cited": [entry_id]}) + "\n")

        payload = criteria_list_payload(cfg, include_usage=True)
        entry = next(e for e in payload["entries"] if e["id"] == entry_id)
        assert entry["citation_count"] == 1
        assert entry["last_cited_date"] is not None


class TestDistillVerdictSlugHint:
    def test_workdir_adds_project_slug_hint_to_draft(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        monkeypatch.setenv("MOCK_CRITERIA_JSON", json.dumps({
            "proposals": [{"category": "design", "prefix": "DESIGN",
                           "strength": "norm", "text": "原則"}]},
            ensure_ascii=False))
        drafts = distill_verdict(cfg, "m1", "x", passed=False, reason="y",
                                 workdir=str(tmp_path / "agentmenu"))
        body = json.loads(drafts[0].read_text())
        assert body["project_slug_hint"] == "agentmenu"

    def test_no_workdir_omits_slug_hint_backward_compatible(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        monkeypatch.setenv("MOCK_CRITERIA_JSON", json.dumps({
            "proposals": [{"category": "design", "prefix": "DESIGN",
                           "strength": "norm", "text": "原則"}]},
            ensure_ascii=False))
        drafts = distill_verdict(cfg, "m1", "x", passed=False, reason="y")
        body = json.loads(drafts[0].read_text())
        assert "project_slug_hint" not in body


class TestApproveCliWithProjectFlag:
    def test_cli_approve_with_project_writes_project_ledger(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cdir = tmp_path / "criteria"
        cfg["criteria_dir"] = str(cdir)
        _make_draft(cdir, "m1-1")
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "criteria", "approve", "m1-1",
            "--project", "agentmenu"])

        cli.main()

        out = capsys.readouterr().out
        prefix = derive_project_prefix(cdir, "agentmenu")
        assert f"{prefix}-001" in out
        assert (cdir / "projects" / "agentmenu.md").is_file()
        assert not (cdir / "design.md").exists()

    def test_cli_approve_without_project_flag_unchanged(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cdir = tmp_path / "criteria"
        cfg["criteria_dir"] = str(cdir)
        _make_draft(cdir, "m1-1")
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "criteria", "approve", "m1-1"])

        cli.main()

        out = capsys.readouterr().out
        assert "DESIGN-001" in out
        assert not (cdir / "projects").exists()

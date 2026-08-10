"""基準台帳(criteria)の読み書きと文脈注入。戦略設計書 柱2の最小版。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from orgh import cli
from orgh.criteria import (append_entry, criteria_context, criteria_dir,
                           distill_verdict, next_id, list_drafts, approve_draft,
                           reject_draft)
from orgh.planner import build_review_prompt
from orgh.state import Mission, RunStore, Task

from .conftest import read_ledger, write_config


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


class TestReviewerInjection:
    def test_review_prompt_contains_criteria(self, tmp_path, cfg):
        cdir = tmp_path / "criteria"
        append_entry(cdir, "design", "DESIGN", "norm",
                     "視覚検証なしの合格を信用しない", src="7307189e")
        cfg["criteria_dir"] = str(cdir)
        t = Task(id="t1", title="UI改修", prompt="やる",
                 acceptance=["画面が表示される"])
        p = build_review_prompt(cfg, t)
        assert "DESIGN-001" in p
        assert "基準" in p          # 台帳セクションの見出しが存在する

    def test_review_prompt_without_ledger(self, cfg, tmp_path):
        cfg["criteria_dir"] = str(tmp_path / "none")
        t = Task(id="t1", title="x", prompt="y", acceptance=["z"])
        assert "(no criteria yet)" in build_review_prompt(cfg, t)


class TestVerdictDistill:
    def test_fail_verdict_generates_draft(self, cfg, mock_state_dir,
                                          tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        monkeypatch.setenv("MOCK_CRITERIA_JSON", json.dumps({
            "proposals": [{"category": "design", "prefix": "DESIGN",
                           "strength": "norm",
                           "text": "視覚検証なしの合格を信用しない"}]},
            ensure_ascii=False))
        drafts = distill_verdict(cfg, "m123", "筐体UI刷新",
                                 passed=False, reason="レバー不可視・リール真っ黒")
        assert len(drafts) == 1
        body = json.loads(drafts[0].read_text())
        assert body["prefix"] == "DESIGN"
        # 本台帳にはまだ載らない(下書き+承認ガバナンス)
        assert criteria_context(cfg) == "(no criteria yet)"

    def test_empty_proposals_writes_nothing(self, cfg, mock_state_dir,
                                            tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        monkeypatch.setenv("MOCK_CRITERIA_JSON", '{"proposals": []}')
        assert distill_verdict(cfg, "m1", "x", passed=True, reason="良い") == []

    def test_repeat_verdict_does_not_overwrite_existing_drafts(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        """同一ミッションへ2回目のverdictを打っても、1回目の未承認下書きを
        上書きしない(番号を1から振り直さず既存最大+1から続ける)。"""
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        monkeypatch.setenv("MOCK_CRITERIA_JSON", json.dumps({
            "proposals": [{"category": "design", "prefix": "DESIGN",
                           "strength": "norm", "text": "1回目の原則"}]},
            ensure_ascii=False))
        first = distill_verdict(cfg, "m123", "筐体UI刷新",
                                passed=False, reason="1回目の指摘")
        assert len(first) == 1

        monkeypatch.setenv("MOCK_CRITERIA_JSON", json.dumps({
            "proposals": [{"category": "design", "prefix": "DESIGN",
                           "strength": "norm", "text": "2回目の原則"}]},
            ensure_ascii=False))
        second = distill_verdict(cfg, "m123", "筐体UI刷新",
                                 passed=False, reason="2回目の指摘")
        assert len(second) == 1
        assert second[0] != first[0]  # 別ファイルに書かれる

        drafts = sorted((tmp_path / "criteria" / "_drafts").glob("m123-*.json"))
        assert len(drafts) == 2
        # 1回目の内容は上書きされず残っている
        assert json.loads(first[0].read_text())["text"] == "1回目の原則"
        assert json.loads(second[0].read_text())["text"] == "2回目の原則"


class TestVerdictCli:
    def test_cli_records_verdict_ledger_and_draft(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        m = Mission.new(intent="筐体UI刷新", context_digest="(test)", tasks=[])
        store = RunStore(cfg["runs_dir"], m.id)
        store.save(m)

        monkeypatch.setenv("MOCK_CRITERIA_JSON", json.dumps({
            "proposals": [{"category": "design", "prefix": "DESIGN",
                           "strength": "norm",
                           "text": "視覚検証なしの合格を信用しない"}]},
            ensure_ascii=False))
        long_reason = "レバー不可視・リール真っ黒" * 40  # 500文字超(ledger切り詰め確認用)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "verdict", m.id,
            "--fail", "--reason", long_reason])
        cli.main()

        verdicts = [json.loads(l) for l in
                    (store.dir / "verdicts.jsonl").read_text().splitlines()]
        assert len(verdicts) == 1
        assert verdicts[0]["passed"] is False
        assert verdicts[0]["reason"] == long_reason  # verdicts.jsonlは全文保持

        ledger = read_ledger(cfg["runs_dir"], m.id)
        ev = next(e for e in ledger if e["event"] == "mission.owner_verdict")
        assert ev["passed"] is False
        assert ev["reason"] == long_reason[:500]  # ledgerは500文字に切り詰め

        drafts = list((tmp_path / "criteria" / "_drafts").glob(f"{m.id}-*.json"))
        assert len(drafts) == 1
        assert json.loads(drafts[0].read_text())["prefix"] == "DESIGN"


def _make_draft(cdir: Path, name: str) -> Path:
    d = cdir / "_drafts"
    d.mkdir(parents=True, exist_ok=True)
    fp = d / f"{name}.json"
    fp.write_text(json.dumps({"category": "design", "prefix": "DESIGN",
                              "strength": "norm", "text": "原則X"},
                             ensure_ascii=False))
    return fp


class TestCriteriaCli:
    def test_approve_moves_draft_to_ledger(self, tmp_path):
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        _make_draft(Path(cfg["criteria_dir"]), "m123-1")
        line = approve_draft(cfg, "m123-1")
        assert "DESIGN-001" in line
        assert "原則X" in criteria_context(cfg)
        assert list_drafts(cfg) == []          # 下書きは消費済み

    def test_reject_keeps_record(self, tmp_path):
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        _make_draft(Path(cfg["criteria_dir"]), "m123-1")
        moved = reject_draft(cfg, "m123-1")
        assert moved.exists() and "rejected" in str(moved)
        assert criteria_context(cfg) == "(no criteria yet)"

    def test_approve_missing_draft_raises(self, tmp_path):
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        import pytest
        with pytest.raises(FileNotFoundError):
            approve_draft(cfg, "nope-1")

    def test_reject_missing_draft_raises(self, tmp_path):
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        import pytest
        with pytest.raises(FileNotFoundError):
            reject_draft(cfg, "nope-1")

    def test_reject_collision_disambiguates_filename(self, tmp_path):
        """同ミッション下書きの再生成→棄却で既存記録を上書きしない。
        ファイル名衝突時は .2, .3 ... サフィックスを自動付与。"""
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        # 1回目: 下書き作成→棄却
        _make_draft(Path(cfg["criteria_dir"]), "m123-1")
        first_rejected = reject_draft(cfg, "m123-1")
        assert first_rejected.name == "m123-1.json"
        first_content = first_rejected.read_text()

        # 2回目: 同じファイル名で別内容の下書き再作成→棄却
        cdir = Path(cfg["criteria_dir"])
        d = cdir / "_drafts"
        fp = d / "m123-1.json"
        fp.write_text(json.dumps({"category": "design", "prefix": "DESIGN",
                                  "strength": "norm", "text": "原則Y"},
                                 ensure_ascii=False))
        second_rejected = reject_draft(cfg, "m123-1")

        # 両方が存在し、内容が異なる
        assert first_rejected.exists()
        assert second_rejected.exists()
        assert second_rejected.name == "m123-1.2.json"  # サフィックス追加
        assert first_rejected.read_text() == first_content  # 1回目のまま
        assert "原則Y" in second_rejected.read_text()  # 2回目の内容


def _make_draft_with(cdir: Path, name: str, **overrides) -> Path:
    """category/prefix/strengthを差し替え可能な下書き生成(不正値注入テスト用)。"""
    body = {"category": "design", "prefix": "DESIGN", "strength": "norm",
            "text": "原則X"}
    body.update(overrides)
    d = cdir / "_drafts"
    d.mkdir(parents=True, exist_ok=True)
    fp = d / f"{name}.json"
    fp.write_text(json.dumps(body, ensure_ascii=False))
    return fp


class TestApproveDraftValidation:
    """approve_draftはdistill LLMが生成したcategory/prefix/strengthを信用しない
    (検証済み脆弱性: パストラバーサルによるcriteria_dir外への書き込み、
    _ENTRY_RE非対応strengthによるID重複発行)。"""

    def test_category_path_traversal_raises_and_writes_nothing_outside(
            self, tmp_path):
        cdir = tmp_path / "criteria"
        _make_draft_with(cdir, "m123-1", category="../../ESCAPED")
        cfg = {"criteria_dir": str(cdir)}
        with pytest.raises(ValueError, match="category"):
            approve_draft(cfg, "m123-1")
        # criteria_dirの外にESCAPED.mdが書かれていないこと
        assert not (tmp_path / "ESCAPED.md").exists()
        assert not (tmp_path.parent / "ESCAPED.md").exists()
        # 下書きも消費されず残る(オーナーが手で直して再承認できるように)
        assert list_drafts(cfg) == [cdir / "_drafts" / "m123-1.json"]

    def test_invalid_strength_raises(self, tmp_path):
        cdir = tmp_path / "criteria"
        _make_draft_with(cdir, "m123-1", strength="強制")
        cfg = {"criteria_dir": str(cdir)}
        with pytest.raises(ValueError, match="strength"):
            approve_draft(cfg, "m123-1")

    def test_prefix_with_space_raises(self, tmp_path):
        cdir = tmp_path / "criteria"
        _make_draft_with(cdir, "m123-1", prefix="DESIGN X")
        cfg = {"criteria_dir": str(cdir)}
        with pytest.raises(ValueError, match="prefix"):
            approve_draft(cfg, "m123-1")

    def test_lowercase_prefix_raises(self, tmp_path):
        """_ENTRY_REは[A-Z]+の接頭辞しか認識しないため、小文字混じりの
        prefixを許すとledger行がnext_idの走査から漏れID重複を招く
        (Fix 1が閉じたはずの欠陥クラスの再発防止)。"""
        cdir = tmp_path / "criteria"
        _make_draft_with(cdir, "m123-1", prefix="design")
        cfg = {"criteria_dir": str(cdir)}
        with pytest.raises(ValueError, match="prefix"):
            approve_draft(cfg, "m123-1")
        assert list_drafts(cfg) == [cdir / "_drafts" / "m123-1.json"]

    def test_category_leading_underscore_raises(self, tmp_path):
        """_ledger_files()は`_`始まりのファイルを台帳走査から除外するため、
        category="_hidden"を許すと承認済みのはずの行がcriteria_context/
        next_idから不可視になる。"""
        cdir = tmp_path / "criteria"
        _make_draft_with(cdir, "m123-1", category="_hidden")
        cfg = {"criteria_dir": str(cdir)}
        with pytest.raises(ValueError, match="category"):
            approve_draft(cfg, "m123-1")
        assert list_drafts(cfg) == [cdir / "_drafts" / "m123-1.json"]

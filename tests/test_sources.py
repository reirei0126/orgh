"""HANDOFF タスク3: 入力層の SourceAdapter 抽象化。

- watcher/cli はインターフェース経由でのみ入力ソースに触れる
  (watcher.py にvault固有の記述が残っていないこと)
- Obsidian固有ロジックは sources/obsidian.py に閉じる(ingest.py は廃止)
- config source.type でアダプタを選択(既定 obsidian)
- 既存STシナリオがアダプタ経由で従来通り通ること(既存スイート全体が回帰網)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orgh.sources.base import MissionFeedback, SourceAdapter, get_source
from orgh.sources.obsidian import ObsidianAdapter

REPO = Path(__file__).resolve().parent.parent


class TestRegistry:
    def test_default_is_obsidian(self, wcfg):
        assert isinstance(get_source(wcfg), ObsidianAdapter)

    def test_explicit_obsidian(self, wcfg):
        wcfg["source"] = {"type": "obsidian"}
        assert isinstance(get_source(wcfg), ObsidianAdapter)

    def test_unknown_type_raises(self, wcfg):
        wcfg["source"] = {"type": "notion"}
        with pytest.raises(KeyError):
            get_source(wcfg)


class TestObsidianAdapter:
    """インターフェースの主要契約(詳細挙動は既存watcher STが担保)。"""

    def test_list_candidates_and_trigger(self, wcfg, vault):
        (vault / "inbox" / "a.md").write_text("候補のみ\n")
        (vault / "inbox" / "b.md").write_text("着火する #go\n")
        src = get_source(wcfg)
        cands = src.list_candidates()
        assert {n.title for n in cands} == {"a", "b"}
        by_title = {n.title: n for n in cands}
        # aは候補どまり(トリガーなし)。bはトリガーはあるがstabilize未達
        assert not src.should_trigger(by_title["a"])
        assert not src.should_trigger(by_title["b"])

    def test_find_by_partial_title(self, wcfg, vault):
        (vault / "inbox" / "オントロジーMVP.md").write_text("x\n")
        src = get_source(wcfg)
        assert src.find("オントロジー").title == "オントロジーMVP"
        assert src.find("存在しない") is None

    def test_feedback_is_results_note(self, wcfg):
        fb = get_source(wcfg).feedback("mid123")
        assert isinstance(fb, MissionFeedback)
        assert fb.cancel_requested() is False


class TestBoundaries:
    def test_watcher_has_no_vault_specific_code(self):
        src = (REPO / "orgh" / "watcher.py").read_text()
        for token in ("ingest", "vault", "ResultsNote", "obsidian",
                      "append_callout", "orgh/results"):
            assert token not in src, f"watcher.py にvault固有の記述: {token}"

    def test_cli_goes_through_interface(self):
        src = (REPO / "orgh" / "cli.py").read_text()
        assert "ingest" not in src
        assert "scan_vault" not in src

    def test_ingest_module_is_gone(self):
        assert not (REPO / "orgh" / "ingest.py").exists()

    def test_base_has_no_obsidian_imports_at_module_level(self):
        import re
        src = (REPO / "orgh" / "sources" / "base.py").read_text()
        head = src.split("def get_source")[0]
        # 拡張点はget_source内の遅延importのみ(モジュールレベルでのimport禁止)
        assert not re.search(r"^\s*(from|import)\s+\S*obsidian", head, re.M)

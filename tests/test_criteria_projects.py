"""criteria台帳の二層化(グローバル+プロジェクト別)。読取・注入のコア。

配置: criteria/projects/<slug>.md。slugはミッション/タスクのworkdir末尾
ディレクトリ名(project_slug()で導出)。注入対象は「グローバル全件+当該
workdirに一致するプロジェクト台帳のみ」——他プロジェクトの台帳は絶対に
混ぜない(config上のミス一つで他プロジェクトの内部方針が漏れる設計は
避ける)。
"""
from __future__ import annotations

from pathlib import Path

from orgh.criteria import (criteria_context, criteria_ids,
                           criteria_list_payload, criteria_list_text,
                           project_slug)


def _write_global(cdir: Path, name: str, content: str) -> Path:
    cdir.mkdir(parents=True, exist_ok=True)
    fp = cdir / f"{name}.md"
    fp.write_text(content)
    return fp


def _write_project(cdir: Path, slug: str, content: str) -> Path:
    pdir = cdir / "projects"
    pdir.mkdir(parents=True, exist_ok=True)
    fp = pdir / f"{slug}.md"
    fp.write_text(content)
    return fp


class TestProjectSlug:
    def test_slug_is_workdir_basename(self, tmp_path):
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        assert project_slug(cfg, str(tmp_path / "agentmenu")) == "agentmenu"

    def test_none_for_unset_workdir(self, tmp_path):
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        assert project_slug(cfg, None) is None
        assert project_slug(cfg, "") is None

    def test_none_for_dot_workdir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        assert project_slug(cfg, ".") is None

    def test_none_for_own_repo_root(self, tmp_path):
        cdir = tmp_path / "criteria"
        cfg = {"criteria_dir": str(cdir)}
        # criteria_dirを含むリポのルート(=cdirの親)を指すworkdirはNone
        assert project_slug(cfg, str(tmp_path)) is None

    def test_none_for_unsafe_slug(self, tmp_path):
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        # 先頭アンダースコアは_ledger_filesの除外規約と衝突するため不可
        assert project_slug(cfg, str(tmp_path / "_hidden")) is None
        # 空白混じりの名前は安全な文字集合(_SAFE_CATEGORY_RE)に合致しない
        assert project_slug(cfg, str(tmp_path / "foo bar")) is None

    def test_agentmenu_and_agentmenu_internal_are_distinct_slugs(self, tmp_path):
        """オーナー確定済み決定: 末尾ディレクトリ名そのままで別台帳にする。"""
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        assert project_slug(cfg, str(tmp_path / "agentmenu")) == "agentmenu"
        assert (project_slug(cfg, str(tmp_path / "agentmenu-internal"))
                == "agentmenu-internal")


class TestProjectLayerInjection:
    def _seed(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_global(cdir, "design",
                      "- DESIGN-001 [norm]: グローバル基準 "
                      "<!-- src:m0 d:2026-01-01 -->\n")
        _write_project(
            cdir, "agentmenu",
            "- AGM-001 [norm]: agentmenu専用基準 "
            "<!-- src:m1 d:2026-08-10 -->\n")
        _write_project(
            cdir, "other",
            "- OTH-001 [norm]: other専用基準 "
            "<!-- src:m2 d:2026-08-10 -->\n")
        return cdir

    def test_matching_project_included_other_project_excluded(self, tmp_path):
        """[AC-1] agentmenu/other両方の台帳がある状態で、workdir=agentmenuの
        注入結果にagentmenu台帳が含まれ、other台帳は1行も含まれない。"""
        cdir = self._seed(tmp_path)
        cfg = {"criteria_dir": str(cdir)}

        ctx = criteria_context(cfg, workdir=str(tmp_path / "agentmenu"))

        assert "AGM-001" in ctx and "agentmenu専用基準" in ctx
        assert "OTH-001" not in ctx and "other専用基準" not in ctx
        assert "DESIGN-001" in ctx  # グローバルは常に含まれる

    def test_ids_match_injected_lines_with_project_layer(self, tmp_path):
        cdir = self._seed(tmp_path)
        cfg = {"criteria_dir": str(cdir)}

        ids = criteria_ids(cfg, workdir=str(tmp_path / "agentmenu"))

        assert ids == {"DESIGN-001", "AGM-001"}

    def test_unspecified_workdir_excludes_all_project_layers(self, tmp_path):
        """[AC-2] workdir未指定ならプロジェクト台帳は一切含まれない
        (現行と完全に同一の挙動)。"""
        cdir = self._seed(tmp_path)
        cfg = {"criteria_dir": str(cdir)}

        ctx = criteria_context(cfg)

        assert "DESIGN-001" in ctx
        assert "AGM-001" not in ctx and "OTH-001" not in ctx

    def test_own_repo_workdir_excludes_all_project_layers(self, tmp_path):
        """[AC-2] workdir=orgh自身(criteria_dirを含むリポのルート)でも
        プロジェクト台帳は一切含まれず、未指定時と同一出力になる。"""
        cdir = self._seed(tmp_path)
        cfg = {"criteria_dir": str(cdir)}

        ctx_unset = criteria_context(cfg)
        ctx_own = criteria_context(cfg, workdir=str(tmp_path))

        assert ctx_own == ctx_unset
        assert criteria_ids(cfg) == criteria_ids(cfg, workdir=str(tmp_path))

    def test_no_such_project_ledger_falls_back_to_global_only(self, tmp_path):
        cdir = self._seed(tmp_path)
        cfg = {"criteria_dir": str(cdir)}

        ctx = criteria_context(cfg, workdir=str(tmp_path / "nonexistent-slug"))

        assert "DESIGN-001" in ctx
        assert "AGM-001" not in ctx and "OTH-001" not in ctx

    def test_superseded_project_entry_excluded_like_global(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_project(
            cdir, "agentmenu",
            "- AGM-001 [norm]: 旧基準 <!-- src:m1 d:2026-08-10 --> "
            "<!-- superseded_by:AGM-002 -->\n"
            "- AGM-002 [norm]: 新基準 <!-- src:m2 d:2026-08-11 -->\n")
        cfg = {"criteria_dir": str(cdir)}

        ctx = criteria_context(cfg, workdir=str(tmp_path / "agentmenu"))

        assert "旧基準" not in ctx
        assert "新基準" in ctx


class TestInjectCapAppliesToBothLayersCombined:
    def _seed(self, tmp_path):
        cdir = tmp_path / "criteria"
        cdir.mkdir()
        global_lines = []
        for i in range(1, 6):
            pad = "x" * 60
            global_lines.append(
                f"- QA-{i:03d} [norm]: {pad} <!-- src:m d:2026-01-{i:02d} -->")
        (cdir / "qa.md").write_text("\n".join(global_lines) + "\n")

        project_lines = []
        for i in range(1, 3):
            pad = "y" * 40
            project_lines.append(
                f"- AGM-{i:03d} [norm]: {pad} <!-- src:m d:2026-02-{i:02d} -->")
        _write_project(cdir, "agentmenu", "\n".join(project_lines) + "\n")
        return cdir, global_lines, project_lines

    def test_project_fully_packed_before_global_is_cut(self, tmp_path):
        """[AC-3] 合算超過時、プロジェクト台帳は全行入り、グローバルは
        日付降順で残り枠だけが入る(打ち切られる)。"""
        cdir, global_lines, project_lines = self._seed(tmp_path)
        cfg = {"criteria_dir": str(cdir)}

        project_chars = sum(len(l) + 1 for l in project_lines)
        newest_global = global_lines[-1]  # QA-005: 日付降順で先頭に来る
        max_chars = project_chars + len(newest_global) + 1 + 5

        ctx = criteria_context(cfg, max_chars=max_chars,
                               workdir=str(tmp_path / "agentmenu"))

        for line in project_lines:
            assert line in ctx
        included_global = [l for l in global_lines if l in ctx]
        assert included_global == [newest_global]  # 1件だけ入り残りは切られる

    def test_criteria_ids_matches_truncated_injection(self, tmp_path):
        """[AC-4] criteria_ids()は、二層合算・打ち切りが起きた場合でも
        実際に注入された行のID集合と一致する。"""
        cdir, global_lines, project_lines = self._seed(tmp_path)
        cfg = {"criteria_dir": str(cdir)}
        project_chars = sum(len(l) + 1 for l in project_lines)
        newest_global = global_lines[-1]
        max_chars = project_chars + len(newest_global) + 1 + 5

        ctx = criteria_context(cfg, max_chars=max_chars,
                               workdir=str(tmp_path / "agentmenu"))
        ids = criteria_ids(cfg, max_chars=max_chars,
                           workdir=str(tmp_path / "agentmenu"))

        assert ids == {"AGM-001", "AGM-002", "QA-005"}
        for entry_id in ids:
            assert entry_id in ctx


class TestCriteriaListIncludesProjectLayers:
    """`orgh criteria list` はオーナーの監査用途のため、全プロジェクトを
    横断して列挙する(注入=criteria_contextとは異なる責務)。"""

    def _seed(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_global(cdir, "design",
                      "- DESIGN-001 [norm]: グローバル基準 "
                      "<!-- src:m0 d:2026-01-01 -->\n")
        _write_project(
            cdir, "agentmenu",
            "- AGM-001 [norm]: agentmenu専用基準 "
            "<!-- src:m1 d:2026-08-10 -->\n")
        return cdir

    def test_list_text_includes_project_entry(self, tmp_path):
        cdir = self._seed(tmp_path)
        cfg = {"criteria_dir": str(cdir)}
        out = criteria_list_text(cfg)
        assert "AGM-001" in out and "agentmenu専用基準" in out
        assert "DESIGN-001" in out

    def test_list_payload_project_entry_identifies_layer_and_slug(
            self, tmp_path):
        cdir = self._seed(tmp_path)
        cfg = {"criteria_dir": str(cdir)}
        payload = criteria_list_payload(cfg)
        ids = {e["id"]: e for e in payload["entries"]}
        assert "AGM-001" in ids and "DESIGN-001" in ids

        project_entry = ids["AGM-001"]
        assert project_entry["layer"] == "project"
        assert project_entry["project"] == "agentmenu"
        # 既存キーは削除・改名されない
        assert project_entry["text"] == "agentmenu専用基準"

        global_entry = ids["DESIGN-001"]
        assert "layer" not in global_entry  # 既存の形状を一切変えない(後方互換)


class TestBackwardCompatibleGlobalOnlyRepo:
    """criteria/projects/ が存在しない、またはworkdir未指定の構成では
    現行と完全に同一の挙動になる。"""

    def test_no_projects_dir_matches_pre_layering_output(self, tmp_path):
        cdir = tmp_path / "criteria"
        _write_global(cdir, "design",
                      "- DESIGN-001 [norm]: 唯一の基準 "
                      "<!-- src:m0 d:2026-01-01 -->\n")
        cfg = {"criteria_dir": str(cdir)}

        assert criteria_context(cfg) == "- DESIGN-001 [norm]: 唯一の基準 <!-- src:m0 d:2026-01-01 -->"
        assert criteria_ids(cfg) == {"DESIGN-001"}

"""実運用ミッション7307189eで発見した欠陥への対処:
ミッションノートに対象リポのパスが無いと Planner が workdir "." を出力し、
orgh自身のリポ(のworktree)で実行されてしまう。
プロジェクトマップ(config: projects_map)をPlanner文脈に注入して解決させる。"""
from __future__ import annotations

from orgh import planner


class TestProjectsContext:
    def test_reads_configured_map_file(self, tmp_path, cfg):
        fp = tmp_path / "projects-map.md"
        fp.write_text("- /abs/path/proj — PROJECT_SENTINEL 説明")
        cfg["projects_map"] = str(fp)
        assert "PROJECT_SENTINEL" in planner._projects_context(cfg)

    def test_unset_key_is_tolerated(self, cfg):
        cfg.pop("projects_map", None)
        assert planner._projects_context(cfg) == "(no project map)"

    def test_missing_file_is_tolerated(self, tmp_path, cfg):
        cfg["projects_map"] = str(tmp_path / "does-not-exist.md")
        assert planner._projects_context(cfg) == "(no project map)"

    def test_empty_file_is_tolerated(self, tmp_path, cfg):
        fp = tmp_path / "projects-map.md"
        fp.write_text("\n")
        cfg["projects_map"] = str(fp)
        assert planner._projects_context(cfg) == "(no project map)"


class TestPlannerInjection:
    def test_plan_prompt_contains_map_and_workdir_rule(self, tmp_path, cfg,
                                                       monkeypatch):
        fp = tmp_path / "projects-map.md"
        fp.write_text("- /abs/path/proj — PROJECT_SENTINEL 説明")
        cfg["projects_map"] = str(fp)

        captured = {}

        def fake_ask(cfg_, role, prompt, **kw):
            captured["prompt"] = prompt
            return {"tasks": [{"id": "t1", "title": "x", "prompt": "y",
                               "worker": "claude_code", "deps": [],
                               "acceptance": ["z"]}]}
        monkeypatch.setattr(planner, "_ask_json", fake_ask)

        planner.plan(cfg, intent="i", context_digest="c")
        assert "PROJECT_SENTINEL" in captured["prompt"]
        # planner.md 側のworkdir制約(絶対パス指定の指示)が消えたら落とす
        assert "絶対パス" in captured["prompt"]

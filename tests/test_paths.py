"""HANDOFF 0b: prompts/playbooksパスのconfig駆動化(パッケージング対応)。"""
from __future__ import annotations

from pathlib import Path

from orgh import planner
from orgh.state import Task

REPO = Path(__file__).resolve().parent.parent


def _task() -> Task:
    return Task(id="t1", title="題名X", prompt="やることY",
                acceptance=["条件Z"])


class TestConfigDrivenPaths:
    def test_worker_prompt_uses_config_prompts_dir(self, tmp_path, cfg):
        pd = tmp_path / "myprompts"
        pd.mkdir()
        (pd / "worker_preamble.md").write_text(
            "PROMPT_SENTINEL {title} / {prompt} / {acceptance}")
        cfg["prompts_dir"] = str(pd)

        out = planner.worker_prompt(cfg, _task())
        assert "PROMPT_SENTINEL" in out
        assert "題名X" in out

    def test_no_repo_relative_file_refs_in_sources(self):
        """パッケージ相対(__file__起点)のprompts/playbooks参照の全廃を強制する。"""
        for src_path in (REPO / "orgh").rglob("*.py"):
            if "__pycache__" in src_path.parts:
                continue
            src = src_path.read_text()
            assert "parent.parent" not in src, \
                f"{src_path.relative_to(REPO)} が__file__相対参照を残している"


class TestPlaybooksNotInjected:
    """playbooks自動注入の廃止(統治線をcriteriaへ一本化)。playbooks_dir配下に
    何を置いてもPlanner/Workerのプロンプト構築結果には一切現れないことを保証する。"""

    def test_worker_prompt_excludes_playbooks_dir_content(self, tmp_path, cfg):
        pb = tmp_path / "mybooks"
        pb.mkdir()
        (pb / "coding.md").write_text("PLAYBOOK_SENTINEL 教訓")
        cfg["playbooks_dir"] = str(pb)

        out = planner.worker_prompt(cfg, _task())
        assert "PLAYBOOK_SENTINEL" not in out

    def test_plan_prompt_excludes_playbooks_dir_content(self, tmp_path, cfg,
                                                         monkeypatch):
        pb = tmp_path / "mybooks"
        pb.mkdir()
        (pb / "coding.md").write_text("PLAYBOOK_SENTINEL 教訓")
        cfg["playbooks_dir"] = str(pb)

        captured = {}

        def fake_ask(cfg_, role, prompt, **kw):
            captured["prompt"] = prompt
            return {"tasks": [{"id": "t1", "title": "x", "prompt": "y",
                               "worker": "claude_code", "deps": [],
                               "acceptance": ["z"]}]}
        monkeypatch.setattr(planner, "_ask_json", fake_ask)

        planner.plan(cfg, intent="i", context_digest="c")
        assert "PLAYBOOK_SENTINEL" not in captured["prompt"]

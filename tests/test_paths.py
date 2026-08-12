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
            "PROMPT_SENTINEL {title} / {prompt} / {acceptance} / {playbooks}")
        cfg["prompts_dir"] = str(pd)

        out = planner.worker_prompt(cfg, _task())
        assert "PROMPT_SENTINEL" in out
        assert "題名X" in out

    def test_playbooks_dir_config_driven(self, tmp_path, cfg):
        pb = tmp_path / "mybooks"
        pb.mkdir()
        (pb / "coding.md").write_text("PLAYBOOK_SENTINEL 教訓")
        cfg["playbooks_dir"] = str(pb)

        out = planner.worker_prompt(cfg, _task())
        assert "PLAYBOOK_SENTINEL" in out

    def test_missing_playbooks_dir_is_tolerated(self, tmp_path, cfg):
        cfg["playbooks_dir"] = str(tmp_path / "does-not-exist")
        out = planner.worker_prompt(cfg, _task())
        assert "no playbooks yet" in out

    def test_no_repo_relative_file_refs_in_sources(self):
        """パッケージ相対(__file__起点)のprompts/playbooks参照の全廃を強制する。"""
        for src_path in (REPO / "orgh").rglob("*.py"):
            if "__pycache__" in src_path.parts:
                continue
            src = src_path.read_text()
            assert "parent.parent" not in src, \
                f"{src_path.relative_to(REPO)} が__file__相対参照を残している"

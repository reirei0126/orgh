"""workdir独立リポ判定ガード(実運用2026-08-12の事故対処)。

- 公開リポ内のgitignore対象サブディレクトリをworkdirに指定すると、worktree分離が
  親リポを対象に `git worktree add` してしまい、非公開の成果物が親リポの
  ブランチへコミットされる事故が起きた。workdirが独立リポのルートかどうかを
  分類し、入れ子(NESTED_IN_OTHER_REPO)を既定で拒否するガードの単体試験。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orgh.workdir_guard import (
    INDEPENDENT_ROOT,
    NESTED_IN_OTHER_REPO,
    NOT_A_REPO,
    WorkdirGuardError,
    classify_workdir,
    guard_workdir,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True)


@pytest.fixture
def parent_repo(tmp_path) -> Path:
    """公開リポを模した親gitリポジトリ。"""
    d = tmp_path / "decision-os-mvp"
    d.mkdir()
    _git(d.parent, "init", "-q", "-b", "main", str(d))
    _git(d, "config", "user.email", "test@example.com")
    _git(d, "config", "user.name", "orgh-test")
    (d / "README.md").write_text("public\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "base")
    return d


class TestClassifyWorkdir:
    def test_repo_root_is_independent(self, parent_repo):
        kind, root = classify_workdir(parent_repo)
        assert kind == INDEPENDENT_ROOT
        assert Path(root) == Path(parent_repo).resolve()

    def test_plain_subdir_is_nested(self, parent_repo):
        sub = parent_repo / "cases" / "003"
        sub.mkdir(parents=True)
        kind, root = classify_workdir(sub)
        assert kind == NESTED_IN_OTHER_REPO
        assert Path(root) == Path(parent_repo).resolve()

    def test_gitignored_subdir_is_still_nested(self, parent_repo):
        """事故の再現ケース: gitignore対象でも親リポ扱いのままであること。"""
        (parent_repo / ".gitignore").write_text("private/\n")
        _git(parent_repo, "add", ".gitignore")
        _git(parent_repo, "commit", "-q", "-m", "add gitignore")

        sub = parent_repo / "private" / "cases" / "003-orgh-portfolio"
        sub.mkdir(parents=True)

        # git check-ignore が無視対象と認めることを前提として確認する
        ignored = subprocess.run(
            ["git", "-C", str(parent_repo), "check-ignore", str(sub)],
            capture_output=True, text=True)
        assert ignored.returncode == 0

        kind, root = classify_workdir(sub)
        assert kind == NESTED_IN_OTHER_REPO
        assert Path(root) == Path(parent_repo).resolve()

    def test_subdir_with_own_git_init_is_independent(self, parent_repo):
        sub = parent_repo / "vendor" / "own-repo"
        sub.mkdir(parents=True)
        _git(sub.parent, "init", "-q", "-b", "main", str(sub))

        kind, root = classify_workdir(sub)
        assert kind == INDEPENDENT_ROOT
        assert Path(root) == sub.resolve()

    def test_non_repo_dir_is_not_a_repo(self, tmp_path):
        plain = tmp_path / "plain-dir"
        plain.mkdir()
        kind, root = classify_workdir(plain)
        assert kind == NOT_A_REPO
        assert root is None


class TestGuardWorkdir:
    def test_independent_root_passes(self, parent_repo):
        guard_workdir({"worktree": {"enabled": True}}, parent_repo)  # raiseしない

    def test_not_a_repo_passes(self, tmp_path):
        plain = tmp_path / "plain-dir"
        plain.mkdir()
        guard_workdir({"worktree": {"enabled": True}}, plain)  # raiseしない

    def test_nested_workdir_is_rejected_with_actionable_message(self, parent_repo):
        sub = parent_repo / "private" / "cases" / "003-orgh-portfolio"
        sub.mkdir(parents=True)

        with pytest.raises(WorkdirGuardError) as exc_info:
            guard_workdir({"worktree": {"enabled": True}}, sub)

        msg = str(exc_info.value)
        assert str(Path(parent_repo).resolve()) in msg
        assert "git init" in msg
        assert "allow_nested_workdir" in msg

    def test_nested_workdir_allowed_with_explicit_opt_in(self, parent_repo):
        sub = parent_repo / "cases" / "003"
        sub.mkdir(parents=True)
        cfg = {"worktree": {"enabled": True, "allow_nested_workdir": True}}
        guard_workdir(cfg, sub)  # raiseしない

    def test_missing_worktree_section_defaults_to_rejecting_nested(self, parent_repo):
        sub = parent_repo / "cases" / "003"
        sub.mkdir(parents=True)
        with pytest.raises(WorkdirGuardError):
            guard_workdir({}, sub)

"""HANDOFF タスク1: git worktreeによるタスク分離。

- 並列タスクが同一リポの同一ファイルを編集しても衝突せず、タスクごとの
  ブランチ(orgh/<mission_id>/<task_id>)に分かれる
- 差し戻し再実行は同じworktreeを再利用する(セッションと成果を捨てない)
- enabled: false / 非gitリポは現行動作にフォールバック
- orgh cleanup <mission_id> でworktreeとブランチが消える
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from orgh import cli
from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore, Task

from .conftest import read_calls, write_config


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, check=True)
    return r.stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    """コミット済みファイルを持つ試験用gitリポ。"""
    d = tmp_path / "target-repo"
    d.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(d)], check=True)
    _git(d, "config", "user.email", "test@example.com")
    _git(d, "config", "user.name", "orgh-test")
    (d / "shared.txt").write_text("base\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "base")
    return d


@pytest.fixture
def wt_cfg(cfg) -> dict:
    cfg["worktree"] = {"enabled": True}  # base_ref/rootはデフォルトを検証
    return cfg


def _task(id: str, workdir: str, worker: str = "claude_code") -> dict:
    return {
        "id": id, "title": f"task {id}",
        "prompt": f"共有ファイルを編集 [[MARK:{id}]] [[WRITE:shared.txt:edit-by-{id}]]",
        "worker": worker, "deps": [],
        "acceptance": ["mock acceptance"], "workdir": workdir,
    }


def _mission(tasks: list[dict]) -> Mission:
    return Mission.new(intent="worktree試験", context_digest="(test)",
                       tasks=tasks)


def _branches(repo: Path) -> set[str]:
    out = _git(repo, "branch", "--format=%(refname:short)")
    return {l.strip() for l in out.splitlines() if l.strip()}


class TestWorktreeIsolation:
    def test_parallel_tasks_do_not_conflict_and_split_branches(
            self, wt_cfg, repo, mock_state_dir):
        m = _mission([_task("t1", str(repo)), _task("t2", str(repo)),
                      _task("t3", str(repo))])
        run_mission(wt_cfg, m, RunStore(wt_cfg["runs_dir"], m.id))

        assert all(t.status == "done" for t in m.tasks)

        # 3タスクが3つの独立worktreeで実行され、同一ファイル編集が衝突しない
        wt_root = repo / ".orgh-worktrees"
        for t in m.tasks:
            wt = wt_root / f"{m.id}-{t.id}"
            assert Path(t.workdir) == wt
            assert (wt / "shared.txt").read_text() == f"edit-by-{t.id}\n"

        # 元リポのファイルは無傷
        assert (repo / "shared.txt").read_text() == "base\n"

        # タスクごとのブランチに分かれ、Task.branchに記録されている
        expected = {f"orgh/{m.id}/{t.id}" for t in m.tasks}
        assert expected <= _branches(repo)
        assert {t.branch for t in m.tasks} == expected

    def test_workers_actually_ran_inside_worktrees(self, wt_cfg, repo,
                                                   mock_state_dir):
        m = _mission([_task("t1", str(repo))])
        run_mission(wt_cfg, m, RunStore(wt_cfg["runs_dir"], m.id))

        worker_calls = [c for c in read_calls(mock_state_dir)
                        if c["role"] == "worker" and c["marker"] == "t1"]
        wt = str((repo / ".orgh-worktrees" / f"{m.id}-t1").resolve())
        assert worker_calls and all(
            str(Path(c["cwd"]).resolve()) == wt for c in worker_calls)


class TestWorktreeRework:
    def test_rejected_task_reuses_same_worktree(self, wt_cfg, repo,
                                                mock_state_dir, monkeypatch):
        monkeypatch.setenv("MOCK_REJECT_ONCE", "t1")
        m = _mission([_task("t1", str(repo))])
        run_mission(wt_cfg, m, RunStore(wt_cfg["runs_dir"], m.id))

        assert m.tasks[0].status == "done"
        assert m.tasks[0].attempts == 2

        # worktreeは1つだけ。2回のworker実行が同じcwdで走っている
        wt_root = repo / ".orgh-worktrees"
        assert [p.name for p in wt_root.iterdir()] == [f"{m.id}-t1"]
        worker_calls = [c for c in read_calls(mock_state_dir)
                        if c["role"] == "worker" and c["marker"] == "t1"]
        assert len(worker_calls) == 2
        assert worker_calls[0]["cwd"] == worker_calls[1]["cwd"]


class TestWorktreeFallback:
    def test_disabled_keeps_current_behavior(self, cfg, repo, mock_state_dir):
        cfg["worktree"] = {"enabled": False}
        m = _mission([_task("t1", str(repo))])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        assert m.tasks[0].status == "done"
        assert m.tasks[0].workdir == str(repo)     # 差し替えなし
        assert m.tasks[0].branch is None
        assert not (repo / ".orgh-worktrees").exists()
        # 元リポが直接編集される(現行動作)
        assert (repo / "shared.txt").read_text() == "edit-by-t1\n"

    def test_non_git_workdir_falls_back_with_warning(self, wt_cfg, tmp_path,
                                                     mock_state_dir, capsys):
        plain = tmp_path / "plain-dir"
        plain.mkdir()
        m = _mission([_task("t1", str(plain))])
        run_mission(wt_cfg, m, RunStore(wt_cfg["runs_dir"], m.id))

        assert m.tasks[0].status == "done"
        assert m.tasks[0].workdir == str(plain)
        assert m.tasks[0].branch is None
        assert "git" in capsys.readouterr().out  # 警告ログのみでフォールバック


class TestCleanup:
    def test_cleanup_removes_worktrees_and_branches(self, wt_cfg, repo,
                                                    mock_state_dir, tmp_path,
                                                    monkeypatch):
        m = _mission([_task("t1", str(repo)), _task("t2", str(repo))])
        run_mission(wt_cfg, m, RunStore(wt_cfg["runs_dir"], m.id))
        assert (repo / ".orgh-worktrees" / f"{m.id}-t1").exists()

        cfg_path = write_config(tmp_path, wt_cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "cleanup", m.id])
        cli.main()

        assert not (repo / ".orgh-worktrees" / f"{m.id}-t1").exists()
        assert not (repo / ".orgh-worktrees" / f"{m.id}-t2").exists()
        assert not any(b.startswith(f"orgh/{m.id}/") for b in _branches(repo))
        # git側のworktree登録も消えている
        assert f"{m.id}-t1" not in _git(repo, "worktree", "list")

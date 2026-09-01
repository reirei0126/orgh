"""task_executorへのcopyback結線(direction-2026-08 §4 3a')の統合試験。

orgh/copyback.py 単体の契約は tests/test_copyback.py が検証済み。ここでは
「workerがworktree直下に orgh-manifest.json を出力した場合にのみ発動し、
検収合格後にコピーし、ledgerへ記録し、失敗時はタスクをdoneにしない」という
orchestrator結線(orgh/orchestrator/copyback_gate.py, task_executor.py)を、
実際に run_task() を1タスク分走らせて確認する。

manifestは "files"(相対パス・サイズ・SHA-256の一覧)と "dest_root"(絶対パス)
を持つJSON。dest_rootはverify_manifest()の関心の外(コアはfiles一覧の照合
にしか関心を持たない)なので、copyback_gate側が別途読む。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from orgh.copyback import DEFAULT_STAGING_DIR
from orgh.orchestrator.task_executor import run_task
from orgh.state import Budget, RunStore, Task

from .conftest import read_ledger


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_staging(workdir: Path, files: dict[str, str],
                   dest_root: str | None) -> None:
    """workdir(worktree直下)に orgh-manifest.json を置き、成果物は
    `_orgh_staging/` サブディレクトリ配下へ出力する(staging専用サブ
    ディレクトリ契約)。"""
    staging = workdir / DEFAULT_STAGING_DIR
    staging.mkdir(parents=True, exist_ok=True)
    entries = []
    for rel, content in files.items():
        fp = staging / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        entries.append({"path": rel, "size": len(content.encode()),
                        "sha256": _sha256(content.encode())})
    manifest: dict = {"files": entries}
    if dest_root is not None:
        manifest["dest_root"] = dest_root
    (workdir / "orgh-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False))


def _task(id: str, workdir: Path) -> Task:
    return Task(id=id, title=f"task {id}", prompt=f"作業せよ [[MARK:{id}]]",
               worker="claude_code", deps=[],
               acceptance=["mock acceptance"], workdir=str(workdir))


def _budget() -> Budget:
    return Budget(limit_usd=None, task_budget_usd=None, spent_usd=0.0)


class TestNoManifestUnchanged:
    """発動条件: manifest無しのミッションは従来動作を一切変えない。"""

    def test_no_manifest_skips_copyback_and_completes_normally(
            self, cfg, mock_state_dir, tmp_path):
        workdir = tmp_path / "staging1"
        workdir.mkdir()
        store = RunStore(cfg["runs_dir"], "cb-none")
        t = _task("t1", workdir)

        result = run_task(cfg, store, t, _budget())

        assert result.status == "done"
        events = [e["event"] for e in read_ledger(cfg["runs_dir"], "cb-none")]
        assert not any(e.startswith("copyback.") for e in events)


class TestManifestCompleted:
    """manifest有り・検収合格: 宛先に成果物が届き、manifest/completedが記録される。"""

    def test_manifest_and_completed_events_recorded_and_files_delivered(
            self, cfg, mock_state_dir, tmp_path):
        workdir = tmp_path / "staging2"
        dest = tmp_path / "dest2"
        _write_staging(workdir, {"a.txt": "A\n", "sub/b.txt": "B\n"},
                       dest_root=str(dest))
        cfg["copyback"] = {"allowed_roots": [str(dest)]}
        store = RunStore(cfg["runs_dir"], "cb-ok")
        t = _task("t2", workdir)

        result = run_task(cfg, store, t, _budget())

        assert result.status == "done"
        assert (dest / "a.txt").read_text() == "A\n"
        assert (dest / "sub" / "b.txt").read_text() == "B\n"
        events = read_ledger(cfg["runs_dir"], "cb-ok")
        by_event = [e["event"] for e in events]
        assert "copyback.manifest" in by_event
        assert "copyback.completed" in by_event
        manifest_ev = next(e for e in events if e["event"] == "copyback.manifest")
        assert manifest_ev["ok"] is True
        assert manifest_ev["file_count"] == 2
        completed_ev = next(e for e in events if e["event"] == "copyback.completed")
        assert sorted(completed_ev["copied"]) == ["a.txt", "sub/b.txt"]


class TestManifestPartial:
    """コピー途中の失敗注入: copyback.partial が記録されタスクがdoneにならない。"""

    def test_injected_copy_failure_records_partial_and_task_not_done(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        workdir = tmp_path / "staging3"
        dest = tmp_path / "dest3"
        _write_staging(workdir, {"a.txt": "A\n"}, dest_root=str(dest))
        cfg["copyback"] = {"allowed_roots": [str(dest)]}
        store = RunStore(cfg["runs_dir"], "cb-partial")
        t = _task("t3", workdir)

        import orgh.copyback as copyback_mod

        def _boom(src, dst):
            raise OSError("simulated disk failure mid-copy")
        monkeypatch.setattr(copyback_mod, "_copy_file", _boom)

        result = run_task(cfg, store, t, _budget())

        assert result.status != "done"
        events = read_ledger(cfg["runs_dir"], "cb-partial")
        by_event = [e["event"] for e in events]
        assert "copyback.partial" in by_event
        partial_ev = next(e for e in events if e["event"] == "copyback.partial")
        assert partial_ev["reason"]
        assert not (dest / "a.txt").exists()


class TestManifestConflict:
    """worker実行中(=review開始のスナップショット以降)に宛先が変化すると
    copyback.conflict が記録されタスクが awaiting_human へ遷移する。"""

    def test_dest_changed_before_copy_triggers_conflict_and_awaiting_human(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        workdir = tmp_path / "staging4"
        dest = tmp_path / "dest4"
        dest.mkdir()
        (dest / "existing.txt").write_text("original\n")
        _write_staging(workdir, {"a.txt": "A\n"}, dest_root=str(dest))
        cfg["copyback"] = {"allowed_roots": [str(dest)]}
        store = RunStore(cfg["runs_dir"], "cb-conflict")
        t = _task("t4", workdir)

        import orgh.orchestrator.task_executor as task_executor_mod

        def _fake_review_that_edits_dest(cfg, store, t, budget, infra_wait):
            # 検収開始時のbaselineスナップショット取得"後"、コピー実行"前"に
            # 第三者が宛先を書き換えた状況を模す(worker実行中の変化の代理)
            (dest / "existing.txt").write_text("edited-by-someone-else\n")
            return True, ""
        monkeypatch.setattr(task_executor_mod, "run_review_pipeline",
                            _fake_review_that_edits_dest)

        result = run_task(cfg, store, t, _budget())

        assert result.status == "awaiting_human"
        events = read_ledger(cfg["runs_dir"], "cb-conflict")
        by_event = [e["event"] for e in events]
        assert "copyback.conflict" in by_event
        assert not (dest / "a.txt").exists()  # 競合検知時はコピーしない
        assert (dest / "existing.txt").read_text() == "edited-by-someone-else\n"


class TestMisplacedManifestDetection:
    """workerがcopyback成果物(orgh-manifest.json / _orgh_staging)を割り当てられた
    worktree直下ではなく実リポ直下へ誤って作った場合(escape第2号 実測
    runs/af7c4832)、has_manifest(t)はFalseのまま(=従来経路)copyback契約が
    発動しないため、機械検知で copyback.misplaced を記録し差し戻す。"""

    def test_manifest_in_repo_root_instead_of_worktree_triggers_misplaced(
            self, cfg, mock_state_dir, tmp_path):
        repo_root = tmp_path / "repo"
        workdir = repo_root / ".orgh-worktrees" / "cb-misplaced-t1"
        workdir.mkdir(parents=True)
        # worktree直下(workdir)ではなく実リポ直下(repo_root)へ誤配置した状態を再現
        _write_staging(repo_root, {"a.txt": "A\n"},
                       dest_root=str(tmp_path / "dest_mp"))
        store = RunStore(cfg["runs_dir"], "cb-misplaced")
        t = _task("t1", workdir)

        result = run_task(cfg, store, t, _budget())

        assert result.status != "done"
        assert result.status == "awaiting_human"
        events = read_ledger(cfg["runs_dir"], "cb-misplaced")
        by_event = [e["event"] for e in events]
        assert "copyback.misplaced" in by_event
        misplaced_ev = next(e for e in events if e["event"] == "copyback.misplaced")
        assert misplaced_ev["misplaced_root"] == str(repo_root)
        # 誤配置検知時は通常のcopyback契約(manifest/completed)を発動させない
        assert "copyback.manifest" not in by_event


class TestNoMisplacementForNormalTask:
    """worktree形のworkdirでも、manifestも誤配置も無ければ copyback.misplaced は
    記録されず、従来どおりdoneになる(挙動不変)。"""

    def test_worktree_shaped_workdir_without_manifest_stays_unchanged(
            self, cfg, mock_state_dir, tmp_path):
        repo_root = tmp_path / "repo"
        workdir = repo_root / ".orgh-worktrees" / "cb-clean-t1"
        workdir.mkdir(parents=True)
        store = RunStore(cfg["runs_dir"], "cb-clean")
        t = _task("t1", workdir)

        result = run_task(cfg, store, t, _budget())

        assert result.status == "done"
        events = [e["event"] for e in read_ledger(cfg["runs_dir"], "cb-clean")]
        assert "copyback.misplaced" not in events


class TestAllowedRootsRejection:
    """allowed_roots外の宛先は拒否され、タスクがdoneにならない。"""

    def test_dest_outside_allowed_roots_is_rejected_and_task_not_done(
            self, cfg, mock_state_dir, tmp_path):
        workdir = tmp_path / "staging5"
        dest = tmp_path / "dest5"
        _write_staging(workdir, {"a.txt": "A\n"}, dest_root=str(dest))
        cfg["copyback"] = {"allowed_roots": [str(tmp_path / "other-allowed-root")]}
        store = RunStore(cfg["runs_dir"], "cb-allowed-roots")
        t = _task("t5", workdir)

        result = run_task(cfg, store, t, _budget())

        assert result.status != "done"
        assert not dest.exists()
        events = read_ledger(cfg["runs_dir"], "cb-allowed-roots")
        assert any(e["event"] == "copyback.partial" for e in events)

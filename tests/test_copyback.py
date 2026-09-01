"""copyback契約のコア(direction-2026-08 §4 3a'): manifest照合・パス閉包・原子コピー。

git管理外の成果物領域(例: decision-osの private/cases/)への書き戻しを、
manifest(相対パス・サイズ・SHA-256)で照合しながら安全に行う。orchestratorへの
結線は後続タスク(このテストはコアモジュール単体の契約のみを検証する)。

staging専用サブディレクトリ契約: workerの成果物はworktree直下の`_orgh_staging/`
(既定。manifestの`staging_dir`キーで変更可)に置く。manifest自体は従来どおり
worktree直下。実worktreeにはgit管理下の通常ファイルが多数存在するため、
staging外のファイルはverify_manifest()の走査・照合・未列挙拒否の対象外である
ことを検証する(旧設計はworktree全体を走査していたため常時未列挙拒否が発火し、
copybackが一度も成立しなかった=このテストが再発防止する欠陥)。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from orgh.copyback import (
    DEFAULT_STAGING_DIR,
    MANIFEST_FILENAME,
    CopybackError,
    run_copyback,
    verify_manifest,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _manifest(worktree: Path, entries: list[dict], **extra) -> None:
    payload: dict = {"files": entries, **extra}
    (worktree / MANIFEST_FILENAME).write_text(json.dumps(payload))


def _staging(worktree: Path) -> Path:
    return worktree / DEFAULT_STAGING_DIR


def _entry_for(staging: Path, rel: str, *, listed_path: str | None = None) -> dict:
    """staging配下の実ファイルからmanifestエントリを作る(実sizeとhashを使う)。"""
    content = (staging / rel).read_bytes()
    return {"path": listed_path or rel, "size": len(content), "sha256": _sha256(content)}


class TestManifestPathNormalization:
    def test_normalizes_relative_path(self, tmp_path):
        worktree = tmp_path / "worktree"
        staging = _staging(worktree)
        _write(staging / "sub" / "file.txt", "hello\n")
        entry = _entry_for(staging, "sub/file.txt", listed_path="./sub//file.txt")
        _manifest(worktree, [entry])

        result = verify_manifest(worktree)

        assert result.ok is True
        assert result.entries[0].path == "sub/file.txt"


class TestManifestRejection:
    def test_rejects_dotdot_path(self, tmp_path):
        worktree = tmp_path / "worktree"
        staging = _staging(worktree)
        staging.mkdir(parents=True)
        _write(worktree / "outside.txt", "secret\n")
        entry = {"path": "../outside.txt", "size": 7, "sha256": _sha256(b"secret\n")}
        _manifest(worktree, [entry])

        result = verify_manifest(worktree)

        assert result.ok is False
        assert "../outside.txt" in result.rejected

    def test_rejects_absolute_path(self, tmp_path):
        worktree = tmp_path / "worktree"
        staging = _staging(worktree)
        staging.mkdir(parents=True)
        entry = {"path": "/etc/passwd", "size": 0, "sha256": _sha256(b"")}
        _manifest(worktree, [entry])

        result = verify_manifest(worktree)

        assert result.ok is False
        assert "/etc/passwd" in result.rejected

    def test_rejects_symlink(self, tmp_path):
        worktree = tmp_path / "worktree"
        staging = _staging(worktree)
        staging.mkdir(parents=True)
        target = tmp_path / "real.txt"
        target.write_text("real\n")
        link = staging / "link.txt"
        os.symlink(target, link)
        entry = {"path": "link.txt", "size": 5, "sha256": _sha256(b"real\n")}
        _manifest(worktree, [entry])

        result = verify_manifest(worktree)

        assert result.ok is False
        assert "link.txt" in result.rejected

    def test_rejects_unlisted_file_in_staging(self, tmp_path):
        """AC-3: _orgh_staging/配下のmanifest未列挙ファイルは拒否される。"""
        worktree = tmp_path / "worktree"
        staging = _staging(worktree)
        _write(staging / "listed.txt", "a\n")
        _write(staging / "sneaky.txt", "b\n")
        _manifest(worktree, [_entry_for(staging, "listed.txt")])

        result = verify_manifest(worktree)

        assert result.ok is False
        assert "sneaky.txt" in result.rejected

    def test_detects_hash_mismatch(self, tmp_path):
        worktree = tmp_path / "worktree"
        staging = _staging(worktree)
        _write(staging / "file.txt", "actual content\n")
        entry = {"path": "file.txt", "size": len(b"actual content\n"),
                 "sha256": _sha256(b"different content\n")}
        _manifest(worktree, [entry])

        result = verify_manifest(worktree)

        assert result.ok is False
        assert "file.txt" in result.mismatches


class TestStagingScopeRealWorktreeFixture:
    """staging専用サブディレクトリ契約: staging外に通常のリポファイルと.git相当の
    ファイルが混在する実worktree相当のフィクスチャでの検証(escape再発防止)。"""

    def _real_worktree_fixture(self, tmp_path, staged_files: dict[str, str]) -> Path:
        worktree = tmp_path / "worktree"
        # staging外: 実worktreeに数百件存在するトラッキング済みリポファイルの代表
        _write(worktree / "README.md", "# repo\n")
        _write(worktree / "src" / "main.py", "print('hi')\n")
        _write(worktree / "package.json", "{}\n")
        # staging外: .git相当の管理ファイル群の代表
        _write(worktree / ".git" / "HEAD", "ref: refs/heads/main\n")
        _write(worktree / ".git" / "config", "[core]\n")

        staging = _staging(worktree)
        entries = []
        for rel, content in staged_files.items():
            _write(staging / rel, content)
            entries.append(_entry_for(staging, rel))
        _manifest(worktree, entries)
        return worktree

    def test_verify_ok_with_repo_files_and_git_outside_staging(self, tmp_path):
        """AC-1: staging外に通常ファイル+.git相当が混在してもok=Trueを返す。"""
        worktree = self._real_worktree_fixture(
            tmp_path, {"artifact.txt": "result\n", "sub/out.txt": "out\n"})

        result = verify_manifest(worktree)

        assert result.ok is True
        assert sorted(e.path for e in result.entries) == ["artifact.txt", "sub/out.txt"]
        assert result.rejected == {}
        assert result.missing == []
        assert result.mismatches == {}

    def test_staging_outside_files_not_rejected_and_not_copied(self, tmp_path):
        """AC-2: staging外のリポファイルは未列挙拒否の対象にもコピー対象にもならない。"""
        worktree = self._real_worktree_fixture(
            tmp_path, {"artifact.txt": "result\n"})
        dest = tmp_path / "dest"

        verification, result = run_copyback(worktree, dest, [str(dest)])

        assert verification.ok is True
        assert "README.md" not in verification.rejected
        assert "src/main.py" not in verification.rejected
        assert "package.json" not in verification.rejected
        assert not any(".git" in key for key in verification.rejected)

        assert result.status == "completed"
        assert result.copied == ["artifact.txt"]
        assert not (dest / "README.md").exists()
        assert not (dest / "src").exists()
        assert not (dest / "package.json").exists()
        assert not (dest / ".git").exists()
        assert (dest / "artifact.txt").read_text() == "result\n"


class TestStagingDirClosure:
    """AC-4: staging_dirが絶対パスまたは'..'を含む場合に拒否される。"""

    def test_rejects_absolute_staging_dir(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir(parents=True)
        _manifest(worktree, [], staging_dir="/etc")

        result = verify_manifest(worktree)

        assert result.ok is False
        assert "staging_dir" in result.rejected

    def test_rejects_dotdot_staging_dir(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir(parents=True)
        _manifest(worktree, [], staging_dir="../escape")

        result = verify_manifest(worktree)

        assert result.ok is False
        assert "staging_dir" in result.rejected


class TestAllowedRoots:
    def test_rejects_dest_outside_allowed_roots(self, tmp_path):
        worktree = tmp_path / "worktree"
        staging = _staging(worktree)
        _write(staging / "file.txt", "content\n")
        _manifest(worktree, [_entry_for(staging, "file.txt")])
        dest = tmp_path / "dest"
        allowed = [str(tmp_path / "other-allowed-root")]

        with pytest.raises(CopybackError, match="allowed_roots"):
            run_copyback(worktree, dest, allowed)


class TestAtomicCopy:
    def _worktree_with_files(self, tmp_path, files: dict[str, str]) -> Path:
        worktree = tmp_path / "worktree"
        staging = _staging(worktree)
        entries = []
        for rel, content in files.items():
            _write(staging / rel, content)
            entries.append(_entry_for(staging, rel))
        _manifest(worktree, entries)
        return worktree

    def test_completed_copies_all_files(self, tmp_path):
        worktree = self._worktree_with_files(
            tmp_path, {"a.txt": "A\n", "sub/b.txt": "B\n"})
        dest = tmp_path / "dest"
        verification, result = run_copyback(worktree, dest, [str(dest)])

        assert verification.ok is True
        assert result.status == "completed"
        assert (dest / "a.txt").read_text() == "A\n"
        assert (dest / "sub" / "b.txt").read_text() == "B\n"
        assert sorted(result.copied) == ["a.txt", "sub/b.txt"]

    def test_partial_on_injected_failure_leaves_dest_untouched(
            self, tmp_path, monkeypatch):
        worktree = self._worktree_with_files(
            tmp_path, {"a.txt": "A\n", "b.txt": "B\n"})
        dest = tmp_path / "dest"

        import orgh.copyback as copyback_mod

        def _boom(src, dst):
            raise OSError("simulated disk failure mid-copy")

        monkeypatch.setattr(copyback_mod, "_copy_file", _boom)

        verification, result = run_copyback(worktree, dest, [str(dest)])

        assert verification.ok is True
        assert result.status == "partial"
        assert result.reason  # 失敗理由を伴う
        # 宛先が中途半端に汚染されていない(何も配置されていない)
        assert not (dest / "a.txt").exists()
        assert not (dest / "b.txt").exists()
        remaining = [p for p in dest.rglob("*")] if dest.exists() else []
        assert remaining == []

    def test_conflict_when_dest_changed_since_baseline(self, tmp_path):
        worktree = self._worktree_with_files(tmp_path, {"a.txt": "A\n"})
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "existing.txt").write_text("original\n")

        from orgh.copyback import snapshot_tree
        baseline = snapshot_tree(dest)

        # workerの実行「中」に想定外の第三者編集が入った状態を模す
        (dest / "existing.txt").write_text("edited-by-someone-else\n")

        verification, result = run_copyback(
            worktree, dest, [str(dest)], baseline_snapshot=baseline)

        assert verification.ok is True
        assert result.status == "conflict"
        assert not (dest / "a.txt").exists()  # 競合検知時はコピーを行わない


class TestBaselineAwareOverwrite:
    """既存ファイルの『更新』配達の三分岐(skip / baseline不変なら上書き / blocked)。

    旧実装は宛先に内容の異なる既存ファイルがあれば baseline_snapshot の有無に
    関わらず無条件で blocked にしていたため、git管理外領域への更新配達が構造的に
    不可能だった(人力ゼロの更新配達が成立しない)。このクラスがその修正を固定する。
    """

    def _worktree_with_files(self, tmp_path, files: dict[str, str]) -> Path:
        worktree = tmp_path / "worktree"
        staging = _staging(worktree)
        entries = []
        for rel, content in files.items():
            _write(staging / rel, content)
            entries.append(_entry_for(staging, rel))
        _manifest(worktree, entries)
        return worktree

    def test_overwrites_existing_file_unchanged_since_baseline(self, tmp_path):
        """宛先の既存ファイルがbaseline記録と一致 → completed かつ内容が更新される。"""
        worktree = self._worktree_with_files(tmp_path, {"a.txt": "NEW\n"})
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "a.txt").write_text("OLD\n")

        from orgh.copyback import snapshot_tree
        baseline = snapshot_tree(dest)  # 検収開始時のスナップショット

        verification, result = run_copyback(
            worktree, dest, [str(dest)], baseline_snapshot=baseline)

        assert verification.ok is True
        assert result.status == "completed"
        assert result.copied == ["a.txt"]
        assert result.blocked == []
        assert (dest / "a.txt").read_text() == "NEW\n"

    def test_conflict_when_existing_file_changed_since_baseline(self, tmp_path):
        """宛先の既存ファイルがbaseline記録から変化 → conflict でコピーは一切行わない。"""
        worktree = self._worktree_with_files(
            tmp_path, {"a.txt": "NEW\n", "fresh.txt": "F\n"})
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "a.txt").write_text("OLD\n")

        from orgh.copyback import snapshot_tree
        baseline = snapshot_tree(dest)

        # 検収開始後に第三者が宛先を書き換えた
        (dest / "a.txt").write_text("EDITED-BY-SOMEONE-ELSE\n")

        verification, result = run_copyback(
            worktree, dest, [str(dest)], baseline_snapshot=baseline)

        assert verification.ok is True
        assert result.status == "conflict"
        assert result.copied == []
        assert (dest / "a.txt").read_text() == "EDITED-BY-SOMEONE-ELSE\n"
        assert not (dest / "fresh.txt").exists()  # 新規分もコピーしない

    def test_blocked_when_existing_file_absent_from_baseline(self, tmp_path):
        """検収開始後に第三者が新規作成した既存ファイル(baseline記録なし)
        → partial かつ blocked。宛先は書き換わらない。"""
        worktree = self._worktree_with_files(tmp_path, {"a.txt": "NEW\n"})
        dest = tmp_path / "dest"
        dest.mkdir()

        from orgh.copyback import snapshot_tree
        baseline = snapshot_tree(dest)  # この時点では a.txt は存在しない
        assert "a.txt" not in baseline

        # 検収開始後に第三者が同名ファイルを作った
        (dest / "a.txt").write_text("CREATED-BY-SOMEONE-ELSE\n")

        verification, result = run_copyback(
            worktree, dest, [str(dest)], baseline_snapshot=baseline)

        assert verification.ok is True
        assert result.status == "partial"
        assert result.blocked == ["a.txt"]
        assert result.copied == []
        assert (dest / "a.txt").read_text() == "CREATED-BY-SOMEONE-ELSE\n"

    def test_backward_compatible_without_baseline_stays_partial(self, tmp_path):
        """後方互換: baseline_snapshotを渡さない呼び出しでは、内容不一致の既存
        ファイルは従来どおり blocked / partial のまま(宛先は不変)。"""
        worktree = self._worktree_with_files(tmp_path, {"a.txt": "NEW\n"})
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "a.txt").write_text("OLD\n")

        verification, result = run_copyback(worktree, dest, [str(dest)])

        assert verification.ok is True
        assert result.status == "partial"
        assert result.blocked == ["a.txt"]
        assert result.copied == []
        assert (dest / "a.txt").read_text() == "OLD\n"

    def test_signature_keeps_baseline_snapshot_keyword_only(self):
        """AC-4: 新規の必須引数を足していない(baseline_snapshotはkeyword-onlyのまま)。"""
        import inspect

        params = inspect.signature(run_copyback).parameters
        positional = [n for n, p in params.items()
                      if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD]
        assert positional == ["worktree_dir", "dest_root", "allowed_roots"]
        keyword_only = {n: p for n, p in params.items()
                        if p.kind is inspect.Parameter.KEYWORD_ONLY}
        assert sorted(keyword_only) == ["baseline_snapshot", "manifest_filename"]
        assert all(p.default is not inspect.Parameter.empty
                   for p in keyword_only.values())


class TestIdempotentRerun:
    def test_rerun_skips_matching_and_stops_on_mismatch(self, tmp_path):
        worktree = tmp_path / "worktree"
        staging = _staging(worktree)
        _write(staging / "a.txt", "A\n")
        _write(staging / "b.txt", "B\n")
        entries = [
            {"path": "a.txt", "size": len(b"A\n"), "sha256": _sha256(b"A\n")},
            {"path": "b.txt", "size": len(b"B\n"), "sha256": _sha256(b"B\n")},
        ]
        _manifest(worktree, entries)
        dest = tmp_path / "dest"

        _, first = run_copyback(worktree, dest, [str(dest)])
        assert first.status == "completed"

        # 宛先を人手/別プロセスで書き換え、manifestの期待値とズレさせる
        (dest / "b.txt").write_text("B-modified-independently\n")

        _, second = run_copyback(worktree, dest, [str(dest)])

        assert second.status == "partial"
        assert "a.txt" in second.skipped     # hash一致はskip
        assert "b.txt" in second.blocked     # 不一致は自動上書きせず人間裁定へ
        # 不一致ファイルは上書きされていない(裁定待ちのまま保持)
        assert (dest / "b.txt").read_text() == "B-modified-independently\n"

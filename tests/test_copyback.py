"""copyback契約のコア(direction-2026-08 §4 3a'): manifest照合・パス閉包・原子コピー。

git管理外の成果物領域(例: decision-osの private/cases/)への書き戻しを、
manifest(相対パス・サイズ・SHA-256)で照合しながら安全に行う。orchestratorへの
結線は後続タスク(このテストはコアモジュール単体の契約のみを検証する)。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from orgh.copyback import (
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


def _manifest(staging: Path, entries: list[dict]) -> None:
    (staging / MANIFEST_FILENAME).write_text(json.dumps({"files": entries}))


def _entry_for(staging: Path, rel: str, *, listed_path: str | None = None) -> dict:
    """staging配下の実ファイルからmanifestエントリを作る(実sizeとhashを使う)。"""
    content = (staging / rel).read_bytes()
    return {"path": listed_path or rel, "size": len(content), "sha256": _sha256(content)}


class TestManifestPathNormalization:
    def test_normalizes_relative_path(self, tmp_path):
        staging = tmp_path / "staging"
        _write(staging / "sub" / "file.txt", "hello\n")
        entry = _entry_for(staging, "sub/file.txt", listed_path="./sub//file.txt")
        _manifest(staging, [entry])

        result = verify_manifest(staging)

        assert result.ok is True
        assert result.entries[0].path == "sub/file.txt"


class TestManifestRejection:
    def test_rejects_dotdot_path(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir(parents=True)
        _write(tmp_path / "outside.txt", "secret\n")
        entry = {"path": "../outside.txt", "size": 7, "sha256": _sha256(b"secret\n")}
        _manifest(staging, [entry])

        result = verify_manifest(staging)

        assert result.ok is False
        assert "../outside.txt" in result.rejected

    def test_rejects_absolute_path(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir(parents=True)
        entry = {"path": "/etc/passwd", "size": 0, "sha256": _sha256(b"")}
        _manifest(staging, [entry])

        result = verify_manifest(staging)

        assert result.ok is False
        assert "/etc/passwd" in result.rejected

    def test_rejects_symlink(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir(parents=True)
        target = tmp_path / "real.txt"
        target.write_text("real\n")
        link = staging / "link.txt"
        os.symlink(target, link)
        entry = {"path": "link.txt", "size": 5, "sha256": _sha256(b"real\n")}
        _manifest(staging, [entry])

        result = verify_manifest(staging)

        assert result.ok is False
        assert "link.txt" in result.rejected

    def test_rejects_unlisted_file(self, tmp_path):
        staging = tmp_path / "staging"
        _write(staging / "listed.txt", "a\n")
        _write(staging / "sneaky.txt", "b\n")
        _manifest(staging, [_entry_for(staging, "listed.txt")])

        result = verify_manifest(staging)

        assert result.ok is False
        assert "sneaky.txt" in result.rejected

    def test_detects_hash_mismatch(self, tmp_path):
        staging = tmp_path / "staging"
        _write(staging / "file.txt", "actual content\n")
        entry = {"path": "file.txt", "size": len(b"actual content\n"),
                 "sha256": _sha256(b"different content\n")}
        _manifest(staging, [entry])

        result = verify_manifest(staging)

        assert result.ok is False
        assert "file.txt" in result.mismatches


class TestAllowedRoots:
    def test_rejects_dest_outside_allowed_roots(self, tmp_path):
        staging = tmp_path / "staging"
        _write(staging / "file.txt", "content\n")
        _manifest(staging, [_entry_for(staging, "file.txt")])
        dest = tmp_path / "dest"
        allowed = [str(tmp_path / "other-allowed-root")]

        with pytest.raises(CopybackError, match="allowed_roots"):
            run_copyback(staging, dest, allowed)


class TestAtomicCopy:
    def _staging_with_files(self, tmp_path, files: dict[str, str]) -> Path:
        staging = tmp_path / "staging"
        entries = []
        for rel, content in files.items():
            _write(staging / rel, content)
            entries.append(_entry_for(staging, rel))
        _manifest(staging, entries)
        return staging

    def test_completed_copies_all_files(self, tmp_path):
        staging = self._staging_with_files(
            tmp_path, {"a.txt": "A\n", "sub/b.txt": "B\n"})
        dest = tmp_path / "dest"
        verification, result = run_copyback(staging, dest, [str(dest)])

        assert verification.ok is True
        assert result.status == "completed"
        assert (dest / "a.txt").read_text() == "A\n"
        assert (dest / "sub" / "b.txt").read_text() == "B\n"
        assert sorted(result.copied) == ["a.txt", "sub/b.txt"]

    def test_partial_on_injected_failure_leaves_dest_untouched(
            self, tmp_path, monkeypatch):
        staging = self._staging_with_files(
            tmp_path, {"a.txt": "A\n", "b.txt": "B\n"})
        dest = tmp_path / "dest"

        import orgh.copyback as copyback_mod

        def _boom(src, dst):
            raise OSError("simulated disk failure mid-copy")

        monkeypatch.setattr(copyback_mod, "_copy_file", _boom)

        verification, result = run_copyback(staging, dest, [str(dest)])

        assert verification.ok is True
        assert result.status == "partial"
        assert result.reason  # 失敗理由を伴う
        # 宛先が中途半端に汚染されていない(何も配置されていない)
        assert not (dest / "a.txt").exists()
        assert not (dest / "b.txt").exists()
        remaining = [p for p in dest.rglob("*")] if dest.exists() else []
        assert remaining == []

    def test_conflict_when_dest_changed_since_baseline(self, tmp_path):
        staging = self._staging_with_files(tmp_path, {"a.txt": "A\n"})
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "existing.txt").write_text("original\n")

        from orgh.copyback import snapshot_tree
        baseline = snapshot_tree(dest)

        # workerの実行「中」に想定外の第三者編集が入った状態を模す
        (dest / "existing.txt").write_text("edited-by-someone-else\n")

        verification, result = run_copyback(
            staging, dest, [str(dest)], baseline_snapshot=baseline)

        assert verification.ok is True
        assert result.status == "conflict"
        assert not (dest / "a.txt").exists()  # 競合検知時はコピーを行わない


class TestIdempotentRerun:
    def test_rerun_skips_matching_and_stops_on_mismatch(self, tmp_path):
        staging = tmp_path / "staging"
        _write(staging / "a.txt", "A\n")
        _write(staging / "b.txt", "B\n")
        entries = [
            {"path": "a.txt", "size": len(b"A\n"), "sha256": _sha256(b"A\n")},
            {"path": "b.txt", "size": len(b"B\n"), "sha256": _sha256(b"B\n")},
        ]
        _manifest(staging, entries)
        dest = tmp_path / "dest"

        _, first = run_copyback(staging, dest, [str(dest)])
        assert first.status == "completed"

        # 宛先を人手/別プロセスで書き換え、manifestの期待値とズレさせる
        (dest / "b.txt").write_text("B-modified-independently\n")

        _, second = run_copyback(staging, dest, [str(dest)])

        assert second.status == "partial"
        assert "a.txt" in second.skipped     # hash一致はskip
        assert "b.txt" in second.blocked     # 不一致は自動上書きせず人間裁定へ
        # 不一致ファイルは上書きされていない(裁定待ちのまま保持)
        assert (dest / "b.txt").read_text() == "B-modified-independently\n"

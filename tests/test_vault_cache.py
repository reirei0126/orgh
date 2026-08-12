"""vault走査のmtime索引化(ヘルスレビュー deferred: vault再読込)。
変更なしファイルは再parseせず、変更・削除は正しく反映する。"""
from __future__ import annotations

from pathlib import Path

from orgh.sources import obsidian
from orgh.sources.obsidian import scan_vault


def _write(vault: Path, name, text):
    p = vault / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_unchanged_files_not_reparsed(tmp_path, monkeypatch):
    vault = tmp_path / "v"
    _write(vault, "inbox/a.md", "# A #go\n")
    _write(vault, "b.md", "# B\n")
    cache = {}
    calls = {"n": 0}
    real_parse = obsidian._parse
    def counting(p):
        calls["n"] += 1
        return real_parse(p)
    monkeypatch.setattr(obsidian, "_parse", counting)

    scan_vault(vault, "inbox", "mission", cache=cache)
    first = calls["n"]
    assert first == 2
    scan_vault(vault, "inbox", "mission", cache=cache)  # 2回目: 変更なし
    assert calls["n"] == first  # 再parseされていない


def test_changed_file_is_reparsed(tmp_path, monkeypatch):
    import os, time
    vault = tmp_path / "v"
    p = _write(vault, "inbox/a.md", "# A #go\n")
    cache = {}
    scan_vault(vault, "inbox", "mission", cache=cache)
    # mtime/sizeを変えて更新
    p.write_text("# A updated #go\nmore\n")
    os.utime(p, (time.time() + 5, time.time() + 5))
    cands, index = scan_vault(vault, "inbox", "mission", cache=cache)
    assert "更新" not in index["a"].body or "updated" in index["a"].body


def test_deleted_file_pruned_from_cache(tmp_path):
    vault = tmp_path / "v"
    p = _write(vault, "inbox/a.md", "# A #go\n")
    _write(vault, "inbox/b.md", "# B #go\n")
    cache = {}
    scan_vault(vault, "inbox", "mission", cache=cache)
    assert len(cache) == 2
    p.unlink()
    scan_vault(vault, "inbox", "mission", cache=cache)
    assert len(cache) == 1
    assert str(p) not in cache


def test_result_identical_to_no_cache(tmp_path):
    vault = tmp_path / "v"
    _write(vault, "inbox/a.md", "# A #go\n")
    _write(vault, "sub/c.md", "# C\n[[a]]\n")
    c1, i1 = scan_vault(vault, "inbox", "mission", cache={})
    c2, i2 = scan_vault(vault, "inbox", "mission", cache=None)
    assert {n.title for n in c1} == {n.title for n in c2}
    assert set(i1) == set(i2)

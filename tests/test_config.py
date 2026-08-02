"""HANDOFF 0b: config検証(dataclassスキーマ。未知キー警告・必須キー欠落エラー)。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orgh.state import ConfigError, ConfigWarning, load_config

REPO = Path(__file__).resolve().parent.parent

VALID = {
    "workers": {"enabled": ["claude_code"], "claude_code": {"bin": "claude"}},
    "loop": {"parallel": 2, "max_attempts": 3, "task_timeout": 60},
}


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True))
    return p


class TestConfigValidation:
    def test_example_config_is_valid(self, recwarn):
        cfg = load_config(REPO / "config.example.yaml")
        assert "workers" in cfg
        assert [w for w in recwarn if isinstance(w.message, ConfigWarning)] == []

    def test_valid_minimal_config(self, tmp_path):
        cfg = load_config(_write(tmp_path, VALID))
        assert cfg["loop"]["parallel"] == 2

    def test_missing_workers_is_error(self, tmp_path):
        data = {k: v for k, v in VALID.items() if k != "workers"}
        with pytest.raises(ConfigError):
            load_config(_write(tmp_path, data))

    def test_unknown_toplevel_key_warns(self, tmp_path):
        data = {**VALID, "worktreee": {"enabled": True}}
        with pytest.warns(ConfigWarning, match="worktreee"):
            load_config(_write(tmp_path, data))

    def test_unknown_nested_key_warns(self, tmp_path):
        data = {**VALID, "loop": {"parallel": 2, "max_attemps": 5}}
        with pytest.warns(ConfigWarning, match="max_attemps"):
            load_config(_write(tmp_path, data))

    def test_wrong_type_is_error(self, tmp_path):
        data = {**VALID, "loop": {"parallel": "three"}}
        with pytest.raises(ConfigError, match="parallel"):
            load_config(_write(tmp_path, data))

    def test_missing_file_is_clear_error(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nope.yaml")

    def test_worktree_section_is_known(self, tmp_path, recwarn):
        data = {**VALID, "worktree": {"enabled": True, "base_ref": "HEAD",
                                      "root": ".orgh-worktrees"}}
        load_config(_write(tmp_path, data))
        assert [w for w in recwarn if isinstance(w.message, ConfigWarning)] == []

    def test_worktree_unknown_key_warns(self, tmp_path):
        data = {**VALID, "worktree": {"enabled": True, "base_reff": "HEAD"}}
        with pytest.warns(ConfigWarning, match="base_reff"):
            load_config(_write(tmp_path, data))

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

    def test_projects_map_is_known(self, tmp_path, recwarn):
        data = {**VALID, "projects_map": "/path/to/projects-map.md"}
        load_config(_write(tmp_path, data))
        assert [w for w in recwarn if isinstance(w.message, ConfigWarning)] == []

    def test_projects_map_wrong_type_is_error(self, tmp_path):
        data = {**VALID, "projects_map": ["a", "b"]}
        with pytest.raises(ConfigError, match="projects_map"):
            load_config(_write(tmp_path, data))

    def test_worktree_unknown_key_warns(self, tmp_path):
        data = {**VALID, "worktree": {"enabled": True, "base_reff": "HEAD"}}
        with pytest.warns(ConfigWarning, match="base_reff"):
            load_config(_write(tmp_path, data))

    def test_personas_enabled_as_bare_string_is_error(self, tmp_path):
        """personas.enabled(list[str])に文字列を渡すとバリデーションで弾く。
        従来は未対応で ['c','o','n','s','u','m','e','r'] に化けて1文字ずつ
        ペルソナ扱いされ、ワーカー実行後に初めて失敗していた(検証済み設定罠)。"""
        data = {**VALID, "personas": {"enabled": "consumer"}}
        with pytest.raises(ConfigError, match="personas.enabled"):
            load_config(_write(tmp_path, data))

    def test_personas_enabled_list_with_non_str_element_is_error(self, tmp_path):
        data = {**VALID, "personas": {"enabled": ["consumer", 1]}}
        with pytest.raises(ConfigError, match="personas.enabled"):
            load_config(_write(tmp_path, data))

    def test_personas_enabled_valid_list_is_accepted(self, tmp_path, recwarn):
        data = {**VALID, "personas": {"enabled": ["consumer", "designer"]}}
        load_config(_write(tmp_path, data))
        assert [w for w in recwarn if isinstance(w.message, ConfigWarning)] == []

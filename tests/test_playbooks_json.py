"""orgh playbooks --json: playbooks/配下の教訓を機械可読で返す契約の検証。

P1-3(desktop/API.md §1.7)。ミッションIDコメント(`<!-- m:xxxx d:YYYY-MM-DD -->`)
が付いたエントリは mission_id/date を分離して返す。playbookが1件も無い場合は
エラーではなく空配列(終了コード0)。
"""
from __future__ import annotations

import json
import sys

import pytest

from orgh import cli
from orgh.playbooks_json import playbooks_payload

from .conftest import write_config


class TestPlaybooksPayload:
    """playbooks_payload() 単体の純関数としての振る舞い。"""

    def test_empty_dir_returns_empty_list_not_error(self, cfg, tmp_path):
        cfg["playbooks_dir"] = str(tmp_path / "no-such-dir")
        payload = playbooks_payload(cfg)
        assert payload == {"playbooks": []}

    def test_no_md_files_returns_empty_list(self, cfg, tmp_path):
        d = tmp_path / "playbooks"
        d.mkdir()
        (d / "notes.txt").write_text("- not a playbook file")
        cfg["playbooks_dir"] = str(d)
        payload = playbooks_payload(cfg)
        assert payload == {"playbooks": []}

    def test_entry_with_mission_tag_split_from_text(self, cfg, tmp_path):
        d = tmp_path / "playbooks"
        d.mkdir()
        (d / "coding.md").write_text(
            "# コーディング\n"
            "- 資産生成を並列分解する前に契約を確定する <!-- m:7307189e d:2026-08-05 -->\n"
            "- Retroが自動追記する。手で書き足してもいい(むしろ推奨)。\n"
        )
        cfg["playbooks_dir"] = str(d)
        payload = playbooks_payload(cfg)
        assert len(payload["playbooks"]) == 1
        pb = payload["playbooks"][0]
        assert pb["name"] == "coding"
        assert pb["path"] == str((d / "coding.md").resolve())
        assert "資産生成を並列分解する前に契約を確定する" in pb["body"]

        tagged, untagged = pb["entries"]
        assert tagged["mission_id"] == "7307189e"
        assert tagged["date"] == "2026-08-05"
        assert tagged["text"] == "資産生成を並列分解する前に契約を確定する"
        assert "<!--" not in tagged["text"]

        assert untagged["mission_id"] is None
        assert untagged["date"] is None
        assert untagged["text"] == "Retroが自動追記する。手で書き足してもいい(むしろ推奨)。"

    def test_non_bullet_lines_excluded_from_entries(self, cfg, tmp_path):
        d = tmp_path / "playbooks"
        d.mkdir()
        (d / "coding.md").write_text(
            "# 見出し行\n\n- 唯一のエントリ\n"
        )
        cfg["playbooks_dir"] = str(d)
        payload = playbooks_payload(cfg)
        entries = payload["playbooks"][0]["entries"]
        assert len(entries) == 1
        assert entries[0]["text"] == "唯一のエントリ"

    def test_multiple_files_sorted_by_name(self, cfg, tmp_path):
        d = tmp_path / "playbooks"
        d.mkdir()
        (d / "zeta.md").write_text("- z\n")
        (d / "alpha.md").write_text("- a\n")
        cfg["playbooks_dir"] = str(d)
        payload = playbooks_payload(cfg)
        assert [p["name"] for p in payload["playbooks"]] == ["alpha", "zeta"]

    def test_payload_is_json_dumpable(self, cfg, tmp_path):
        d = tmp_path / "playbooks"
        d.mkdir()
        (d / "coding.md").write_text(
            "- tagged <!-- m:abc123 d:2026-01-01 -->\n")
        cfg["playbooks_dir"] = str(d)
        payload = playbooks_payload(cfg)
        json.dumps(payload, ensure_ascii=False)  # 例外を出さない


class TestPlaybooksJsonCli:
    def test_cli_playbooks_json_outputs_parseable_json(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        d = tmp_path / "playbooks"
        d.mkdir()
        (d / "coding.md").write_text("- 教訓その1\n")
        cfg["playbooks_dir"] = str(d)
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "playbooks", "--json"])
        cli.main()  # 正常時はexitしない

        payload = json.loads(capsys.readouterr().out)
        assert payload["playbooks"][0]["name"] == "coding"

    def test_cli_playbooks_json_empty_when_no_playbooks_dir_exits_zero(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cfg["playbooks_dir"] = str(tmp_path / "does-not-exist")
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "playbooks", "--json"])
        cli.main()  # 例外/SystemExitを出さない = 終了コード0相当

        payload = json.loads(capsys.readouterr().out)
        assert payload == {"playbooks": []}

    def test_cli_playbooks_without_json_flag_does_not_crash(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        d = tmp_path / "playbooks"
        d.mkdir()
        (d / "coding.md").write_text("- 教訓その1\n")
        cfg["playbooks_dir"] = str(d)
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "playbooks"])
        cli.main()

        out = capsys.readouterr().out
        assert "coding" in out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)

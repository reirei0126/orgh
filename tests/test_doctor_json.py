"""orgh doctor --json: 疎通確認結果を機械可読で返す契約の検証。"""
from __future__ import annotations

import json
import sys

import pytest

from orgh import cli
from orgh.doctor import doctor_payload

from .conftest import write_config

REQUIRED_CHECK_KEYS = {"name", "ok", "detail"}


class TestDoctorPayload:
    def test_payload_is_json_dumpable_with_required_keys(self, cfg):
        payload = doctor_payload(cfg)
        dumped = json.dumps(payload, ensure_ascii=False)
        reloaded = json.loads(dumped)
        assert set(reloaded.keys()) == {"ok", "checks"}
        assert reloaded["checks"]
        for check in reloaded["checks"]:
            assert REQUIRED_CHECK_KEYS <= check.keys()

    def test_ok_true_with_mock_binaries(self, cfg):
        payload = doctor_payload(cfg)
        assert payload["ok"] is True
        assert all(c["ok"] for c in payload["checks"])

    def test_ok_false_on_missing_binary(self, cfg):
        cfg["workers"]["claude_code"]["bin"] = "/nonexistent/claude-xyz"
        payload = doctor_payload(cfg)
        assert payload["ok"] is False
        bad = [c for c in payload["checks"] if not c["ok"]]
        assert any("claude" in c["name"] for c in bad)


class TestDoctorJsonCli:
    def test_cli_doctor_json_outputs_parseable_json(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "doctor", "--json"])
        cli.main()  # 正常時はexitしない

        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert isinstance(payload["checks"], list)

    def test_cli_doctor_json_exits_nonzero_and_reports_error_on_failure(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cfg["workers"]["claude_code"]["bin"] = "/nonexistent/claude-xyz"
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "doctor", "--json"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code != 0

        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False

    def test_cli_doctor_without_json_flag_prints_human_text(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "doctor"])
        cli.main()

        out = capsys.readouterr().out
        assert "OK" in out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)


class TestDoctorBrokenRoleValues:
    """壊れたrole設定値でdoctor自体が死なずNGチェックとして報告する。"""

    def test_role_bin_null_reported_not_crash(self, cfg):
        cfg["roles"]["planner"] = {"bin": None}
        payload = doctor_payload(cfg)
        assert payload["ok"] is False
        bad = [c for c in payload["checks"] if c["name"] == "role:planner"]
        assert bad and bad[0]["ok"] is False

    def test_role_value_null_reported_not_crash(self, cfg):
        cfg["roles"]["planner"] = None
        payload = doctor_payload(cfg)
        assert payload["ok"] is False
        roles_check = [c for c in payload["checks"] if c["name"] == "roles"]
        assert roles_check and roles_check[0]["ok"] is False

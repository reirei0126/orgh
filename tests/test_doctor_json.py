"""orgh doctor --json: 疎通確認結果を機械可読で返す契約の検証。"""
from __future__ import annotations

import json
import sys

import pytest

from orgh import cli
from orgh.doctor import doctor_payload

from .conftest import MOCK_CLAUDE, write_config

REQUIRED_CHECK_KEYS = {"name", "ok", "detail"}
REQUIRED_CHECK_KEYS_P2 = REQUIRED_CHECK_KEYS | {"kind", "auth_state"}


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

    def test_worker_value_string_reported_not_crash(self, cfg):
        cfg["workers"]["claude_code"] = "invalid"
        payload = doctor_payload(cfg)
        assert payload["ok"] is False
        bad = [c for c in payload["checks"] if c["name"] == "worker:claude_code"]
        assert bad and bad[0]["ok"] is False

    def test_shell_worker_broken_argv_reported_not_silent(self, cfg):
        cfg["workers"]["enabled"] = list(cfg["workers"]["enabled"]) + ["shell"]
        cfg["workers"]["shell"] = {"argv": None}
        payload = doctor_payload(cfg)
        assert payload["ok"] is False
        bad = [c for c in payload["checks"] if c["name"] == "worker:shell"]
        assert bad and bad[0]["ok"] is False


class TestDoctorAuthState:
    """P0-1(G-07): worker:<name> チェックの認証状態(auth_state)。

    疎通(--version)だけでなく、対話ログイン不要な認証確認手段が実在する
    ワーカー種別(claude_code/codex)では実際に確認し、確認手段が無い種別
    (shell)では無条件のOKにせず unverified を返す(API.md §1.3)。
    """

    def test_all_checks_carry_kind_and_auth_state(self, cfg):
        payload = doctor_payload(cfg)
        for check in payload["checks"]:
            assert REQUIRED_CHECK_KEYS_P2 <= check.keys()
            assert check["kind"] == "connectivity"

    def test_non_executable_checks_have_auth_state_na(self, cfg):
        # role:*はClaudeCodeAdapter経由で実行されるためworkerと同様に認証確認の
        # 対象(Codexレビューp2r1で是正)。n/aは実行を伴わないチェックのみ
        payload = doctor_payload(cfg)
        for check in payload["checks"]:
            if not check["name"].startswith(("worker:", "role:")):
                assert check["auth_state"] == "n/a", check

    def test_role_checks_have_auth_state(self, cfg):
        payload = doctor_payload(cfg)
        role_checks = [c for c in payload["checks"]
                       if c["name"].startswith("role:")]
        assert role_checks
        for c in role_checks:
            assert c["auth_state"] in ("ok", "unverified", "failed"), c

    def test_claude_worker_auth_ok_by_default(self, cfg):
        payload = doctor_payload(cfg)
        c = next(x for x in payload["checks"] if x["name"] == "worker:claude_code")
        assert c["auth_state"] == "ok"
        assert c["ok"] is True
        assert "認証" in c["detail"]

    def test_claude_worker_auth_failed_forces_ok_false(self, cfg, monkeypatch):
        monkeypatch.setenv("MOCK_CLAUDE_AUTH", "failed")
        payload = doctor_payload(cfg)
        c = next(x for x in payload["checks"] if x["name"] == "worker:claude_code")
        assert c["auth_state"] == "failed"
        assert c["ok"] is False
        assert "認証切れ" in c["detail"]
        assert payload["ok"] is False

    def test_codex_worker_auth_ok_by_default(self, cfg):
        payload = doctor_payload(cfg)
        c = next(x for x in payload["checks"] if x["name"] == "worker:codex")
        assert c["auth_state"] == "ok"
        assert c["ok"] is True

    def test_codex_worker_auth_failed_forces_ok_false(self, cfg, monkeypatch):
        monkeypatch.setenv("MOCK_CODEX_AUTH", "failed")
        payload = doctor_payload(cfg)
        c = next(x for x in payload["checks"] if x["name"] == "worker:codex")
        assert c["auth_state"] == "failed"
        assert c["ok"] is False
        assert payload["ok"] is False

    def test_shell_worker_auth_unverified_not_silent_ok(self, cfg):
        cfg["workers"]["enabled"] = list(cfg["workers"]["enabled"]) + ["shell"]
        cfg["workers"]["shell"] = {"argv": [MOCK_CLAUDE, "{prompt}"]}
        payload = doctor_payload(cfg)
        c = next(x for x in payload["checks"] if x["name"] == "worker:shell")
        assert c["auth_state"] == "unverified"
        assert "認証未確認" in c["detail"]
        # 疎通(--version相当)自体はOKのままであるべき(認証未確認≠疎通NG)
        assert c["ok"] is True

    def test_cli_doctor_json_includes_auth_state(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "doctor", "--json"])
        cli.main()
        payload = json.loads(capsys.readouterr().out)
        worker_checks = [c for c in payload["checks"]
                          if c["name"].startswith("worker:")]
        assert worker_checks
        for c in worker_checks:
            assert c["auth_state"] in ("ok", "unverified", "failed")

"""worker環境変数のallowlist(ヘルスレビュー deferred: worker env)。
秘密パターンの変数を継承させず、認証用の既定keep・config指定は通す。"""
from __future__ import annotations

from orgh.adapters.base import filtered_env


def test_secret_vars_are_stripped(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_xxx")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s3cr3t")
    monkeypatch.setenv("MY_DB_PASSWORD", "pw")
    env = filtered_env({})
    assert "GITHUB_TOKEN" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "MY_DB_PASSWORD" not in env


def test_base_vars_pass_through(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/x")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    env = filtered_env({})
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/x"
    assert env["CLAUDE_CODE_ENTRYPOINT"] == "cli"  # KEY/TOKEN等を含まない


def test_default_auth_keep_passes(monkeypatch):
    # APIキー認証のworkerを壊さない: 既定keepは秘密パターンでも通す
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxx")
    env = filtered_env({})
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-xxx"


def test_config_allowlist_passes(monkeypatch):
    monkeypatch.setenv("MY_CUSTOM_TOKEN", "keepme")
    assert "MY_CUSTOM_TOKEN" not in filtered_env({})
    env = filtered_env({"env_secret_allow": ["MY_CUSTOM_TOKEN"]})
    assert env["MY_CUSTOM_TOKEN"] == "keepme"


def test_mock_env_vars_pass_through(monkeypatch):
    # テスト用MOCK_*は秘密パターンに当たらず継承される(既存テストを壊さない)
    monkeypatch.setenv("MOCK_PLAN_JSON", "{}")
    monkeypatch.setenv("MOCK_WORKER_FAIL", "t1")
    env = filtered_env({})
    assert "MOCK_PLAN_JSON" in env and "MOCK_WORKER_FAIL" in env

"""`orgh notion pull` (orgh/notion.py) の結合テスト。

tests/mocks/notion_mcp をMCPサーバに見立て、(a) ノート生成、(b) 同一ページ
再pullの冪等性(ノート数・内容が不変)、(c) 新規ページのみ追加取込、
(d) トークン環境変数未設定時の挙動、(e) ツール解決失敗時の明示エラー、を
検証する。実Notionへの接続は行わない。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from orgh.notion import (NotionConfigError, NotionDisabledError,
                         NotionToolResolutionError, pull)

REPO = Path(__file__).resolve().parent.parent
MOCK_NOTION = str(REPO / "tests" / "mocks" / "notion_mcp")

TOKEN_ENV = "ORGH_TEST_NOTION_TOKEN"


@pytest.fixture
def vault(tmp_path) -> Path:
    v = tmp_path / "vault"
    (v / "inbox").mkdir(parents=True)
    return v


@pytest.fixture
def cfg(tmp_path, vault) -> dict:
    return {
        "workers": {"enabled": []},
        "runs_dir": str(tmp_path / "runs"),
        "vault": {"path": str(vault), "inbox": "inbox", "mission_tag": "mission",
                  "trigger_tag": "go"},
        "notion": {
            "mcp_command": [MOCK_NOTION],
            "database_id": "db-mock-1",
            "token_env": TOKEN_ENV,
        },
    }


class TestPull:
    def test_pull_writes_mission_notes(self, cfg, vault, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "dummy-token-value")
        written = pull(cfg)
        assert len(written) == 2
        notes = list((vault / "inbox").glob("*.md"))
        assert len(notes) == 2
        text = notes[0].read_text()
        assert "tags: [mission]" in text
        assert "notion_page_id:" in text
        assert "source: notion" in text
        # 着火トリガタグは付けない(人間が既存Obsidian経路で着火する設計)
        assert "#go" not in text
        assert "orgh: go" not in text

    def test_pull_is_idempotent_on_second_call(self, cfg, vault, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "dummy-token-value")
        first = pull(cfg)
        assert len(first) == 2
        before = {p.name: p.read_text() for p in (vault / "inbox").glob("*.md")}

        second = pull(cfg)
        assert second == []  # 新規ノートは作られない

        after = {p.name: p.read_text() for p in (vault / "inbox").glob("*.md")}
        assert before == after  # ノート数・内容が不変(既存ノートも上書きしない)

    def test_pull_picks_up_new_pages_only(self, cfg, vault, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "dummy-token-value")
        pull(cfg)

        db = json.dumps({"db-mock-1": [
            {"id": "page-001", "url": "https://notion.so/page-001",
             "properties": {"Name": {"type": "title",
                                     "title": [{"plain_text": "最初のページ"}]}},
             "blocks": []},
            {"id": "page-003", "url": "https://notion.so/page-003",
             "properties": {"Name": {"type": "title",
                                     "title": [{"plain_text": "3番目のページ"}]}},
             "blocks": [{"type": "paragraph",
                        "paragraph": {"rich_text": [{"plain_text": "新規"}]}}]},
        ]})
        monkeypatch.setenv("MOCK_NOTION_DB", db)

        second = pull(cfg)
        assert len(second) == 1
        assert "page-003" in second[0].read_text()
        assert len(list((vault / "inbox").glob("*.md"))) == 3


class TestConfigErrors:
    def test_disabled_when_mcp_command_empty(self, cfg, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "dummy-token-value")
        cfg["notion"]["mcp_command"] = []
        with pytest.raises(NotionDisabledError):
            pull(cfg)

    def test_missing_token_env_raises_before_spawning_server(self, cfg, monkeypatch):
        """トークン環境変数が未設定ならMCPサーバを起動する前に明示エラーで
        落ちること。存在しないコマンドを指しても(McpProcessErrorではなく)
        NotionConfigErrorになることで、実際に起動を試みていないと確認できる。"""
        monkeypatch.delenv(TOKEN_ENV, raising=False)
        cfg["notion"]["mcp_command"] = ["/no/such/binary/orgh-notion-test"]
        with pytest.raises(NotionConfigError):
            pull(cfg)

    def test_missing_database_id_raises(self, cfg, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "dummy-token-value")
        cfg["notion"]["database_id"] = ""
        with pytest.raises(NotionConfigError):
            pull(cfg)

    def test_missing_vault_path_raises(self, cfg, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "dummy-token-value")
        cfg["vault"]["path"] = ""
        with pytest.raises(NotionConfigError):
            pull(cfg)

    def test_unresolvable_tool_raises(self, cfg, monkeypatch):
        """サーバが想定ツール名をどれも提供しない場合、フォールバック解決に
        失敗して明示エラーになること。"""
        monkeypatch.setenv(TOKEN_ENV, "dummy-token-value")
        script = (
            "import json, sys\n"
            "for line in sys.stdin:\n"
            "    req = json.loads(line)\n"
            "    rid, m = req.get('id'), req.get('method')\n"
            "    if m == 'initialize':\n"
            "        out = {'jsonrpc': '2.0', 'id': rid,\n"
            "               'result': {'protocolVersion': '2025-06-18'}}\n"
            "    elif m == 'notifications/initialized':\n"
            "        continue\n"
            "    elif m == 'tools/list':\n"
            "        out = {'jsonrpc': '2.0', 'id': rid,\n"
            "               'result': {'tools': [{'name': 'unrelated_tool'}]}}\n"
            "    else:\n"
            "        out = {'jsonrpc': '2.0', 'id': rid, 'error':\n"
            "               {'code': -32601, 'message': 'unknown'}}\n"
            "    sys.stdout.write(json.dumps(out) + '\\n')\n"
            "    sys.stdout.flush()\n"
        )
        cfg["notion"]["mcp_command"] = [sys.executable, "-c", script]
        with pytest.raises(NotionToolResolutionError):
            pull(cfg)

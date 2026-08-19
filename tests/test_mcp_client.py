"""orgh/mcp_client.py: MCP(2025-06) stdioクライアントの結合テスト。

tests/mocks/notion_mcp を相手にinitialize/tools/list/tools/callの往復を検証し、
異常系(タイムアウト・非0終了・不正JSON・JSON-RPC error)を明示的な例外で
捕捉できることを確認する。実Notionへの接続は行わない。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from orgh.mcp_client import (McpClient, McpProcessError, McpProtocolError,
                              McpRpcError, McpTimeoutError)

REPO = Path(__file__).resolve().parent.parent
MOCK_NOTION = str(REPO / "tests" / "mocks" / "notion_mcp")


class TestRoundTrip:
    def test_initialize_tools_list_tools_call(self):
        with McpClient([MOCK_NOTION]) as client:
            init_result = client.initialize()
            assert init_result["protocolVersion"] == "2025-06-18"

            tools = client.list_tools()
            names = {t["name"] for t in tools}
            assert "API-post-database-query" in names
            assert "API-get-block-children" in names

            result = client.call_tool(
                "API-post-database-query", {"database_id": "db-mock-1"})
            pages = result["structuredContent"]["results"]
            assert {p["id"] for p in pages} == {"page-001", "page-002"}

    def test_call_tool_content(self):
        with McpClient([MOCK_NOTION]) as client:
            client.initialize()
            result = client.call_tool(
                "API-get-block-children", {"block_id": "page-001"})
            blocks = result["structuredContent"]["results"]
            assert len(blocks) == 2

    def test_unknown_tool_raises_rpc_error(self):
        with McpClient([MOCK_NOTION]) as client:
            client.initialize()
            with pytest.raises(McpRpcError):
                client.call_tool("no-such-tool", {})

    def test_mock_reports_failure_tool_as_rpc_error(self, monkeypatch):
        monkeypatch.setenv("MOCK_NOTION_FAIL_TOOL", "API-post-database-query")
        with McpClient([MOCK_NOTION]) as client:
            client.initialize()
            with pytest.raises(McpRpcError) as exc:
                client.call_tool("API-post-database-query", {"database_id": "x"})
            assert exc.value.code == -32000


class TestErrorHandling:
    def test_empty_command_raises_valueerror(self):
        with pytest.raises(ValueError):
            McpClient([])

    def test_nonexistent_binary_raises_process_error(self):
        with pytest.raises(McpProcessError):
            with McpClient(["/no/such/binary/orgh-mcp-test"]):
                pass

    def test_nonzero_exit_before_response_raises_process_error(self):
        # プロセスは起動するが、応答を返さず非0終了する
        script = "import sys; sys.exit(3)"
        with McpClient([sys.executable, "-c", script]) as client:
            with pytest.raises(McpProcessError):
                client.initialize()

    def test_malformed_json_raises_protocol_error(self):
        script = (
            "import sys\n"
            "for line in sys.stdin:\n"
            "    sys.stdout.write('not json at all\\n')\n"
            "    sys.stdout.flush()\n"
        )
        with McpClient([sys.executable, "-c", script]) as client:
            with pytest.raises(McpProtocolError):
                client.initialize()

    def test_no_response_times_out(self):
        script = (
            "import sys, time\n"
            "for line in sys.stdin:\n"
            "    time.sleep(60)\n"
        )
        with McpClient([sys.executable, "-c", script], timeout=0.3) as client:
            with pytest.raises(McpTimeoutError):
                client.initialize()

    def test_missing_token_env_makes_mock_exit_nonzero(self, monkeypatch):
        """トークン環境変数未設定シナリオでモックサーバ自体が非0終了すること
        (orgh側の未設定検知は tests/test_notion_pull.py で確認する。ここでは
        mcp_clientが非0終了を明示的な例外として捕捉できることのみ確認)。"""
        monkeypatch.setenv("MOCK_NOTION_TOKEN_ENV", "ORGH_TEST_NOTION_TOKEN")
        monkeypatch.delenv("ORGH_TEST_NOTION_TOKEN", raising=False)
        with McpClient([MOCK_NOTION]) as client:
            with pytest.raises(McpProcessError):
                client.initialize()

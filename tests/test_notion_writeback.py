"""`orgh notion writeback` (orgh/notion.py の writeback()) の結合テスト。

tests/mocks/notion_mcp をMCPサーバに見立て、(a) done ミッションのサマリが
tools/call(ページ作成相当)としてintent・コスト・ブランチ名込みで要求される
こと、(b) MCP側の失敗(JSON-RPC error / プロセス異常終了)がミッション状態
(ledger/state)を一切変化させないこと(best-effort)、(c) done でないミッション
は実行前に明示エラーで拒否されること、を検証する。実Notionへの接続は行わない。
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from orgh.notion import (NotionWritebackStateError, writeback)
from orgh.state import Budget, Mission, RunStore, Task

REPO = Path(__file__).resolve().parent.parent
MOCK_NOTION = str(REPO / "tests" / "mocks" / "notion_mcp")

TOKEN_ENV = "ORGH_TEST_NOTION_TOKEN"
MISSION_ID = "wbtest01"


@pytest.fixture
def cfg(tmp_path) -> dict:
    return {
        "workers": {"enabled": []},
        "runs_dir": str(tmp_path / "runs"),
        "notion": {
            "mcp_command": [MOCK_NOTION],
            "database_id": "db-mock-1",
            "token_env": TOKEN_ENV,
        },
    }


def _make_mission(*, done: bool, cost_usd: float = 1.2345,
                   branches: list[str] | None = None) -> Mission:
    branches = branches if branches is not None else [
        f"orgh/{MISSION_ID}/t1", f"orgh/{MISSION_ID}/t2"]
    tasks = [
        Task(id="t1", title="最初のタスク", prompt="p1", worker="claude_code",
             status="done", branch=branches[0] if len(branches) > 0 else None,
             cost_usd=cost_usd / 2),
        Task(id="t2", title="2番目のタスク", prompt="p2", worker="claude_code",
             status="done" if done else "pending",
             branch=branches[1] if len(branches) > 1 else None,
             cost_usd=cost_usd / 2),
    ]
    return Mission(id=MISSION_ID, intent="Notion writeback結合テスト用ミッション",
                   context_digest="", tasks=tasks,
                   budget=Budget(spent_usd=cost_usd))


def _store(cfg: dict) -> RunStore:
    return RunStore(cfg["runs_dir"], MISSION_ID)


class TestWritebackRequestsCreatePage:
    def test_requests_tools_call_with_summary_fields(self, cfg, tmp_path, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "dummy-token-value")
        calls_file = tmp_path / "calls.jsonl"
        monkeypatch.setenv("MOCK_NOTION_CALLS_FILE", str(calls_file))

        store = _store(cfg)
        mission = _make_mission(done=True, cost_usd=1.2345)
        store.save(mission)

        result = writeback(cfg, MISSION_ID)
        assert result == {"ok": True, "error": None}

        calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
        create_calls = [c for c in calls if c["name"] == "API-post-page"]
        assert len(create_calls) == 1
        arguments_text = json.dumps(create_calls[0]["arguments"], ensure_ascii=False)
        assert mission.intent in arguments_text
        assert "1.2345" in arguments_text
        assert f"orgh/{MISSION_ID}/t1" in arguments_text
        assert f"orgh/{MISSION_ID}/t2" in arguments_text


class TestWritebackBestEffort:
    def test_json_rpc_error_leaves_mission_state_unchanged(self, cfg, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "dummy-token-value")
        monkeypatch.setenv("MOCK_NOTION_FAIL_TOOL", "API-post-page")

        store = _store(cfg)
        mission = _make_mission(done=True)
        store.save(mission)
        before = asdict(store.load(reset_inflight=False))

        result = writeback(cfg, MISSION_ID)
        assert result["ok"] is False
        assert result["error"]

        after = asdict(store.load(reset_inflight=False))
        assert before == after

    def test_server_process_crash_leaves_mission_state_unchanged(self, cfg, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "dummy-token-value")
        crashing_script = (
            "import json, sys\n"
            "for line in sys.stdin:\n"
            "    req = json.loads(line)\n"
            "    rid, m = req.get('id'), req.get('method')\n"
            "    if m == 'initialize':\n"
            "        out = {'jsonrpc': '2.0', 'id': rid,\n"
            "               'result': {'protocolVersion': '2025-06-18'}}\n"
            "        sys.stdout.write(json.dumps(out) + '\\n')\n"
            "        sys.stdout.flush()\n"
            "    elif m == 'notifications/initialized':\n"
            "        sys.exit(1)\n"  # initialize直後にクラッシュ
            "\n"
        )
        cfg["notion"]["mcp_command"] = [sys.executable, "-c", crashing_script]

        store = _store(cfg)
        mission = _make_mission(done=True)
        store.save(mission)
        before = asdict(store.load(reset_inflight=False))

        result = writeback(cfg, MISSION_ID)
        assert result["ok"] is False
        assert result["error"]

        after = asdict(store.load(reset_inflight=False))
        assert before == after


class TestWritebackRequiresDoneMission:
    def test_non_done_mission_is_rejected_before_mcp_call(self, cfg, tmp_path, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "dummy-token-value")
        calls_file = tmp_path / "calls.jsonl"
        monkeypatch.setenv("MOCK_NOTION_CALLS_FILE", str(calls_file))

        store = _store(cfg)
        mission = _make_mission(done=False)
        store.save(mission)

        with pytest.raises(NotionWritebackStateError):
            writeback(cfg, MISSION_ID)

        # MCPサーバへ一切接続していない(呼び出しファイルが作られてもいない)
        assert not calls_file.exists()

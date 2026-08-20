"""2025-09 API世代(database→data source改名)のNotion MCPサーバとの互換テスト。

実運用(2026-08-21、公式 notion-mcp-server 最新版)で「提供ツールが
API-query-data-source に改名されており旧候補が解決できない」事象を確認した
(QA-016: 実運用相当の構成でテストする)。モックの MOCK_NOTION_ERA=datasource で
その世代を再現する。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orgh.notion import pull, writeback
from orgh.state import Budget, Mission, RunStore, Task

REPO = Path(__file__).resolve().parent.parent
MOCK_NOTION = str(REPO / "tests" / "mocks" / "notion_mcp")
TOKEN_ENV = "ORGH_TEST_NOTION_TOKEN"
MISSION_ID = "dsera001"


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
        "vault": {"path": str(vault), "inbox": "inbox",
                  "mission_tag": "mission", "trigger_tag": "go"},
        "notion": {
            "mcp_command": [MOCK_NOTION],
            "database_id": "db-mock-1",
            "token_env": TOKEN_ENV,
        },
    }


def test_pull_resolves_data_source_id(cfg, vault, monkeypatch):
    """data-source世代: retrieve-a-databaseでidを解決し、data_source_idで照会する。"""
    monkeypatch.setenv(TOKEN_ENV, "dummy")
    monkeypatch.setenv("MOCK_NOTION_ERA", "datasource")
    written = pull(cfg)
    assert len(written) == 2  # 組み込みデータセットの2ページが取り込める
    for p in written:
        assert p.exists()


def test_writeback_uses_data_source_parent(cfg, tmp_path, monkeypatch):
    """data-source世代: ページ作成のparentが data_source_id 形式になる。"""
    monkeypatch.setenv(TOKEN_ENV, "dummy")
    monkeypatch.setenv("MOCK_NOTION_ERA", "datasource")
    calls_file = tmp_path / "calls.jsonl"
    monkeypatch.setenv("MOCK_NOTION_CALLS_FILE", str(calls_file))

    store = RunStore(cfg["runs_dir"], MISSION_ID)
    mission = Mission(id=MISSION_ID, intent="dsera試験", context_digest="",
                      tasks=[Task(id="t1", title="t", prompt="p",
                                  worker="claude_code", status="done")],
                      budget=Budget())
    store.save(mission)

    result = writeback(cfg, MISSION_ID)
    assert result["ok"] is True

    calls = [json.loads(l) for l in calls_file.read_text().splitlines()]
    create = [c for c in calls if c["name"] == "API-post-page"]
    assert len(create) == 1
    parent = create[0]["arguments"]["parent"]
    assert parent == {"type": "data_source_id", "data_source_id": "ds-db-mock-1"}

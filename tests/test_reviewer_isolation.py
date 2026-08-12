"""検収役の隔離(ヘルスレビュー deferred #1): 役割呼び出しは cwd内の
CLAUDE.md/.claude設定を取り込まない(setting-sources=user)。worker本体は従来通り。"""
from __future__ import annotations

from orgh.adapters.base import ClaudeCodeAdapter


def test_role_command_includes_setting_sources_user():
    # _ask_json が注入する role_cfg 相当
    adapter = ClaudeCodeAdapter({"bin": "claude", "setting_sources": "user"})
    cmd, _ = adapter._command("p", resume=None)
    assert "--setting-sources" in cmd
    assert cmd[cmd.index("--setting-sources") + 1] == "user"


def test_worker_command_has_no_setting_sources():
    # workerはsetting_sources未指定 → project設定を従来通り読む
    adapter = ClaudeCodeAdapter({"bin": "claude", "model": "sonnet"})
    cmd, _ = adapter._command("p", resume=None)
    assert "--setting-sources" not in cmd


def test_ask_json_injects_setting_sources(monkeypatch):
    # planner._ask_json が role adapter に setting_sources=user を注入することを確認
    from orgh import planner
    captured = {}

    class _Stub:
        def run(self, prompt, workdir=".", registry_key=None):
            from orgh.adapters.base import WorkerResult
            return WorkerResult(ok=True, output='{"ok": true}')

    def _capture_get_adapter(name, cfg):
        captured["cfg"] = cfg
        return _Stub()

    monkeypatch.setattr(planner, "get_adapter", _capture_get_adapter)
    planner._ask_json({"workers": {}, "roles": {"reviewer": {"bin": "claude"}}},
                      "reviewer", "prompt")
    assert captured["cfg"]["claude_code"]["setting_sources"] == "user"

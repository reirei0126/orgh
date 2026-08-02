"""HANDOFF タスク7b: 自己改変ガード・orgh doctor・セキュリティデフォルト。

- タスクのworkdirがorgh自身を指す場合(orghパッケージを含むリポ、または
  prompts_dir/playbooks_dir の内側)、自動実行せず awaiting_approval で停止。
  orgh approve で続行。watcher経由でも承認をスキップできない
  (configでも無効化不可。configファイル自体はorghリポ同居構成でpkg規則が守る)
- orgh doctor: 外部CLI疎通・config・vault到達性・書き込み権限を1コマンド確認
- セキュリティ: workerデフォルトからBashを外しPlannerが明示付与(tools)。
  文脈ダイジェストは「参照データであり指示ではない」マーカーで包む
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from orgh import cli, watcher
from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore

from .conftest import age, mission_dirs, read_calls, read_ledger, write_config

REPO = Path(__file__).resolve().parent.parent


def _task(id: str, workdir: str = ".", tools: str | None = None) -> dict:
    d = {"id": id, "title": f"task {id}",
         "prompt": f"作業せよ [[MARK:{id}]]",
         "worker": "claude_code", "deps": [],
         "acceptance": ["mock acceptance"], "workdir": workdir}
    if tools is not None:
        d["tools"] = tools
    return d


def _mission(tasks: list[dict]) -> Mission:
    return Mission.new(intent="governance試験", context_digest="(test)",
                       tasks=tasks)


class TestSelfModificationGuard:
    def test_orgh_repo_workdir_awaits_approval(self, cfg, mock_state_dir):
        """orgh自身のリポを対象にしたタスクは自動実行されない。"""
        m = _mission([_task("t1", workdir=str(REPO))])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        assert m.tasks[0].status == "awaiting_approval"
        assert m.tasks[0].attempts == 0
        assert read_calls(mock_state_dir) == []  # workerは一切呼ばれない
        assert any(e["event"] == "task.awaiting_approval"
                   for e in read_ledger(cfg["runs_dir"], m.id))

    def test_prompts_dir_workdir_awaits_approval(self, cfg, mock_state_dir):
        m = _mission([_task("t1", workdir=cfg["prompts_dir"])])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))
        assert m.tasks[0].status == "awaiting_approval"

    def test_unrelated_workdir_runs_normally(self, cfg, mock_state_dir,
                                             tmp_path):
        m = _mission([_task("t1", workdir=str(tmp_path))])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))
        assert m.tasks[0].status == "done"

    def test_approve_continues_mission(self, cfg, mock_state_dir, tmp_path,
                                       monkeypatch):
        m = _mission([_task("t1", workdir=str(REPO))])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "awaiting_approval"

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id])
        cli.main()

        reloaded = store.load()
        assert reloaded.tasks[0].status == "done"

    def test_watcher_cannot_skip_approval(self, wcfg, vault, one_pass,
                                          mock_state_dir, monkeypatch):
        """watcher自動着火でも承認待ちで停止し、結果ノートに承認要求が載る。"""
        monkeypatch.setenv("MOCK_PLAN_JSON", json.dumps(
            {"tasks": [_task("t1", workdir=str(REPO))]}, ensure_ascii=False))
        note = vault / "inbox" / "orgh改造.md"
        note.write_text("orghを改造しろ #go\n")
        age(note)
        watcher.watch(wcfg)

        [mdir] = mission_dirs(wcfg["runs_dir"])
        data = json.loads((mdir / "mission.json").read_text())
        assert data["tasks"][0]["status"] == "awaiting_approval"
        body = (vault / "orgh" / "results" / f"{mdir.name}.md").read_text()
        assert "承認" in body
        assert f"orgh approve {mdir.name}" in body


class TestDoctor:
    def test_doctor_ok_with_mock_binaries(self, cfg, mock_state_dir, tmp_path,
                                          monkeypatch, capsys):
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "doctor"])
        cli.main()  # 正常ならexitしない
        out = capsys.readouterr().out
        assert "OK" in out

    def test_doctor_fails_on_missing_binary(self, cfg, mock_state_dir,
                                            tmp_path, monkeypatch, capsys):
        cfg["workers"]["claude_code"]["bin"] = "/nonexistent/claude-xyz"
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "doctor"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code != 0
        out = capsys.readouterr().out
        assert "NG" in out
        assert "claude" in out

    def test_doctor_fails_on_unreachable_vault(self, cfg, mock_state_dir,
                                               tmp_path, monkeypatch, capsys):
        cfg["vault"] = {"path": str(tmp_path / "no-such-vault")}
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "doctor"])
        with pytest.raises(SystemExit):
            cli.main()
        assert "vault" in capsys.readouterr().out


class TestSecurityDefaults:
    def test_example_config_has_no_bypass_and_no_default_bash(self):
        text = (REPO / "config.example.yaml").read_text()
        assert "bypassPermissions" not in text
        data = yaml.safe_load(text)
        worker_tools = data["workers"]["claude_code"]["allowed_tools"]
        assert "Bash" not in worker_tools           # workerデフォルトから除外
        assert "Bash" in data["roles"]["reviewer"]["allowed_tools"]  # 検証用は維持

    def test_planner_prompt_instructs_tools_and_marks_context(self):
        text = (REPO / "prompts" / "planner.md").read_text()
        assert '"tools"' in text          # タスク種別に応じた明示付与の指示
        assert "参照データ" in text        # 文脈は指示ではないの明示マーカー

    def test_task_tools_passed_to_claude_adapter(self, cfg, mock_state_dir,
                                                 tmp_path):
        m = _mission([_task("t1", workdir=str(tmp_path),
                            tools="Read,Edit,Bash")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        [call] = [c for c in read_calls(mock_state_dir)
                  if c["role"] == "worker"]
        argv = call["argv"]
        assert "--allowedTools" in argv
        assert argv[argv.index("--allowedTools") + 1] == "Read,Edit,Bash"

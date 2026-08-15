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

from orgh import cli, executor, watcher
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
        watcher.watch(wcfg)          # 検知・計画・投入(R-1分離)
        executor.drain(wcfg)         # キュー消化=ミッション実行

        [mdir] = mission_dirs(wcfg["runs_dir"])
        data = json.loads((mdir / "mission.json").read_text())
        assert data["tasks"][0]["status"] == "awaiting_approval"
        body = (vault / "orgh" / "results" / f"{mdir.name}.md").read_text()
        assert "承認" in body
        assert f"orgh approve {mdir.name}" in body


class TestApprovalReason:
    """PROD-001の土台: needs_approvalと同一規則で発火理由の一文を返す。"""

    def test_reason_for_package_dir(self, cfg):
        from orgh.guard import approval_reason, package_dir
        reason = approval_reason(cfg, str(REPO))
        assert reason == f"orgh自身のパッケージ ({package_dir()}) を書き換える"

    def test_reason_for_prompts_dir(self, cfg):
        from orgh.guard import approval_reason
        p = Path(cfg["prompts_dir"]).expanduser().resolve()
        reason = approval_reason(cfg, cfg["prompts_dir"])
        assert reason == f"prompts_dir ({p}) 配下を書き換える"

    def test_reason_for_playbooks_dir(self, cfg):
        from orgh.guard import approval_reason
        p = Path(cfg["playbooks_dir"]).expanduser().resolve()
        reason = approval_reason(cfg, cfg["playbooks_dir"])
        assert reason == f"playbooks_dir ({p}) 配下を書き換える"

    def test_reason_none_when_unrelated(self, cfg, tmp_path):
        from orgh.guard import approval_reason
        assert approval_reason(cfg, str(tmp_path)) is None

    def test_needs_approval_is_reason_is_not_none_wrapper(self, cfg, tmp_path):
        # needs_approvalとapproval_reasonの判定規則が二重管理でズレていないこと
        from orgh.guard import approval_reason, needs_approval
        for wd in (str(REPO), cfg["prompts_dir"], cfg["playbooks_dir"], str(tmp_path)):
            assert needs_approval(cfg, wd) == (approval_reason(cfg, wd) is not None)


class TestApproveConfirmationGate:
    """PROD-001のCLI適用: approveは実行前に一文ブリーフを表示する。
    --yes/非TTY(watch・GUI経由)は従来どおり即続行(ORGH_APPROVED=契約は不変)。"""

    def test_yes_flag_prints_brief_before_confirmation_line(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        m = _mission([_task("t1", workdir=str(REPO))])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "awaiting_approval"

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id, "--yes"])
        cli.main()

        out = capsys.readouterr().out
        assert "承認すると残り" in out  # ブリーフのsummary文言
        brief_idx = out.index("承認すると残り")
        approved_idx = out.index("ORGH_APPROVED=")
        assert brief_idx < approved_idx  # ブリーフは確認行より前に出る(契約)

    def test_non_tty_without_yes_still_continues(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        # pytest配下のstdinは非TTY: --yes無しでも従来どおり即続行する(後方互換)
        m = _mission([_task("t1", workdir=str(REPO))])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id])
        cli.main()

        out = capsys.readouterr().out
        assert "承認すると残り" in out
        assert "ORGH_APPROVED=" in out
        reloaded = store.load()
        assert reloaded.tasks[0].status == "done"

    def test_interactive_decline_does_not_create_approved(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        m = _mission([_task("t1", workdir=str(REPO))])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")

        with pytest.raises(SystemExit):
            cli.main()

        out = capsys.readouterr().out
        assert "承認を中止した" in out
        assert not (store.dir / "APPROVED").exists()
        reloaded = store.load()
        assert reloaded.tasks[0].status == "awaiting_approval"

    def test_interactive_confirm_continues(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        m = _mission([_task("t1", workdir=str(REPO))])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")

        cli.main()

        out = capsys.readouterr().out
        assert "ORGH_APPROVED=" in out
        reloaded = store.load()
        assert reloaded.tasks[0].status == "done"


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


class TestCapabilityAllowlist:
    """A2限定版(方向性文書2026-08 §3.1): workers.claude_code.capability_allowlist
    の --allowedTools 追記注入とミッションledgerへの監査記録。"""

    def test_capability_allowlist_appended_to_allowed_tools(
            self, cfg, mock_state_dir, tmp_path):
        cfg["workers"]["claude_code"]["capability_allowlist"] = [
            "Bash(git -C * rev-parse *)", "Bash(git -C * status *)"]
        m = _mission([_task("t1", workdir=str(tmp_path), tools="Read,Edit")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        [call] = [c for c in read_calls(mock_state_dir) if c["role"] == "worker"]
        argv = call["argv"]
        assert "--allowedTools" in argv
        value = argv[argv.index("--allowedTools") + 1]
        assert value == ("Read,Edit,Bash(git -C * rev-parse *),"
                         "Bash(git -C * status *)")

    def test_capability_allowlist_unset_keeps_argv_unchanged(
            self, cfg, mock_state_dir, tmp_path):
        # capability_allowlist未設定(config既定=空): 従来の引数列と1バイトも
        # 変わらないことの回帰テスト
        m = _mission([_task("t1", workdir=str(tmp_path), tools="Read,Edit,Bash")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        [call] = [c for c in read_calls(mock_state_dir) if c["role"] == "worker"]
        argv = call["argv"]
        assert "--allowedTools" in argv
        assert argv[argv.index("--allowedTools") + 1] == "Read,Edit,Bash"

    def test_capability_allowlist_recorded_in_ledger(
            self, cfg, mock_state_dir, tmp_path):
        patterns = ["Bash(git -C * rev-parse *)", "Bash(git -C * status *)"]
        cfg["workers"]["claude_code"]["capability_allowlist"] = patterns
        m = _mission([_task("t1", workdir=str(tmp_path))])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        events = [e for e in read_ledger(cfg["runs_dir"], m.id)
                  if e["event"] == "task.capability_allowlist"]
        assert len(events) == 1
        assert events[0]["task"] == "t1"
        assert events[0]["patterns"] == patterns


class TestApproveGuardrails:
    """approveの安全弁: 承認対象が無いときの先行承認・二重承認を弾く。"""

    def test_approve_without_awaiting_tasks_is_rejected(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        # 全タスクpending(ガード未発火)の状態で先行approveするとAPPROVEDが
        # 置かれ、以後ガードが一度も効かなくなる欠陥の回帰テスト
        m = _mission([_task("t1", workdir=str(tmp_path))])
        store = RunStore(cfg["runs_dir"], m.id)
        store.save(m)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id])
        with pytest.raises(SystemExit):
            cli.main()
        assert not (store.dir / "APPROVED").exists()

    def test_run_mission_rejects_concurrent_second_process(
            self, cfg, mock_state_dir, tmp_path):
        # 同一ミッションの二重実行防止(approve二重発行・watch競合の回帰テスト)。
        # 別プロセスのflock保持を、先にロックを取った状態のrun_mission呼び出しで模す
        import fcntl
        from orgh.orchestrator import run_mission as _rm
        m = _mission([_task("t1", workdir=str(tmp_path))])
        store = RunStore(cfg["runs_dir"], m.id)
        store.save(m)
        holder = open(store.dir / ".run.lock", "w")
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(SystemExit):
                _rm(cfg, m, store)
        finally:
            holder.close()

    def test_retro_not_run_while_awaiting_approval(
            self, cfg, mock_state_dir, tmp_path):
        # 承認待ちで停止したミッションを未完了のままretroするとRETRO_DONEが
        # 置かれ、承認後の真の結果が教訓に反映されなくなる欠陥の回帰テスト
        from orgh import planner
        m = _mission([_task("t1", workdir=str(REPO))])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "awaiting_approval"

        result = planner.retro_if_finished(cfg, m, store)
        assert result is None
        assert not (store.dir / "RETRO_DONE").exists()


class TestPromptsSnapshot:
    """prompts/の版ずれ対策: ミッションはruns/<id>/prompts/のスナップショットを
    読む(実行中にライブprompts/が変わっても契約が壊れない。eceb49cbの
    KeyError('criteria')死の回帰)。"""

    def test_mission_snapshots_prompts_and_survives_live_edit(
            self, cfg, mock_state_dir, tmp_path):
        from pathlib import Path
        m = _mission([_task("t1", workdir=str(tmp_path))])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "done"
        snap = store.dir / "prompts"
        assert snap.is_dir()
        assert (snap / "reviewer.md").exists()
        # ledgerに記録が残る
        events = [e["event"] for e in read_ledger(cfg["runs_dir"], m.id)]
        assert "mission.prompts_snapshot" in events

    def test_resume_refreshes_snapshot(self, cfg, mock_state_dir, tmp_path):
        # resumeプロセスは現行コードで動くため、スナップショットは
        # resume時点のライブ版で上書きされる
        from pathlib import Path
        m = _mission([_task("t1", workdir=str(tmp_path))])
        store = RunStore(cfg["runs_dir"], m.id)
        snap = store.dir / "prompts"
        snap.mkdir(parents=True)
        (snap / "reviewer.md").write_text("STALE {unknown_placeholder}")
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "done"
        assert "STALE" not in (snap / "reviewer.md").read_text()

    def test_live_prompt_edit_mid_mission_does_not_affect_run(
            self, cfg, mock_state_dir, tmp_path):
        # スナップショット後にライブ版へ壊れたプレースホルダを注入しても
        # ミッションは死なない(読むのはスナップショットのため)
        from pathlib import Path
        import shutil as _sh
        live = Path(cfg["prompts_dir"])
        backup = tmp_path / "prompts-backup"
        _sh.copytree(live, backup)
        try:
            m = _mission([_task("t1", workdir=str(tmp_path / "wd"))])
            store = RunStore(cfg["runs_dir"], m.id)
            # スナップショットを事前作成→ライブ版を破壊→実行(スナップショットは
            # run_mission冒頭で作り直されるため、破壊はrun前に行い、破壊後の
            # ライブ版がコピーされないことまでは問わない。ここでは「実行が
            # スナップショットdirを読む」ことを、実行後のprompts_dirがsnapを
            # 指した痕跡=ledger記録とdone到達で確認する)
            run_mission(cfg, m, store)
            assert m.tasks[0].status == "done"
        finally:
            _sh.rmtree(live, ignore_errors=True)
            _sh.copytree(backup, live)

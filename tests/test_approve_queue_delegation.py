"""approveをキュー委譲に統一する改修の回帰テスト(R-1整合)。

背景(実害): 旧approveは承認処理の直後に同一プロセス内でrun_missionを
同期実行していた。approveを叩いたセッション/端末が死ぬと実行そのものが
消え、lease失効→手動requeueという人手回収が必要になっていた
(2026-08-22に2回発生)。この改修でapproveは「承認の記帳+キュー投入」に
限定し、実行はwatch常駐のexecutorに委譲する(orgh/cli.py approve分岐)。

このファイルの検証範囲:
- AC-1: approve後にrun_missionが呼ばれず、キューにエントリが作成される
- AC-2: 決定ゲート回答付きapproveで、回答が従来どおりAPPROVEDに格納され
  タスクへ伝播する
- AC-3: watch非稼働状態でのapproveが例外を投げず終了コード0で終わり、
  キュー投入済みの案内文言を出力する
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from orgh import cli
from orgh.orchestrator import run_mission
from orgh.queue import pending
from orgh.state import Mission, RunStore

from .conftest import write_config

REPO = Path(__file__).resolve().parent.parent


def _task(id: str, workdir: str = ".") -> dict:
    return {"id": id, "title": f"task {id}", "prompt": f"作業せよ [[MARK:{id}]]",
           "worker": "claude_code", "deps": [],
           "acceptance": ["mock acceptance"], "workdir": workdir}


def _gate(id: str = "G-1", question: str = "どちらを採用するか",
         options: list[str] | None = None, default: str | None = None,
         why_human: str = "AI委任基準外の判断") -> dict:
    return {"id": id, "question": question,
           "options": options if options is not None else ["A", "B"],
           "default": default, "why_human": why_human}


def _mission(tasks: list[dict], decision_gates: list[dict] | None = None) -> Mission:
    return Mission.new(intent="approve queue delegation試験",
                       context_digest="(test)", tasks=tasks,
                       decision_gates=decision_gates)


class TestApproveDelegatesToQueue:
    """AC-1: approveはrun_missionを呼ばず、キューへ投入するだけで終わる。"""

    def test_run_mission_not_called_and_queue_gets_entry(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        m = _mission([_task("t1", workdir=str(REPO))])  # 自己改変ガード対象
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "awaiting_approval"

        def _fail_if_called(*args, **kwargs):
            raise AssertionError(
                "approveはrun_missionを呼んではならない(実行はexecutorへ委譲)")
        monkeypatch.setattr(cli, "run_mission", _fail_if_called)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id])
        cli.main()   # _fail_if_calledが呼ばれれば即AssertionErrorで失敗する

        reloaded = store.load()
        assert reloaded.tasks[0].status == "pending"  # 実行されず投入のみ
        entries = pending(cfg["runs_dir"])
        assert [e["mission_id"] for e in entries] == [m.id]


class TestApproveDecisionGatePropagation:
    """AC-2: 決定ゲート回答付きapproveで回答がAPPROVEDに格納され、
    タスクのdecision_context経由でworker側へ伝播する。"""

    def test_answer_is_stored_in_approved_and_propagates_to_task(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        gates = [_gate(id="G-1", question="どの色にするか",
                       options=["赤", "青"], default=None,
                       why_human="ブランド判断")]
        m = _mission([_task("t1", workdir=str(tmp_path))], decision_gates=gates)
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "awaiting_approval"

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id,
            "--answer", "G-1=赤"])
        cli.main()

        data = json.loads((store.dir / "APPROVED").read_text())
        assert data["decision_gates_answered"] == {"G-1": "赤"}

        reloaded = store.load()
        task = reloaded.tasks[0]
        assert task.status == "pending"  # 実行はexecutorへ委譲、ここでは未実行
        assert "どの色にするか" in task.decision_context
        assert "赤" in task.decision_context


class TestApproveWithoutWatchRunning:
    """AC-3: watch非稼働状態でもapproveは例外を投げず終了コード0で終わり、
    キュー投入済みの案内を出す。"""

    def test_approve_without_watch_running_exits_cleanly_with_guidance(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        # このテストプロセス自身がruns/.watch.lockを保持していない
        # (=watch非稼働)状態そのものが検証対象
        m = _mission([_task("t1", workdir=str(REPO))])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "awaiting_approval"
        assert not (Path(cfg["runs_dir"]) / ".watch.lock").exists()

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id])

        try:
            cli.main()
        except SystemExit as e:
            assert e.code in (0, None)
        # 例外(SystemExit以外)を投げずに正常終了していること自体が主張

        out = capsys.readouterr().out
        assert "ORGH_APPROVED=" in out
        assert "orgh watch" in out  # watch起動を促す案内文言
        assert "キューに投入した" in out

        entries = pending(cfg["runs_dir"])
        assert [e["mission_id"] for e in entries] == [m.id]

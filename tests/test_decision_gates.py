"""決定ゲート表(mission.decision_gates)の承認ブリーフ集約とworkerへの回答伝播。

- decision_gatesが非空のミッションはAPPROVEDが無い限りawaiting_approvalで停止する
  (自己改変ガードと同じAPPROVEDファイルで解除されるが、理由は別物)
- status_payloadのapproval_briefにゲート表(question/options/default/why_human)を出す
- orgh approve --answer <gate_id>=<value> で回答を確定し、未回答は default で埋める。
  default が無い(None)ゲートが未回答のまま承認されようとしたら中止する
- 確定した回答は task.decision_context 経由で worker_prompt に注入される
- decision_gates が空のミッションでは判定・出力・ledger・遷移が完全に無変更
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from orgh import cli, planner
from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore, build_task
from orgh.status_json import status_payload

from .conftest import read_calls, read_ledger, write_config

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
    return Mission.new(intent="decision_gates試験", context_digest="(test)",
                       tasks=tasks, decision_gates=decision_gates)


class TestSchedulerGate:
    def test_non_empty_decision_gates_awaits_approval_without_approved(
            self, cfg, mock_state_dir, tmp_path):
        m = _mission([_task("t1", workdir=str(tmp_path))],
                     decision_gates=[_gate()])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        assert m.tasks[0].status == "awaiting_approval"
        assert m.tasks[0].attempts == 0
        assert read_calls(mock_state_dir) == []  # workerは一切呼ばれない
        assert not (store.dir / "APPROVED").exists()

    def test_empty_decision_gates_does_not_gate_unrelated_workdir(
            self, cfg, mock_state_dir, tmp_path):
        m = _mission([_task("t1", workdir=str(tmp_path))], decision_gates=None)
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))
        assert m.tasks[0].status == "done"

    def test_self_mod_only_ledger_event_unchanged_when_gates_empty(
            self, cfg, mock_state_dir):
        # 自己改変ガード単独発火時、decision_gatesが空ならledgerに"reason"キーが
        # 増えない(既存ledger形状の無変更保証)
        m = _mission([_task("t1", workdir=str(REPO))], decision_gates=None)
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "awaiting_approval"

        events = [e for e in read_ledger(cfg["runs_dir"], m.id)
                  if e["event"] == "task.awaiting_approval"]
        assert len(events) == 1
        assert "reason" not in events[0]

    def test_gates_only_reason_is_distinct_from_self_mod(
            self, cfg, mock_state_dir, tmp_path):
        # 自己改変を伴わない(通常workdirの)タスクがdecision_gatesだけで停止した
        # 場合、ledgerのreasonが自己改変ガードの文言と混同されない
        m = _mission([_task("t1", workdir=str(tmp_path))],
                     decision_gates=[_gate()])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        events = [e for e in read_ledger(cfg["runs_dir"], m.id)
                  if e["event"] == "task.awaiting_approval"]
        assert len(events) == 1
        assert events[0].get("reason") == "decision_gates"


class TestApprovalBriefDecisionGates:
    def test_absent_when_decision_gates_empty(self, cfg):
        t1 = build_task(_task("t1", workdir=cfg["prompts_dir"]))
        t1.status = "awaiting_approval"
        m = Mission(id="mabc", intent="x", context_digest="(t)", tasks=[t1])
        brief = status_payload(m, cfg)["approval_brief"]
        assert "decision_gates" not in brief

    def test_all_gate_fields_present_when_awaiting(self, cfg, tmp_path):
        gates = [_gate(id="G-1", question="どの色にするか",
                       options=["赤", "青"], default="赤", why_human="ブランド判断"),
                 _gate(id="G-2", question="通知間隔は何分か",
                       options=[], default=None, why_human="運用コスト判断")]
        t1 = build_task(_task("t1", workdir=str(tmp_path)))
        t1.status = "awaiting_approval"
        m = Mission(id="mabc", intent="x", context_digest="(t)", tasks=[t1],
                   decision_gates=gates)
        brief = status_payload(m, cfg)["approval_brief"]
        assert brief["decision_gates"] == gates

    def test_absent_without_awaiting_task_even_if_gates_non_empty(self, cfg):
        # approval_brief自体の後方互換方針(承認待ちタスク無しならキー自体が無い)
        t1 = build_task(_task("t1"))  # status=pending既定
        m = Mission(id="mabc", intent="x", context_digest="(t)", tasks=[t1],
                   decision_gates=[_gate()])
        assert "approval_brief" not in status_payload(m, cfg)


class TestApproveAnswerFlow:
    def test_answers_and_defaults_reach_worker_prompt(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        gates = [
            _gate(id="G-1", question="どの色にするか", options=["赤", "青"],
                 default=None, why_human="ブランド判断"),
            _gate(id="G-2", question="通知間隔は何分か", options=["5", "10"],
                 default="10", why_human="運用コスト判断"),
        ]
        m = _mission([_task("t1", workdir=str(tmp_path))], decision_gates=gates)
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "awaiting_approval"

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id,
            "--answer", "G-1=赤"])
        cli.main()

        reloaded = store.load()
        task = reloaded.tasks[0]
        assert task.status == "done"
        prompt = planner.worker_prompt(cfg, task)
        assert "オーナーが確定済みの決定事項" in prompt
        assert "どの色にするか" in prompt and "赤" in prompt   # --answerで確定した値
        assert "通知間隔は何分か" in prompt and "10" in prompt  # 未回答→default採用
        assert "人間へ確認を返してはならない" in prompt

        events = [e for e in read_ledger(cfg["runs_dir"], m.id)
                  if e["event"] == "mission.decision_gates_answered"]
        assert len(events) == 1
        assert events[0]["count"] == 2

    def test_approved_file_contains_resolved_answers_as_json(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        gates = [_gate(id="G-1", default="既定値")]
        m = _mission([_task("t1", workdir=str(tmp_path))], decision_gates=gates)
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id])
        cli.main()

        data = json.loads((store.dir / "APPROVED").read_text())
        assert data["decision_gates_answered"] == {"G-1": "既定値"}

    def test_unanswered_gate_without_default_blocks_approval(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        gates = [_gate(id="G-1", default=None)]
        m = _mission([_task("t1", workdir=str(tmp_path))], decision_gates=gates)
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "awaiting_approval"

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code not in (0, None)

        assert not (store.dir / "APPROVED").exists()
        reloaded = store.load()
        assert reloaded.tasks[0].status == "awaiting_approval"

    def test_answer_with_missing_equals_sign_is_rejected(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        gates = [_gate(id="G-1", default="x")]
        m = _mission([_task("t1", workdir=str(tmp_path))], decision_gates=gates)
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id,
            "--answer", "G-1noeq"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code not in (0, None)
        assert not (store.dir / "APPROVED").exists()

    def test_answer_with_unknown_gate_id_is_rejected(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        gates = [_gate(id="G-1", default="x")]
        m = _mission([_task("t1", workdir=str(tmp_path))], decision_gates=gates)
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "approve", m.id,
            "--answer", "G-999=y"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code not in (0, None)
        assert not (store.dir / "APPROVED").exists()


class TestWorkerPromptNoOpWhenEmpty:
    def test_worker_prompt_unchanged_without_decision_context(self, cfg):
        base = build_task({"id": "t1", "title": "タイトル", "prompt": "指示",
                           "acceptance": ["AC1"]})
        assert base.decision_context == ""
        prompt = planner.worker_prompt(cfg, base)
        assert "オーナーが確定済みの決定事項" not in prompt

        other = build_task({"id": "t1", "title": "タイトル", "prompt": "指示",
                            "acceptance": ["AC1"]})
        assert planner.worker_prompt(cfg, other) == prompt

    def test_worker_prompt_appends_section_only_when_context_present(self, cfg):
        t = build_task({"id": "t1", "title": "タイトル", "prompt": "指示",
                       "acceptance": ["AC1"]})
        without = planner.worker_prompt(cfg, t)
        t.decision_context = "- 質問: Q → 確定値: V"
        with_ctx = planner.worker_prompt(cfg, t)
        assert with_ctx.startswith(without)
        assert with_ctx != without
        assert "確定値: V" in with_ctx

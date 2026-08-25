"""計画契約の拡張(model/model_reason)とplan lintでの機械強制、および実行系接続。

タスクごとにworkerモデル等級(haiku/sonnet/opus)をPlannerが選べるようにする。
判定はPythonのコードのみで行う(LLMには問い合わせない)。model未指定タスクの
挙動は完全不変(config既定のまま)。

TestModelRoutingExecution 以降は実行系(worker起動argv・差し戻し昇格・ledger記録)
の接続を検証する(orgh/adapters/base.py get_adapter・orgh/orchestrator/task_executor.py)。
"""
from __future__ import annotations

from pathlib import Path

from orgh import planner
from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore

from .conftest import read_calls, read_ledger

REPO = Path(__file__).resolve().parent.parent


def _mission(tasks: list[dict]) -> Mission:
    return Mission.new(intent="モデル振り分け試験", context_digest="(test)",
                       tasks=tasks)


def _task(id: str, model: str | None = None, worker: str = "claude_code") -> dict:
    task = {"id": id, "title": f"task {id}", "prompt": f"作業せよ [[MARK:{id}]]",
           "worker": worker, "deps": [], "acceptance": ["mock acceptance"],
           "workdir": "."}
    if model is not None:
        task["model"] = model
        task["model_reason"] = "テスト用の明示指定"
    return task


def _worker_calls(mock_state_dir, marker: str) -> list[dict]:
    return [c for c in read_calls(mock_state_dir)
           if c["role"] == "worker" and c["marker"] == marker]


def _plan_json(model: str | None = None, model_reason: str = "") -> dict:
    task = {"id": "t1", "title": "x", "prompt": "y",
           "worker": "claude_code", "deps": [], "acceptance": ["z"]}
    if model is not None:
        task["model"] = model
    if model_reason:
        task["model_reason"] = model_reason
    return {"tasks": [task]}


class TestLintPlanModelReasonRequired:
    def test_model_without_reason_is_a_violation(self):
        v = planner.lint_plan(_plan_json(model="haiku"))
        assert len(v) >= 1
        assert any("model_reason" in x for x in v)

    def test_model_with_reason_is_clean(self):
        assert planner.lint_plan(
            _plan_json(model="haiku", model_reason="定型的な機械編集")) == []

    def test_model_unspecified_is_clean(self):
        assert planner.lint_plan(_plan_json()) == []


class TestLintPlanModelAllowlist:
    def test_model_outside_allowlist_is_a_violation(self):
        v = planner.lint_plan(
            _plan_json(model="gpt-5", model_reason="理由あり"))
        assert len(v) >= 1

    def test_model_in_default_allowlist_is_clean(self):
        for m in ("haiku", "sonnet", "opus"):
            assert planner.lint_plan(
                _plan_json(model=m, model_reason="理由あり")) == []

    def test_custom_allowlist_overrides_default(self):
        v = planner.lint_plan(
            _plan_json(model="opus", model_reason="理由あり"),
            model_allowlist=["haiku", "sonnet"])
        assert len(v) >= 1

    def test_malformed_tasks_is_not_a_violation(self):
        assert planner.lint_plan({"tasks": "oops"}) == []

    def test_empty_tasks_is_not_a_violation(self):
        assert planner.lint_plan({"tasks": []}) == []


class TestPlannerPromptContract:
    def test_prompt_mentions_model_reason_and_note_override(self):
        text = (REPO / "prompts" / "planner.md").read_text()
        assert "model_reason" in text
        assert "worker: haiku" in text


class TestModelRoutingExecution:
    """AC-1/AC-4: worker起動argvへのmodel通しと、未指定タスクの完全不変。"""

    def test_explicit_model_reaches_worker_argv(self, cfg, mock_state_dir):
        m = _mission([_task("t1", model="haiku")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        assert m.tasks[0].status == "done"
        [call] = _worker_calls(mock_state_dir, "t1")
        argv = call["argv"]
        assert "--model" in argv
        assert argv[argv.index("--model") + 1] == "haiku"

    def test_unspecified_model_keeps_config_default_only(self, cfg,
                                                          mock_state_dir):
        # cfgフィクスチャのclaude_code既定は model: "sonnet"。タスク由来の
        # 追加/上書きが起きなければ --model は1回だけ・値はconfig既定のまま。
        m = _mission([_task("t2")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        assert m.tasks[0].status == "done"
        [call] = _worker_calls(mock_state_dir, "t2")
        argv = call["argv"]
        assert argv.count("--model") == 1
        assert argv[argv.index("--model") + 1] == "sonnet"

    def test_task_start_event_includes_model(self, cfg, mock_state_dir):
        m = _mission([_task("t3", model="haiku")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        starts = [e for e in read_ledger(cfg["runs_dir"], m.id)
                 if e["event"] == "task.start"]
        assert starts and starts[0]["model"] == "haiku"

    def test_task_start_event_model_is_none_when_unspecified(self, cfg,
                                                              mock_state_dir):
        m = _mission([_task("t4")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        starts = [e for e in read_ledger(cfg["runs_dir"], m.id)
                 if e["event"] == "task.start"]
        assert starts and starts[0]["model"] is None


class TestModelEscalationOnRejection:
    """AC-2/AC-3: 差し戻し後の1段昇格(haiku->sonnet)とopusの据え置き。"""

    def test_haiku_escalates_to_sonnet_after_rejection(self, cfg,
                                                        mock_state_dir,
                                                        monkeypatch):
        monkeypatch.setenv("MOCK_REJECT_ONCE", "t1")
        m = _mission([_task("t1", model="haiku")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        assert m.tasks[0].status == "done"
        assert m.tasks[0].attempts == 2
        calls = _worker_calls(mock_state_dir, "t1")
        assert len(calls) == 2
        argv1, argv2 = calls[0]["argv"], calls[1]["argv"]
        assert argv1[argv1.index("--model") + 1] == "haiku"
        assert argv2[argv2.index("--model") + 1] == "sonnet"

        events = [e for e in read_ledger(cfg["runs_dir"], m.id)
                 if e["event"] == "model.escalated"]
        assert len(events) == 1
        assert events[0]["task"] == "t1"
        assert events[0]["from_"] == "haiku"
        assert events[0]["to"] == "sonnet"

    def test_opus_stays_put_after_rejection(self, cfg, mock_state_dir,
                                            monkeypatch):
        monkeypatch.setenv("MOCK_REJECT_ONCE", "t1")
        m = _mission([_task("t1", model="opus")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        assert m.tasks[0].status == "done"
        calls = _worker_calls(mock_state_dir, "t1")
        assert len(calls) == 2
        for call in calls:
            argv = call["argv"]
            assert argv[argv.index("--model") + 1] == "opus"

        events = [e for e in read_ledger(cfg["runs_dir"], m.id)
                 if e["event"] == "model.escalated"]
        assert events == []

    def test_unspecified_model_never_escalates(self, cfg, mock_state_dir,
                                               monkeypatch):
        monkeypatch.setenv("MOCK_REJECT_ONCE", "t1")
        m = _mission([_task("t1")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        assert m.tasks[0].status == "done"
        calls = _worker_calls(mock_state_dir, "t1")
        assert len(calls) == 2
        for call in calls:
            argv = call["argv"]
            assert argv.count("--model") == 1
            assert argv[argv.index("--model") + 1] == "sonnet"

        events = [e for e in read_ledger(cfg["runs_dir"], m.id)
                 if e["event"] == "model.escalated"]
        assert events == []


class TestCodexModelIgnored:
    """model指定がcodexタスクに付いた場合はargvを変えずledgerへ1回だけ記録する。"""

    def test_codex_model_is_ignored_but_logged(self, cfg, mock_state_dir):
        m = _mission([_task("t1", model="haiku", worker="codex")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        assert m.tasks[0].status == "done"

        events = [e for e in read_ledger(cfg["runs_dir"], m.id)
                 if e["event"] == "task.model_ignored"]
        assert len(events) == 1
        assert events[0]["task"] == "t1"
        assert events[0]["worker"] == "codex"
        assert events[0]["model"] == "haiku"

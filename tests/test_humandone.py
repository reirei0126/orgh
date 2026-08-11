"""orgh humandone CLI: awaiting_human タスクの完了報告→通常のReviewer検収。

- --note の内容が task.last_output としてReviewerに渡される(通常のworker成果と
  同じ扱い)
- 合格: task.status は done になり、依頼一文(human_request)はクリアされる。
  ミッションは続行され、依存タスクがあれば実行される
- 不合格: task.status は awaiting_human に戻り、新しい依頼書artifactが
  Reviewerのfeedbackを反映して再生成される
- 対象外(awaiting_human以外・存在しないtask_id)はエラー終了し状態を変えない
"""
from __future__ import annotations

import sys

from orgh import cli
from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore

from .conftest import read_ledger, write_config


def _task(id: str, worker: str = "human", deps: list[str] | None = None,
         workdir: str = ".") -> dict:
    return {"id": id, "title": f"task {id}",
            "prompt": f"作業せよ [[MARK:{id}]]",
            "worker": worker, "deps": deps or [],
            "acceptance": ["mock acceptance"], "workdir": workdir}


def _mission(tasks: list[dict]) -> Mission:
    return Mission.new(intent="humandone試験", context_digest="(test)",
                       tasks=tasks)


def _run_humandone(cfg, tmp_path, monkeypatch, mission_id, task_id, note):
    cfg_path = write_config(tmp_path, cfg)
    monkeypatch.setattr(sys, "argv", [
        "orgh", "--config", str(cfg_path), "humandone", mission_id, task_id,
        "--note", note])
    cli.main()


class TestHumandoneValidation:
    def test_errors_when_task_not_found(self, cfg, mock_state_dir, tmp_path,
                                        monkeypatch):
        m = _mission([_task("t1")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "humandone", m.id, "nope",
            "--note", "やった"])
        try:
            cli.main()
            raise AssertionError("SystemExitが発生するはず")
        except SystemExit as e:
            assert e.code != 0

    def test_errors_when_task_not_awaiting_human(self, cfg, mock_state_dir,
                                                 tmp_path, monkeypatch):
        m = _mission([_task("t1", worker="claude_code")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert store.load(reset_inflight=False).tasks[0].status == "done"

        try:
            _run_humandone(cfg, tmp_path, monkeypatch, m.id, "t1", "やった")
            raise AssertionError("SystemExitが発生するはず")
        except SystemExit as e:
            assert e.code != 0
        reloaded = store.load(reset_inflight=False)
        assert reloaded.tasks[0].status == "done"  # 状態は変わらない


class TestHumandonePassingReview:
    def test_marks_task_done_and_clears_request(self, cfg, mock_state_dir,
                                                 tmp_path, monkeypatch):
        m = _mission([_task("t1", worker="human")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert store.load(reset_inflight=False).tasks[0].status == "awaiting_human"

        _run_humandone(cfg, tmp_path, monkeypatch, m.id, "t1", "現地で対応した")

        reloaded = store.load(reset_inflight=False)
        t1 = reloaded.tasks[0]
        assert t1.status == "done"
        assert t1.human_request == ""
        assert t1.last_output == "現地で対応した"
        events = read_ledger(cfg["runs_dir"], m.id)
        assert any(e["event"] == "task.human_report" and e["task"] == "t1"
                   for e in events)

    def test_downstream_task_runs_after_humandone(self, cfg, mock_state_dir,
                                                   tmp_path, monkeypatch):
        m = _mission([
            _task("t1", worker="human"),
            _task("t2", worker="claude_code", deps=["t1"]),
        ])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        loaded = store.load(reset_inflight=False)
        assert loaded.tasks[0].status == "awaiting_human"
        assert loaded.tasks[1].status == "pending"

        _run_humandone(cfg, tmp_path, monkeypatch, m.id, "t1", "現地で対応した")

        reloaded = store.load(reset_inflight=False)
        assert reloaded.tasks[0].status == "done"
        assert reloaded.tasks[1].status == "done"


class TestHumandoneFailingReview:
    def test_rejected_report_returns_to_awaiting_human(self, cfg,
                                                        mock_state_dir,
                                                        tmp_path, monkeypatch):
        m = _mission([_task("t1", worker="human")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        monkeypatch.setenv("MOCK_REVIEW_ALWAYS_FAIL", "t1")
        _run_humandone(cfg, tmp_path, monkeypatch, m.id, "t1", "不十分な報告")

        reloaded = store.load(reset_inflight=False)
        t1 = reloaded.tasks[0]
        assert t1.status == "awaiting_human"
        assert t1.human_request  # 新しい依頼一文が入っている
        fp = store.dir / "artifacts" / "human_request_t1.md"
        assert fp.exists()
        assert "モック差し戻し" in fp.read_text()

    def test_human_feedback_reason_becomes_new_request(self, cfg,
                                                        mock_state_dir,
                                                        tmp_path, monkeypatch):
        m = _mission([_task("t1", worker="human")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        monkeypatch.setenv("MOCK_REVIEW_HUMAN", "t1")
        _run_humandone(cfg, tmp_path, monkeypatch, m.id, "t1", "一部だけ対応した")

        reloaded = store.load(reset_inflight=False)
        t1 = reloaded.tasks[0]
        assert t1.status == "awaiting_human"
        assert not t1.human_request.startswith("HUMAN:")

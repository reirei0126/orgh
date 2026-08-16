"""notify.py: 人間接点イベント通知(A1out)。

- 3種のイベントが必須フィールドを全て持つこと
- 同一事象から2回イベントを生成すると event_id が同一になること
- webhook_url未設定時はPOSTが行われずnotify.emittedのみ記録されること
- webhook先が接続不能なとき、例外が漏れずnotify.failedが記録されること
"""
from __future__ import annotations

import socket
from pathlib import Path

from orgh import notify
from orgh.state import Mission, RunStore, Task

from .conftest import read_ledger

REQUIRED_FIELDS = {"event_type", "event_id", "schema_version", "mission_id",
                   "summary", "ts"}


def _task(id: str = "t1", workdir: str = ".") -> Task:
    return Task(id=id, title=f"task {id}", prompt="do it", workdir=workdir,
               acceptance=["ok"])


def _mission(tasks: list[Task]) -> Mission:
    m = Mission(id="m1", intent="試験ミッション", context_digest="(test)",
                tasks=tasks)
    return m


def _closed_port_url() -> str:
    """接続不能なURLを確実に得る: 一時的にlistenして即closeしたポート番号を使う。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/notify"


class TestEventShape:
    def test_approval_requested_has_required_fields(self, cfg):
        cfg = {**cfg, "prompts_dir": cfg["prompts_dir"]}
        t = _task("t1", workdir=cfg["prompts_dir"])
        event = notify.approval_requested_event(cfg, "m1", t)
        assert REQUIRED_FIELDS <= event.keys()
        assert event["event_type"] == "approval.requested"
        assert event["schema_version"] == "1"
        assert event["mission_id"] == "m1"
        assert event["task_id"] == "t1"
        assert event["summary"]

    def test_human_task_requested_has_required_fields(self):
        t = _task("t2")
        event = notify.human_task_requested_event("m1", t, "人間の判断が必要")
        assert REQUIRED_FIELDS <= event.keys()
        assert event["event_type"] == "human_task.requested"
        assert event["task_id"] == "t2"
        assert event["summary"]

    def test_mission_completed_has_required_fields(self):
        t = _task("t1")
        t.status = "done"
        m = _mission([t])
        event = notify.mission_completed_event(m)
        assert REQUIRED_FIELDS <= event.keys()
        assert event["event_type"] == "mission.completed"
        assert event["mission_id"] == "m1"
        assert event["summary"]
        # mission.completedにはtaskの概念が無い(該当時のみのフィールド)
        assert "task_id" not in event


class TestIdempotency:
    def test_same_approval_event_has_same_event_id(self, cfg):
        t = _task("t1", workdir=cfg["prompts_dir"])
        e1 = notify.approval_requested_event(cfg, "m1", t)
        e2 = notify.approval_requested_event(cfg, "m1", t)
        assert e1["event_id"] == e2["event_id"]

    def test_same_human_task_event_has_same_event_id(self):
        t = _task("t2")
        e1 = notify.human_task_requested_event("m1", t, "理由A")
        e2 = notify.human_task_requested_event("m1", t, "理由B")
        # event_idは識別キー(mission/task)から決定される。理由文言が変わっても
        # 同一事象(同一task)の再発行であればevent_idは同一のまま
        assert e1["event_id"] == e2["event_id"]

    def test_same_mission_completed_event_has_same_event_id(self):
        m = _mission([_task("t1")])
        e1 = notify.mission_completed_event(m)
        e2 = notify.mission_completed_event(m)
        assert e1["event_id"] == e2["event_id"]

    def test_different_tasks_have_different_event_ids(self):
        e1 = notify.human_task_requested_event("m1", _task("t1"), "r")
        e2 = notify.human_task_requested_event("m1", _task("t2"), "r")
        assert e1["event_id"] != e2["event_id"]


class TestEmit:
    def test_no_webhook_url_skips_post_and_logs_emitted_only(self, cfg, tmp_path):
        store = RunStore(cfg["runs_dir"], "m1")
        event = notify.human_task_requested_event("m1", _task("t1"), "理由")

        notify.emit(store, cfg, event)

        events = read_ledger(cfg["runs_dir"], "m1")
        kinds = [e["event"] for e in events]
        assert kinds == ["notify.emitted"]
        assert "notify.failed" not in kinds
        emitted = events[0]
        assert emitted["event_id"] == event["event_id"]
        assert emitted["event_type"] == "human_task.requested"

    def test_emit_with_no_cfg_notify_section_also_skips_post(self, cfg):
        assert "notify" not in cfg  # 既定挙動: notify未指定でも壊れない
        store = RunStore(cfg["runs_dir"], "m1")
        event = notify.human_task_requested_event("m1", _task("t1"), "理由")
        notify.emit(store, cfg, event)
        events = read_ledger(cfg["runs_dir"], "m1")
        assert [e["event"] for e in events] == ["notify.emitted"]

    def test_unreachable_webhook_does_not_raise_and_logs_failed(self, cfg):
        cfg = {**cfg, "notify": {"webhook_url": _closed_port_url(), "timeout": 2}}
        store = RunStore(cfg["runs_dir"], "m1")
        event = notify.human_task_requested_event("m1", _task("t1"), "理由")

        notify.emit(store, cfg, event)  # 例外が漏れないこと自体が検証点

        events = read_ledger(cfg["runs_dir"], "m1")
        kinds = [e["event"] for e in events]
        assert kinds == ["notify.emitted", "notify.failed"]
        failed = events[1]
        assert failed["event_id"] == event["event_id"]
        assert failed["event_type"] == "human_task.requested"
        assert failed["error"]

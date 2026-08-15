"""notify発火点の統合テスト(orchestrator/transitions・scheduler への差し込み)。

- 3種のイベント(human_task.requested / approval.requested / mission.completed)が
  ローカルHTTPサーバへJSONとしてPOSTされること
- 同ミッションの ledger.jsonl に notify.emitted が3件記録されること
- webhook先が接続不能でもミッションが完走し、notify.failed が記録されること
- 同一事象の再発行(resume等、同じ遷移を再度通す経路)で event_id が同一になること
"""
from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore, Task

from .conftest import read_ledger

REQUIRED_FIELDS = {"event_type", "event_id", "schema_version", "mission_id",
                   "summary", "ts"}
REPO = Path(__file__).resolve().parent.parent


def _human_task(id: str = "th") -> Task:
    return Task(id=id, title=f"human task {id}", prompt=f"作業せよ [[MARK:{id}]]",
               worker="human", deps=[], acceptance=["ok"], workdir=".")


def _approval_task(id: str = "ta") -> Task:
    # workdirがorghリポ自身を指す = 自己改変ガード発動 -> awaiting_approval
    return Task(id=id, title=f"approval task {id}",
               prompt=f"作業せよ [[MARK:{id}]]", worker="claude_code", deps=[],
               acceptance=["ok"], workdir=str(REPO))


def _mission(mission_id: str, tasks: list[Task]) -> Mission:
    return Mission(id=mission_id, intent="通知統合試験", context_digest="(test)",
                   tasks=tasks)


def _closed_port_url() -> str:
    """接続不能なURLを確実に得る: 一時的にlistenして即closeしたポート番号を使う。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/notify"


class _RecordingHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.received.append(json.loads(body))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # テスト出力を静かに保つ(標準エラーへのアクセスログを抑止)


@pytest.fixture
def webhook_server():
    server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    server.received = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _webhook_url(server: HTTPServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/notify"


class TestWebhookDelivery:
    def test_three_events_delivered_as_json(self, cfg, mock_state_dir,
                                             webhook_server):
        cfg = {**cfg, "notify": {"webhook_url": _webhook_url(webhook_server),
                                 "timeout": 5}}
        m = _mission("mwh1", [_human_task("th"), _approval_task("ta")])
        store = RunStore(cfg["runs_dir"], m.id)

        run_mission(cfg, m, store)

        assert m.tasks[0].status == "awaiting_human"
        assert m.tasks[1].status == "awaiting_approval"

        received = webhook_server.received
        event_types = {e["event_type"] for e in received}
        assert event_types == {"human_task.requested", "approval.requested",
                               "mission.completed"}
        assert len(received) == 3
        for event in received:
            assert REQUIRED_FIELDS <= event.keys()
            assert event["mission_id"] == m.id
            assert event["schema_version"] == "1"
            assert event["summary"]


class TestLedgerRecording:
    def test_three_notify_emitted_recorded_in_ledger(self, cfg, mock_state_dir,
                                                      webhook_server):
        cfg = {**cfg, "notify": {"webhook_url": _webhook_url(webhook_server),
                                 "timeout": 5}}
        m = _mission("mwh2", [_human_task("th"), _approval_task("ta")])
        store = RunStore(cfg["runs_dir"], m.id)

        run_mission(cfg, m, store)

        events = read_ledger(cfg["runs_dir"], m.id)
        emitted = [e for e in events if e["event"] == "notify.emitted"]
        assert len(emitted) == 3
        assert {e["event_type"] for e in emitted} == {
            "human_task.requested", "approval.requested", "mission.completed"}
        assert not [e for e in events if e["event"] == "notify.failed"]


class TestWebhookFailureResilience:
    def test_mission_completes_and_notify_failed_recorded(
            self, cfg, mock_state_dir):
        cfg = {**cfg, "notify": {"webhook_url": _closed_port_url(),
                                 "timeout": 2}}
        m = _mission("mwh3", [_human_task("th"), _approval_task("ta")])
        store = RunStore(cfg["runs_dir"], m.id)

        run_mission(cfg, m, store)  # 例外が漏れずミッションが完走すること自体が検証点

        assert m.tasks[0].status == "awaiting_human"
        assert m.tasks[1].status == "awaiting_approval"

        events = read_ledger(cfg["runs_dir"], m.id)
        emitted = [e for e in events if e["event"] == "notify.emitted"]
        failed = [e for e in events if e["event"] == "notify.failed"]
        assert len(emitted) == 3
        assert len(failed) == 3
        assert {e["event_type"] for e in failed} == {
            "human_task.requested", "approval.requested", "mission.completed"}
        for f in failed:
            assert f["error"]


class TestIdempotentReEmission:
    def test_mission_completed_event_id_stable_across_resume(
            self, cfg, mock_state_dir, webhook_server):
        """同一store/missionへ run_mission を2度通す(resumeの模倣)。2回目は
        既にawaiting_human/awaiting_approvalのタスクは再処理されないが、
        mission.finished(→mission.completed)は都度記録される経路のため、
        同一事象の再発行としてevent_idの安定性を検証できる。"""
        cfg = {**cfg, "notify": {"webhook_url": _webhook_url(webhook_server),
                                 "timeout": 5}}
        m = _mission("mwh4", [_human_task("th"), _approval_task("ta")])
        store = RunStore(cfg["runs_dir"], m.id)

        run_mission(cfg, m, store)
        run_mission(cfg, m, store)  # resume相当: 同じ遷移を再度通す

        events = read_ledger(cfg["runs_dir"], m.id)
        completed_ids = [e["event_id"] for e in events
                         if e["event"] == "notify.emitted"
                         and e["event_type"] == "mission.completed"]
        assert len(completed_ids) == 2
        assert completed_ids[0] == completed_ids[1]

    def test_human_task_and_approval_event_id_stable_across_independent_runs(
            self, cfg, mock_state_dir):
        """再計画等で同一mission_id/task_idの事象が独立に2回発行されても
        (=resumeでない別経路の再発行でも)event_idは同一になること。"""
        mission_id = "mwh5"
        store1 = RunStore(cfg["runs_dir"], mission_id)
        m1 = _mission(mission_id, [_human_task("th"), _approval_task("ta")])
        run_mission(cfg, m1, store1)

        cfg2 = {**cfg, "runs_dir": str(Path(cfg["runs_dir"]).parent / "runs2")}
        store2 = RunStore(cfg2["runs_dir"], mission_id)
        m2 = _mission(mission_id, [_human_task("th"), _approval_task("ta")])
        run_mission(cfg2, m2, store2)

        def _ids(runs_dir: str, event_type: str) -> list[str]:
            events = read_ledger(runs_dir, mission_id)
            return [e["event_id"] for e in events
                    if e["event"] == "notify.emitted"
                    and e["event_type"] == event_type]

        for event_type in ("human_task.requested", "approval.requested",
                           "mission.completed"):
            ids1 = _ids(cfg["runs_dir"], event_type)
            ids2 = _ids(cfg2["runs_dir"], event_type)
            assert len(ids1) == 1 and len(ids2) == 1
            assert ids1[0] == ids2[0]

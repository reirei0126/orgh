"""awaiting_human基盤: 人間依頼タスクの土台。

- worker: "human" のタスクはサブプロセスを起動せず awaiting_human で停止する
  (自己改変ガードは従来どおり先に効く。順序不変)
- awaiting_human タスクに依存するタスクは実行されない(_readyの既存挙動)
- 依頼書 human_request_<task_id>.md が runs/<mission>/artifacts/ に生成され、
  1行目が依頼一文になる
- Reviewerが "HUMAN:" feedbackを返すとタスクはfailedではなくawaiting_humanに
  転換し、attemptsは消費しない(REPLANと同型)
- worker: "human" を含むミッション実行がハングせず有限時間で戻る
"""
from __future__ import annotations

from pathlib import Path

from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore

from .conftest import read_calls, read_ledger

REPO = Path(__file__).resolve().parent.parent


def _task(id: str, worker: str = "claude_code", deps: list[str] | None = None,
         workdir: str = ".") -> dict:
    return {"id": id, "title": f"task {id}",
            "prompt": f"作業せよ [[MARK:{id}]]",
            "worker": worker, "deps": deps or [],
            "acceptance": ["mock acceptance"], "workdir": workdir}


def _mission(tasks: list[dict]) -> Mission:
    return Mission.new(intent="human試験", context_digest="(test)", tasks=tasks)


class TestHumanWorkerDispatch:
    def test_human_worker_task_stops_without_subprocess(self, cfg, mock_state_dir):
        m = _mission([_task("t1", worker="human")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        t = m.tasks[0]
        assert t.status == "awaiting_human"
        assert t.attempts == 0
        assert read_calls(mock_state_dir) == []  # workerは一切呼ばれない
        assert t.human_request                    # 依頼一文が保存されている
        events = read_ledger(cfg["runs_dir"], m.id)
        assert any(e["event"] == "task.awaiting_human" and e["task"] == "t1"
                   for e in events)

    def test_dependent_task_not_dispatched(self, cfg, mock_state_dir):
        m = _mission([
            _task("t1", worker="human"),
            _task("t2", deps=["t1"]),
        ])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        assert m.tasks[0].status == "awaiting_human"
        assert m.tasks[1].status == "pending"      # t1未完了なのでブロックされたまま
        assert read_calls(mock_state_dir) == []

    def test_mission_finishes_in_finite_time_with_human_task(
            self, cfg, mock_state_dir):
        """他タスクと並行して走っても、humanタスクの依存が無い限りミッションは
        正常終了する(実行が戻ってくること自体がハングしていない証拠)。"""
        m = _mission([
            _task("t1", worker="human"),
            _task("t2"),
        ])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        assert m.tasks[0].status == "awaiting_human"
        assert m.tasks[1].status == "done"

    def test_self_modification_guard_still_wins_for_human_worker(
            self, cfg, mock_state_dir):
        """自己改変ガードの判定順序は不変: humanタスクだからといって迂回しない。"""
        m = _mission([_task("t1", worker="human", workdir=str(REPO))])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        assert m.tasks[0].status == "awaiting_approval"
        assert m.tasks[0].human_request == ""
        assert read_calls(mock_state_dir) == []


class TestHumanRequestArtifact:
    def test_artifact_first_line_is_the_brief(self, cfg, mock_state_dir):
        m = _mission([_task("t1", worker="human")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        fp = store.dir / "artifacts" / "human_request_t1.md"
        assert fp.exists()
        text = fp.read_text()
        first_line = text.splitlines()[0]
        assert first_line == m.tasks[0].human_request
        assert first_line.strip()
        assert "## 何をするか" in text
        assert "## なぜ人間が必要か" in text
        assert "## 完了時に提出する証拠" in text
        assert f"orgh humandone {m.id} t1" in text


class TestHumanReviewTransition:
    def test_human_feedback_transitions_without_consuming_attempts(
            self, cfg, mock_state_dir, monkeypatch):
        monkeypatch.setenv("MOCK_REVIEW_HUMAN", "tr")
        m = Mission.new(intent="human転換試験", context_digest="(test)", tasks=[{
            "id": "tr", "title": "task tr",
            "prompt": "対面確認が要る作業をせよ [[MARK:tr]]",
            "worker": "claude_code", "deps": [],
            "acceptance": ["mock acceptance"], "workdir": ".",
        }])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        t = m.tasks[0]
        assert t.status == "awaiting_human"
        assert t.status != "failed"
        assert t.attempts == 0                     # HUMAN:転換はattemptsを消費しない
        assert t.human_request

        fp = store.dir / "artifacts" / "human_request_tr.md"
        assert fp.exists()
        assert "対面作業でしか解消できない" in fp.read_text()

        events = read_ledger(cfg["runs_dir"], m.id)
        assert any(e["event"] == "task.awaiting_human" and e["task"] == "tr"
                   for e in events)
        # worker成果は消費された(呼ばれてはいる)が、レビューでHUMAN:のため
        # 再実行(2回目のworker呼び出し)は発生していないこと
        workers = [c for c in read_calls(mock_state_dir) if c["role"] == "worker"]
        assert len(workers) == 1

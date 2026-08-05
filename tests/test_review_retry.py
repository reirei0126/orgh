"""実運用7307189e t6で発見: reviewer呼び出しがmax_turns超過で例外になると、
workerが全条件をクリアしていてもタスクがinternal errorで即failedになり、
成果ごと捨てられる(resume --retry-failedでworkerが丸ごと再実行される)。

対処: レビュー呼び出しの失敗はレビューのみリトライする(上限つき)。
上限超過時もinternal errorではなく原因の分かるreview_notesで失敗させる。"""
from __future__ import annotations

from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore

from .conftest import read_calls, read_ledger


def _mission(tasks):
    return Mission.new(intent="レビュー耐性試験", context_digest="(test)", tasks=tasks)


def _task(id: str) -> dict:
    return {
        "id": id, "title": f"task {id}",
        "prompt": f"作業せよ [[MARK:{id}]]",
        "worker": "claude_code", "deps": [],
        "acceptance": ["mock acceptance"], "workdir": ".",
    }


class TestReviewRetry:
    def test_reviewer_error_once_then_pass(self, cfg, mock_state_dir,
                                           monkeypatch):
        """レビュー1回失敗→リトライで合格。workerは1回しか呼ばれない。"""
        monkeypatch.setenv("MOCK_REVIEWER_FAIL_TIMES", "1")
        cfg["loop"]["infra_retry_wait"] = 0
        m = _mission([_task("rr")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "done"
        assert t.attempts == 1
        workers = [c for c in read_calls(mock_state_dir)
                   if c["role"] == "worker" and c["marker"] == "rr"]
        assert len(workers) == 1  # workerの成果は捨てられていない
        retries = [e for e in read_ledger(cfg["runs_dir"], m.id)
                   if e["event"] == "role.retry" and e["role"] == "reviewer"]
        assert len(retries) == 1

    def test_reviewer_error_exhausted_fails_with_reason(self, cfg,
                                                        mock_state_dir,
                                                        monkeypatch):
        """リトライ上限まで失敗が続いたら、原因の分かるreview_notesでfailed。"""
        monkeypatch.setenv("MOCK_REVIEWER_FAIL_TIMES", "99")
        cfg["loop"]["infra_retry_wait"] = 0
        m = _mission([_task("rx")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "failed"
        assert "レビュー" in t.review_notes
        assert "internal error" not in t.review_notes
        # worker成果(last_output)は保存されている
        assert "WORKER_DONE" in t.last_output

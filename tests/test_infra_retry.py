"""実運用7307189e t5で発見: ネットワーク断・スリープ中に走ったattemptが
「Request timed out」「API Error: Unable to connect to API (ENOTFOUND)」で
3回失敗し、タスクの全attempt(≒6.4USD相当のセッション)を浪費した。

対処: インフラ起因のエラーはworkerの失敗ではないため、attemptを消費せず
待機後に再試行する。ただし無限リトライはコスト垂れ流しになるため上限つき
(loop.infra_max_retries、既定3)。"""
from __future__ import annotations

from orgh.orchestrator import _is_infra_error, run_mission
from orgh.state import Mission, RunStore

from .conftest import read_calls, read_ledger


def _mission(tasks):
    return Mission.new(intent="インフラ試験", context_digest="(test)", tasks=tasks)


def _task(id: str, worker: str = "claude_code") -> dict:
    return {
        "id": id, "title": f"task {id}",
        "prompt": f"作業せよ [[MARK:{id}]]",
        "worker": worker, "deps": [],
        "acceptance": ["mock acceptance"], "workdir": ".",
    }


class TestInfraErrorDetection:
    def test_known_infra_signatures(self):
        for out in (
            "Request timed out",
            "API Error: Unable to connect to API (ENOTFOUND)",
            "API Error: Connection closed mid-response. The response above may be incomplete.",
            "fetch failed: ECONNRESET",
        ):
            assert _is_infra_error(out), out

    def test_normal_failures_are_not_infra(self):
        for out in (
            "timeout",  # task_timeout超過は「詰まったworker」の可能性があるため通常failure
            "simulated worker error: t1",
            "Reached maximum number of turns (15)",
            "",
        ):
            assert not _is_infra_error(out), repr(out)


class TestInfraRetryLoop:
    def test_infra_error_does_not_consume_attempts(self, cfg, mock_state_dir,
                                                   monkeypatch):
        """インフラエラー2回→成功。attemptsは1のまま、ledgerにinfra_retryが残る。"""
        monkeypatch.setenv("MOCK_INFRA_FAIL_TIMES", "2")
        cfg["loop"]["infra_retry_wait"] = 0
        m = _mission([_task("ti")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "done"
        assert t.attempts == 1  # インフラ分は消費しない
        retries = [e for e in read_ledger(cfg["runs_dir"], m.id)
                   if e["event"] == "task.infra_retry"]
        assert len(retries) == 2
        # worker自体は3回呼ばれている(失敗2+成功1)
        calls = [c for c in read_calls(mock_state_dir)
                 if c["role"] == "worker" and c["marker"] == "ti"]
        assert len(calls) == 3

    def test_infra_retry_cap_fails_task(self, cfg, mock_state_dir, monkeypatch):
        """上限(既定3)を超えて続くインフラエラーはタスクをfailedにする。"""
        monkeypatch.setenv("MOCK_INFRA_FAIL_TIMES", "99")
        cfg["loop"]["infra_retry_wait"] = 0
        m = _mission([_task("tc")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "failed"
        assert "インフラ" in t.review_notes
        retries = [e for e in read_ledger(cfg["runs_dir"], m.id)
                   if e["event"] == "task.infra_retry"]
        assert len(retries) == 3  # 既定上限

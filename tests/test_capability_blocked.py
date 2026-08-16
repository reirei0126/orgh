"""実運用b6503b9a t3で発見: workerの非対話実行環境でgitコマンドが
"This command requires approval" で承認待ちのまま完了せず(runs/b6503b9a/
artifacts/t3_attempt1.md, t3_attempt2.md で実測)、3ターンを浪費した末に
Reviewerの `HUMAN:` 判断でawaiting_humanへ人手で転換された。

対処: この署名をLLM判断(review)を介さず機械的に検知し、ledgerに
capability.blocked を記録した上でawaiting_humanへ直接遷移させる。誤検知は
awaiting_humanの濫発に直結するため、署名は実測されたものだけを対象にする。
"""
from __future__ import annotations

from orgh.orchestrator import _is_capability_error, run_mission
from orgh.state import Mission, RunStore

from .conftest import read_calls, read_ledger


def _mission(tasks):
    return Mission.new(intent="権限失敗試験", context_digest="(test)", tasks=tasks)


def _task(id: str, worker: str = "claude_code") -> dict:
    return {
        "id": id, "title": f"task {id}",
        "prompt": f"作業せよ [[MARK:{id}]]",
        "worker": worker, "deps": [],
        "acceptance": ["mock acceptance"], "workdir": ".",
    }


class TestCapabilityErrorDetection:
    def test_known_capability_signature(self):
        assert _is_capability_error(
            "$ git -C /path/to/target rev-parse HEAD\n"
            "This command requires approval")

    def test_normal_failures_are_not_capability(self):
        for out in (
            "simulated worker error: t1",
            "Reached maximum number of turns (15)",
            "Request timed out",  # インフラエラーは別署名(誤検知しない)
            "",
        ):
            assert not _is_capability_error(out), repr(out)


class TestCapabilityBlockedTransition:
    def test_capability_blocked_skips_review_to_awaiting_human(
            self, cfg, mock_state_dir, monkeypatch):
        """権限起因署名を含むworker出力は、LLM判断(review)を経ずに
        直接awaiting_humanへ遷移する。"""
        monkeypatch.setenv("MOCK_CAPABILITY_BLOCK", "tc")
        m = _mission([_task("tc")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "awaiting_human"
        calls = read_calls(mock_state_dir)
        assert not [c for c in calls if c["role"] == "reviewer"]

    def test_capability_blocked_records_ledger_event(
            self, cfg, mock_state_dir, monkeypatch):
        monkeypatch.setenv("MOCK_CAPABILITY_BLOCK", "tc")
        m = _mission([_task("tc")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        events = [e for e in read_ledger(cfg["runs_dir"], m.id)
                  if e["event"] == "capability.blocked"]
        assert len(events) == 1
        assert events[0]["task"] == "tc"

    def test_human_request_includes_blocked_command_and_allowlist_suggestion(
            self, cfg, mock_state_dir, monkeypatch):
        monkeypatch.setenv("MOCK_CAPABILITY_BLOCK", "tc")
        m = _mission([_task("tc")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        body = (store.dir / "artifacts" / "human_request_tc.md").read_text()
        assert "This command requires approval" in body
        assert "capability_allowlist" in body

    def test_non_capability_failure_still_goes_to_retry(
            self, cfg, mock_state_dir, monkeypatch):
        """権限起因でない通常の失敗出力は従来通りretry/レビュー経路に流れる
        (誤検知しない): awaiting_humanへ直行せず、capability.blockedも
        記録されず、workerが複数回呼ばれる(retry)。"""
        monkeypatch.setenv("MOCK_WORKER_FAIL", "tf")
        m = _mission([_task("tf")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status != "awaiting_human"
        events = [e for e in read_ledger(cfg["runs_dir"], m.id)
                  if e["event"] == "capability.blocked"]
        assert not events
        worker_calls = [c for c in read_calls(mock_state_dir)
                        if c["role"] == "worker"]
        assert len(worker_calls) >= 2  # 最初の失敗のあとretryされている

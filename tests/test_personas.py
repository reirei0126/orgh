"""ペルソナ検収ゲート(戦略設計書 柱1)。final_task割り当てと検収ループ。"""
from __future__ import annotations

import time

import pytest

from .conftest import read_calls, read_ledger
from orgh.orchestrator import _assign_personas, run_mission
from orgh.planner import persona_review
from orgh.state import Mission, RunStore, Task


def _task(id: str, deps=None, **kw) -> dict:
    return {"id": id, "title": f"task {id}", "prompt": f"作業 [[MARK:{id}]]",
            "worker": "claude_code", "deps": deps or [],
            "acceptance": ["mock acceptance"], "workdir": ".", **kw}


class TestAssign:
    def test_final_task_gets_personas(self):
        m = Mission.new(intent="x", context_digest="",
                        tasks=[_task("t1"), _task("t2", deps=["t1"])])
        _assign_personas({"personas": {"enabled": ["consumer"]}}, m)
        assert m.tasks[0].personas == []          # 中間タスクは対象外
        assert m.tasks[1].personas == ["consumer"]

    def test_disabled_is_noop(self):
        m = Mission.new(intent="x", context_digest="", tasks=[_task("t1")])
        _assign_personas({}, m)
        assert m.tasks[0].personas == []

    def test_planner_explicit_wins(self):
        m = Mission.new(intent="x", context_digest="",
                        tasks=[_task("t1", personas=["designer"])])
        _assign_personas({"personas": {"enabled": ["consumer"]}}, m)
        assert m.tasks[0].personas == ["designer"]


def _t(id="p1") -> Task:
    return Task(id=id, title="UI", prompt=f"作業 [[MARK:{id}]]",
                acceptance=["a"], last_output="done")


class TestPersonaReview:
    def test_pass_with_evidence(self, cfg, mock_state_dir):
        # フォローアップ2: persona_reviewの戻り値は3タプル(pass, feedback,
        # evidence)。evidenceは呼び出し側がledgerへ記録できるよう返す
        ok, fb, evidence = persona_review(cfg, "consumer", _t(), workdir=".")
        assert ok and fb == ""
        assert evidence == ["shot.png"]

    def test_no_evidence_pass_is_invalid(self, cfg, mock_state_dir,
                                         monkeypatch):
        monkeypatch.setenv("MOCK_PERSONA_NO_EVIDENCE", "p1")
        with pytest.raises(ValueError, match="証拠"):
            persona_review(cfg, "consumer", _t(), workdir=".")

    def test_fail_without_evidence_is_valid(self, cfg, mock_state_dir,
                                            monkeypatch):
        monkeypatch.setenv("MOCK_PERSONA_ALWAYS_FAIL", "p1")
        ok, fb, evidence = persona_review(cfg, "designer", _t(), workdir=".")
        assert not ok and "MARK" in fb
        assert evidence == ["shot.png"]  # 差し戻しでもモックはevidenceを返す


class TestPersonaGateST:
    def _cfg(self, cfg):
        cfg["personas"] = {"enabled": ["consumer", "designer"]}
        cfg["loop"]["infra_retry_wait"] = 0
        return cfg

    def test_persona_reject_once_then_pass(self, cfg, mock_state_dir,
                                           monkeypatch):
        """consumer差し戻し→worker修正→再レビュー→全ペルソナ合格→done。"""
        monkeypatch.setenv("MOCK_PERSONA_REJECT_ONCE", "g1")
        m = Mission.new(intent="x", context_digest="", tasks=[_task("g1")])
        run_mission(self._cfg(cfg), m, RunStore(cfg["runs_dir"], m.id))
        t = m.tasks[0]
        assert t.status == "done"
        assert t.attempts == 2                    # 差し戻しで1回増える
        events = [e for e in read_ledger(cfg["runs_dir"], m.id)
                  if e["event"] == "task.persona_review"]
        assert any(not e["passed"] for e in events)
        assert events[-1]["passed"]
        # フォローアップ2: evidenceがledgerに記録され、監査に使える(非空)
        assert all(e.get("evidence") for e in events)

    def test_persona_always_fail_exhausts_attempts(self, cfg, mock_state_dir,
                                                   monkeypatch):
        monkeypatch.setenv("MOCK_PERSONA_ALWAYS_FAIL", "g2")
        m = Mission.new(intent="x", context_digest="", tasks=[_task("g2")])
        run_mission(self._cfg(cfg), m, RunStore(cfg["runs_dir"], m.id))
        assert m.tasks[0].status == "failed"
        assert "ペルソナ" in m.tasks[0].review_notes

    def test_no_evidence_pass_retries_then_fails_keeping_output(
            self, cfg, mock_state_dir, monkeypatch):
        """証拠なし合格はロールリトライ→枯渇でfailed。worker成果は保持。"""
        monkeypatch.setenv("MOCK_PERSONA_NO_EVIDENCE", "g3")
        m = Mission.new(intent="x", context_digest="", tasks=[_task("g3")])
        run_mission(self._cfg(cfg), m, RunStore(cfg["runs_dir"], m.id))
        t = m.tasks[0]
        assert t.status == "failed"
        assert t.last_output           # 成果は捨てられていない
        retries = [e for e in read_ledger(cfg["runs_dir"], m.id)
                   if e["event"] == "role.retry"
                   and e["role"] == "persona_consumer"]
        assert len(retries) == 2

    def test_task_cost_usd_includes_reviewer_and_persona_costs(
            self, cfg, mock_state_dir):
        """フォローアップ4b: t.cost_usdはworker実行コストのみだったため、
        reviewer/ペルソナのロールコストがタスク単価に反映されず過小表示に
        なっていた(次attempt冒頭のタスク予算チェックも同様に過小評価)。
        worker(0.01)+reviewer(0.01)+persona consumer(0.01)+persona designer(0.01)
        の合計がt.cost_usdに載ることを確認する。"""
        m = Mission.new(intent="x", context_digest="", tasks=[_task("g6")])
        run_mission(self._cfg(cfg), m, RunStore(cfg["runs_dir"], m.id))
        t = m.tasks[0]
        assert t.status == "done"
        assert abs(t.cost_usd - 0.04) < 1e-9

    def test_disabled_personas_no_calls(self, cfg, mock_state_dir):
        """personas未設定なら従来動作(ペルソナ呼び出しゼロ)。"""
        m = Mission.new(intent="x", context_digest="", tasks=[_task("g4")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))
        assert m.tasks[0].status == "done"
        personas = [c for c in read_calls(mock_state_dir)
                    if c["role"] == "persona"]
        assert personas == []

    def test_missing_persona_prompt_fails_without_retry(self, cfg,
                                                         mock_state_dir):
        """personas.enabledのタイポ等でprompts/persona_<name>.mdが無い場合は
        FileNotFoundError(決定論的な設定ミス)。一時的失敗と同様にロール
        リトライ(infra_retry_wait秒待機)しても直らないため、即失敗させる。"""
        cfg["personas"] = {"enabled": ["nosuch"]}
        cfg["loop"]["infra_retry_wait"] = 5
        m = Mission.new(intent="x", context_digest="", tasks=[_task("g5")])
        start = time.time()
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))
        elapsed = time.time() - start
        t = m.tasks[0]
        assert t.status == "failed"
        assert "ペルソナ" in t.review_notes
        retries = [e for e in read_ledger(cfg["runs_dir"], m.id)
                   if e["event"] == "role.retry"
                   and e["role"] == "persona_nosuch"]
        assert retries == []              # リトライ待機を経由していない証拠
        assert elapsed < cfg["loop"]["infra_retry_wait"]  # 60秒級の待機なし

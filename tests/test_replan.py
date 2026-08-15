"""HANDOFF タスク5: 差し戻し先の分岐(REPLAN)。

- Reviewerのfeedbackが "REPLAN:" で始まる場合、Workerへの再実行ではなく
  Plannerへエスカレーションし、タスクのprompt/acceptanceを再設計させる
- REPLAN再実行はattemptsを消費しない
- REPLAN再設計は1タスク1回まで。2回目は failed にして理由を記録
- ledgerに task.replan イベントを記録
"""
from __future__ import annotations

from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore

from .conftest import read_calls, read_ledger


def _mission() -> Mission:
    return Mission.new(intent="replan試験", context_digest="(test)", tasks=[{
        "id": "tr", "title": "task tr",
        "prompt": "曖昧な作業をせよ [[MARK:tr]]",
        "worker": "claude_code", "deps": [],
        "acceptance": ["いい感じにする"],  # 主観語のみ=計画の欠陥
        "workdir": ".",
    }])


class TestReplan:
    def test_replan_redesigns_task_and_completes(self, cfg, mock_state_dir,
                                                 monkeypatch):
        monkeypatch.setenv("MOCK_REVIEW_REPLAN", "tr")
        cfg["loop"]["max_attempts"] = 1  # attempts非消費の証明: 1でも再実行できる
        m = _mission()
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        t = m.tasks[0]
        assert t.status == "done"
        assert t.attempts == 1                      # REPLAN再実行は消費しない
        # Plannerが検証可能なacceptanceに置き換えている
        assert t.acceptance == ["機械検証可能な条件: 成果物ファイルが存在する"]
        assert t.prompt.startswith("再設計済みの指示")

        calls = read_calls(mock_state_dir)
        assert any(c.get("kind") == "replan" for c in calls)
        workers = [c for c in calls if c["role"] == "worker"]
        assert len(workers) == 2                    # 再設計後にworkerが再実行
        assert any(e["event"] == "task.replan" and e["task"] == "tr"
                   for e in read_ledger(cfg["runs_dir"], m.id))

    def test_second_replan_fails_with_reason(self, cfg, mock_state_dir,
                                             monkeypatch):
        monkeypatch.setenv("MOCK_REVIEW_REPLAN_ALWAYS", "tr")
        m = _mission()
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        t = m.tasks[0]
        assert t.status == "failed"                 # 無限ループ防止
        assert "REPLAN" in t.review_notes
        replans = [e for e in read_ledger(cfg["runs_dir"], m.id)
                   if e["event"] == "task.replan"]
        assert len(replans) == 1                    # 再設計は1回まで

    def test_normal_reject_still_goes_to_worker(self, cfg, mock_state_dir,
                                                monkeypatch):
        """REPLANでない通常差し戻しは従来通りworkerへ(回帰)。"""
        monkeypatch.setenv("MOCK_REJECT_ONCE", "tr")
        m = _mission()
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "done"
        assert t.attempts == 2                      # 通常差し戻しはattempt消費
        # 再設計されない(build_task正規化後のAC最小構造のまま)
        assert t.acceptance == [{"id": "AC-1", "text": "いい感じにする",
                                 "verify": None, "evidence": None}]

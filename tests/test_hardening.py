"""コードヘルスレビュー(2026-08-12)で確定したセキュリティ・堅牢性修正の回帰テスト。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from orgh.state import Mission, RunStore, build_task


class TestTaskIdValidation:
    def test_valid_id_accepted(self):
        t = build_task({"id": "t1", "title": "x", "prompt": "p"})
        assert t.id == "t1"

    @pytest.mark.parametrize("bad", ["../../x", "t/1", "a b", "", ".hidden",
                                     "x" * 65, "a;rm", "$(x)"])
    def test_bad_id_rejected(self, bad):
        with pytest.raises(ValueError):
            build_task({"id": bad, "title": "x", "prompt": "p"})

    def test_unknown_keys_dropped_not_crash(self):
        # LLMスキーマ揺れ(余分キー)でTypeError即死しない
        t = build_task({"id": "t1", "title": "x", "prompt": "p",
                        "priority": 1, "note": "z"})
        assert t.id == "t1"

    def test_mission_new_rejects_bad_task_id(self):
        with pytest.raises(ValueError):
            Mission.new("i", "c", [{"id": "../evil", "title": "x", "prompt": "p"}])


class TestArtifactConfinement:
    def test_traversal_name_rejected(self, tmp_path):
        store = RunStore(tmp_path / "runs", "m1")
        with pytest.raises(ValueError):
            store.artifact("../../escape.md", "x")

    def test_normal_name_written(self, tmp_path):
        store = RunStore(tmp_path / "runs", "m1")
        fp = store.artifact("t1_attempt1.md", "hello")
        assert fp.read_text() == "hello"
        assert fp.parent.name == "artifacts"


class TestPlaybookNameValidation:
    def test_traversal_name_coerced_to_general(self, cfg, tmp_path, monkeypatch):
        from orgh import planner
        from orgh.state import Budget
        # retroのplaybook_nameに../prompts/reviewerを返させ、playbooks外へ
        # 追記されないことを確認
        import json as _json
        monkeypatch.setenv("MOCK_RETRO_JSON", _json.dumps(
            {"playbook_name": "../prompts/reviewer", "lessons": "- evil"}))
        # playbooks_dirをtmpへ隔離する(cfgフィクスチャ既定は実リポジトリの
        # playbooks/を指しており、隔離しないままplanner.retro()を呼ぶと
        # 実ファイルへ教訓行を書き込んでしまう)
        cfg["playbooks_dir"] = str(tmp_path / "playbooks")
        m = Mission.new("i", "c", [{"id": "t1", "title": "x", "prompt": "p",
                                    "status": "done"}])
        m.budget = Budget(limit_usd=None, spent_usd=0.0)
        fp = planner.retro(cfg, m)
        pdir = Path(cfg["playbooks_dir"]).resolve()
        assert Path(fp).resolve().is_relative_to(pdir)
        # prompts/reviewer.md が作られていない
        assert not (Path(cfg["prompts_dir"]) / "reviewer.md.md").exists()


class TestGcSkipsActiveMissions:
    def _mk(self, runs, mid, status, days_old):
        d = runs / mid
        d.mkdir(parents=True)
        tasks = [{"id": "t1", "title": "x", "prompt": "p",
                  "worker": "claude_code", "deps": [], "status": status,
                  "attempts": 0}]
        (d / "mission.json").write_text(json.dumps({
            "id": mid, "intent": "x", "context_digest": "",
            "tasks": tasks, "budget": None,
            "created_at": time.time() - days_old * 86400}))

    def test_awaiting_human_not_archived(self, cfg, tmp_path):
        from orgh import gc
        # playbooks_dirをtmpへ隔離する(cfgフィクスチャ既定は実リポジトリの
        # playbooks/を指しており、隔離しないままgc.run_gc()を呼ぶと実ファイルを
        # 書き換えてしまう。他のgcテストはpb_dirフィクスチャで隔離している)
        cfg["playbooks_dir"] = str(tmp_path / "playbooks")
        runs = Path(cfg["runs_dir"])
        self._mk(runs, "activeold", "awaiting_human", 200)
        self._mk(runs, "doneold", "done", 200)
        gc.run_gc(cfg)
        assert (runs / "activeold" / "mission.json").exists()  # 保持
        assert not (runs / "doneold").exists()                 # アーカイブ済み
        assert (runs / "_archive" / "doneold").exists()


class TestCancelLockSafety:
    def test_cancel_when_locked_does_not_clobber_state(self, cfg, mock_state_dir,
                                                       tmp_path, monkeypatch):
        # executor実行中(ロック保持)を模し、cancelがmission.jsonを上書き
        # しないことを確認する
        import fcntl
        import sys as _sys
        from orgh import cli
        from orgh.orchestrator import acquire_mission_lock
        from .conftest import write_config
        m = Mission.new("i", "c", [{"id": "t1", "title": "x", "prompt": "p",
                                    "status": "running", "attempts": 1}])
        store = RunStore(cfg["runs_dir"], m.id)
        store.save(m)
        holder = acquire_mission_lock(store)   # executor役がロック保持
        assert holder is not None
        try:
            cfg_path = write_config(tmp_path, cfg)
            monkeypatch.setattr(_sys, "argv",
                                ["orgh", "--config", str(cfg_path),
                                 "cancel", m.id])
            cli.main()
            # ロックが取れないので状態は書き換わらない(runningのまま)
            reloaded = store.load(reset_inflight=False)
            assert reloaded.tasks[0].status == "running"
            assert (store.dir / "CANCEL").exists()  # フラグは設置される
        finally:
            holder.close()


class TestWorktreePreambleOnRetry:
    def test_retry_prompt_keeps_worktree_preamble(self, cfg):
        from orgh.orchestrator import _retry_prompt
        from orgh.state import Task

        class _NoResume:
            supports_resume = False
        t = Task(id="t1", title="x", prompt="p", worker="codex",
                 branch="orgh/m/t1", workdir="/tmp/wt")
        out = _retry_prompt(_NoResume(), cfg, t, "直してください")
        assert "【作業場所の厳守】" in out

    def test_full_worker_prompt_no_preamble_without_branch(self, cfg):
        from orgh.orchestrator import _full_worker_prompt
        from orgh.state import Task
        t = Task(id="t1", title="x", prompt="p", branch=None)
        assert "【作業場所の厳守】" not in _full_worker_prompt(cfg, t)

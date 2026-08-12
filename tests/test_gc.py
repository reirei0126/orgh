"""HANDOFF タスク6: playbookの代謝(orgh gc)。

- 教訓行のメタデータ <!-- m:<mission_id> d:<date> -->(retro追記時に付与)
- orgh gc: 実行前に playbooks/_backup/<date>/ へ全量バックアップ(なしでは走らない)、
  ファイルごとに統合Retro(重複統合・矛盾は新日付優先)、
  180日より古い教訓は playbooks/_archive/ へ退避
- 注入時のcapは「日付降順で詰める」(新しい教訓が必ず入る)
- runs/ 保持ポリシー: retention_days(既定90)超のミッションを runs/_archive/ へ
- watcherの gc_interval_days(既定14)で自動gc(初回パスはベースライン記録のみ)
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from orgh import cli, executor, planner, watcher
from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore

from .conftest import write_config

_OLD = "2025-01-01"                                   # 180日より昔
_NEW = (date.today() - timedelta(days=3)).isoformat()  # 最近
_MID = (date.today() - timedelta(days=30)).isoformat()


@pytest.fixture
def pb_dir(tmp_path, cfg) -> Path:
    d = tmp_path / "playbooks"
    d.mkdir()
    (d / "coding.md").write_text(
        f"- テストは書くな <!-- m:aaa d:{_MID} -->\n"
        f"- テストは必ず書け <!-- m:bbb d:{_NEW} -->\n")
    cfg["playbooks_dir"] = str(d)
    return d


class TestRetroMetadata:
    def test_retro_appends_lessons_with_metadata(self, cfg, pb_dir,
                                                 mock_state_dir, monkeypatch):
        monkeypatch.setenv(
            "MOCK_PLAN_JSON", "")  # 未使用だが明示
        m = Mission.new(intent="meta試験", context_digest="(test)", tasks=[{
            "id": "t1", "title": "task t1", "prompt": "作業 [[MARK:t1]]",
            "worker": "claude_code", "deps": [], "acceptance": ["a"],
            "workdir": "."}])
        # retroモックはlessons空を返すので、ここでは直接lessonsを返させる
        monkeypatch.setenv("MOCK_RETRO_JSON", json.dumps(
            {"playbook_name": "coding", "lessons": "- 新しい教訓"},
            ensure_ascii=False))
        planner.retro(cfg, m)

        body = (pb_dir / "coding.md").read_text()
        assert f"- 新しい教訓 <!-- m:{m.id} d:{date.today().isoformat()} -->" \
            in body


class TestGc:
    def test_contradictions_consolidated_with_backup(self, cfg, pb_dir,
                                                     mock_state_dir, tmp_path,
                                                     monkeypatch):
        original = (pb_dir / "coding.md").read_text()
        monkeypatch.setenv("MOCK_GC_JSON", json.dumps(
            {"lessons": f"- テストは必ず書け(統合済み) <!-- m:gc d:{_NEW} -->"},
            ensure_ascii=False))
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "gc"])
        cli.main()

        body = (pb_dir / "coding.md").read_text()
        assert "統合済み" in body
        assert "テストは書くな" not in body        # 矛盾は新日付優先で解消
        # 全量バックアップが取られている
        backups = list((pb_dir / "_backup").glob("*/coding.md"))
        assert len(backups) == 1
        assert backups[0].read_text() == original

    def test_old_lessons_archived_not_deleted(self, cfg, pb_dir,
                                              mock_state_dir):
        (pb_dir / "coding.md").write_text(
            f"- 古の教訓 <!-- m:old d:{_OLD} -->\n"
            f"- 現役の教訓 <!-- m:new d:{_NEW} -->\n")
        from orgh import gc
        gc.run_gc(cfg)

        assert "古の教訓" not in (pb_dir / "coding.md").read_text()
        archived = (pb_dir / "_archive" / "coding.md").read_text()
        assert "古の教訓" in archived              # 削除ではなく退避

    def test_gc_refuses_to_run_without_backup(self, cfg, pb_dir,
                                              mock_state_dir):
        original = (pb_dir / "coding.md").read_text()
        (pb_dir / "_backup").write_text("邪魔")   # ディレクトリを作れなくする
        from orgh import gc
        with pytest.raises(OSError):
            gc.run_gc(cfg)
        assert (pb_dir / "coding.md").read_text() == original  # 無傷

    def test_runs_retention_archives_old_missions(self, cfg, pb_dir,
                                                  mock_state_dir):
        runs = Path(cfg["runs_dir"])
        for mid, days in (("oldmission", 120), ("newmission", 5)):
            m = Mission(id=mid, intent="x", context_digest="c", tasks=[],
                        created_at=time.time() - days * 86400)
            RunStore(runs, mid).save(m)
        from orgh import gc
        gc.run_gc(cfg)

        assert not (runs / "oldmission").exists()
        assert (runs / "_archive" / "oldmission" / "mission.json").exists()
        assert (runs / "newmission" / "mission.json").exists()


class TestInjectionCap:
    def test_cap_keeps_newest_lessons(self, cfg, pb_dir):
        # 古い行を先頭に大量に置いてもcap内に最新が必ず入る
        lines = [f"- 古い教訓その{i} <!-- m:a d:{_MID} -->" for i in range(50)]
        lines.append(f"- 最新の教訓 <!-- m:z d:{_NEW} -->")
        (pb_dir / "coding.md").write_text("\n".join(lines) + "\n")

        ctx = planner._playbook_context(cfg, max_chars=200)
        assert "最新の教訓" in ctx
        assert "古い教訓その49" not in ctx or len(ctx) <= 200


class TestExecutorAutoGc:
    """自動gcの持ち主はexecutor(R-1分離でwatchから移設)。ミッション実行中は
    走らない(playbooks書き換えとretro追記の排他)。"""

    def test_first_pass_only_records_baseline(self, wcfg, vault, pb_dir,
                                              executor_one_pass,
                                              mock_state_dir):
        wcfg["playbooks_dir"] = str(pb_dir)
        executor.serve(wcfg)
        assert not (pb_dir / "_backup").exists()   # 初回はgcを走らせない
        state = json.loads(
            (Path(wcfg["runs_dir"]) / "_gc_state.json").read_text())
        assert state["last_gc"] > 0

    def test_elapsed_interval_triggers_gc(self, wcfg, vault, pb_dir,
                                          executor_one_pass, mock_state_dir):
        wcfg["playbooks_dir"] = str(pb_dir)
        runs = Path(wcfg["runs_dir"])
        runs.mkdir(parents=True, exist_ok=True)
        (runs / "_gc_state.json").write_text(json.dumps(
            {"last_gc": time.time() - 15 * 86400}))  # 既定14日を超過
        executor.serve(wcfg)
        assert (pb_dir / "_backup").exists()       # 自動gcが走った

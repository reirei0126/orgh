"""orgh list: runs配下の全ミッションをid/intent要約/状態/累計コストで一覧する。"""
from __future__ import annotations

from pathlib import Path

from orgh.listing import list_missions
from orgh.state import Budget, Mission, RunStore, Task


def _task(id: str, status: str) -> Task:
    return Task(id=id, title=f"task {id}", prompt="p", worker="claude_code",
                status=status)


def _mk_mission(runs_dir, mission_id: str, intent: str, tasks: list[Task],
                 spent: float = 0.0) -> RunStore:
    m = Mission(id=mission_id, intent=intent, context_digest="(test)",
                tasks=tasks, budget=Budget(limit_usd=None, spent_usd=spent))
    store = RunStore(runs_dir, mission_id)
    store.save(m)
    return store


class TestListMissions:
    def test_returns_all_missions_sorted_by_id(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m2", "二番目", [_task("t1", "done")])
        _mk_mission(runs_dir, "m1", "一番目", [_task("t1", "done")])
        out = list_missions(runs_dir)
        assert [m["mission_id"] for m in out] == ["m1", "m2"]

    def test_status_done_when_all_tasks_done(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "全部完了",
                    [_task("t1", "done"), _task("t2", "done")])
        out = list_missions(runs_dir)
        assert out[0]["status"] == "done"
        assert out[0]["tasks_done"] == 2
        assert out[0]["tasks_total"] == 2

    def test_status_failed_when_any_task_failed(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "一部失敗",
                    [_task("t1", "done"), _task("t2", "failed")])
        out = list_missions(runs_dir)
        assert out[0]["status"] == "failed"

    def test_status_running_when_in_progress(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "進行中",
                    [_task("t1", "done"), _task("t2", "pending")])
        out = list_missions(runs_dir)
        assert out[0]["status"] == "running"

    def test_status_empty_when_no_tasks(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "タスクなし", [])
        out = list_missions(runs_dir)
        assert out[0]["status"] == "empty"

    def test_intent_truncated_over_60_chars(self, tmp_path):
        runs_dir = tmp_path / "runs"
        long_intent = "あ" * 80
        _mk_mission(runs_dir, "m1", long_intent, [_task("t1", "done")])
        out = list_missions(runs_dir)
        assert len(out[0]["intent"]) == 61  # 60文字 + "…"
        assert out[0]["intent"].endswith("…")
        assert out[0]["intent"][:60] == long_intent[:60]

    def test_intent_short_not_truncated(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "短い意図", [_task("t1", "done")])
        out = list_missions(runs_dir)
        assert out[0]["intent"] == "短い意図"
        assert "…" not in out[0]["intent"]

    def test_intent_newlines_replaced_with_space(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "一行目\n二行目", [_task("t1", "done")])
        out = list_missions(runs_dir)
        assert "\n" not in out[0]["intent"]
        assert out[0]["intent"] == "一行目 二行目"

    def test_cost_usd_from_budget(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "コスト確認", [_task("t1", "done")],
                    spent=1.2345)
        out = list_missions(runs_dir)
        assert out[0]["cost_usd"] == 1.2345

    def test_cost_usd_zero_when_no_budget(self, tmp_path):
        runs_dir = tmp_path / "runs"
        m = Mission(id="m1", intent="予算なし", context_digest="(test)",
                    tasks=[_task("t1", "done")], budget=None)
        store = RunStore(runs_dir, "m1")
        store.save(m)
        out = list_missions(runs_dir)
        assert out[0]["cost_usd"] == 0.0

    def test_missing_runs_dir_returns_empty_list(self, tmp_path):
        assert list_missions(tmp_path / "does-not-exist") == []

    def test_broken_mission_dir_is_skipped_others_returned(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "正常ミッション", [_task("t1", "done")])
        broken = runs_dir / "m0-broken"
        broken.mkdir(parents=True)
        (broken / "mission.json").write_text("{not valid json")
        out = list_missions(runs_dir)
        assert [m["mission_id"] for m in out] == ["m1"]

    def test_dir_without_mission_json_is_skipped(self, tmp_path):
        runs_dir = tmp_path / "runs"
        _mk_mission(runs_dir, "m1", "正常ミッション", [_task("t1", "done")])
        (runs_dir / "not-a-mission").mkdir(parents=True)
        out = list_missions(runs_dir)
        assert [m["mission_id"] for m in out] == ["m1"]

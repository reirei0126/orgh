"""orgh report への verdict取得率・escape件数(category別)の追加、および
mission.completed通知/結果ノートfinalizeでの未裁定件数の告知。

docs/strategy/direction-2026-08.md §3.4 / A4:
- verdict取得率は「取得できた割合」であって精度指標ではない(精度を語る
  指標名を新たに名乗ってはいけない)
- 報告済みescape件数は「機械ゲート通過後にownerが不合格とした件数」の
  生データであり、それ自体が品質の良否を示すものではない
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from orgh import cli, listing, notify, report
from orgh.results import ResultsNote
from orgh.state import Budget, Mission, RunStore, Task

from .conftest import read_ledger, write_config


def _task(id: str, status: str = "done") -> Task:
    return Task(id=id, title=f"task {id}", prompt="p", worker="claude_code",
                status=status)


def _mk_mission(cfg, mission_id: str, tasks: list[Task]) -> RunStore:
    m = Mission(id=mission_id, intent=f"試験{mission_id}", context_digest="(test)",
                tasks=tasks, budget=Budget(limit_usd=None, spent_usd=0.0))
    store = RunStore(cfg["runs_dir"], mission_id)
    store.save(m)
    return store


def _record_verdict(store: RunStore, passed: bool, reason: str) -> None:
    with open(store.dir / "verdicts.jsonl", "a") as f:
        f.write(json.dumps({"ts": 1.0, "passed": passed, "reason": reason},
                            ensure_ascii=False) + "\n")


def _record_escape(store: RunStore, mission_id: str, reason: str,
                    tasks: list[str], category: str) -> None:
    with open(store.dir / "ledger.jsonl", "a") as f:
        f.write(json.dumps({"ts": 1.0, "event": "escape",
                            "mission_id": mission_id, "reason": reason,
                            "tasks": tasks, "category": category},
                           ensure_ascii=False) + "\n")


def _seed(cfg) -> None:
    """3件done(うちverdict済み2件、うち1件escape)+1件未完了。

    verdict取得率 = 2/3。escape件数 = 1件(category=visual)。
    """
    m1 = _mk_mission(cfg, "m1", [_task("t1")])
    _record_verdict(m1, passed=True, reason="良い")

    m2 = _mk_mission(cfg, "m2", [_task("t1")])
    _record_verdict(m2, passed=False, reason="配色が違う")
    _record_escape(m2, "m2", "配色が違う", ["t1"], "visual")

    _mk_mission(cfg, "m3", [_task("t1")])  # done, 未裁定

    _mk_mission(cfg, "m4", [_task("t1", status="failed")])  # 未完了(分母対象外)


class TestReportVerdictRate:
    def test_text_report_includes_verdict_rate_numerator_and_denominator(
            self, cfg, mock_state_dir):
        _seed(cfg)
        out = report.build_report(cfg)
        assert "verdict取得率" in out
        assert "2/3" in out

    def test_payload_unchanged_no_new_top_level_keys(self, cfg, mock_state_dir):
        # report_payload(JSON)はGUI連携の既存契約(desktop/API.md §1.6)。
        # 新指標はテキスト版(build_report)のみに追加し、JSON側のキー集合は
        # 変更しない(既存の厳密一致テストtest_report.py::
        # test_empty_when_no_missions_in_range を壊さないため)
        _seed(cfg)
        payload = report.report_payload(cfg)
        assert set(payload.keys()) == {"days", "weekly", "missions",
                                       "workers", "skipped"}


class TestReportEscapeCount:
    def test_text_report_includes_escape_total_and_category_breakdown(
            self, cfg, mock_state_dir):
        _seed(cfg)
        out = report.build_report(cfg)
        assert "報告済みescape件数" in out
        assert "1" in out
        assert "visual" in out

class TestMissionCompletedNotifiesPendingVerdictCount:
    def test_summary_includes_pending_verdict_count_when_given(self):
        t = Task(id="t1", title="task t1", prompt="do it", acceptance=["ok"])
        t.status = "done"
        m = Mission(id="m1", intent="試験ミッション", context_digest="(test)",
                    tasks=[t])
        event = notify.mission_completed_event(m, pending_verdict_count=3)
        assert "未裁定のミッションが3件あります" in event["summary"]

    def test_summary_unchanged_when_count_omitted(self):
        # 既存呼び出し(count省略)は従来どおりの文面のまま
        t = Task(id="t1", title="task t1", prompt="do it", acceptance=["ok"])
        t.status = "done"
        m = Mission(id="m1", intent="試験ミッション", context_digest="(test)",
                    tasks=[t])
        event = notify.mission_completed_event(m)
        assert "未裁定" not in event["summary"]

    def test_scheduler_reports_pending_count_matching_listing(
            self, cfg, mock_state_dir):
        from orgh.orchestrator import run_mission

        # 先に1件、verdict未実施のdoneミッションを作っておく
        _mk_mission(cfg, "already-done", [_task("t1")])

        m = Mission.new(intent="通知経路試験", context_digest="(test)",
                        tasks=[{"id": "t1", "title": "task t1", "prompt": "p",
                                "worker": "claude_code", "deps": [],
                                "acceptance": ["a"], "workdir": "."}])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)

        events = read_ledger(cfg["runs_dir"], m.id)
        completed = next(e for e in events if e["event"] == "notify.emitted"
                         and e["event_type"] == "mission.completed")
        expected = len(listing.list_pending_verdicts(cfg["runs_dir"])["missions"])
        assert f"未裁定のミッションが{expected}件あります" in completed["summary"]


class TestResultsNoteFinalizeShowsPendingVerdictCount:
    def test_finalize_note_includes_pending_verdict_count(
            self, cfg, mock_state_dir, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg["vault"] = {"path": str(vault)}

        _mk_mission(cfg, "already-done", [_task("t1")])  # 未裁定1件を先に作る

        t = Task(id="t1", title="task t1", prompt="p", worker="claude_code",
                 status="done")
        m = Mission(id="m2", intent="結果ノート試験", context_digest="(test)",
                    tasks=[t])
        store = RunStore(cfg["runs_dir"], "m2")
        store.save(m)

        note = ResultsNote(cfg, "m2")
        note.finalize(m, store)

        body = note.path.read_text()
        expected = len(listing.list_pending_verdicts(cfg["runs_dir"])["missions"])
        assert f"未裁定のミッションが{expected}件あります" in body


class TestCliReportUnaffectedForExistingSections:
    def test_existing_report_sections_still_present(self, cfg, mock_state_dir,
                                                     tmp_path, monkeypatch,
                                                     capsys):
        _seed(cfg)
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "report"])
        cli.main()
        out = capsys.readouterr().out
        assert "## 週次: 初回attempt合格率と差し戻し率" in out
        assert "## ミッション別コスト・所要時間" in out
        assert "## worker別失敗率" in out

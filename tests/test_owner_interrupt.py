"""owner.interrupt ledgerの新設とreport集計。

「ミッションあたりのオーナー割り込み回数」は割り込みゼロ設計(raison-detre-2026-08
§5-R3補遺)の効果を導入前後で比較する唯一の数値指標。記録漏れがあると指標そのもの
が無意味になるため、awaiting_human遷移・承認要求・REPLANの3経路それぞれが
owner.interruptイベントを1行追加で記録することを検証する。

既存の task.awaiting_human / task.awaiting_approval / task.replan イベントは
そのまま残る(既存テストと既存集計は不変)。owner.interrupt はその横に追加で
記録される新規イベント。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from orgh import cli, report
from orgh.orchestrator import run_mission
from orgh.state import Budget, Mission, RunStore, Task

from .conftest import read_ledger, write_config

REPO = Path(__file__).resolve().parent.parent


def _task(id: str, worker: str = "claude_code", deps: list[str] | None = None,
         workdir: str = ".", acceptance: list | None = None) -> dict:
    return {"id": id, "title": f"task {id}",
            "prompt": f"作業せよ [[MARK:{id}]]",
            "worker": worker, "deps": deps or [],
            "acceptance": acceptance or ["mock acceptance"], "workdir": workdir}


def _mission(tasks: list[dict]) -> Mission:
    return Mission.new(intent="owner.interrupt試験", context_digest="(test)",
                       tasks=tasks)


class TestOwnerInterruptOnAwaitingHuman:
    def test_worker_human_transition_logs_owner_interrupt(self, cfg,
                                                           mock_state_dir):
        """orgh/orchestrator/transitions.py の enter_awaiting_human 経路
        (scheduler.pyのworker: human分岐)。"""
        m = _mission([_task("t1", worker="human")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "awaiting_human"

        events = read_ledger(cfg["runs_dir"], m.id)
        interrupts = [e for e in events if e["event"] == "owner.interrupt"]
        assert len(interrupts) == 1
        assert interrupts[0]["kind"] == "awaiting_human"
        assert interrupts[0]["task"] == "t1"
        assert interrupts[0].get("detail")
        # 既存イベントはそのまま残る
        assert any(e["event"] == "task.awaiting_human" for e in events)

    def test_humandone_rejection_logs_owner_interrupt(self, cfg, mock_state_dir,
                                                       tmp_path, monkeypatch):
        """orgh/cli.py の humandone 差し戻し経路(enter_awaiting_humanを経由
        しない別経路)。両方に入れないと片方だけ計測が欠ける。"""
        m = _mission([_task("t1", worker="human")])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "awaiting_human"

        monkeypatch.setenv("MOCK_REVIEW_ALWAYS_FAIL", "t1")
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "humandone", m.id, "t1",
            "--note", "不十分な報告"])
        cli.main()

        events = read_ledger(cfg["runs_dir"], m.id)
        interrupts = [e for e in events if e["event"] == "owner.interrupt"
                      and e["kind"] == "awaiting_human"]
        # 1件目はworker:human着火時、2件目がhumandone差し戻し経路
        assert len(interrupts) == 2
        assert all(i["task"] == "t1" for i in interrupts)


class TestOwnerInterruptOnApprovalRequested:
    def test_self_mod_guard_logs_owner_interrupt(self, cfg, mock_state_dir):
        """orgh/orchestrator/scheduler.py の承認ガード(206〜217行目付近)。"""
        m = _mission([_task("t1", workdir=str(REPO))])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "awaiting_approval"

        events = read_ledger(cfg["runs_dir"], m.id)
        interrupts = [e for e in events if e["event"] == "owner.interrupt"]
        assert len(interrupts) == 1
        assert interrupts[0]["kind"] == "approval_requested"
        assert interrupts[0]["task"] == "t1"
        assert any(e["event"] == "task.awaiting_approval" for e in events)


class TestOwnerInterruptOnReplan:
    def test_replan_logs_owner_interrupt(self, cfg, mock_state_dir, monkeypatch):
        """orgh/orchestrator/task_executor.py のREPLAN経路(316行目付近)。"""
        monkeypatch.setenv("MOCK_REVIEW_REPLAN", "tr")
        cfg["loop"]["max_attempts"] = 1
        m = _mission([{
            "id": "tr", "title": "task tr",
            "prompt": "曖昧な作業をせよ [[MARK:tr]]",
            "worker": "claude_code", "deps": [],
            "acceptance": ["いい感じにする"], "workdir": ".",
        }])
        store = RunStore(cfg["runs_dir"], m.id)
        run_mission(cfg, m, store)
        assert m.tasks[0].status == "done"

        events = read_ledger(cfg["runs_dir"], m.id)
        interrupts = [e for e in events if e["event"] == "owner.interrupt"]
        assert len(interrupts) == 1
        assert interrupts[0]["kind"] == "owner_replan"
        assert interrupts[0]["task"] == "tr"
        assert any(e["event"] == "task.replan" for e in events)


# ------------------------------------------------------------- report集計


def _write_ledger(store: RunStore, events: list[dict]) -> None:
    with open(store.dir / "ledger.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _mk_mission(cfg, mission_id: str, tasks: list[Task]) -> RunStore:
    m = Mission(id=mission_id, intent=f"試験ミッション{mission_id}",
               context_digest="(test)", tasks=tasks,
               budget=Budget(limit_usd=None, spent_usd=0.0))
    store = RunStore(cfg["runs_dir"], mission_id)
    store.save(m)
    return store


def _t(id: str) -> Task:
    return Task(id=id, title=f"task {id}", prompt="p", worker="claude_code",
               status="done")


def _seed_interrupts(cfg) -> None:
    """3ミッション: m1は割り込み2件(awaiting_human x1, approval_requested x1)、
    m2は割り込み1件(owner_replan x1)、m3は割り込みゼロ。
    総件数3 / ミッション数3 = 1.00 が期待値。"""
    s1 = _mk_mission(cfg, "m1", [_t("t1")])
    _write_ledger(s1, [
        {"ts": 1000.0, "event": "task.awaiting_human", "task": "t1", "brief": "b"},
        {"ts": 1000.0, "event": "owner.interrupt", "kind": "awaiting_human",
         "task": "t1", "detail": "b"},
        {"ts": 1001.0, "event": "task.awaiting_approval", "task": "t1"},
        {"ts": 1001.0, "event": "owner.interrupt", "kind": "approval_requested",
         "task": "t1", "detail": "self_mod"},
        {"ts": 1002.0, "event": "mission.finished", "done": ["t1"]},
    ])
    s2 = _mk_mission(cfg, "m2", [_t("t2")])
    _write_ledger(s2, [
        {"ts": 2000.0, "event": "task.replan", "task": "t2", "reason": "r"},
        {"ts": 2000.0, "event": "owner.interrupt", "kind": "owner_replan",
         "task": "t2", "detail": "r"},
        {"ts": 2001.0, "event": "mission.finished", "done": ["t2"]},
    ])
    s3 = _mk_mission(cfg, "m3", [_t("t3")])
    _write_ledger(s3, [
        {"ts": 3000.0, "event": "task.start", "task": "t3"},
        {"ts": 3001.0, "event": "mission.finished", "done": ["t3"]},
    ])


class TestReportOwnerInterruptsText:
    def test_build_report_shows_per_mission_rate_and_breakdown(self, cfg,
                                                                mock_state_dir):
        _seed_interrupts(cfg)
        out = report.build_report(cfg)
        assert "## オーナー割り込み" in out
        assert "ミッションあたり割り込み回数: 1.00" in out
        line = next(l for l in out.splitlines()
                    if "ミッションあたり割り込み回数" in l)
        assert "3" in line  # 総件数3
        assert "awaiting_human: 1" in out
        assert "approval_requested: 1" in out
        assert "owner_replan: 1" in out

    def test_existing_sections_unchanged_content(self, cfg, mock_state_dir):
        # 既存セクションの文言・数値は変わらない(worker別失敗率は0%のまま)
        _seed_interrupts(cfg)
        out = report.build_report(cfg)
        assert "## 週次: 初回attempt合格率と差し戻し率" in out
        assert "## ミッション別コスト・所要時間" in out
        assert "## worker別失敗率" in out
        assert "## 検収の裏付け" in out


class TestReportOwnerInterruptsJson:
    """report_payload(JSON)はGUI連携の既存契約(desktop/API.md §1.6)で、
    tests/test_verdict_report_metrics.py::test_payload_unchanged_no_new_top_level_keys
    が「新指標はテキスト版のみに追加し、JSON側のトップレベルキー集合は変更
    しない」を既に確定させている(既存の厳密一致テストtest_report.py::
    test_empty_when_no_missions_in_range を壊さないための設計)。
    そのためowner.interrupt件数はmissions配列の各要素に
    owner_interrupts(ミッション単位の件数)として載せ、これを合計した値が
    テキスト版の総件数と一致することで「食い違わない」契約を担保する。
    """

    def test_per_mission_counts_sum_to_text_report_total(self, cfg,
                                                          mock_state_dir):
        _seed_interrupts(cfg)
        payload = report.report_payload(cfg)
        out = report.build_report(cfg)

        by_mission = {m["mission_id"]: m["owner_interrupts"]
                     for m in payload["missions"]}
        assert by_mission == {"m1": 2, "m2": 1, "m3": 0}
        assert sum(by_mission.values()) == 3
        assert "ミッションあたり割り込み回数: 1.00" in out
        assert "(総件数 3 / ミッション数 3)" in out

    def test_json_dumpable(self, cfg, mock_state_dir):
        _seed_interrupts(cfg)
        payload = report.report_payload(cfg)
        json.dumps(payload, ensure_ascii=False)  # 例外を出さない

    def test_top_level_key_set_unchanged(self, cfg, mock_state_dir):
        _seed_interrupts(cfg)
        payload = report.report_payload(cfg)
        assert set(payload.keys()) == {"days", "weekly", "missions",
                                       "workers", "skipped"}

    def test_cli_report_json_includes_per_mission_owner_interrupts(
            self, cfg, mock_state_dir, tmp_path, monkeypatch, capsys):
        _seed_interrupts(cfg)
        cfg_path = write_config(tmp_path, cfg)
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "report", "--json"])
        cli.main()
        out = capsys.readouterr().out
        payload = json.loads(out)
        m1 = next(m for m in payload["missions"] if m["mission_id"] == "m1")
        assert m1["owner_interrupts"] == 2


class TestReportOwnerInterruptsBackwardCompat:
    """owner.interruptを1件も含まない既存形式のledgerでもreportが例外なく
    生成される。既存のtests/test_report.pyは無変更・無改変のままPASSすること
    (このファイルとは別に担保する)。"""

    def test_legacy_ledger_without_owner_interrupt_events(self, cfg,
                                                           mock_state_dir):
        s1 = _mk_mission(cfg, "legacy1", [_t("t1")])
        _write_ledger(s1, [
            {"ts": 1000.0, "event": "watch.triggered"},
            {"ts": 1001.0, "event": "task.start", "task": "t1"},
            {"ts": 1005.0, "event": "task.review", "task": "t1", "passed": True},
            {"ts": 1006.0, "event": "mission.finished", "done": ["t1"]},
        ])
        out = report.build_report(cfg)  # 例外を出さない
        assert "## オーナー割り込み" in out
        assert "ミッションあたり割り込み回数: 0.00" in out

        payload = report.report_payload(cfg)  # 例外を出さない
        assert payload["missions"][0]["owner_interrupts"] == 0

    def test_no_missions_in_scope_matches_legacy_exact_shape(self, cfg,
                                                              mock_state_dir):
        # 既存回帰テスト test_report.py::test_empty_when_no_missions_in_range
        # と同じ入力での完全一致(トップレベルキー集合が増えていないこと)
        _seed_interrupts(cfg)
        payload = report.report_payload(cfg, days=1)  # 過去日付シードは全滅
        assert payload == {"days": 1, "weekly": [], "missions": [],
                           "workers": [], "skipped": []}

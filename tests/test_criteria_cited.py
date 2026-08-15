"""裁定応答の criteria_cited 記録と捏造ID破棄(A3aの前段計器)。

Reviewer/ペルソナがどのオーナー判断基準(criteria)を実際に参照したかを
task.review / task.persona_review イベントへ criteria_cited として記録する。
そのタスクの裁定プロンプトに実際に注入されなかったID(捏造)は破棄する。

裁定応答は orgh.planner._ask_json をmonkeypatchして直接与える(外部API不使用)。
"""
from __future__ import annotations

from orgh import planner
from orgh.criteria import append_entry
from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore

from .conftest import read_ledger


def _mission(tasks):
    return Mission.new(intent="criteria_cited試験", context_digest="(test)",
                       tasks=tasks)


def _task(id: str, **kw) -> dict:
    return {"id": id, "title": f"task {id}",
            "prompt": f"作業せよ [[MARK:{id}]]",
            "worker": "claude_code", "deps": [], "workdir": ".",
            "acceptance": ["mock acceptance"], **kw}


def _fake_ask(responses: dict):
    """role名(reviewer/persona_<name>)ごとに固定応答を返す_ask_jsonの代役。"""
    def fake(cfg_, role, prompt, **kw):
        return responses[role]
    return fake


def _review_events(cfg, mission_id, task_id):
    return [e for e in read_ledger(cfg["runs_dir"], mission_id)
            if e["event"] == "task.review" and e["task"] == task_id]


def _persona_events(cfg, mission_id, task_id):
    return [e for e in read_ledger(cfg["runs_dir"], mission_id)
            if e["event"] == "task.persona_review" and e["task"] == task_id]


def _seed_criteria(cfg, tmp_path, entries):
    """entriesは (category, prefix, strength, text) のリスト。台帳に順番に
    追記し、生成されたIDのリストを返す(next_idの採番順に依存しない)。"""
    cdir = tmp_path / "criteria"
    cfg["criteria_dir"] = str(cdir)
    from orgh.criteria import next_id
    ids = []
    for category, prefix, strength, text in entries:
        line = append_entry(cdir, category, prefix, strength, text, src="seed")
        ids.append(line.split(" ")[1])
    return ids


class TestReviewerCriteriaCitedRecorded:
    def test_only_injected_ids_are_recorded(self, cfg, mock_state_dir,
                                            tmp_path, monkeypatch):
        qa1, qa2 = _seed_criteria(cfg, tmp_path, [
            ("qa", "QA", "norm", "テストを書く"),
            ("qa", "QA", "norm", "型を確認する"),
        ])
        monkeypatch.setattr(planner, "_ask_json", _fake_ask({
            "reviewer": {"pass": True, "feedback": "",
                        "criteria_cited": [qa1]},
        }))
        m = _mission([_task("r1")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "done"
        events = _review_events(cfg, m.id, "r1")
        assert len(events) == 1
        assert events[0]["criteria_cited"] == [qa1]
        assert qa2 not in events[0]["criteria_cited"]

    def test_id_not_injected_is_dropped(self, cfg, mock_state_dir,
                                        tmp_path, monkeypatch):
        (qa1,) = _seed_criteria(cfg, tmp_path, [
            ("qa", "QA", "norm", "テストを書く"),
        ])
        monkeypatch.setattr(planner, "_ask_json", _fake_ask({
            "reviewer": {"pass": True, "feedback": "",
                        "criteria_cited": [qa1, "QA-999"]},
        }))
        m = _mission([_task("r2")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "done"
        events = _review_events(cfg, m.id, "r2")
        assert len(events) == 1
        # 捏造ID(QA-999)は落ち、注入済みIDのみ残る
        assert events[0]["criteria_cited"] == [qa1]

    def test_missing_key_records_empty_list(self, cfg, mock_state_dir,
                                             tmp_path, monkeypatch):
        _seed_criteria(cfg, tmp_path, [("qa", "QA", "norm", "テストを書く")])
        monkeypatch.setattr(planner, "_ask_json", _fake_ask({
            "reviewer": {"pass": True, "feedback": ""},  # criteria_cited欠落
        }))
        m = _mission([_task("r3")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "done"
        events = _review_events(cfg, m.id, "r3")
        assert len(events) == 1
        assert events[0]["criteria_cited"] == []

    def test_no_criteria_ledger_records_empty_list(self, cfg, mock_state_dir,
                                                    tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "no-such-dir")
        monkeypatch.setattr(planner, "_ask_json", _fake_ask({
            "reviewer": {"pass": True, "feedback": "", "criteria_cited": []},
        }))
        m = _mission([_task("r4")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))

        events = _review_events(cfg, m.id, "r4")
        assert events[0]["criteria_cited"] == []


class TestPersonaCriteriaCitedRecorded:
    def _cfg(self, cfg):
        cfg["personas"] = {"enabled": ["consumer"]}
        cfg["loop"]["infra_retry_wait"] = 0
        return cfg

    def test_only_injected_ids_are_recorded(self, cfg, mock_state_dir,
                                            tmp_path, monkeypatch):
        qa1, qa2 = _seed_criteria(cfg, tmp_path, [
            ("qa", "QA", "norm", "テストを書く"),
            ("qa", "QA", "norm", "型を確認する"),
        ])
        monkeypatch.setattr(planner, "_ask_json", _fake_ask({
            "reviewer": {"pass": True, "feedback": ""},
            "persona_consumer": {"pass": True, "feedback": "",
                                 "evidence": ["shot.png"],
                                 "criteria_cited": [qa2]},
        }))
        m = _mission([_task("p1", personas=["consumer"])])
        run_mission(self._cfg(cfg), m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "done"
        events = _persona_events(cfg, m.id, "p1")
        assert len(events) == 1
        assert events[0]["criteria_cited"] == [qa2]
        assert qa1 not in events[0]["criteria_cited"]

    def test_id_not_injected_is_dropped(self, cfg, mock_state_dir,
                                        tmp_path, monkeypatch):
        (qa1,) = _seed_criteria(cfg, tmp_path, [
            ("qa", "QA", "norm", "テストを書く"),
        ])
        monkeypatch.setattr(planner, "_ask_json", _fake_ask({
            "reviewer": {"pass": True, "feedback": ""},
            "persona_consumer": {"pass": True, "feedback": "",
                                 "evidence": ["shot.png"],
                                 "criteria_cited": [qa1, "QA-FAKE-999"]},
        }))
        m = _mission([_task("p2", personas=["consumer"])])
        run_mission(self._cfg(cfg), m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "done"
        events = _persona_events(cfg, m.id, "p2")
        assert len(events) == 1
        assert events[0]["criteria_cited"] == [qa1]

    def test_missing_key_records_empty_list(self, cfg, mock_state_dir,
                                             tmp_path, monkeypatch):
        _seed_criteria(cfg, tmp_path, [("qa", "QA", "norm", "テストを書く")])
        monkeypatch.setattr(planner, "_ask_json", _fake_ask({
            "reviewer": {"pass": True, "feedback": ""},
            "persona_consumer": {"pass": True, "feedback": "",
                                 "evidence": ["shot.png"]},  # criteria_cited欠落
        }))
        m = _mission([_task("p3", personas=["consumer"])])
        run_mission(self._cfg(cfg), m, RunStore(cfg["runs_dir"], m.id))

        t = m.tasks[0]
        assert t.status == "done"
        events = _persona_events(cfg, m.id, "p3")
        assert len(events) == 1
        assert events[0]["criteria_cited"] == []

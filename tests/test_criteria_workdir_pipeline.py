"""Reviewerとペルソナ裁定へのプロジェクトcriteria workdir配管。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from orgh import planner
from orgh.criteria import criteria_context, criteria_ids
from orgh.orchestrator.scheduler import with_criteria_snapshot
from orgh.state import RunStore, Task


def _seed_project_criteria(cfg: dict, tmp_path: Path) -> str:
    cdir = tmp_path / "criteria"
    projects = cdir / "projects"
    projects.mkdir(parents=True)
    cfg["criteria_dir"] = str(cdir)
    (projects / "external-project.md").write_text(
        "- PROJECT-001 [norm]: matching project rule "
        "<!-- src:p d:2026-08-21 -->\n")
    (projects / "other-project.md").write_text(
        "- OTHER-001 [norm]: unrelated project rule "
        "<!-- src:o d:2026-08-21 -->\n")
    return str(tmp_path / "external-project")


def _task() -> Task:
    return Task(id="t1", title="review", prompt="check",
                acceptance=[], last_output="done")


def _capture_criteria_workdirs(monkeypatch):
    calls = {"context": [], "ids": []}
    real_context = planner.criteria_context
    real_ids = planner.criteria_ids

    def capture_context(cfg, max_chars=None, workdir=None):
        calls["context"].append(workdir)
        return real_context(cfg, max_chars=max_chars, workdir=workdir)

    def capture_ids(cfg, max_chars=None, workdir=None):
        calls["ids"].append(workdir)
        return real_ids(cfg, max_chars=max_chars, workdir=workdir)

    monkeypatch.setattr(planner, "criteria_context", capture_context)
    monkeypatch.setattr(planner, "criteria_ids", capture_ids)
    return calls


def test_review_uses_same_workdir_for_prompt_and_cited_id_validation(
        cfg, tmp_path, monkeypatch):
    workdir = _seed_project_criteria(cfg, tmp_path)
    captured = {}
    criteria_calls = _capture_criteria_workdirs(monkeypatch)

    def fake_ask(cfg_, role, prompt, **kwargs):
        captured["prompt"] = prompt
        return {"pass": True, "feedback": "",
                "criteria_cited": ["PROJECT-001", "OTHER-001"]}

    monkeypatch.setattr(planner, "_ask_json", fake_ask)

    result = planner.review(cfg, _task(), workdir=workdir)

    assert "PROJECT-001" in captured["prompt"]
    assert "OTHER-001" not in captured["prompt"]
    assert result[4] == ["PROJECT-001"]
    assert criteria_calls == {"context": [workdir], "ids": [workdir]}


def test_persona_review_uses_same_workdir_for_prompt_and_cited_id_validation(
        cfg, tmp_path, monkeypatch):
    workdir = _seed_project_criteria(cfg, tmp_path)
    captured = {}
    criteria_calls = _capture_criteria_workdirs(monkeypatch)

    def fake_ask(cfg_, role, prompt, **kwargs):
        captured["prompt"] = prompt
        return {"pass": True, "feedback": "", "evidence": ["artifact"],
                "criteria_cited": ["PROJECT-001", "OTHER-001"]}

    monkeypatch.setattr(planner, "_ask_json", fake_ask)
    cited = []

    result = planner.persona_review(
        cfg, "consumer", _task(), workdir=workdir,
        criteria_cited_sink=cited)

    assert result[0]
    assert "PROJECT-001" in captured["prompt"]
    assert "OTHER-001" not in captured["prompt"]
    assert cited == ["PROJECT-001"]
    assert criteria_calls == {"context": [workdir], "ids": [workdir]}


def test_snapshot_copies_project_ledger_and_injects_only_matching_slug(
        cfg, tmp_path):
    live = tmp_path / "criteria"
    projects = live / "projects"
    projects.mkdir(parents=True)
    cfg["criteria_dir"] = str(live)
    (live / "design.md").write_text(
        "- DESIGN-001 [norm]: global rule <!-- src:g d:2026-01-01 -->\n")
    target = projects / "external-project.md"
    target.write_text(
        "- PROJECT-001 [norm]: target rule <!-- src:p d:2026-02-01 -->\n")
    (projects / "other-project.md").write_text(
        "- OTHER-001 [norm]: other rule <!-- src:o d:2026-02-02 -->\n")
    store = RunStore(cfg["runs_dir"], "snapshot-project-ledger")

    snapshot_cfg = with_criteria_snapshot(cfg, store)

    copied = store.dir / "criteria" / "projects" / target.name
    assert copied.read_bytes() == target.read_bytes()
    workdir = tmp_path / "external-project"
    context = criteria_context(snapshot_cfg, workdir=workdir)
    assert "PROJECT-001" in context
    assert "OTHER-001" not in context
    assert criteria_ids(snapshot_cfg, workdir=workdir) == {
        "PROJECT-001", "DESIGN-001"}
    records = [json.loads(line) for line in
               (store.dir / "ledger.jsonl").read_text().splitlines()]
    event = next(record for record in records
                 if record["event"] == "mission.criteria_snapshot")
    assert event["hash"] == hashlib.sha256(
        b"design.md- DESIGN-001 [norm]: global rule "
        b"<!-- src:g d:2026-01-01 -->\n"
        b"projects/external-project.md- PROJECT-001 [norm]: target rule "
        b"<!-- src:p d:2026-02-01 -->\n"
        b"projects/other-project.md- OTHER-001 [norm]: other rule "
        b"<!-- src:o d:2026-02-02 -->\n"
    ).hexdigest()


def test_snapshot_without_projects_keeps_top_level_result_and_hash(
        cfg, tmp_path):
    live = tmp_path / "criteria"
    live.mkdir()
    cfg["criteria_dir"] = str(live)
    source = live / "design.md"
    source.write_text("- DESIGN-001 [norm]: top-level only\n")
    store = RunStore(cfg["runs_dir"], "snapshot-without-projects")

    snapshot_cfg = with_criteria_snapshot(cfg, store)

    snapshot = Path(snapshot_cfg["_criteria_read_dir"])
    assert (snapshot / "design.md").read_bytes() == source.read_bytes()
    assert not (snapshot / "projects").exists()
    records = [json.loads(line) for line in
               (store.dir / "ledger.jsonl").read_text().splitlines()]
    event = next(record for record in records
                 if record["event"] == "mission.criteria_snapshot")
    assert event["hash"] == hashlib.sha256(
        b"design.md- DESIGN-001 [norm]: top-level only\n"
    ).hexdigest()

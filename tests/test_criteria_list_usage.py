"""`orgh criteria list` に裁定でのcriteria引用実績を表示する。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from orgh import cli
from orgh.criteria import append_entry

from .conftest import write_config


def _write_events(runs_dir: str, mission_id: str, events: list[dict]) -> None:
    run_dir = Path(runs_dir) / mission_id
    run_dir.mkdir(parents=True)
    (run_dir / "ledger.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events))


def _run_criteria_list(cfg, tmp_path, monkeypatch, capsys, *, as_json=False) -> str:
    cfg_path = write_config(tmp_path, cfg)
    argv = ["orgh", "--config", str(cfg_path), "criteria", "list"]
    if as_json:
        argv.append("--json")
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()
    return capsys.readouterr().out


def test_criteria_list_shows_citation_count_and_last_date(
        cfg, tmp_path, monkeypatch, capsys):
    cfg["criteria_dir"] = str(tmp_path / "criteria")
    line = append_entry(Path(cfg["criteria_dir"]), "qa", "QA", "norm",
                        "実物を確認する", src="seed")
    criterion_id = line.split()[1]
    older = datetime(2026, 8, 14, 23, 59, tzinfo=timezone.utc).timestamp()
    newer = datetime(2026, 8, 16, 0, 1, tzinfo=timezone.utc).timestamp()
    _write_events(cfg["runs_dir"], "mission-a", [
        {"ts": older, "event": "task.review",
         "criteria_cited": [criterion_id, criterion_id]},
        {"ts": newer + 1, "event": "task.start",
         "criteria_cited": [criterion_id]},
    ])
    _write_events(str(Path(cfg["runs_dir"]) / "_archive"), "mission-old", [
        {"ts": newer, "event": "task.persona_review",
         "criteria_cited": [criterion_id]},
    ])

    out = _run_criteria_list(cfg, tmp_path, monkeypatch, capsys)

    lines = out.splitlines()
    criterion_index = next(i for i, line in enumerate(lines)
                           if line.startswith(f"- {criterion_id} "))
    assert lines[criterion_index - 1] == (
        f"<!-- id:{criterion_id} 引用回数:2 最終引用日:2026-08-16 -->")
    assert "引用回数" not in lines[criterion_index]

    payload = json.loads(_run_criteria_list(
        cfg, tmp_path, monkeypatch, capsys, as_json=True))
    entry = next(entry for entry in payload["entries"]
                 if entry["id"] == criterion_id)
    assert entry["citation_count"] == 2
    assert entry["last_cited_date"] == "2026-08-16"


def test_criteria_list_shows_zero_and_dash_for_uncited_criterion(
        cfg, tmp_path, monkeypatch, capsys):
    cfg["criteria_dir"] = str(tmp_path / "criteria")
    line = append_entry(Path(cfg["criteria_dir"]), "qa", "QA", "pref",
                        "前提を確認する", src="seed")
    criterion_id = line.split()[1]

    out = _run_criteria_list(cfg, tmp_path, monkeypatch, capsys)

    lines = out.splitlines()
    criterion_index = next(i for i, line in enumerate(lines)
                           if line.startswith(f"- {criterion_id} "))
    assert lines[criterion_index - 1] == (
        f"<!-- id:{criterion_id} 引用回数:0 最終引用日:- -->")
    assert "引用回数" not in lines[criterion_index]

    payload = json.loads(_run_criteria_list(
        cfg, tmp_path, monkeypatch, capsys, as_json=True))
    entry = next(entry for entry in payload["entries"]
                 if entry["id"] == criterion_id)
    assert entry["citation_count"] == 0
    assert entry["last_cited_date"] is None

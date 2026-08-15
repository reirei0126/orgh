"""criteria台帳のミッション固定スナップショット。"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from orgh.criteria import append_entry, criteria_context, criteria_dir
from orgh.orchestrator import run_mission
from orgh.orchestrator.scheduler import with_criteria_snapshot
from orgh.state import Mission, RunStore


def _mission(workdir: Path) -> Mission:
    return Mission.new(
        intent="criteria snapshot test",
        context_digest="(test)",
        tasks=[{
            "id": "t1", "title": "snapshot task", "prompt": "作業せよ",
            "worker": "claude_code", "deps": [],
            "acceptance": ["完了する"], "workdir": str(workdir),
        }],
    )


def _write_live_criteria(cfg: dict, root: Path, content: str) -> Path:
    cfg["criteria_dir"] = str(root / "criteria")
    live = Path(cfg["criteria_dir"])
    live.mkdir(parents=True, exist_ok=True)
    (live / "design.md").write_text(content)
    return live


def test_mission_start_copies_criteria_and_logs_hash(
        cfg, mock_state_dir, tmp_path):
    live = _write_live_criteria(
        cfg, tmp_path, "- DESIGN-001 [norm]: snapshot content\n")
    (live / "architecture.md").write_bytes(b"architecture\n")
    mission = _mission(tmp_path / "workdir")
    store = RunStore(cfg["runs_dir"], mission.id)

    run_mission(cfg, mission, store)

    snap = store.dir / "criteria"
    assert snap.is_dir()
    assert (snap / "design.md").read_bytes() == (live / "design.md").read_bytes()
    assert (snap / "architecture.md").read_bytes() == b"architecture\n"
    records = [json.loads(line) for line in
               (store.dir / "ledger.jsonl").read_text().splitlines()]
    events = [record for record in records
              if record["event"] == "mission.criteria_snapshot"]
    assert events
    assert isinstance(events[0].get("hash"), str)
    expected = hashlib.sha256(
        b"architecture.mdarchitecture\n"
        b"design.md- DESIGN-001 [norm]: snapshot content\n"
    ).hexdigest()
    assert events[0]["hash"] == expected


def test_context_stays_fixed_after_live_criteria_edit(cfg, tmp_path):
    live = _write_live_criteria(
        cfg, tmp_path, "- DESIGN-001 [norm]: before snapshot\n")
    store = RunStore(cfg["runs_dir"], "snapshot-context")
    snapshot_cfg = with_criteria_snapshot(cfg, store)

    before = criteria_context(snapshot_cfg)
    (live / "design.md").write_text(
        "- DESIGN-001 [norm]: after snapshot\n")

    assert criteria_context(snapshot_cfg) == before
    assert "before snapshot" in before
    assert "after snapshot" not in before


def test_append_entry_ignores_criteria_read_snapshot(cfg, tmp_path):
    live = _write_live_criteria(
        cfg, tmp_path, "- OPS-001 [pref]: live entry\n")
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "ops.md").write_text("- OPS-001 [pref]: snapshot entry\n")
    snapshot_cfg = {**cfg, "_criteria_read_dir": str(snapshot)}

    append_entry(criteria_dir(snapshot_cfg), "ops", "OPS", "pref",
                 "new live entry", "mission-1")

    assert "new live entry" in (live / "ops.md").read_text()
    assert "new live entry" not in (snapshot / "ops.md").read_text()


def test_copy_failure_preserves_previous_snapshot_and_falls_back(
        cfg, tmp_path, monkeypatch, capsys):
    live = _write_live_criteria(cfg, tmp_path, "old content\n")
    store = RunStore(cfg["runs_dir"], "snapshot-copy-failure")
    first_cfg = with_criteria_snapshot(cfg, store)
    snap = Path(first_cfg["_criteria_read_dir"])
    assert (snap / "design.md").read_text() == "old content\n"

    (live / "design.md").write_text("new content\n")
    (live / "second.md").write_text("unreadable\n")
    original_read_bytes = Path.read_bytes

    def fail_second(path: Path) -> bytes:
        if path.name == "second.md":
            raise OSError("simulated copy failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_second)
    fallback_cfg = with_criteria_snapshot(cfg, store)

    assert fallback_cfg is cfg
    assert (snap / "design.md").read_text() == "old content\n"
    assert not (snap / "second.md").exists()
    assert "[warn]" in capsys.readouterr().out

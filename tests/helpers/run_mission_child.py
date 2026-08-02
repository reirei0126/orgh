"""kill -9 試験用の子プロセス: spec JSONを読んでミッションを実行する。

usage: python run_mission_child.py <spec.json>
spec = {"cfg": {...}, "mission_id": "...", "tasks": [...]}
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orgh.orchestrator import run_mission          # noqa: E402
from orgh.state import Mission, RunStore, Task     # noqa: E402


def main() -> None:
    spec = json.loads(Path(sys.argv[1]).read_text())
    cfg = spec["cfg"]
    mission = Mission(
        id=spec["mission_id"],
        intent="kill -9 試験",
        context_digest="(test)",
        tasks=[Task(**t) for t in spec["tasks"]],
    )
    store = RunStore(cfg["runs_dir"], mission.id)
    run_mission(cfg, mission, store)


if __name__ == "__main__":
    main()

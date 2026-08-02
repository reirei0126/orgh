"""orgh CLI
  orgh watch                      # vault監視デーモン: ノート投稿で自動着火
  orgh scan                       # vaultからミッション候補を一覧
  orgh run --note "ノート名"       # ノート起点でplan->execute->review->retro全部
  orgh run --intent "..."         # ノートなしで直接指示
  orgh resume <mission_id>        # 中断ミッション再開
  orgh status <mission_id>
  orgh cleanup <mission_id>       # worktree/ブランチの掃除(worktree.enabled時)
"""
from __future__ import annotations

import argparse
import sys

from . import ingest, planner, watcher
from .orchestrator import run_mission
from .state import RunStore, load_config
from . import worktree


def main() -> None:
    ap = argparse.ArgumentParser(prog="orgh")
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scan")
    sub.add_parser("watch")

    runp = sub.add_parser("run")
    runp.add_argument("--note")
    runp.add_argument("--intent")
    runp.add_argument("--no-retro", action="store_true")

    for name in ("resume", "status", "cleanup"):
        sp = sub.add_parser(name)
        sp.add_argument("mission_id")
        if name == "resume":
            sp.add_argument("--retry-failed", action="store_true")

    args = ap.parse_args()
    cfg = load_config(args.config)

    if args.cmd == "watch":
        watcher.watch(cfg)
        return

    if args.cmd == "scan":
        cands, _ = ingest.scan_vault(cfg["vault"]["path"],
                                     cfg["vault"].get("inbox", "inbox"),
                                     cfg["vault"].get("mission_tag", "mission"))
        for n in cands:
            print(f"- {n.title}  ({n.path})")
        return

    if args.cmd == "run":
        if args.note:
            cands, index = ingest.scan_vault(cfg["vault"]["path"])
            note = index.get(args.note) or next(
                (n for n in cands if args.note.lower() in n.title.lower()), None)
            if not note:
                sys.exit(f"note '{args.note}' not found")
            intent = args.intent or f"ノート「{note.title}」の内容を実行可能な成果に落とし込む"
            digest = ingest.build_context_digest(note, index)
        else:
            if not args.intent:
                sys.exit("--note か --intent のどちらかは必須")
            intent, digest = args.intent, "(no vault context)"

        print("== planning ==")
        mission = planner.plan(cfg, intent, digest)
        store = RunStore(cfg.get("runs_dir", "runs"), mission.id)
        print(f"mission {mission.id}: {len(mission.tasks)} tasks")
        for t in mission.tasks:
            print(f"  - {t.id} [{t.worker}] {t.title} deps={t.deps}")

        print("== executing ==")
        mission = run_mission(cfg, mission, store)

        if not args.no_retro:
            print("== retro ==")
            fp = planner.retro(cfg, mission)
            print(f"playbook updated: {fp or '(no lessons)'}")
        _summary(mission)
        return

    store = RunStore(cfg.get("runs_dir", "runs"), args.mission_id)
    mission = store.load()
    if args.cmd == "status":
        _summary(mission)
    elif args.cmd == "cleanup":
        for line in worktree.cleanup_mission_worktrees(mission):
            print(line)
    else:  # resume
        if getattr(args, "retry_failed", False):
            for t in mission.tasks:
                if t.status == "failed":
                    t.status, t.attempts = "pending", 0
        mission = run_mission(cfg, mission, store)
        _summary(mission)


def _summary(m) -> None:
    print(f"\nmission {m.id}: {m.intent}")
    for t in m.tasks:
        mark = {"done": "✓", "failed": "✗"}.get(t.status, "…")
        print(f"  {mark} {t.title} [{t.status}] attempts={t.attempts}")


if __name__ == "__main__":
    main()

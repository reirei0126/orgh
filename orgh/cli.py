"""orgh CLI
  orgh watch                      # vault監視デーモン: ノート投稿で自動着火
  orgh scan                       # vaultからミッション候補を一覧
  orgh run --note "ノート名"       # ノート起点でplan->execute->review->retro全部
  orgh run --intent "..."         # ノートなしで直接指示
  orgh resume <mission_id>        # 中断・キャンセルしたミッションの再開
  orgh status <mission_id>
  orgh cancel <mission_id>        # 実行中subprocessをterminateし未着手をcancelledに
  orgh approve <mission_id>       # 自己改変ガードで停止したミッションを承認して続行
  orgh cleanup <mission_id>       # worktree/ブランチの掃除(worktree.enabled時)
  orgh doctor                     # 外部CLI疎通・config・vault・書き込み権限の確認
  orgh gc                         # playbookの統合・退避とruns/のアーカイブ
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import doctor, gc, planner, report, watcher
from .orchestrator import run_mission
from .sources.base import get_source
from .state import RunStore, load_config
from .status_json import status_payload
from . import worktree


def main() -> None:
    ap = argparse.ArgumentParser(prog="orgh")
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scan")
    sub.add_parser("watch")
    sub.add_parser("doctor")
    sub.add_parser("gc")

    rp = sub.add_parser("report")
    rp.add_argument("--days", type=int)
    rp.add_argument("--vault", action="store_true")

    runp = sub.add_parser("run")
    runp.add_argument("--note")
    runp.add_argument("--intent")
    runp.add_argument("--no-retro", action="store_true")

    for name in ("resume", "status", "cleanup", "cancel", "approve"):
        sp = sub.add_parser(name)
        sp.add_argument("mission_id")
        if name == "resume":
            sp.add_argument("--retry-failed", action="store_true")
        if name == "status":
            sp.add_argument("--json", action="store_true")

    args = ap.parse_args()
    cfg = load_config(args.config)

    if args.cmd == "watch":
        watcher.watch(cfg)
        return

    if args.cmd == "doctor":
        lines, ok = doctor.run_doctor(cfg)
        for line in lines:
            print(line)
        if not ok:
            sys.exit(1)
        return

    if args.cmd == "gc":
        for line in gc.run_gc(cfg):
            print(line)
        return

    if args.cmd == "scan":
        src = get_source(cfg)
        for n in src.list_candidates():
            print(f"- {n.title}  ({n.path})")
        return

    if args.cmd == "report":
        out = report.build_report(cfg, days=args.days)
        print(out)
        if args.vault:
            d = Path(cfg["vault"]["path"]).expanduser() / "orgh" / "reports"
            d.mkdir(parents=True, exist_ok=True)
            fp = d / f"{datetime.now():%Y-%m-%d}.md"
            fp.write_text(out)
            print(f"report written: {fp}")
        return

    if args.cmd == "run":
        if args.note:
            src = get_source(cfg)
            note = src.find(args.note)
            if not note:
                sys.exit(f"note '{args.note}' not found")
            intent = args.intent or f"ノート「{note.title}」の内容を実行可能な成果に落とし込む"
            digest = src.build_context(note)
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
            store.save(mission)
            (store.dir / "RETRO_DONE").touch()
            print(f"playbook updated: {fp or '(no lessons)'}")
        _summary(mission)
        return

    store = RunStore(cfg.get("runs_dir", "runs"), args.mission_id)
    mission = store.load()
    if args.cmd == "status":
        if args.json:
            print(json.dumps(status_payload(mission), ensure_ascii=False, indent=2))
            return
        _summary(mission)
    elif args.cmd == "cleanup":
        for line in worktree.cleanup_mission_worktrees(mission):
            print(line)
    elif args.cmd == "approve":
        # 自己改変ガードの解除はこのコマンドのみ(watcher/configからは不可)
        (store.dir / "APPROVED").touch()
        for t in mission.tasks:
            if t.status == "awaiting_approval":
                t.status = "pending"
        print(f"mission {mission.id} を承認した。実行を続行する")
        mission = run_mission(cfg, mission, store)
        _summary(mission)
    elif args.cmd == "cancel":
        # フラグが唯一の停止信号: 実行中プロセス側がループごとに検知して
        # subprocessをterminateする。ここでは未着手をcancelledに確定するだけ
        (store.dir / "CANCEL").touch()
        for t in mission.tasks:
            if t.status == "pending":
                t.status = "cancelled"
        store.save(mission)
        print(f"mission {mission.id} にCANCELフラグを置いた。"
              f"実行中のプロセスがあればまもなく停止する")
        _summary(mission)
    else:  # resume
        (store.dir / "CANCEL").unlink(missing_ok=True)  # cancel後の再開
        for t in mission.tasks:
            if t.status in ("cancelled", "skipped"):
                t.status, t.attempts = "pending", 0
        if getattr(args, "retry_failed", False):
            for t in mission.tasks:
                if t.status == "failed":
                    t.status, t.attempts = "pending", 0
        mission = run_mission(cfg, mission, store)
        _maybe_retro(cfg, mission, store)
        _summary(mission)


def _maybe_retro(cfg: dict, mission, store: RunStore) -> None:
    """resume完走時のretro。run/watcher経路と違いresumeは従来retroを呼ばず、
    resumeで完走したミッションの教訓がplaybookに残らなかった(実運用7307189eで
    発見)。RETRO_DONEマーカーで再resume時の二重追記を防ぐ。"""
    marker = store.dir / "RETRO_DONE"
    if marker.exists() or not mission.tasks or \
            not all(t.status == "done" for t in mission.tasks):
        return
    print("== retro ==")
    fp = planner.retro(cfg, mission)
    store.save(mission)
    marker.touch()
    print(f"playbook updated: {fp or '(no lessons)'}")


def _summary(m) -> None:
    print(f"\nmission {m.id}: {m.intent}")
    for t in m.tasks:
        mark = {"done": "✓", "failed": "✗", "cancelled": "⊘",
                "skipped": "⊘"}.get(t.status, "…")
        print(f"  {mark} {t.title} [{t.status}] attempts={t.attempts}")
    b = getattr(m, "budget", None)
    if b and b.spent_usd:
        line = f"  cost: {b.spent_usd:.4f} USD"
        if b.limit_usd:
            line += f" / budget {b.limit_usd} USD ({b.spent_usd / b.limit_usd * 100:.0f}%)"
        print(line)


if __name__ == "__main__":
    main()

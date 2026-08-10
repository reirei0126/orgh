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
  orgh list                       # runs配下の全ミッションをid/intent/状態/コストで一覧
  orgh events <mission_id>        # ミッションのledger.jsonlをイベントとして表示
  orgh verdict <mission_id> --pass|--fail --reason <text>  # オーナー裁定の記録と基準蒸留
  orgh criteria                   # 判断基準台帳の下書き確認・承認・却下
  orgh report --days N            # 週次合格率・ミッション別コスト・worker別失敗率
  orgh playbooks                  # playbooks/配下の教訓(Retro追記分)を表示
  # 上記の list/doctor/events/status/report/playbooks は --json で機械可読出力
  # (GUI連携用)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from . import doctor, gc, listing, planner, report, watcher
from .criteria import (approve_draft, criteria_context, distill_verdict,
                       list_drafts, reject_draft)
from .events_json import events_payload
from .orchestrator import run_mission
from .playbooks_json import playbooks_payload
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
    dp = sub.add_parser("doctor")
    dp.add_argument("--json", action="store_true")
    sub.add_parser("gc")
    lp = sub.add_parser("list")
    lp.add_argument("--json", action="store_true")

    ep = sub.add_parser("events")
    ep.add_argument("mission_id")
    ep.add_argument("--json", action="store_true")
    ep.add_argument("--tail", type=int, default=100)

    rp = sub.add_parser("report")
    rp.add_argument("--days", type=int)
    rp.add_argument("--vault", action="store_true")
    rp.add_argument("--json", action="store_true")

    pp = sub.add_parser("playbooks")
    pp.add_argument("--json", action="store_true")

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

    vp = sub.add_parser("verdict")   # オーナー検収裁定の記録と基準蒸留
    vp.add_argument("mission_id")
    g = vp.add_mutually_exclusive_group(required=True)
    g.add_argument("--pass", dest="passed", action="store_true")
    g.add_argument("--fail", dest="passed", action="store_false")
    vp.add_argument("--reason", required=True)

    cp = sub.add_parser("criteria")
    cp.add_argument("action", choices=["list", "approve", "reject"])
    cp.add_argument("name", nargs="?")

    args = ap.parse_args()
    try:
        cfg = load_config(args.config)
    except Exception as e:
        if args.cmd == "doctor":
            # 設定が壊れているときこそdoctorが原因を報告できないと意味がない。
            # configチェックNGのDoctorReportとして返す(GUIのSettings画面もこれに依存)
            payload = {"ok": False, "checks": [{
                "name": "config", "ok": False,
                "detail": f"{type(e).__name__}: {e}",
                "kind": "connectivity", "auth_state": "n/a"}]}
            if getattr(args, "json", False):
                print(json.dumps(payload, ensure_ascii=False))
            else:
                print(f"NG config — {type(e).__name__}: {e}")
            sys.exit(1)
        raise

    if args.cmd == "watch":
        watcher.watch(cfg)
        return

    if args.cmd == "doctor":
        if args.json:
            payload = doctor.doctor_payload(cfg)
            print(json.dumps(payload, ensure_ascii=False))
            if not payload["ok"]:
                sys.exit(1)
            return
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
        if args.json:
            payload = report.report_payload(cfg, days=args.days)
            print(json.dumps(payload, ensure_ascii=False))
            return
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
        # GUI等がpipe越しに購読するため行バッファリングに依存せず即時flushする
        print(f"ORGH_MISSION_ID={mission.id}", flush=True)
        for t in mission.tasks:
            print(f"  - {t.id} [{t.worker}] {t.title} deps={t.deps}")

        print("== executing ==")
        mission = run_mission(cfg, mission, store)

        if not args.no_retro:
            # 承認待ちで停止したミッションを未完了のままretroしない(決着時のみ)
            planner.retro_if_finished(cfg, mission, store)
        _summary(mission)
        return

    if args.cmd == "list":
        payload = listing.list_missions_report(cfg.get("runs_dir", "runs"))
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
            return
        missions = payload["missions"]
        if not missions:
            print("no missions")
        else:
            for m in missions:
                print(f"{m['mission_id']}  [{m['status']}]  "
                      f"{m['tasks_done']}/{m['tasks_total']} tasks  "
                      f"{m['cost_usd']:.4f} USD  {m['intent']}")
        for s in payload["skipped"]:
            print(f"! 読めないmission.jsonをスキップ: {s['path']} ({s['reason']})",
                  file=sys.stderr)
        return

    if args.cmd == "events":
        runs_dir = cfg.get("runs_dir", "runs")
        mission_dir = Path(runs_dir) / args.mission_id
        if not mission_dir.is_dir():
            msg = f"mission '{args.mission_id}' not found"
            if args.json:
                print(json.dumps({"error": msg}, ensure_ascii=False))
                sys.exit(1)
            sys.exit(msg)
        payload = events_payload(runs_dir, args.mission_id, tail=args.tail)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
            return
        for ev in payload["events"]:
            rest = {k: v for k, v in ev.items() if k not in ("ts", "event")}
            print(f"{ev.get('ts')}  {ev.get('event')}  {rest}")
        return

    if args.cmd == "verdict":
        store = RunStore(cfg.get("runs_dir", "runs"), args.mission_id)
        mission = store.load(reset_inflight=False)  # 読むだけ。実行状態は触らない
        with open(store.dir / "verdicts.jsonl", "a") as f:
            f.write(json.dumps({"ts": time.time(), "passed": args.passed,
                                "reason": args.reason}, ensure_ascii=False) + "\n")
        store.log("mission.owner_verdict", passed=args.passed,
                  reason=args.reason[:500])
        drafts = distill_verdict(cfg, args.mission_id, mission.intent,
                                 args.passed, args.reason)
        for fp in drafts:
            print(f"draft: {fp}")
        print(f"下書き{len(drafts)}件。orgh criteria list で確認、"
              f"orgh criteria approve <name> で本台帳へ反映")
        return

    if args.cmd == "criteria":
        if args.action == "list":
            for fp in list_drafts(cfg):
                print(f"[draft] {fp.stem}: {fp.read_text()}")
            print("--- 台帳 ---")
            print(criteria_context(cfg, max_chars=100000))
            return
        if not args.name:
            raise SystemExit("approve/reject には name が必要(orgh criteria list で確認)")
        if args.action == "approve":
            print(approve_draft(cfg, args.name))
        else:
            print(f"rejected -> {reject_draft(cfg, args.name)}")
        return

    if args.cmd == "playbooks":
        payload = playbooks_payload(cfg)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
            return
        if not payload["playbooks"]:
            print("no playbooks")
        else:
            for pb in payload["playbooks"]:
                print(f"## {pb['name']}  ({pb['path']})")
                for e in pb["entries"]:
                    tag = f"  [m:{e['mission_id']} d:{e['date']}]" \
                        if e["mission_id"] else ""
                    print(f"- {e['text']}{tag}")
        return

    store = RunStore(cfg.get("runs_dir", "runs"), args.mission_id)
    # status/cleanupは読み取り専用: 実行中ステータスの巻き戻し(クラッシュ復旧用)を
    # 適用すると、動いているタスクをpendingと偽って表示してしまう。
    # cancelも巻き戻さない: running→pending→cancelledと保存すると、まだ動いている
    # タスクを終端表示に偽装し、直後に実行側の保存でdone/failedへ再変化する
    mission = store.load(reset_inflight=args.cmd not in ("status", "cleanup", "cancel"))
    if args.cmd == "status":
        if args.json:
            print(json.dumps(status_payload(mission), ensure_ascii=False, indent=2))
            return
        _summary(mission)
    elif args.cmd == "cleanup":
        for line in worktree.cleanup_mission_worktrees(mission):
            print(line)
    elif args.cmd == "approve":
        # 自己改変ガードの解除はこのコマンドのみ(watcher/configからは不可)。
        # 承認待ちタスクが無いのにAPPROVEDを先置きするとガード発火前のミッションを
        # 素通しできてしまうため、対象がある場合しか承認させない(二重承認もここで弾く)。
        # 判定〜APPROVED作成〜確認行出力は実行ロック内で行う: ロック外だと同時承認の
        # 双方が確認行を出してGUIに二重成功が見え、片方だけ実行時に競合死する
        from .orchestrator import acquire_mission_lock
        lock_fp = acquire_mission_lock(store)
        if lock_fp is None:
            sys.exit(f"mission {mission.id} は別プロセスが実行中。承認を中止する")
        mission = store.load()  # ロック取得後に再読込(先行プロセスの結果を見る)
        waiting = [t for t in mission.tasks if t.status == "awaiting_approval"]
        if not waiting:
            sys.exit(f"mission {mission.id} に承認待ちタスクが無い"
                     f"(承認済み・実行中・またはガード未発火)。承認を中止する")
        (store.dir / "APPROVED").touch()
        for t in waiting:
            t.status = "pending"
        store.save(mission)
        # GUI(spawn_and_bridge)が承認受理を機械的に検知するための確認行。
        # これより前にsys.exitする失敗は「承認されなかった」として扱われる
        print(f"ORGH_APPROVED={mission.id}", flush=True)
        print(f"mission {mission.id} を承認した。実行を続行する", flush=True)
        mission = run_mission(cfg, mission, store, lock_fp=lock_fp)
        # run/watch経路と違いapprove完走時にretroが走らないギャップの解消
        # (決着時のみ・RETRO_DONEで二重防止)
        planner.retro_if_finished(cfg, mission, store)
        _sync_results_note(cfg, mission, store)
        _summary(mission)
    elif args.cmd == "cancel":
        # フラグが唯一の停止信号: 実行中プロセス側がループごとに検知して
        # subprocessをterminateする。ここでは未着手をcancelledに確定するだけ
        (store.dir / "CANCEL").touch()
        for t in mission.tasks:
            # awaiting_approvalは実行プロセスが既に終了しているため、ここで
            # 確定させないと永遠に承認待ち表示のまま残る
            if t.status in ("pending", "awaiting_approval"):
                t.status = "cancelled"
        store.save(mission)
        print(f"mission {mission.id} にCANCELフラグを置いた。"
              f"実行中のプロセスがあればまもなく停止する")
        _sync_results_note(cfg, mission, store)
        _summary(mission)
    else:  # resume
        # 実行ロックを先に取得する。CANCEL削除をロック外で行うと、まだ動いている
        # 実行プロセスへのキャンセル信号をresumeが握り潰してしまう
        # (キャンセル直後・停止完了前のresumeで実測しうる競合)
        from .orchestrator import acquire_mission_lock
        lock_fp = acquire_mission_lock(store)
        if lock_fp is None:
            sys.exit(f"mission {mission.id} は別プロセスが実行中"
                     f"(停止待ちの可能性)。停止を確認してから再実行すること")
        mission = store.load()  # ロック取得後に再読込(実行側の最終保存を見る)
        (store.dir / "CANCEL").unlink(missing_ok=True)  # cancel後の再開
        for t in mission.tasks:
            if t.status in ("cancelled", "skipped"):
                t.status, t.attempts = "pending", 0
        if getattr(args, "retry_failed", False):
            for t in mission.tasks:
                if t.status == "failed":
                    t.status, t.attempts = "pending", 0
        store.save(mission)
        # GUI(spawn_and_bridge)がresume受理を機械的に検知するための確認行。
        # ロック取得・状態復元より前にsys.exitした場合は「再開されなかった」扱い
        print(f"ORGH_RESUMED={mission.id}", flush=True)
        mission = run_mission(cfg, mission, store, lock_fp=lock_fp)
        # resume完走時のretro(実運用7307189eで発見したギャップ)。resumeは
        # 再試行経路なので全doneのときだけretroする(失敗時にRETRO_DONEを
        # 置くと、後の再resume完走時の真の教訓が阻まれる)
        planner.retro_if_finished(cfg, mission, store, only_if_all_done=True)
        _sync_results_note(cfg, mission, store)
        _summary(mission)


def _sync_results_note(cfg: dict, mission, store: RunStore) -> None:
    """CLI操作(cancel/approve/resume)後にvaultの結果ノートを追従させる。

    watcherは承認待ちや完走の時点でノートをfinalizeして終了するため、その後の
    CLI操作による状態変化はここで反映しないとObsidian側が古い状態のまま残る。
    ノートはvault経由ミッションにしか存在しないので、既存の場合だけ更新する。"""
    try:
        if not (cfg.get("vault") or {}).get("path"):
            return
        from .results import ResultsNote
        note = ResultsNote(cfg, mission.id)
        if not note.path.exists():
            return
        terminal = ("done", "failed", "cancelled", "skipped")
        if mission.tasks and all(t.status in terminal for t in mission.tasks):
            note.finalize(mission, store)
        else:
            note.update(mission)
    except Exception as e:
        print(f"結果ノートの更新に失敗(処理は続行): {e!r}", file=sys.stderr)


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

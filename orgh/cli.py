"""orgh CLI
  orgh watch                      # vault監視デーモン: ノート投稿で自動着火
  orgh scan                       # vaultからミッション候補を一覧
  orgh run --note "ノート名"       # ノート起点でplan->execute->review->retro全部
  orgh run --intent "..."         # ノートなしで直接指示
  orgh resume <mission_id>        # 中断・キャンセルしたミッションの再開
  orgh status <mission_id>
  orgh cancel <mission_id>        # 実行中subprocessをterminateし未着手をcancelledに
  orgh approve <mission_id>       # 自己改変ガードで停止したミッションを承認して続行
  orgh humandone <mission_id> <task_id> --note "..."  # 人間対応待ちタスクの完了報告
  orgh cleanup <mission_id>       # worktree/ブランチの掃除(worktree.enabled時)
  orgh doctor                     # 外部CLI疎通・config・vault・書き込み権限の確認
  orgh gc                         # playbookの統合・退避とruns/のアーカイブ
  orgh list                       # runs配下の全ミッションをid/intent/状態/コストで一覧
  orgh events <mission_id>        # ミッションのledger.jsonlをイベントとして表示
  orgh verdict <mission_id> --pass|--fail --reason <text>  # オーナー裁定の記録と基準蒸留
  orgh criteria                   # 判断基準台帳の下書き確認・承認・却下
  orgh report --days N            # 週次合格率・ミッション別コスト・worker別失敗率
  orgh playbooks                  # playbooks/配下の教訓(Retro追記分)を表示
  # 上記の list/doctor/events/status/report/playbooks/criteria list は --json で
  # 機械可読出力(GUI連携用)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from . import doctor, gc, listing, planner, report, watcher
from .criteria import (approve_draft, criteria_context, criteria_list_payload,
                       distill_verdict, list_drafts, reject_draft)
from .events_json import events_payload
from .orchestrator import run_mission
from .playbooks_json import playbooks_payload
from .sources.base import get_source
from .state import TERMINAL, RunStore, load_config
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
        if name == "approve":
            sp.add_argument("--yes", action="store_true")

    vp = sub.add_parser("verdict")   # オーナー検収裁定の記録と基準蒸留
    vp.add_argument("mission_id")
    g = vp.add_mutually_exclusive_group(required=True)
    g.add_argument("--pass", dest="passed", action="store_true")
    g.add_argument("--fail", dest="passed", action="store_false")
    vp.add_argument("--reason", required=True)

    hd = sub.add_parser("humandone")  # awaiting_human タスクの人間完了報告
    hd.add_argument("mission_id")
    hd.add_argument("task_id")
    hd.add_argument("--note", required=True)

    cp = sub.add_parser("criteria")
    cp.add_argument("action", choices=["list", "approve", "reject"])
    cp.add_argument("name", nargs="?")
    cp.add_argument("--json", action="store_true")

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
        _summary(mission, store)
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
            def _dt(ts):
                return (datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
                        if ts else "--")
            for m in missions:
                print(f"{m['mission_id']}  [{m['status']}]  "
                      f"起票 {_dt(m['created_ts'])}  "
                      f"完了 {_dt(m['finished_ts'])}  "
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

    if args.cmd == "humandone":
        # awaiting_human タスクの完了報告: --note を人間の成果物として
        # 通常のReviewerに掛ける(worker成果と同様の扱い)。approve/resumeと
        # 同じくミッション実行ロックを取ってから状態を変える(二重発行防止)
        from .orchestrator import acquire_mission_lock
        store = RunStore(cfg.get("runs_dir", "runs"), args.mission_id)
        lock_fp = acquire_mission_lock(store)
        if lock_fp is None:
            sys.exit(f"mission {args.mission_id} は別プロセスが実行中。"
                     f"完了報告を中止する")
        mission = store.load()  # ロック取得後に再読込(実行側の最終保存を見る)
        task = next((t for t in mission.tasks if t.id == args.task_id), None)
        if task is None:
            lock_fp.close()
            sys.exit(f"task '{args.task_id}' が mission {args.mission_id} に"
                     f"見つからない")
        if task.status != "awaiting_human":
            lock_fp.close()
            sys.exit(f"task '{args.task_id}' は awaiting_human ではない"
                     f"(現在: {task.status})。完了報告を中止する")

        task.last_output = args.note
        store.log("task.human_report", task=task.id, note=args.note[:500])
        cost_sink: list[float] = []
        passed, feedback = planner.review(
            cfg, task, workdir=task.workdir, budget=mission.budget,
            registry_key=store.dir.name, cost_sink=cost_sink)
        task.cost_usd += sum(cost_sink)
        task.review_notes = feedback
        store.log("task.review", task=task.id, passed=passed)

        if passed:
            commit = worktree.commit_task_result(task, store.dir.name)
            if commit:
                store.log("task.committed", task=task.id, commit=commit)
            task.status = "done"
            task.human_request = ""
            store.save(mission)
            print(f"task {task.id} を検収した(人間の完了報告に基づくレビュー合格)")
            mission = run_mission(cfg, mission, store, lock_fp=lock_fp)
            planner.retro_if_finished(cfg, mission, store)
            _sync_results_note(cfg, mission, store)
            _summary(mission, store)
            return

        # 不合格: 人間には再試行回数の上限を設けない(HUMAN:転換と同型)。
        # feedbackが"HUMAN:"ならその理由を、そうでなくても通常のreview feedback
        # をそのまま「なぜ人間が必要か」として再度依頼書を作る
        reason = (feedback[len("HUMAN:"):].strip() if feedback.startswith("HUMAN:")
                  else feedback or "レビューで差し戻された。再度対応せよ")
        brief, body = planner.build_human_request(mission.id, task, reason)
        task.status = "awaiting_human"
        task.human_request = brief
        store.artifact(f"human_request_{task.id}.md", body)
        store.log("task.awaiting_human", task=task.id, brief=brief)
        store.save(mission)
        lock_fp.close()
        print(f"task {task.id} の完了報告はレビューで差し戻された — {brief}")
        _summary(mission, store)
        return

    if args.cmd == "criteria":
        if args.action == "list":
            if args.json:
                print(json.dumps(criteria_list_payload(cfg), ensure_ascii=False))
                return
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
            print(json.dumps(status_payload(mission, cfg), ensure_ascii=False, indent=2))
            return
        _summary(mission, store)
    elif args.cmd == "cleanup":
        for line in worktree.cleanup_mission_worktrees(mission):
            print(line)
        # cleanupが削除したworktree/branch参照の除去をmission.jsonへ永続化する
        # (保存しないと後続resumeが古い参照で孤立リポを再作成する)
        store.save(mission)
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

        # PROD-001: 承認接点は「何を承認するか」を一文(summary)で先に提示し、
        # 詳細(対象タスク一覧)はその下に展開する。これより後段の確認行
        # (ORGH_APPROVED=)より必ず前に出す
        brief = status_payload(mission, cfg).get("approval_brief")
        if brief:
            print(brief["summary"])
            for t in brief["gated_tasks"]:
                print(f"  - {t['title']}  ({t['workdir']})")

        # --yesが無くTTY接続時のみ対話確認する。watch/GUI(非TTY)や--yes指定は
        # 従来どおり即続行(後方互換優先。ブリーフは表示済み)
        if not args.yes and sys.stdin.isatty():
            ans = input("承認して実行する? [y/N]: ")
            if ans.strip().lower() != "y":
                print("承認を中止した")
                sys.exit(0)

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
        _summary(mission, store)
    elif args.cmd == "cancel":
        # フラグが唯一の停止信号: 実行中プロセス側がループごとに検知して
        # subprocessをterminateする。フラグ設置は常に行う。
        (store.dir / "CANCEL").touch()
        # 状態の確定は実行ロックが取れたとき(=executorが走っていない)だけ行う。
        # ロックを取らずにload→mutate→saveすると、executorの最終保存を古い
        # スナップショットで上書きし、完了タスクをrunning表示のまま固定してしまう
        from .orchestrator import acquire_mission_lock
        lock_fp = acquire_mission_lock(store)
        if lock_fp is None:
            print(f"mission {mission.id} にCANCELフラグを置いた。"
                  f"実行中プロセスが検知してまもなく停止する"
                  f"(状態の確定は実行側に委ねる)")
        else:
            try:
                # reset_inflight=False: 実行中(running/review)タスクはここで
                # 触らず実行側の最終確定に委ねる。cancelが確定するのは未着手系のみ
                mission = store.load(reset_inflight=False)
                for t in mission.tasks:
                    # 実行プロセスは居ないので、未着手・承認待ちをここで確定する
                    if t.status in ("pending", "awaiting_approval",
                                    "awaiting_human"):
                        t.status = "cancelled"
                store.save(mission)
            finally:
                lock_fp.close()
            print(f"mission {mission.id} にCANCELフラグを置き、未着手を"
                  f"cancelledに確定した")
        _sync_results_note(cfg, mission, store)
        _summary(mission, store)
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
        _summary(mission, store)


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
        if mission.tasks and all(t.status in TERMINAL for t in mission.tasks):
            note.finalize(mission, store)
        else:
            note.update(mission)
    except Exception as e:
        print(f"結果ノートの更新に失敗(処理は続行): {e!r}", file=sys.stderr)


def _summary(m, store: RunStore | None = None) -> None:
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

    # PROD-001: 承認ブリーフ(approveコマンド、上のbrief["summary"]出力)と同様、
    # まず依頼一文を一行で示し、詳細(依頼書artifact)と完了報告コマンドを続ける
    for t in m.tasks:
        if t.status != "awaiting_human":
            continue
        print(f"\n  🙋 {t.human_request}")
        artifact = (store.dir / "artifacts" / f"human_request_{t.id}.md"
                    if store is not None else f"artifacts/human_request_{t.id}.md")
        print(f"     依頼書: {artifact}")
        print(f"     完了したら: orgh humandone {m.id} {t.id} --note \"実施内容の要約\"")


if __name__ == "__main__":
    main()

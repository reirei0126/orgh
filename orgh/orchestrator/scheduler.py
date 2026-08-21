"""MissionScheduler: DAG解決と並列dispatch、ミッション実行のライフサイクル
(プロセス間ロック・promptsスナップショット・キャンセル/予算停止の起動・
自己改変ガード・人間依頼タスクの停止)。"""
from __future__ import annotations

import fcntl
import hashlib
import shutil
import time
from pathlib import Path
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .. import lease, listing, notify
from ..guard import needs_approval
from ..state import TERMINAL, Mission, RunStore, Task
from .budget_policy import initiate_budget_stop, setup_budget
from .cancellation import cancel_flag, initiate_cancel
from .sleep_recovery import detect_sleep_gap, reclaim_hung_workers
from .task_executor import run_task
from .transitions import enter_awaiting_human, transition

# キャンセル検知のポーリング間隔(秒)。タスク完了イベントもこの粒度で拾う
POLL_INTERVAL = 0.5


def ready(m: Mission) -> list[Task]:
    done = {t.id for t in m.tasks if t.status == "done"}
    return [t for t in m.tasks
            if t.status == "pending" and all(d in done for d in t.deps)]


def blocked_forever(m: Mission) -> bool:
    dead = {t.id for t in m.tasks if t.status in ("failed", "cancelled")}
    pend = [t for t in m.tasks if t.status == "pending"]
    return bool(dead) and all(
        any(d in dead for d in t.deps) for t in pend) if pend else False


def assign_personas(cfg: dict, mission: Mission) -> None:
    """final_task(誰のdepsにも現れないタスク)へ検収ペルソナを割り当てる。
    Plannerが明示指定したタスクは尊重して上書きしない。"""
    enabled = (cfg.get("personas") or {}).get("enabled") or []
    if not enabled:
        return
    dep_ids = {d for t in mission.tasks for d in t.deps}
    for t in mission.tasks:
        if t.id not in dep_ids and not t.personas:
            t.personas = list(enabled)


def acquire_mission_lock(store: RunStore):
    """ミッション実行のプロセス間ロック(flock)を非ブロッキングで取得する。

    取得できなければNone。返したファイルオブジェクトを保持している間ロックが
    生き、close(またはプロセス終了・クラッシュ)で自動解放される。
    approveのように「承認の受理宣言と実行開始を同一ロック内で行う」必要がある
    呼び出し元は、先にこれを取得してから run_mission に渡す。
    """
    fp = open(store.dir / ".run.lock", "w")
    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fp
    except OSError:
        fp.close()
        return None


def with_prompts_snapshot(cfg: dict, store: RunStore) -> dict:
    """prompts/をミッション専用スナップショットへ差し替えたcfgを返す。

    コードとconfigはプロセス起動時に固定される一方、prompts/は毎回ディスクから
    読まれる。長時間ミッションの実行中にmainが進むと「古いコード×新しい
    プロンプト」の版ずれが起き、新プレースホルダでformatがKeyError死する
    (mission eceb49cbのreviewerがKeyError('criteria')で死んだ実例)。
    実行開始・resumeの時点(=プロセスのコードと確実に整合する時点)の
    prompts/を runs/<id>/prompts/ へ写し、以後はそれだけを読む。
    resumeのたびに上書きするのは、resumeプロセスは現行コードで動くため
    「その時点のライブ版」と揃えるのが正しいから。
    副次効果: どのプロンプトで実行されたかがミッション記録に残る。
    """
    src = Path(cfg.get("prompts_dir", "prompts")).expanduser()
    dst = store.dir / "prompts"
    try:
        if not src.is_dir():
            return cfg
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        store.log("mission.prompts_snapshot", src=str(src))
    except OSError as e:
        print(f"  [warn] prompts/スナップショット作成に失敗、ライブ版を使用: {e!r}")
        return cfg
    # 注意: prompts_dir自体は差し替えない(自己改変ガードがcfg["prompts_dir"]を
    # 保護対象パスとして参照するため)。読み取り先のみ別キーで上書きする
    return {**cfg, "_prompts_read_dir": str(dst)}


def with_criteria_snapshot(cfg: dict, store: RunStore) -> dict:
    """criteria/をミッション専用スナップショットへ差し替えたcfgを返す。

    コードとconfigはプロセス起動時に固定される一方、criteria/はReviewer・
    ペルソナへの注入のたびにディスクから読まれる。長時間ミッションやresume中に
    本台帳が変わると、同じ成果物が別基準で裁定されても監査できない。
    実行開始・resumeの時点(=プロセスのコードと確実に整合する時点)の
    criteria/*.mdを runs/<id>/criteria/ へ写し、以後はそれだけを読む。
    resumeのたびに上書きするのは、resumeプロセスは現行コードで動くため
    「その時点のライブ版」と揃えるのが正しいから。
    副次効果: どの判断基準で裁定されたかがミッション記録に残る。
    """
    src = Path(cfg.get("criteria_dir", "criteria")).expanduser()
    dst = store.dir / "criteria"
    tmp = store.dir / ".criteria.snapshot.tmp"
    try:
        if not src.is_dir():
            print("  [warn] criteria/スナップショット作成に失敗、ライブ版を使用: "
                  f"台帳ディレクトリが存在しない: {src}")
            return cfg
        files = sorted(src.glob("*.md"), key=lambda p: p.name)
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        digest = hashlib.sha256()
        for fp in files:
            content = fp.read_bytes()
            digest.update(fp.name.encode())
            digest.update(content)
            (tmp / fp.name).write_bytes(content)
        if dst.exists():
            shutil.rmtree(dst)
        tmp.rename(dst)
        store.log("mission.criteria_snapshot", src=str(src),
                  hash=digest.hexdigest())
    except OSError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"  [warn] criteria/スナップショット作成に失敗、ライブ版を使用: {e!r}")
        return cfg
    # 注意: criteria_dir自体は差し替えない(自己改変ガードがcfg["criteria_dir"]を
    # 保護対象パスとして参照するため)。読み取り先のみ別キーで上書きする
    return {**cfg, "_criteria_read_dir": str(dst)}


def run_mission(cfg: dict, mission: Mission, store: RunStore,
                on_update=None, poll_cancel=None, lock_fp=None) -> Mission:
    """同一ミッションの二重実行防止(GUI/CLI/watchの経路をまたぐプロセス間ロック)
    を掛けてから実行本体へ。lock_fpに取得済みロックを渡された場合はそれを引き継ぐ
    (いずれの場合も終了時にcloseして解放する)。"""
    if lock_fp is None:
        lock_fp = acquire_mission_lock(store)
        if lock_fp is None:
            store.log("mission.lock_conflict")
            raise SystemExit(
                f"mission {mission.id} は別プロセスが実行中(approve/resume/watchの"
                f"二重発行の可能性)。二重実行を中止する")
    try:
        cfg = with_prompts_snapshot(cfg, store)
        cfg = with_criteria_snapshot(cfg, store)
        return _run_mission_locked(cfg, mission, store, on_update, poll_cancel)
    finally:
        lock_fp.close()  # closeでflockも解放される


def _run_mission_locked(cfg: dict, mission: Mission, store: RunStore,
                        on_update=None, poll_cancel=None) -> Mission:
    workers = cfg.get("loop", {}).get("parallel", 3)
    budget = setup_budget(cfg, mission)
    assign_personas(cfg, mission)
    store.save(mission)
    store.artifact("context_digest.md", mission.context_digest)
    # plan lint(orgh/planner.py lint_plan)が再計画後も違反を確定させたまま
    # 計画を通した場合のゲート: workerを一切起動させず、pendingの全タスクを
    # awaiting_humanへ落として停止する(dispatchループへ入る前に必ず通す)。
    # plan_lint_violationsが空なら以下は何もしない(挙動不変)
    if mission.plan_lint_violations:
        reason = (
            "plan lintが計画の規範違反を検出したまま確定した: "
            + "; ".join(mission.plan_lint_violations)
            + "。計画をレビューして orgh resume で続行するか、"
              "ノートを直して再起票すること")
        for t in mission.tasks:
            if t.status == "pending":
                enter_awaiting_human(store, cfg, t, reason)
    # 永続lease(orgh/lease.py): 実行開始時に起動世代を取得し、以後
    # HEARTBEAT_INTERVAL_SECごとに更新する。再起動後の他プロセス(GUI/CLI)が
    # 「表示上は実行中系のタスクの背後で本当にプロセスが生きているか」を
    # 判定できるようにする(RunStore.load(reset_inflight=True)が参照する)
    lease.acquire(store.dir)
    last_heartbeat = time.time()
    cancelling = False
    budget_stopped = False
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        while True:
            now = time.time()
            # スリープ復帰検知(H0①, outcome-2026-08.md §3.3): heartbeatが
            # 更新されないまま実測経過した秒数がlease.LEASE_EXPIRY_SECを大幅に
            # 超えていたら、GC一時停止等では説明のつかないwall-clockの飛び
            # (Macスリープ復帰)とみなす。heartbeat更新(直後の分岐)より前に
            # 判定することで、飛び幅を正しく計測してから基準時刻をリセットする
            gap = detect_sleep_gap(now, last_heartbeat)
            if gap is not None:
                reclaim_hung_workers(cfg, store, mission, futures, gap)
            if now - last_heartbeat >= lease.HEARTBEAT_INTERVAL_SEC:
                lease.heartbeat(store.dir, now=now)
                last_heartbeat = now
            if not cancelling and (
                    cancel_flag(store).exists()
                    or (poll_cancel and poll_cancel())):
                cancelling = True
                initiate_cancel(mission, store)
            if not cancelling and not budget_stopped and budget.exceeded():
                budget_stopped = True
                initiate_budget_stop(mission, store, budget)
            if not cancelling and not budget_stopped:
                for t in ready(mission):
                    if t.id in futures:
                        continue
                    # 自己改変ガード: orgh自身を指すworkdirは承認なしに実行しない
                    # (watcher経由でもスキップ不可。configでも無効化不可)。
                    # decision_gates(人間判断が必要な値)ゲート: mission.decision_gates
                    # が非空のうちはAPPROVEDが置かれるまで同様に停止する(方向性文書
                    # 2026-08 §9)。両ガードはAPPROVED作成で同時に解除される点で
                    # 自己改変ガードと同じ仕組みを共有するが、理由は別物のため
                    # ledgerのpayloadを混同させない(自己改変ガード発火時は従来どおり
                    # workdirのみ、decision_gates単独発火時のみreasonを足す)
                    self_mod = needs_approval(cfg, t.workdir)
                    gates_pending = bool(mission.decision_gates)
                    if not (store.dir / "APPROVED").exists() and (
                            self_mod or gates_pending):
                        extra = {} if self_mod else {"reason": "decision_gates"}
                        transition(store, t, "awaiting_approval",
                                   event="task.awaiting_approval",
                                   workdir=t.workdir, **extra)
                        store.log("owner.interrupt", kind="approval_requested",
                                  task=t.id,
                                  detail=extra.get("reason") or t.workdir)
                        print(f"  [awaiting_approval] {t.title} — "
                              f"orgh approve {store.dir.name} で続行")
                        try:
                            event = notify.approval_requested_event(
                                cfg, store.dir.name, t)
                            notify.emit(store, cfg, event)
                        except Exception:
                            pass  # 通知処理の失敗でミッション進行を止めない
                        continue
                    # worker: "human"(人間依頼): サブプロセスを一切起動せず、
                    # 依頼書を生成してawaiting_humanで停止する。poolにsubmitしない
                    # ため futures には入らず、後続の「if not futures: break」が
                    # 依存タスクだけが残った状態でミッションを自然に終了させる
                    # (blocked_forever改修は不要: awaiting_humanは"dead"扱いに
                    # せず、依存タスクはreadyの既存規則どおりpendingのまま残る)
                    if t.worker == "human":
                        reason = ("Plannerがこのタスクをworker: human"
                                  "(人間依頼)として計画した。headlessなAI"
                                  "ワーカーでは恒常的に実行不能と判断された作業")
                        enter_awaiting_human(store, cfg, t, reason)
                        continue
                    transition(store, t, "queued")
                    futures[t.id] = pool.submit(run_task, cfg, store, t,
                                                budget)
            if not futures:
                break
            done, _ = wait(list(futures.values()), timeout=POLL_INTERVAL,
                           return_when=FIRST_COMPLETED)
            for fut in done:
                finished = fut.result()
                futures = {k: v for k, v in futures.items() if v is not fut}
                store.save(mission)
                if on_update:
                    on_update(mission)
                print(f"  [{finished.status}] {finished.title}")
            if not done:
                continue
            if all(t.status in TERMINAL for t in mission.tasks) and not futures:
                break
            if blocked_forever(mission) and not futures:
                break
    store.save(mission)
    lease.release(store.dir)
    # 完了直前(最後のタスクのdone確定後)に届いたCANCELは、もう止める対象が
    # 無いため完了扱いになる。残存する数ms級の競合窓は仕様として受容し、
    # 「キャンセルは間に合わなかった」ことをledgerに明示して観測可能にする
    if cancel_flag(store).exists() and not cancelling and \
            all(t.status in TERMINAL for t in mission.tasks):
        store.log("mission.cancel_too_late")
    store.log("mission.finished",
              done=[t.id for t in mission.tasks if t.status == "done"],
              failed=[t.id for t in mission.tasks if t.status == "failed"],
              cancelled=[t.id for t in mission.tasks
                         if t.status == "cancelled"])
    try:
        # 未裁定件数はorgh verdict --pending(A1out)と同じ判定ロジックを再利用する
        # (二重定義しない)。ここでの取得失敗も通知全体と同様に進行を止めない
        pending = listing.list_pending_verdicts(
            cfg.get("runs_dir", "runs"))["missions"]
        event = notify.mission_completed_event(
            mission, pending_verdict_count=len(pending))
        notify.emit(store, cfg, event)
    except Exception:
        pass  # 通知処理の失敗でミッション進行を止めない
    return mission

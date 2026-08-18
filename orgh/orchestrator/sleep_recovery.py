"""スリープ復帰検知とハングworkerの自動回収(H0①, outcome-2026-08.md §3.3)。

背景(実害): 2026-08-17 ミッションae3ee54a t2実行中にMacがスリープし、
`claude -p` のworker subprocessがネットワーク接続を握ったまま応答を返さなく
なった。subprocess.communicate(timeout=...)のタイムアウトはmonotonic clockで
計測されるためスリープ中は進まず、復帰後もexecutorには効かない。8時間の
無進捗を人手のkillで回収した実運用がある。

契約(outcome-2026-08.md §3.3・direction-2026-08.md §7 A5): schedulerの
heartbeatループ(orgh/orchestrator/scheduler.py)が唯一wall-clockの飛びを
観測できる地点であることを利用し、heartbeat未更新の実測経過が
lease.LEASE_EXPIRY_SEC(既存定数、変更しない)を大きく超えたら『スリープ
復帰』と判定する。回収対象は「workerプロセスが死亡している」場合のみに
厳格に限定する: 生存中のworkerには一切触れず、タスクブランチにコミット
済み成果がある・判定が曖昧な場合は自動回収せず人間確認に委ねる(A5契約:
判別不能をpending/failedへ丸めない。迷ったら回収しない)。

人間確認への委ね方について(2026-08-19 レビュー差し戻しで修正): 当初
Task.status へ文字列 "unknown" を直接書き込んでいたが、これはorghの既存
契約(tests/test_unknown_status.py が固定)を破る。"unknown" は生タスク
ステータス(queued/running/review)+leaseの失効から**表示時に導出するだけ**
の値であり(orgh/listing.py・orgh/status_json.py・orgh/cli.py の
`_INFLIGHT_TASK_STATUSES`、orgh/state.py の `TERMINAL` のいずれにも含まれ
ない)、Task.status へ実際に書き込まれることは無い前提で全体が設計されて
いる。書き込んでしまうと `orgh list`/`status`/`doctor` の判定条件を素通り
し、ミッションが永久に running と誤表示され続ける(実機確認で発覚)。
そのため、既に全経路(orgh list/status/doctor、CLI `orgh humandone`)が
表示・復旧に対応済みの **awaiting_human** 状態(orgh/orchestrator/
transitions.py の enter_awaiting_human)を再利用する。人間は `orgh status`
でブランチの状況を確認し、`orgh humandone <mission> <task> --note "..."`
で成果を活かす/破棄するといった判断をレビュアーへ渡して復旧できる。

スレッド境界の受け渡し: schedulerループ(検知側)とThreadPoolExecutorの
workerスレッド(subprocess所有側、orgh/orchestrator/task_executor.py)は
別スレッドであり、workerスレッドはproc.communicate()でブロックされている
間チェックポイントを一切通過できない。誤った二重実行(schedulerが次
attemptを始めた後、いつか目覚めた古いスレッドが同じtaskへ書き込む)を防ぐ
ため、cancellation.py の CANCEL フラグと同じ「ファイルの有無を両スレッドが
ポーリングする」設計を踏襲し、タスク単位のreclaimフラグファイルを新設した
(procregはmission単位/タスク単位の集合を保持できるが「既に外部で確定済み」
という事後通知の手段は持たないため、既存のフラグファイル方式の方が素直に
馴染む)。フラグの中身にattempt番号を書き込み、対応する攻撃対象の
attemptだけが自分を止める・以降のattemptには影響しないようにしている。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .. import lease, procreg
from ..state import Mission, RunStore, Task
from .transitions import enter_awaiting_human, transition

# スリープ復帰判定のしきい値(秒)。lease.LEASE_EXPIRY_SEC(120秒、既存定数は
# 変更しない・流用のみ)の5倍を採る。HEARTBEAT_INTERVAL_SEC(30秒)ごとに
# 打つheartbeatがこれを超えて更新されないのは、GC一時停止・CPU過負荷では
# 説明がつかない規模であり(LEASE_EXPIRY_SEC自体が既にその種の一時的遅延を
# 吸収する設計になっている)、2026-08-17実運用(8時間無進捗)を踏まえて
# Macスリープ復帰以外に説明がつかないと判断する
SLEEP_GAP_SEC = lease.LEASE_EXPIRY_SEC * 5


def _git(workdir, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(workdir), *args],
                          capture_output=True, text=True)


def task_registry_key(mission_id: str, task_id: str) -> str:
    """procregへタスク単位で登録するためのキー。orgh cancelが使うmission単位
    のキー(mission_idそのもの)と衝突しないよう区切り文字を挟む。"""
    return f"{mission_id}::{task_id}"


def reclaim_flag_path(store: RunStore, task_id: str) -> Path:
    """このタスクの『いま在るattempt』がscheduler側で確定済み(reclaim/
    awaiting_humanのいずれか)であることを、後から目覚めるworkerスレッドへ
    伝える印。
    中身はattempt番号の文字列で、対応するattemptのスレッドだけが自分を
    止める(古いフラグが後続attemptを誤って止めない)。"""
    return store.dir / f".reclaimed_{task_id}"


def was_reclaimed(store: RunStore, task_id: str, attempt: int) -> bool:
    """attempt_loop側のチェックポイントから呼ぶ。このattemptが既に
    scheduler側で確定済みなら True(呼び出し元はそれ以上何も書かず即returnする)。"""
    p = reclaim_flag_path(store, task_id)
    try:
        return p.read_text().strip() == str(attempt)
    except (OSError, ValueError):
        return False


def _mark_reclaimed(store: RunStore, task: Task) -> None:
    reclaim_flag_path(store, task.id).write_text(str(task.attempts))


def _has_committed_work(t: Task, wt_cfg: dict) -> bool | None:
    """タスクブランチに、分岐元(base_ref)より先のコミットが積まれているかを
    判定する。非worktree運用・gitエラー等の判定不能はNone(呼び出し側は
    『曖昧』としてawaiting_humanへ委ねる)。

    base_refをworktree(t.workdir)側で素朴に解決すると、worktree内での
    "HEAD" は常にタスクブランチ自身の先端を指す自己参照になり
    (rev-list HEAD..HEAD は常に0)判定として無意味になる。そのため
    base_refは主リポ側(git-common-dirの親)で解決し、
    merge-base(タスクブランチ, base_ref)をタスクブランチの分岐点として
    採用してからworktree側でrev-listする(worktree.pyのcleanup_mission_
    worktreesが主リポ特定に使っているのと同じ手法)。
    """
    if not t.branch or not Path(t.workdir).exists():
        return None
    common = _git(t.workdir, "rev-parse", "--path-format=absolute",
                  "--git-common-dir")
    if common.returncode != 0:
        return None
    main_repo = Path(common.stdout.strip()).parent
    base_ref = wt_cfg.get("base_ref", "HEAD")
    mb = _git(main_repo, "merge-base", t.branch, base_ref)
    if mb.returncode != 0:
        return None
    fork_point = mb.stdout.strip()
    rl = _git(t.workdir, "rev-list", "--count", f"{fork_point}..HEAD")
    if rl.returncode != 0:
        return None
    try:
        return int(rl.stdout.strip()) > 0
    except ValueError:
        return None


def detect_sleep_gap(now: float, last_heartbeat: float) -> float | None:
    """heartbeatループから毎周呼ぶ。飛びが無ければNone。"""
    gap = now - last_heartbeat
    return gap if gap >= SLEEP_GAP_SEC else None


def reclaim_hung_workers(cfg: dict, store: RunStore, mission: Mission,
                         futures: dict, gap: float) -> None:
    """スリープ復帰を検知した直後に1回だけ呼ぶ。実行中(running)タスクごとに
    worker生死を確認し、死亡かつ未コミットの場合のみ、いま在るattemptを
    失敗として確定させ次のattemptへ進められる状態(pending/failed)にする。
    死亡していてもコミット済み成果がある・判定が曖昧な場合は自動回収せず
    awaiting_human(orgh humandoneで人間が復旧できる既存導線)へ委ねる。
    生存中のworkerには一切手を触れない(A5契約: 迷ったら回収しない)。"""
    store.log("sleep.detected", gap_seconds=round(gap, 1))
    wt_cfg = cfg.get("worktree") or {}
    lcfg = cfg.get("loop", {})
    max_attempts = lcfg.get("max_attempts", 3)
    for t in mission.tasks:
        if t.status != "running":
            continue
        pids = procreg.pids(task_registry_key(store.dir.name, t.id))
        if not pids:
            continue  # workerを特定できない(枠待ち・phase遷移中等)。何もしない
        if any(lease.pid_alive(p) for p in pids):
            continue  # 生存・進捗中とみなし何もしない(A5契約: 迷ったら回収しない)

        has_commit = _has_committed_work(t, wt_cfg)
        if has_commit is not False:
            # コミット済み成果がある、または判定不能(git不明・非worktree等)
            # → 自動回収せず、既存のawaiting_human導線(orgh humandoneで
            # 復旧できる・orgh list/status/doctorが正しく表示する)へ委ねる
            # (理由はモジュールdocstring参照: Task.statusへ生の"unknown"を
            # 書くと既存の表示・復旧経路をすべて素通りしてしまう)。ただし
            # 後から目覚めるworkerスレッドが上書きしないよう、先にreclaim
            # フラグを立てておく
            _mark_reclaimed(store, t)
            reason_kind = "has_committed_work" if has_commit else "judgement_ambiguous"
            store.log("task.sleep_ambiguous", task=t.id, pids=pids,
                      gap_seconds=round(gap, 1), reason=reason_kind)
            enter_awaiting_human(
                store, cfg, t,
                (f"スリープ復帰検知({gap:.0f}秒の無更新)でworker(pid={pids})"
                 f"の死亡を確認したが、タスクブランチ({t.branch})に"
                 + ("コミット済み成果がある" if has_commit
                    else "成果物の状態を機械判定できない")
                 + "ため自動回収せず人間確認が必要。ブランチの内容を確認し、"
                   "成果を活かせるかどうかの判断を `orgh humandone` の"
                   "--note で伝えること"),
                refund_attempt=True)
            continue

        # 死亡確定 + 未コミット: 安全に回収してよい
        _mark_reclaimed(store, t)
        next_status = "pending" if t.attempts < max_attempts else "failed"
        transition(store, t, next_status,
                  notes=(f"スリープ復帰検知({gap:.0f}秒の無更新)によりworker"
                         f"(pid={pids})の死亡を確認、attempt{t.attempts}を"
                         f"失敗として回収した"),
                  event="worker.reclaimed", pids=pids,
                  gap_seconds=round(gap, 1), next_status=next_status)
        futures.pop(t.id, None)

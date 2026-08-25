"""TaskExecutor: 1タスクのattemptループ。worker起動・インフラリトライ・
検収裁定の反映(retry/REPLAN/HUMAN)・合格成果のタスクブランチへのコミット。
task: pending -> running -> review -> done / (feedback付きで再実行) -> failed
Claude Codeタスクは session_id を保持し --resume でフィードバックを渡す(文脈を捨てない)。
"""
from __future__ import annotations

import re
import subprocess
import time
import traceback
from pathlib import Path

from ..adapters.base import get_adapter
from ..planner import replan_task, worker_prompt
from ..state import Budget, RunStore, Task
from ..slots import SlotAborted, acquire_slot
from ..worktree import commit_task_result, ensure_task_worktree
from . import copyback_gate, sleep_recovery
from .cancellation import CancelledDuringRole, cancel_flag, cancellable_sleep
from .review_pipeline import run_review_pipeline
from .transitions import enter_awaiting_human, transition

# インフラ(ネットワーク・接続)起因のエラー署名。workerの失敗ではないため
# attemptを消費せずにリトライする(実運用7307189e t5: ネットワーク断で
# 3attempt≒6.4USD相当を浪費した事例への対処)。署名は実際に観測されたものを登録する
INFRA_ERROR_RE = re.compile(
    r"Request timed out"               # claude CLI(t5 attempt1/2で実測)
    r"|Unable to connect to API"       # claude CLI(t5 attempt3で実測)
    r"|Connection closed mid-response" # claude CLI(7307189e t1初回で実測)
    r"|ENOTFOUND|ECONNREFUSED|ECONNRESET|ETIMEDOUT|EAI_AGAIN"
    r"|fetch failed",
)
# 注: BaseAdapter.run の task_timeout マーカー("timeout")は対象外。
# あれは「詰まったworker」の可能性があり、attempt非消費で粘ると無限に待つため
# 従来どおりattemptを消費する通常failure扱いにする


def is_infra_error(output: str) -> bool:
    return bool(INFRA_ERROR_RE.search(output or ""))


# 権限起因の失敗署名。CLIサンドボックス側の非対話承認待ちはworkerでは解消
# 不能な環境側の制約であり、retry/レビュー(LLM判断)に回しても直らないため
# 機械的にawaiting_humanへ回す(実運用b6503b9a t3: 読み取り専用gitコマンドが
# 承認待ちのまま完了せず、3ターン浪費した末にReviewerのHUMAN:判断で人間へ
# 転換された事例。runs/b6503b9a/artifacts/t3_attempt1.md・t3_attempt2.md で
# "This command requires approval" を実測)。署名は実際に観測されたものだけ
# 登録する(誤検知はawaiting_humanの濫発に直結する)
CAPABILITY_ERROR_RE = re.compile(
    r"This command requires approval",  # claude CLI(b6503b9a t3で実測)
)


def is_capability_error(output: str) -> bool:
    return bool(CAPABILITY_ERROR_RE.search(output or ""))


# 差し戻し昇格の順序(モデル未指定タスクには適用しない。opusは終端で昇格なし)
_MODEL_ESCALATION = {"haiku": "sonnet", "sonnet": "opus"}


def run_task(cfg: dict, store: RunStore, t: Task, budget: Budget) -> Task:
    """最外周の薄いラッパ: 実処理(attempt_loop)の全例外を1タスクのfailedに閉じ込め、
    ミッション全体を道連れにしない。"""
    try:
        return attempt_loop(cfg, store, t, budget)
    except Exception as e:
        # キャンセルのterminateが引き起こした例外(replan中のplanner死など)は
        # failedではなくcancelled: failedにすると通常resumeで復元されない
        if cancel_flag(store).exists() or isinstance(e, CancelledDuringRole):
            transition(store, t, "cancelled",
                       event="task.cancelled_during_role", error=repr(e)[:300])
            return t
        transition(store, t, "failed", notes=f"internal error: {e!r}",
                   event="task.error", error=repr(e),
                   trace=traceback.format_exc()[-2000:])
        return t


def retry_prompt(adapter, cfg: dict, t: Task, followup: str) -> str:
    """再試行プロンプトの構築。セッションresumeできるworkerはフィードバックのみで
    よい(セッションが文脈を保持する)が、できないworker(codex等)は元タスクの
    文脈を全て失うため、タスク一式(preamble込み)+追記の自己完結形にする。
    実運用7307189e t3で発見: 断片だけ受けたcodexが実装せず確認質問を返して失敗した。"""
    if adapter.supports_resume:
        return followup
    # 非resume workerの再実行はworker_promptを丸ごと再構築するため、worktree
    # 厳守preambleもここで再付与しないと初回以降落ちる(retry/REPLANで
    # worktree外へ書き成果が失われる。mission 02a434adの退行)
    return f"{full_worker_prompt(cfg, t)}\n\n## 再実行の指示\n{followup}"


def full_worker_prompt(cfg: dict, t: Task) -> str:
    """worker_promptに、worktree実行時の作業場所厳守preambleを付けた完全版。
    初回・retry・REPLAN後の全経路がこれを使い、preambleの付け忘れを防ぐ。"""
    prompt = worker_prompt(cfg, t)
    if t.branch:
        # Plannerがタスク指示に主リポの絶対パスを書くと、workerがworktree外へ
        # 成果物を書いて自動コミットから漏れる(mission 02a434ad t1/t2で実測)
        prompt = (
            f"【作業場所の厳守】このタスクの作業ディレクトリは専用worktree "
            f"{t.workdir} である。以降の指示に他のディレクトリパスが書かれて"
            f"いても、ファイルの新規作成・編集は必ずこのworktree内で行うこと"
            f"(worktree外に書いた成果物は自動コミットの対象外となり失われる)。"
            f"git show等での他ブランチ・他パスの読み取り参照は行ってよい。\n\n"
            + prompt)
    return prompt


def ensure_workdir(store: RunStore, t: Task, wt_cfg: dict) -> None:
    """新規プロジェクト用にPlannerが計画したworkdirが未作成だと、worker subprocess
    の起動がFileNotFoundErrorで即死する(mission eceb49cbで実測)。ディレクトリを
    作成し、worktree運用時はgitリポとして初期化する(worktree addは初回コミットが
    無いと失敗するため空コミットまで行う)。"""
    wd = Path(t.workdir)
    if wd.exists():
        return
    wd.mkdir(parents=True, exist_ok=True)
    store.log("task.workdir_created", task=t.id, workdir=str(wd))
    print(f"  [workdir] {t.workdir} を新規作成した(新規プロジェクト)")
    if wt_cfg.get("enabled"):
        subprocess.run(["git", "-C", str(wd), "init", "-q", "-b", "main"],
                       check=False, capture_output=True)
        subprocess.run(["git", "-C", str(wd),
                        "-c", "user.name=orgh", "-c", "user.email=orgh@local",
                        "commit", "-q", "--allow-empty",
                        "-m", "orgh: 新規プロジェクト初期化"],
                       check=False, capture_output=True)


def attempt_loop(cfg: dict, store: RunStore, t: Task, budget: Budget) -> Task:
    wt_cfg = cfg.get("worktree") or {}
    ensure_workdir(store, t, wt_cfg)
    if wt_cfg.get("enabled"):
        got = ensure_task_worktree(wt_cfg, store.dir.name, t)
        if got:
            path, branch = got
            with store.lock:
                t.workdir, t.branch = str(path), branch
            store.log("task.worktree", task=t.id, path=str(path), branch=branch)

    # タスク単位のmodel指定(Planner明示)をworker起動へ通す(HANDOFF後続)。
    # t.model が None のタスクは effective_model も常にNoneのままで、
    # get_adapter(model=None)は既存cfgをそのまま渡すため挙動は完全不変。
    # codexアダプタはmodel引数をargvへ通す口が無いため、指定があっても
    # 無視してledgerに1回だけ記録し、argv/実行は既定のまま続行する。
    effective_model = t.model
    if t.worker == "codex" and effective_model is not None:
        store.log("task.model_ignored", task=t.id, worker=t.worker,
                  model=effective_model)

    def _adapter_for(model: str | None):
        return get_adapter(t.worker, cfg["workers"],
                           model=None if t.worker == "codex" else model)

    adapter = _adapter_for(effective_model)
    # A2限定版(方向性文書2026-08 §3.1): 注入したcapability_allowlistを監査記録する。
    # 「そのタスクに何が許可されていたか」を事後追跡できるようにするための記録
    # であって、セキュリティ保証ではない(orgh/adapters/base.py build_allowed_tools参照)
    capability_allowlist = cfg["workers"].get(t.worker, {}).get(
        "capability_allowlist")
    if capability_allowlist:
        store.log("task.capability_allowlist", task=t.id, worker=t.worker,
                  patterns=list(capability_allowlist))
    lcfg = cfg.get("loop", {})
    max_attempts = lcfg.get("max_attempts", 3)
    infra_max = lcfg.get("infra_max_retries", 3)
    infra_wait = lcfg.get("infra_retry_wait", 60)
    infra_retries = 0
    flag = cancel_flag(store)

    prompt = full_worker_prompt(cfg, t)
    while t.attempts < max_attempts:
        if flag.exists():
            transition(store, t, "cancelled")
            return t
        # グローバル枠(R-2): 全orghプロセス横断のworker同時数上限。枠待ちの間は
        # attemptを消費せずstatusもqueuedのまま。スロットはworker実行中のみ保持し、
        # 後続のreviewer/persona(roles別枠)には持ち越さない
        slot_wait_t0 = time.time()
        try:
            with acquire_slot(cfg.get("runs_dir", "runs"),
                              lcfg.get("global_parallel"),
                              pool="workers", should_abort=flag.exists):
                waited = time.time() - slot_wait_t0
                if waited >= 1.0:
                    # 枠待ちを観測可能にする(非FIFOのため長い待機が起こりうる)
                    store.log("task.slot_wait", task=t.id,
                              seconds=round(waited, 1))
                with store.lock:
                    t.attempts += 1
                    t.status = "running"
                my_attempt = t.attempts
                store.log("task.start", task=t.id, worker=t.worker,
                          attempt=t.attempts, model=effective_model)
                res = adapter.run(prompt, workdir=t.workdir,
                                  resume=t.session_id,
                                  timeout=lcfg.get("task_timeout", 3600),
                                  registry_key=store.dir.name,
                                  task_key=sleep_recovery.task_registry_key(
                                      store.dir.name, t.id),
                                  allowed_tools=t.tools)
        except SlotAborted:
            # 枠待ち中のキャンセル。attemptは未消費のままcancelledで確定
            transition(store, t, "cancelled")
            return t
        if sleep_recovery.was_reclaimed(store, t.id, my_attempt):
            # スリープ復帰検知(sleep_recovery.reclaim_hung_workers)がscheduler
            # スレッド側で既にこのattemptを失敗確定・次attemptへ進めている。
            # 目覚めたこのスレッドが同じattemptへ二重に書き込むと、既に次の
            # attemptが走っている場合に状態を破壊しうるため、以降の状態変更
            # (last_output/session_id/cost/ledger/レビュー遷移)を一切行わず
            # 即座に抜ける(誤った二重実行の防止。cancellation.pyのCANCEL
            # フラグと同じ「両スレッドがファイルをポーリングする」設計)
            return t
        with store.lock:
            t.last_output = res.output
            t.session_id = res.session_id or t.session_id
            t.cost_usd += res.cost_usd or 0.0
        budget.charge(res.cost_usd)
        store.artifact(f"{t.id}_attempt{t.attempts}.md", res.output)
        store.log("task.output", task=t.id, ok=res.ok, cost=res.cost_usd)

        # タスク上限超過: 次のattemptにもレビューにも進まない。
        # t.cost_usdはworker+レビュー/ペルソナのロールコストを含むタスク総コスト
        # (失敗呼び出し含む)。フォローアップ4以降、reviewer/ペルソナ呼び出し後に
        # t.cost_usdへ加算されるため、この直後(次attempt冒頭)のチェックは
        # 前attemptのロールコストも見た上で判定する
        if (budget.task_budget_usd is not None
                and t.cost_usd >= budget.task_budget_usd):
            transition(store, t, "failed",
                       notes=(f"task予算超過: {t.cost_usd:.4f} USD >= "
                              f"{budget.task_budget_usd} USD"),
                       event="task.budget_exceeded", cost=t.cost_usd,
                       limit=budget.task_budget_usd)
            return t

        if not res.ok:
            if flag.exists():
                # terminateによる異常終了は失敗ではなくキャンセル扱い
                transition(store, t, "cancelled")
                return t
            if is_capability_error(res.output):
                # 権限起因はworkerの実力不足ではなく環境側の制約。retry/レビュー
                # (LLM判断)を介さず、機械的にawaiting_humanへ遷移する
                store.log("capability.blocked", task=t.id,
                          detail=res.output[:500])
                reason = (
                    "権限起因のエラーで失敗した(機械検知。レビュー未経由): "
                    f"{res.output[:500]}\n\n"
                    "対処案: config の `workers.claude_code.capability_allowlist` "
                    "へ、ブロックされたコマンドを許可する追加パターンを登録する"
                    "ことを検討せよ。")
                enter_awaiting_human(store, cfg, t, reason,
                                     refund_attempt=True)
                return t
            if is_infra_error(res.output):
                # ネットワーク断等はworkerの失敗ではない: attemptを返却して待機後に再試行。
                # ただしセッションコストは実際に発生しうるため無限には粘らない(上限つき)
                if infra_retries >= infra_max:
                    transition(store, t, "failed", notes=(
                        f"インフラエラーが継続(リトライ上限{infra_max}回を消化)。"
                        f"ネットワーク・スリープ状態を確認して resume --retry-failed せよ: "
                        f"{res.output[:200]}"),
                        event="task.infra_exhausted", detail=res.output[:200])
                    return t
                infra_retries += 1
                store.log("task.infra_retry", task=t.id, retry=infra_retries,
                          detail=res.output[:200])
                with store.lock:
                    t.attempts -= 1  # このattemptは消費しない
                if cancellable_sleep(store, infra_wait):
                    transition(store, t, "cancelled")
                    return t
                continue  # プロンプトは変えずそのまま再試行
            prompt = retry_prompt(
                adapter, cfg, t,
                f"前回の実行がエラーで終了した。原因を特定して完了させろ。\n---\n{res.output[:4000]}")
            continue

        transition(store, t, "review")
        # 非git成果物の配達契約(direction-2026-08 §4 3a'): workerがworktree直下に
        # orgh-manifest.json を出力した場合のみ発動する(無ければNone=従来動作)。
        # 検収開始時点でstagingを凍結扱いにして照合するため、reviewer呼び出し
        # (成果物を書き換えない前提)より前にここで行う
        copyback_ctx = copyback_gate.start_review_gate(store, t)
        verdict = run_review_pipeline(cfg, store, t, budget, infra_wait)
        if verdict is None:
            return t   # レビュー/ペルソナ枯渇でfailed確定済み(成果は保持)
        passed, feedback = verdict
        if passed:
            # レビュー中にキャンセルされていたら成果を確定させない
            # (terminateを逃れて完走したレビューがここへ到達しうる)
            if flag.exists():
                transition(store, t, "cancelled",
                           event="task.cancelled_after_review")
                return t
            # 合格成果をタスクブランチへコミット(依存タスク・検収への受け渡し)。
            # done確定はコミット後の最終CANCEL確認を通ってから行う: 確認→done→
            # コミットの順だと、その隙間のキャンセルが成果確定に化ける
            commit = commit_task_result(t, store.dir.name)
            if commit:
                store.log("task.committed", task=t.id, commit=commit)
            if flag.exists():
                # コミット自体はブランチに残るが、タスクはキャンセル扱いにする
                # (resumeで再実行され、ブランチは次の合格コミットで進む)
                transition(store, t, "cancelled",
                           event="task.cancelled_after_review")
                return t
            if copyback_ctx is not None:
                # 検収合格後にのみ実コピーを行う(コピー直前に再検証する契約は
                # copyback_gate.finalize -> run_copyback 内で行われる)。
                # False = 既にfailed/awaiting_humanへ遷移済み(doneにしない)
                if not copyback_gate.finalize(store, cfg, t, copyback_ctx):
                    return t
            transition(store, t, "done")
            return t

        if feedback.startswith("REPLAN:"):
            # 計画自体の欠陥: Workerを回しても直らないのでPlannerへエスカレーション
            if t.replans >= 1:
                transition(store, t, "failed",
                           notes=f"REPLAN上限超過(再設計は1回まで): {feedback[:500]}",
                           event="task.replan_exceeded")
                return t
            redesigned = replan_task(cfg, t, feedback, budget,
                                     registry_key=store.dir.name)
            with store.lock:
                t.prompt = redesigned.get("prompt", t.prompt)
                t.acceptance = redesigned.get("acceptance", t.acceptance)
                t.replans += 1
                t.attempts -= 1          # REPLAN再実行はattemptsを消費しない
            store.log("task.replan", task=t.id, reason=feedback[:500])
            # owner.interrupt: REPLANは「計画時にオーナーが埋めるべきだった
            # 判断を実行中に埋め直している」ため割り込みとして数える
            store.log("owner.interrupt", kind="owner_replan", task=t.id,
                      detail=feedback[:200])
            prompt = full_worker_prompt(cfg, t)  # 再設計後の指示で最初から
            continue

        if feedback.startswith("HUMAN:"):
            # workerには解消不能な環境側の恒常的制約(オーナー裁定: 保護パスへの
            # 書き込み・対面作業・アカウント登録等)。REPLANと同型でattemptsは
            # 消費しない(再設計しても解消しない制約のため回数上限も設けない)
            reason = feedback[len("HUMAN:"):].strip()
            enter_awaiting_human(store, cfg, t, reason, refund_attempt=True)
            return t

        # 改善ループ: レビューのフィードバックを次のattemptへ
        prompt = retry_prompt(
            adapter, cfg, t,
            f"レビューで差し戻し。以下を修正して受け入れ条件を満たせ。\n"
            f"## Feedback\n{feedback}")
        # 差し戻し昇格: タスクにmodelが明示指定されている場合のみ、次attemptの
        # 実効モデルを1段昇格する(haiku -> sonnet -> opus)。opusは据え置き
        # (昇格イベントも記録しない)。model未指定タスクは完全不変。
        if t.model is not None:
            next_model = _MODEL_ESCALATION.get(effective_model)
            if next_model:
                store.log("model.escalated", task=t.id, from_=effective_model,
                          to=next_model, attempt=t.attempts + 1,
                          reason="review_rejected")
                effective_model = next_model
                adapter = _adapter_for(effective_model)

    transition(store, t, "failed")
    return t

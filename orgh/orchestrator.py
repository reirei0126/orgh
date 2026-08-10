"""Orchestrator: DAGに従いWorkerを並列起動。
task: pending -> running -> review -> done / (feedback付きで再実行) -> failed
Claude Codeタスクは session_id を保持し --resume でフィードバックを渡す(文脈を捨てない)。

キャンセル(HANDOFF タスク4): runs/<mission_id>/CANCEL フラグファイルが唯一の
停止信号。orgh cancel(別プロセス)はフラグを置くだけで、ミッションを実行中の
プロセス自身がループごとにフラグを検知し、実行中subprocessをterminate・
未着手タスクをcancelledにして停止する。poll_cancel(watcherが渡す結果ノートの
#cancel検知)がTrueを返した場合もフラグを置いて同じ経路に合流する。
"""
from __future__ import annotations

import fcntl
import re
import shutil
import subprocess
import time
import traceback
from pathlib import Path
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from . import procreg
from .adapters.base import get_adapter
from .guard import needs_approval
from .planner import persona_review, replan_task, review, worker_prompt
from .state import Budget, Mission, RunStore, Task
from .worktree import commit_task_result, ensure_task_worktree

# 終端ステータス(これ以外は実行中系としてresume時にpendingへ巻き戻される)
TERMINAL = ("done", "failed", "cancelled", "skipped")

# キャンセル検知のポーリング間隔(秒)。タスク完了イベントもこの粒度で拾う
_POLL_INTERVAL = 0.5

# インフラ(ネットワーク・接続)起因のエラー署名。workerの失敗ではないため
# attemptを消費せずにリトライする(実運用7307189e t5: ネットワーク断で
# 3attempt≒6.4USD相当を浪費した事例への対処)。署名は実際に観測されたものを登録する
_INFRA_ERROR_RE = re.compile(
    r"Request timed out"               # claude CLI(t5 attempt1/2で実測)
    r"|Unable to connect to API"       # claude CLI(t5 attempt3で実測)
    r"|Connection closed mid-response" # claude CLI(7307189e t1初回で実測)
    r"|ENOTFOUND|ECONNREFUSED|ECONNRESET|ETIMEDOUT|EAI_AGAIN"
    r"|fetch failed",
)
# 注: BaseAdapter.run の task_timeout マーカー("timeout")は対象外。
# あれは「詰まったworker」の可能性があり、attempt非消費で粘ると無限に待つため
# 従来どおりattemptを消費する通常failure扱いにする


def _is_infra_error(output: str) -> bool:
    return bool(_INFRA_ERROR_RE.search(output or ""))


def _ready(m: Mission) -> list[Task]:
    done = {t.id for t in m.tasks if t.status == "done"}
    return [t for t in m.tasks
            if t.status == "pending" and all(d in done for d in t.deps)]


def _blocked_forever(m: Mission) -> bool:
    dead = {t.id for t in m.tasks if t.status in ("failed", "cancelled")}
    pend = [t for t in m.tasks if t.status == "pending"]
    return bool(dead) and all(
        any(d in dead for d in t.deps) for t in pend) if pend else False


def _cancel_flag(store: RunStore):
    return store.dir / "CANCEL"


def _cancellable_sleep(store: RunStore, seconds: float) -> bool:
    """リトライ待機。CANCEL検知で早期復帰しTrueを返す。

    素のtime.sleepだと待機中のキャンセルが最大でinfra_wait(既定60秒)止まらない
    (停止対象subprocessが存在しない区間のため、terminateでは中断できない)。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _cancel_flag(store).exists():
            return True
        time.sleep(min(1.0, max(0.0, deadline - time.time())))
    return _cancel_flag(store).exists()


class _CancelledDuringRole(Exception):
    """キャンセルのterminateがreviewer/planner subprocessを落とした際の内部信号。
    包括エラーハンドラでfailedに化けさせず、cancelledとして確定させる。"""


def _is_non_retryable_role_error(e: Exception) -> bool:
    """ロール呼び出し失敗のうち、リトライしても結果が変わらない決定論的な
    設定ミスを見分ける。例: personas.enabledのタイポやprompts/persona_<name>.md
    未作成によるFileNotFoundError(_read_prompt)。これを他の一時的失敗
    (接続断・max_turns超過等)と同様にretries回リトライすると、無意味な
    infra_retry_wait秒×retries回の待機だけが発生してユーザー体験を損なう。
    ロールリトライ枯渇時の扱い(failed化・worker成果保持)自体は変えない —
    呼び出し元の except節へ即座に流すだけ。"""
    return isinstance(e, FileNotFoundError)


def _run_task(cfg: dict, store: RunStore, t: Task, budget: Budget) -> Task:
    """最外周の薄いラッパ: 実処理(_attempt_loop)の全例外を1タスクのfailedに閉じ込め、
    ミッション全体を道連れにしない。"""
    try:
        return _attempt_loop(cfg, store, t, budget)
    except Exception as e:
        # キャンセルのterminateが引き起こした例外(replan中のplanner死など)は
        # failedではなくcancelled: failedにすると通常resumeで復元されない
        if _cancel_flag(store).exists() or isinstance(e, _CancelledDuringRole):
            with store.lock:
                t.status = "cancelled"
            store.log("task.cancelled_during_role", task=t.id, error=repr(e)[:300])
            return t
        with store.lock:
            t.status = "failed"
            t.review_notes = f"internal error: {e!r}"
        store.log("task.error", task=t.id, error=repr(e),
                  trace=traceback.format_exc()[-2000:])
        return t


def _role_call_with_retry(cfg: dict, store: RunStore, t: Task, role: str,
                          fn, retries: int = 2, wait: float = 60):
    """ロール呼び出し(reviewer/persona)の失敗はロールのみリトライする。
    worker実行はやり直さない(成果とコストを捨てない)。

    呼び出し側のfnはadapter/_ask_jsonにregistry_keyを渡すこと。未登録だと
    ロール実行中のキャンセルが効かず、キャンセル後に成果が確定してしまう。

    再試行しない例外(_is_non_retryable_role_errorが真を返すもの)は即座に
    再送出する: 設定ミス等の決定論的エラーをリトライで隠さない(60秒級の
    無駄な待機×retries回を発生させない)ため。
    """
    last: Exception | None = None
    for i in range(retries + 1):
        if _cancel_flag(store).exists():
            # terminateされたロールの例外を「失敗」と誤認して新しいロールを
            # 起動しない(キャンセル後の再起動はコストと成果確定の両方で有害)
            raise _CancelledDuringRole(f"cancelled before/during {role}")
        try:
            return fn()
        except Exception as e:
            if _cancel_flag(store).exists():
                raise _CancelledDuringRole(f"{role} terminated by cancel") from e
            if _is_non_retryable_role_error(e):
                raise
            last = e
            if i < retries:
                store.log("role.retry", role=role, task=t.id,
                          retry=i + 1, error=repr(e)[:300])
                if _cancellable_sleep(store, wait):
                    raise _CancelledDuringRole("cancelled during retry wait") from e
    raise last  # type: ignore[misc]


def _review_with_retry(cfg: dict, store: RunStore, t: Task, budget: Budget,
                       retries: int = 2, wait: float = 60):
    return _role_call_with_retry(
        cfg, store, t, "reviewer",
        lambda: review(cfg, t, workdir=t.workdir, budget=budget,
                       registry_key=store.dir.name),
        retries=retries, wait=wait)


def _retry_prompt(adapter, cfg: dict, t: Task, followup: str) -> str:
    """再試行プロンプトの構築。セッションresumeできるworkerはフィードバックのみで
    よい(セッションが文脈を保持する)が、できないworker(codex等)は元タスクの
    文脈を全て失うため、タスク一式(preamble込み)+追記の自己完結形にする。
    実運用7307189e t3で発見: 断片だけ受けたcodexが実装せず確認質問を返して失敗した。"""
    if adapter.supports_resume:
        return followup
    return f"{worker_prompt(cfg, t)}\n\n## 再実行の指示\n{followup}"


def _ensure_workdir(store: RunStore, t: Task, wt_cfg: dict) -> None:
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


def _attempt_loop(cfg: dict, store: RunStore, t: Task, budget: Budget) -> Task:
    wt_cfg = cfg.get("worktree") or {}
    _ensure_workdir(store, t, wt_cfg)
    if wt_cfg.get("enabled"):
        got = ensure_task_worktree(wt_cfg, store.dir.name, t)
        if got:
            path, branch = got
            with store.lock:
                t.workdir, t.branch = str(path), branch
            store.log("task.worktree", task=t.id, path=str(path), branch=branch)

    adapter = get_adapter(t.worker, cfg["workers"])
    lcfg = cfg.get("loop", {})
    max_attempts = lcfg.get("max_attempts", 3)
    infra_max = lcfg.get("infra_max_retries", 3)
    infra_wait = lcfg.get("infra_retry_wait", 60)
    infra_retries = 0
    cancel_flag = _cancel_flag(store)

    prompt = worker_prompt(cfg, t)
    if t.branch:
        # Plannerがタスク指示に主リポの絶対パスを書くと、workerがworktree外へ
        # 成果物を書いて自動コミットから漏れる(mission 02a434ad t1/t2で実測)。
        # worktree実行時は作業場所の厳守を指示の先頭で明示する
        prompt = (
            f"【作業場所の厳守】このタスクの作業ディレクトリは専用worktree "
            f"{t.workdir} である。以降の指示に他のディレクトリパスが書かれて"
            f"いても、ファイルの新規作成・編集は必ずこのworktree内で行うこと"
            f"(worktree外に書いた成果物は自動コミットの対象外となり失われる)。"
            f"git show等での他ブランチ・他パスの読み取り参照は行ってよい。\n\n"
            + prompt)
    while t.attempts < max_attempts:
        if cancel_flag.exists():
            with store.lock:
                t.status = "cancelled"
            return t
        with store.lock:
            t.attempts += 1
            t.status = "running"
        store.log("task.start", task=t.id, worker=t.worker, attempt=t.attempts)
        res = adapter.run(prompt, workdir=t.workdir,
                          resume=t.session_id,
                          timeout=cfg.get("loop", {}).get("task_timeout", 3600),
                          registry_key=store.dir.name,
                          allowed_tools=t.tools)
        with store.lock:
            t.last_output = res.output
            t.session_id = res.session_id or t.session_id
            t.cost_usd += res.cost_usd or 0.0
        budget.charge(res.cost_usd)
        store.artifact(f"{t.id}_attempt{t.attempts}.md", res.output)
        store.log("task.output", task=t.id, ok=res.ok, cost=res.cost_usd)

        # タスク上限超過: 次のattemptにもレビューにも進まない。
        # t.cost_usdはworker実行コストのみを積む(reviewer/ペルソナのロール
        # コストはミッション予算(budget.spent_usd)にのみ計上され、この
        # タスク単価上限の対象外 — 会計を変える変更ではなく契約の明文化)
        if (budget.task_budget_usd is not None
                and t.cost_usd >= budget.task_budget_usd):
            with store.lock:
                t.status = "failed"
                t.review_notes = (f"task予算超過: {t.cost_usd:.4f} USD >= "
                                  f"{budget.task_budget_usd} USD")
            store.log("task.budget_exceeded", task=t.id, cost=t.cost_usd,
                      limit=budget.task_budget_usd)
            return t

        if not res.ok:
            if cancel_flag.exists():
                # terminateによる異常終了は失敗ではなくキャンセル扱い
                with store.lock:
                    t.status = "cancelled"
                return t
            if _is_infra_error(res.output):
                # ネットワーク断等はworkerの失敗ではない: attemptを返却して待機後に再試行。
                # ただしセッションコストは実際に発生しうるため無限には粘らない(上限つき)
                if infra_retries >= infra_max:
                    with store.lock:
                        t.status = "failed"
                        t.review_notes = (
                            f"インフラエラーが継続(リトライ上限{infra_max}回を消化)。"
                            f"ネットワーク・スリープ状態を確認して resume --retry-failed せよ: "
                            f"{res.output[:200]}")
                    store.log("task.infra_exhausted", task=t.id,
                              detail=res.output[:200])
                    return t
                infra_retries += 1
                store.log("task.infra_retry", task=t.id, retry=infra_retries,
                          detail=res.output[:200])
                with store.lock:
                    t.attempts -= 1  # このattemptは消費しない
                if _cancellable_sleep(store, infra_wait):
                    with store.lock:
                        t.status = "cancelled"
                    return t
                continue  # プロンプトは変えずそのまま再試行
            prompt = _retry_prompt(
                adapter, cfg, t,
                f"前回の実行がエラーで終了した。原因を特定して完了させろ。\n---\n{res.output[:4000]}")
            continue

        with store.lock:
            t.status = "review"
        try:
            passed, feedback = _review_with_retry(cfg, store, t, budget,
                                                  wait=infra_wait)
        except _CancelledDuringRole:
            # キャンセル起因は_run_taskの包括ハンドラでcancelled化する。
            # ここの包括exceptに食わせるとfailedに化けて通常resume不能になる
            raise
        except Exception as e:
            # レビューが繰り返し失敗してもworkerの成果(last_output/worktree)は
            # 捨てない。原因の分かる形でfailedにし、resumeでの再挑戦に委ねる
            # (実運用7307189e t6: reviewerのmax_turns死でタスクごとinternal error化した)
            with store.lock:
                t.status = "failed"
                t.review_notes = (f"レビュー呼び出しが失敗(リトライ上限超過)。"
                                  f"worker成果は保持済み: {e!s:.300}")
            store.log("task.review_exhausted", task=t.id, error=repr(e)[:500])
            return t
        with store.lock:
            t.review_notes = feedback
        store.log("task.review", task=t.id, passed=passed)
        if passed and t.personas:
            for persona in t.personas:
                try:
                    p_ok, p_fb = _role_call_with_retry(
                        cfg, store, t, f"persona_{persona}",
                        lambda p=persona: persona_review(
                            cfg, p, t, workdir=t.workdir, budget=budget,
                            registry_key=store.dir.name),
                        wait=infra_wait)
                except _CancelledDuringRole:
                    raise
                except Exception as e:
                    # 証拠なし合格の連発等。reviewer枯渇と同様に成果は保持してfailed
                    with store.lock:
                        t.status = "failed"
                        t.review_notes = (f"ペルソナ検収({persona})の呼び出しが失敗"
                                          f"(リトライ上限超過)。worker成果は保持済み: "
                                          f"{e!s:.300}")
                    store.log("task.persona_exhausted", task=t.id,
                              persona=persona, error=repr(e)[:500])
                    return t
                store.log("task.persona_review", task=t.id, persona=persona,
                          passed=p_ok)
                if not p_ok:
                    passed = False
                    feedback = f"[{persona}ペルソナ検収] {p_fb}"
                    with store.lock:
                        t.review_notes = feedback   # attempts枯渇時に原因が残るように
                    break
        if passed:
            # レビュー中にキャンセルされていたら成果を確定させない
            # (terminateを逃れて完走したレビューがここへ到達しうる)
            if cancel_flag.exists():
                with store.lock:
                    t.status = "cancelled"
                store.log("task.cancelled_after_review", task=t.id)
                return t
            # 合格成果をタスクブランチへコミット(依存タスク・検収への受け渡し)。
            # done確定はコミット後の最終CANCEL確認を通ってから行う: 確認→done→
            # コミットの順だと、その隙間のキャンセルが成果確定に化ける
            commit = commit_task_result(t, store.dir.name)
            if commit:
                store.log("task.committed", task=t.id, commit=commit)
            if cancel_flag.exists():
                # コミット自体はブランチに残るが、タスクはキャンセル扱いにする
                # (resumeで再実行され、ブランチは次の合格コミットで進む)
                with store.lock:
                    t.status = "cancelled"
                store.log("task.cancelled_after_review", task=t.id)
                return t
            with store.lock:
                t.status = "done"
            return t

        if feedback.startswith("REPLAN:"):
            # 計画自体の欠陥: Workerを回しても直らないのでPlannerへエスカレーション
            if t.replans >= 1:
                with store.lock:
                    t.status = "failed"
                    t.review_notes = f"REPLAN上限超過(再設計は1回まで): {feedback[:500]}"
                store.log("task.replan_exceeded", task=t.id)
                return t
            redesigned = replan_task(cfg, t, feedback, budget,
                                     registry_key=store.dir.name)
            with store.lock:
                t.prompt = redesigned.get("prompt", t.prompt)
                t.acceptance = redesigned.get("acceptance", t.acceptance)
                t.replans += 1
                t.attempts -= 1          # REPLAN再実行はattemptsを消費しない
            store.log("task.replan", task=t.id, reason=feedback[:500])
            prompt = worker_prompt(cfg, t)  # 再設計後の指示で最初から
            continue

        # 改善ループ: レビューのフィードバックを次のattemptへ
        prompt = _retry_prompt(
            adapter, cfg, t,
            f"レビューで差し戻し。以下を修正して受け入れ条件を満たせ。\n"
            f"## Feedback\n{feedback}")

    with store.lock:
        t.status = "failed"
    return t


def _initiate_cancel(mission: Mission, store: RunStore) -> None:
    """キャンセル開始: フラグを確定し、実行中subprocessをterminate、
    未着手タスクをcancelledにする。実行中タスクの完了(cancelled化)は
    _attempt_loop側がフラグを見て行う。"""
    _cancel_flag(store).touch()
    n = procreg.terminate(store.dir.name)
    with store.lock:
        for t in mission.tasks:
            if t.status == "pending":
                t.status = "cancelled"
    store.save(mission)
    store.log("mission.cancelled", terminated=n)
    print(f"  mission {store.dir.name} cancelling... ({n} proc terminated)")


def _setup_budget(cfg: dict, mission: Mission) -> Budget:
    """ミッションの予算プールを用意する。初回はconfigから確保、resume時は
    消費(spent)を引き継ぎつつ上限だけconfigから更新する(予算を上げて続行
    できるように)。split()で割当を受けた子ミッションは上限を上書きしない。"""
    lcfg = cfg.get("loop", {})
    if mission.budget is None:
        mission.budget = Budget(limit_usd=lcfg.get("budget_usd"),
                                task_budget_usd=lcfg.get("task_budget_usd"))
    elif mission.budget._parent is None:
        mission.budget.limit_usd = lcfg.get("budget_usd")
        mission.budget.task_budget_usd = lcfg.get("task_budget_usd")
    return mission.budget


def _initiate_budget_stop(mission: Mission, store: RunStore,
                          budget: Budget) -> None:
    """予算超過: 実行中タスクの完了は待つが、未着手はdispatchせずskippedに。"""
    with store.lock:
        for t in mission.tasks:
            if t.status == "pending":
                t.status = "skipped"
    store.save(mission)
    store.log("mission.budget_exceeded", spent=budget.spent_usd,
              limit=budget.limit_usd)
    print(f"  mission {store.dir.name} budget exceeded "
          f"({budget.spent_usd:.4f}/{budget.limit_usd} USD) — 未着手をskip")


def _assign_personas(cfg: dict, mission: Mission) -> None:
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


def _with_prompts_snapshot(cfg: dict, store: RunStore) -> dict:
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
        cfg = _with_prompts_snapshot(cfg, store)
        return _run_mission_locked(cfg, mission, store, on_update, poll_cancel)
    finally:
        lock_fp.close()  # closeでflockも解放される


def _run_mission_locked(cfg: dict, mission: Mission, store: RunStore,
                        on_update=None, poll_cancel=None) -> Mission:
    workers = cfg.get("loop", {}).get("parallel", 3)
    budget = _setup_budget(cfg, mission)
    _assign_personas(cfg, mission)
    store.save(mission)
    store.artifact("context_digest.md", mission.context_digest)
    cancelling = False
    budget_stopped = False
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        while True:
            if not cancelling and (
                    _cancel_flag(store).exists()
                    or (poll_cancel and poll_cancel())):
                cancelling = True
                _initiate_cancel(mission, store)
            if not cancelling and not budget_stopped and budget.exceeded():
                budget_stopped = True
                _initiate_budget_stop(mission, store, budget)
            if not cancelling and not budget_stopped:
                for t in _ready(mission):
                    if t.id in futures:
                        continue
                    # 自己改変ガード: orgh自身を指すworkdirは承認なしに実行しない
                    # (watcher経由でもスキップ不可。configでも無効化不可)
                    if (needs_approval(cfg, t.workdir)
                            and not (store.dir / "APPROVED").exists()):
                        with store.lock:
                            t.status = "awaiting_approval"
                        store.log("task.awaiting_approval", task=t.id,
                                  workdir=t.workdir)
                        print(f"  [awaiting_approval] {t.title} — "
                              f"orgh approve {store.dir.name} で続行")
                        continue
                    with store.lock:
                        t.status = "queued"
                    futures[t.id] = pool.submit(_run_task, cfg, store, t,
                                                budget)
            if not futures:
                break
            done, _ = wait(list(futures.values()), timeout=_POLL_INTERVAL,
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
            if _blocked_forever(mission) and not futures:
                break
    store.save(mission)
    # 完了直前(最後のタスクのdone確定後)に届いたCANCELは、もう止める対象が
    # 無いため完了扱いになる。残存する数ms級の競合窓は仕様として受容し、
    # 「キャンセルは間に合わなかった」ことをledgerに明示して観測可能にする
    if _cancel_flag(store).exists() and not cancelling and \
            all(t.status in TERMINAL for t in mission.tasks):
        store.log("mission.cancel_too_late")
    store.log("mission.finished",
              done=[t.id for t in mission.tasks if t.status == "done"],
              failed=[t.id for t in mission.tasks if t.status == "failed"],
              cancelled=[t.id for t in mission.tasks
                         if t.status == "cancelled"])
    return mission

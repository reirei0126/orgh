"""検収パイプライン: reviewer + persona 検収の直列裁定と、ロール呼び出しの
リトライ方針。workerの成果とコストを捨てない(ロールのみリトライする)。"""
from __future__ import annotations

from ..planner import persona_review, review
from ..state import Budget, RunStore, Task
from .cancellation import CancelledDuringRole, cancel_flag, cancellable_sleep


def is_non_retryable_role_error(e: Exception) -> bool:
    """ロール呼び出し失敗のうち、リトライしても結果が変わらない決定論的な
    設定ミスを見分ける。例: personas.enabledのタイポやprompts/persona_<name>.md
    未作成によるFileNotFoundError(_read_prompt)。これを他の一時的失敗
    (接続断・max_turns超過等)と同様にretries回リトライすると、無意味な
    infra_retry_wait秒×retries回の待機だけが発生してユーザー体験を損なう。
    ロールリトライ枯渇時の扱い(failed化・worker成果保持)自体は変えない —
    呼び出し元の except節へ即座に流すだけ。"""
    return isinstance(e, FileNotFoundError)


def role_call_with_retry(cfg: dict, store: RunStore, t: Task, role: str,
                         fn, retries: int = 2, wait: float = 60):
    """ロール呼び出し(reviewer/persona)の失敗はロールのみリトライする。
    worker実行はやり直さない(成果とコストを捨てない)。

    呼び出し側のfnはadapter/_ask_jsonにregistry_keyを渡すこと。未登録だと
    ロール実行中のキャンセルが効かず、キャンセル後に成果が確定してしまう。

    再試行しない例外(is_non_retryable_role_errorが真を返すもの)は即座に
    再送出する: 設定ミス等の決定論的エラーをリトライで隠さない(60秒級の
    無駄な待機×retries回を発生させない)ため。
    """
    last: Exception | None = None
    for i in range(retries + 1):
        if cancel_flag(store).exists():
            # terminateされたロールの例外を「失敗」と誤認して新しいロールを
            # 起動しない(キャンセル後の再起動はコストと成果確定の両方で有害)
            raise CancelledDuringRole(f"cancelled before/during {role}")
        try:
            return fn()
        except Exception as e:
            if cancel_flag(store).exists():
                raise CancelledDuringRole(f"{role} terminated by cancel") from e
            if is_non_retryable_role_error(e):
                raise
            last = e
            if i < retries:
                store.log("role.retry", role=role, task=t.id,
                          retry=i + 1, error=repr(e)[:300])
                if cancellable_sleep(store, wait):
                    raise CancelledDuringRole("cancelled during retry wait") from e
    raise last  # type: ignore[misc]


def review_with_retry(cfg: dict, store: RunStore, t: Task, budget: Budget,
                      retries: int = 2, wait: float = 60,
                      cost_sink: list | None = None):
    return role_call_with_retry(
        cfg, store, t, "reviewer",
        lambda: review(cfg, t, workdir=t.workdir, budget=budget,
                       registry_key=store.dir.name, cost_sink=cost_sink),
        retries=retries, wait=wait)


def run_review_pipeline(cfg: dict, store: RunStore, t: Task, budget: Budget,
                        infra_wait: float):
    """reviewer + persona 検収の直列裁定。呼び出し前に t.status = "review" に
    しておくこと。戻り値は (passed, feedback)。ロールのリトライ枯渇でタスクを
    failed 確定済みにした場合は None を返す(呼び出し側は即 return する)。
    キャンセル起因の CancelledDuringRole はそのまま透過する。"""
    # reviewerのコスト(成功・失敗いずれの呼び出しも含む)を貯め、呼び出しが
    # 例外で終わってもfinallyでt.cost_usdへ合算する(フォローアップ4b:
    # 従来t.cost_usdはworker実行コストのみで、レビューコストがタスク単価に
    # 反映されず、次attempt冒頭のタスク予算チェックも過小評価していた)
    review_cost_sink: list[float] = []
    try:
        passed, feedback = review_with_retry(cfg, store, t, budget,
                                             wait=infra_wait,
                                             cost_sink=review_cost_sink)
    except CancelledDuringRole:
        # キャンセル起因は_run_taskの包括ハンドラでcancelled化する。
        # 包括exceptに食わせるとfailedに化けて通常resume不能になる
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
        return None
    finally:
        with store.lock:
            t.cost_usd += sum(review_cost_sink)
    with store.lock:
        t.review_notes = feedback
    store.log("task.review", task=t.id, passed=passed)
    if passed and t.personas:
        for persona in t.personas:
            persona_cost_sink: list[float] = []
            try:
                p_ok, p_fb, p_ev = role_call_with_retry(
                    cfg, store, t, f"persona_{persona}",
                    lambda p=persona: persona_review(
                        cfg, p, t, workdir=t.workdir, budget=budget,
                        registry_key=store.dir.name,
                        cost_sink=persona_cost_sink),
                    wait=infra_wait)
            except CancelledDuringRole:
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
                return None
            finally:
                with store.lock:
                    t.cost_usd += sum(persona_cost_sink)
            # evidenceはledger肥大防止のため10件で打ち切り、各要素も
            # str化して300文字に丸める(監査に必要な最小限のみ残す)
            store.log("task.persona_review", task=t.id, persona=persona,
                      passed=p_ok,
                      evidence=[str(x)[:300] for x in p_ev[:10]])
            if not p_ok:
                passed = False
                feedback = f"[{persona}ペルソナ検収] {p_fb}"
                with store.lock:
                    t.review_notes = feedback   # attempts枯渇時に原因が残るように
                break
    return passed, feedback

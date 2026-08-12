# R-3: orchestrator 分割 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 653行の神モジュール `orgh/orchestrator.py` を、挙動を一切変えずに責務別パッケージ `orgh/orchestrator/` へ分割する(docs/refactor/execution-architecture.md R-3)。

**Architecture:** `orchestrator.py` をパッケージ化し、bottom-up(葉から)の順で cancellation → review_pipeline → task_executor → scheduler を抽出。`__init__.py` は facade として公開API(`run_mission`, `acquire_mission_lock`)とテスト参照名を再輸出する。最後に状態遷移を単一 `transition()` 関数へ集約。

**Tech Stack:** Python 3.11+ / pytest(362件が回帰網)/ 追加依存なし

## Global Constraints

- **純リファクタ**: ledgerイベント名・payloadキー・print文言・ステータス遷移順・ロック粒度を一切変えない
- 各タスク末尾で `pytest -q` 全緑 → 即コミット(mainブランチ、小刻み)
- 公開API `run_mission(cfg, mission, store, on_update=None, poll_cancel=None, lock_fp=None)` と `acquire_mission_lock(store)` のシグネチャ不変(cli.py / watcher.py は無修正)
- playbooks/ 配下の既存作業ツリー変更はコミットに含めない(並行作業の痕跡)
- 有効化(watch再起動)はミッション0件の窓でのみ行う

## 分割マップ(移動元は現行 orgh/orchestrator.py の行番号)

| 新モジュール | 移動するシンボル(現行行) |
|---|---|
| `cancellation.py` | `_cancel_flag`(68), `_cancellable_sleep`(72), `_CancelledDuringRole`(85), `_initiate_cancel`(446) |
| `budget_policy.py` | `_setup_budget`(461), `_initiate_budget_stop`(475) |
| `review_pipeline.py` | `_is_non_retryable_role_error`(90), `_role_call_with_retry`(122), `_review_with_retry`(156), 新関数 `run_review_pipeline`(_attempt_loop 308-375 のreview+persona直列裁定を抽出) |
| `task_executor.py` | `_INFRA_ERROR_RE`(39), `_is_infra_error`(51), `_run_task`(101), `_retry_prompt`(166), `_full_worker_prompt`(179), `_ensure_workdir`(196), `_attempt_loop`(217) |
| `scheduler.py` | `TERMINAL`(31), `_POLL_INTERVAL`(34), `_ready`(55), `_blocked_forever`(61), `_assign_personas`(489), `acquire_mission_lock`(501), `_with_prompts_snapshot`(518), `run_mission`(548), `_run_mission_locked`(567) |
| `transitions.py` | 新規: `transition()` 単一関数(Task 6) |
| `__init__.py` | facade: docstring(1-10行)+ 再輸出のみ |

---

### Task 1: パッケージ化(無変更の器づくり)

**Files:**
- Move: `orgh/orchestrator.py` → `orgh/orchestrator/__init__.py`(git mv、中身無変更)
- Modify: `tests/test_paths.py:43-48`(ファイル列挙 → orgh/ 配下 *.py の再帰glob)

**Interfaces:**
- Produces: パッケージ `orgh.orchestrator`(import面は完全互換。`from .orchestrator import run_mission` 等は無修正で通る)

- [ ] **Step 1: git mv でパッケージ化**

```bash
mkdir orgh/orchestrator && git mv orgh/orchestrator.py orgh/orchestrator/__init__.py
```

- [ ] **Step 2: test_paths の規約テストを再帰globへ強化**

`test_no_repo_relative_file_refs_in_sources` を以下に置換(分割後の新モジュールも自動で監視対象になる):

```python
    def test_no_repo_relative_file_refs_in_sources(self):
        """パッケージ相対(__file__起点)のprompts/playbooks参照の全廃を強制する。"""
        for src_path in (REPO / "orgh").rglob("*.py"):
            src = src_path.read_text()
            assert "parent.parent" not in src, \
                f"{src_path.relative_to(REPO)} が__file__相対参照を残している"
```

- [ ] **Step 3: pytest 全緑を確認**

Run: `pytest -q` / Expected: 362 passed

- [ ] **Step 4: Commit**

```bash
git add -A orgh/orchestrator tests/test_paths.py
git commit -m "refactor(R-3): orchestrator.pyをパッケージ化(無変更move、規約テストを再帰glob化)"
```

---

### Task 2: cancellation / budget_policy の抽出

**Files:**
- Create: `orgh/orchestrator/cancellation.py`, `orgh/orchestrator/budget_policy.py`
- Modify: `orgh/orchestrator/__init__.py`(移動分を削除し import に置換)

**Interfaces:**
- Produces(後続タスクが import する名前):
  - `cancellation.cancel_flag(store) -> Path`(旧 `_cancel_flag` と同一実装・改名)
  - `cancellation.cancellable_sleep(store, seconds: float) -> bool`
  - `cancellation.CancelledDuringRole(Exception)`
  - `cancellation.initiate_cancel(mission, store) -> None`
  - `budget_policy.setup_budget(cfg, mission) -> Budget`
  - `budget_policy.initiate_budget_stop(mission, store, budget) -> None`

- [ ] **Step 1: cancellation.py を作成**(4シンボルを本文そのまま移動。モジュール docstring は現行 orchestrator docstring のキャンセル段落(5-9行)を移す。先頭のアンダースコアは外し、公開名にする)

- [ ] **Step 2: budget_policy.py を作成**(2シンボルを本文そのまま移動)

- [ ] **Step 3: __init__.py 側を書き換え**

```python
from .cancellation import (CancelledDuringRole as _CancelledDuringRole,
                           cancel_flag as _cancel_flag,
                           cancellable_sleep as _cancellable_sleep,
                           initiate_cancel as _initiate_cancel)
from .budget_policy import (setup_budget as _setup_budget,
                            initiate_budget_stop as _initiate_budget_stop)
```

旧定義を削除。`_attempt_loop` 等の残存コードは `_cancel_flag` 等の旧名参照のまま動く(alias)。

- [ ] **Step 4: pytest 全緑を確認** → Run: `pytest -q`

- [ ] **Step 5: Commit**

```bash
git add orgh/orchestrator/
git commit -m "refactor(R-3): cancellation/budget_policyを抽出(横断ポリシーの分離)"
```

---

### Task 3: review_pipeline の抽出

**Files:**
- Create: `orgh/orchestrator/review_pipeline.py`
- Modify: `orgh/orchestrator/__init__.py`

**Interfaces:**
- Consumes: `cancellation.cancel_flag / cancellable_sleep / CancelledDuringRole`
- Produces:
  - `role_call_with_retry(cfg, store, t, role, fn, retries=2, wait=60)`(旧 `_role_call_with_retry` 本文そのまま)
  - `review_with_retry(cfg, store, t, budget, retries=2, wait=60, cost_sink=None)`(旧 `_review_with_retry`)
  - `run_review_pipeline(cfg, store, t, budget, infra_wait) -> tuple[bool, str] | None` — **新関数**。`_attempt_loop` の review〜persona 直列裁定(現行308-375行)を切り出す。戻り値 `None` は「タスクを failed 確定済み(review/persona枯渇)」、`(passed, feedback)` は裁定結果。`CancelledDuringRole` はそのまま透過(raise)

- [ ] **Step 1: review_pipeline.py を作成**(retry系2関数+`_is_non_retryable_role_error` を移動)

- [ ] **Step 2: run_review_pipeline を実装** — `_attempt_loop` から以下を移す。挙動不変の要点: ① `t.status = "review"` 設定は呼び出し元に残す ② cost_sink の finally 合算・ledgerイベント名(`task.review` / `task.persona_review` / `task.review_exhausted` / `task.persona_exhausted`)・evidence の10件/300字丸めを一字一句維持 ③ persona不合格時の `t.review_notes = feedback` 更新と break を維持:

```python
def run_review_pipeline(cfg, store, t, budget, infra_wait):
    review_cost_sink: list[float] = []
    try:
        passed, feedback = review_with_retry(cfg, store, t, budget,
                                             wait=infra_wait,
                                             cost_sink=review_cost_sink)
    except CancelledDuringRole:
        raise
    except Exception as e:
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
        ...(現行339-375行を移動。except節の return t は return None に置換)...
    return passed, feedback
```

- [ ] **Step 3: _attempt_loop 側を呼び出しに置換**

```python
        with store.lock:
            t.status = "review"
        verdict = run_review_pipeline(cfg, store, t, budget, infra_wait)
        if verdict is None:
            return t
        passed, feedback = verdict
```

- [ ] **Step 4: pytest 全緑を確認** → Run: `pytest -q`(特に test_review_retry / test_personas / test_cancel)

- [ ] **Step 5: Commit**

```bash
git add orgh/orchestrator/
git commit -m "refactor(R-3): ReviewPipelineを抽出(reviewer+persona直列裁定の分離)"
```

---

### Task 4: task_executor の抽出

**Files:**
- Create: `orgh/orchestrator/task_executor.py`
- Modify: `orgh/orchestrator/__init__.py`, `tests/test_cancel.py:250-280`, `tests/test_hardening.py:122,133`, `tests/test_infra_retry.py:10`

**Interfaces:**
- Consumes: `cancellation.*`, `review_pipeline.run_review_pipeline`, `budget` はタスク予算チェックのみ(現行264-272行、executor内に残置)
- Produces: `run_task(cfg, store, t, budget) -> Task`(旧 `_run_task`)、`attempt_loop`, `retry_prompt`, `full_worker_prompt`, `ensure_workdir`, `is_infra_error`

- [ ] **Step 1: task_executor.py を作成**(7シンボルを本文そのまま移動、公開名化)

- [ ] **Step 2: __init__.py から旧定義を削除し alias import に置換**(`_run_task = run_task` 等)

- [ ] **Step 3: monkeypatch 先を新モジュールへ更新** — `tests/test_cancel.py` の2箇所: `monkeypatch.setattr(orch, "_attempt_loop", boom)` → `from orgh.orchestrator import task_executor` + `monkeypatch.setattr(task_executor, "attempt_loop", boom)`。`_review_with_retry` のpatchも同様に `task_executor` 内で参照される `run_review_pipeline` を patch する形へ(内部で `review_with_retry` を呼ぶ経路が変わったため、patch対象は「executorが実際に参照する名前」に合わせる)

- [ ] **Step 4: pytest 全緑を確認** → Run: `pytest -q`

- [ ] **Step 5: Commit**

```bash
git add orgh/orchestrator/ tests/
git commit -m "refactor(R-3): TaskExecutorを抽出(attemptループ・worker起動・成果コミット)"
```

---

### Task 5: scheduler の抽出(__init__ を薄い facade に)

**Files:**
- Create: `orgh/orchestrator/scheduler.py`
- Modify: `orgh/orchestrator/__init__.py`

**Interfaces:**
- Consumes: `task_executor.run_task`, `cancellation.*`, `budget_policy.*`
- Produces: `run_mission`, `acquire_mission_lock`, `TERMINAL`, `ready`, `blocked_forever`, `assign_personas`, `with_prompts_snapshot`

- [ ] **Step 1: scheduler.py を作成**(9シンボル移動。`_assign_personas`→`assign_personas` 等公開名化)

- [ ] **Step 2: __init__.py を facade 化** — docstring(現行1-10行)+ 以下のみ:

```python
from .cancellation import CancelledDuringRole as _CancelledDuringRole
from .review_pipeline import review_with_retry as _review_with_retry
from .scheduler import (TERMINAL, acquire_mission_lock, run_mission,
                        assign_personas as _assign_personas)
from .task_executor import (attempt_loop as _attempt_loop,
                            full_worker_prompt as _full_worker_prompt,
                            is_infra_error as _is_infra_error,
                            retry_prompt as _retry_prompt,
                            run_task as _run_task)
```

(アンダースコア alias は既存テストの import 互換のため。新規コードは各サブモジュールから公開名を import する)

- [ ] **Step 3: pytest 全緑を確認** → Run: `pytest -q`

- [ ] **Step 4: Commit**

```bash
git add orgh/orchestrator/
git commit -m "refactor(R-3): MissionSchedulerを抽出、orchestratorを薄いfacadeに"
```

---

### Task 6: 状態遷移の単一 transition 関数へ集約

**Files:**
- Create: `orgh/orchestrator/transitions.py`
- Modify: `orgh/orchestrator/task_executor.py`, `orgh/orchestrator/scheduler.py`, `orgh/orchestrator/review_pipeline.py`, `orgh/orchestrator/cancellation.py`, `orgh/orchestrator/budget_policy.py`

**Interfaces:**
- Produces:

```python
def transition(store, t, status, *, notes=None, event=None, **payload):
    """タスク状態遷移の単一経路。lock下でstatus(と任意でreview_notes)を更新し、
    event指定時はledgerへ記録する。イベント名・payloadは呼び出し側が従来と
    同一のものを渡す(このモジュールは共通化のみで意味づけを持たない)。"""
    with store.lock:
        t.status = status
        if notes is not None:
            t.review_notes = notes
    if event:
        store.log(event, task=t.id, **payload)
```

- [ ] **Step 1: transitions.py を作成**(上記そのまま)

- [ ] **Step 2: 単純な status 設定箇所を transition() 呼び出しへ機械置換** — 対象: status+review_notes(+log)だけを行う箇所。**対象外(現行のまま残す)**: `attempts`/`human_request`/`session_id` 等の付随フィールドを同一lock内で更新する箇所(lockの原子性を保つ)、`initiate_cancel`/`initiate_budget_stop` の全タスク一括ループ(1 lockで全件更新する現行粒度を維持)

- [ ] **Step 3: pytest 全緑を確認** → Run: `pytest -q`

- [ ] **Step 4: Commit**

```bash
git add orgh/orchestrator/
git commit -m "refactor(R-3): 状態遷移を単一transition関数へ集約"
```

---

### Task 7: ドキュメント反映と検証

**Files:**
- Modify: `docs/refactor/execution-architecture.md`(R-3 を「完了」へ、モジュール構成を追記)、`HANDOFF.md`(冒頭に本セッションの記録)

- [ ] **Step 1: pytest 全緑 + `python -m orgh --help` 等の煙試験**
- [ ] **Step 2: code-review スキルで分割差分をレビュー(このリポの標準: 各段階でレビューを通す)**
- [ ] **Step 3: 指摘があれば修正しコミット、ドキュメント更新をコミット**

```bash
git add docs/ HANDOFF.md
git commit -m "docs: R-3完了を記録(orchestratorパッケージ構成・R-1/R-2への申し送り)"
```

---

## Self-Review メモ

- スペック照合: execution-architecture.md R-3 の「あるべき姿」5項目 → MissionScheduler=Task5 / TaskExecutor=Task4 / ReviewPipeline=Task3 / Cancellation・BudgetPolicy=Task2 / transition集約=Task6。全カバー
- 型整合: `run_review_pipeline` の戻り値 `None`(failed確定済み)の扱いは Task 3 Step 3 の呼び出し側と一致
- テスト互換: 内部名を直参照する4ファイル(test_cancel / test_hardening / test_infra_retry / test_personas)のうち、monkeypatch 2件のみ patch 先更新が必要(Task 4)。import のみの参照は facade の alias で無修正互換

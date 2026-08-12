# R-1+R-2: watch/executor分離 + グローバル並行数制御 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** watch を「検知・計画・キュー投入」専任に分離し(R-1)、全orghプロセス横断で worker subprocess の同時数を flock 計数セマフォで制限する(R-2)。docs/refactor/execution-architecture.md の残2件。

**Architecture:** R-2 を先に単体で入れる(独立価値・小さい)。次に R-1: `runs/_queue/` の永続ファイルキュー + 新デーモン `orgh executor`。watch は enqueue して即ポーリングへ戻る。executor はキューを消化し、ミッションごとに従来の run_mission+retro+feedback を回す(mission lock 不変)。

**Tech Stack:** Python 3.11+ / fcntl.flock / pytest(既存362件+新規)

## Global Constraints

- 既存の不変条件を壊さない: mission lock(flock)による二重実行防止、CANCELフラグ経路、prompts スナップショット、自己改変ガード
- `loop.global_parallel` 未設定(None)なら R-2 は完全に無効(挙動不変)。ロール呼び出しは既定でセマフォ対象外
- 各タスク末尾で `pytest -q` 全緑 → 即コミット
- config スキーマ変更は `orgh/state.py` のdataclassと `config.example.yaml` の両方を更新
- playbooks/ 配下の未コミット変更はコミットに含めない

## 設計判断(実装前に確定させたもの)

1. **R-2の実装点**: `BaseAdapter.run` のsubprocess起動を囲む。呼び出し元が slot取得コンテキスト(`orgh/slots.py`)を `run(..., slot=...)` で注入する(adapterはworker cfgしか持たないため)。注入しない呼び出しは従来動作
2. **ロール別枠**: reviewer/persona/planner のロール呼び出しは既定で対象外(`loop.global_role_parallel` で別枠を任意設定可)。workerが本丸(重い・多い)で、ロールを同枠にするとレビュー待ちがworkerスロットを飢餓させ得るため
3. **スロット待機中のキャンセル**: `should_abort` コールバックをslot取得に渡し、CANCEL検知で `WorkerResult(ok=False, output="cancelled while waiting for worker slot")` 相当に落とす(attempt_loopの既存キャンセル分岐が回収する)
4. **R-1のキュー粒度**: watch側で plan() まで実施し「mission_id + note参照」を積む(execution-architecture.mdの記載どおり)。plan中(分単位)の検知停止は受容し、時間単位の実行ブロックだけを解消する
5. **executorの起動形態**: 独立デーモン `orgh executor`。`orgh watch` は `--with-executor` で子プロセスとして併起動できる(移行期の運用互換)。watch停止でexecutorも止まるのは `--with-executor` 時のみ(既定の独立起動なら結合なし)
6. **キューの有界性**: 上限 `watch.queue_limit`(既定20)。満杯時はwatchが着火を見送り(mark_processedしない)、次パスで再試行

---

### Task 1: R-2 slots.py(クロスプロセス計数セマフォ)

**Files:**
- Create: `orgh/slots.py`
- Test: `tests/test_slots.py`

**Interfaces:**
- Produces:

```python
class SlotAborted(Exception): ...

@contextmanager
def acquire_slot(runs_dir: str | Path, limit: int | None, *,
                 pool: str = "workers", poll: float = 0.5,
                 should_abort: Callable[[], bool] | None = None):
    """runs/_slots/<pool>/slot_<i>.lock (i < limit) のどれかを flock (EX|NB) で
    確保できるまで待つ context manager。limit が None/0 以下なら即 yield(無効)。
    should_abort が True を返したら SlotAborted。fdはyield中保持し、exit(または
    プロセス死)で自動解放。"""
```

- [ ] **Step 1: 失敗するテストを書く**(同一プロセス内で limit=2 のとき3つ目の acquire がブロックすること・解放後に取れること・limit=None が即通ること・should_abort で SlotAborted・子プロセスkillでスロットが解放されること(flock特性)。子プロセスは `tests/helpers/` の流儀で `.venv/bin/python -c` により起動)
- [ ] **Step 2: テストが落ちることを確認** → `pytest tests/test_slots.py -v`
- [ ] **Step 3: orgh/slots.py を実装**(スロットファイルは `runs/_slots/<pool>/` に `slot_0.lock`〜。各ファイルを順に open+flock(EX|NB) 試行、全滅なら poll 秒 sleep して再走査。should_abort は走査ごとに確認)
- [ ] **Step 4: テスト全緑** → `pytest -q`
- [ ] **Step 5: Commit** — `feat(R-2): クロスプロセス計数セマフォ orgh/slots.py`

### Task 2: R-2 配線(config + BaseAdapter.run + 呼び出し元)

**Files:**
- Modify: `orgh/state.py`(LoopCfg に `global_parallel: int | None = None`, `global_role_parallel: int | None = None`)
- Modify: `orgh/adapters/base.py`(`run(..., slot=None)`: slotはcontext manager。`with (slot or nullcontext()):` でPopen起動を囲む。SlotAborted捕捉→`WorkerResult(ok=False, output="cancelled while waiting for worker slot")`)
- Modify: `orgh/orchestrator/task_executor.py`(attempt_loop の adapter.run に slot を渡す: `acquire_slot(cfg["runs_dir"], lcfg.get("global_parallel"), should_abort=flag.exists)`)
- Modify: `orgh/planner.py`(`_ask_json` のロール呼び出しに `global_role_parallel` の slot を注入。cfg全体が届いていない場合は None で従来動作)
- Modify: `config.example.yaml`(loopセクションにコメント付きで2キー追記)
- Test: `tests/test_slots.py` に統合ケース追加(mockワーカーで parallel=3・global_parallel=1 のミッションを回し、mock呼び出しの重なりが1以下であること — mockのMOCK_SLEEP_ALL等で滞留させ検証)

- [ ] **Step 1: 失敗するテスト(統合)を書く** → 落ちることを確認
- [ ] **Step 2: LoopCfg / config.example.yaml 追記**
- [ ] **Step 3: BaseAdapter.run の slot 対応**
- [ ] **Step 4: task_executor / planner の注入配線**
- [ ] **Step 5: pytest 全緑** → **Step 6: Commit** — `feat(R-2): グローバル並行数制御を配線(global_parallel、既定無効)`

### Task 3: R-1 queue.py(永続有界キュー)

**Files:**
- Create: `orgh/queue.py`
- Test: `tests/test_queue.py`

**Interfaces:**
- Produces:

```python
def enqueue(runs_dir, mission_id: str, note_path: str | None,
            limit: int = 20) -> bool:
    """runs/_queue/<mission_id>.json を原子的に作成(tmp→rename)。
    既存エントリ数が limit 以上なら False(満杯)。重複IDは冪等にTrue。"""

def claim_next(runs_dir):
    """最古のエントリを flock で claim して (entry_dict, release_fn) を返す。
    無ければ None。claim中のエントリは他プロセスからskipされる。
    release_fn(done=True) でエントリ削除、done=False でclaim解除(再試行可能に)"""

def pending(runs_dir) -> list[dict]:  # 一覧(orgh status / doctor 用)
```

- [ ] **Step 1: 失敗するテストを書く**(FIFO順・満杯False・冪等・claim中スキップ・release(done=False)で再claim可・プロセス死でclaim解除(flock))
- [ ] **Step 2: 落ちることを確認** → **Step 3: 実装** → **Step 4: pytest 全緑**
- [ ] **Step 5: Commit** — `feat(R-1): 永続有界ミッションキュー runs/_queue/`

### Task 4: R-1 executor デーモンと watch の分離

**Files:**
- Create: `orgh/executor.py`(`serve(cfg)`: ループで claim_next → ThreadPool(`watch.parallel_missions`、既定2)で従来のミッション実行一式)
- Modify: `orgh/watcher.py`(run_mission 一式を enqueue に置換。満杯時は mark_processed を取り消せないため、**mark_processed を enqueue 成功後に移動**。writeback は従来どおり着火時に実施)
- Modify: `orgh/cli.py`(`orgh executor` サブコマンド追加、`orgh watch --with-executor` フラグ)
- Modify: `orgh/state.py`(WatchCfg に `queue_limit: int = 20`, `parallel_missions: int = 2`)
- Test: `tests/test_executor.py`(watchパスがenqueueだけして戻ること(既存 one_pass fixture流用)/ executorがキューを消化しミッションが完走すること / executor再起動でキュー内容が残ること / mission lockによりexecutorと手動runが二重実行しないこと)

**executor のミッション実行一式**(watcher.py から移す。挙動不変で移設):
`RunStore(runs_dir, mission_id)` → `store.load()` → `src.feedback(mission_id)` → `run_mission(cfg, mission, store, on_update=fb.update, poll_cancel=fb.cancel_requested)` → `planner.retro_if_finished` → `fb.finalize`。エントリの note_path から src(get_source(cfg))を再構築する。plan失敗の notify_failure は watch 側に残る(mission_id採番前のため)

- [ ] **Step 1: 失敗するテストを書く** → **Step 2: 落ちることを確認**
- [ ] **Step 3: executor.py 実装** → **Step 4: watcher.py を enqueue 化** → **Step 5: cli.py 配線**
- [ ] **Step 6: pytest 全緑(既存 test_watcher_st の期待値更新を含む)**
- [ ] **Step 7: Commit** — `feat(R-1): watch/executor分離(検知とミッション実行の独立ライフサイクル)`

### Task 5: ドキュメント・運用反映

- [ ] execution-architecture.md の R-1/R-2 を完了化(構成・configキー・運用手順)
- [ ] HANDOFF.md 冒頭更新(起動手順の変化: `orgh executor` 併用 or `--with-executor`)
- [ ] README のwatch説明があれば更新
- [ ] code-review スキルで差分レビュー → 指摘対応
- [ ] Commit — `docs: R-1/R-2完了を記録`
- [ ] ミッション0件の窓で watch 停止 → `orgh executor` 起動 → `orgh watch` 再起動(有効化)

## Self-Review メモ

- R-2受け入れ基準: 「別プロセス大量起動でも上限超えない」= flockはプロセス横断 ✓ /「クラッシュで自動解放」= flock特性 ✓(Task 1で子プロセスkillテスト)
- R-1受け入れ基準: 「実行中でも数秒以内に検知・投入」= watchループからrun_mission除去 ✓ /「executor再起動でキュー不失」= ファイル永続 ✓ /「mission lock/cancel/retro回帰なし」= 実行一式を挙動不変で移設+既存テスト ✓
- 既知の受容事項: plan()はwatchループ内に残る(分単位のブロックは受容、doc記載どおり)。burst抑制(投入レート)は今回見送り(R-2のセマフォで実行側は抑まる)

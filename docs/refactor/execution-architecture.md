# 執行アーキテクチャ改修ロードマップ

> **状態: R-3 完了(2026-08-12)、R-1/R-2 未着手**。コードヘルスレビュー(/code-review
> high + Codex、2026-08-12)で確定した deferred 7件のうち、セキュリティ2件・性能索引
> 2件は実装・mainマージ済み。残る3件のうち R-3(orchestrator分割)を同日の集中
> セッションで完了(下記に構成を記載)。次にこの領域を触るセッションは、まずこの
> ファイルを読む。実装計画の記録: `docs/refactor/plans/2026-08-12-r3-orchestrator-split.md`

## なぜ別立てにしたか

この3件は運用モデルそのものを変える最大級の変更で、相互依存する。セキュリティ/性能修正
(小さく外科的)と違い、半端に着手すると危険なため、**腰を据えた集中セッションで一括設計・
実装する**方針で分離した(オーナー裁定 2026-08-12: 「一旦Aで区切る」)。

現状の実害度: **いずれも今の規模(ミッション累計〜30件、単一マシン運用)では顕在化していない。**
スケールした時・多重起動した時に効く。着手優先度は運用規模の伸びに合わせて判断する。

---

## R-1: watch/executor 分離(ヘルスレビュー deferred 大)

**現状の問題**: `orgh/watcher.py` の `watch()` が候補走査ループ内で `run_mission()` を
**同期実行**する。1件が1時間かかればその間は新規ノートを検知しない。複数候補も直列で、
並行ミッション数を増やせない。

**根拠コード**: `orgh/watcher.py:59-91`(`for note in src.list_candidates(): ... run_mission(...)`)

**あるべき姿**:
- watch は「着火判定 → mission ID を**有界キュー**へ投入 → 永続化」までを担当し、即座に次の
  ポーリングへ戻る
- 実行は別の worker pool / プロセスが キューから取り出して `run_mission` を回す
- キューは**永続**(プロセス再起動・クラッシュで消えない)。`runs/_queue/` にファイルとして
  積む案が素直(既存の runs/ ファイル永続の流儀に合う)
- グローバル同時ミッション数は設定で上限(R-3 と統合)

**設計上の注意**:
- 現在 watch は `run_mission` を**同一プロセス内**で回すため、watch を止めると実行中ミッションも
  死ぬ。分離後はこの結合を切る(executor プロセスの独立ライフサイクル)
- GUI/CLI の `orgh run`/`approve`/`resume` は今も個別プロセスで直接 `run_mission` する。
  これらと executor が同じ mission lock(flock)を共有するので二重実行防止は既に効く。
  分離後もこの不変条件を壊さないこと
- キャンセル(CANCEL フラグ)・prompts スナップショット・自己改変ガードは executor 側で従来通り

**受け入れ基準の骨子**:
- watch が長時間ミッション実行中でも新規ノートを数秒以内に検知しキュー投入する
- executor 再起動でキュー内容が失われない
- 既存の mission lock / cancel / retro 経路の回帰なし(pytest 全緑)

---

## R-2: グローバル並行数制御(ヘルスレビュー deferred 中)

**現状の問題**: `loop.parallel` は**1ミッション内**の同時タスク数上限でしかない。プロセスを
またいだ枠が無い。`parallel=3` で 10 ミッションを別々の CLI から同時起動すると、最大 30 の
worker subprocess + reviewer/persona が立ち、API レート制限・メモリ・fd を同時圧迫する。
mission lock は同一ミッションの重複しか防がない。

**根拠コード**: `orgh/orchestrator.py` の `ThreadPoolExecutor(max_workers=workers)`
(`workers = cfg["loop"]["parallel"]`)。`orgh/adapters/base.py:BaseAdapter.run` が worker
subprocess を起動する唯一の経路。

**あるべき姿**:
- runs/ 配下に**クロスプロセスの計数セマフォ**(N個のスロットファイルへ flock で acquire)。
  全 orgh プロセス(watch/executor/GUI起動run/手動CLI)横断で worker subprocess の総同時数を
  上限 N に制限する
- 実装点は `BaseAdapter.run` の subprocess 起動を囲む context manager が素直(全 worker/role が
  必ず通る単一経路)。ただし adapter は worker cfg しか持たないため、runs_dir と上限値の
  注入が要る(get_adapter か run の引数で渡す設計に手を入れる)
- worker と role で別枠にするかは要検討(role=reviewer等は軽いので別枠 or 上限緩め)
- 投入レート(burst 抑制)も併せて検討

**設計上の注意**: R-1 と統合すると綺麗(executor がキュー消化時にグローバル枠を尊重)。
セマフォ単体でも R-1 と独立に価値がある(多重 CLI 起動の暴走防止)。

**受け入れ基準の骨子**:
- 別プロセスから同時に大量ミッションを起動しても、同時 worker 数がグローバル上限を超えない
- スロットはプロセス終了(クラッシュ含む)で自動解放される(flock の性質を使う)

---

## R-3: orchestrator 分割(ヘルスレビュー deferred 中〜大)— **完了 2026-08-12**

**実施結果**: `orgh/orchestrator.py`(653行)を挙動不変の純リファクタでパッケージ
`orgh/orchestrator/` に分割した(pytest 362件を回帰網に、6コミットで段階実施)。

| モジュール | 責務 | 行数 |
|---|---|---|
| `scheduler.py` | DAG解決・並列dispatch・ミッションライフサイクル(lock/prompts snapshot/cancel・予算停止の起動) | 202 |
| `task_executor.py` | 1タスクのattemptループ・worker起動・インフラリトライ・成果コミット | 275 |
| `review_pipeline.py` | reviewer+persona検収の直列裁定・ロールリトライ | 137 |
| `cancellation.py` | CANCELフラグ検知・開始・待機(横断) | 52 |
| `budget_policy.py` | 予算プール用意・超過停止(横断) | 32 |
| `transitions.py` | 状態遷移の単一経路 `transition()`(status+review_notes+ledger記録の共通化) | 24 |
| `__init__.py` | facade(公開API `run_mission`/`acquire_mission_lock`/`TERMINAL` + テスト互換alias) | 25 |

R-1/R-2 が実装点として使う接合部: グローバルセマフォ(R-2)は
`task_executor.attempt_loop` の adapter.run 呼び出しを囲むか `BaseAdapter.run` 内、
executor分離(R-1)は `scheduler.run_mission` を watch から切り離してキュー消化
プロセスに載せ替える形になる。

---

### (記録)分割前の問題

**現状の問題**: `orgh/orchestrator.py` が 644 行の単一モジュールに、workdir 作成・worker retry・
review/persona・予算・キャンセル・worktree・承認・人間依頼・永続化・並列 dispatch を全部
抱える神モジュール。`_attempt_loop` だけでも状態遷移と外部 I/O が密結合。次のゲートや retry
種別を足すたびに、保存・課金・cancel 確認の抜けが生じやすい(本ヘルスレビューで見つかった
複数バグの温床)。

**根拠コード**: `orgh/orchestrator.py` 全体(特に `_attempt_loop`、`_run_mission_locked`)

**あるべき姿**(Codex 提案):
- `MissionScheduler`(DAG 解決・並列 dispatch)
- `TaskExecutor`(1タスクの attempt ループ・worker 起動・成果コミット)
- `ReviewPipeline`(reviewer + persona 検収の直列裁定)
- `Cancellation` / `BudgetPolicy`(横断ポリシー)
- 状態遷移を**単一の transition 関数**へ集約し、各外部呼び出しの前後処理(保存・ledger・
  cancel 確認)を共通化する

**設計上の注意**: これは挙動を変えない**純リファクタ**が理想。362件のテストが回帰網になる
(分割前後で全緑を維持)。R-1/R-2 の土台になるので、着手順は R-3 を先にやると R-1/R-2 が
載せやすい。ただし R-3 単体は大きいので、テストを頼りに小さいコミットに刻むこと。

---

## 着手順の推奨

1. ~~**R-3(orchestrator 分割)を先に**~~ — **完了(2026-08-12)**
2. **R-1 + R-2 をセットで** — 執行を watch から切り離し、キュー消化にグローバルセマフォを効かせる

各段階で pytest 全緑・Codex 検証を通し、main へ載せ、ミッション0件の窓で watch 再起動により
有効化する(このリポの標準運用)。

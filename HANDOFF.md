# orgh ハンドオフ(2026-08-14 更新)

## 設計原則: 実行メカニズム / 制御意味論(2026-08-15 改訂・最優先で読む)

台帳: **ARCH-003 / ARCH-004**(`criteria/arch.md`)。2026-08-14の ARCH-001/002 は
Codex 10ラウンドレビューでFATAL判定を受け**失効**(記録: `docs/strategy/arch-001-002-superseded.md`)。

- 実行層は **実行メカニズム**(スレッド/プロセス管理・ロック実装・スケジューラ実体・隔離手段)と
  **制御意味論**(再開条件・重複実行の防止・人間/外部承認待ちの永続化・監査記録との原子的遷移)に分ける
- メカニズムへの**差別化目的の投資はしない**が、**成果欠落・重複実行・状態不整合・再開不能を防ぐ
  信頼性投資は許可**する。制御意味論はorghが所有し続け、土台へ委譲してはならない(ARCH-003)
- 委譲の判定は「土台の次版で出るか」という予測ではなく、「**永続性・冪等性・障害復旧・監査ID・
  版固定を含む代替契約が実在し、移行試験に合格したか**」という検証で行う(ARCH-004)
- 方向性・機能の取捨・実行順: **`docs/strategy/direction-2026-08.md`**(Phase 0〜2完了・3a'は
  成立条件1件目達成) / アウトカム計測: **`docs/strategy/outcome-2026-08.md`**

## ▶ 次セッションの実行キュー(2026-08-18更新・これが唯一の正)

**やることの全量(条件付き・凍結含む)は `BACKLOG.md`(リポジトリ直下)が正本。完了・着火・棄却は即日反映。**

1. **30日プロトコルの運用**(毎セッション冒頭): 下記「30日運用プロトコル」節の義務を実施
2. **H0① スリープ復帰検知**の実装(条件: worker死亡**かつ**タスク未コミットの場合のみ自動回収。
   コミット済み・外部副作用の疑いがある場合は unknown→人間確認のまま=A5契約を破らない)
3. **3a'成立条件2件目**: 次のcopyback付き実運用ミッションが契約変更なしで通るか
4. **3b'(writeback_pending)**: 3a'成立後に着手(directionの実行順が上位)。着手前にオーナー決定
   ②=ack再提示UXを確認。E1が成功していればpending-action共通基盤と統合設計、E1失敗でも
   3b'自体は独立に実施する(writebackは配達契約でありusage計測と別物)
5. 実装系の介入(outcome/draft等)は**30日プロトコルの結果が出てから**(outcome §3.2)

**判明した要改修**: `criteria_context()` は台帳ファイルの全行を注入する実装のため、台帳に注釈を
書くとそれも規範として注入される。supersede機能と注入対象の限定が必要(詳細は失効記録の末尾)。

## 2026-08-12 R-1/R-2: watch/executor分離+グローバル並行数制御 完了(このセクションが最新)

執行アーキ改修の残り2件を完了。詳細構成は `docs/refactor/execution-architecture.md`。

- **R-2(`orgh/slots.py`)**: 全orghプロセス横断のflock計数セマフォ。
  `loop.global_parallel`(worker)/`loop.global_role_parallel`(ロール)は
  **既定null=無効**。有効化はconfig.yamlに設定を足すだけ(オーナー判断待ち)
- **R-1(`orgh/queue.py` + `orgh/executor.py`)**: watchは検知・計画・
  `runs/_queue/`への投入専任。実行はexecutorがキュー消化で行う
- **運用の変化**: `orgh watch` は従来どおり1コマンドで完結(executorを同プロセス
  併走)。watch停止で実行中ミッションも止まる点は従来と同じ。完全分離したい場合は
  `orgh watch --watch-only` + 別プロセス `orgh executor`(こちらはwatch再起動が
  実行に影響しない)
- テスト 362→384件(slots 9 / queue 8 / executor 5 を新設。watch完走前提の
  既存ST 8件はwatch+drain方式に更新)
- **有効化済み**: ミッション0件の窓でwatch再起動(PID 44406 → **59563**、8/12 18:12頃)。
  `runs/watch.log` に watch+executor 両方の起動ログを確認。R-1/R-2込みの現行コードで稼働中
- 実装後の /code-review high(multi-agent)で確定10件を全対応:
  Ctrl-C時のプールjoinハング(daemonスレッド化)、queueのglob/stat競合・
  壊れエントリ隔離のflock順序・inode同一性claim、enqueue失敗によるノート損失
  (計画後はlimit=Noneで必ず投入)、parallel_missions既定を1に(直列=旧挙動)、
  gcをexecutorアイドル時へ移設(retro追記との排他復元)、_TYPE_MAPにint|None、
  スロット待機のtask.slot_wait記録、queued表示の新設(listing/status_json/GUI型)

## 2026-08-12 R-3: orchestrator分割 完了

執行アーキ改修3件(`docs/refactor/execution-architecture.md`)のうち R-3 を実施。
653行の `orgh/orchestrator.py` を挙動不変の純リファクタでパッケージ分割した
(scheduler / task_executor / review_pipeline / cancellation / budget_policy /
transitions + facade。構成表は execution-architecture.md 参照)。

- 公開API(`run_mission`/`acquire_mission_lock`)のシグネチャ不変。cli.py/watcher.py は無修正
- 既存テストのimport互換は `__init__` のアンダースコアaliasで維持。monkeypatch
  2箇所のみ実参照先モジュールへpatch先を更新(tests/test_cancel.py)
- pytest 362件全緑を各コミットで維持(計画: `docs/refactor/plans/2026-08-12-r3-orchestrator-split.md`)
- 分割後に /code-review high(multi-agent)で挙動不変性を検証。確定4件を修正済み:
  facadeのaliasがmonkeypatch標的として死角になる件(docstring明記+死角alias削除)、
  awaiting_human遷移の重複(transitions.enter_awaiting_humanへ共通化)、
  TERMINALのハードコード5箇所(state.pyへ正準化)、task_timeoutの再lookup
- **有効化済み**: ミッション0件の窓でwatch再起動(旧PID 19676 → 新PID 44406、
  8/12 17:47頃)。以後の出力は `runs/watch.log`(detached起動に変更、PYTHONUNBUFFERED=1)
- 次: R-1(watch/executor分離)+ R-2(グローバル並行数制御)をセットで。
  接合部のメモは execution-architecture.md の R-3 完了記録に記載

## 2026-08-12 コードヘルスレビュー対応

`/code-review high` + Codex の2系統レビューでorghコアを健診し、確定バグ+deferredを対応。

**実装・mainマージ・有効化(watch再起動)済み:**
- ハードニング10件(`25583f9`): task.id/playbook_name/artifactのパストラバーサル封鎖、
  cancelロック、GC状態チェック、watch耐障害、cancel後課金停止、worktree preamble退行、
  cleanup後resume、plan()クラッシュ耐性
- セキュリティ2件(`4daab58`): 検収役の隔離(役割呼び出しに `--setting-sources user` 注入で
  worker生成のCLAUDE.md/.claude設定を無視)、worker env の秘密パターンstrip(認証変数は既定keep)
- 性能索引2件(`aa6a105`): vault走査のmtimeキャッシュ、runs一覧の `runs/_index.json` 終端
  ミッションキャッシュ(GUIポーリングの全読み回避)
- **現行watch = PID 19676(8/12 13:43起動)= 上記すべて反映済み**。テスト362件グリーン

**未着手(オーナー裁定で次回集中セッションへ分離):**
- R-1 watch/executor分離、R-2 グローバル並行数制御、R-3 orchestrator分割(644行の神モジュール)
- この3件は執行アーキの相互依存変更。**次にこの領域を触るセッションは
  `docs/refactor/execution-architecture.md` を最初に読む**(着手順・根拠コード・受け入れ基準を記載)

## 2026-08-11 人間依頼(awaiting_human)実装・GUI耐性確認

mission 3af738a2: headlessなAIワーカーでは恒常的に実行不能なタスク(保護
パスへの書き込み・対面作業・アカウント登録等)を、人間に依頼して完了を待つ
新ステータス `awaiting_human` を実装。t1/t2で基盤とCLI/JSON表示を実装済み
だったが、実装の実体を確認したところ**`orgh humandone` CLIコマンド自体が
未実装**(README/依頼書テンプレ/テストにコマンド名の言及はあるが、
argparseにもハンドラにも存在しなかった)。ドキュメントに「実装済み」として
書くと嘘になるため、本タスクでコマンド実体を追加した(スコープ外への
逸脱ではなく、ドキュメント化に必須の欠落として判断)。

- **新ステータス `awaiting_human`**(t1/t2で実装済み・本タスクでは変更なし):
  `Task.human_request` フィールド、`orgh/status_json.py`/`orgh/listing.py`の
  優先順位(`awaiting_approval` > `awaiting_human`)、結果ノート(vault)への
  🙋アイコン表示
- **新CLI `orgh humandone <mission_id> <task_id> --note "..."`**(本タスクで
  追加。`orgh/cli.py`): `--note`の内容をタスクの成果物(`last_output`)として
  設定し、**通常のReviewer検収と同じ `planner.review()` をそのまま呼ぶ**
  (worker成果と同等の扱い)。合格なら`done`にしてミッション実行を再開し
  (依存タスクがあれば続けて動く)、不合格ならfeedbackを新しい依頼理由として
  再度`awaiting_human`に戻す(試行回数の上限は設けない=HUMAN:転換と同型)。
  対象外(task_id不在・awaiting_human以外の状態)はエラー終了し状態を変えない
- **PROD-001是正(orgh/planner.py `build_human_request`)**: 実際の出力で
  確認したところ、依頼一文が100字超過時に単純な文字数カットで切っており、
  `"...headlessな"` が `"...head…"` のように英単語途中で千切れ、「端的な
  一文」として読みにくい実例を確認した。`_elide()` ヘルパーを追加し、
  切れ目が英数字列の途中に来た場合はその単語ごと落として省略するよう修正
  (例: `"...計画した。…"` のように文の区切りで切れるようになった)
- **desktop/src/types.ts**: `MissionListStatus`/`MissionRunStatus` に
  `"awaiting_human"` を追加(型の正確性のため。表示・導線ロジックの変更は無し)
- **GUI耐性確認**(実装変更ではなく確認作業。詳細は
  [docs/gui-phase2/UNKNOWN-STATUS-RESILIENCE.md](docs/gui-phase2/UNKNOWN-STATUS-RESILIENCE.md)):
  `StatusBadge`は元々未知ステータスに対する安全側フォールバックを持っており、
  未知の`status`文字列・未知のJSONキー(`human_requests`)のいずれも
  クラッシュしない(Rustブリッジ側もserdeの既定でunknownフィールドを無視、
  `status`はenumでなく素の`String`)。承認/再開ボタンの条件式も
  `awaiting_human`単体では誤って活性化しないことを確認済み
- テスト: 295→301件(全緑。`tests/test_humandone.py`を新規追加)。
  `cd desktop && npm run build`(`tsc && vite build`)も終了コード0を確認

**スコープ外として残した事項(申し送り)**:
- **GUIのawaiting_human専用UI**: 専用ラベル・専用導線(依頼書へのリンク、
  humandone実行ボタン等)は本ミッションの禁則により未実装。現状GUIからは
  awaiting_humanミッションに対してキャンセルボタンすら押せない(活性条件が
  `running`/`awaiting_approval`のみのため)。CLIの`orgh cancel`は引き続き使える
- **依頼書の通知連携**: 結果ノート(vault)には🙋表示が追記されるが、
  approval_brief同様、push通知やSlack等の外部アラートは無い。人間側が
  能動的に`orgh status`か結果ノートを見に行かないと依頼に気づけない
- **humandoneのREPLAN:扱いの簡略化**: `orgh humandone`後のReviewer feedbackが
  `REPLAN:`だった場合でも、本実装では計画の再設計(`replan_task`)は行わず、
  HUMAN:と同様にfeedback文言をそのまま新しい依頼理由として`awaiting_human`に
  戻すだけ。acceptance自体に欠陥がある場合の是正導線は無い(将来的に
  `replan_task`相当の呼び出しを足す余地あり)

## 2026-08-11 承認ブリーフ実装

オーナー裁定(台帳 PROD-001 [norm]): 承認・検収などのオーナー接点では、
求める判断の内容を端的な一文で先に提示し、詳細はオーナーが求めたときに
展開表示する(判断材料を探させるUIは不合格)。mission 1adf234eで承認ボタンを
押す際、何を承認するのか分からなかった実例の是正。`feat/approval-brief`
(worktree)で実装、PROD-001の初適用。

- **orgh/guard.py**: `approval_reason(cfg, workdir)` を追加(発火理由を
  人間可読の一文で返す)。`needs_approval` はそのラッパに書き換え、判定規則の
  二重管理を排除
- **orgh/status_json.py**: `status_payload(mission, cfg=None)` に拡張。
  awaiting_approvalタスクが1件以上あるときのみ `approval_brief`
  (summary/gated_tasks/pending_task_count)を追加。cfg未指定時は従来どおり
  省略(GUI後方互換)
- **orgh/cli.py**: `orgh approve` に `--yes` を追加。waiting判定後・APPROVED
  作成前にブリーフをprintし、`--yes` 無し&TTY接続時のみ `y/N` 確認する
  (非TTY・`--yes` は従来どおり即続行。`ORGH_APPROVED=` の契約と出力順は不変)
- **desktop**: MissionDetailPageの「承認する」ボタンが確認ダイアログを
  経由するようになった(summaryを一文表示・詳細は展開)。approval_briefが
  無い旧CLI/旧データでは従来どおり即時承認(graceful degradation)。
  実機Tauriビルドでも届くよう `models.rs` の `MissionStatus` にも
  `approval_brief` を追加(brief記載外だが、無いと実機で機能しないため)
- テスト: 267→280件(全緑)。詳細は
  [.superpowers/sdd/approval-brief/report.md](.superpowers/sdd/approval-brief/report.md)

改修候補(申し送り・a2d8d01a 21時間ゾンビ事例より):
- **watch再起動が実行中ミッションを巻き込む(graceful drainなし)**:
  watchデーモンを再起動すると、実行中のタスクを穏やかに待たずそのまま
  巻き込む。実行中subprocessの生死とdaemon再起動のタイミングが噛み合わない
  ケースの対策が未実装
- **死んだミッションが `orgh list` で `[running]` 表示され続ける
  (プロセス生存確認なし)**: mission.jsonの`status`はプロセスの実死活と
  非同期のため、subprocessが既に死んでいてもrunning表示のまま残り続ける
  (a2d8d01aで21時間ゾンビ状態のまま検出されなかった実例)
- **(2026-08-12追記・同根の裏面)実行中ミッションが status/GUI で全タスク
  [pending] 表示になる**: mission.jsonはタスク完了時にしか保存されないため、
  実行中の task.start がCLI status・デスクトップGUI双方に反映されない
  (fcb7bd7e t1実行中に全タスク待機中表示となった実例。オーナー裁定:
  デスクトップアプリ側との結合不具合として扱う)。上記と合わせ、状態表示は
  mission.jsonスナップショットではなく ledger/procreg との突合で導出する
  改修が正道。「嘘をつくUI」一族としてGUI第2期P0と同格に扱うこと

---

## 2026-08-11 フォローアップ対応

2026-08-10スプリントの検収ゲートに対するオーナー承認済み改修候補4件を
`feat/persona-followups`(worktree)で実装。

- **report指標へのペルソナ折り込み**: `_weekly_stats` が `task.review` に加え
  `task.persona_review` も集計対象にし、初回合格判定を「全イベント合格」に
  変更(直列ゲート構造上reviewer-only履歴とは数値が完全一致=遡及変化なし)。
  ペルソナ差し戻しが初回合格として計上されていた問題を解消
- **evidenceのledger記録**: `persona_review` の戻り値を `tuple[bool, str]` →
  `tuple[bool, str, list[str]]` に変更し、`task.persona_review` イベントへ
  `evidence`(最大10件・各300文字丸め)を記録。監査可能性を確保
- **無効化後resume挙動の明記**: `config.example.yaml`/README に、実行開始
  済みミッションは `personas.enabled` を空に戻しても resume 時はゲートが
  走り続ける旨(ミッション単位の一貫性)を明記。コード変更なし
- **ロールコスト会計**: (a) `_ask_json` で失敗したロール呼び出しのコストも
  `budget.charge`/`cost_sink` へ計上するよう順序を修正(従来は例外raiseが
  先で失敗コールのコストが計上漏れ)。(b) reviewer/ペルソナのコストを
  `t.cost_usd` に合算するようにし、タスク単価とタスク予算チェックが
  worker実行コストのみだった過小評価を解消
- テスト: 263→267件(全緑)。詳細は
  [.superpowers/sdd/followups/report.md](.superpowers/sdd/followups/report.md)

以下「改修候補(申し送り)」4件は本対応で解消(→ 2026-08-11 対応済み。詳細は上記)。

---

## 2026-08-10 GUI第2期マージ済み

- **GUI第2期(mission 4d048081)をmainへマージ**(2df2619)。P0全6件+レポート/Playbook画面。
  Codexレビュー3R(9指摘)+オーナー実機目視済み。同時に実機で発覚した2バグを修正:
  (1) Tauri同期コマンドのメインスレッド凍結 — start/approve/resumeをasync+spawn_blocking化
  (2) 新規プロジェクトの未作成workdir — orchestratorが自動ブートストラップ(mkdir+git init。
  mission eceb49cb「puku-pals」で実測)
- **resumeにORGH_RESUMED確認行契約を追加**(approveのORGH_APPROVEDと同方式)。
  doctorは認証チェック(worker+role)対応。report/playbooks --json追加
- 下記ペルソナ検収ゲート(別セッション)とは追加同士でマージ両立済み(競合2ファイルは両取り解消)。
  マージ後の全テスト260件グリーン。watchデーモンはマージ後コードで再起動済み
- GUI利用のvenv(~/.orgh-venv)はmainリポのeditable installへ再ポイント済み
- config.yaml実測調整: reviewer max_turns 30→50、claude_code worker max_turns 60→100
  (いずれも大型タスクの上限死。4d048081 t2/t7で実証)
- mission eceb49cb(puku-pals=癒し系ゲームアプリ)完走・オーナー検収済み(ドラフト承認、今後改善)。
  成果は ~/projects/puku-pals main
- **prompts/版ずれ対策実装済み(ad3faea)**: run_mission開始時にprompts/を runs/<id>/prompts/ へ
  スナップショットし実行・retroはそれのみを読む。resume時は再スナップショット。
  読み取り先は_prompts_read_dirキーで分離(prompts_dir差し替えは自己改変ガードを壊すため)

## 2026-08-10 スプリント: 判断基準台帳とペルソナ検収ゲート

- **判断基準台帳(criteria)**: `criteria_dir`(既定`criteria`)配下に台帳行
  `- ID [norm]: ... <!-- src:x d:date -->` を保持し、Reviewer・ペルソナ検収の
  文脈に日付降順で自動注入。`orgh verdict <mission_id> --pass|--fail --reason "..."`
  でオーナー裁定を`verdicts.jsonl`とledger(`mission.owner_verdict`)に記録し、
  `criteria/_drafts/<mission_id>-<n>.json` へ台帳差分の下書きを蒸留生成する
  (採番衝突は自動回避)。`orgh criteria list` で下書き+現行台帳を確認、
  `orgh criteria approve <name>` で本台帳へ反映、`orgh criteria reject <name>` で
  `_drafts/rejected/` へ退避(同名衝突は`.2`/`.3`連番)。本台帳への反映経路は
  approveのみ
- **ペルソナ検収ゲート**: `personas.enabled: [consumer, designer]` を設定すると、
  依存されない最終タスク(`apply: final_task`)にReviewer合格後、実ブラウザ/
  スクショ証拠つきの裁定が追加される。証拠なしの合格主張は`ValueError`で
  ロールリトライ、ペルソナ名のtypo(プロンプト欠如)はリトライせず即failed。
  不合格は`[<persona>ペルソナ検収] `プレフィックスで既存の差し戻しループへ
  合流。ledgerイベントは`task.persona_review`/`task.persona_exhausted`。
  ロール設定は`roles.persona_consumer`/`persona_designer`/`criteria_distill`
  (未指定時デフォルト注入、`bin`はreviewer継承)
- **運用手順**: ミッション完走→`orgh verdict`で裁定→`orgh criteria list`で
  下書き確認→`orgh criteria approve`/`reject`。ペルソナ検収を使うには
  `config.yaml`の`personas.enabled`に`consumer`/`designer`を追加するのみ
  (空配列なら従来動作のまま無効)
- **既知の会計上の割り切り**: `task_budget_usd`はworker実行コストのみを
  キャップし、ロール(persona_*/criteria_distill含む)のコストはミッション
  全体の`budget_usd`でのみ制約される。ペルソナ検収コストがタスク単位の
  予算上限に反映されない点は改修候補 → **2026-08-11 対応済み**(下記フォローアップ参照。
  `t.cost_usd`にreviewer/ペルソナのロールコストも合算されるようになった)
- テスト: 195→222件(全緑)
- 戦略設計書: [docs/strategy/2026-08-10-value-strategy-design.md](docs/strategy/2026-08-10-value-strategy-design.md) /
  実装計画: [docs/plans/2026-08-10-criteria-personas-plan.md](docs/plans/2026-08-10-criteria-personas-plan.md)
- **改修候補(申し送り)**:
  - orgh report の first-pass/rework 指標が task.persona_review を見ない
    (ペルソナ差し戻しが初回合格として計上される)→ 柱1の成立条件検証の前に
    _weekly_stats へ折り込み要 → **2026-08-11 対応済み**
  - task.persona_review イベントに evidence を記録していない
    (ゲートの監査可能性のため store.log に evidence を追加)
    → **2026-08-11 対応済み**
  - personas無効化後もmission.jsonのpersonasが残りresumeでゲートが走る
    (ミッションレベル一貫性としては妥当、仕様として明記)
    → **2026-08-11 対応済み**(config.example.yaml/READMEに明記)
  - 失敗ロール呼び出しコストの未計上とペルソナ再実行のコスト増幅
    (task_budget_usdはworker専用キャップ)
    → **2026-08-11 対応済み**

---

## 2026-08-07〜08-10 スプリント(前スプリント)

- **ミッション3本完走→検収→mainマージ済み**: 8e096d63(デスクトップGUI第1期+コア堅牢化、23.6USD)/ a385f876(機能精査監査、12.0USD)/ 02a434ad(GUI第2期ギャップ分析+PRD、7.9USD)
- **Codexレビュー→修正ループ**: GUI 10ラウンド50指摘+監査7ラウンド29指摘、全件検証・修正。orghコアの重大修正多数(approve二重実行のflockロック、ガード先行迂回、ORGH_APPROVED確認行契約、statusの実行中偽装解消、キャンセル系レース群、retro決着ゲート)。pytest 190(+63)
- **監査の決着**: 89機能でKEEP 58/WATCH 29/CANDIDATE 2→オーナー裁定で**削除0件**(ShellAdapterは「モデル非依存方針」で維持、cleanupは「マージ/退避確認後のみ」の条件つき運用化を承認)。台帳=docs/audit/pruning-ledger.md
- **GUI第2期の入力が揃った**: docs/gui-phase2/(ギャップ28件・PRD-PHASE2.md)。P0は「嘘をつくUI」2件(doctorの認証未確認OK表示/runsDirダミーフィールド)。実装ミッションはこのPRDから着火可能
- **watchデーモンはマージ後コードで再起動済み**(2026-08-10)。起動ログ: runs/watch-console.log
- **新ハーネス教訓(未修正)**: Plannerがworkdirをリポ直下に向けたタスクはworktree自動コミットから漏れる(02a434adのt1成果は未追跡置き去り→手動救出、t2はmainへ直接コミットe14a3bc)。②の受け渡し規約とworkdir指定の整合が改修候補
- cleanup運用化の条件「マージ確認の安全ガード」も改修候補(worktree.py: 現状--force+branch -D無条件)

---

# (旧)orgh ハンドオフ(2026-08-05 更新)

実運用フェーズ第2週の引き継ぎ。次セッションはここから読む。
前版(タスクA〜D体制)は完了済み。git logの「実運用で発見」コミット群が変更の実体。

## このスプリント(08-03〜08-05)でやったこと

### ハーネス改修(全て実運用データ起点・テスト127件グリーン)

- **projects_map**(3b5dd0d): ノートにリポパスが無いとPlannerがworkdir "."を出し
  orgh自身で実行される欠陥(7307189e t1が誤リポ走査で3.13 USD浪費)への対処。
  vault側の対応表(`vault/orgh/projects-map.md`)をPlanner文脈に注入
- **codexの自己完結リトライ**(5f3d8bb): resume不可workerが差し戻し時に文脈を失い
  「進めてよいですか?」と質問して死ぬ問題。adapterがsupports_resumeを宣言
- **reviewer max_turns 30**(4f7707a): ビルド再実行を伴うレビューが15で上限死
- **resume完走時のretro実行**(7076ae7): resumeで完走したミッションの教訓が
  playbookに残らないギャップ。RETRO_DONEマーカーで二重追記防止
- **①インフラエラーのattempt非消費リトライ**(664f294): ネットワーク断で
  3attempt≒6.4USD浪費した事例。実測署名のみ検出、上限3回・待機60s
- **④レビューのみリトライ**(53fe4e0): reviewer死でworker成果ごとfailedになる問題
- **②worktree成果物受け渡し**(4aed415): 合格時にタスクブランチへ自動コミット
  (`orgh(<mission>/<task>)`)+依存タスクは依存元ブランチをマージして開始。
  最終タスクのブランチに全成果が積まれ、検収・マージが1ブランチで完結する
- **③REPLANのacceptance制約**(f18d870): 開始前から存在する状態で必ず落ちる
  条件の禁止(t3が未追跡ファイル起因のgitチェックで永久失敗した事例)

### ミッション7307189e(sikore-slot筐体UI刷新)の顛末

全6タスク完走(総額28.68 USD)→ **機械検証は全合格なのに目視検収でUI崩壊が発覚**
(レバー不可視・リール真っ黒)。ユーザー指定のQAワークフローを実施:
全38ユーザーストーリーの棚卸し→カノニカル追跡表→実ブラウザR1テスト→修正23件→R2再テスト。
ドラフト承認済み。成果は sikore-slot の `orgh/7307189e/t5` ブランチ、コミット7dcdb92。
追跡表: `sikore-slot/.orgh-worktrees/7307189e-t5/docs/qa/feature-tracker.csv`。
**mainマージ・デプロイは未実施(ユーザー判断待ち)**。

### 組織学習(playbook)の現在地

- retro是正は機能: 予算トリビアが消え、構造的教訓のみが蒸留されている
  (planning.md 2件、coding.md 2件=共有インターフェース先行定義+UI目視必須)
- D(増幅の数字判定)は初回実測済みだが、N=10・同一週・交絡多数で時期尚早。
  定性的証拠は3つ(retro品質反転・REPLANの前提自己訂正・失敗の資産化6コミット)

## 後続TODO(優先順)

1. **watchデーモンの再起動確認**: configは起動時読込のため、projects_map追加より
   前に起動したwatchには反映されていない。`ps aux | grep "orgh.*watch"` で起動時刻を
   確認し、古ければCtrl-C→ `cd ops && ../.venv/bin/orgh --config ../config.yaml watch`
2. **クリーンな新ミッション2〜3本 → `orgh report` で増幅の数字判定**(D本番)。
   ②の自動コミット受け渡しの実地検証を兼ねる(マルチタスクミッション推奨)
3. **sikore-slotのマージ/デプロイ判断**(ユーザー): `orgh/7307189e/t5` → main。
   残課題はfeature-tracker.csvの「将来課題」参照(iOS実機の音・振動、履歴無上限等)
4. d0d795d4(別軸ノート「スロット筐体のUIが全然現実感ない。」)はcancel済み。
   再開したいときはresumeではなく**ノートを編集して再着火**(watchは内容ハッシュ管理。
   新Plannerがprojects_map込みで正しく計画し直す)
5. サブミッション再帰はDの数字実測後(合意順は不変)

## 後回しでよい改善候補(旧版から継続+新規)

- 観測性: 実行中タスクがmission.jsonでpending表示のまま(真実はledger側)
- REPLAN経緯が結果ノートに出ない(差し戻し理由に併記すべき)
- watchのCtrl-Cが実行中workerの完了を待つ(SIGINT→procreg.terminateにすべき)
- doctorに実プロンプト1発の疎通チェック
- usePerfTierのiPhone一律lite判定(sikore-slot側課題)
- worktree掃除: 検収済みミッションは `orgh cleanup <id>`

## 運用上の注意

- **並行セッション**: org-harnessを同時に触る別セッションが実在し、未コミット作業が
  消えた実例あり(履歴のリベースも発生)。作業は細かく即コミット。開始時にgit logで
  他セッションの痕跡を確認。別セッションは公開準備(英語サマリ・MIT、a11a60f)を進行中
- git identityのホスト名自動検出が壊れることがある(リポローカルに設定済み)。
  orghの自動コミットは明示identity(orgh <orgh@local>)を使う
- watch起動はopsディレクトリから(リポ直下だとworkdir "."が自己改変ガードに触れる)
- 課金: claude -p はサブスク認証のため実費なし。月次クレジット制が再開されたら
  budget_usd を実費上限として復活させること

## 30日運用プロトコル(2026-08-19〜09-17)— セッション引き継ぎ必須
- 正本: `docs/ops/outcome-log-2026-08.md` / 規約: `docs/strategy/outcome-2026-08.md` §3
- セッションAIの義務(週次=セッションが開いた最初の機会):
  ①E1: done済み対象(20USD超orB〜E分類)をログへ登録し、オーナーへ最大3件だけ判定確認(usageと、outcome宣言がある案件はoutcome_resultも)
  ②E2: 起票された調査・分析系ノートに `予算上限:` 行があるか確認、無ければオーナーへ一言
  ③E3: orgh対象(メタ)ノートに「期待する外部効果」行があるか確認。**あわせて新規起票ノート全般に期待変化(outcome宣言)1行があるか確認**、無ければオーナーへ一言
  ④E5: 該当ミッション(目視品質×reference無し)の発生を検知したら、開始前に比較対照をE5補助表へ登録。②確認の5日無応答は保留操作
  ⑤E4: vault `00-Inbox/orgh未起票メモ.md` を確認し、新規行をoutcome-logへroute行として転記
  ⑥30日後(9/17)にE1〜E5の判定レポート作成(E1率の定義はoutcome §3.1)・90日観測分は12月に追跡レポート

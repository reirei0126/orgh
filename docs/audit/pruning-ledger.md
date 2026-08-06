# 不要機能・削除候補台帳(人間承認用)

本台帳は、docs/audit/usecases.json(実際のユースケース24件)・docs/audit/features.json(実装機能89件)・docs/audit/usage-evidence.json(feature_idごとの稼働証跡、features.jsonと1対1対応)を突き合わせ、「どの実装機能がどのユースケースにも紐づかない/使われていない可能性が高いか」を人間が削除可否を判断できる形にまとめたものである。

**このタスクでは実際の削除は一切行っていない。orghのコード・設定への変更もゼロ件。** 削除の実行・承認はすべて人間が行う前提で書かれている。

---

## 1. 判定基準(全機能に機械的に適用)

各機能について以下の2つの値を算出し、下記ルールを**上から順に**適用して1つの判定を確定する。

- **U(紐づくユースケース数)**: usecases.json の `trigger`/`description` と features.json の `entrypoint`/`description` の文言対応で判断した、紐づく usecase_id の数(0件も許容)。判断根拠は台帳表の「判定根拠」列に1文で記載。
- **T(証跡合計)**: usage-evidence.json の `code_refs + test_refs + runtime_hits` の単純合算(該当featureの定義元自身への参照は集計対象外という同ファイルの前提をそのまま踏襲)。

判定ルール(優先順位順):

1. **U = 0**(紐づくユースケースが1件も無い)→ **CANDIDATE**
2. **U ≥ 1 かつ紐づく全usecaseのstatusが `obsolete`** → **CANDIDATE**(現行運用ではもう成立しないユースケースにしか紐づかない)
3. **U ≥ 1 かつ T ≤ 2** → **CANDIDATE**(ユースケースはあるが実装が使われた形跡がほぼ皆無)
4. **U ≥ 1 かつ 3 ≤ T ≤ 9** → **WATCH**(使われているが証跡の厚みが薄い)
5. **U ≥ 1 かつ T ≥ 10** → **KEEP**(現行ユースケースに紐づき、継続使用の証跡も十分)
6. 上記1〜5のいずれについても、「そもそもどのusecase_idに帰属させるべきか、trigger/description上の手掛かりが不十分で一意に判断できない」場合は例外的に **UNKNOWN** とする(今回該当したのは1件のみ、後述)。

### 既知の限界(人間の判断で補正すべき点)

この機械ルールには2つの構造的な弱点があり、CANDIDATE判定の中には「本当に不要」ではなく「評価方法のクセで低く出た」ものが混じっている。個々のCANDIDATE詳細セクションで都度指摘するが、先に一般論として明記する。

1. **パイプライン内部のヘルパー関数**: `run_gc()` が呼ぶ `_backup → _archive_old_lessons → _consolidate → _gc_runs` のように、1つの呼び出し元からしか参照されない内部関数は `code_refs` が構造的に1件しか付かず、実際には毎回まとめて実行されているのに個別ではT≤2になりやすい。
2. **usecases.json自体に載っていない運用コマンド**: `orgh scan`/`orgh list`/`orgh status`/`--config` のように、usecases.jsonの24件が(意図的にせよ見落としにせよ)言及していない周辺コマンドはU=0で機械的にCANDIDATEになるが、これは「usecase台帳の網羅漏れ」の可能性と「本当に不要な機能」の可能性の両方があり、機械ルールだけでは区別できない。

---

## 2. サマリー(全89機能)

| 判定 | 件数 | 意味 |
|---|---|---|
| **KEEP** | 49 | 現行ユースケースに必須。証跡も十分(T≥10)。 |
| **WATCH** | 20 | 現行ユースケースに紐づくが証跡が薄い(3≤T≤9)。定期的な再確認を推奨。 |
| **CANDIDATE** | 19 | 削除候補。紐づくユースケースが無い/obsoleteのみ/証跡がT≤2のいずれか。 |
| **UNKNOWN** | 1 | ユースケースへの一意な帰属を判断する材料が不足。 |
| **合計** | 89 | |

---

## 3. 全機能台帳表

| feature_id | kind | 紐づく usecase_id | 証跡合計(T) | 判定 | 判定根拠 | 人間の承認欄 |
|---|---|---|---|---|---|---|
| `config.example.yaml::gc.retention_days` | config | UC-13 | 6 | **WATCH** | descriptionの「runs/配下の保持期間」がUC-13のruns/アーカイブと一致 | 承認/保留/却下: |
| `config.example.yaml::loop.budget_usd` | config | UC-10, UC-11 | 19 | **KEEP** | descriptionの「超過すると未着手タスクをskippedに」がUC-10(計測)とUC-11(旧・上限停止)の両方に対応 | 承認/保留/却下: |
| `config.example.yaml::loop.max_attempts` | config | UC-06 | 33 | **KEEP** | descriptionの「実行+差し戻しの上限回数」がUC-06のattemptsループそのもの | 承認/保留/却下: |
| `config.example.yaml::loop.parallel` | config | UC-09, UC-01 | 9 | **WATCH** | descriptionのThreadPoolExecutor同時実行数がUC-09(worktree並列実行)の前提設定、run_mission自体はUC-01/02 | 承認/保留/却下: |
| `config.example.yaml::loop.task_budget_usd` | config | UC-10, UC-11 | 16 | **KEEP** | 同上、1タスク単位の上限がUC-10/UC-11に対応 | 承認/保留/却下: |
| `config.example.yaml::loop.task_timeout` | config | (なし) | 8 | **UNKNOWN** | worker subprocess全般のタイムアウト設定で、特定usecaseのtrigger/descriptionに紐づく記述が無くUC-01/02/03いずれにも一様に関わるため単一usecaseへの帰属を判断できない | 承認/保留/却下: |
| `config.example.yaml::playbooks_dir` | config | UC-08, UC-04 | 32 | **KEEP** | descriptionが「Retroが蒸留した組織知の置き場」でUC-08、かつ「自己改変ガードの保護対象」でUC-04と対応 | 承認/保留/却下: |
| `config.example.yaml::projects_map` | config | UC-17 | 13 | **KEEP** | descriptionが「曖昧なノートでも正しいリポで実行させる」でUC-17のprojects_map経由実行と一致 | 承認/保留/却下: |
| `config.example.yaml::prompts_dir` | config | UC-01, UC-04 | 15 | **KEEP** | descriptionが「自己改変ガードの保護対象パス」と明記しUC-04と対応、Plannerテンプレート置き場としてUC-01と対応 | 承認/保留/却下: |
| `config.example.yaml::roles` | config | UC-01, UC-06, UC-08 | 50 | **KEEP** | Planner/Reviewer/Retroの個別設定がUC-01(plan)/UC-06(review)/UC-08(retro)に対応 | 承認/保留/却下: |
| `config.example.yaml::runs_dir` | config | UC-01, UC-02, UC-03, UC-12, UC-13 | 172 | **KEEP** | referenced_byがcli/watcher/gc/report/listing/obsidianと広く、UC-01/02/03/12/13の永続化基盤 | 承認/保留/却下: |
| `config.example.yaml::source.type` | config | UC-01, UC-03, UC-24 | 16 | **KEEP** | descriptionが「将来Notion等を追加する拡張点」と明記しUC-24と直接対応、既定obsidianはUC-01/UC-03 | 承認/保留/却下: |
| `config.example.yaml::vault` | config | UC-01, UC-03 | 112 | **KEEP** | descriptionのObsidianAdapter/doctor参照がUC-01(ノート起点実行)とUC-03(vault監視)に対応 | 承認/保留/却下: |
| `config.example.yaml::watch.gc_interval_days` | config | UC-13, UC-03 | 7 | **WATCH** | descriptionの「watchデーモンが自動でorgh gc相当を実行」がUC-13かつUC-03のトリガー元 | 承認/保留/却下: |
| `config.example.yaml::watch.interval` | config | UC-03 | 15 | **KEEP** | descriptionの「orgh watchのポーリング間隔」がUC-03のtriggerと一致 | 承認/保留/却下: |
| `config.example.yaml::watch.writeback` | config | UC-03 | 20 | **KEEP** | descriptionの「着火直後にノート末尾へ結果ノートへのリンクを追記」がUC-03のvault運用に対応 | 承認/保留/却下: |
| `config.example.yaml::workers.claude_code` | config | UC-01, UC-02 | 93 | **KEEP** | descriptionのClaudeCodeAdapter設定がUC-01/UC-02の既定worker経路 | 承認/保留/却下: |
| `config.example.yaml::workers.codex` | config | UC-19 | 57 | **KEEP** | descriptionのCodexAdapter設定がUC-19のCodexワーカー経路と一致 | 承認/保留/却下: |
| `config.example.yaml::workers.enabled` | config | UC-19, UC-01 | 91 | **KEEP** | descriptionの「doctorの疎通確認対象」がUC-14、claude_code/codex混在利用がUC-19/UC-01 | 承認/保留/却下: |
| `config.example.yaml::workers.shell` | config | UC-23 | 2 | **CANDIDATE** | descriptionが「他LLM CLI用の汎用枠」と明記しUC-23と直接対応 | 承認/保留/却下: |
| `config.example.yaml::worktree` | config | UC-09 | 86 | **KEEP** | descriptionの「タスクごとにgit worktreeを分離」がUC-09のtriggerそのもの | 承認/保留/却下: |
| `orgh/adapters/base.py::BaseAdapter.run` | module | UC-01, UC-02 | 102 | **KEEP** | descriptionの「全workerアダプタ共通のsubprocess実行テンプレート」がUC-01/02の実行基盤 | 承認/保留/却下: |
| `orgh/adapters/base.py::ClaudeCodeAdapter` | integration | UC-01, UC-02 | 54 | **KEEP** | descriptionの「claude CLIをheadlessで叩く」がUC-01/UC-02の既定worker経路 | 承認/保留/却下: |
| `orgh/adapters/base.py::CodexAdapter` | integration | UC-19 | 22 | **KEEP** | descriptionの「codex exec非対話モードで叩く」がUC-19のtriggerそのもの | 承認/保留/却下: |
| `orgh/adapters/base.py::ShellAdapter` | integration | UC-23 | 1 | **CANDIDATE** | descriptionの「任意のCLI LLM(gemini等)」がUC-23のtriggerそのもの | 承認/保留/却下: |
| `orgh/adapters/base.py::get_adapter` | module | UC-01, UC-19 | 79 | **KEEP** | descriptionの「worker名文字列からアダプタを解決」がUC-01(claude_code既定)とUC-19(codex選択) | 承認/保留/却下: |
| `orgh/cli.py::--config` | cli | (なし) | 16 | **CANDIDATE** | 全サブコマンド共通グローバルフラグで、特定usecaseのtrigger/descriptionには現れない | 承認/保留/却下: |
| `orgh/cli.py::approve` | cli | UC-04 | 10 | **KEEP** | entrypointが`orgh approve`でUC-04のtrigger(解除経路)と一致 | 承認/保留/却下: |
| `orgh/cli.py::cancel` | cli | UC-05 | 25 | **KEEP** | entrypointが`orgh cancel`でUC-05のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::cleanup` | cli | UC-21 | 4 | **WATCH** | entrypointが`orgh cleanup`でUC-21のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::doctor` | cli | UC-14 | 10 | **KEEP** | entrypointが`orgh doctor`でUC-14のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::gc` | cli | UC-13 | 38 | **KEEP** | entrypointが`orgh gc`でUC-13のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::list` | cli | (なし) | 77 | **CANDIDATE** | usecases.json全24件中`orgh list`に言及するものが無い(一覧表示の周辺コマンド) | 承認/保留/却下: |
| `orgh/cli.py::report` | cli | UC-12 | 14 | **KEEP** | entrypointが`orgh report`でUC-12のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::resume` | cli | UC-06 | 66 | **KEEP** | descriptionの「差し戻し」「resume」がUC-06のresume経由改善ループと一致 | 承認/保留/却下: |
| `orgh/cli.py::run` | cli | UC-01, UC-02 | 30 | **KEEP** | entrypointが`orgh run --note`/`--intent`でUC-01/UC-02のtriggerそのもの | 承認/保留/却下: |
| `orgh/cli.py::scan` | cli | (なし) | 7 | **CANDIDATE** | usecases.json全24件中`orgh scan`に言及するものが無い(閲覧専用の周辺コマンド) | 承認/保留/却下: |
| `orgh/cli.py::status` | cli | (なし) | 145 | **CANDIDATE** | usecases.json全24件中`orgh status`に言及するものが無い(進捗確認の周辺コマンド) | 承認/保留/却下: |
| `orgh/cli.py::watch` | cli | UC-03 | 54 | **KEEP** | entrypointが`orgh watch`でUC-03のtrigger文言と完全一致 | 承認/保留/却下: |
| `orgh/doctor.py::run_doctor` | module | UC-14 | 1 | **CANDIDATE** | entrypointが`orgh doctor`でUC-14のtriggerと一致 | 承認/保留/却下: |
| `orgh/gc.py::_archive_old_lessons` | module | UC-13 | 1 | **CANDIDATE** | run_gc()のバックアップ後ステップとしてUC-13のgcパイプライン内部処理 | 承認/保留/却下: |
| `orgh/gc.py::_backup` | module | UC-13 | 10 | **KEEP** | run_gc()の最初のステップとしてUC-13のgcパイプライン内部処理 | 承認/保留/却下: |
| `orgh/gc.py::_consolidate` | module | UC-13 | 1 | **CANDIDATE** | run_gc()の退避後ステップとしてUC-13のgcパイプライン内部処理 | 承認/保留/却下: |
| `orgh/gc.py::_gc_runs` | module | UC-13 | 1 | **CANDIDATE** | run_gc()の最終ステップとしてUC-13のruns/アーカイブそのもの | 承認/保留/却下: |
| `orgh/gc.py::run_gc` | module | UC-13 | 5 | **WATCH** | descriptionの「代謝とruns/保持ポリシー適用を厳守の順序で実行」がUC-13のtriggerそのもの | 承認/保留/却下: |
| `orgh/guard.py::needs_approval` | hook | UC-04 | 5 | **WATCH** | descriptionの「自己改変ガード」がUC-04のtriggerそのもの | 承認/保留/却下: |
| `orgh/listing.py::list_missions` | module | (なし) | 15 | **CANDIDATE** | usecases.json全24件中`orgh list`に言及するものが無い | 承認/保留/却下: |
| `orgh/orchestrator.py::_attempt_loop` | module | UC-06 | 77 | **KEEP** | descriptionの「合格/差し戻し」管理がUC-06のattemptsループの実装本体 | 承認/保留/却下: |
| `orgh/orchestrator.py::_initiate_budget_stop` | module | UC-11 | 6 | **CANDIDATE** | descriptionの「未着手タスクをskippedに」がUC-11のtriggerそのもの | 承認/保留/却下: |
| `orgh/orchestrator.py::_initiate_cancel` | module | UC-05 | 3 | **WATCH** | descriptionの「procreg.terminateでSIGTERM」がUC-05のcancel実行部 | 承認/保留/却下: |
| `orgh/orchestrator.py::_is_infra_error` | hook | (なし) | 6 | **CANDIDATE** | usecases.json全24件中インフラエラー判別に言及するものが無い(orchestrator内部の耐障害ロジック) | 承認/保留/却下: |
| `orgh/orchestrator.py::_retry_prompt` | module | UC-06, UC-19 | 27 | **KEEP** | descriptionの「非対応worker(codex等)には自己完結プロンプト」がUC-06(差し戻し)とUC-19(codex特性)の両方 | 承認/保留/却下: |
| `orgh/orchestrator.py::replan_escalation` | hook | UC-07 | 7 | **WATCH** | descriptionの「REPLAN:で始まると自動発火」がUC-07のtriggerそのもの | 承認/保留/却下: |
| `orgh/orchestrator.py::run_mission` | module | UC-01, UC-02, UC-03 | 82 | **KEEP** | descriptionの「DAGに従いThreadPoolExecutorで並列ディスパッチするメインループ」がUC-01/02/03いずれの実行主経路 | 承認/保留/却下: |
| `orgh/planner.py::_playbook_context` | module | UC-08, UC-20 | 3 | **WATCH** | descriptionの「教訓をmax_charsへ詰める」がUC-08の注入機構、UC-20(実ブラウザQA教訓)もこの経路で注入される | 承認/保留/却下: |
| `orgh/planner.py::_projects_context` | module | UC-17 | 5 | **WATCH** | descriptionの「workdir解決の曖昧さを減らす」がUC-17のprojects_map解決と一致 | 承認/保留/却下: |
| `orgh/planner.py::plan` | module | UC-01, UC-02 | 18 | **KEEP** | descriptionの「タスクDAGを得てMissionを生成」がUC-01/UC-02いずれの起点でも呼ばれる | 承認/保留/却下: |
| `orgh/planner.py::replan_task` | module | UC-07 | 9 | **WATCH** | descriptionの「受け入れ条件そのものを再設計」がUC-07のtriggerそのもの | 承認/保留/却下: |
| `orgh/planner.py::retro` | module | UC-08 | 34 | **KEEP** | descriptionの「教訓を抽出しplaybooksへ追記」がUC-08のtriggerそのもの | 承認/保留/却下: |
| `orgh/planner.py::review` | module | UC-06 | 65 | **KEEP** | descriptionの「受け入れ条件を満たすか判定する品質ゲート」がUC-06のレビュー工程そのもの | 承認/保留/却下: |
| `orgh/planner.py::worker_prompt` | module | UC-01, UC-08 | 81 | **KEEP** | descriptionの「playbook注入を埋め込みWorkerへの指示文を組み立てる」がUC-01実行とUC-08のplaybook注入経路 | 承認/保留/却下: |
| `orgh/procreg.py::terminate` | module | UC-05 | 14 | **KEEP** | descriptionの「キャンセル処理がSIGTERM送信に使う」がUC-05の実行部 | 承認/保留/却下: |
| `orgh/report.py::build_report` | report | UC-12 | 5 | **WATCH** | descriptionの「初回attempt合格率/差し戻し率を集計」がUC-12のtriggerそのもの | 承認/保留/却下: |
| `orgh/results.py::ResultsNote` | report | UC-03, UC-05 | 3 | **WATCH** | descriptionの「vault内へミッション進行・結果を書き出す」がUC-03の運用形態、承認待ち警告等はUC-05のcancel表示も含む | 承認/保留/却下: |
| `orgh/results.py::ResultsNote.cancel_requested` | hook | UC-05 | 6 | **WATCH** | descriptionの「#cancelタグ追記で中断できる」がUC-05のvault経由キャンセルと一致 | 承認/保留/却下: |
| `orgh/sources/base.py::SourceAdapter` | module | UC-01, UC-03, UC-24 | 17 | **KEEP** | descriptionの「将来Notion等を追加する拡張点」がUC-24、実装済み経路としてUC-01/UC-03 | 承認/保留/却下: |
| `orgh/sources/base.py::get_source` | module | UC-01, UC-03 | 23 | **KEEP** | descriptionの「config.source.typeでSourceAdapter実装を選択」がUC-01/UC-03双方の起点 | 承認/保留/却下: |
| `orgh/sources/obsidian.py::ObsidianAdapter` | integration | UC-01, UC-03 | 13 | **KEEP** | descriptionの「scan/find/build_context/writeback/feedback」がUC-01(ノート起点実行)とUC-03(監視)双方の実装本体 | 承認/保留/却下: |
| `orgh/sources/obsidian.py::WatchState` | module | UC-03 | 3 | **WATCH** | descriptionの「着火済みノートの再着火を防ぐ」がUC-03のwatchループ専用機構 | 承認/保留/却下: |
| `orgh/sources/obsidian.py::build_context_digest` | module | UC-01 | 9 | **WATCH** | descriptionの「ノート本文とwikilink先を連結」がUC-01のtrigger文言(wikilink先を文脈として)と一致 | 承認/保留/却下: |
| `orgh/sources/obsidian.py::is_triggered` | hook | UC-03 | 9 | **WATCH** | descriptionの「明示着火条件の判定」がUC-03のtrigger文言(#go/orgh:go)と一致 | 承認/保留/却下: |
| `orgh/sources/obsidian.py::scan_vault` | module | UC-01, UC-03 | 10 | **KEEP** | descriptionの「ミッション候補の索引を構築」がUC-01のノート探索とUC-03の監視対象探索 | 承認/保留/却下: |
| `orgh/state.py::Budget` | module | UC-10, UC-11, UC-22 | 38 | **KEEP** | descriptionの「再帰的なタスクのサブミッション分解を前提」がUC-22、charge/exceededがUC-10/UC-11 | 承認/保留/却下: |
| `orgh/state.py::LoopCfg.infra_max_retries` | config | (なし) | 4 | **CANDIDATE** | usecases.json全24件中インフラリトライに言及するものが無い(orchestrator内部の耐障害ロジック) | 承認/保留/却下: |
| `orgh/state.py::RunStore` | module | UC-01, UC-02, UC-03 | 95 | **KEEP** | descriptionの「mission.json/ledger.jsonlを永続化」がUC-01/02/03すべての基盤 | 承認/保留/却下: |
| `orgh/state.py::validate_config` | module | (なし) | 1 | **CANDIDATE** | usecases.json全24件中config検証に言及するものが無い(load_config内部の防御ロジック) | 承認/保留/却下: |
| `orgh/status_json.py::status_payload` | report | (なし) | 9 | **CANDIDATE** | usecases.json全24件中`orgh status --json`に言及するものが無い | 承認/保留/却下: |
| `orgh/watcher.py::_maybe_gc` | hook | UC-13 | 2 | **CANDIDATE** | descriptionの「watchデーモンが定期的にorgh gc相当を自動実行」がUC-13のtrigger(cron経由)と一致 | 承認/保留/却下: |
| `orgh/watcher.py::watch` | module | UC-03 | 54 | **KEEP** | entrypointが`orgh watch`でUC-03のtriggerそのもの | 承認/保留/却下: |
| `orgh/worktree.py::cleanup_mission_worktrees` | integration | UC-21 | 2 | **CANDIDATE** | entrypointが`orgh cleanup`でUC-21のtriggerと一致 | 承認/保留/却下: |
| `orgh/worktree.py::commit_task_result` | integration | UC-09 | 16 | **KEEP** | descriptionの「合格タスクの成果をタスクブランチへコミット」がUC-09の成果受け渡し経路 | 承認/保留/却下: |
| `orgh/worktree.py::ensure_task_worktree` | integration | UC-09 | 40 | **KEEP** | descriptionの「タスクをgit worktreeとブランチに分離」がUC-09のtriggerそのもの | 承認/保留/却下: |
| `orgh/worktree.py::merge_dep_branches` | integration | UC-09 | 1 | **CANDIDATE** | ensure_task_worktree()内部から呼ばれるUC-09パイプラインの一部 | 承認/保留/却下: |
| `prompts/gc.md::gc.md` | prompt | UC-13 | 4 | **WATCH** | descriptionの「重複教訓の統合」がUC-13のgc._consolidate()専用テンプレート | 承認/保留/却下: |
| `prompts/planner.md::planner.md` | prompt | UC-01, UC-02 | 12 | **KEEP** | descriptionの「タスクDAG(JSON)を出力させる」がUC-01/UC-02のplan()呼び出しで使われるテンプレート | 承認/保留/却下: |
| `prompts/replan.md::replan.md` | prompt | UC-07 | 9 | **WATCH** | descriptionの「受け入れ条件を再設計させる」がUC-07のtriggerそのもの | 承認/保留/却下: |
| `prompts/retro.md::retro.md` | prompt | UC-08 | 7 | **WATCH** | descriptionの「構造的に再現しうるパターンだけを蒸留」がUC-08のtriggerそのもの | 承認/保留/却下: |
| `prompts/reviewer.md::reviewer.md` | prompt | UC-06 | 42 | **KEEP** | descriptionの「acceptance自体の検査」がUC-06のレビュー工程そのもの | 承認/保留/却下: |
| `prompts/worker_preamble.md::worker_preamble.md` | prompt | UC-01, UC-08, UC-20 | 77 | **KEEP** | descriptionの「playbook注入を埋め込む」がUC-01実行時のWorker指示文組み立てとUC-08/UC-20の教訓注入経路 | 承認/保留/却下: |

---

## 4. 差分表(a): ユースケースはあるが対応する実装機能が見当たらないもの

usecases.json 24件のうち、上記台帳のどのfeature_idからも紐づけられなかったもの。

| usecase_id | title | status | 見当たらない理由の暫定メモ |
|---|---|---|---|
| UC-15 | orgh自身の機能追加・ドキュメント整備(自己改善ミッション) | active | 「orgh run --note/--intentでworkdirをorgh自身に向けるだけ」の運用パターンであり、UC-01/UC-02の実行機構(`orgh/cli.py::run`, `orgh/planner.py::plan` 等)をそのまま再利用している。専用の実装機能は存在せず、機能不足ではなく「既存機構の使い方の一種」である。 |
| UC-16 | デスクトップGUIプロトタイプ探索(Tauri) | active | デスクトップGUIプロトタイプ(runs/8e096d63)は4タスクとも完了しているが、成果物(desktop/配下)はworktreeブランチに留まりmainへ未マージ。そのためfeatures.jsonのインベントリ(mainブランチのコード)には該当機能が一切現れない。実装自体は(未マージのブランチに)存在するが、現状の棚卸し対象の外にある。 |
| UC-18 | プロダクト説明資料・ピッチ資料の生成(dogfooding) | active | UC-15と同様、orgh run --intentでdocs/product/配下を生成する運用パターンであり、専用のコード機能は無くUC-01/UC-02の実行機構を再利用している。 |

**解釈上の注意**: UC-15/UC-18は「実装が欠けている」のではなく「汎用実行機構(UC-01/UC-02)の適用例」であり緊急の対応は不要。UC-16のみ、既に書かれた実装がmainブランチに存在しない(=このリポジトリの機能インベントリには現れないが、どこかのworktree/ブランチには実体がある可能性がある)という別種の状態であり、確認が必要。

---

## 5. 差分表(b): 実装機能はあるがどのユースケースにも紐づかないもの

feature_id 89件のうち、U=0(またはUNKNOWN)と判定されたもの。

| feature_id | kind | 判定 | 証跡合計(T) | 見当たらない理由 |
|---|---|---|---|---|
| `config.example.yaml::loop.task_timeout` | config | UNKNOWN | 8 | worker subprocess全般のタイムアウト設定で、特定usecaseのtrigger/descriptionに紐づく記述が無くUC-01/02/03いずれにも一様に関わるため単一usecaseへの帰属を判断できない |
| `orgh/cli.py::--config` | cli | CANDIDATE | 16 | 全サブコマンド共通グローバルフラグで、特定usecaseのtrigger/descriptionには現れない |
| `orgh/cli.py::list` | cli | CANDIDATE | 77 | usecases.json全24件中`orgh list`に言及するものが無い(一覧表示の周辺コマンド) |
| `orgh/cli.py::scan` | cli | CANDIDATE | 7 | usecases.json全24件中`orgh scan`に言及するものが無い(閲覧専用の周辺コマンド) |
| `orgh/cli.py::status` | cli | CANDIDATE | 145 | usecases.json全24件中`orgh status`に言及するものが無い(進捗確認の周辺コマンド) |
| `orgh/listing.py::list_missions` | module | CANDIDATE | 15 | usecases.json全24件中`orgh list`に言及するものが無い |
| `orgh/orchestrator.py::_is_infra_error` | hook | CANDIDATE | 6 | usecases.json全24件中インフラエラー判別に言及するものが無い(orchestrator内部の耐障害ロジック) |
| `orgh/state.py::LoopCfg.infra_max_retries` | config | CANDIDATE | 4 | usecases.json全24件中インフラリトライに言及するものが無い(orchestrator内部の耐障害ロジック) |
| `orgh/state.py::validate_config` | module | CANDIDATE | 1 | usecases.json全24件中config検証に言及するものが無い(load_config内部の防御ロジック) |
| `orgh/status_json.py::status_payload` | report | CANDIDATE | 9 | usecases.json全24件中`orgh status --json`に言及するものが無い |

**解釈上の注意**: この10件のうち `orgh/cli.py::list`/`status`/`scan`/`status_payload`/`list_missions` は、日常運用で人間がミッション状況を確認するための周辺CLIコマンドである可能性が高く、T(証跡合計)も高い(list=77, status=145)。usecases.jsonがこれらを1件も明示的なusecaseとして記録していないのは、機能側の不要さではなく「usecase台帳作成時にこの種の閲覧系コマンドを対象外にした」可能性がある。削除より先に「usecases.jsonへの追記漏れではないか」を確認することを推奨する(詳細はセクション6のCANDIDATE詳細参照)。

---

## 6. CANDIDATE機能ごとの詳細(19件)

各項目: 影響範囲(referenced_byから辿れる呼び出し元)/ 削除手順の概要 / 復元容易性 / 削除しない場合のコスト。全機能はgit管理下にあり、削除してもコミット履歴に残るため、復元容易性は原則「高い」(該当コミットをgit revertまたは該当ファイル/関数をgit checkout <commit> -- <path>で復元可能)。個別に注意点がある場合のみ明記する。

### `config.example.yaml::workers.shell` / `orgh/adapters/base.py::ShellAdapter`(UC-23専用、事実上未使用)
- **影響範囲**: `orgh/adapters/base.py`のREGISTRYからのみ参照。`orgh/orchestrator.py`はworker名文字列経由でしか触れないため、config.example.yamlからworkers.shellの例示を消してもClaudeCode/Codexアダプタには影響しない。ただしShellAdapterクラス自体を消すと、`get_adapter("shell")`を指定したタスクは即座にKeyError相当で失敗する。
- **削除手順の概要**: (1) ShellAdapterクラスとREGISTRY登録をorgh/adapters/base.pyから削除、(2) config.example.yamlのworkers.shellセクションを削除、(3) doctorの疎通確認対象からも除外。
- **復元容易性**: 高い(単一ファイル内の1クラス、直近コミット `dde8aa2` 2026-08-03)。
- **削除しない場合のコスト**: 低〜中。config.example.yamlに例示が残り続けると「gemini等の他LLMを使える」という誤解を新規ユーザーに与える保守負担がある一方、コード自体はREGISTRY登録の数行なので放置コストは小さい。UC-23自体は「assumed」(設計上の拡張点)であり実運用実績が0件のため、消しても既存ミッションへの影響はない。

### `orgh/doctor.py::run_doctor`(UC-14専用、T=1)
- **影響範囲**: `orgh/cli.py::doctor`から呼ばれる唯一の実処理。ここを削除すると `orgh doctor` コマンド自体が機能しなくなる(cli.py::doctor自体はT=10でKEEP寄りの証跡を持つため、両者はセットで扱う必要がある)。
- **削除手順の概要**: run_doctor単体の削除は非推奨(cli.py::doctorが直接依存)。もし本当に不要なら`orgh doctor`サブコマンド自体(cli.py::doctor)を含めて削除する必要がある。
- **復元容易性**: 高い(直近コミット `ceef653` 2026-08-02)。
- **削除しない場合のコスト**: 低い。「全タスク謎のfailed」を防ぐ事前診断という位置付けであり、実行ログが残らない設計のため実運用での発火痕跡が薄いだけで、機能自体は軽量(51行)。

### `orgh/gc.py::_archive_old_lessons` / `_consolidate` / `_gc_runs`(UC-13パイプライン内部、各T=1)
- **影響範囲**: いずれも `orgh/gc.py::run_gc` から順に呼ばれる内部ステップ。単体で削除するとrun_gc()全体が壊れ、`orgh gc`コマンドと`orgh/watcher.py::_maybe_gc`(watchデーモンの定期gc)の両方が失敗する。
- **削除手順の概要**: 個別削除は推奨しない。run_gc()パイプライン全体(_backup含む4ステップ)をまとめて評価・削除する必要がある。
- **復元容易性**: 高い(同一コミット `ceef653` 2026-08-02にまとめて導入)。
- **削除しない場合のコスト**: 低い。3関数合計でも44行程度であり、機械的な証跡ルール上は「使われていない」ように見えるが、これは「1呼び出し元からしか参照されない内部ヘルパー」という構造上の理由でT値が低く出ているだけ(セクション1の既知の限界を参照)。**この3件は誤検出の可能性が高いCANDIDATEであり、削除ではなく`run_gc`パイプライン全体を1単位として再評価することを推奨する。**

### `orgh/watcher.py::_maybe_gc`(UC-13、T=2)
- **影響範囲**: `orgh/watcher.py::watch`のループ末尾から毎周呼ばれる。削除するとwatchデーモンの自動gc起動が消え、`orgh gc`を人間が手動実行しない限りplaybook代謝とruns/アーカイブが永久に走らなくなる。
- **削除手順の概要**: watch()内の呼び出し行と_maybe_gc関数本体を削除。config.watch.gc_interval_daysも合わせて整理が必要。
- **復元容易性**: 高い(直近コミット `7076ae7` 2026-08-05)。
- **削除しない場合のコスト**: 低い。usecases.json UC-13自身が「実際の統合・アーカイブ処理が走った痕跡は確認できない」と記録しており、初回パスがベースライン書き込みのみで済む設計のため、証跡が薄いのは想定通りの挙動。14日間隔の初回発火がまだ到来していないだけの可能性が高く、時期尚早な削除判断は避けるべき。

### `orgh/orchestrator.py::_initiate_budget_stop`(UC-11のみ、UC-11はobsolete)
- **影響範囲**: `orgh/orchestrator.py::run_mission`のループから`budget.exceeded()`検知時に呼ばれる。config.loop.budget_usd/task_budget_usdがnull(無制限)である限り`exceeded()`は常にFalseを返すため、現行運用では到達しないコードパス。
- **削除手順の概要**: run_mission内の呼び出し分岐と_initiate_budget_stop本体を削除。ただしBudget/loop.budget_usd自体(UC-10計測用)は残す必要がある。
- **復元容易性**: 高い(直近コミット `4aed415` 2026-08-05)。
- **削除しない場合のコスト**: 中。実際に過去5回発火した実績(2026-08-02時点のledger.jsonl記録)があり、コードとしては健全に動作している。HANDOFF.mdが「月次クレジット制が再開されたらbudget_usdを実費上限として復活させること」と明記しているため、**削除するとその復活作業がゼロからのコード実装に戻ってしまう**。放置コストは「使われない分岐が残る」程度で小さく、削除の実益は薄い。

### `orgh/orchestrator.py::_is_infra_error` / `orgh/state.py::LoopCfg.infra_max_retries`(usecaseに記載なし、実際は稼働実績あり)
- **影響範囲**: `_is_infra_error`はattempt失敗時にorchestrator._attempt_loop内で参照され、ネットワーク断等を通常失敗と区別してattempt非消費リトライに回す。`infra_max_retries`はそのリトライ上限。両者はセットで機能する。削除すると、インフラ起因の一時的エラーが通常の実装失敗として扱われ、attemptsを浪費してタスクがfailedになりやすくなる。
- **削除手順の概要**: 単体では削除しない方がよい。もし削除するなら_attempt_loop内のtry/except分岐ごと簡素化する必要がある。
- **復元容易性**: 高い(直近コミット `664f294`/`4aed415` 2026-08-05)。
- **削除しない場合のコスト**: 低い。むしろ**これはusecases.json側の記載漏れの可能性が高い**(runs/09957da4/ledger.jsonlに実際に`task.infra_retry`イベントが2回記録されており、「接続断による予算浪費事例への対処」というdescriptionの記述とも整合する)。CANDIDATE判定はあくまで「usecases.json 24件のテキストに文言が無い」という機械ルールの結果であり、実態は稼働実績のある耐障害機構である。**削除ではなく、usecases.jsonへのUC追記を検討すべき候補。**

### `orgh/state.py::validate_config`(usecaseに記載なし、T=1)
- **影響範囲**: `load_config()`から直後に自動呼び出しされる唯一の呼び出し元。削除するとconfig.yamlの必須キー欠落・型不一致が実行時まで検知されなくなる(orgh doctorや起動直後のクラッシュで代替検知はされる)。
- **削除手順の概要**: state.py内の関数削除とload_config()からの呼び出し除去。
- **復元容易性**: 高い(直近コミット `664f294` 2026-08-05)。
- **削除しない場合のコスト**: 低い。21行の防御ロジックであり、T=1は「load_config内部からの単一呼び出し」という構造上の理由(セクション1参照)。usecases.jsonに個別のusecaseとして記載されていないのは「config読み込みの前提処理」であって独立した利用シナリオではないためであり、これも誤検出寄りのCANDIDATEと考えられる。

### `orgh/worktree.py::merge_dep_branches`(UC-09パイプライン内部、T=1)
- **影響範囲**: `ensure_task_worktree()`が新規worktree作成直後に自動呼び出し。ensure_task_worktree自体はrun_hits=38の主力機能(KEEP)であり、merge_dep_branchesはその内部ステップにすぎない。単体削除すると依存タスクの成果ブランチが新規worktreeにマージされなくなり、依存関係のあるタスクが前段の成果を見れなくなる(worktree分離の実用性が大きく損なわれる)。
- **削除手順の概要**: 単体削除は非推奨。ensure_task_worktree全体の設計変更とセットで検討すべき。
- **復元容易性**: 高い(直近コミット `4aed415` 2026-08-05)。
- **削除しない場合のコスト**: 低い。18行の内部ヘルパーであり、T=1は「1呼び出し元からしか参照されない」構造上の理由。**誤検出の可能性が高いCANDIDATEであり実質的にはKEEP相当。**

### `orgh/worktree.py::cleanup_mission_worktrees`(UC-21、T=2)
- **影響範囲**: `orgh/cli.py::cleanup`からのみ呼ばれる。削除すると`orgh cleanup`コマンドが機能しなくなる。
- **削除手順の概要**: cli.py::cleanupサブコマンドごと削除するかどうかとセットで判断。
- **復元容易性**: 高い(直近コミット `4aed415` 2026-08-05)。
- **削除しない場合のコスト**: 中。UC-21自身が「HANDOFF.mdの『後回しでよい改善候補』に挙げられたまま未着手」「.orgh-worktrees配下に過去ミッションのworktreeが削除されずに残存」と明記しており、**usecases.json側も実運用で使われていないことを認めている**。放置してもディスク容量を圧迫する程度で機能面の実害は無いが、worktreeが溜まり続ける運用コストは実在する。人間が明示的に`orgh cleanup`を使う運用を始めるか、削除して手動`git worktree remove`に戻すかの二択。

### `orgh/cli.py::scan` / `orgh/cli.py::list` / `orgh/cli.py::status` / `orgh/listing.py::list_missions` / `orgh/status_json.py::status_payload`(usecaseに記載なし、証跡は中〜高)
- **影響範囲**: いずれも独立したCLIサブコマンド(および専用モジュール)であり、run_mission本体のロジックには依存されていない(orchestrator/plannerからは呼ばれない、人間が手動で叩く閲覧系コマンド)。削除しても既存ミッションの実行・レビュー・retroフローには一切影響しない。
- **削除手順の概要**: 各サブコマンド定義をcli.pyから削除し、対応モジュール(listing.py, status_json.py)を削除。scanのみdoctor.pyからの間接参照は無い。
- **復元容易性**: 高い(いずれも直近コミット `4e3e881`/`60b63ef`/`01b9f04`、2026-08-06)。
- **削除しない場合のコスト**: 低い。cli.py::status(T=145)・cli.py::list(T=77)はテストコードからの参照が非常に多く(status:80件、list:25件)、実装として活発にメンテされている形跡がある。**これは「不要な機能」というより「usecases.json側がこの種の運用確認コマンドを棚卸し対象に含め忘れた」可能性が高い。** 削除を急ぐより、まずusecases.jsonにUC-25(仮称:「orgh list/status/scanによる運用中ミッションの確認」)を追記すべきかを人間が判断することを推奨する。

### `orgh/cli.py::--config`(グローバルフラグ、usecaseに記載なし)
- **影響範囲**: 全12サブコマンドが`--config <path>`フラグを共有して利用する基盤機能。削除すると`config.yaml`を切り替えて動かす手段が無くなり、テスト(tests/test_packaging.py等)や複数プロジェクトでの並行運用(config.yamlを使い分けるケース)が壊れる。
- **削除手順の概要**: 削除は推奨しない。
- **復元容易性**: 高い(直近コミット `4e3e881` 2026-08-06)、ただし影響範囲が全サブコマンドに及ぶため復元よりも「削除しないこと」を強く推奨する。
- **削除しない場合のコスト**: ほぼゼロ。**これは典型的な機械ルールの誤検出であり、削除候補として扱うべきではない**(セクション1の既知の限界を参照)。個々のusecaseのtrigger文言が具体的なサブコマンド名しか書いていないため、共通グローバルフラグという性質上どのusecaseの本文にも単独では現れない。

---

## 7. 人間が次に決めること

1. `orgh/gc.py`の`_archive_old_lessons`/`_consolidate`/`_gc_runs`と`orgh/worktree.py::merge_dep_branches`は「パイプライン内部ヘルパーゆえの低評価」と判定した。これらを台帳表の判定どおりCANDIDATE(要削除検討)として個別に承認/却下欄で扱ってよいか、それとも親機能(`run_gc`/`ensure_task_worktree`)とまとめて1単位として扱うべきか。(Yes/No: まとめて1単位として扱う)
2. `orgh/cli.py::scan`/`list`/`status`(及び`listing.py::list_missions`/`status_json.py::status_payload`)がusecases.jsonに載っていないのは、usecase台帳作成時の記載漏れだと考えてよいか。(Yes/No: 記載漏れと認め、usecases.jsonへUCを追記する)
3. `orgh/orchestrator.py::_is_infra_error`と`orgh/state.py::LoopCfg.infra_max_retries`(インフラエラー時のattempt非消費リトライ)も同様にusecases.jsonへの追記漏れと認めてよいか。(Yes/No)
4. `orgh/cli.py::--config`グローバルフラグと`orgh/state.py::validate_config`は、機械ルール上CANDIDATEに分類されたが実質的に削除対象外(構造的必須機能)として扱ってよいか。(Yes/No: 承認欄では「却下」で確定してよい)
5. `orgh/orchestrator.py::_initiate_budget_stop`(および関連するUC-11の予算上限自動停止機構)は、月次クレジット制が再開されるまでコードを残したまま凍結しておいてよいか、それとも今のうちに削除してよいか。(Yes: 凍結して残す / No: 今削除する)
6. `orgh/worktree.py::cleanup_mission_worktrees`(`orgh cleanup`)について、放置されている`.orgh-worktrees`配下の掃除を今後は`orgh cleanup`コマンドを使う運用に切り替えるか。(Yes: 運用に組み込む / No: コマンドごと削除し手動`git worktree remove`に戻す)
7. `config.example.yaml::workers.shell`と`orgh/adapters/base.py::ShellAdapter`(gemini等の任意CLI LLM拡張枠)は、実運用実績が0件のまま今後も設計上の拡張点として維持するか、それとも実際に使う計画が無いなら削除してよいか。(Yes: 維持する / No: 削除する)

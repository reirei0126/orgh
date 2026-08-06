# 不要機能・削除候補台帳(人間承認用)

本台帳は、docs/audit/usecases.json(実際のユースケース28件)・docs/audit/features.json(実装機能89件)・docs/audit/usage-evidence.json(feature_idごとの稼働証跡、features.jsonと1対1対応)を突き合わせ、「どの実装機能がどのユースケースにも紐づかない/使われていない可能性が高いか」を人間が削除可否を判断できる形にまとめたものである。

**このタスクでは実際の削除は一切行っていない。orghのコード・設定への変更もゼロ件。** 削除の実行・承認はすべて人間が行う前提で書かれている。

> **2026-08-07 改訂(レビュー指摘 review-audit-r1 反映)**: 初版(2026-08-06)はU=0を無条件にCANDIDATE化するルールにより、稼働証跡の厚い機能(`orgh status`のT=145等)を「削除候補」と誤誘導していた。本改訂で判定ルールを是正し、usecases.jsonへ欠落していた4ユースケース(UC-25〜UC-28)を追加、内部ヘルパー関数の判定を親機能へ統合し、全該当行を再判定した。変更点の一覧はセクション6bを参照。

---

## 1. 判定基準(全機能に適用)

各機能について以下の2つの値を算出し、下記ルールを**上から順に**適用して1つの判定を確定する。ただし本節末尾の「機械ルールの上書き」に該当する行は、根拠を明記したうえで機械判定を人間が上書きする。

- **U(紐づくユースケース数)**: usecases.json の `trigger`/`description` と features.json の `entrypoint`/`description` の文言対応で判断した、紐づく usecase_id の数(0件も許容)。判断根拠は台帳表の「判定根拠」列に1文で記載。
- **T(証跡合計)**: usage-evidence.json の `code_refs + test_refs + runtime_hits` の単純合算(該当featureの定義元自身への参照は集計対象外という同ファイルの前提をそのまま踏襲)。**T列は異種証跡(静的参照・テスト被覆・実行時マーカー)の単純加算であり、単位も性質も異なる値を足し合わせているに過ぎない。厚みの絶対比較には使わず、あくまで「0に近いか・そうでないか」の粗いシグナルとして読むこと**(詳細は下記「既知の限界」参照)。

判定ルール(優先順位順):

0. **内部ヘルパー関数の統合評価**: 1つの呼び出し元(親のパイプライン関数、または唯一のCLIサブコマンド)からしか参照されない内部関数・実装本体は、独立に下記1〜6を適用せず、**親の判定をそのまま継承する**。親を残す判断をした場合、内部ヘルパーだけを個別に削除候補として承認欄に出さない(理由: 親を残す限りヘルパーも実行され続けるため、独立した削除候補として扱うと「親はKEEP、部品はCANDIDATE」という実行不能な組み合わせが生まれる)。対象例: `orgh/gc.py::_archive_old_lessons`/`_consolidate`/`_gc_runs`(親: `run_gc`)、`orgh/worktree.py::merge_dep_branches`(親: `ensure_task_worktree`)、`orgh/doctor.py::run_doctor`(親: CLIの`orgh/cli.py::doctor`)、`orgh/worktree.py::cleanup_mission_worktrees`(親: CLIの`orgh/cli.py::cleanup`)。
1. **U = 0**(紐づくユースケースが1件も無い)→ 原則 **UNKNOWN**(「本当に不要」なのか「usecase台帳の記載漏れ」なのかを機械ルールだけでは区別できないため、無条件のCANDIDATE化はしない)。ただし、T ≥ 10、または運用文書(HANDOFF.md・README.md・git log等)に実運用を裏付ける明示的な記述がある場合は、記載漏れの可能性が高いとみなし **UNKNOWN ではなく KEEP(T≥10)/WATCH(3≤T≤9)** とする。T ≤ 2 かつ運用文書上の裏付けも無い場合のみ UNKNOWN のまま据え置く。
2. **U ≥ 1 かつ紐づく全usecaseのstatusが `obsolete`**(恒久的に成立しない)→ **CANDIDATE**。ただし紐づく全usecaseのstatusが `dormant`(意図的な休止・復活条件が明記されている)の場合は、恒久的に不要な`obsolete`とは区別し **WATCH以上**(実装本体は凍結保持)とする。
3. **U ≥ 1 かつ T ≤ 2** → **CANDIDATE**(ユースケースはあるが実装が使われた形跡がほぼ皆無)
4. **U ≥ 1 かつ 3 ≤ T ≤ 9** → **WATCH**(使われているが証跡の厚みが薄い)
5. **U ≥ 1 かつ T ≥ 10** → **KEEP**(現行ユースケースに紐づき、継続使用の証跡も十分)
6. 上記1〜5のいずれについても、「そもそもどのusecase_idに帰属させるべきか、trigger/description上の手掛かりが不十分で一意に判断できない」場合は例外的に **UNKNOWN** とする。

### 機械ルールの上書き(2026-08-07 追加)

機械しきい値(特にT≥10のKEEP基準)は出発点にすぎない。個別に強い運用証跡(HANDOFF.md記載の実装確認、全コマンド共通の前提処理であることが実装から明らかである等)があり、かつT値がusecases.json記載漏れ由来の過小評価だとレビューで具体的に指摘された機能については、人間監査者が判定根拠列に上書き理由を明記したうえで機械判定を上書きする。本改訂でこの上書きを適用した行はセクション3の判定根拠列に「(機械しきい値を上書き)」と明記した。

### 既知の限界(人間の判断で補正すべき点)

この機械ルールには構造的な弱点があり、CANDIDATE/WATCH判定の中には「本当に不要」ではなく「評価方法のクセで低く出た」ものが混じり得る。個々の詳細は各セクションで都度指摘するが、先に一般論として明記する。

1. **パイプライン内部のヘルパー関数**: `run_gc()` が呼ぶ `_backup → _archive_old_lessons → _consolidate → _gc_runs` のように、1つの呼び出し元からしか参照されない内部関数は `code_refs` が構造的に1件しか付かず、実際には毎回まとめて実行されているのに個別ではT≤2になりやすい(→ ルール0で対処済み)。
2. **usecases.json自体に載っていない運用コマンド**: `orgh scan`/`orgh list`/`orgh status`/`--config` のように、usecases.jsonの当初24件が(意図的にせよ見落としにせよ)言及していない周辺コマンドはU=0で機械的にCANDIDATEになっていたが、これは「usecase台帳の網羅漏れ」の可能性と「本当に不要な機能」の可能性の両方があり、機械ルールだけでは区別できない(→ ルール1を改訂し、`orgh status`/`orgh list`/`--config`は記載漏れと確認しUC-25〜UC-27を追加。`orgh scan`は運用文書上の強い裏付けが確認できなかったためUNKNOWNではなくWATCHに留め、追加usecaseは見送った)。
3. **異種証跡の単純加算**: `code_refs`(静的参照)・`test_refs`(テスト被覆)・`runtime_hits`(実行時マーカー)は単位も性質も異なる。同一のタスク実行が`_attempt_loop`・`worker_prompt`・`get_adapter`等の複数featureへ独立に重複計上されるため、T値の大小だけで機能同士の「利用の厚み」を序列化してはならない。
4. **検索語が一般語の場合のT値水増し**: `orgh/cli.py::status`・`orgh/cli.py::list`のように検索語が一般的な英単語と一致する機能は、無関係な箇所(`task.status`フィールドアクセス、Python組み込み`list`型等)まで参照として拾ってしまい、T値が実態より大幅に高く出ることがある(是正内容はusage-evidence.md参照)。
5. **ログを残さない機能の過小評価**: `orgh/doctor.py::run_doctor`のように永続的な出力を残さない設計の機能は、実際に頻繁に実行されていてもruntime_hits=0になり、T値だけを見ると「ほぼ未使用」に誤読される。

---

## 2. サマリー(全89機能、2026-08-07 review-audit-r1反映で再集計)

| 判定 | 件数(初版2026-08-06) | 件数(本改訂) | 増減 | 意味 |
|---|---|---|---|---|
| **KEEP** | 49 | **59** | +10 | 現行ユースケースに必須。証跡も十分(T≥10)、または機械しきい値を上書きするだけの強い運用証跡がある。 |
| **WATCH** | 20 | **27** | +7 | 現行ユースケースに紐づくが証跡が薄い(3≤T≤9)、または休止(dormant)ユースケース専属の実装。定期的な再確認を推奨。 |
| **CANDIDATE** | 19 | **3** | −16 | 削除候補。紐づくユースケースが無く運用文書上の裏付けも無い、またはT≤2のいずれか。 |
| **UNKNOWN** | 1 | **0** | −1 | ユースケースへの一意な帰属を判断する材料が不足。 |
| **合計** | 89 | 89 | 0 | |

再集計の内訳(16件がCANDIDATE/UNKNOWNから移動): usecases.json記載漏れが確認できた9機能(`orgh/cli.py::status`・`--config`・`list`、`orgh/listing.py::list_missions`、`orgh/status_json.py::status_payload`、`orgh/orchestrator.py::_is_infra_error`、`orgh/state.py::LoopCfg.infra_max_retries`・`validate_config`、`orgh/worktree.py::merge_dep_branches`)→**KEEP**、CLI/実装本体の統合評価により1機能(`orgh/doctor.py::run_doctor`)→**KEEP**、内部ヘルパー3機能(`orgh/gc.py::_archive_old_lessons`/`_consolidate`/`_gc_runs`)・CLI/実装本体統合1機能(`orgh/worktree.py::cleanup_mission_worktrees`)・休止ユースケース化1機能(`orgh/orchestrator.py::_initiate_budget_stop`)・記載漏れ1機能(`orgh/cli.py::scan`)→**WATCH**、UNKNOWN 1機能(`config.example.yaml::loop.task_timeout`)→複数usecase帰属により**WATCH**。詳細はセクション3・7を参照。

---

## 3. 全機能台帳表

| feature_id | kind | 紐づく usecase_id | 証跡合計(T) | 判定 | 判定根拠 | 人間の承認欄 |
|---|---|---|---|---|---|---|
| `config.example.yaml::gc.retention_days` | config | UC-13 | 6 | **WATCH** | descriptionの「runs/配下の保持期間」がUC-13のruns/アーカイブと一致 | 承認/保留/却下: |
| `config.example.yaml::loop.budget_usd` | config | UC-10, UC-11 | 19 | **KEEP** | descriptionの「超過すると未着手タスクをskippedに」がUC-10(計測)とUC-11(旧・上限停止)の両方に対応 | 承認/保留/却下: |
| `config.example.yaml::loop.max_attempts` | config | UC-06 | 33 | **KEEP** | descriptionの「実行+差し戻しの上限回数」がUC-06のattemptsループそのもの | 承認/保留/却下: |
| `config.example.yaml::loop.parallel` | config | UC-09, UC-01 | 9 | **WATCH** | descriptionのThreadPoolExecutor同時実行数がUC-09(worktree並列実行)の前提設定、run_mission自体はUC-01/02 | 承認/保留/却下: |
| `config.example.yaml::loop.task_budget_usd` | config | UC-10, UC-11 | 16 | **KEEP** | 同上、1タスク単位の上限がUC-10/UC-11に対応 | 承認/保留/却下: |
| `config.example.yaml::loop.task_timeout` | config | UC-01, UC-02, UC-03, UC-06, UC-19 | 8 | **WATCH** | worker subprocess全般のタイムアウト設定で、BaseAdapter.run()経由で全workerが呼ばれる主経路(UC-01/02/03の実行)、差し戻し再実行(UC-06)、Codexワーカー実行(UC-19)いずれの呼び出しにも一様に適用される。単一usecaseに帰属できないことは「他機能との基準が一致しないUNKNOWN」の理由にはならないため、複数usecase帰属として再算定(T=8は3〜9のWATCH域) | 承認/保留/却下: |
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
| `orgh/cli.py::--config` | cli | UC-27 | 16 | **KEEP** | UC-27(任意の作業ディレクトリから明示configで起動)を追加。HANDOFF.md:47のwatch再起動手順`orgh --config ../config.yaml watch`が実運用での必須手順であることを確認しUNKNOWNから復帰(usecase台帳の記載漏れだったと判明) | 承認/保留/却下: |
| `orgh/cli.py::approve` | cli | UC-04 | 10 | **KEEP** | entrypointが`orgh approve`でUC-04のtrigger(解除経路)と一致 | 承認/保留/却下: |
| `orgh/cli.py::cancel` | cli | UC-05 | 25 | **KEEP** | entrypointが`orgh cancel`でUC-05のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::cleanup` | cli | UC-21 | 4 | **WATCH** | entrypointが`orgh cleanup`でUC-21のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::doctor` | cli | UC-14 | 10 | **KEEP** | entrypointが`orgh doctor`でUC-14のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::gc` | cli | UC-13 | 38 | **KEEP** | entrypointが`orgh gc`でUC-13のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::list` | cli | UC-26 | 4(旧77は「list」一般語検索による水増し。usage-evidence.md参照) | **KEEP** | UC-26(全ミッション一覧確認)を追加。ops/demo/runs/099e281bはこの機能自体を追加したミッションで、README.mdのデモ節が実演記録として明記。T値は是正後4(WATCH域)だが、記載漏れ由来の過小評価だったことがレビューで確認済みのため機械しきい値を上書きしKEEPとする(機械しきい値を上書き) | 承認/保留/却下: |
| `orgh/cli.py::report` | cli | UC-12 | 14 | **KEEP** | entrypointが`orgh report`でUC-12のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::resume` | cli | UC-06 | 66 | **KEEP** | descriptionの「差し戻し」「resume」がUC-06のresume経由改善ループと一致 | 承認/保留/却下: |
| `orgh/cli.py::run` | cli | UC-01, UC-02 | 30 | **KEEP** | entrypointが`orgh run --note`/`--intent`でUC-01/UC-02のtriggerそのもの | 承認/保留/却下: |
| `orgh/cli.py::scan` | cli | (なし) | 7 | **WATCH** | usecases.json全28件中`orgh scan`に言及するものが無いが、T=7は無関係な語のヒットではない実質的な参照(cli.py/doctor.py/sources配下)であり0に近くない。ルール1改訂によりUNKNOWNではなくWATCH域として再判定(記載漏れの可能性は残るが、本改訂ではusecase追加の裏付けとなる運用文書上の明示記述までは確認できなかったため追加は見送り) | 承認/保留/却下: |
| `orgh/cli.py::status` | cli | UC-25 | 9(旧145は「status」一般語検索による水増し。usage-evidence.md参照) | **KEEP** | UC-25(単一ミッションの状態確認)を追加。ops/demo/runs/099e281bはこの機能自体を追加したミッションで、README.mdのデモ節が実演記録として明記。T値は是正後9(WATCH域上限)だが、記載漏れ由来の過小評価だったことがレビューで確認済みのため機械しきい値を上書きしKEEPとする(機械しきい値を上書き) | 承認/保留/却下: |
| `orgh/cli.py::watch` | cli | UC-03 | 54 | **KEEP** | entrypointが`orgh watch`でUC-03のtrigger文言と完全一致 | 承認/保留/却下: |
| `orgh/doctor.py::run_doctor` | module | UC-14 | 1 | **KEEP** | `orgh/cli.py::doctor`の唯一の実処理本体。CLIサブコマンドと実装本体は同一評価単位とするルール(1章ルール0)により親の判定(KEEP, T=10)を継承。T=1は永続ログを残さない設計上の構造的特性であり利用実績の低さではない | 承認/保留/却下: 承認不要(`orgh/cli.py::doctor`に統合、独立審査対象外) |
| `orgh/gc.py::_archive_old_lessons` | module | UC-13 | 1 | **WATCH** | run_gc()のバックアップ後ステップ。内部ヘルパーは親と同一判定とするルール(1章ルール0)により`run_gc`(WATCH, T=5)の判定を継承 | 承認/保留/却下: 承認不要(`run_gc`に統合、独立審査対象外) |
| `orgh/gc.py::_backup` | module | UC-13 | 10 | **KEEP** | run_gc()の最初のステップとしてUC-13のgcパイプライン内部処理 | 承認/保留/却下: |
| `orgh/gc.py::_consolidate` | module | UC-13 | 1 | **WATCH** | run_gc()の退避後ステップ。内部ヘルパーは親と同一判定とするルール(1章ルール0)により`run_gc`(WATCH, T=5)の判定を継承 | 承認/保留/却下: 承認不要(`run_gc`に統合、独立審査対象外) |
| `orgh/gc.py::_gc_runs` | module | UC-13 | 1 | **WATCH** | run_gc()の最終ステップ。内部ヘルパーは親と同一判定とするルール(1章ルール0)により`run_gc`(WATCH, T=5)の判定を継承 | 承認/保留/却下: 承認不要(`run_gc`に統合、独立審査対象外) |
| `orgh/gc.py::run_gc` | module | UC-13 | 5 | **WATCH** | descriptionの「代謝とruns/保持ポリシー適用を厳守の順序で実行」がUC-13のtriggerそのもの | 承認/保留/却下: |
| `orgh/guard.py::needs_approval` | hook | UC-04 | 5 | **WATCH** | descriptionの「自己改変ガード」がUC-04のtriggerそのもの | 承認/保留/却下: |
| `orgh/listing.py::list_missions` | module | UC-26 | 15 | **KEEP** | UC-26(全ミッション一覧確認)を追加。`orgh/cli.py::list`の唯一の実処理本体で、tests/test_list.py(14件)による専用テストも既存。T=15は元々T≥10のKEEP域であり是正不要 | 承認/保留/却下: |
| `orgh/orchestrator.py::_attempt_loop` | module | UC-06 | 77 | **KEEP** | descriptionの「合格/差し戻し」管理がUC-06のattemptsループの実装本体 | 承認/保留/却下: |
| `orgh/orchestrator.py::_initiate_budget_stop` | module | UC-11 | 6 | **WATCH** | descriptionの「未着手タスクをskippedに」がUC-11のtriggerそのもの。UC-11のstatusを`obsolete`から`dormant`(休止・復活条件あり)へ訂正したため、1章ルール2により恒久不要のCANDIDATEではなくWATCH(凍結保持)とする。runtime_hits=5(task.budget_exceeded)は過去の実運用での実発火実績 | 承認/保留/却下: |
| `orgh/orchestrator.py::_initiate_cancel` | module | UC-05 | 3 | **WATCH** | descriptionの「procreg.terminateでSIGTERM」がUC-05のcancel実行部 | 承認/保留/却下: |
| `orgh/orchestrator.py::_is_infra_error` | hook | UC-28 | 6 | **KEEP** | UC-28(インフラ障害のattempt非消費リトライ)を追加。HANDOFF.md:18が実運用でのネットワーク断3attempt≒6.4USD浪費事例への対処と明記し、runs/09957da4/ledger.jsonlに`task.infra_retry`が2件実記録。T=6はWATCH域だが実障害由来の耐障害機構という強い運用証跡によりKEEPへ上書き(機械しきい値を上書き) | 承認/保留/却下: |
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
| `orgh/state.py::LoopCfg.infra_max_retries` | config | UC-28 | 4 | **KEEP** | UC-28(インフラ障害のattempt非消費リトライ)を追加。`_is_infra_error`とセットで機能するリトライ上限設定であり、同一の根拠(HANDOFF.md:18、runs/09957da4/ledger.jsonlのtask.infra_retry×2)によりKEEPへ上書き(機械しきい値を上書き) | 承認/保留/却下: |
| `orgh/state.py::RunStore` | module | UC-01, UC-02, UC-03 | 95 | **KEEP** | descriptionの「mission.json/ledger.jsonlを永続化」がUC-01/02/03すべての基盤 | 承認/保留/却下: |
| `orgh/state.py::validate_config` | module | (横断的: 全usecase共通の前提処理) | 1 | **KEEP** | `load_config()`が全CLIコマンドで設定読込直後に無条件で呼ぶ唯一の呼び出し元であり、T=1は「1箇所からしか呼ばれない」構造上の特性であってその1箇所が全実行の入口であることを意味する。特定usecaseに紐づけるのではなく横断的前提機能としてKEEPへ上書き(機械しきい値を上書き) | 承認/保留/却下: |
| `orgh/status_json.py::status_payload` | report | UC-25 | 9 | **KEEP** | UC-25(単一ミッションの状態確認)を追加。`orgh/cli.py::status --json`の唯一の実処理本体で、tests/test_status_json.py(7件)による専用テストも既存。T=9はWATCH域上限だが親CLI(status, KEEP)と同一評価単位として扱いKEEPへ上書き(機械しきい値を上書き) | 承認/保留/却下: |
| `orgh/watcher.py::_maybe_gc` | hook | UC-13 | 2 | **CANDIDATE** | descriptionの「watchデーモンが定期的にorgh gc相当を自動実行」がUC-13のtrigger(cron経由)と一致 | 承認/保留/却下: |
| `orgh/watcher.py::watch` | module | UC-03 | 54 | **KEEP** | entrypointが`orgh watch`でUC-03のtriggerそのもの | 承認/保留/却下: |
| `orgh/worktree.py::cleanup_mission_worktrees` | integration | UC-21 | 2 | **WATCH** | `orgh/cli.py::cleanup`の唯一の実処理本体。CLIサブコマンドと実装本体は同一評価単位とするルール(1章ルール0)により親の判定(WATCH, T=4)を継承 | 承認/保留/却下: 承認不要(`orgh/cli.py::cleanup`に統合、独立審査対象外) |
| `orgh/worktree.py::commit_task_result` | integration | UC-09 | 16 | **KEEP** | descriptionの「合格タスクの成果をタスクブランチへコミット」がUC-09の成果受け渡し経路 | 承認/保留/却下: |
| `orgh/worktree.py::ensure_task_worktree` | integration | UC-09 | 40 | **KEEP** | descriptionの「タスクをgit worktreeとブランチに分離」がUC-09のtriggerそのもの | 承認/保留/却下: |
| `orgh/worktree.py::merge_dep_branches` | integration | UC-09 | 1 | **KEEP** | ensure_task_worktree()内部から呼ばれるUC-09パイプラインの一部。内部ヘルパーは親と同一判定とするルール(1章ルール0)により`ensure_task_worktree`(KEEP, T=40)の判定を継承 | 承認/保留/却下: 承認不要(`ensure_task_worktree`に統合、独立審査対象外) |
| `prompts/gc.md::gc.md` | prompt | UC-13 | 4 | **WATCH** | descriptionの「重複教訓の統合」がUC-13のgc._consolidate()専用テンプレート | 承認/保留/却下: |
| `prompts/planner.md::planner.md` | prompt | UC-01, UC-02 | 12 | **KEEP** | descriptionの「タスクDAG(JSON)を出力させる」がUC-01/UC-02のplan()呼び出しで使われるテンプレート | 承認/保留/却下: |
| `prompts/replan.md::replan.md` | prompt | UC-07 | 9 | **WATCH** | descriptionの「受け入れ条件を再設計させる」がUC-07のtriggerそのもの | 承認/保留/却下: |
| `prompts/retro.md::retro.md` | prompt | UC-08 | 7 | **WATCH** | descriptionの「構造的に再現しうるパターンだけを蒸留」がUC-08のtriggerそのもの | 承認/保留/却下: |
| `prompts/reviewer.md::reviewer.md` | prompt | UC-06 | 42 | **KEEP** | descriptionの「acceptance自体の検査」がUC-06のレビュー工程そのもの | 承認/保留/却下: |
| `prompts/worker_preamble.md::worker_preamble.md` | prompt | UC-01, UC-08, UC-20 | 77 | **KEEP** | descriptionの「playbook注入を埋め込む」がUC-01実行時のWorker指示文組み立てとUC-08/UC-20の教訓注入経路 | 承認/保留/却下: |

---

## 4. 差分表(a): ユースケースはあるが対応する実装機能が見当たらないもの

usecases.json 28件(2026-08-07改訂でUC-25〜UC-28を追加)のうち、上記台帳のどのfeature_idからも紐づけられなかったもの。UC-25〜UC-28はいずれも対応する実装機能(cli.py::status/list/--config、orchestrator.py::_is_infra_error等)が紐づいたため、このセクションには現れない。

| usecase_id | title | status | 見当たらない理由の暫定メモ |
|---|---|---|---|
| UC-15 | orgh自身の機能追加・ドキュメント整備(自己改善ミッション) | active | 「orgh run --note/--intentでworkdirをorgh自身に向けるだけ」の運用パターンであり、UC-01/UC-02の実行機構(`orgh/cli.py::run`, `orgh/planner.py::plan` 等)をそのまま再利用している。専用の実装機能は存在せず、機能不足ではなく「既存機構の使い方の一種」である。 |
| UC-16 | デスクトップGUIプロトタイプ探索(Tauri) | active | デスクトップGUIプロトタイプ(runs/8e096d63)は4タスクとも完了しているが、成果物(desktop/配下)はworktreeブランチに留まりmainへ未マージ。そのためfeatures.jsonのインベントリ(mainブランチのコード)には該当機能が一切現れない。実装自体は(未マージのブランチに)存在するが、現状の棚卸し対象の外にある。 |
| UC-18 | プロダクト説明資料・ピッチ資料の生成(dogfooding) | active | UC-15と同様、orgh run --intentでdocs/product/配下を生成する運用パターンであり、専用のコード機能は無くUC-01/UC-02の実行機構を再利用している。 |

**解釈上の注意**: UC-15/UC-18は「実装が欠けている」のではなく「汎用実行機構(UC-01/UC-02)の適用例」であり緊急の対応は不要。UC-16のみ、既に書かれた実装がmainブランチに存在しない(=このリポジトリの機能インベントリには現れないが、どこかのworktree/ブランチには実体がある可能性がある)という別種の状態であり、確認が必要。

---

## 5. 差分表(b): 実装機能はあるがどのユースケースにも紐づかないもの

feature_id 89件のうち、U=0と判定されたもの(2026-08-07改訂版)。

| feature_id | kind | 判定 | 証跡合計(T) | 見当たらない理由 |
|---|---|---|---|---|
| `orgh/cli.py::scan` | cli | WATCH | 7 | usecases.json全28件中`orgh scan`に言及するものが無い。T=7は無視できない実質的な参照があるためWATCHとし、UNKNOWN/CANDIDATEにはしない(1章ルール1) |

**解釈上の注意**: 初版(2026-08-06)ではこの表に10件が並び、うち`orgh/cli.py::list`/`status`/`scan`/`status_payload`/`list_missions`はT値が高い(list=77, status=145)にもかかわらずCANDIDATE化されていた。レビュー指摘(review-audit-r1)により、これらのT値のうちlist/statusは「list」「status」という一般語の行ヒット水増しだったこと、および`--config`・`orgh/orchestrator.py::_is_infra_error`・`orgh/state.py::LoopCfg.infra_max_retries`・`orgh/state.py::validate_config`・`orgh/status_json.py::status_payload`・`orgh/listing.py::list_missions`の9件はusecases.json側の記載漏れであったことが確認できたため、UC-25〜UC-28を追加のうえ全てKEEPへ再判定した(セクション3参照)。残るのは`orgh/cli.py::scan`のみで、こちらは運用文書上の明示的な裏付けが本改訂では確認できなかったためusecase追加は見送り、WATCHとして次回監査へ持ち越す。

---

## 6. CANDIDATE機能ごとの詳細(2026-08-07改訂: 3件)

各項目: 影響範囲(referenced_byから辿れる呼び出し元)/ 削除手順の概要 / 復元容易性 / 削除しない場合のコスト。全機能はgit管理下にあり、削除してもコミット履歴に残るため、復元容易性は原則「高い」(該当コミットをgit revertまたは該当ファイル/関数をgit checkout <commit> -- <path>で復元可能)。個別に注意点がある場合のみ明記する。

**2026-08-07改訂の注記**: 初版(2026-08-06)では本セクションに19件のCANDIDATEが並んでいたが、レビュー指摘(review-audit-r1)によりU=0の無条件CANDIDATE化ルールの誤りが指摘され、16件がKEEP/WATCHへ再判定された。再判定の詳細な理由・移動元は「6b. このレビューで判定が変更された機能」を参照。以下は再判定後も真にCANDIDATE(削除候補として人間の判断を仰ぐべき)のまま残った3件のみを扱う。

### `config.example.yaml::workers.shell` / `orgh/adapters/base.py::ShellAdapter`(UC-23専用、事実上未使用)
- **影響範囲**: `orgh/adapters/base.py`のREGISTRYからのみ参照。`orgh/orchestrator.py`はworker名文字列経由でしか触れないため、config.example.yamlからworkers.shellの例示を消してもClaudeCode/Codexアダプタには影響しない。ただしShellAdapterクラス自体を消すと、`get_adapter("shell")`を指定したタスクは即座にKeyError相当で失敗する。
- **削除手順の概要**: (1) ShellAdapterクラスとREGISTRY登録をorgh/adapters/base.pyから削除、(2) config.example.yamlのworkers.shellセクションを削除、(3) doctorの疎通確認対象からも除外。
- **復元容易性**: 高い(単一ファイル内の1クラス、直近コミット `dde8aa2` 2026-08-03)。
- **削除しない場合のコスト**: 低〜中。config.example.yamlに例示が残り続けると「gemini等の他LLMを使える」という誤解を新規ユーザーに与える保守負担がある一方、コード自体はREGISTRY登録の数行なので放置コストは小さい。UC-23自体は「assumed」(設計上の拡張点)であり実運用実績が0件のため、消しても既存ミッションへの影響はない。今回のレビューではこの2件について指摘が無かったため判定は変更していない。

### `orgh/watcher.py::_maybe_gc`(UC-13、T=2)
- **影響範囲**: `orgh/watcher.py::watch`のループ末尾から毎周呼ばれる。削除するとwatchデーモンの自動gc起動が消え、`orgh gc`を人間が手動実行しない限りplaybook代謝とruns/アーカイブが永久に走らなくなる。
- **削除手順の概要**: watch()内の呼び出し行と_maybe_gc関数本体を削除。config.watch.gc_interval_daysも合わせて整理が必要。
- **復元容易性**: 高い(直近コミット `7076ae7` 2026-08-05)。
- **削除しない場合のコスト**: 低い。usecases.json UC-13自身が「実際の統合・アーカイブ処理が走った痕跡は確認できない」と記録しており、初回パスがベースライン書き込みのみで済む設計のため、証跡が薄いのは想定通りの挙動。14日間隔の初回発火がまだ到来していないだけの可能性が高く、時期尚早な削除判断は避けるべき。**注記**: 構造的には`orgh/gc.py`の内部ヘルパー3件と同様に「1呼び出し元(`watch()`)からしか参照されない」パターンに見えるが、今回のレビュー指摘はこの機能を対象に含めていなかったため、スコープ外として判定は変更していない(根拠のない判定変更を避けるため)。次回監査で親子統合ルール(1章ルール0)の適用要否を再検討することを推奨する。

---

## 6b. このレビューで判定が変更された機能(review-audit-r1反映、16件)

| feature_id | 旧判定 | 新判定 | 変更理由(要約) |
|---|---|---|---|
| `config.example.yaml::loop.task_timeout` | UNKNOWN | WATCH | UC-01/02/03/06/19への複数usecase帰属に再算定。単一帰属できないことはUNKNOWNの理由にならない |
| `orgh/cli.py::--config` | CANDIDATE | KEEP | UC-27(明示config起動)追加。HANDOFF.mdのwatch再起動手順に必須と確認 |
| `orgh/cli.py::list` | CANDIDATE | KEEP | UC-26(全ミッション一覧確認)追加。旧T=77は「list」一般語水増しと判明、是正後T=4だが記載漏れ由来のため上書きKEEP |
| `orgh/cli.py::status` | CANDIDATE | KEEP | UC-25(単一ミッション状態確認)追加。旧T=145は「status」一般語水増しと判明、是正後T=9だが記載漏れ由来のため上書きKEEP |
| `orgh/doctor.py::run_doctor` | CANDIDATE | KEEP | CLIと実装本体の統合評価ルールにより`orgh/cli.py::doctor`(KEEP)の判定を継承 |
| `orgh/gc.py::_archive_old_lessons` | CANDIDATE | WATCH | 内部ヘルパー統合評価ルールにより`run_gc`(WATCH)の判定を継承 |
| `orgh/gc.py::_consolidate` | CANDIDATE | WATCH | 同上 |
| `orgh/gc.py::_gc_runs` | CANDIDATE | WATCH | 同上 |
| `orgh/listing.py::list_missions` | CANDIDATE | KEEP | UC-26追加。T=15はもともとKEEP域であり是正不要 |
| `orgh/orchestrator.py::_initiate_budget_stop` | CANDIDATE | WATCH | UC-11のstatusをobsolete→dormant(休止・復活条件あり)に訂正したことに伴い、恒久不要のCANDIDATEから凍結保持のWATCHへ |
| `orgh/orchestrator.py::_is_infra_error` | CANDIDATE | KEEP | UC-28(インフラ障害の非消費リトライ)追加。実障害事例(HANDOFF.md:18)・ledger実績(task.infra_retry×2)により上書きKEEP |
| `orgh/state.py::LoopCfg.infra_max_retries` | CANDIDATE | KEEP | 同上(_is_infra_errorとセットの機能) |
| `orgh/state.py::validate_config` | CANDIDATE | KEEP | 全コマンド共通の前提処理(load_config()から無条件呼び出し)であることを理由に上書きKEEP |
| `orgh/status_json.py::status_payload` | CANDIDATE | KEEP | UC-25追加。`orgh/cli.py::status`と同一評価単位として上書きKEEP |
| `orgh/worktree.py::cleanup_mission_worktrees` | CANDIDATE | WATCH | CLIと実装本体の統合評価ルールにより`orgh/cli.py::cleanup`(WATCH)の判定を継承 |
| `orgh/worktree.py::merge_dep_branches` | CANDIDATE | KEEP | 内部ヘルパー統合評価ルールにより`ensure_task_worktree`(KEEP)の判定を継承 |

---

## 7. 人間が次に決めること(2026-08-07改訂)

以下1〜5はレビュー指摘(review-audit-r1)を反映し、本改訂で解釈・判定を確定済み。人間に残る作業は各行の「承認/保留/却下」欄への実際のチェックのみである。

1. ~~`orgh/gc.py`の内部ヘルパー3件と`orgh/worktree.py::merge_dep_branches`を親機能とまとめて1単位として扱うか~~ → **確定: まとめて1単位として扱う**(1章ルール0として明文化し、セクション3の該当行に反映済み)。
2. ~~`orgh/cli.py::scan`/`list`/`status`(及び`listing.py::list_missions`/`status_json.py::status_payload`)がusecases.jsonの記載漏れか~~ → **確定: list/status/list_missions/status_payloadは記載漏れと認め、UC-25・UC-26を追加してKEEPへ変更した。scanのみ運用文書上の裏付けが本改訂では確認できず、追加は見送りWATCHに留めた**(次回監査での再確認を推奨)。
3. ~~`_is_infra_error`と`LoopCfg.infra_max_retries`もusecases.jsonへの記載漏れと認めてよいか~~ → **確定: 記載漏れと認め、UC-28を追加してKEEPへ変更した**。
4. ~~`--config`グローバルフラグと`validate_config`は構造的必須機能として扱ってよいか~~ → **確定: --configはUC-27追加のうえKEEP、validate_configは横断的前提機能として上書きKEEPとした**。
5. ~~`_initiate_budget_stop`(及びUC-11)は凍結保持か即時削除か~~ → **確定: 凍結保持。UC-11のstatusをobsolete→dormant(休止・復活条件あり)に訂正し、実装本体もWATCHへ変更した**。

以下は本改訂でも未確定(引き続き人間の判断が必要)。

6. `orgh/worktree.py::cleanup_mission_worktrees`(`orgh cleanup`)について、放置されている`.orgh-worktrees`配下の掃除を今後は`orgh cleanup`コマンドを使う運用に切り替えるか。(Yes: 運用に組み込む / No: コマンドごと削除し手動`git worktree remove`に戻す)
7. `config.example.yaml::workers.shell`と`orgh/adapters/base.py::ShellAdapter`(gemini等の任意CLI LLM拡張枠)は、実運用実績が0件のまま今後も設計上の拡張点として維持するか、それとも実際に使う計画が無いなら削除してよいか。(Yes: 維持する / No: 削除する)
8. `orgh/watcher.py::_maybe_gc`は構造的に`orgh/gc.py`の内部ヘルパーと同様のパターン(単一呼び出し元)に見えるが、今回のレビュー指摘の対象外だったため判定を維持した。次回監査で1章ルール0の適用要否を再検討してよいか。(Yes/No)

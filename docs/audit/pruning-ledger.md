# 不要機能・削除候補台帳(人間承認用)

本台帳は、docs/audit/usecases.json(実際のユースケース28件)・docs/audit/features.json(実装機能89件)・docs/audit/usage-evidence.json(feature_idごとの稼働証跡、features.jsonと1対1対応)を突き合わせ、「どの実装機能がどのユースケースにも紐づかない/使われていない可能性が高いか」を人間が削除可否を判断できる形にまとめたものである。

**このタスクでは実際の削除は一切行っていない。orghのコード・設定への変更もゼロ件。** 削除の実行・承認はすべて人間が行う前提で書かれている。

> **2026-08-07 改訂(レビュー指摘 review-audit-r1 反映)**: 初版(2026-08-06)はU=0を無条件にCANDIDATE化するルールにより、稼働証跡の厚い機能(`orgh status`のT=145等)を「削除候補」と誤誘導していた。本改訂で判定ルールを是正し、usecases.jsonへ欠落していた4ユースケース(UC-25〜UC-28)を追加、内部ヘルパー関数の判定を親機能へ統合し、全該当行を再判定した。変更点の一覧はセクション6bを参照。
>
> **2026-08-07 再改訂(レビュー指摘 review-audit-r2 反映)**: r1改訂に対しさらに6件の指摘を受け、(1)セクション6bに欠落していた`orgh/cli.py::scan`の移動記録を追加し件数を17件に訂正、(2)ルール1にU=0かつ3≤T≤9の扱い(WATCH)を明文化、(3)`orgh/watcher.py::_maybe_gc`をルール0(親判定統合)の対象外としていた誤りを是正し`watch()`と統合評価してKEEPへ変更、(4)UC-25/UC-27の実行痕跡をリポジトリ本体の実データで再検証(詳細はusecases.json・usecase-inventory.md側の改訂を参照)、(5)ShellAdapter削除候補の詳細に後方互換性の注意と関連文書の整理範囲を追記、(6)CANDIDATEサマリーの説明文を実際の判定ルールと一致させた。変更点の一覧はセクション6bおよび6cを参照。

---

## 1. 判定基準(全機能に適用)

各機能について以下の2つの値を算出し、下記ルールを**上から順に**適用して1つの判定を確定する。ただし本節末尾の「機械ルールの上書き」に該当する行は、根拠を明記したうえで機械判定を人間が上書きする。

- **U(紐づくユースケース数)**: usecases.json の `trigger`/`description` と features.json の `entrypoint`/`description` の文言対応で判断した、紐づく usecase_id の数(0件も許容)。判断根拠は台帳表の「判定根拠」列に1文で記載。
- **T(証跡合計)**: usage-evidence.json の `code_refs + test_refs + runtime_hits` の単純合算(該当featureの定義元自身への参照は集計対象外という同ファイルの前提をそのまま踏襲)。**T列は異種証跡(静的参照・テスト被覆・実行時マーカー)の単純加算であり、単位も性質も異なる値を足し合わせているに過ぎない。厚みの絶対比較には使わず、あくまで「0に近いか・そうでないか」の粗いシグナルとして読むこと**(詳細は下記「既知の限界」参照)。

判定ルール(優先順位順):

0. **内部ヘルパー関数の統合評価**: 1つの呼び出し元(親のパイプライン関数、または唯一のCLIサブコマンド)からしか参照されず、**除去すると親の機能自体が成立しない実装本体**は、独立に下記1〜6を適用せず、**親の判定をそのまま継承する**。親を残す判断をした場合、内部ヘルパーだけを個別に削除候補として承認欄に出さない(理由: 親を残す限りヘルパーも実行され続けるため、独立した削除候補として扱うと「親はKEEP、部品はCANDIDATE」という実行不能な組み合わせが生まれる)。対象例: `orgh/gc.py::_backup`/`_archive_old_lessons`/`_consolidate`/`_gc_runs`(親: `run_gc`。この4段が`run_gc`の処理本体そのもの)、`orgh/worktree.py::merge_dep_branches`(親: `ensure_task_worktree`。除去すると依存タスクが依存元の成果物を受け取れず、マルチタスクミッションのワークツリー機構が成立しない)、`orgh/doctor.py::run_doctor`(親: CLIの`orgh/cli.py::doctor`)、`orgh/worktree.py::cleanup_mission_worktrees`(親: CLIの`orgh/cli.py::cleanup`)。
   **適用除外(2026-08-07 review-audit-r3で限定)**: 呼び出し元が1つでも、**親を残したまま除去できる任意フック・付加挙動**(設定で無効化可能な定期処理など)はこのルールの対象外とし、個別に評価する。該当: `orgh/watcher.py::_maybe_gc`(`watch.gc_interval_days`を空にすれば無効化でき、`watch()`本体の監視・着火機能は成立し続ける)、`orgh/worktree.py::merge_dep_branches`(依存ブランチ不在・マージ競合時はスキップして実行継続する実装のため、除去してもworktree機構の最小動作は成立する)→ いずれも個別評価のうえ、必要なら下記の上書き規則を適用する。
7. **機械判定の上書き規則(2026-08-07 review-audit-r4で明文化)**: ルール1〜6の機械判定は、次のいずれかを根拠として判定根拠列に明記した場合に限り上書きできる。(a) **実行痕跡**: runs/配下のマーカー・ログ・コンソール出力に当該機能の実行記録が現存する。(b) **文書化された機能価値**: HANDOFF.md・コミット履歴に、実運用の障害・要求から導入された経緯が記録されている。上書きした行は根拠の所在(ファイルパス)を必ず判定根拠列に書く。
1. **U = 0**(紐づくユースケースが1件も無い)→ 原則 **UNKNOWN**(「本当に不要」なのか「usecase台帳の記載漏れ」なのかを機械ルールだけでは区別できないため、無条件のCANDIDATE化はしない)。ただし以下の3区分でこの原則から外れる(2026-08-07 review-audit-r2反映で3区分を明文化。旧版はT=3〜9の扱いが未定義だった):
   - **T ≥ 10** → 記載漏れの可能性が高いとみなし **KEEP**。運用文書(HANDOFF.md・README.md・git log等)に実運用を裏付ける明示的な記述があれば判定根拠列に併記する。
   - **3 ≤ T ≤ 9** → 運用文書上の明示的な裏付けの有無を問わず **WATCH** とする(無関係語の水増しでは説明できない実質的な参照が一定数ある以上、無条件のUNKNOWNには据え置かない。例: `orgh/cli.py::scan`、T=7、運用文書上の裏付けなし)。
   - **T ≤ 2** → 運用文書に実運用を裏付ける明示的な記述があれば **WATCH** に格上げする。無ければ **UNKNOWN** のまま据え置く。
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

## 2. サマリー(全89機能、2026-08-07 review-audit-r1・r2反映で再集計)

| 判定 | 件数(初版2026-08-06) | 件数(本改訂) | 増減 | 意味 |
|---|---|---|---|---|
| **KEEP** | 49 | **58** | +9 | 現行ユースケースに必須。証跡も十分(T≥10)、機械しきい値を上書きするだけの強い運用証跡がある、または内部ヘルパー統合評価によりKEEPの親機能の判定を継承している。 |
| **WATCH** | 20 | **29** | +9 | 現行ユースケースに紐づくが証跡が薄い(3≤T≤9)、休止(dormant)ユースケース専属の実装、またはユースケース帰属が無くとも(U=0)T=3〜9の実質的な参照がある実装(1章ルール1)。定期的な再確認を推奨。 |
| **CANDIDATE** | 19 | **2** | −17 | 削除候補。ユースケースは紐づくが実装が使われた形跡がほぼ皆無(U≥1かつT≤2、1章ルール3)。 |
| **UNKNOWN** | 1 | **0** | −1 | ユースケースへの一意な帰属を判断する材料が不足。 |
| **合計** | 89 | 89 | 0 | |

再集計の内訳(review-audit-r1反映で17件がCANDIDATE/UNKNOWNから移動): usecases.json記載漏れが確認できた9機能(`orgh/cli.py::status`・`--config`・`list`、`orgh/listing.py::list_missions`、`orgh/status_json.py::status_payload`、`orgh/orchestrator.py::_is_infra_error`、`orgh/state.py::LoopCfg.infra_max_retries`・`validate_config`、`orgh/worktree.py::merge_dep_branches`)→**KEEP**、CLI/実装本体の統合評価により1機能(`orgh/doctor.py::run_doctor`)→**KEEP**、内部ヘルパー3機能(`orgh/gc.py::_archive_old_lessons`/`_consolidate`/`_gc_runs`)・CLI/実装本体統合1機能(`orgh/worktree.py::cleanup_mission_worktrees`)・休止ユースケース化1機能(`orgh/orchestrator.py::_initiate_budget_stop`)・記載漏れ1機能(`orgh/cli.py::scan`)→**WATCH**、UNKNOWN 1機能(`config.example.yaml::loop.task_timeout`)→複数usecase帰属により**WATCH**(9+1+3+1+1+1+1=17件。詳細はセクション6b)。さらに`orgh/watcher.py::_maybe_gc`はr2でKEEPへ移動後、r4の再改訂で最終的に**WATCH**となった(経緯はセクション6c)。cumulative で計18件がCANDIDATE/UNKNOWNから移動し、残るCANDIDATEは2件。詳細はセクション3・7を参照。

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
| `orgh/cli.py::--config` | cli | UC-27 | 16 | **KEEP** | UC-27(任意の作業ディレクトリから明示configで起動)を追加。2026-08-07 review-audit-r2でHANDOFF.md:47の手順が実施済みか実データで検証: `ps -p 8843`で`orgh --config ../config.yaml watch`が実際に稼働中のプロセスとして確認できた(開始2026-08-05T15:51:14、監査時点で経過1日10時間超)。HANDOFF.md記載の未着手TODOではなく、実行そのものの直接証跡がある(usecase台帳の記載漏れだったと判明) | 承認/保留/却下: |
| `orgh/cli.py::approve` | cli | UC-04 | 10 | **KEEP** | entrypointが`orgh approve`でUC-04のtrigger(解除経路)と一致 | 承認/保留/却下: |
| `orgh/cli.py::cancel` | cli | UC-05 | 25 | **KEEP** | entrypointが`orgh cancel`でUC-05のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::cleanup` | cli | UC-21 | 4 | **WATCH** | entrypointが`orgh cleanup`でUC-21のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::doctor` | cli | UC-14 | 10 | **KEEP** | entrypointが`orgh doctor`でUC-14のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::gc` | cli | UC-13 | 38 | **KEEP** | entrypointが`orgh gc`でUC-13のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::list` | cli | UC-26 | 4(旧77は「list」一般語検索による水増し。usage-evidence.md参照) | **KEEP** | UC-26(全ミッション一覧確認)を追加。ops/demo/runs/099e281bはこの機能自体を追加したミッションで、README.mdのデモ節が実演記録として明記。T値は是正後4(WATCH域)だが、記載漏れ由来の過小評価だったことがレビューで確認済みのため機械しきい値を上書きしKEEPとする(機械しきい値を上書き) | 承認/保留/却下: |
| `orgh/cli.py::report` | cli | UC-12 | 14 | **KEEP** | entrypointが`orgh report`でUC-12のtriggerと一致 | 承認/保留/却下: |
| `orgh/cli.py::resume` | cli | UC-06 | 66 | **KEEP** | descriptionの「差し戻し」「resume」がUC-06のresume経由改善ループと一致 | 承認/保留/却下: |
| `orgh/cli.py::run` | cli | UC-01, UC-02 | 30 | **KEEP** | entrypointが`orgh run --note`/`--intent`でUC-01/UC-02のtriggerそのもの | 承認/保留/却下: |
| `orgh/cli.py::scan` | cli | (なし) | 7 | **WATCH** | usecases.json全28件中`orgh scan`に言及するものが無いが、T=7は無関係な語のヒットではない実質的な参照(cli.py/doctor.py/sources配下)であり0に近くない。1章ルール1の明文化区分「U=0かつ3≤T≤9→WATCH」に該当し、運用文書上の裏付けが無くてもUNKNOWNではなくWATCHとする(記載漏れの可能性は残るが、本改訂ではusecase追加の裏付けとなる運用文書上の明示記述までは確認できなかったため追加は見送り) | 承認/保留/却下: |
| `orgh/cli.py::status` | cli | UC-25 | 9(旧145は「status」一般語検索による水増し。usage-evidence.md参照) | **KEEP** | UC-25(単一ミッションの状態確認)を追加。ops/demo/runs/099e281bはこの機能「自体を追加した」ミッションであり、README.mdのデモ節もその実装過程の記録である(2026-08-07 review-audit-r2でusecases.json UC-25の評価を再検証した結果、「機能を作った証跡」であって「機能を利用した証跡」ではないと判明し、UC-25のstatusはactiveからassumedへ訂正した。usecase-inventory.md参照)。T値は是正後9(WATCH域上限)だが、CLIの中核サブコマンドとしてREADMEに継続的に案内されている構造的機能であることを理由に機械しきい値を上書きしKEEPとする(機械しきい値を上書き。根拠を「記載漏れ由来の過小評価」から訂正) | 承認/保留/却下: |
| `orgh/cli.py::watch` | cli | UC-03 | 54 | **KEEP** | entrypointが`orgh watch`でUC-03のtrigger文言と完全一致 | 承認/保留/却下: |
| `orgh/doctor.py::run_doctor` | module | UC-14 | 1 | **KEEP** | `orgh/cli.py::doctor`の唯一の実処理本体。CLIサブコマンドと実装本体は同一評価単位とするルール(1章ルール0)により親の判定(KEEP, T=10)を継承。T=1は永続ログを残さない設計上の構造的特性であり利用実績の低さではない | 承認/保留/却下: 承認不要(`orgh/cli.py::doctor`に統合、独立審査対象外) |
| `orgh/gc.py::_archive_old_lessons` | module | UC-13 | 1 | **WATCH** | run_gc()のバックアップ後ステップ。内部ヘルパーは親と同一判定とするルール(1章ルール0)により`run_gc`(WATCH, T=5)の判定を継承 | 承認/保留/却下: 承認不要(`run_gc`に統合、独立審査対象外) |
| `orgh/gc.py::_backup` | module | UC-13 | 10 | **WATCH** | run_gc()の最初のステップ。内部ヘルパーは親と同一判定とするルール(1章ルール0)により`run_gc`(WATCH, T=5)の判定を継承(T=10単独ではKEEP相当だが、親を削除すれば実行されない部品を親より強く残す判定は実行不能な組み合わせを生む) | 承認/保留/却下: 承認不要(`run_gc`に統合、独立審査対象外) |
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
| `orgh/status_json.py::status_payload` | report | UC-25 | 9 | **KEEP** | UC-25(単一ミッションの状態確認、2026-08-07 review-audit-r2でstatusをactive→assumedへ訂正。usecase-inventory.md参照)を追加。`orgh/cli.py::status --json`の唯一の実処理本体で、tests/test_status_json.py(7件)による専用テストも既存。T=9はWATCH域上限だが親CLI(`orgh/cli.py::status`, KEEP)と同一評価単位として扱いKEEPへ上書き(機械しきい値を上書き) | 承認/保留/却下: |
| `orgh/watcher.py::_maybe_gc` | hook | UC-13 | 2 | **WATCH** | 任意フックのためルール0適用外の独立評価(1章ルール0の適用除外)。機械判定ではU≥1・T=2でCANDIDATE相当(ルール3)だが、上書き規則(1章ルール7(a))を適用: 実行痕跡=runs/_gc_state.json(自動GCの実行マーカー、最終更新2026-08-02)が現存し、実際に稼働している定期処理のためWATCH。削除判断は設定`config.example.yaml::watch.gc_interval_days`(WATCH)と一体で行うこと(2026-08-07 review-audit-r4で根拠を明文化) | 承認/保留/却下: |
| `orgh/watcher.py::watch` | module | UC-03 | 54 | **KEEP** | entrypointが`orgh watch`でUC-03のtriggerそのもの | 承認/保留/却下: |
| `orgh/worktree.py::cleanup_mission_worktrees` | integration | UC-21 | 2 | **WATCH** | `orgh/cli.py::cleanup`の唯一の実処理本体。CLIサブコマンドと実装本体は同一評価単位とするルール(1章ルール0)により親の判定(WATCH, T=4)を継承 | 承認/保留/却下: 承認不要(`orgh/cli.py::cleanup`に統合、独立審査対象外) |
| `orgh/worktree.py::commit_task_result` | integration | UC-09 | 16 | **KEEP** | descriptionの「合格タスクの成果をタスクブランチへコミット」がUC-09の成果受け渡し経路 | 承認/保留/却下: |
| `orgh/worktree.py::ensure_task_worktree` | integration | UC-09 | 40 | **KEEP** | descriptionの「タスクをgit worktreeとブランチに分離」がUC-09のtriggerそのもの | 承認/保留/却下: |
| `orgh/worktree.py::merge_dep_branches` | integration | UC-09 | 1 | **KEEP** | 独立評価ではU≥1・T=1でCANDIDATE相当だが、上書き規則(1章ルール7)を適用: (a)実行痕跡=runs/a385f876/resume-console.logに「t4 dep取り込み: orgh/a385f876/t1」等の実実行記録が現存(2026-08-07)、(b)機能価値=HANDOFF.md「②worktree成果物受け渡し」・コミット4aed415(依存タスクへの成果受け渡しは実運用の要求から導入)。除去すると依存タスクが依存元の成果を受け取れなくなるため KEEP | 承認/保留/却下: |
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

## 6. CANDIDATE機能ごとの詳細(2026-08-07改訂: review-audit-r1・r2反映で2件)

各項目: 影響範囲(referenced_byから辿れる呼び出し元)/ 削除手順の概要 / 復元容易性 / 削除しない場合のコスト。全機能はgit管理下にあり、削除してもコミット履歴に残るため、復元容易性は原則「高い」(該当コミットをgit revertまたは該当ファイル/関数をgit checkout <commit> -- <path>で復元可能)。個別に注意点がある場合のみ明記する。

**2026-08-07改訂の注記**: 初版(2026-08-06)では本セクションに19件のCANDIDATEが並んでいたが、レビュー指摘(review-audit-r1)によりU=0の無条件CANDIDATE化ルールの誤りが指摘され、17件がKEEP/WATCHへ再判定された(セクション6b参照)。さらにレビュー指摘(review-audit-r2)により`orgh/watcher.py::_maybe_gc`のルール0適用漏れが指摘され、1件がKEEPへ再判定された(セクション6c参照)。以下は再判定後も真にCANDIDATE(削除候補として人間の判断を仰ぐべき)のまま残った2件のみを扱う。

### `config.example.yaml::workers.shell` / `orgh/adapters/base.py::ShellAdapter`(UC-23専用、事実上未使用)
- **影響範囲**: `orgh/adapters/base.py`のREGISTRYからのみ参照。`orgh/orchestrator.py`はworker名文字列経由でしか触れないため、config.example.yamlからworkers.shellの例示を消してもClaudeCode/Codexアダプタには影響しない。ただしShellAdapterクラス自体を消すと、`get_adapter("shell")`を指定したタスクは即座にKeyError相当で失敗する。
- **後方互換性への注意(2026-08-07 review-audit-r2で追記)**: config.example.yamlはあくまで例示テンプレートだが、これを元にしたユーザーの実運用`config.yaml`(本リポジトリの`config.yaml`自体は`workers.enabled`に`shell`を含めていないため無関係だが、他ユーザー・他環境が`workers.shell`を実際に設定している可能性は排除できない)が`worker: shell`をタスクに指定している場合、ShellAdapterクラスを削除すると`get_adapter("shell")`がKeyError相当で失敗し、既存の外部configが起動不能になる。これは**後方互換性を破る変更**であり、削除前に(i)配布済みのconfig.example.yamlを参照したユーザー環境の有無を確認する、または(ii)非推奨(deprecation)警告を1リリース挟んでから削除する、といった移行手順の要否を人間が判断する必要がある。
- **削除時に整理すべき文書一覧(2026-08-07 review-audit-r2で追記)**: ShellAdapter/workers.shellを削除する場合、コード本体だけでなく「任意LLM対応」を表明している以下の文書も合わせて整理しないと、削除後もorghが他CLI LLMに対応しているという誤った印象が残る。
  1. `README.md:30` — アーキテクチャ図の`(+shell枠で任意LLM)`表記
  2. `docs/deep-dive.md:50`(構成図の`CodexAdapter/ShellAdapter`表記)・`docs/deep-dive.md:129`(ShellAdapterの説明段落)・`docs/deep-dive.md:261`(config表の`shell`列挙)
  3. `docs/audit/usecases.json`のUC-23(ShellAdapter経由の任意CLI LLM利用)を`obsolete`化するか、削除後の状態に合わせて記述を更新
  4. `docs/audit/usecase-inventory.md`のUC-23関連記述、および本監査文書群(`docs/audit/features.json`・`docs/audit/usage-evidence.json`・`docs/audit/feature-inventory.md`・本ファイル)からのShellAdapter/workers.shell行の削除または「削除済み」注記
  5. 利用者向け成果物 `docs/product/orgh-deep-dive.html`・`docs/product/orgh-techbook.html`(ShellAdapter/任意LLM対応の記述あり)を更新し、対応するPDF(`orgh-deep-dive.pdf`・`orgh-techbook.pdf`)を`docs/product/BUILD.md`の手順で再生成
- **削除手順の概要**: (1) 上記の後方互換性影響を人間が判断・許容、(2) ShellAdapterクラスとREGISTRY登録をorgh/adapters/base.pyから削除、(3) config.example.yamlのworkers.shellセクションを削除、(4) doctorの疎通確認対象からも除外、(5) 上記の文書一覧を更新、(6) 最終検証としてリポジトリ全体を `ShellAdapter`・`workers.shell`・`shell枠` で横断検索し、削除漏れ・言及残りが無いことを確認。
- **復元容易性**: 高い(単一ファイル内の1クラス、直近コミット `dde8aa2` 2026-08-03)。
- **削除しない場合のコスト**: 低〜中。config.example.yamlに例示が残り続けると「gemini等の他LLMを使える」という誤解を新規ユーザーに与える保守負担がある一方、コード自体はREGISTRY登録の数行なので放置コストは小さい。UC-23自体は「assumed」(設計上の拡張点)であり実運用実績が0件のため、消しても既存ミッション(本リポジトリの`runs/`・`ops/demo/runs/`配下)への影響はない。ただし上記の外部config互換性リスクは残るため、判定はCANDIDATEのまま維持する。

---

## 6b. このレビューで判定が変更された機能(review-audit-r1反映、17件)

| feature_id | 旧判定 | 新判定 | 変更理由(要約) |
|---|---|---|---|
| `config.example.yaml::loop.task_timeout` | UNKNOWN | WATCH | UC-01/02/03/06/19への複数usecase帰属に再算定。単一帰属できないことはUNKNOWNの理由にならない |
| `orgh/cli.py::--config` | CANDIDATE | KEEP | UC-27(明示config起動)追加。HANDOFF.mdのwatch再起動手順に必須と確認(2026-08-07 review-audit-r2で`ps`による稼働中プロセスの直接確認に根拠を強化。セクション3参照) |
| `orgh/cli.py::list` | CANDIDATE | KEEP | UC-26(全ミッション一覧確認)追加。旧T=77は「list」一般語水増しと判明、是正後T=4だが記載漏れ由来のため上書きKEEP |
| `orgh/cli.py::scan` | CANDIDATE | WATCH | usecases.jsonに紐づくusecaseは無く(U=0)追加も見送ったが、T=7は無関係語水増しではない実質参照であり1章ルール1「U=0かつ3≤T≤9→WATCH」に該当。無条件のUNKNOWN/CANDIDATE化はしない(2026-08-07 review-audit-r2で本表への記載漏れを是正。判定自体はr1改訂時点からWATCHで変更なし) |
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

## 6c. review-audit-r2で追加で判定が変更された機能(1件)

r1改訂(セクション6b)の後、review-audit-r2で新たに指摘され判定が変わったもの。

| feature_id | 旧判定 | 新判定 | 変更理由(要約) |
|---|---|---|---|
| `orgh/watcher.py::_maybe_gc` | CANDIDATE | KEEP→WATCH(最終) | r2でルール0を適用しKEEPへ変更したが、r3のレビューで「設定により無効化できる任意フックにルール0(実装本体の親判定継承)を適用するのは過剰」と再指摘され、r4で独立評価+上書き規則(実行痕跡runs/_gc_state.json)による**WATCH**へ再改訂した。経緯: CANDIDATE(初版)→KEEP(r2)→WATCH(r4、最終)。セクション3の現行判定がWATCHであることに注意 |

---

## 7. 人間が次に決めること(2026-08-07改訂: review-audit-r1・r2反映)

以下1〜6はレビュー指摘(review-audit-r1・r2)を反映し、本改訂で解釈・判定を確定済み。人間に残る作業は各行の「承認/保留/却下」欄への実際のチェックのみである。

1. ~~`orgh/gc.py`の内部ヘルパー3件と`orgh/worktree.py::merge_dep_branches`を親機能とまとめて1単位として扱うか~~ → **確定: まとめて1単位として扱う**(1章ルール0として明文化し、セクション3の該当行に反映済み)。
2. ~~`orgh/cli.py::scan`/`list`/`status`(及び`listing.py::list_missions`/`status_json.py::status_payload`)がusecases.jsonの記載漏れか~~ → **確定: list/status/list_missions/status_payloadは記載漏れと認め、UC-25・UC-26を追加してKEEPへ変更した。scanのみ運用文書上の裏付けが確認できず、追加は見送りWATCHに留めた**(1章ルール1の明文化区分「U=0かつ3≤T≤9→WATCH」に基づく。セクション6b参照)。
3. ~~`_is_infra_error`と`LoopCfg.infra_max_retries`もusecases.jsonへの記載漏れと認めてよいか~~ → **確定: 記載漏れと認め、UC-28を追加してKEEPへ変更した**。
4. ~~`--config`グローバルフラグと`validate_config`は構造的必須機能として扱ってよいか~~ → **確定: --configはUC-27追加のうえKEEP、validate_configは横断的前提機能として上書きKEEPとした。2026-08-07 review-audit-r2で--configはさらに`ps`による稼働中プロセスの直接確認で裏付けを強化した(usecase-inventory.md参照)**。
5. ~~`_initiate_budget_stop`(及びUC-11)は凍結保持か即時削除か~~ → **確定: 凍結保持。UC-11のstatusをobsolete→dormant(休止・復活条件あり)に訂正し、実装本体もWATCHへ変更した**。
6. ~~`orgh/watcher.py::_maybe_gc`は構造的に`orgh/gc.py`の内部ヘルパーと同様のパターン(単一呼び出し元)に見えるが、1章ルール0の適用要否を再検討してよいか~~ → **最終確定(r4): ルール0は適用しない(設定で無効化可能な任意フックのため)。独立評価+上書き規則(実行痕跡runs/_gc_state.json)により最終判定はWATCH**(経緯はセクション6c参照)。

以下は本改訂でも未確定(引き続き人間の判断が必要)。

7. `orgh/worktree.py::cleanup_mission_worktrees`(`orgh cleanup`)について、放置されている`.orgh-worktrees`配下の掃除を今後は`orgh cleanup`コマンドを使う運用に切り替えるか。**破壊性の注意(2026-08-07 review-audit-r3で追記)**: 実装は各worktreeを`git worktree remove --force`で除去し、対応するタスクブランチも`git branch -D`で**マージ済みか否かを確認せず無条件削除**する(orgh/worktree.py:129,135)。未マージ・未退避の成果があるミッションに実行すると回復困難な消失を起こし得るため、採用する場合も「成果のmainマージまたは退避を確認してから実行する」を運用条件とすること。マージ確認の安全ガードを実装するまでは、検収済みミッション以外への実行は保留を推奨。(Yes: 運用に組み込む(上記条件つき) / No: コマンドごと削除し手動`git worktree remove`に戻す)
8. `config.example.yaml::workers.shell`と`orgh/adapters/base.py::ShellAdapter`(gemini等の任意CLI LLM拡張枠)は、実運用実績が0件のまま今後も設計上の拡張点として維持するか、それとも実際に使う計画が無いなら削除してよいか。維持しないと決めた場合、セクション6の後方互換性の注意・削除時に整理すべき文書一覧(2026-08-07 review-audit-r2で追記)に従って進めること。(Yes: 維持する / No: 削除する)

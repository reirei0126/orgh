# orgh 実装機能インベントリ

棚卸し対象: リポジトリ `org-harness`(orgh CLI + Python パッケージ)。ソースコード(orgh/*.py, orgh/adapters, orgh/sources)、設定スキーマ(config.example.yaml, orgh/state.py)、プロンプトテンプレート(prompts/*.md)を走査し、CLIサブコマンド・設定キー・自動発火挙動・主要モジュール/クラス/関数・外部統合・レポート生成の単位で機能を列挙した。

## サマリ

- 総件数: **89**

| kind | 件数 |
|---|---|
| cli(CLI サブコマンド / フラグ) | 13 |
| config(設定キー) | 22 |
| module(モジュール / クラス / 関数) | 31 |
| hook(自動発火フック) | 6 |
| integration(外部統合(worker CLI・入力ソース・git)) | 8 |
| report(レポート / 出力生成) | 3 |
| prompt(プロンプトテンプレート) | 6 |

- `referenced_by` が空の機能(参照元0件、後続の未使用判定シグナル候補): **11件**

## kind別 一覧

### cli — CLI サブコマンド / フラグ(13件)

| feature_id | entrypoint | 参照元件数 |
|---|---|---|
| `orgh/cli.py::--config` | `orgh --config <path> <サブコマンド>`(既定 config.yaml) | 1 |
| `orgh/cli.py::approve` | `orgh approve <mission_id>` を実行する | 0 |
| `orgh/cli.py::cancel` | `orgh cancel <mission_id>` を実行する | 0 |
| `orgh/cli.py::cleanup` | `orgh cleanup <mission_id>` を実行する | 0 |
| `orgh/cli.py::doctor` | `orgh doctor` を実行する | 0 |
| `orgh/cli.py::gc` | `orgh gc` を実行する | 0 |
| `orgh/cli.py::list` | `orgh list` を実行する | 0 |
| `orgh/cli.py::report` | `orgh report [--days N] [--vault]` を実行する | 0 |
| `orgh/cli.py::resume` | `orgh resume <mission_id> [--retry-failed]` を実行する | 0 |
| `orgh/cli.py::run` | `orgh run --note "ノート名"` または `orgh run --intent "..."` [--no-retro] を実行する | 1 |
| `orgh/cli.py::scan` | `orgh scan` を実行する | 0 |
| `orgh/cli.py::status` | `orgh status <mission_id> [--json]` を実行する | 0 |
| `orgh/cli.py::watch` | `orgh watch` を実行する | 0 |

### config — 設定キー(22件)

| feature_id | entrypoint | 参照元件数 |
|---|---|---|
| `config.example.yaml::gc.retention_days` | config.yamlのgc.retention_days(既定 90) | 1 |
| `config.example.yaml::loop.budget_usd` | config.yamlのloop.budget_usd(既定 null=無制限) | 1 |
| `config.example.yaml::loop.max_attempts` | config.yamlのloop.max_attempts(既定 3) | 1 |
| `config.example.yaml::loop.parallel` | config.yamlのloop.parallel(既定 3) | 1 |
| `config.example.yaml::loop.task_budget_usd` | config.yamlのloop.task_budget_usd(既定 null=無制限) | 1 |
| `config.example.yaml::loop.task_timeout` | config.yamlのloop.task_timeout(既定 3600秒) | 2 |
| `config.example.yaml::playbooks_dir` | config.yamlのplaybooks_dir(既定 playbooks) | 3 |
| `config.example.yaml::projects_map` | config.yamlのprojects_map(既定なし・任意) | 1 |
| `config.example.yaml::prompts_dir` | config.yamlのprompts_dir(既定 prompts) | 3 |
| `config.example.yaml::roles` | config.yamlのroles.{planner,reviewer,retro}(model/max_turns/allowed_tools) | 2 |
| `config.example.yaml::runs_dir` | config.yamlのruns_dir(既定 runs) | 6 |
| `config.example.yaml::source.type` | config.yamlのsource.type(既定 obsidian) | 1 |
| `config.example.yaml::vault` | config.yamlのvaultセクション(path/inbox/mission_tag/trigger_tag) | 2 |
| `config.example.yaml::watch.gc_interval_days` | config.yamlのwatch.gc_interval_days(既定 14、null=無効) | 1 |
| `config.example.yaml::watch.interval` | config.yamlのwatch.interval / watch.stabilize_seconds(既定 5秒 / 20秒) | 2 |
| `config.example.yaml::watch.writeback` | config.yamlのwatch.writeback(既定 true) | 1 |
| `config.example.yaml::workers.claude_code` | config.yamlのworkers.claude_code(bin/model/max_turns/allowed_tools/permission_mode) | 1 |
| `config.example.yaml::workers.codex` | config.yamlのworkers.codex(bin/extra_args) | 1 |
| `config.example.yaml::workers.enabled` | config.yamlのworkers.enabled(例 [claude_code, codex]) | 2 |
| `config.example.yaml::workers.shell` | config.yamlのworkers.shell.argv(例 ["gemini","-p","{prompt}"]) | 1 |
| `config.example.yaml::worktree` | config.yamlのworktree.{enabled,base_ref,root}(既定 enabled=false) | 2 |
| `orgh/state.py::LoopCfg.infra_max_retries` | config.yamlのloop.infra_max_retries / loop.infra_retry_wait(config.example.yamlには未記載、既定 3回/60秒) | 1 |

### module — モジュール / クラス / 関数(31件)

| feature_id | entrypoint | 参照元件数 |
|---|---|---|
| `orgh/adapters/base.py::BaseAdapter.run` | _attempt_loop()・_ask_json()がworker実行のたびに呼ぶ | 2 |
| `orgh/adapters/base.py::get_adapter` | orchestrator._attempt_loop()がtask.workerで、planner._ask_json()が"claude_code"固定で呼ぶ | 2 |
| `orgh/doctor.py::run_doctor` | `orgh doctor` | 1 |
| `orgh/gc.py::_archive_old_lessons` | run_gc()がバックアップ後に自動呼び出し | 1 |
| `orgh/gc.py::_backup` | run_gc()が最初のステップとして自動呼び出し | 1 |
| `orgh/gc.py::_consolidate` | run_gc()が退避後に自動呼び出し | 1 |
| `orgh/gc.py::_gc_runs` | run_gc()が最後のステップとして自動呼び出し | 1 |
| `orgh/gc.py::run_gc` | `orgh gc`、watcher._maybe_gc()の定期自動実行 | 3 |
| `orgh/listing.py::list_missions` | `orgh list` | 2 |
| `orgh/orchestrator.py::_attempt_loop` | run_mission()が準備完了タスクごとにpool.submitで呼ぶ | 1 |
| `orgh/orchestrator.py::_initiate_budget_stop` | run_mission()のループがbudget.exceeded()検知時に自動呼び出し | 1 |
| `orgh/orchestrator.py::_initiate_cancel` | run_mission()のループがCANCELフラグまたはpoll_cancel()検知時に自動呼び出し | 1 |
| `orgh/orchestrator.py::_retry_prompt` | _attempt_loop()がエラー/差し戻し再試行時に呼ぶ | 1 |
| `orgh/orchestrator.py::run_mission` | orgh run/resume/approve、watcher.watch()から呼ばれる | 3 |
| `orgh/planner.py::_playbook_context` | plan()/worker_prompt()が内部で自動呼び出し | 1 |
| `orgh/planner.py::_projects_context` | plan()が内部で自動呼び出し(config.projects_map設定時のみ実体を返す) | 2 |
| `orgh/planner.py::plan` | orgh run、watcher.watch()の新規ノート検知時に自動呼び出し | 2 |
| `orgh/planner.py::replan_task` | _attempt_loop()がreviewerからREPLAN:指摘を受けた際に自動呼び出し(1タスク1回まで) | 1 |
| `orgh/planner.py::retro` | orgh run(--no-retro未指定時)、resume完走時、watcher.watch()のミッション完了時に自動呼び出し | 2 |
| `orgh/planner.py::review` | _attempt_loop()がworker成果物完成後に自動呼び出し | 1 |
| `orgh/planner.py::worker_prompt` | _attempt_loop()がタスク実行前に自動呼び出し | 2 |
| `orgh/procreg.py::terminate` | orchestrator._initiate_cancel()がキャンセル確定時に自動呼び出し | 3 |
| `orgh/sources/base.py::SourceAdapter` | get_source()が返す抽象基底。ObsidianAdapterが実装する | 1 |
| `orgh/sources/base.py::get_source` | cli.py(scan/run --note)、watcher.watch()が呼ぶ | 3 |
| `orgh/sources/obsidian.py::WatchState` | ObsidianAdapter.__init__がruns_dir/_watch_state.jsonとして自動生成 | 1 |
| `orgh/sources/obsidian.py::build_context_digest` | ObsidianAdapter.build_context()が内部で自動呼び出し | 1 |
| `orgh/sources/obsidian.py::scan_vault` | ObsidianAdapter.list_candidates()が内部で自動呼び出し | 1 |
| `orgh/state.py::Budget` | planner.plan()/orchestrator._setup_budget()がミッション開始時に生成、split()で子ミッションへ分割 | 3 |
| `orgh/state.py::RunStore` | cli/watcherがミッション開始時にRunStore(runs_dir, mission_id)を生成 | 3 |
| `orgh/state.py::validate_config` | load_config()がconfig.yaml読み込み直後に自動実行 | 1 |
| `orgh/watcher.py::watch` | `orgh watch` | 1 |

### hook — 自動発火フック(6件)

| feature_id | entrypoint | 参照元件数 |
|---|---|---|
| `orgh/guard.py::needs_approval` | run_mission()のディスパッチループが準備完了タスクごとに自動評価(configで無効化不可) | 1 |
| `orgh/orchestrator.py::_is_infra_error` | worker実行が失敗した際、出力が_INFRA_ERROR_RE(タイムアウト・接続断等の既知署名)にマッチすると自動発火 | 1 |
| `orgh/orchestrator.py::replan_escalation` | reviewerのfeedbackが"REPLAN:"で始まると_attempt_loop内で自動発火(1タスク1回まで) | 3 |
| `orgh/results.py::ResultsNote.cancel_requested` | 結果ノート本文への#cancelタグ追記(vault側からの中断指示) | 1 |
| `orgh/sources/obsidian.py::is_triggered` | ノート本文の#<trigger_tag>インラインタグ、またはfrontmatterの`orgh: <trigger_tag>` | 1 |
| `orgh/watcher.py::_maybe_gc` | watch()のループ末尾で毎周チェック、watch.gc_interval_days(既定14日)経過で自動発火 | 1 |

### integration — 外部統合(worker CLI・入力ソース・git)(8件)

| feature_id | entrypoint | 参照元件数 |
|---|---|---|
| `orgh/adapters/base.py::ClaudeCodeAdapter` | config.workers.claude_code、またはtask.worker="claude_code"(既定) | 2 |
| `orgh/adapters/base.py::CodexAdapter` | config.workers.codex、task.worker="codex"指定時 | 1 |
| `orgh/adapters/base.py::ShellAdapter` | config.workers.shell.argv、task.worker="shell"指定時 | 1 |
| `orgh/sources/obsidian.py::ObsidianAdapter` | config.source.type=obsidian(既定) | 2 |
| `orgh/worktree.py::cleanup_mission_worktrees` | `orgh cleanup <mission_id>` | 1 |
| `orgh/worktree.py::commit_task_result` | _attempt_loop()がレビュー合格直後に自動呼び出し | 1 |
| `orgh/worktree.py::ensure_task_worktree` | _attempt_loop()がworktree.enabled時にタスク開始前へ自動呼び出し | 1 |
| `orgh/worktree.py::merge_dep_branches` | ensure_task_worktree()が新規worktree作成直後に自動呼び出し | 1 |

### report — レポート / 出力生成(3件)

| feature_id | entrypoint | 参照元件数 |
|---|---|---|
| `orgh/report.py::build_report` | `orgh report [--days N] [--vault]` | 2 |
| `orgh/results.py::ResultsNote` | ObsidianAdapter.feedback(mission_id)が返す。watcherが着火直後・タスク完了ごと・終了時に自動呼び出し | 1 |
| `orgh/status_json.py::status_payload` | `orgh status <mission_id> --json` | 2 |

### prompt — プロンプトテンプレート(6件)

| feature_id | entrypoint | 参照元件数 |
|---|---|---|
| `prompts/gc.md::gc.md` | planner._read_prompt(cfg, "gc.md")がgc._consolidate()実行時に読み込む | 1 |
| `prompts/planner.md::planner.md` | planner._read_prompt(cfg, "planner.md")がplan()実行時に読み込む | 1 |
| `prompts/replan.md::replan.md` | planner._read_prompt(cfg, "replan.md")がreplan_task()実行時に読み込む | 1 |
| `prompts/retro.md::retro.md` | planner._read_prompt(cfg, "retro.md")がretro()実行時に読み込む | 1 |
| `prompts/reviewer.md::reviewer.md` | planner._read_prompt(cfg, "reviewer.md")がreview()実行時に読み込む | 1 |
| `prompts/worker_preamble.md::worker_preamble.md` | planner._read_prompt(cfg, "worker_preamble.md")がworker_prompt()実行時に読み込む | 1 |

## referenced_by が空の機能(参照元0件)

grep等で実際にコード上の参照元を確認した結果、他ファイルから呼ばれている形跡が0件だった機能。いずれもCLIサブコマンド(ユーザーがシェルから直接起動する入口のため、Pythonコード上の呼び出し元が存在しないのは構造上自然)。ただし `run` と `--config` を除く全サブコマンドは、テストコードからも直接は起動されていない(サブプロセス経由の疎通テストは`run`のみ)。後続タスクで「実際に使われているか」を判定する際は、この一覧のうち特に `watch` / `resume` / `approve` / `cleanup` / `cancel`(運用オペレーション系)が実運用ログ・READMEでの言及頻度と突き合わせる対象になる。

- `orgh/cli.py::approve` (kind=cli) — `orgh approve <mission_id>` を実行する
- `orgh/cli.py::cancel` (kind=cli) — `orgh cancel <mission_id>` を実行する
- `orgh/cli.py::cleanup` (kind=cli) — `orgh cleanup <mission_id>` を実行する
- `orgh/cli.py::doctor` (kind=cli) — `orgh doctor` を実行する
- `orgh/cli.py::gc` (kind=cli) — `orgh gc` を実行する
- `orgh/cli.py::list` (kind=cli) — `orgh list` を実行する
- `orgh/cli.py::report` (kind=cli) — `orgh report [--days N] [--vault]` を実行する
- `orgh/cli.py::resume` (kind=cli) — `orgh resume <mission_id> [--retry-failed]` を実行する
- `orgh/cli.py::scan` (kind=cli) — `orgh scan` を実行する
- `orgh/cli.py::status` (kind=cli) — `orgh status <mission_id> [--json]` を実行する
- `orgh/cli.py::watch` (kind=cli) — `orgh watch` を実行する

## 補足: 集計方法と判断

- 機能粒度は「CLIサブコマンド1つ・設定キー1つ・分岐する挙動1つ・独立したモジュール/クラス/主要関数1つ」を基準にした。ユーティリティ関数(例: `_git`, `_hash`, `_stabilized` 等の内部ヘルパー)は列挙対象から除外し、外部から観測できる挙動(CLIの出力・vaultへの書き込み・playbookの更新・レビュー判定など)を持つ単位のみ機能として数えた。
- `referenced_by` は `Grep` ツールで各シンボル名を実際に検索し、ヒットしたファイルのみを記載した(推測での記入はしていない)。同一ファイル内の別関数からの呼び出し(例: `orgh/gc.py` 内の `run_gc()` が `_backup()` を呼ぶ)も実参照として計上している。
- config系は `config.example.yaml` に現れるキー単位を基本とし、複数サブキーが1つの機能(例: `vault.path/inbox/mission_tag/trigger_tag`)を構成する場合はセクション単位でまとめた。逆に `budget_usd` と `task_budget_usd` のように挙動が明確に異なる場合は分離した。`loop.infra_max_retries` / `infra_retry_wait` は `orgh/state.py` の `LoopCfg` にスキーマとしては存在するが `config.example.yaml` には例示されていないため、path を `orgh/state.py` とした(ドキュメント欠落の一例)。
- 自己改変ガード(`needs_approval`)・vault着火条件判定(`is_triggered`)・定期自動GC(`_maybe_gc`)・vaultの `#cancel` タグ検知(`cancel_requested`)・インフラエラー非消費リトライ(`_is_infra_error`)・REPLANエスカレーションは、ユーザー操作を介さず条件成立時に自動発火する挙動のため `kind: hook` に分類した。
- worker CLI(claude/codex/shell)アダプタ、Obsidian vault アダプタ、git worktree 分離・コミット・掃除は外部システム/外部プロセスとの連携を担うため `kind: integration` に分類した。
- `orgh/report.py`(週次メトリクス集計)、`orgh/results.py`(vault結果ノート生成)、`orgh/status_json.py`(機械可読ステータス)は、いずれも実行結果を成果物として出力する機能のため `kind: report` に分類した。
- 本タスクでは「使われているか」の判定(不要機能の特定)は行っていない。上記の空 `referenced_by` 一覧は後続タスクが判定を行うための材料としてのみ提示している。

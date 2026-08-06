# orgh 深掘り解説(エンジニア向け)

本ドキュメントは `org-harness`(通称 orgh: AIエージェント・オーケストレーションハーネス)の実装を、ソースコードを直接参照しながら解説する。対象読者は本リポジトリに変更を加えるエンジニアであり、抽象的な機能紹介ではなく「どのファイルのどの行がその挙動を作っているか」を優先する。

読解対象は `orgh/` 配下の全 `*.py`(`__init__.py`, `adapters/base.py`, `cli.py`, `doctor.py`, `gc.py`, `guard.py`, `listing.py`, `orchestrator.py`, `planner.py`, `procreg.py`, `report.py`, `results.py`, `sources/base.py`, `sources/obsidian.py`, `state.py`, `status_json.py`, `watcher.py`, `worktree.py`)、および `prompts/*.md`、`config.example.yaml` である。実装から確認できない事項は記載しない。

---

## 1. アーキテクチャ全体像

orgh は「Obsidian vault に書いたノート(または CLI 引数)」を起点に、Planner が JSON でタスク DAG を設計し、Orchestrator が worker CLI(`claude`, `codex` 等)を並列起動して実行し、Reviewer が成果を検査し、Retro が学びを playbooks に蒸留する、というループを繰り返すバッチ指向のオーケストレータである。常駐監視は `orgh watch` が担う。

```
┌────────────────────────────────────────────────────────────────────┐
│  入力層 (SourceAdapter)                                              │
│  orgh/sources/base.py, orgh/sources/obsidian.py                     │
│                                                                       │
│  Obsidian vault ──scan_vault()──▶ candidates(inbox/mission_tag)      │
│         │                          │                                │
│         │                is_triggered()(#go / frontmatter orgh:go)  │
│         ▼                          ▼                                │
│    build_context_digest()   watcher.watch() ループ (orgh/watcher.py) │
│    (wikilinkで depth=1 まで連結、最大24000字)                        │
└───────────────────────────┬───────────────────────────────────────┘
                             │ intent, context_digest
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│  Planner (orgh/planner.py: plan())                                   │
│  prompts/planner.md をテンプレに claude -p --output-format json を1発 │
│  playbooks(組織知)・projects_map(workdir解決表)を注入                │
│  出力: Mission(tasks: Task[]) の DAG(id/prompt/deps/acceptance/tools)│
└───────────────────────────┬───────────────────────────────────────┘
                             │ Mission
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│  Orchestrator (orgh/orchestrator.py: run_mission())                  │
│  ThreadPoolExecutor(max_workers=loop.parallel) で DAG を並列消化      │
│  ready = deps がすべて done のタスク                                  │
│  各タスクごとに: worktree分離 → Worker実行 → Budget課金 → Reviewer     │
│    → 合格ならcommit / 不合格ならフィードバック再実行 or REPLAN         │
│  自己改変ガード(guard.py)・CANCELフラグ・Budget枯渇もここで判定        │
└───────────────────────────┬───────────────────────────────────────┘
                             │ per-task
                 ┌───────────┼───────────────┐
                 ▼                           ▼
┌───────────────────────────┐   ┌───────────────────────────────────┐
│ Worker adapters             │   │ Reviewer (orgh/planner.py: review())│
│ orgh/adapters/base.py       │   │ prompts/reviewer.md               │
│ ClaudeCodeAdapter/           │   │ pass/feedback を返す。             │
│ CodexAdapter/ShellAdapter    │   │ feedback が "REPLAN:" ならPlanner  │
│ subprocess.Popen → procreg   │   │ へエスカレーション(replan_task())  │
│ 登録 → WorkerResult(ok,      │   └───────────────────────────────────┘
│ output, session_id, cost_usd)│
└───────────────────────────┘
                             │ 全タスク終端 (TERMINAL)
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│  Retro (orgh/planner.py: retro())                                    │
│  prompts/retro.md でミッション summary から教訓を抽出し               │
│  playbooks/<name>.md へ `<!-- m:<mission_id> d:<date> -->` 付きで追記 │
└───────────────────────────┬───────────────────────────────────────┘
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│  playbooks/ (組織の長期記憶)                                         │
│  次回の Planner/Worker プロンプトに _playbook_context() で再注入      │
│  (新しい教訓を優先して cap 内に詰める = 「増幅」の実体)               │
└───────────────────────────┬───────────────────────────────────────┘
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│  gc (orgh/gc.py: run_gc())                                           │
│  playbooks の代謝: backup → 180日超の教訓をarchive → 統合Retroで      │
│  重複解消 → runs/ の retention_days 超過分を runs/_archive/ へ退避     │
│  watcher.py の _maybe_gc() が gc_interval_days ごとに自動起動         │
└────────────────────────────────────────────────────────────────────┘
```

補助的なコンポーネント: `RunStore`(`orgh/state.py`)が `runs/<mission_id>/mission.json` と `ledger.jsonl` への永続化を、`procreg.py` が cancel 用のプロセスレジストリを、`results.py` が Obsidian への進行状況書き戻しを、`report.py`/`listing.py`/`status_json.py` が集計・一覧・機械可読出力を、`doctor.py` が実行前診断を担う。CLI エントリポイントは `orgh/cli.py: main()` で、`scan/watch/run/resume/status/cancel/approve/cleanup/doctor/gc/report/list` の各サブコマンドを提供する。

---

## 2. 各コンポーネントの責務と設計判断

### 2.1 ingest / SourceAdapter — `orgh/sources/base.py`, `orgh/sources/obsidian.py`

`SourceAdapter`(`orgh/sources/base.py:26`)は入力ソースの共通インターフェースで、`list_candidates` / `should_trigger` / `find` / `build_context` / `writeback` / `notify_failure` / `feedback` / `mark_processed` / `is_processed` / `describe` を定義する(すべて `raise NotImplementedError` の抽象メソッド、`orgh/sources/base.py:37-75`)。`get_source(cfg)`(`orgh/sources/base.py:78`)が `config.source.type`(既定 `obsidian`)でアダプタを選択する。ファイル冒頭のコメント(`orgh/sources/base.py:1-7`)が明言する設計意図は「watcher/cliはこのインターフェース経由でのみ入力ソースに触れる」「将来の入力ソース(Notion等)はREGISTRYにアダプタを足すだけで差し替えられる」であり、現時点で実装済みなのは `ObsidianAdapter` のみである(Notion等の実アダプタはコード上に存在しない)。

現在の唯一の実装 `ObsidianAdapter`(`orgh/sources/obsidian.py:122`)は MCP を使わずファイルを直読みする。`scan_vault()`(`orgh/sources/obsidian.py:40`)は vault 配下の `*.md` を再帰走査し、`inbox` フォルダ配下 or `mission_tag` タグ付きノートを候補とする。着火判定は `is_triggered()`(`orgh/sources/obsidian.py:58`)が担い、`trigger_tag`(既定 `go`)のインラインタグ、または frontmatter の `orgh: go` がある場合のみ着火する。関数の docstring(`orgh/sources/obsidian.py:59-64`)が明言する設計判断は「inbox配置やmission_tagだけでは着火しない」——誤爆防止のため明示タグを要求する二段階ゲートである。さらに `_stabilized()`(`orgh/sources/obsidian.py:118`)が `watch.stabilize_seconds` 経過を要求し、書きかけノートの拾い上げを防ぐ。

文脈構築は `build_context_digest()`(`orgh/sources/obsidian.py:79`)が担当し、ミッションノート本文に加えて wikilink(`[[...]]`)で辿れる関連ノートを `depth`(既定1)まで連結、`max_chars`(既定24000)で切り詰める。書き戻しは `append_callout()`(`orgh/sources/obsidian.py:73`)がノート末尾に1行のコールアウトを追記するだけの「競合安全writeback」である。処理済み管理は `WatchState`(`orgh/sources/obsidian.py:102`)がファイルの SHA-256 先頭16文字(`_hash()`, `orgh/sources/obsidian.py:98`)をパスごとに `runs/_watch_state.json` に記録する方式で、本文が変わればハッシュも変わるため再着火する。

### 2.2 Planner — `orgh/planner.py: plan()`(`orgh/planner.py:98`)

Planner はファイル冒頭のコメント(`orgh/planner.py:1-3`)どおり「`claude -p`(headless)を1発叩いてJSONを返させる薄いラッパ」であり、Planner/Reviewer/Retroの3役はすべて共通ヘルパー `_ask_json()`(`orgh/planner.py:81`)を経由する。`_ask_json()` は `res.output` から正規表現 `\{.*\}`(DOTALL)で最初の JSON ブロックを抜き出し `json.loads` する(`orgh/planner.py:92-95`)——コードフェンスや前置き説明が混ざっても頑健に拾える設計である。

`plan()` は `prompts/planner.md` をテンプレートに、`intent`(ミッション文)・`context`(vault由来の文脈)・`playbooks`(過去の学び)・`projects`(workdir解決表)・`workers`(利用可能worker一覧)を埋め込み、`_ask_json(cfg, "planner", ...)` を呼ぶ。返る JSON の `tasks` から `Mission.new()`(`orgh/state.py:229`)で `Task` dataclass のリストを組み立てる。

`_playbook_context()`(`orgh/planner.py:35`)の設計判断が重要である。docstring(`orgh/planner.py:36-41`)によれば、cap(`max_chars`既定8000字)は「先頭から切り捨て」ではなく「全playbookの全行をメタデータ日付(`<!-- m:<mission_id> d:<date> -->`)で降順ソートしてから詰める」方式(`orgh/planner.py:45-61`)。これにより playbook が育つほど古い教訓から溢れ、常に新しい教訓が生き残る——リポジトリ内で「増幅」と呼ばれている自己強化ループの実体である。

`_projects_context()`(`orgh/planner.py:64`)は `config.projects_map` で指定したファイルの内容をそのまま注入する。docstring(`orgh/planner.py:65-70`)にある設計判断の理由は実運用で観測した不具合の再発防止で、「ノートに対象リポのパスが書かれていないとPlannerはworkdir "." を出力し、orgh自身のリポで実行されてしまう(実運用7307189eで実証)」ため、プロジェクトマップを明示的に注入する。

### 2.3 Orchestrator — `orgh/orchestrator.py: run_mission()`(`orgh/orchestrator.py:290`)

`run_mission()` は `ThreadPoolExecutor(max_workers=cfg.loop.parallel)`(既定3)を使い、`_ready(m)`(`orgh/orchestrator.py:50`)——「status が pending かつ deps がすべて done のタスク」——を毎ループ抽出して `pool.submit(_run_task, ...)` する。ループはポーリング粒度 `_POLL_INTERVAL = 0.5秒`(`orgh/orchestrator.py:29`)で `wait(..., return_when=FIRST_COMPLETED)` する。

タスクディスパッチ直前に2つのゲートが挟まる(`orgh/orchestrator.py:301-327`):
1. `_cancel_flag(store).exists()` または `poll_cancel()` が真なら `_initiate_cancel()` を呼び、未着手タスクを終了させて以後ディスパッチしない。
2. `budget.exceeded()` なら `_initiate_budget_stop()` を呼び、実行中タスクの完了は待つが未着手はディスパッチしない。
3. `needs_approval(cfg, t.workdir)` かつ `APPROVED` マーカーが無ければ、そのタスクだけを承認待ちにして先送りする(3節・4節で詳述)。

1タスクの実処理は `_attempt_loop()`(`orgh/orchestrator.py:108`)。`_run_task()`(`orgh/orchestrator.py:67`)はその外側の薄いラッパで、docstring(`orgh/orchestrator.py:68-69`)が言う設計意図は「実処理の全例外を1タスクの失敗に閉じ込め、ミッション全体を道連れにしない」。

`_attempt_loop()` の主なロジック:
- worktree 分離(`worktree.enabled` 時、4節で詳述)。
- `max_attempts`(既定3)回まで、worker実行 → コスト課金 → タスク予算超過チェック(`orgh/orchestrator.py:150-158`)→ 失敗ならインフラエラー判定→Reviewer呼び出し、を繰り返す。
- インフラエラー判定 `_is_infra_error()`(`orgh/orchestrator.py:46`)は "Request timed out" 等の正規表現(`orgh/orchestrator.py:34-40`)にマッチする出力を worker の実質的失敗ではなくネットワーク断等とみなし、`t.attempts` を消費せずに `infra_retry_wait` 秒待って再試行する(コメント `orgh/orchestrator.py:31-33` によれば「実運用7307189e t5: ネットワーク断で3attempt≒6.4USD相当を浪費した事例への対処」)。ただし `infra_max_retries`(既定3)で無限リトライは防ぐ。
- Reviewer 呼び出しは `_review_with_retry()`(`orgh/orchestrator.py:81`)がレビュー呼び出し自体の失敗(max_turns超過等)のみ最大2回リトライする。worker 実行はやり直さない——コメント(`orgh/orchestrator.py:83-84`)が言う理由は「成果とコストを捨てない」ため。
- Reviewer の feedback が `"REPLAN:"` で始まる場合、`replan_task()`(`orgh/planner.py:153`)にエスカレーションする(3節で詳述)。`t.replans >= 1` なら以後は失敗として打ち切る(1タスク1回まで、`orgh/orchestrator.py:220-225`)。
- 不合格(REPLANでない通常の差し戻し)の場合は `_retry_prompt()`(`orgh/orchestrator.py:98`)がフィードバックを次のプロンプトに組み込む。`adapter.supports_resume` が真の worker(claude_code)はフィードバックのみで足りる(セッション resume が文脈を保持するため)が、`False` の worker(codex等)には `worker_prompt()` で組み立てた元タスク一式を再度連結した自己完結プロンプトを渡す——コメント(`orgh/orchestrator.py:99-102`)の理由は「実運用7307189e t3で発見: 断片だけ受けたcodexが実装せず確認質問を返して失敗した」。

合格したタスクは `commit_task_result()`(`orgh/worktree.py:94`)でタスクブランチへコミットされる(4節で詳述)。

### 2.4 Worker adapters — `orgh/adapters/base.py`

`BaseAdapter`(`orgh/adapters/base.py:27`)はテンプレートメソッドパターンで、サブクラスは `_command()`(引数列とstdin)と `_parse()`(`WorkerResult` への変換)だけを実装すればよい。共通の `run()`(`orgh/adapters/base.py:37`)が `subprocess.Popen` を起動し、`registry_key`(mission_id)が渡された場合は `procreg.register()` に登録する。`WorkerResult`(`orgh/adapters/base.py:18`)は `ok/output/session_id/cost_usd/raw` の5フィールドに正規化する共通契約であり、ファイル冒頭コメント(`orgh/adapters/base.py:1-2`)の言葉を借りれば「どのCLIエージェントも『prompt in -> WorkerResult out』に正規化する」。タイムアウトは `subprocess.TimeoutExpired` をここで捕捉し `WorkerResult(ok=False, output="timeout")` に変換する(それ以外の例外は orchestrator 側の `_run_task` の例外隔離に委ねる、`orgh/adapters/base.py:3-5`)。

実装は3種:
- `ClaudeCodeAdapter`(`orgh/adapters/base.py:68`, `supports_resume = True`): `claude -p --output-format json --max-turns N` を組み立て、`--resume <session_id>` でセッションを継続できる。`_parse()`(`orgh/adapters/base.py:89`)は stdout 最終行を JSON として解釈し `result/session_id/total_cost_usd/is_error` を取り出す。
- `CodexAdapter`(`orgh/adapters/base.py:104`, `supports_resume` 既定 `False`): `codex exec` + `config.workers.codex.extra_args` を叩く。
- `ShellAdapter`(`orgh/adapters/base.py:119`): `config.workers.shell.argv` のテンプレートで任意のCLI LLM(gemini等)を呼ぶ汎用アダプタ。`{prompt}` トークンを実プロンプトに置換する。

`REGISTRY`(`orgh/adapters/base.py:132`)と `get_adapter(name, cfg)`(`orgh/adapters/base.py:135`)がタスクの `worker` フィールド(既定 `claude_code`)からアダプタを解決する。

### 2.5 Reviewer — `orgh/planner.py: review()`(`orgh/planner.py:116`)

`prompts/reviewer.md` をテンプレートに `title/prompt/acceptance/output`(`t.last_output` の先頭12000字)を埋め込み `_ask_json(cfg, "reviewer", ...)` を呼ぶ。`prompts/reviewer.md` 自体の指示(2行目)は「甘い判定は組織全体を劣化させる。満たしていなければ遠慮なく差し戻せ」であり、判定手順として「acceptance自体を検査し、機械検証可能な条件が1つもない・主観語のみの場合は `pass=false` かつ feedback 先頭に `REPLAN:` を付ける」ことを Reviewer 役に指示している。これが 2.6 の REPLAN エスカレーションの発火源である。

### 2.6 REPLAN エスカレーション — `orgh/planner.py: replan_task()`(`orgh/planner.py:153`)

docstring(`orgh/planner.py:155-156`)の設計意図は「計画の欠陥が指摘されたタスクの指示と受け入れ条件をPlannerに再設計させる」。`prompts/replan.md` に現在の `prompt/acceptance` と Reviewer の指摘(`reason`)を渡し、新しい `prompt/acceptance` を JSON で受け取る。orchestrator 側(`orgh/orchestrator.py:218-234`)では、REPLAN 適用時に `t.attempts -= 1`(REPLAN自体はattemptを消費しない)、`t.replans += 1` としたうえで `worker_prompt()` を再構築し「再設計後の指示で最初から」再実行する。1タスクにつき REPLAN は1回まで(`t.replans >= 1` で打ち切り、`orgh/orchestrator.py:220-225`)。

### 2.7 Retro — `orgh/planner.py: retro()`(`orgh/planner.py:126`)

docstring(`orgh/planner.py:127`)いわく「完了ミッションから学びを抽出して playbooks/ に追記 → 次回以降の全員が賢くなる」。`mission.tasks` から `status/title/attempts/review_notes` のサマリを組み立て `prompts/retro.md` に渡し、返る `{"playbook_name", "lessons"}` を `playbooks/<playbook_name>.md` に追記する。追記時、本文が `-` で始まる行にのみ `<!-- m:<mission_id> d:<today> -->` のメタデータコメントを付与する(`orgh/planner.py:142-146`)——これが 2.2 の `_playbook_context()` が日付ソートに使うメタデータである。

呼び出し経路は3つあり、挙動が微妙に異なる: `orgh run` は毎回無条件に retro する(`--no-retro` で抑制可、`orgh/cli.py:119-124`)。`orgh watch` は着火ループの中で毎回 retro する(`orgh/watcher.py:85`)。`orgh resume` は `_maybe_retro()`(`orgh/cli.py:183`)経由で、**全タスクが done かつ `RETRO_DONE` マーカーが無い場合のみ** retro する——コメント(`orgh/cli.py:184-186`)の理由は「resumeは従来retroを呼ばず、resumeで完走したミッションの教訓がplaybookに残らなかった(実運用7307189eで発見)」ため。`RETRO_DONE` マーカー(`store.dir / "RETRO_DONE"`)は3経路共通で、再resume時の二重追記を防ぐ。

### 2.8 playbooks — 組織知の蓄積・注入・代謝

playbooks は `.md` ファイル群(`playbooks_dir`、既定 `playbooks`)で、書き手は 2.7 の Retro、読み手は 2.2 の `_playbook_context()`(Planner/Worker双方のプロンプトに注入、`worker_prompt()` は `orgh/planner.py:164-168` で `max_chars=4000` を指定)である。人手での追記も想定されている(`_META_RE` にマッチしない行は日付 `"0000-00-00"` 扱いで最古として扱われる、`orgh/planner.py:45,51`)。

### 2.9 gc による代謝 — `orgh/gc.py: run_gc()`(`orgh/gc.py:115`)

ファイル冒頭のコメント(`orgh/gc.py:1-4`)が明言する問題意識は「追記onlyのplaybookは矛盾・重複・陳腐化した教訓が淘汰されず、8000字capにより新しい教訓ほど切り捨てられていた(増幅が数ヶ月でノイズ増幅に反転する)」。`run_gc()` は厳守の順序で4段階を実行する:

1. `_backup()`(`orgh/gc.py:41`): `playbooks/_backup/<date>/` へ全量コピー。失敗(`_backup` がファイルとして存在する等)したら `OSError` を送出して即中断し、playbooks には一切触れない。
2. `_archive_old_lessons()`(`orgh/gc.py:50`): `ARCHIVE_AFTER_DAYS = 180`(`orgh/gc.py:27`)より古い教訓行を `playbooks/_archive/` へ退避(削除ではなく追記+除去)。
3. `_consolidate()`(`orgh/gc.py:74`): 退避後の各ファイルを `prompts/gc.md` 経由で1回 LLM に通し、重複統合・矛盾解消(新日付優先)した結果で全置換する。
4. `_gc_runs()`(`orgh/gc.py:91`): `config.gc.retention_days`(既定90)を超えた `runs/<mission_id>/` を `runs/_archive/` へ移動(削除しない)。判定は各ミッションの `mission.json` の `created_at` を読む。

自動起動は `orgh/watcher.py: _maybe_gc()`(`orgh/watcher.py:27`)が担い、`watch.gc_interval_days`(既定14、`null`で無効)ごとに1回だけ実行する。初回パス(stateファイルが無い場合)は現在時刻をベースラインとして書き込むだけで gc は走らせない(`orgh/watcher.py:33-40`)——「初回パスでいきなり実playbooksを書き換えないため」。手動実行は `orgh gc` サブコマンド(`orgh/cli.py:74-77`)。

---

## 3. タスクの状態遷移

`Task.status`(`orgh/state.py:208`)は Python の `str` 型フィールドであり、専用の enum クラスは定義されていない。`orgh/state.py` 自体が状態名として実際に含む文字列リテラルは以下の6つである(`grep`で確認済み):

| 箇所 | 内容 |
|---|---|
| `orgh/state.py:208` | `status: str = "pending"` — `Task` の既定値。同じ行のコメントに `pending -> running -> review -> done / failed` と明記 |
| `orgh/state.py:239` | `_INFLIGHT_STATUSES = ("queued", "running", "review")` |
| `orgh/state.py:269` | `RunStore.load()` 内で `_INFLIGHT_STATUSES` に該当するタスクを `"pending"` へ巻き戻す |

つまり `state.py` レベルで名前が確認できる状態は **pending / queued / running / review / done / failed** の6つである。`RunStore.load()`(`orgh/state.py:261`)はミッション再開(`resume`)時にこの `_INFLIGHT_STATUSES` を使い、「実行中にクラッシュした場合、ロード時にpendingへ巻き戻す(デッドロック解消)」(`orgh/state.py:238` 直上のコメント)を行う。`Budget`・`Mission`・`RunStore` の永続化はすべて `asdict()`(`orgh/state.py:256`)による JSON シリアライズで、`mission.json` への保存は tmp書き込み→`os.replace` のアトミック置換である(`orgh/state.py:257-259`)。

`state.py` に定義がある6状態の遷移は次のとおり:

```
pending ──(_ready(): depsが全てdone)──▶ queued ──(pool.submit)──▶ running
running ──(adapter.run()成功)──▶ review ──(Reviewer合格)──▶ done
running ──(adapter.run()失敗・attempts上限到達)──▶ failed
review  ──(Reviewer不合格・feedbackで再実行)──▶ running (attempts+1して再ループ)
```

一方で `Task.status` には `state.py` に文字列リテラルとしては現れない値も実行時に代入される。これは `Task.status` が bare `str` であることを利用して、オーケストレーション層(`orgh/orchestrator.py`)・自己改変ガード層(`orgh/guard.py` を呼ぶ `orgh/orchestrator.py`)・CLI層(`orgh/cli.py`)が独自の終端値・一時停止値を追加しているためであり、`state.py` は状態空間の一部(実行中系のロールバック対象)しか列挙していない。具体的には:

- `orgh/orchestrator.py:26` の `TERMINAL` タプルは `done / failed` に加えて2つの終端値(タスク予算超過や `_initiate_budget_stop()` による見送り、CANCEL フラグによる中止)を追加で持つ。これらは `_run_task`/`_attempt_loop`/`_initiate_cancel`/`_initiate_budget_stop` の各所(`orgh/orchestrator.py:130-131, 163-165, 253-256, 279-282`)で `t.status` に代入される。
- `orgh/orchestrator.py:315-320` では、自己改変ガード(4節)が発動したタスクに対し、`pending` から遷移する一時停止的な値(承認待ち)を代入する。この値からの復帰は `orgh cli approve` サブコマンド(`orgh/cli.py:149-157`)のみが行い、`store.dir / "APPROVED"` マーカーを作成したうえで該当タスクを `"pending"` に戻して `run_mission()` を再実行する。
- `orgh/cli.py:169-173`(`resume`)は、直前の中止・見送り相当の状態にあるタスクを `attempts=0` の `"pending"` に戻す。`--retry-failed` 指定時は `failed` タスクも同様に `pending, attempts=0` へ戻す(`orgh/cli.py:174-177`)。
- `orgh/cli.py:158-165`(`cancel`)は `CANCEL` フラグファイルを作成し、`pending` のタスクを即座に中止相当の値へ遷移させる。実行中タスクは `_attempt_loop()` がループの都度 `cancel_flag.exists()` を検査して中止相当へ遷移する(`orgh/orchestrator.py:128-131, 161-165`)。

state.py に閉じた表現を優先する理由は、`Task.status` の「正規の」状態機械定義がリポジトリ中に単一の enum として存在せず、実際の状態空間は `orgh/state.py`(ロールバック対象の3状態を含む土台)と `orgh/orchestrator.py`(終端値・一時停止値の実代入元)と `orgh/cli.py`(人手操作による復帰)に分散しているという実装上の事実そのものが、このハーネスのアーキテクチャ的特徴だからである。エンジニアが新しい終端状態を追加する場合、`state.py` の `_INFLIGHT_STATUSES` や `orgh/orchestrator.py` の `TERMINAL` タプル、`orgh/results.py` のアイコン辞書、`orgh/listing.py` の `_derive_status()`、`orgh/status_json.py` の判定ロジックなど、複数箇所を横断して更新する必要がある。

---

## 4. worktree 分離 / Budget 共有プールの split 設計 / 統治線(ガード・承認)の実装

### 4.1 worktree 分離 — `orgh/worktree.py`

`config.worktree.enabled`(既定 `false`)かつ対象 `workdir` が git リポジトリの場合、タスクごとに専用の worktree とブランチを割り当てる。エントリポイントは `ensure_task_worktree()`(`orgh/worktree.py:32`)で、呼び出し元は `orgh/orchestrator.py:110-116`(`_attempt_loop` 冒頭)。

- パスは `<root>/<mission_id>-<task_id>`、ブランチ名は `orgh/<mission_id>/<task_id>`(`orgh/worktree.py:46-47`)。
- 差し戻し再実行・resume は「`task.branch` が設定済みかつ `workdir` が実在する」なら既存 worktree をそのまま再利用する(`orgh/worktree.py:35-36`)——セッションと成果を捨てないための設計。
- 同一リポへの並列 `git worktree add` は `threading.Lock`(`orgh/worktree.py:19`, `_LOCK`)で直列化する。docstring(`orgh/worktree.py:18`)いわく「git側の索引破損を避ける」ため。
- 新規 worktree 作成時のみ、依存タスクのブランチ(`orgh/<mission_id>/<dep>`)を `merge_dep_branches()`(`orgh/worktree.py:74`)でマージしてから開始する。再利用 worktree ではマージしない——コメント(`orgh/worktree.py:65-66`)の理由は「作業途中の状態に後からマージを重ねると衝突リスクの方が大きい」。マージ衝突は `git merge --abort` してスキップし、タスク自体は止めない(「成果は劣化するが検収で気づける」、`orgh/worktree.py:77-78`)。
- 非gitリポ・`enabled: false` は `is_git_repo()` チェック(`orgh/worktree.py:27-29`)で判定し、`None` を返して orchestrator 側の現行動作(通常の `workdir` 実行)にフォールバックする。
- 合格タスクの成果は `commit_task_result()`(`orgh/worktree.py:94`)がタスクブランチへ `git add -A && git commit` する。変更が無ければコミットしない(`git diff --cached --quiet` で判定、`orgh/worktree.py:101-103`)。identity は `user.name=orgh user.email=orgh@local` を明示指定する——「ホスト名変化で自動検出が壊れた実例があるため」(`orgh/worktree.py:96-97`)。
- ミッション終了時に worktree は自動削除されない。`cleanup_mission_worktrees()`(`orgh/worktree.py:112`)が `orgh cleanup <mission_id>` サブコマンド(`orgh/cli.py:146-148`)経由で明示的に呼ばれたときのみ、`git worktree remove --force` とブランチ `-D` 削除を行う。

### 4.2 Budget 共有プールの split 設計 — `orgh/state.py: Budget`(`orgh/state.py:154`)

docstring(`orgh/state.py:155-163`)が設計意図を明言する: 「再帰(タスクのサブミッション分解)前提の設計: 上限をミッション単位の固定値にすると子ミッションごとの上限が掛け算になって破綻するため、ルートで確保したプールを `split()` で親から子へ分割し、参照渡しする。子の `charge()` は親へ伝播し、親プールの枯渇は子の `exceeded()` にも波及する」。

実装の要点:
- `Budget` は `limit_usd`(このプールの上限、`None`=無制限)・`task_budget_usd`(1タスク上限)・`spent_usd`(累計消費)の3フィールドを持ち、これのみが永続化対象(`orgh/state.py:164-166`)。親リンク `_parent` は `__post_init__()`(`orgh/state.py:168-170`)で実行時にのみ張られる非永続フィールドである。
- `charge(amount)`(`orgh/state.py:172`)は `threading.Lock` で保護しつつ `self.spent_usd` に加算し、`self._parent` があれば再帰的に `_parent.charge(amount)` も呼ぶ——子の消費が親プールにも即座に反映される。
- `exceeded()`(`orgh/state.py:180`)は自分の `limit_usd` 超過、または親の `exceeded()` が真なら真を返す(親の枯渇が子にも波及)。
- `remaining()`(`orgh/state.py:185`)は `limit_usd - spent_usd`(下限0)。`limit_usd is None` なら `None`(無制限)。
- `split(limit_usd=None)`(`orgh/state.py:190`)は「子ミッションへの割当を切り出す(プール自体は共有のまま)」。`limit_usd` 省略時は現在の `remaining()` をそのまま子の上限にする。

呼び出し側の運用は `orgh/orchestrator.py: _setup_budget()`(`orgh/orchestrator.py:262`)が担う。初回実行時は `config.loop.budget_usd`/`task_budget_usd` から新規 `Budget` を作る。resume 時、`mission.budget._parent is None`(ルートミッション)なら消費(`spent_usd`)は引き継ぎつつ上限だけ config から再読込する——「予算を上げて続行できるように」(`orgh/orchestrator.py:264-265`)。`split()` で割当を受けた子ミッション(`_parent` が非 `None`)は上限を上書きしない。

タスク単位の予算超過は `_attempt_loop()` 内(`orgh/orchestrator.py:149-158`)で `t.cost_usd >= budget.task_budget_usd` を毎attempt後にチェックし、超過なら即 `failed` とし次のattempt・レビューには進まない。ミッション単位の予算超過は `run_mission()` のメインループ(`orgh/orchestrator.py:306-308`)が `budget.exceeded()` を毎ポーリングで見て `_initiate_budget_stop()` を呼び、未着手タスクを打ち切る(実行中タスクの完了は待つ)。

### 4.3 統治線(ガード・承認)の実装 — `orgh/guard.py`, `orgh/orchestrator.py`, `orgh/cli.py`

自己改変ガードの実体は `needs_approval(cfg, workdir)`(`orgh/guard.py:25`)という純関数で、判定規則はモジュール docstring(`orgh/guard.py:1-14`)に明記されている:

1. `workdir` を絶対パスに解決した上で、`orgh` パッケージディレクトリ(`package_dir()`, `orgh/guard.py:20-22`、`import orgh; Path(orgh.__file__).resolve().parent`)と一致する・その内側・その親である、のいずれかなら承認必須(`orgh/guard.py:28-30`)。
2. `config.prompts_dir` / `config.playbooks_dir` の実パスに対し、`workdir` がそれと一致 or その内側なら承認必須(`orgh/guard.py:32-36`)。逆方向(`prompts_dir`/`playbooks_dir` が `workdir` の内側にある場合)は対象としない——コメント(`orgh/guard.py:12-13`)の理由は「運用ディレクトリにprompts/やconfig.yamlを置く正規構成のタスクまで巻き込まないよう」。

呼び出し元は `run_mission()` のディスパッチループ(`orgh/orchestrator.py:313-323`)で、`needs_approval(cfg, t.workdir)` かつ `(store.dir / "APPROVED")` が存在しない場合、そのタスクだけを承認待ち相当の状態にして次ループ以降もディスパッチしない(他の準備完了タスクはブロックされない——タスク単位の判定であるため)。

このガードには意図的にconfigでの無効化手段が無い(モジュールdocstring 3行目「意図的に config での無効化手段を設けない」、`orgh/guard.py:6`)。承認できる唯一の経路は `orgh approve <mission_id>` サブコマンド(`orgh/cli.py:149-157`)で、`store.dir / "APPROVED"` マーカーファイルを作成したうえで該当タスクを `pending` に戻し `run_mission()` を再実行する。`orgh/orchestrator.py:313-314` のコメントが明言するとおり、「watcher経由でもスキップ不可。configでも無効化不可」——`orgh watch` の自動着火ループも同じ `run_mission()` を呼ぶため、このガードを迂回できない。

キャンセルの統治線は `runs/<mission_id>/CANCEL` フラグファイルが「唯一の停止信号」(`orgh/orchestrator.py:5-9`)である。`orgh cancel <mission_id>`(別プロセス、`orgh/cli.py:158-167`)はフラグを置くだけで、ミッションを実行中のプロセス自身が `run_mission()` ループごとに `_cancel_flag(store).exists()`(`orgh/orchestrator.py:63,301-303`)を検知し、`procreg.terminate()`(`orgh/procreg.py:33`)で実行中 subprocess を SIGTERM、未着手タスクを中止相当にする(`_initiate_cancel()`, `orgh/orchestrator.py:247-259`)。`poll_cancel`(`orgh watch` 経由では `ResultsNote.cancel_requested()`, `orgh/results.py:44-48`——結果ノート本文の `#cancel` タグ検知)が真を返した場合も同じフラグ経路に合流する(`orgh/orchestrator.py:301-303`)。

プロセスレジストリ `orgh/procreg.py` はモジュール内メモリの `dict[str, set[subprocess.Popen]]`(`orgh/procreg.py:16`)で、`register()`/`unregister()` は `BaseAdapter.run()`(`orgh/adapters/base.py:45-56`)が Popen 起動直後・終了直後に呼ぶ。別プロセスからの `orgh cancel` はこのメモリ内レジストリに直接アクセスできないため、`CANCEL` フラグファイルというファイルシステム経由の signal に頼っている(`orgh/procreg.py:6-9` のコメントが明言)。

---

## 5. 設定リファレンスの読み方

設定は `config.yaml`(既定パス、`--config` で変更可、`orgh/cli.py:33`)を `load_config()`(`orgh/state.py:144`)で読み、`validate_config()`(`orgh/state.py:121`)でスキーマ検証する。存在しない場合は `FileNotFoundError`(「`config.example.yaml` をコピーせよ」、`orgh/state.py:146-148`)。テンプレートは `config.example.yaml`。

### 5.1 検証の仕組み

`ConfigSchema`(`orgh/state.py:78`)は既知のトップレベルキーを dataclass で列挙する。`workers`/`roles` はワーカー名・役割名が自由なため深掘りしない(値は `dict` であることのみ検証、`orgh/state.py:135-137`)。それ以外のセクション(`vault/loop/watch/worktree/source/gc`)は `_SECTION_SCHEMAS`(`orgh/state.py:96-97`)で個別 dataclass にマップされ、`_check_section()`(`orgh/state.py:105`)がキーごとに型検証する。

- **必須キー**: `_REQUIRED_KEYS = ("workers",)`(`orgh/state.py:95`)。無いと `ConfigError`(続行不能)。
- **未知キー**: トップレベル・セクション内とも `ConfigWarning`(`warnings.warn`、続行可能)を出すだけで無視される(`orgh/state.py:111-113, 129-131`)。
- **型不一致**: セクション内キーの型が `_TYPE_MAP`(`orgh/state.py:99-102`、`from __future__ import annotations` により `field.type` が文字列になるための手動マップ)と合わなければ `ConfigError`。
- `runs_dir`/`prompts_dir`/`playbooks_dir`/`projects_map` は文字列必須(`orgh/state.py:138-140`)。

`ConfigError`/`ConfigWarning` はいずれも `orgh/state.py` 冒頭で定義されるカスタム例外・警告クラス(`orgh/state.py:23-28`)。

### 5.2 主要キーと既定値(dataclass の default 値、`config.example.yaml` の値とあわせて記載)

| キー | dataclass / 既定値 | 意味 |
|---|---|---|
| `workers`(必須) | なし(`dict`) | 有効な worker とその接続設定。`workers.enabled` に `claude_code`/`codex`/`shell` を列挙 |
| `roles` | なし(`dict`) | `planner`/`reviewer`/`retro` それぞれのモデル・`max_turns`・`allowed_tools` |
| `vault.path` | `VaultCfg`(`orgh/state.py:33`)、既定 `""` | Obsidian vault の絶対パス |
| `vault.inbox` | 既定 `"inbox"` | ミッション候補と見なすフォルダ名 |
| `vault.mission_tag` | 既定 `"mission"` | 候補タグ(scan用) |
| `vault.trigger_tag` | 既定 `"go"` | 明示着火タグ |
| `loop.parallel` | `LoopCfg`(`orgh/state.py:41`)、既定 `3` | 同時実行タスク数(`ThreadPoolExecutor` の `max_workers`) |
| `loop.max_attempts` | 既定 `3` | 1タスクあたりの実行+差し戻し上限 |
| `loop.task_timeout` | 既定 `3600`(秒) | worker subprocess のタイムアウト |
| `loop.budget_usd` | 既定 `None`(無制限) | ルートミッション全体のコスト上限 |
| `loop.task_budget_usd` | 既定 `None`(無制限) | 1タスクあたりのコスト上限 |
| `loop.infra_max_retries` | 既定 `3` | インフラエラーのattempt非消費リトライ上限 |
| `loop.infra_retry_wait` | 既定 `60`(秒) | 同リトライ前の待機秒 |
| `watch.interval` | `WatchCfg`(`orgh/state.py:52`)、既定 `5`(秒) | vault 監視ポーリング間隔 |
| `watch.stabilize_seconds` | 既定 `20` | 書きかけノートを拾わない猶予秒 |
| `watch.writeback` | 既定 `True` | 着火結果をノートへ書き戻すか |
| `watch.gc_interval_days` | 既定 `14`(`None`で無効) | この日数ごとに自動 gc |
| `worktree.enabled` | `WorktreeCfg`(`orgh/state.py:60`)、既定 `False` | タスクごとの git worktree 分離を有効化 |
| `worktree.base_ref` | 既定 `"HEAD"` | worktree 分岐元 |
| `worktree.root` | 既定 `".orgh-worktrees"` | worktree 置き場(相対なら `workdir` 起点) |
| `source.type` | `SourceCfg`(`orgh/state.py:67`)、既定 `"obsidian"` | 入力ソース種別 |
| `gc.retention_days` | `GcCfg`(`orgh/state.py:73`)、既定 `90` | この日数より古いミッションを `runs/_archive/` へ |
| `runs_dir` | 既定 `"runs"` | ミッション実行状態の永続化先 |
| `prompts_dir` | 既定 `"prompts"` | 役割プロンプト(`planner.md`/`reviewer.md`/`retro.md`/`worker_preamble.md`/`replan.md`/`gc.md`)の置き場。`doctor.py` の `_REQUIRED_PROMPTS`(`orgh/doctor.py:15-16`)がこの6ファイルの存在を検査する |
| `playbooks_dir` | 既定 `"playbooks"` | 組織知の置き場 |
| `projects_map` | 既定 `None` | 対象リポの絶対パス⇔説明の対応表ファイルパス。Planner に注入(2.2節) |

### 5.3 優先順位・上書きルール

- **config内の優先順位**: 未知キーは無視(警告のみ)されるため、タイポしたキーは無言でデフォルト値にフォールバックする——`doctor` の `OK config: 検証済み`(`orgh/doctor.py:66`)は型検証を通過したことのみを示し、キー名の綴りミスは検出しない。
- **worker/role 単位の上書き**: `adapters/base.py: get_adapter(name, cfg)`(`orgh/adapters/base.py:135`)は `cfg.get(name, {})` でそのワーカー名のサブ辞書のみを渡す。Planner 呼び出し(`_ask_json`, `orgh/planner.py:83`)は `{**cfg["workers"], "claude_code": cfg["roles"][role]}` という合成辞書を渡しており、これは「`workers` セクションをベースに `claude_code` キーだけを `roles.<role>` の設定で上書きする」ことを意味する——Planner/Reviewer/Retro は常に `claude_code` アダプタ経由で動作し、`roles` 側の `model`/`max_turns`/`allowed_tools` が実働 worker 用の `workers.claude_code` 設定を完全に置き換える。
- **タスク単位の `tools` 上書き**: `Task.tools`(`orgh/state.py:215`、Planner が明示付与)は worker 既定の `allowed_tools` より優先される。`ClaudeCodeAdapter._command()`(`orgh/adapters/base.py:81-82`)が `allowed_tools or c["allowed_tools"]` の順で解決するため。
- **予算の優先順位**: `_setup_budget()`(4.2節)により、resume 時は config の新しい `budget_usd`/`task_budget_usd` が既存 `spent_usd` を保持したまま上限にのみ反映される(子ミッションの `split()` 済み `Budget` は対象外)。
- **CLI引数 `--config`**: `orgh/cli.py:33` の `ap.add_argument("--config", default="config.yaml")` が唯一の config パス指定手段であり、環境変数等の代替経路はコード上に存在しない。

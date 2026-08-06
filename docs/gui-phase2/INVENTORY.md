# orgh GUI第1期 実装インベントリ(事実台帳)

本ドキュメントは、未マージブランチ `orgh/8e096d63/t4`(デスクトップGUI第1期)の実装内容を、後続の分析タスクが共通の事実基盤として使うために棚卸ししたものである。分析・提案・優先度づけは行わず、事実の列挙のみを行う。断定できない箇所は「未確認」と明記する。

## 0. 調査方法とブランチ情報

- 作業ディレクトリ: `/Users/uesugirei/projects/org-harness`。調査中、HEADは常に `main` のまま維持した(ブランチのcheckout・merge・pull・push・ブランチ作成は一切行っていない)。
- 使用した読み取り専用gitコマンド:
  - `git rev-parse --abbrev-ref HEAD`(HEADが`main`のままであることの確認)
  - `git log main..orgh/8e096d63/t4 --oneline | wc -l`(コミット数の把握)
  - `git log main..orgh/8e096d63/t4 --stat`(変更ファイル全体の把握)
  - `git ls-tree -r --name-only orgh/8e096d63/t4 -- desktop/`(`desktop/`配下の全ファイル一覧)
  - `git show orgh/8e096d63/t4:<path>`(個別ファイル内容の読み取り)
  - `git grep -n "<pattern>" orgh/8e096d63/t4 -- desktop/`(ブランチのツリーに対する読み取り専用grep。特定のCLIサブコマンド文字列がGUI側に一切出現しないことの確認に使用)
- `git log main..orgh/8e096d63/t4 --oneline | wc -l` の結果: **15コミット**。
- コミット構成(`git log main..orgh/8e096d63/t4 --stat` より、新しい順):
  1. `b8d7767` Codexレビューr10反映(`orgh/orchestrator.py`のみ)
  2. `0e4af88` Codexレビューr9反映(`orgh/orchestrator.py`, `tests/test_cancel.py`)
  3. `26c7d0d` Codexレビューr8反映(`orgh/cli.py`, `orgh/orchestrator.py`, `tests/test_cancel.py`)
  4. `7847511` Codexレビューr7反映(`orgh/cli.py`, `orgh/doctor.py`, `orgh/orchestrator.py`, `orgh/planner.py`, `tests/*`)
  5. `d36b5fb` Codexレビューr6反映(`orgh/cli.py`, `orgh/doctor.py`, `tests/*`)
  6. `e9f96cf` Codexレビューr5反映(`desktop/API.md`, `desktop/src/logStore.ts`, `desktop/src/pages/NewMissionPage.tsx`, `orgh/cli.py`, `orgh/doctor.py`, `orgh/orchestrator.py`, `tests/*`)
  7. `93f10a3` Codexレビューr4反映(`README.md`, `desktop/src/api.ts`, `desktop/src/styles.css`, `desktop/src/types.ts`, `orgh/doctor.py`, `orgh/events_json.py`, `orgh/status_json.py`, `tests/*`)
  8. `b3cb493` Codexレビューr3反映(`desktop/src-tauri/src/settings.rs`, `desktop/src/api.ts`, `desktop/src/logStore.ts`, `desktop/src/pages/NewMissionPage.tsx`, `orgh/doctor.py`, `orgh/events_json.py`, `tests/*`)
  9. `a1e9ace` Codexレビューr1反映(承認二重実行・自己改変ガード迂回・実行中状態偽装の修正。`desktop/API.md`, `desktop/src-tauri/src/{cli,commands,models}.rs`, `desktop/src/{api,types}.ts`, `desktop/src/pages/*`, `orgh/{cli,listing,orchestrator,state,status_json}.py`, `tests/*`)
  10. `653373b`(著者`orgh`)実データ結線・アプリ実起動検証・導入ドキュメント(`README.md`, `desktop/docs/VERIFY.md` 新規294行, `desktop/docs/screenshots/app-running*.png`, `desktop/src-tauri/tauri.conf.json`)
  11. `ed2169c` Merge `orgh/8e096d63/t3` into `orgh/8e096d63/t4`
  12. `054adb1`(著者`orgh`)`orgh(8e096d63/t2)`: Rustブリッジ層(Tauriコマンド)の実装(`desktop/src-tauri/**` 新規)
  13. `972dad0`(著者`orgh`)`orgh(8e096d63/t3)`: フロントエンドUI(ミッション一覧・詳細・起動)の実装(`desktop/src/**` 大半が新規)
  14. `d39b3e4`(著者`orgh`)`orgh(8e096d63/t1)`: GUI用CLI-JSON APIとTauri雛形・契約の確定(`desktop/API.md`, `desktop/src/types.ts` 新規、`orgh/cli.py`, `orgh/doctor.py`, `orgh/events_json.py` 拡張)
  15. (`e9f96cf`より上位のコミット順は上記1〜9が該当。マージコミット`ed2169c`を含めて計15件)
- 出典: `git log main..orgh/8e096d63/t4 --stat`(コマンド出力そのもの)。個別コミットハッシュは短縮形。

## 1. CLI側の能力一覧

`orgh/8e096d63/t4:orgh/cli.py` の `main()` 内、`ap.add_subparsers(dest="cmd", required=True)` 以降の `sub.add_parser(...)` 呼び出しをすべて列挙した(全13サブコマンド)。グローバル引数として `ap.add_argument("--config", default="config.yaml")` が全サブコマンドに共通で付与される(出典: `orgh/8e096d63/t4:orgh/cli.py` `main()`冒頭)。

| ID | 機能・サブコマンド | 主な引数/オプション | 何ができるか(1行) | 定義元パス |
|---|---|---|---|---|
| C1 | `scan` | なし(`--config`共通のみ) | vaultからミッション候補ノートを一覧表示 | `orgh/8e096d63/t4:orgh/cli.py` `sub.add_parser("scan")` / 実行部 `if args.cmd == "scan":` |
| C2 | `watch` | なし | vault監視デーモンとして常駐し、ノート投稿を検知して自動着火 | `orgh/8e096d63/t4:orgh/cli.py` `sub.add_parser("watch")` / `if args.cmd == "watch": watcher.watch(cfg)` |
| C3 | `doctor` | `--json` | 外部CLI疎通・config・prompts_dir・vault・runs_dirの書き込み権限を診断 | `orgh/8e096d63/t4:orgh/cli.py` `dp = sub.add_parser("doctor"); dp.add_argument("--json", ...)` |
| C4 | `gc` | なし | playbookの統合・退避とruns/のアーカイブ | `orgh/8e096d63/t4:orgh/cli.py` `sub.add_parser("gc")` / `if args.cmd == "gc": ... gc.run_gc(cfg)` |
| C5 | `list` | `--json` | runs配下の全ミッションをid/intent/状態/コストで一覧 | `orgh/8e096d63/t4:orgh/cli.py` `lp = sub.add_parser("list"); lp.add_argument("--json", ...)` |
| C6 | `events` | `mission_id`(必須位置引数), `--json`, `--tail N`(既定100) | 指定ミッションの`ledger.jsonl`をイベントとして表示 | `orgh/8e096d63/t4:orgh/cli.py` `ep = sub.add_parser("events"); ep.add_argument("mission_id"); ep.add_argument("--json", ...); ep.add_argument("--tail", type=int, default=100)` |
| C7 | `report` | `--days N`, `--vault`(vault内にレポートを書き出すフラグ) | 期間集計レポートを生成(標準出力、`--vault`指定時はvault内`orgh/reports/`にも保存) | `orgh/8e096d63/t4:orgh/cli.py` `rp = sub.add_parser("report"); rp.add_argument("--days", ...); rp.add_argument("--vault", ...)` |
| C8 | `run` | `--note`(vaultノート名), `--intent`(直接指示), `--no-retro` | ノートまたはintentを起点にplan→execute→review→retroまでを完走 | `orgh/8e096d63/t4:orgh/cli.py` `runp = sub.add_parser("run"); runp.add_argument("--note"); runp.add_argument("--intent"); runp.add_argument("--no-retro", ...)` |
| C9 | `resume` | `mission_id`, `--retry-failed` | 中断・キャンセルされたミッションを再開(`--retry-failed`でfailedタスクもpendingへ戻す) | `orgh/8e096d63/t4:orgh/cli.py` `for name in ("resume", "status", "cleanup", "cancel", "approve"): sp = sub.add_parser(name); sp.add_argument("mission_id"); if name == "resume": sp.add_argument("--retry-failed", ...)` |
| C10 | `status` | `mission_id`, `--json` | 指定ミッションの現在状態(タスク別status/attempts/deps含む)を表示 | `orgh/8e096d63/t4:orgh/cli.py` 同上ループ内 `if name == "status": sp.add_argument("--json", ...)` |
| C11 | `cleanup` | `mission_id` | ミッションのworktree/ブランチを掃除(`worktree.enabled`時) | `orgh/8e096d63/t4:orgh/cli.py` 同上ループ / `elif args.cmd == "cleanup": ... worktree.cleanup_mission_worktrees(mission)` |
| C12 | `cancel` | `mission_id` | `CANCEL`フラグを設置し実行中subprocessに停止を促す。未着手タスクは即`cancelled`に確定 | `orgh/8e096d63/t4:orgh/cli.py` 同上ループ / `elif args.cmd == "cancel":` ブロック |
| C13 | `approve` | `mission_id` | 自己改変ガード等で`awaiting_approval`停止したミッションを承認し実行を再開 | `orgh/8e096d63/t4:orgh/cli.py` 同上ループ / `elif args.cmd == "approve":` ブロック |

補足: `run`/`approve`はミッション完走(または再度の承認待ち/終端)までブロックする長時間プロセスである(出典: `orgh/8e096d63/t4:orgh/cli.py` `if args.cmd == "run":` 内 `mission = run_mission(cfg, mission, store)` および `elif args.cmd == "approve":` 内 `mission = run_mission(cfg, mission, store, lock_fp=lock_fp)`)。`run`は`mission {id}: N tasks`行の直後に `print(f"ORGH_MISSION_ID={mission.id}", flush=True)` でID確定行を即時flushする(出典: 同ファイル `if args.cmd == "run":` ブロック)。`approve`は承認受理時に `print(f"ORGH_APPROVED={mission.id}", flush=True)` を出す(出典: 同ファイル `elif args.cmd == "approve":` ブロック)。

## 2. CLIが公開する構造化データ

### 2.1 `orgh/8e096d63/t4:orgh/listing.py`(`list_missions_report()`)

| フィールド | 意味 |
|---|---|
| `missions[].mission_id` | ミッションID(`mission.json`の`id`) |
| `missions[].intent` | intentを60文字超で`…`切り詰め・改行をスペース置換したもの(`_summarize_intent`、`_MAX_INTENT_LEN = 60`) |
| `missions[].status` | `_derive_status(tasks)`による派生ステータス。`empty`/`done`/`failed`/`awaiting_approval`/`cancelled`/`running`のいずれか |
| `missions[].cost_usd` | `mission.json`の`budget.spent_usd`(無ければ`0.0`) |
| `missions[].tasks_done` | `status == "done"`のタスク数 |
| `missions[].tasks_total` | タスク総数 |
| `skipped[].path` | 読み込みに失敗した`mission.json`のパス |
| `skipped[].reason` | 失敗理由(`f"{type(e).__name__}: {e}"`) |

`_derive_status`の規則(出典: `orgh/8e096d63/t4:orgh/listing.py` `_derive_status()`): タスク0件→`empty`。全件`done`→`done`。1件でも`failed`→`failed`。1件でも`awaiting_approval`→`awaiting_approval`。全件終端(`done`/`failed`/`cancelled`/`skipped`)で`done`以外を含む→`cancelled`。それ以外→`running`。`runs_dir`が存在しない場合は`{"missions": [], "skipped": []}`を返す(出典: 同ファイル `list_missions_report()` 冒頭 `if not root.exists(): return {"missions": [], "skipped": []}`)。

### 2.2 `orgh/8e096d63/t4:orgh/status_json.py`(`status_payload()`)

| フィールド | 意味 |
|---|---|
| `mission_id` | ミッションID |
| `intent` | intent文字列(切り詰めなし・生の値) |
| `status` | `listing._derive_status`と同一規則で導出(コメントで相互参照を明記。出典: 同ファイル冒頭コメント `# listing._derive_status と同一の導出規則を保つこと`)。ただしタスク0件時は明示的に`"empty"`を返す分岐が独立して書かれている |
| `tasks[].id`/`title`/`status`/`attempts`/`worker`/`deps` | `mission.tasks`の各要素をそのまま辞書化(`deps`は`list(t.deps)`) |
| `cost_usd` | `mission.budget.spent_usd`(budgetが無ければ`0.0`) |
| `budget_usd` | `mission.budget.limit_usd`(budgetが無ければ`None`) |

### 2.3 `orgh/8e096d63/t4:orgh/events_json.py`(`events_payload()`)

| フィールド | 意味 |
|---|---|
| `mission_id` | 呼び出し引数のミッションID(そのまま返す) |
| `events[].ts` | イベント発生時刻(unix epoch秒、`int`/`float`。`bool`型は`ts`として無効扱い) |
| `events[].event` | イベント種別文字列(必須。文字列でなければ無効行として除外) |
| `events[]` のその他キー | イベント種別ごとに自由形式(発行元は`orgh/orchestrator.py`の`store.log(...)`呼び出しだが、`orchestrator.py`は本タスクの調査対象外のため個別のイベント種別・フィールド名の全件列挙は**未確認**) |

`ledger.jsonl`が存在しない場合は`{"mission_id": mission_id, "events": []}`(出典: `orgh/8e096d63/t4:orgh/events_json.py` `events_payload()` `if not fp.exists(): return {"mission_id": mission_id, "events": []}`)。`_iter_valid()`は次の行を除外する(出典: 同ファイル `_iter_valid()`): JSONとして読めない行、dictでない値、`ts`が`bool`型、`ts`が`int`/`float`でない、`ts`が`math.isfinite`でない(NaN/Inf)、`event`が文字列でない。`tail`指定時は末尾から`_TAIL_CHUNK = 256 * 1024`バイト単位でチャンク読みし、必要件数に満たなければ倍々でチャンクを広げる(出典: 同ファイル `events_payload()` 本体のwhileループ)。

### 2.4 `orgh/8e096d63/t4:orgh/doctor.py`(`doctor_payload()` / `_run_checks()`)

`doctor_payload()`は`{"ok": bool, "checks": [{"name","ok","detail"}, ...]}`を返す(出典: 同ファイル `doctor_payload()`)。チェック項目全件(`_run_checks()`が生成する順):

| チェック名(`name`) | 内容 | 出典(関数/分岐) |
|---|---|---|
| `worker:<name>`(有効化ワーカーごと、可変個) | `cfg["workers"]["enabled"]`列挙の各ワーカーについて、バイナリ(`workers.<name>.bin`、既定`claude`/`codex`または名前そのもの)に`--version`を実行して疎通確認。`workers.<name>`が非dict値なら`bins[...] = None`としNGへ。`worker:shell`はargvの先頭要素を検査対象とし、argvが欠落/空/非文字列要素ならNG | `orgh/8e096d63/t4:orgh/doctor.py` `_binaries()` / `_check_binary()` |
| `role:<role>`(定義済みroleごと、可変個) | `cfg["roles"]`の各roleについて、`bin`(既定`claude`)に`--version`疎通確認。同一パスを既に検査済みなら`detail: "(= <path>)"`で参照のみ | `orgh/8e096d63/t4:orgh/doctor.py` `_binaries()` 後段のforループ、`_run_checks()`内`seen`辞書によるパス重複排除 |
| `config` | ここに到達している時点でスキーマ検証通過済み。常に`ok:true`, `detail:"検証済み"`(config自体が壊れている場合はこのチェックには到達せず、`orgh/cli.py`側の`load_config`失敗ハンドラが別途`{"name":"config","ok":false,...}`を1件だけ返す) | `orgh/8e096d63/t4:orgh/doctor.py` `_run_checks()` の固定行 / `orgh/8e096d63/t4:orgh/cli.py` `main()`冒頭の`try: cfg = load_config(args.config) except Exception as e:` ブロック |
| `roles` | `cfg["roles"]`に`planner`/`reviewer`/`retro`がすべて辞書として定義されているか(`roles.planner: null`等の壊れた値もNG) | `orgh/8e096d63/t4:orgh/doctor.py` `_run_checks()` `bad_roles = [...]` |
| `prompts_dir` | `cfg["prompts_dir"]`(既定`prompts`)配下に必須テンプレート6種(`planner.md`/`reviewer.md`/`retro.md`/`worker_preamble.md`/`replan.md`/`gc.md`)が揃っているか | `orgh/8e096d63/t4:orgh/doctor.py` `_REQUIRED_PROMPTS` 定数 / `_run_checks()` |
| `vault` | `cfg["vault"]["path"]`が未設定なら`ok:true, prefix:"--", detail:"未設定(watch/scanを使わないなら問題なし)"`。設定済みならディレクトリ存在確認+書き込み権限確認 | `orgh/8e096d63/t4:orgh/doctor.py` `_run_checks()` vaultブロック |
| `runs_dir` | `cfg["runs_dir"]`(既定`runs`)にプローブファイルを作成・削除できるかで書き込み権限を確認 | `orgh/8e096d63/t4:orgh/doctor.py` `_run_checks()` runsブロック |

`config`/`prompts_dir`/`vault`/`runs_dir`の4件は常に1件ずつ出力される(`worker:*`/`role:*`/`roles`は設定依存で可変)。この点は`desktop/API.md`にも記載がある(出典: `orgh/8e096d63/t4:desktop/API.md` 1.3節「`config`/`prompts_dir`/`vault`/`runs_dir`の4つは常に1件ずつ出る」)。

## 3. GUI画面インベントリ

`orgh/8e096d63/t4:desktop/src/pages/` 配下4ファイルが画面(ページ)コンポーネント。ルーティングはハッシュベースの自作router(出典: `orgh/8e096d63/t4:desktop/src/router.ts`)で、`App.tsx`のサイドナビ(`rail`)から遷移する(出典: `orgh/8e096d63/t4:desktop/src/App.tsx`)。

| 画面・パネル名 | ファイルパス | 表示している情報 | ユーザーが実行できる操作 | 呼び出しているCLI/データ源 |
|---|---|---|---|---|
| ミッション一覧(MissionListPage) | `orgh/8e096d63/t4:desktop/src/pages/MissionListPage.tsx` | ミッション一覧テーブル(Mission ID/Intent/Status/進捗バー/Cost)、読み込み中/取得失敗/0件/skipped件数の各状態表示 | 「+ 新規ミッション」ボタンで新規画面へ遷移、行クリックで詳細画面へ遷移、取得失敗時は設定画面へのリンクボタン | `listMissions()`(`orgh/8e096d63/t4:desktop/src/api.ts`)→ Tauriコマンド`list_missions`(`orgh/8e096d63/t4:desktop/src-tauri/src/commands.rs` `list_missions()`)→ `orgh list --json`(C5)。10秒間隔でポーリング(`LIST_POLL_MS = 10_000`) |
| 新規ミッション(NewMissionPage) | `orgh/8e096d63/t4:desktop/src/pages/NewMissionPage.tsx` | intent直接入力/note名指定のラジオ切替フォーム、送信中のplanningライブ出力(直近50行) | intentまたはnoteを入力して「▶ ミッションを開始」、「キャンセル」で一覧に戻る | `startMission()`(`orgh/8e096d63/t4:desktop/src/api.ts`)→ Tauriコマンド`start_mission`(`orgh/8e096d63/t4:desktop/src-tauri/src/commands.rs` `start_mission()`)→ `orgh run --intent <...>` または `orgh run --note <...>`(C8) |
| ミッション詳細(MissionDetailPage) | `orgh/8e096d63/t4:desktop/src/pages/MissionDetailPage.tsx` | intent、StatusBadge、Cost/Budget統計+予算プログレスバー、タスク表(ID/Title/Worker/Status/Attempts/Deps)、依存関係DAG(`DependencyGraph`)、ライブログ(ledgerイベント+ライブstdout/stderr) | `awaiting_approval`タスクがある場合のみ「✓ 承認する」を活性化、`running`/`awaiting_approval`状態のみ「✕ キャンセル」を活性化 | `missionStatus()`→`mission_status`→`orgh status <id> --json`(C10)。`missionEvents()`→`mission_events`→`orgh events <id> --json --tail 100`(C6)。`approveMission()`→`approve_mission`→`orgh approve <id>`(C13)。`cancelMission()`→`cancel_mission`→`orgh cancel <id>`(C12、`--json`なし)。5秒間隔ポーリング(`DETAIL_POLL_MS = 5_000`)出典: `orgh/8e096d63/t4:desktop/src/pages/MissionDetailPage.tsx` |
| 設定(SettingsPage) | `orgh/8e096d63/t4:desktop/src/pages/SettingsPage.tsx` | `orghBin`/`configPath`/`runsDir`の3フィールド、診断(doctor)結果テーブル(Check/OK/Detail) | 各フィールドを編集し「保存する」、「orgh doctor を実行」(未保存の編集がある場合は先に自動保存してから診断=「保存して診断」表示に切替) | `getSettings()`/`setSettings()`→ Tauriコマンド`get_settings`/`set_settings`(`orgh/8e096d63/t4:desktop/src-tauri/src/settings.rs`。orghを呼ばずTauriのapp_config_dir配下`settings.json`をRust側で直接読み書き)。`doctor()`→ Tauriコマンド`doctor`→ `orgh doctor --json`(C3) |

共有コンポーネント(単独画面ではなく上記ページから利用): `StatusBadge`(`orgh/8e096d63/t4:desktop/src/components/StatusBadge.tsx`、status文字列→色/ラベル/パルス表示)、`DependencyGraph`(`orgh/8e096d63/t4:desktop/src/components/DependencyGraph.tsx`、タスクdepsから層(Layer)分けし循環依存・欠損依存を検出して警告表示)、`LiveLog`(`orgh/8e096d63/t4:desktop/src/components/LiveLog.tsx`、自動スクロールするログ行リスト)、`ErrorBanner`(`orgh/8e096d63/t4:desktop/src/components/ErrorBanner.tsx`、エラーバナー表示・手動dismiss)。

アプリ全体のログ一元管理は`logStore.ts`(出典: `orgh/8e096d63/t4:desktop/src/logStore.ts`)が担い、`App.tsx`起動時に`startLogStore()`を1回だけ呼ぶ(出典: `orgh/8e096d63/t4:desktop/src/App.tsx` `useEffect(() => { startLogStore(); }, [])`)。バッファ上限は`MAX_LINES = 2000`(出典: `orgh/8e096d63/t4:desktop/src/logStore.ts`)。

ブラウザ単体実行(Tauri外)時は`desktop/src/mocks.ts`のモックデータへ自動フォールバックする(出典: `orgh/8e096d63/t4:desktop/src/api.ts` `isTauriRuntime()`、`orgh/8e096d63/t4:desktop/src/mocks.ts`)。

## 4. CLI能力 × GUI対応マップ

| CLI能力(1章のID) | GUI上の対応UI(画面名+パス) | 状態(あり/部分的/なし) | 備考 |
|---|---|---|---|
| C1 `scan` | — | なし | `git grep -n "scan" orgh/8e096d63/t4 -- desktop/` の一致は`API.md`/`mocks.ts`中の`doctor`のvaultチェック説明文言「未設定(watch/scanを使わないなら問題なし)」のみで、実際の呼び出しコードは0件 |
| C2 `watch` | — | なし | `git grep`で`watch`を含む実呼び出しコード(Tauriコマンド・`api.ts`・ページ)は見つからず。C1と同じ説明文言内にのみ単語として出現 |
| C3 `doctor --json` | 設定(SettingsPage) `orgh/8e096d63/t4:desktop/src/pages/SettingsPage.tsx` | あり | 「orgh doctor を実行」ボタン。`checks[]`をテーブル表示 |
| C4 `gc` | — | なし | `git grep -n "gc"`相当の呼び出しコードなし(`desktop/src-tauri/src/commands.rs`の9コマンド一覧に`gc`は含まれない。`orgh/8e096d63/t4:desktop/src-tauri/src/lib.rs`の`generate_handler!`列挙にも無し) |
| C5 `list --json` | ミッション一覧(MissionListPage) | あり | `list_missions`コマンド経由 |
| C6 `events --json --tail` | ミッション詳細(MissionDetailPage)のライブログ部 | あり | `tail`引数はUI側で固定値`100`のみ(`missionEvents(missionId, 100)`、可変UIなし。出典: `orgh/8e096d63/t4:desktop/src/pages/MissionDetailPage.tsx`) |
| C7 `report` | — | なし | `desktop/src-tauri/src/commands.rs`の9コマンド一覧・`desktop/src/api.ts`のいずれにも`report`相当の呼び出しなし |
| C8 `run --intent/--note` | 新規ミッション(NewMissionPage) | 部分的 | `--intent`/`--note`はUIから選択可能。`--no-retro`フラグに対応するUI操作は無し(`orgh/8e096d63/t4:desktop/src-tauri/src/commands.rs` `build_run_args()`は`--config`/`run`/`--intent`または`--note`のみを組み立て、`--no-retro`は付与しない) |
| C9 `resume` | — | なし | `git grep -n "resume" orgh/8e096d63/t4 -- desktop/` の一致0件。`commands.rs`の9コマンドにも`resume`相当なし。cancelされたミッションをGUIから再開する導線は存在しない |
| C10 `status --json` | ミッション詳細(MissionDetailPage) | あり | `mission_status`コマンド経由 |
| C11 `cleanup` | — | なし | `git grep -n "cleanup" orgh/8e096d63/t4 -- desktop/` の一致0件 |
| C12 `cancel` | ミッション詳細(MissionDetailPage)「✕ キャンセル」ボタン | あり | `cancel_mission`は`cli::run_sync`(JSON非使用の同期実行)経由。出典: `orgh/8e096d63/t4:desktop/src-tauri/src/commands.rs` `cancel_mission()` |
| C13 `approve` | ミッション詳細(MissionDetailPage)「✓ 承認する」ボタン | あり | `approve_mission`は`cli::spawn_and_bridge`(非同期・`ORGH_APPROVED=<id>`確認行待ち)経由 |

## 5. 設定・接続まわりの実装状況

- **接続設定の型**: `Settings { orghBin: string, configPath: string, runsDir: string }`(出典: `orgh/8e096d63/t4:desktop/src/types.ts` `Settings`インターフェース)。Rust側は`orgh_bin`/`config_path`/`runs_dir`(snake_case)で`#[serde(rename_all = "camelCase")]`によりJSON表現をcamelCaseへ変換(出典: `orgh/8e096d63/t4:desktop/src-tauri/src/settings.rs` `Settings`構造体)。
- **永続化方式**: Tauriの`app_config_dir()`配下`settings.json`にJSONとして保存(出典: `orgh/8e096d63/t4:desktop/src-tauri/src/settings.rs` `settings_file_path()`)。`orgh` CLIの`--config`は呼ばれず、GUI固有のローカル永続化である。
- **既定値**: `orghBin: "orgh"`, `configPath: "config.yaml"`, `runsDir: "runs"`(相対パス。出典: 同ファイル`impl Default for Settings`)。VERIFY.mdでは、この既定の相対パスがGUIプロセスのcwdに依存するため実機検証時に絶対パスへ事前投入する運用を取ったと記録されている(3.1節、後述6章参照)。
- **保存前バリデーション**: `orghBin`/`configPath`/`runsDir`の空文字禁止、trim正規化してから検証・保存(空白付きパス保存を防止)、絶対パス指定時のみファイル実在チェック(相対名=PATH解決はdoctor実行時の疎通確認に委ねる)。出典: `orgh/8e096d63/t4:desktop/src-tauri/src/settings.rs` `validate_settings()` / `normalized()`。
- **認証**: GUI・Rustブリッジ・CLI間に認証機構は**確認できず**(認証関連のコード・設定項目はAPI.md/types.ts/settings.rs/commands.rsのいずれにも見当たらない)。ローカルプロセス起動のみを前提とした設計と読み取れる(推測。断定の根拠となる明文記述は見つからず、この点は**未確認**扱いとする)。
- **doctor実行導線**: 設定画面(SettingsPage)内に「orgh doctor を実行」ボタンとして存在(3章参照)。未保存の編集(`dirty`状態)がある場合はボタン表示が「保存して診断」に切り替わり、先に`save()`を実行してから`doctor()`を呼ぶ(出典: `orgh/8e096d63/t4:desktop/src/pages/SettingsPage.tsx` `handleDoctor()`)。診断結果は同画面内にCheck/OK/Detailのテーブルとして表示され、他画面(一覧・詳細)からdoctorへの導線は無い(一覧画面の取得失敗バナーから設定画面への遷移ボタンはあるが、doctor実行そのものへの直接導線ではない。出典: `orgh/8e096d63/t4:desktop/src/pages/MissionListPage.tsx` の取得失敗表示ブロック)。

## 6. VERIFY.md(第1期検証記録)の要点

出典: `orgh/8e096d63/t4:desktop/docs/VERIFY.md`(294行、コミット`653373b`で新規追加)。

- **検証環境**: macOS 15.5 (Darwin 24.5.0) / Apple M4 / Node v24.7.0 / npm 11.5.1 / Python 3.14.6(orgh実行用に別途`~/.orgh-venv`)/ Rust stable 1.97.1(検証タスク内で`rustup`導入)。
- **1章 契約整合性レビュー**: `list_missions`/`mission_status`/`mission_events`/`doctor`/`ORGH_MISSION_ID`検出/コマンド名・引数名/`Settings`型の7項目すべてで「CLI(`--json`)⇔Rust `models.rs`⇔TS `types.ts`」の一致を確認し、**コードレベルの不整合は0件**だったと記載。
- **1章末尾の差分表(唯一のコード変更)**: `desktop/src-tauri/tauri.conf.json`の`bundle.targets`を`"all"`から`["app"]`に変更。理由: `targets: "all"`だと`.dmg`生成時に`bundle_dmg.sh`が`osascript`(Finder自動化)を呼び、検証環境でAccessibility/Automation権限を対話許可できずハングするため。`.app`のみに限定した。API.md契約(CLI⇔Rust⇔TS)には影響しないとされる。
- **2章 ビルド検証**: `npm install`(128パッケージ追加、脆弱性警告2件は既存依存由来でスコープ外と記載)、`npm run tauri build -- --debug`が最終的に終了コード0で成功し`orgh Desktop.app`(Mach-O 64-bit arm64)を生成したことを記録。
- **3章 実起動検証**: GUI設定に実際の絶対パス(`orghBin: /Users/uesugirei/.orgh-venv/bin/orgh`, `configPath`/`runsDir`は本リポジトリの実パス)を事前投入し、実データ(過去ミッション8件)で`list`/`status`/`events`/`doctor`の4コマンドすべてが正常応答したことを確認。`.app`を`open`で起動し、`ps aux`でプロセス生存、`log show`でWebKitロード完了、`CGWindowListCopyWindowInfo`でウィンドウのオンスクリーン描画(`bounds`が`tauri.conf.json`の`1200x800`設定と一致)を確認したと記載。
- **4章 スクリーンショット取得の経緯**: `screencapture -x`はサンドボックス環境のScreen Recording権限欠如により「壁紙のみのダミー画像」を返す既知の挙動で失敗し、ウィンドウ指定キャプチャは`could not create image from window`で明示的に失敗(終了コード1)。フォールバックとして一時的なローカルHTTPブリッジ(リポジトリには含まれず`/tmp`配下のみ、撮影後`git checkout -- desktop/src/api.ts`で完全に戻したと記載)を使いPlaywrightで撮影。撮影結果`app-running.png`はミッション詳細画面(実ミッションID`09957da4`、実タスク6件、実コスト`$41.1010`)で、`orgh status 09957da4 --json`の値と一致・レイアウト崩れなしと記載。
- **5章 既存挙動への影響確認**: `pytest tests/ -q` 166件成功、`cargo test`(lib 11件+統合テスト`tests/orgh_cli_integration.rs` 6件)計17件成功。`git status --porcelain`の差分は`tauri.conf.json`の変更1件と`VERIFY.md`・スクリーンショット2枚の新規追加のみ(README.md追記を含めるとさらに1件)と記載。
- **6章 既知の制約(記載されている既知の未実装・制約)**:
  1. Rustツールチェーン必須(`cargo build`/`tauri build`にRust stable、未導入環境では`rustup`導入が必要)。
  2. `orgh`がPATHまたは`Settings.orghBin`に解決可能である必要がある(RustブリッジはPythonロジックを再実装せず子プロセス起動のみの薄いラッパのため)。
  3. `configPath`は絶対パス指定を強く推奨(既定値`config.yaml`は相対パスでGUIプロセスのcwd依存)。
  4. `.dmg`バンドリングはこの検証環境では未検証(`osascript`権限問題、対話的環境なら`targets: "all"`に戻せば生成できるはずだが未確認と記載)。
  5. `screencapture`による実機スクリーンショットはサンドボックス環境では取得不可(Screen Recording権限が対話的にしか付与できないため)。
  6. 副作用として、検証中に発生した`System Events`のAccessibility権限問い合わせダイアログ(`universalAccessAuthWarn`)が画面上に残ったまま検証を終えており、次回ユーザーが手動で閉じる必要があると記載。

以上。

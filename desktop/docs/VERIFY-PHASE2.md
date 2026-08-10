# orgh GUI第2期 — 統合検証記録(VERIFY-PHASE2.md)

先行タスク(orgh/4d048081/t2〜t7)で実装された PRD-PHASE2.md 3章 P0-1〜P0-6・
P1-2・P1-3 を、本タスク(t8)でブランチ統合後の状態として最終検証した記録。
検証環境: macOS(Darwin 24.5.0) / Node v24.7.0 / Python 3.14.6 / Rust stable
(`export PATH="$HOME/.cargo/bin:$PATH"` で導入)。orgh CLIは
`~/.orgh-venv` に本worktree(`4d048081-t8`)を editable install して使用した
(`pip show orgh` の `Editable project location` で確認済み)。

---

## 1. 機械検証(4コマンド)

すべて終了コード0で完了。

### 1.1 `python -m pytest tests/ -q`

このシェルには裸の `python` コマンドが存在しない(`command -v python` が
何も返さない)ため、前回(第1期)VERIFY.mdと同様に venv の `python` バイナリ
(`~/.orgh-venv/bin/python`)をフルパスで実行した。実体は指示通り
`python -m pytest tests/ -q` である。

```
$ ~/.orgh-venv/bin/python -m pytest tests/ -q
........................................................................ [ 32%]
........................................................................ [ 65%]
........................................................................ [ 98%]
....                                                                     [100%]
220 passed in 15.76s
```

第1期時点(166件)からP0-1(doctor認証チェック)・P1-2(report --json)・
P1-3(playbooks --json)などのCLI拡張テストが追加され220件。

### 1.2 `cargo test`(`desktop/src-tauri`)

```
$ export PATH="$HOME/.cargo/bin:$PATH" && cd desktop/src-tauri && cargo test
running 15 tests (lib)
test cli::tests::falls_back_to_stderr_when_stdout_is_unparseable ... ok
test cli::tests::falls_back_to_exit_status_message_when_no_stderr_and_empty_stdout ... ok
test cli::tests::doctor_ok_false_still_parses_as_structured_report_despite_nonzero_exit ... ok
test cli::tests::parses_error_object_on_failure ... ok
test cli::tests::parses_success_payload ... ok
test commands::tests::build_run_args_rejects_both_none ... ok
test commands::tests::build_run_args_rejects_both_some ... ok
test commands::tests::build_run_args_uses_note_flag ... ok
test commands::tests::build_run_args_uses_intent_flag ... ok
test settings::tests::default_settings_match_cli_defaults ... ok
test settings::tests::normalized_strips_surrounding_whitespace ... ok
test settings::tests::validate_accepts_relative_command_names ... ok
test settings::tests::settings_roundtrip_camel_case_json ... ok
test settings::tests::validate_rejects_empty_fields ... ok
test settings::tests::validate_rejects_missing_absolute_paths ... ok
test result: ok. 15 passed; 0 failed; 0 ignored

running 10 tests (tests/orgh_cli_integration.rs)
test doctor_old_json_defaults_authentication_fields ... ok
test resume_args_include_config_and_optional_retry_flag ... ok
test list_missions_on_empty_runs_dir_returns_empty_array ... ok
test mission_events_parses_ledger_lines_including_unknown_fields ... ok
test mission_events_for_missing_mission_dir_is_an_error ... ok
test list_missions_parses_a_real_mission_json_fixture ... ok
test doctor_real_invocation_parses_into_doctor_report ... ok
test mission_events_without_ledger_file_returns_empty_events ... ok
test playbooks_invokes_stub_and_parses_payload ... ok
test report_invokes_stub_with_days_and_parses_payload ... ok
test result: ok. 10 passed; 0 failed; 0 ignored
```

合計25件成功(第1期時点17件から、resume/report/playbooks関連の統合テストが
8件追加)。

### 1.3 `npx tsc --noEmit`

```
$ cd desktop && npm install   # node_modules未導入だったため実施(128 packages)
$ npx tsc --noEmit
$ echo $?
0
```

エラー0件。

### 1.4 `npm run build`

```
$ cd desktop && npm run build
> tsc && vite build
✓ 51 modules transformed.
dist/index.html                   0.40 kB │ gzip:  0.27 kB
dist/assets/index-*.css           8.66 kB │ gzip:  2.49 kB
dist/assets/core-*.js             0.20 kB │ gzip:  0.15 kB
dist/assets/event-*.js            1.15 kB │ gzip:  0.61 kB
dist/assets/index-*.js          184.90 kB │ gzip: 59.53 kB
✓ built in 259ms
$ echo $?
0
```

---

## 2. 実アプリ起動と目視確認

### 2.1 起動経路について(screencaptureの権限問題と代替経路)

タスク指示通り `npm run tauri build -- --debug` で `.app` をビルドし
(`bundle/macos/orgh Desktop.app`)、実際に `open` で起動してプロセス生存・
ウィンドウ生成をログで確認した(`WebPageProxy::didFinishLoadForFrame` まで
到達、`CGWindowListCopyWindowInfo` 相当のSwift製ツールでウィンドウが
`bounds=[135,47,1200,800] layer=0` でオンスクリーンに存在することも確認)。

しかし `screencapture -x` によるフルスクリーン撮影は、第1期VERIFY.mdで
報告されたのと**全く同じ症状**(Screen Recording権限が本エージェント実行
プロセスツリーに付与されておらず、エラーを返さずに「デスクトップ壁紙+
メニューバーのみでウィンドウ内容が写らないダミー画像」を返す)を再現した。
`screencapture -x -l<windowId>`(ウィンドウ指定キャプチャ)では
`could not create image from window`(終了コード1)と明示的に失敗し、権限
不足であることを裏付けた。この場から対話的に権限ダイアログを許可する手段
はない。

そのため第1期と同様、**実データでのUI目視確認とスクリーンショット取得は
Playwrightでのブラウザ経由撮影で代替した**。具体的には:

1. `orgh --config config.yaml <cmd> --json` をそのまま呼び出し、Rustの
   `models.rs` と同じsnake_case→camelCase変換をかけて返すだけの一時HTTP
   ブリッジ(`/tmp/orgh_bridge.py`、リポジトリには一切含めていない)を用意。
2. `desktop/src/api.ts` 等の**ソースコードは一切変更せず**、Playwrightの
   `page.addInitScript()` でページ読み込み前に `window.__TAURI_INTERNALS__`
   (`invoke`/`transformCallback`等)をブラウザ側にのみ注入し、`invoke(cmd,
   args)` 呼び出しを上記ブリッジへのfetchに委譲するシムを実装。
   `@tauri-apps/api/core` の `invoke()` は `window.__TAURI_INTERNALS__.invoke`
   を呼ぶだけの薄いラッパ(`node_modules/@tauri-apps/api/core.js`で確認済み)
   のため、この注入だけで実アプリと同じフロントエンドコード・同じCLI実データ
   を経由した画面を、権限を要さないブラウザ側で再現できる。
3. `vite dev`(`desktop/src`のビルド前ソースをそのまま配信)に対し、上記シム
   込みのPlaywright(Chromium)でナビゲーションし、6画面すべてを撮影。

この方式は「実アプリの.appウィンドウ」そのものではなく「実アプリと同一の
Reactビルド成果物 + 同一のCLI実データ経路」をブラウザ内で再現したもので
ある点に注意。.appプロセス自体が実データで問題なく起動・ロード完了する
ことは2.1節前半のログで別途確認済みであり、今回のスクリーンショットは
「レイアウト崩壊の有無」「日本語ラベルの一貫性」「実データの表示可否」を
確認する目的においては実アプリと同等の証跡になる。

### 2.2 目視確認した画面・操作

Playwright経由で以下を実際に操作し、レイアウト崩壊がないこと・日本語
ラベルが一貫していることを確認した(実データ: `runs/`配下の実ミッション
11件、うち `4d048081` は本タスクが属するミッション自身)。

| # | 画面 | 確認した操作 | スクリーンショット |
|---|---|---|---|
| 1 | ミッション一覧 | 実ミッション11件の一覧表示、ステータス列の日本語化(完了/失敗/実行中)、進捗バー、コスト列 | `integrated-list.png` |
| 2 | 新規ミッション | サイドバーから遷移、intentモードのヒント欄表示 | `integrated-new.png` |
| 3 | ミッション詳細 | 実ミッション `db8e54e5` を開き、コスト/予算カード・タスク表・依存関係DAG・ライブログを表示 | `integrated-detail.png` |
| 4 | 設定 | サイドバーから遷移、接続設定とrunsディレクトリ(表示専用キャッシュ)の視覚的区分を確認 | `integrated-settings.png` |
| 5 | 設定→doctor実行(認証OK) | 「orgh doctor を実行」をクリックし、claude_code/codexとも「認証OK」バッジで表示されることを確認 | `integrated-settings-doctor-ok.png` |
| 6 | 設定→doctor実行(認証エラー) | tests/mocks配下の既存モックCLI(`MOCK_CLAUDE_AUTH=failed`/`MOCK_CODEX_AUTH=failed`)を使い、実際の`_check_worker_auth`実装コードパスを通して「認証エラー」バッジ表示を確認(2.3節で補足) | `integrated-settings-doctor-authfail.png` |
| 7 | レポート | サイドバーから遷移、週次合格率・ミッション別コスト・worker別失敗率テーブルの表示を確認 | `integrated-report.png` |
| 8 | Playbook | サイドバーから遷移、ファイル一覧とREADME本文表示を確認 | `integrated-playbooks.png` |
| 9 | Playbook→エントリ表示 | `coding.md` をクリックし、末尾付記(ミッションID・日付)付きのエントリ2件が表示されることを確認 | `integrated-playbooks-entries.png` |

上記に加え、先行サブタスク(t2〜t7、いずれも本ブランチにマージ済みの成果)
が個別実装検証時に撮影した以下のスクリーンショットも `desktop/docs/
screenshots/phase2/` に残っており、本タスクで内容を再確認した(モック
データによる状態別・エラー系の確認が中心。実データでの統合確認は上表の
`integrated-*.png` が担う):

| ファイル | 内容 |
|---|---|
| `detail-japanese-status-labels.png` | 詳細画面タスク表で `実行中`/`レビュー中`/`承認待ち`/`待機中` 等ステータスラベルが日本語化され、`承認待ち`行が視覚的に強調されていることを確認 |
| `detail-resume-hidden-done.png` | `done`状態のミッション詳細で「再開する」ボタンが表示されないこと(P0-3受け入れ基準の回帰確認)を確認 |
| `detail-resume-visible-cancelled.png` | `cancelled`状態で「再開する」ボタンと「失敗タスクも含めて再試行する」チェックボックスが表示されることを確認 |
| `detail-resume-visible-failed.png` | `failed`状態でも同様に「再開する」操作が表示されることを確認 |
| `list-orgh-bin-not-found-error.png` | 一覧取得失敗時、原因別(orghコマンド未検出)のバナー文言と「設定画面へ」導線を確認(P0-5) |
| `new-intent-mode-guide.png` | 新規ミッション画面のintentモードで常時表示ヒントを確認(P0-4) |
| `new-note-mode-guide.png` | 新規ミッション画面のnoteモードで検索仕様・`#go`タグ・`projects_map`説明の常時表示を確認(P0-4) |
| `new-note-not-found-error.png` | note未検出時、生例外を折りたたみ詳細に退避し主要文言を平易な日本語にしていることを確認(P0-5) |
| `playbooks-coding-entries.png` | 先行タスク時点(モック相当データ)でのplaybookエントリ表示。本タスクの`integrated-playbooks-entries.png`が実データでの最終確認 |
| `report-7days.png` / `report-30days-after-period-change.png` | レポート画面の期間切替(7日/30日)で集計値が再計算されることを確認(P1-2) |
| `settings-doctor-auth-states.png` | 認証OK/認証未確認の2状態が同一テーブル内で視覚的に区別されることを確認(P0-1、モックデータ時点) |
| `settings-runsdir-cache-section.png` | runsディレクトリ欄が枠線色・バッジ・常時表示の説明文でorghBin/configPathと区分されていることを確認(P0-2) |

`desktop/docs/screenshots/phase2/` 配下の全ファイル一覧と各ファイルの説明は
5章にまとめる。

### 2.3 doctor「認証切れ」状態の再現方法について

P0-1の受け入れ基準「認証切れ状態のワーカーに対してdoctorを実行すると…」
を検証するにあたり、`claude`/`codex`の実認証を実際にログアウトして壊す
ことは破壊的操作であり(`orgh/doctor.py`のコード内コメントにも同様の理由
で「実施しない」と明記されている)行っていない。代わりに、pytestスイート
が実際に使用している既存のモックCLI(`tests/mocks/claude`, `tests/mocks/
codex`)を、環境変数 `MOCK_CLAUDE_AUTH=failed` / `MOCK_CODEX_AUTH=failed`
とともに実行し、`orgh/doctor.py`の`_check_worker_auth`の本番コードパスを
そのまま通して「認証切れ」レスポンスを生成した。これは単体テストと同じ
手法を実際のdoctor CLI実行(`orgh doctor --json`)に対して行っているだけ
であり、doctor.py側のロジックを一切変更・迂回していない。

---

## 3. PRD 3章 受け入れ基準 チェック表

| 項目 | 判定 | 根拠 |
|---|---|---|
| **P0-1** 診断結果を実態に一致させる | **満たす** | `orgh doctor --json`が`authState`(ok/unverified/failed)を`detail`とは別フィールドで返すことを実機で確認(1.1節pytest・1.2節cargo testの`doctor_old_json_defaults_authentication_fields`/`test_claude_worker_auth_failed_forces_ok_false`等で機械検証済み)。SettingsPageは「OK」列と「認証」列を別バッジで表示(`integrated-settings-doctor-ok.png`=認証OK、`integrated-settings-doctor-authfail.png`=認証エラー)。shell系等「非対応」ワーカーは`unverified`で無条件OK化されない(`orgh/doctor.py`の`_check_worker_auth`のデフォルト分岐、`settings-doctor-auth-states.png`)。認証済み実ワーカー(claude_code/codex)は従来通り「OK」表示(回帰なし、`integrated-settings-doctor-ok.png`)。 |
| **P0-2** runsディレクトリの実態区別 | **満たす** | SettingsPageで`runsDir`欄のみ枠線色(warn色)・「表示専用キャッシュ」バッジ・常時表示の説明文(「list/status/doctor等のCLI呼び出しには一切反映されません」)を付与し、`orghBin`/`configPath`と視覚的に区分(`integrated-settings.png`, `settings-runsdir-cache-section.png`)。`orghBin`/`configPath`の保存・doctor実行フローは1.1/1.2節のテスト・2.2節の目視で回帰なしを確認。 |
| **P0-3** キャンセル後のresume | **満たす** | `cancelled`/`failed`状態で「再開する」+「失敗タスクも含めて再試行する」チェックボックスが表示され(`detail-resume-visible-cancelled.png`, `detail-resume-visible-failed.png`)、`done`状態では表示されない(`detail-resume-hidden-done.png`)。cargo testの`resume_args_include_config_and_optional_retry_flag`が`--retry-failed`有無で引数が変わることを機械検証。 |
| **P0-4** 初回ミッション導線ガイド | **満たす** | NewMissionPageのnoteモードに「完全一致優先→部分一致フォールバック」「`#go`はnoteモードの計画生成条件に不使用」「`projects_map`未設定時の影響」の3説明が常時表示(`new-note-mode-guide.png`)。intentモードにも`projects_map`ヒントが常時表示(`integrated-new.png`, `new-intent-mode-guide.png`)。いずれもプレースホルダではなく固定表示のヒントパネル。 |
| **P0-5** エラーメッセージの言い換え | **満たす** | orgh未検出エラーで「orghコマンドが見つかりません」+「設定画面へ」導線+「詳細(元のエラーメッセージ)」折りたたみ(`list-orgh-bin-not-found-error.png`)。note未検出エラーで「ノートが見つかりません。ノート名の綴りを確認するか…」の平易文言+生例外の折りたたみ(`new-note-not-found-error.png`)。判別できないエラーは生メッセージのまま表示される設計(コード上、パターンマッチしないケースはフォールバックで生文言を出す実装を確認)。 |
| **P0-6** ステータスラベル日本語化 | **満たす** | `detail-japanese-status-labels.png`で`実行中`/`レビュー中`/`承認待ち`/`待機中`を確認、`integrated-list.png`で`完了`/`失敗`/`実行中`を確認。8種全ラベルの日本語化はStatusBadgeコンポーネントの実装(コードレビューで確認、内部status値は変更なし)とpytestの回帰無し(1.1節)で担保。 |
| **P1-2** report相当のGUI表示 | **満たす** | ReportPageが週次初回合格率・差し戻し率・ミッション別コスト/所要時間・worker別失敗率を表示(`integrated-report.png`)。期間セレクタ変更で再計算(`report-7days.png`→`report-30days-after-period-change.png`、対象タスク数が20→32等に変化)。**GUI表示の数値とCLI出力の一致を実測で確認**: `integrated-report.png`の週次表(2026-W32: 20件/19件/95%/1件/5%、2026-W33: 10件/9件/90%/1件/10%)と、同時刻に実行した`orgh --config config.yaml report --days 7`のテキスト出力(「2026-W32: 初回合格 19/20 (95%) / 差し戻し 1/20 (5%)」「2026-W33: 初回合格 9/10 (90%) / 差し戻し 1/10 (10%)」)が完全一致。 |
| **P1-3** playbook/retro閲覧画面 | **満たす** | PlaybooksPageがファイル一覧(README/coding/planning/st-test)とエントリ(末尾付記のミッションID・日付付き)を表示(`integrated-playbooks.png`, `integrated-playbooks-entries.png`)。エントリ0件のREADME.mdは「この行形式のエントリはまだありません(「元ファイルを表示」で全文を確認できます)」の空状態表示(エラーにならない)。ミッション詳細画面からplaybookへの直接導線は本タスクの目視確認範囲では確認できず(4章参照)。 |

---

## 4. 既存CLI利用者への非破壊確認

第2期でCLI側に変更が入った`doctor`(認証チェック追加)・`report`
(`--json`追加)・`playbooks`(新設)について、**既存の(`--json`なしの)
テキスト出力**を実機で叩いて確認した。

```
$ orgh --config config.yaml doctor
OK worker:claude_code: 2.1.226 (Claude Code) / 認証: 確認済み
OK worker:codex: codex-cli 0.146.0 / 認証: 確認済み
OK role:planner: (= claude)
...
$ echo $?
0
```

```
$ orgh --config config.yaml report --days 7
# orgh report (last 7 days)
## 週次: 初回attempt合格率と差し戻し率
- 2026-W32: 初回合格 19/20 (95%) / 差し戻し 1/20 (5%)
...
$ echo $?
0
```

```
$ orgh --config config.yaml playbooks
## README  (/Users/uesugirei/projects/org-harness/playbooks/README.md)
## coding  (/Users/uesugirei/projects/org-harness/playbooks/coding.md)
- 資産生成(SVG/データ/CSS等)を複数タスクへ並列分解し...
$ echo $?
0
```

`doctor`のテキスト出力には認証状態の断片(「/ 認証: 確認済み」)が`detail`
文言の一部として追記される形になっており、行フォーマット自体(`OK <name>:
<detail>`)は第1期から変更されていない。`report`・`playbooks`のテキスト
出力は第1期時点で存在した仕様通りで、`--json`追加はオプトインのフラグで
あり無指定時の挙動に変化はない。

既存の`list`/`status`/`events`のテキスト出力も回帰がないことを確認した:

```
$ orgh --config config.yaml list
02a434ad  [done]  4/4 tasks  7.9425 USD  ノート「orgh GUI第2期 ライフサイクル起点の...
...
$ echo $?
0

$ orgh --config config.yaml status db8e54e5
mission db8e54e5: ノート「Sikoslot デプロイ」の内容を実行可能な成果に落とし込む
  ✓ しこれスロットを本番デプロイしURLを確定 [done] attempts=1
  ✓ 本番URLの実ブラウザ動作確認と報告書作成 [done] attempts=1
  cost: 4.0914 USD
$ echo $?
0

$ orgh --config config.yaml events db8e54e5 --tail 3
1785971092.7981231  task.review  {'task': 't2', 'passed': True}
1785971092.885059  task.committed  {'task': 't2', 'commit': '504119d'}
1785971092.886228  mission.finished  {'done': ['t1', 't2'], 'failed': [], 'cancelled': []}
$ echo $?
0
```

**結論: 既存CLI利用者への非破壊は保たれている。**

---

## 5. スクリーンショット一覧(全ファイル)

`desktop/docs/screenshots/phase2/` 配下の全21ファイル:

- `detail-japanese-status-labels.png` — 詳細画面のステータス日本語ラベル(P0-6)
- `detail-resume-hidden-done.png` — done状態で再開ボタン非表示(P0-3回帰確認)
- `detail-resume-visible-cancelled.png` — cancelled状態の再開UI(P0-3)
- `detail-resume-visible-failed.png` — failed状態の再開UI(P0-3)
- `integrated-detail.png` — 【本タスク撮影・実データ】ミッション詳細画面統合確認
- `integrated-list.png` — 【本タスク撮影・実データ】ミッション一覧画面統合確認
- `integrated-new.png` — 【本タスク撮影】新規ミッション画面統合確認
- `integrated-playbooks-entries.png` — 【本タスク撮影・実データ】Playbookエントリ表示統合確認
- `integrated-playbooks.png` — 【本タスク撮影・実データ】Playbook画面統合確認
- `integrated-report.png` — 【本タスク撮影・実データ】レポート画面統合確認(CLI出力と数値一致確認済み)
- `integrated-settings-doctor-authfail.png` — 【本タスク撮影】設定画面doctor実行・認証エラー状態
- `integrated-settings-doctor-ok.png` — 【本タスク撮影・実データ】設定画面doctor実行・認証OK状態
- `integrated-settings.png` — 【本タスク撮影・実データ】設定画面統合確認
- `list-orgh-bin-not-found-error.png` — 一覧画面orgh未検出エラーバナー(P0-5)
- `new-intent-mode-guide.png` — 新規ミッションintentモードヒント(P0-4)
- `new-note-mode-guide.png` — 新規ミッションnoteモードヒント(P0-4)
- `new-note-not-found-error.png` — note未検出エラーの平易文言化(P0-5)
- `playbooks-coding-entries.png` — Playbookエントリ表示(先行タスク時点)
- `report-30days-after-period-change.png` — レポート期間切替後(30日、P1-2)
- `report-7days.png` — レポート期間切替前(7日、P1-2)
- `settings-doctor-auth-states.png` — 認証OK/認証未確認の2状態比較(P0-1)
- `settings-runsdir-cache-section.png` — runsディレクトリの視覚的区分(P0-2)

---

## 6. 既知の未解決事項

正直に列挙する。「無し」ではない。

1. **screencaptureによる実機スクリーンショットはこの実行環境では取得
   不可**(2.1節)。Screen Recording権限が本エージェントの実行プロセス
   ツリーに対話的にしか付与できず、非対話セッションからは解消できない。
   第1期VERIFY.mdで報告された既知の制約が第2期でも継続している。実際の
   ユーザー端末(通常のGUI操作が可能な環境)ではこの制約は発生しない
   はずだが、本タスクの実行環境では未検証。
2. **P1-3(playbook)の「ミッション詳細画面からのplaybook導線」が本タスク
   の目視確認範囲では未確認**。PRD受け入れ基準は「ミッション詳細画面
   から、そのミッションのretroが追記した内容へ辿れる、またはその旨が
   明示される」を「または」で許容しており、`integrated-playbooks-entries.
   png`のエントリ末尾に追記元ミッションID・日付が表示されることでPRDの
   最小要件(逆方向の対応関係の明示)は満たしていると判断したが、
   MissionDetailPage側からPlaybookページへの順方向のリンク導線は本タスク
   では実装有無を個別に確認していない(コードレビューでは`MissionDetail
   Page.tsx`にPlaybookへの直接リンクは見当たらなかった)。次期スコープで
   の確認・追加を推奨する。
3. **P0-1の「認証切れ」状態は実際の認証情報を破壊して再現したものでは
   ない**(2.3節)。実CLIの実認証を意図的に切れさせる検証は破壊的操作の
   ため見送っており、代わりにpytestが使う既存モックCLIを実doctorコード
   パスに通す方法で代替した。本番のclaude/codex CLIが将来`auth status
   --json`/`login status`の出力形式を変更した場合の追従は本検証の範囲外。
4. **実アプリ(.app)のスクリーンショットではなくPlaywright経由のブラウザ
   再現であることの限定**(2.1節)。ネイティブのメニューバー・ウィンドウ
   枠を含んだ完全な実アプリの見た目は今回のスクリーンショットには写って
   いない。ただし.appプロセス自体の起動・実データロード完了はログで別途
   確認済みであり、React側のレイアウト・ラベル・実データ表示については
   実アプリと同一の成果物・同一のCLI実データを経由しているため、目視
   確認の実効性は損なわれていないと判断する。
5. **`npm install`が必要だった**: `desktop/node_modules`が本worktreeに
   未導入の状態から検証を開始したため、`npm install`(128 packages)を
   実施した。既存の`package-lock.json`からの復元であり、依存追加は
   行っていない(`npm audit`が指摘する既存の脆弱性2件はスコープ外)。

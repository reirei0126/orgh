# orgh GUI第3期 — 統合検証記録(VERIFY-PHASE3.md)

先行タスク群(mission 4892cfca: t1コアCLI後方互換JSON追加 / t2 Tauriブリッジ5コマンド
契約確定 / t3 ミッション詳細ページへの検収裁定・人間依頼UI実装 / t4 基準台帳ページ新設)
が「完了」と報告された状態で、本タスク(t5)がブランチ統合後(`ac432a6`)の実装を
実際にコードを読んで確認し、機械検証・目視検証・回帰確認・ドキュメント反映を行った記録。

検証環境: macOS(Darwin 24.5.0, arm64) / Node v24.7.0 / Python 3.14.6
(`~/.orgh-venv/bin/python`。本worktree `.orgh-worktrees/4892cfca-t5` から実行すると
`import orgh` が worktree 内の `orgh/__init__.py` を解決することを確認済み — 同venvの
editable install先は別worktreeを指しているが、cwd優先でシャドウされるため問題ない)
/ Rust `rustc 1.97.1` / `cargo 1.97.1`。

---

## 1. 実装の実在確認(報告を鵜呑みにしない)

着手前に、報告された成果物を実際に読んで確認した。

| 確認対象 | 結果 |
|---|---|
| `orgh/cli.py` の `verdict`/`humandone`/`criteria` サブコマンド | 実装あり(cli.py:231-324)。`humandone`は`planner.review()`を通常のworker成果と同じく通し、合格時のみ`run_mission()`で残タスク実行を継続する — 検収ゲートを迂回する代替経路になっていないことを確認 |
| `desktop/src-tauri/src/lib.rs` の `invoke_handler` | `owner_verdict`/`criteria_list`/`criteria_approve`/`criteria_reject`/`human_done` の5コマンドすべて登録済み(lib.rs:11-27) |
| `desktop/src-tauri/src/commands.rs` | 5コマンドの本体・`build_verdict_args`/`build_human_done_args`(先頭ハイフン注入対策の単体テスト付き)実装あり。コメントで「`spawn_and_bridge`/`ORGH_APPROVED=`確認行契約には一切手を入れない」ことを明記 |
| `desktop/src/api.ts` | 5コマンドすべて `isTauriRuntime()` 分岐 + モックフォールバックまで実装済み(list_missions等の既存9コマンドと同一パターン) |
| `desktop/src/mocks.ts` | `MOCK_CRITERIA` 定義あり。`humanDone`/`ownerVerdict`のモック実装が状態遷移(done化・verdicts追記)を模擬 |
| `desktop/src/router.ts` / `App.tsx` | `criteria`ルートとサイドバー「基準台帳」ナビが実装され、実際に配線されている(画面だけ作ってルータ未接続、という欠落は無かった) |
| `desktop/src/pages/MissionDetailPage.tsx` / `CriteriaPage.tsx` | `ownerVerdict`/`humanDone`/`criteriaList`/`criteriaApprove`/`criteriaReject` を実際に呼び出している |

結論: 4機能(コアJSON・Tauriブリッジ・詳細ページUI・基準台帳ページ)は報告どおり
実在し、主要な結線漏れ(画面はあるがルータ未接続、コマンドはあるがinvoke_handler未登録等)
は見つからなかった。ただし2章・3章で述べる**新規の不具合を2件検出し、本タスクで修正した**。

---

## 2. 機械検証(3コマンド)

すべて終了コード0で完了。

### 2.1 `python -m pytest tests/ -q`

裸の`python`が無いため`~/.orgh-venv/bin/python`をフルパスで実行(前期と同様)。

```
$ ~/.orgh-venv/bin/python -m pytest tests/ -q
........................................................................ [ 22%]
........................................................................ [ 45%]
........................................................................ [ 67%]
........................................................................ [ 90%]
................................                                         [100%]
320 passed in 19.58s
```

第2期時点(220件)からcriteria/verdict/humandone関連のCLIテストが追加され320件。
既存分を含め失敗0件。

### 2.2 `cd desktop/src-tauri && cargo test`

```
$ export PATH="$HOME/.cargo/bin:$PATH" && cd desktop/src-tauri && cargo test
running 22 tests (lib)
test cli::tests::falls_back_to_stderr_when_stdout_is_unparseable ... ok
test cli::tests::parses_success_payload ... ok
test cli::tests::falls_back_to_exit_status_message_when_no_stderr_and_empty_stdout ... ok
test commands::tests::build_human_done_args_note_with_leading_hyphen_stays_one_token ... ok
test commands::tests::build_human_done_args_basic ... ok
test cli::tests::parses_error_object_on_failure ... ok
test cli::tests::doctor_ok_false_still_parses_as_structured_report_despite_nonzero_exit ... ok
test commands::tests::build_human_done_args_note_with_whitespace_and_newlines ... ok
test commands::tests::build_run_args_rejects_both_none ... ok
test commands::tests::build_run_args_rejects_both_some ... ok
test commands::tests::build_run_args_uses_intent_flag ... ok
test commands::tests::build_run_args_uses_note_flag ... ok
test commands::tests::build_verdict_args_fail ... ok
test commands::tests::build_verdict_args_pass ... ok
test commands::tests::build_verdict_args_reason_with_leading_hyphen_stays_one_token ... ok
test commands::tests::build_verdict_args_reason_with_whitespace_and_newlines ... ok
test settings::tests::default_settings_match_cli_defaults ... ok
test settings::tests::normalized_strips_surrounding_whitespace ... ok
test settings::tests::settings_roundtrip_camel_case_json ... ok
test settings::tests::validate_accepts_relative_command_names ... ok
test settings::tests::validate_rejects_empty_fields ... ok
test settings::tests::validate_rejects_missing_absolute_paths ... ok
test result: ok. 22 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s

running tests/orgh_cli_integration.rs (10 tests)
test doctor_old_json_defaults_authentication_fields ... ok
test resume_args_include_config_and_optional_retry_flag ... ok
test mission_events_without_ledger_file_returns_empty_events ... ok
test mission_events_parses_ledger_lines_including_unknown_fields ... ok
test mission_events_for_missing_mission_dir_is_an_error ... ok
test list_missions_parses_a_real_mission_json_fixture ... ok
test list_missions_on_empty_runs_dir_returns_empty_array ... ok
test doctor_real_invocation_parses_into_doctor_report ... ok
test report_invokes_stub_with_days_and_parses_payload ... ok
test playbooks_invokes_stub_and_parses_payload ... ok
test result: ok. 10 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.41s
```

合計32件成功(lib 22件 + integration 10件)。`build_verdict_args`/`build_human_done_args`
の先頭ハイフン・改行注入対策テストを含め全緑。

### 2.3 `cd desktop && npm run build`

`desktop/node_modules`が本worktreeに未導入だったため`npm install`(package-lock.jsonから
の復元、128 packages、依存追加なし)を実施した後に実行。

```
$ npm run build
> orgh-desktop@0.1.0 build
> tsc && vite build

vite v5.4.21 building for production...
✓ 52 modules transformed.
dist/index.html                   0.40 kB │ gzip:  0.27 kB
dist/assets/index-*.css          10.08 kB │ gzip:  2.80 kB
dist/assets/core-*.js             0.20 kB │ gzip:  0.15 kB
dist/assets/event-*.js            1.15 kB │ gzip:  0.61 kB
dist/assets/index-*.js          202.37 kB │ gzip: 64.53 kB
✓ built in 311ms
$ echo $?
0
```

`tsc --noEmit`もエラー0件(ビルドコマンドの前段として実行され、後述のフロントエンド
修正後も再実行して0件を確認)。

**`package.json`/`package-lock.json`は無変更**(`npm install`は既存lockfileからの復元のみ):
```
$ git diff -- desktop/package.json desktop/package-lock.json
(出力なし)
```

---

## 3. モックモードでの実表示確認・不具合の発見と修正

`VITE_MOCK=1 npm run dev`(http://localhost:1420)を起動し、Playwright(`npx`キャッシュに
既存のplaywrightパッケージを`node_modules/playwright`へシンボリックリンクして使用 —
`package.json`は変更していない。`node_modules`自体は`.gitignore`対象で追跡外)経由で
実際にクリック・入力操作をしながら画面を辿った。

### 3.1 発見した不具合1: 基準台帳の承認導線が実際には機能していなかった(既存スクショが撮影ミス)

着手時点で`desktop/docs/screenshots/phase3/`には5枚のPNGが既にあったが、目視すると
2件の問題があった:
1. `criteria-drafts.png`と`criteria-ledger.png`が**完全に同一ファイル**(md5一致)で、
   承認操作の前後差分を撮影できていなかった。
2. `detail-verdict-form.png`等3枚は、サイドバーに「基準台帳」ナビ項目が無い
   状態(t4マージ前)で撮影されたものだった。

`desktop/scripts/shot.mjs`に基準台帳の2状態(下書き2件→1件目承認後1件)を実際に
ボタンクリックして撮り分けるステップを追加し、全8枚(list/detail/new + phase3の5枚)を
統合後の状態で再撮影した(4章参照)。

### 3.2 発見した不具合2(コードの不具合・本タスクで修正): ミッション詳細ページ間のUI状態リーク

Playwrightで「裁定を記録→別ミッションのURLへ直接遷移」を試したところ、遷移先の
ミッション(未裁定・別のawaiting_humanミッション)に前のミッションの
「検収裁定を記録しました」という成功バナーが残留して表示されることを発見した。

原因: `desktop/src/pages/MissionDetailPage.tsx`の`missionId`変更時`useEffect`
(96-143行目)が`status`/`ledgerLines`/`liveLines`はリセットしていたが、検収裁定
フォーム(`verdictPassed`/`verdictReason`/`verdictResult`)と人間依頼フォーム
(`humanNotes`/`humanResults`/`humanDetailsOpen`)のローカルstateをリセットしていな
かった。React側は`<MissionDetailPage missionId={route.missionId} .../>`に`key`を
渡していないため、ミッションを跨ぐ遷移時にコンポーネントがアンマウントされず
stateが持ち越される。

再現手順(Playwright, VITE_MOCK=1):
1. `#/mission/b1c2d3e4`(done未裁定)を開き、合格を選択・理由入力・「裁定を記録」
   をクリック → 「検収裁定を記録しました」バナーと裁定済みカードが表示される
2. `window.location.hash`を`#/mission/d1e2f3a4`(awaiting_humanミッション、未裁定)
   へ直接変更(URLバー遷移・ブラウザ戻る等でも同じ経路)
3. **修正前**: 遷移先の画面にも「検収裁定を記録しました」バナーが残留して表示
   された(このミッションでは裁定操作を一度も行っていないにもかかわらず)
4. **修正後**: バナーは表示されない(`page.locator("text=検収裁定を記録しました").count()` が 0 を確認)

修正: 同`useEffect`内に以下を追加(`desktop/src/pages/MissionDetailPage.tsx`):
```ts
setVerdictPassed(null);
setVerdictReason("");
setVerdictResult(null);
setHumanNotes({});
setHumanResults({});
setHumanDetailsOpen({});
```
修正後、`npx tsc --noEmit`エラー0件・`npm run build`成功(2.3節)・pytestとcargo testは
Rust/Python側に影響しないコード変更のため無変更のまま320件/32件成功を再確認済み。

この不具合は今回のスコープ(検収裁定・人間依頼UI)に直接属する回帰であり、
「画面はあるが未統合」という先行タスク報告の再検証という本タスクの主旨に沿って
最小限の修正を行った。CLIコア(`orgh/`)・Tauriブリッジ(`.rs`)・`ORGH_APPROVED=`
契約には一切手を入れていない。

### 3.3 目視確認した画面・操作(スクリーンショット一覧)

`desktop/docs/screenshots/phase3/`配下、修正後の統合状態で全て再撮影(5枚、
いずれも10KB超)。

| # | 画面 | 確認した操作 | ファイル |
|---|---|---|---|
| 1 | ミッション詳細(done・未裁定) | サイドバーに「基準台帳」を含む全6ナビ項目、検収裁定フォーム(合格/不合格ラジオ・理由欄・「裁定を記録」ボタン) | `detail-verdict-form.png` |
| 2 | ミッション詳細(done・裁定済み) | 裁定記録カード(合格バッジ・日時・理由文)の表示 | `detail-verdict-recorded.png` |
| 3 | ミッション詳細(awaiting_human) | 「人間対応が必要なタスク」ブロック、依頼理由・完了報告欄・「完了を報告」ボタン | `detail-human-request.png` |
| 4 | 基準台帳(下書き2件) | `#/criteria`遷移、下書き2件(承認待ち)と本台帳(design 2件・process 1件)の表示 | `criteria-drafts.png` |
| 5 | 基準台帳(承認後) | 1件目の「承認」ボタンを実際にクリックし、下書きが1件に減ることを確認(モック承認導線が実際に動作) | `criteria-ledger.png` |

さらに、インタラクティブ操作(クリック・入力・送信)自体が正しく動くことも
Playwrightで確認した(スクリーンショットは`/tmp`一時保存、リポジトリには含めていない):
- 検収裁定フォームへの入力→送信→裁定記録カードへの反映(3.2節の再現手順1)
- 人間依頼フォームへの入力→「完了を報告」送信→タスクが`done`化しミッション
  全体が`完了`ステータスに遷移すること
- 基準台帳の「承認」クリック→下書きが台帳から消えること(3.1節)

### 3.4 既存画面の回帰確認

一覧(`list.png`)・新規ミッション(`new.png`)は「基準台帳」ナビ追加後もレイアウト
崩れなく表示されることを確認(再撮影済み)。設定画面(`#/settings`)もモックモードで
正常表示を確認した。

**既知の問題(本タスクのスコープ外・先行フェーズからの既存バグ)**: レポート画面
(`#/report`)とPlaybook画面(`#/playbooks`)は、`VITE_MOCK=1`モードで開くと
`TypeError: Cannot read properties of undefined (reading 'invoke')`で失敗する。
原因は`ReportPage.tsx`/`PlaybooksPage.tsx`が`api.ts`のモック対応ラッパーを経由せず
`@tauri-apps/api/core`の`invoke()`を直接呼んでいるため(`git log --follow`で
コミット`541b4ed`/`fed2629`、mission `4d048081`(第2期)時点から存在する既存コード
と確認 — 本タスク`4892cfca`が壊したものではない)。第2期の検証記録
(`VERIFY-PHASE2.md`)はこの2画面を`VITE_MOCK`ではなくPlaywrightで
`window.__TAURI_INTERNALS__`を注入するシム方式で確認しており、素の`VITE_MOCK`
モードでは元々未検証だった経路だと考えられる。今回のスコープ(検収裁定・
基準台帳・人間依頼)には無関係のため本タスクでは修正していないが、次期で
`ReportPage`/`PlaybooksPage`も`api.ts`経由(`report()`/`playbooks()`)へ揃え、
`mocks.ts`に`MOCK_REPORT`/`MOCK_PLAYBOOKS`相当を追加することを推奨する。

### 3.5 `ORGH_APPROVED=`確認行契約の非破壊確認

```
$ grep -rn 'ORGH_APPROVED=' desktop/src-tauri/src orgh/
desktop/src-tauri/src/commands.rs:102:        cli::spawn_and_bridge(app, bin, args, Some(mission_id), "ORGH_APPROVED=").map(|_| ())
desktop/src-tauri/src/commands.rs:133:// owner_verdict/criteria_*/human_doneは確認行の待受(ORGH_APPROVED=等)を...
desktop/src-tauri/src/cli.rs:96:/// `confirm_prefix`(approve: `ORGH_APPROVED=` / resume: `ORGH_RESUMED=`)の...
desktop/src-tauri/src/cli.rs:178:    // stdout: 確定行(start: ORGH_MISSION_ID= / approve: ORGH_APPROVED=)を検出し、...
orgh/cli.py:374:        # (ORGH_APPROVED=)より必ず前に出す
orgh/cli.py:395:        print(f"ORGH_APPROVED={mission.id}", flush=True)
orgh/status_json.py:41:    `ORGH_APPROVED=`で始まる行を偽造されてしまう(cli.rsのstrip_prefix検知が...
```

`approve_mission`(commands.rs:102)は従来どおり`spawn_and_bridge`+`ORGH_APPROVED=`
確認行方式のまま。新規5コマンド(`owner_verdict`/`criteria_*`/`human_done`)は
コメント(commands.rs:133-135)で明示されているとおり、この契約に一切触れない
別経路(`cli::run_sync`/`cli::run_json`、確認行を持たない同期コマンド)を使う。
`status_json.py`の改行注入対策(タイトル中の偽装`ORGH_APPROVED=`行をスペースへ
畳む処理)もそのまま残っている。契約に変更なし。

---

## 4. スクリーンショット差分表(統合前後)

| ファイル | 統合前(着手時点) | 統合後(本タスクで再撮影) |
|---|---|---|
| `phase3/detail-verdict-form.png` | サイドバーに「基準台帳」ナビ無し(t4マージ前の状態で撮影) | 全6ナビ項目(基準台帳含む)表示、内容は同一操作 |
| `phase3/detail-verdict-recorded.png` | 同上 | 同上 |
| `phase3/detail-human-request.png` | 同上 | 同上 |
| `phase3/criteria-drafts.png` | `criteria-ledger.png`と完全同一ファイル(撮り分け失敗) | 下書き2件の初期状態を正しく撮影(読み込み完了後) |
| `phase3/criteria-ledger.png` | 同上(重複) | 実際に「承認」をクリックした後、下書き1件に減った状態を撮影 |
| `screenshots/list.png`/`new.png`/`detail.png` | 「基準台帳」ナビ無しの旧版 | 統合後の全ナビ項目入りで再撮影(回帰無しの確認を兼ねる) |
| `desktop/src/pages/MissionDetailPage.tsx` | ミッション間遷移でverdict/human関連stateが残留(3.2節) | `useEffect`にリセット処理を追加、残留を解消 |
| `desktop/scripts/shot.mjs` | 基準台帳の撮影ステップが無かった(手動撮影で重複ミスが発生した推定原因) | 承認操作を伴う2状態の自動撮影ステップを追加 |

---

## 5. ドキュメント反映

- `README.md`「デスクトップアプリ」節に、検収裁定・人間依頼・基準台帳の3機能の説明と、
  `VERIFY-PHASE2.md`/`VERIFY-PHASE3.md`へのリンクを追加した。
- `desktop/API.md`は§1.8〜1.10(verdict/criteria/humandone)・Tauriコマンド表
  (§2)・§2.1(確認行契約の対象外である旨)に、5コマンドの契約が**既に**t2の
  契約確定タスクによって記述済みであることを確認した。ファイル所有権規約
  (API.md冒頭「後続タスクは編集禁止」)に従い、内容が実装と一致していることを
  確認した上で追記はしていない(既に正確なため)。

---

## 6. 残課題

正直に列挙する。「無し」ではない。

1. **レポート/Playbook画面が`VITE_MOCK=1`単体では動かない**(3.4節)。本タスクの
   スコープ外の既存バグ(mission 4d048081由来)。次期で`api.ts`経由に揃えることを推奨。
2. **実アプリ(.app)でのネイティブスクリーンショットは本実行環境では取得不可**
   (screencapture権限の制約、第1期・第2期から継続する既知の環境制約)。本タスクも
   前期同様Playwright経由のブラウザ再現で代替した。
3. **`基準台帳`ページからミッション詳細への逆導線、またはミッション詳細から
   基準台帳への直接リンクは無い**(サイドバーナビ経由のみ)。PRD側の受け入れ基準に
   個別導線の明記が無いため未対応のままだが、UX改善の余地として記録する。
4. `criteria-ledger.png`は「1件目の下書きを承認した直後」の状態であり、2件目
   (「破壊的操作は人間対応へ委譲」)の下書きは意図的にモックデータとして
   残したまま撮影している(承認導線が実際に機能することを差分で示すため)。

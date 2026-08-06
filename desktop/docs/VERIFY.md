# orgh Desktop — 実データ結線・実起動検証記録(VERIFY.md)

前段3タスクの成果(a) CLI-JSON面 `orgh/{listing,events_json,status_json,doctor}.py` /
(b) Rustブリッジ `desktop/src-tauri/**` /
(c) React UI `desktop/src/**` を実際に結線し、org-harness 本体リポジトリの実
`runs/`(過去ミッション8件)を使ってデスクトップアプリを実起動させた記録。

検証環境: macOS 15.5 (Darwin 24.5.0) / Apple M4 / Node v24.7.0 / npm 11.5.1 /
Python 3.14.6(orgh実行用に別途 `~/.orgh-venv` を用意) / Rust stable 1.97.1
(本タスクで `rustup` 経由で導入。ユーザーのシェルrc設定は変更せず、各コマンド実行時に
`export PATH="$HOME/.cargo/bin:$PATH"` で明示指定した)。

---

## 1. 契約整合性レビュー(結線で見つかった不整合)

Rustブリッジ実装タスク・フロントエンドUI実装タスクの両方が `desktop/API.md` /
`desktop/src/types.ts` を厳密に踏襲していたため、**コードレベルの不整合は0件**だった。
以下の対応関係を1件ずつ実データで突き合わせて確認済み:

| 確認項目 | orgh CLI(`--json`) | Rust `models.rs` | TS `types.ts` | 結果 |
|---|---|---|---|---|
| `list_missions` | `orgh list --json` → `mission_id/intent/status/cost_usd/tasks_done/tasks_total` | `MissionSummary`(`#[serde(rename(serialize="missionId"...))]`等でcamelCase化) | `MissionSummary`(`missionId/costUsd/tasksDone/tasksTotal`) | 一致 |
| `mission_status` | `orgh status <id> --json` → `mission_id/intent/status/tasks[]/cost_usd/budget_usd` | `MissionStatus`/`TaskStatus` | `MissionStatus`/`TaskStatus` | 一致(`budget_usd: null`もOption<f64>で正しくハンドリング) |
| `mission_events` | `orgh events <id> --json --tail N` → `events[]`(`ts`/`event`固定、他は自由形式) | `LedgerEvent`(`#[serde(flatten)] extra: BTreeMap`で未知キー保持) | `LedgerEvent`(インデックスシグネチャ) | 一致 |
| `doctor` | `orgh doctor --json` → `ok/checks[]` | `DoctorReport`/`DoctorCheck` | 同左 | 一致(`ok:false`でも終了コード非0のままJSONは完全体で返る仕様も`interpret_response`のテストで担保済み) |
| `start_mission`/`approve_mission` の `ORGH_MISSION_ID=<id>` 行検出 | `orgh run`が`mission {id}: N tasks`の次行で出力(`orgh/cli.py`) | `spawn_and_bridge`が`strip_prefix("ORGH_MISSION_ID=")`で検出 | — | 一致 |
| コマンド名・引数名 | — | `list_missions/mission_status/mission_events/start_mission/approve_mission/cancel_mission/doctor/get_settings/set_settings`(`lib.rs`の`generate_handler!`) | `api.ts`の`invoke("mission_status", { missionId })`等(Tauri既定のcamelCase自動変換に依拠) | 一致 |
| `Settings`型 | — | `orgh_bin/config_path/runs_dir` + `#[serde(rename_all="camelCase")]` | `orghBin/configPath/runsDir` | 一致 |

このため、API.md自体の書き換えは発生していない。**唯一コードを変更したのはビルド設定
`desktop/src-tauri/tauri.conf.json` の1箇所**(下記2章)で、これはCLI-Rust-TS間の契約とは
無関係な、この検証環境固有のビルド阻害要因への対処である。

### 差分表(変更前→変更後→理由)

| ファイル | 変更前 | 変更後 | 理由 |
|---|---|---|---|
| `desktop/src-tauri/tauri.conf.json` | `"bundle": { "active": true, "targets": "all" }` | `"bundle": { "active": true, "targets": ["app"] }` | `targets: "all"`だと macOS の `.app` に加えて `.dmg` も生成しようとし、`bundle_dmg.sh` が内部で `osascript`(Finderのウィンドウレイアウト設定用AppleScript)を呼ぶ。この検証環境ではGUI自動化(Accessibility/Automation)権限を対話的に許可できず`osascript`が無限に応答待ちでハングし、`npm run tauri build -- --debug` が終了コード0で終わらない(dmgバンドリング自体が失敗する)。受け入れ条件が要求するのは「`.app`もしくは実行バイナリの存在」であり`.dmg`は不要なため、`targets`を`["app"]`に限定してビルドを`.app`のみに絞った。API.md契約(CLI⇔Rust⇔TS)には一切影響しない。 |

---

## 2. `npm install` / `npm run tauri build -- --debug`

### 2.1 環境準備

- `cargo`が未導入だったため `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y` でRust(stable 1.97.1)を導入。ユーザーの`~/.zshrc`等は変更していない(各コマンド実行時に`export PATH="$HOME/.cargo/bin:$PATH"`を明示)。
- `orgh` CLIがPATHに無かったため、`python3 -m venv ~/.orgh-venv && ~/.orgh-venv/bin/pip install -e <このworktree>` で editable install し、`~/.local/bin/orgh`(既定PATHに含まれるディレクトリ)へシンボリックリンクした。`~/.local/bin/orgh -> ~/.orgh-venv/bin/orgh`。

### 2.2 `npm install`

```
$ cd desktop && npm install
added 128 packages, and audited 129 packages in 813ms
9 packages are looking for funding
2 vulnerabilities (1 moderate, 1 high)
```
終了コード0。脆弱性警告は既存の`package.json`依存(`@tauri-apps/*`/`vite`等)由来で、
このタスクのスコープ外(依存追加はしていない)。

### 2.3 `npm run tauri build -- --debug`(最終実行・成功)

```
$ npm run tauri build -- --debug
> orgh-desktop@0.1.0 tauri
> tauri build --debug
     Running beforeBuildCommand `npm run build`
> orgh-desktop@0.1.0 build
> tsc && vite build
vite v5.4.21 building for production...
✓ 47 modules transformed.
dist/index.html                   0.40 kB │ gzip:  0.27 kB
dist/assets/index-CS-KlgJr.css   10.91 kB │ gzip:  3.06 kB
dist/assets/core-BMtQprb4.js      0.54 kB │ gzip:  0.29 kB
dist/assets/event-CqUVweiu.js     1.83 kB │ gzip:  0.72 kB
dist/assets/index-DQz-nJMW.js   258.99 kB │ gzip: 64.12 kB
✓ built in 315ms
   Compiling orgh-desktop v0.1.0 (.../desktop/src-tauri)
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 2.56s
       Built application at: .../desktop/src-tauri/target/debug/orgh-desktop
    Bundling orgh Desktop.app (.../desktop/src-tauri/target/debug/bundle/macos/orgh Desktop.app)
    Finished 1 bundle at:
        .../desktop/src-tauri/target/debug/bundle/macos/orgh Desktop.app

$ echo "EXIT_CODE=$?"
EXIT_CODE=0
```

生成物:
```
$ file "desktop/src-tauri/target/debug/bundle/macos/orgh Desktop.app/Contents/MacOS/orgh-desktop"
.../orgh-desktop: Mach-O 64-bit executable arm64
```

(参考: `tauri.conf.json`修正前の1回目の実行では`.app`生成後に`.dmg`バンドリングで
`bundle_dmg.sh`がハングし、`failed to bundle project: error running bundle_dmg.sh`で
終了コード非0だった。原因は1章末尾の差分表に記載の通り。)

---

## 3. 実起動検証

### 3.1 GUI設定の事前投入

`get_settings`/`set_settings`のデフォルト(`orghBin: "orgh"`, `configPath: "config.yaml"`,
`runsDir: "runs"`)は相対パス前提で、`open`で起動したGUIアプリのプロセスcwdは
リポジトリルートと一致しない。実データに結線するため、Tauriのapp_config_dir
(`~/Library/Application Support/com.orgh.desktop/settings.json`)に以下を事前投入した:

```json
{
  "orghBin": "/Users/uesugirei/.orgh-venv/bin/orgh",
  "configPath": "/Users/uesugirei/projects/org-harness/config.yaml",
  "runsDir": "/Users/uesugirei/projects/org-harness/runs"
}
```

`config.yaml`の`runs_dir`は`/Users/uesugirei/projects/org-harness/runs`を指しており、
ここには過去ミッション8件(`09957da4`/`0f9d5591`/`7307189e`/`8e096d63`/`a385f876`/
`b6503b9a`/`d0d795d4`/`db8e54e5`)の実データがある。

### 3.2 orgh CLI-JSON面の実データ疎通確認(単体)

```
$ orgh --config config.yaml list --json
{"missions": [{"mission_id": "09957da4", "intent": "ノート「スロット筐体のUIが...", "status": "done", "cost_usd": 41.101011899999996, "tasks_done": 6, "tasks_total": 6}, ... 計8件 ...]}

$ orgh --config config.yaml status db8e54e5 --json
{
  "mission_id": "db8e54e5", "intent": "ノート「Sikoslot デプロイ」の内容を実行可能な成果に落とし込む",
  "status": "done",
  "tasks": [{"id": "t1", ..., "status": "done", "attempts": 1, "worker": "claude_code", "deps": []}, ...],
  "cost_usd": 4.0913816999999995, "budget_usd": null
}

$ orgh --config config.yaml events db8e54e5 --json --tail 3
{"mission_id": "db8e54e5", "events": [{"ts": 1785971092.7981231, "event": "task.review", "task": "t2", "passed": true}, ...]}

$ orgh --config config.yaml doctor --json
{"ok": true, "checks": [{"name": "worker:claude_code", "ok": true, "detail": "2.1.223 (Claude Code)"}, {"name": "worker:codex", "ok": true, "detail": "codex-cli 0.146.0"}, ..., {"name": "runs_dir", "ok": true, "detail": "/Users/uesugirei/projects/org-harness/runs"}]}
```

4コマンドとも実データで正常応答。返却スキーマは1章の対応表通りRust側の構造体と一致。

### 3.3 実際の`.app`起動と生存確認(`ps`)

```
$ open "desktop/src-tauri/target/debug/bundle/macos/orgh Desktop.app"
$ sleep 10
$ ps aux | grep -i "orgh-desktop" | grep -v grep
uesugirei        83456   0.0  0.5 416379936  87904   ??  S    12:50#午前   0:00.22 /Users/uesugirei/projects/org-harness/.orgh-worktrees/8e096d63-t4/desktop/src-tauri/target/debug/bundle/macos/orgh Desktop.app/Contents/MacOS/orgh-desktop
```

10秒経過後もプロセス生存(状態`S`=sleeping、正常稼働中)。プロセスの起動から終了までを
`log show`(統合ログ)でも追跡し、WebKitがフロントエンドをロードし
`WebPageProxy::didFinishLoadForFrame` まで到達していることを確認した(エラーログなし)。

さらに、ウィンドウが実際に画面上へ描画されていることを`CGWindowListCopyWindowInfo`
(Swiftの小さな検証ツールを一時的にビルドして使用)で直接確認した:

```
$ ./listwin | grep -i "orgh Desktop"
orgh Desktop | layer=0 | name= | bounds=["X": 135, "Y": 47, "Width": 1200, "Height": 800]
```

`layer=0`(通常ウィンドウ層)・`bounds`が`tauri.conf.json`の`windows[0]`設定
(`width:1200, height:800`)と一致するサイズでオンスクリーンに存在することを確認できた。
検証後、このプロセスは`kill`で終了させた(ユーザーの実デスクトップ上で稼働中の
他アプリに影響を与えないため)。

---

## 4. 目視記録(スクリーンショット)と`screencapture`失敗の経緯

### 4.1 `screencapture`が実質的に失敗した経緯

タスク指示通り、まず`screencapture -x desktop/docs/screenshots/app-running.png`を
実行したが、**終了コードは0でファイルも生成されるものの、内容はデスクトップの壁紙のみで
どのウィンドウ(orgh Desktop含む)も写っていなかった**。これはmacOSの既知の仕様で、
Screen Recording権限が付与されていないプロセスから`screencapture`(フルスクリーンモード)
を呼ぶと、エラーを返さずに「壁紙のみのダミー画像」を返す。本検証を実行しているエージェント
実行環境(プロセスツリー: `zsh → claude → Python.app → zsh → claude → zsh`)には
Screen Recording権限が付与されておらず、かつ許可ダイアログはGUI操作でのみ解決できるため
(非対話的セッションからは`Allow`をクリックできない)、この場では恒久的に解消できない。

同じ権限不足はウィンドウ指定キャプチャでも明示的なエラーとして現れ、原因を裏付けている:

```
$ screencapture -x -l23837 /tmp/window_test.png
could not create image from window
$ echo $?
1
```

(`23837`は`CGWindowListCopyWindowInfo`で取得した実際の`orgh Desktop`ウィンドウID)

### 4.2 フォールバック: Playwrightでの実データ画面撮影

タスク指示の通り、フォールバックとして「devサーバをモック無しで起動しPlaywrightで撮影」
を実施した。ただし`desktop/src/api.ts`の`isTauriRuntime()`は、Tauriの`window.__TAURI_INTERNALS__`
が存在しない環境(素のブラウザ)では常にモックへフォールバックする設計(意図通りの仕様、
`API.md`が要求する挙動ではなく実装側の安全側デフォルト)であるため、単純に`vite`の
devサーバをブラウザで開いても本物のCLIデータは出せない。

そこで、**この撮影作業専用の一時的なローカルHTTPブリッジ**(`orgh --config ... <cmd> --json`
をそのまま呼び出し、Rust側と同じsnake_case→camelCase変換をかけて返すだけの単純なPythonスクリプト、
`/tmp`配下に作成・リポジトリには一切含めていない)を用意し、`desktop/src/api.ts`に
`VITE_REAL_HTTP_BRIDGE=1`のときだけこのHTTPブリッジ経由で実データを取得する分岐を**一時的に**
追加してスクリーンショットを撮影した後、**`git checkout -- desktop/src/api.ts`で完全に元へ戻した**
(最終的な差分に一切残っていないことは`git status`/`git diff`で確認済み)。この迂回はあくまで
「サンドボックス環境のScreen Recording権限が使えないことの代替証跡」を得るためのものであり、
実際のTauriアプリ(3.3節で確認済み)はこのブリッジを一切使わず、本来の`invoke()`経路のみで動作する。

撮影時に発覚した副次的な事実(コード変更不要・記録のみ): 一時ブリッジの初版はCLIのsnake_case
JSONをそのまま返しており、`MissionListPage`が`costUsd.toFixed()`で`undefined`エラーを
起こした。これは一時ブリッジ側がRustの`#[serde(rename(...))]`と同等のcamelCase変換を
していなかったための自作自演のバグであり、実際のRustブリッジ(`models.rs`)は最初から
正しくcamelCase変換している(1章の突き合わせ・`cargo test`で担保済み)。ブリッジ側の
変換ロジックを修正して撮り直し、正常表示を確認した。

撮影結果(`desktop/docs/screenshots/app-running.png`、ミッション詳細画面):
実ミッションID `09957da4`、実タスク6件(`t1`〜`t6`、すべて`done`、`worker: claude_code`)、
実コスト`$41.1010`が表示されている。これは3.2節で直接確認した
`orgh status 09957da4 --json`の値と一致する。レイアウト崩れなし(サイドバー・
ヘッダー・コスト/予算カード・タスク表・依存関係DAGが正しく描画されている)。

一覧画面(`desktop/docs/screenshots/app-running-list.png`、参考添付・受け入れ条件外)には
実ミッション8件全件のmission_id/intent/status/進捗/costが正しく一覧表示されていることも
確認した。

両ファイルとも100KB超(20KB以上の受け入れ条件を満たす)。

---

## 5. 既存挙動への影響確認

```
$ /Users/uesugirei/.orgh-venv/bin/python -m pytest tests/ -q
........................................................................ [ 43%]
........................................................................ [ 86%]
......................                                                   [100%]
166 passed in 13.61s
```

Python側は無変更(`orgh/`配下は今回一切編集していない)。参考として`desktop/src-tauri`の
Rust単体テスト/統合テストも実行し、全17件成功を確認した:

```
$ cargo test
running 11 tests (lib) ... ok (11 passed)
running 6 tests (tests/orgh_cli_integration.rs) ... ok (6 passed)
```

`git status --porcelain`は以下のみ(node_modules/target/dist配下のファイルは含まれない
— リポジトリルートの`.gitignore`で`node_modules/`・`desktop/src-tauri/target/`・
`desktop/src-tauri/gen/`・`dist/`を除外済み):

```
 M desktop/src-tauri/tauri.conf.json
?? desktop/docs/VERIFY.md
?? desktop/docs/screenshots/app-running-list.png
?? desktop/docs/screenshots/app-running.png
```
（README.mdへの追記を含めると変更ファイルはさらに1件増える。)

---

## 6. 既知の制約

- **Rustツールチェーン必須**: `cargo build`/`tauri build`にはRust stable(このタスクでは
  1.97.1で確認)が必要。未導入環境では`rustup`でのインストールが必要(数分)。
- **orghがPATHに必要**(または`Settings.orghBin`に絶対パス指定): Rustブリッジは`orgh`を
  子プロセスとして起動するだけの薄いラッパであり、PythonのCLIロジックを再実装していない
  ため、`orgh`コマンド自体が解決できないと全コマンドが失敗する。今回は`pip install -e .`
  相当のeditable installを`~/.orgh-venv`に作り、`~/.local/bin/orgh`へシンボリックリンクした。
  本番導入時はユーザーが任意の方法(pipx/venv等)で`orgh`をインストールし、GUIの設定画面
  (`get_settings`/`set_settings`)で`orghBin`にフルパスを指定することを想定。
- **`configPath`は絶対パス指定を強く推奨**: デフォルト値`config.yaml`は相対パスであり、
  GUIプロセスの実行時cwdに依存する。`open`でLaunchServices経由起動した場合、cwdは
  リポジトリルートと一致する保証がないため、初回起動時に設定画面から`config.yaml`の
  絶対パスを指定する必要がある(3.1節)。
- **`.dmg`バンドリングはこの検証環境では未検証**: 1章の差分表の通り、`bundle_dmg.sh`が
  内部で呼ぶ`osascript`(Finder自動化)がAccessibility/Automation権限を要求し、この
  非対話的環境では許可できずハングする。実際のユーザー端末(対話的にGUI操作可能な環境)
  では`targets: "all"`に戻せば`.dmg`も生成できるはずだが未確認。配布用`.dmg`が必要な場合は
  対話的な環境で`npm run tauri build`(`--debug`なし)を実行し、初回のみ権限ダイアログを
  手動で許可すること。
- **screencaptureによる実機スクリーンショットはこのサンドボックス環境では取得不可**:
  4.1節の通りScreen Recording権限が対話的にしか付与できないため。実際のユーザー端末では
  通常この制約はない(権限ダイアログで`許可`を押すだけで解消する)。
- 本検証で発生した副作用: `System Events`へのAccessibility権限を問い合わせるダイアログ
  (`universalAccessAuthWarn`)が画面上に残った状態で本タスクを終えている。ユーザーが
  次回このMacの画面を確認する際、手動で閉じる(「許可しない」を押す、またはダイアログを
  閉じる)必要がある。このタスク実行環境からはクリック操作ができないため解消できなかった。

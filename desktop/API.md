# orgh Desktop — GUI-CLI連携 契約(API.md)

このファイルは `desktop/src/types.ts` とセットで **真実源(SSOT)**。
後続の「Rustブリッジ実装タスク」(`desktop/src-tauri/**` を担当)と
「フロントエンドUI実装タスク」(`desktop/src/**` を、`types.ts` を除いて担当)は、
この2ファイルだけを見て並列に作業する。曖昧な箇所があればこのファイルの
記述を優先し、憶測で実装しない。

## 0. ファイル所有権(重要・厳守)

| パス | 担当 | 備考 |
|---|---|---|
| `desktop/API.md` | このタスク(契約タスク)のみ | 後続タスクは編集禁止 |
| `desktop/src/types.ts` | このタスク(契約タスク)のみ | 後続タスクは編集禁止 |
| `desktop/src-tauri/**` | Rustブリッジ実装タスク | `#[tauri::command]` 本体・イベント発火・Cargo依存追加はここ |
| `desktop/src/**`(`types.ts` を除く) | フロントエンドUI実装タスク | React UI・`invoke()`呼び出しコードはここ |
| `desktop/package.json` 等ビルド設定 | 両タスク共通(必要なら双方が追記可) | 依存追加時は競合に注意 |

後続タスクがこの契約に矛盾を見つけた場合、`API.md`/`types.ts` を直接書き換えず、
上位(このタスクの発行元)に差し戻すこと。

## 1. 前提: orgh CLIのJSON面

すべて `orgh <cmd> ... --json` の形で呼ぶ。**stdoutに単一のJSONオブジェクトのみ**
を出力し、正常時は終了コード0。エラー時は `{"error": "<message>"}` を出力し
終了コードは非0。テキスト出力(`--json`なし)は既存のまま変更していない。

### 1.1 `orgh list --json`

```json
{
  "missions": [
    {
      "mission_id": "a1b2c3d4",
      "intent": "要約済みintent(60文字超は…で切り詰め、改行はスペースに置換)",
      "status": "empty" | "running" | "done" | "failed",
      "cost_usd": 0.1234,
      "tasks_done": 2,
      "tasks_total": 5
    }
  ]
}
```
- 実装: `orgh/listing.py` `list_missions_report()` を再利用(`orgh/cli.py` の `list --json` 分岐)。
- `status` 派生規則(`orgh status --json` と同一規則): タスク0件→`empty`。全件`done`→`done`。1件でも`failed`→`failed`。1件でも`awaiting_approval`→`awaiting_approval`。全件終端(done/cancelled/skipped)で`done`以外を含む→`cancelled`。それ以外→`running`。
- ミッションが1件もない場合 `{"missions": [], "skipped": []}`(エラーではない)。
- `runs/` 配下の壊れた `mission.json`(JSON不正など)は `skipped` 配列(`{"path": ..., "reason": ...}`)として明示的に返る。黙殺すると「0件」とデータ破損をGUIが区別できないため。

### 1.2 `orgh events <mission_id> --json [--tail N]`

```json
{
  "mission_id": "a1b2c3d4",
  "events": [
    {"ts": 1733500000.123, "event": "task.start", "task": "t1", "worker": "claude_code", "attempt": 1},
    {"ts": 1733500012.456, "event": "task.output", "task": "t1", "ok": true, "cost": 0.0031}
  ]
}
```
- 実装: `orgh/events_json.py` `events_payload()`。`runs/<mission_id>/ledger.jsonl` を読み、
  壊れた行(JSONとして読めない行)はスキップする。
- `--tail` 省略時は既定100件。末尾からN件(`--tail 0` は空配列)。
- `event` の種類とそれに付随するフィールドは固定スキーマではない
  (`orgh/orchestrator.py` の `store.log("task.start", task=..., worker=..., attempt=...)` 等、
  呼び出し箇所ごとにキーが異なる自由形式)。`ts`/`event`は必ず存在する。
- 対象ミッションのディレクトリ自体が存在しない場合はエラー
  (`{"error": "mission '<id>' not found"}`、終了コード非0)。
  ディレクトリはあるが `ledger.jsonl` がまだない場合は `{"mission_id": ..., "events": []}`(エラーではない)。

### 1.3 `orgh doctor --json`

```json
{
  "ok": true,
  "checks": [
    {"name": "worker:claude_code", "ok": true, "detail": "1.2.3"},
    {"name": "role:planner", "ok": true, "detail": "(= claude)"},
    {"name": "config", "ok": true, "detail": "検証済み"},
    {"name": "prompts_dir", "ok": true, "detail": "/path/to/prompts"},
    {"name": "vault", "ok": true, "detail": "未設定(watch/scanを使わないなら問題なし)"},
    {"name": "runs_dir", "ok": true, "detail": "/path/to/runs"}
  ]
}
```
- 実装: `orgh/doctor.py` `doctor_payload()`。テキスト出力(`orgh doctor`)と同じ内部チェック結果
  (`_run_checks()`)を共有しており、テキスト/JSONで判定結果が食い違うことはない。
- `checks[].name` は固定リストではない(`workers.enabled` / `roles` の設定次第で
  `worker:<name>` / `role:<name>` が増減する)。`config` / `prompts_dir` / `vault` / `runs_dir`
  の4つは常に1件ずつ出る。
- `ok`(トップレベル)が`false`のとき、CLIの終了コードは非0。

### 1.4 `orgh status <mission_id> --json`(既存・変更なし)

```json
{
  "mission_id": "a1b2c3d4",
  "intent": "...",
  "status": "running" | "done" | "failed",
  "tasks": [
    {"id": "t1", "title": "...", "status": "done", "attempts": 1, "worker": "claude_code", "deps": []}
  ],
  "cost_usd": 0.5,
  "budget_usd": 2.0
}
```
実装: `orgh/status_json.py` `status_payload()`(このタスクでは変更していない)。

### 1.5 `orgh run` 標準出力への `ORGH_MISSION_ID` 行

`orgh run --intent "..."` / `orgh run --note "..."` は、Planner実行(計画)が完了した直後、
既存の `mission <id>: N tasks` 行の**次の行**として、追加で以下の1行を出す
(既存行は削除していない):

```
ORGH_MISSION_ID=<mission_id>
```

その後もプロセスは実行を継続し(`== executing ==` 以降、タスク実行・レビュー・retroまで)、
最終的な `mission <id>: <intent>` サマリを出して終了する。**`orgh run` はミッション完走まで
ブロックする長時間プロセス**である前提でRustブリッジを設計すること(詳細は §3.1)。

`orgh approve <mission_id>` も同様に、承認後 `run_mission()` を呼んでミッション完走まで
ブロックする(ただし `ORGH_MISSION_ID` 行は出さない — 既にmission_idが引数として
分かっているため不要)。

## 2. Tauriコマンド契約(Rust側 `#[tauri::command]`)

命名規約: **Rust関数名・引数はsnake_case**で書く(例: `mission_id: String`)。
Tauriの既定動作でJS側の `invoke()` 引数名は自動的にcamelCaseへ変換されるため、
`#[tauri::command(rename_all = "snake_case")]` 等の上書きは行わないこと
(既定のまま — JS側は `invoke("mission_status", { missionId })` のように呼ぶ)。
戻り値の構造体は明示的に `#[derive(Serialize)]` + `#[serde(rename_all = "camelCase")]`
を付け、`desktop/src/types.ts` の型とフィールド名を一致させること。

エラー表現: 全コマンド `Result<T, String>` を返す。TS側は `invoke()` の戻り値の
`Promise<T>` が reject された場合を例外(catchすべきエラー)として扱う
(`try { await invoke(...) } catch (e) { ... }`、あるいは `.catch()`)。

| コマンド | 引数 | 戻り値 | 対応するCLI |
|---|---|---|---|
| `list_missions` | なし | `ListPayload`(missions+skipped) | `orgh list --json` の出力そのもの(camelCase変換のみ) |
| `mission_status` | `mission_id: string` | `MissionStatus` | `orgh status <id> --json` の出力そのもの(camelCase変換のみ) |
| `mission_events` | `mission_id: string`, `tail: number` | `LedgerEvent[]` | `orgh events <id> --json --tail <tail>` の `events` 配列をそのまま返す |
| `start_mission` | `intent: string \| null`, `note: string \| null` | `string`(mission_id) | `orgh run --intent <intent>` または `orgh run --note <note>` を起動(§3.1) |
| `approve_mission` | `mission_id: string` | なし(`void`) | `orgh approve <id>` を起動(§3.1) |
| `cancel_mission` | `mission_id: string` | なし(`void`) | `orgh cancel <id>` を実行し完了を待つ(短時間で終わる) |
| `doctor` | なし | `DoctorReport` | `orgh doctor --json` の出力そのもの |
| `get_settings` | なし | `Settings` | GUI設定の読み出し(永続化方式はブリッジ実装タスクの裁量) |
| `set_settings` | `settings: Settings` | なし(`void`) | GUI設定の書き込み |

`intent` / `note` はどちらか一方が必須、もう一方は `null`(CLI側の `--note`/`--intent`
排他ルールに合わせる。両方 `null` はRust側でバリデーションしエラーを返すこと)。

`get_settings`/`set_settings` の `Settings` 型(TS: `desktop/src/types.ts`):
```
{ orghBin: string, configPath: string, runsDir: string }
```
- `orghBin`: `orgh` バイナリの絶対パス、またはPATH解決可能なコマンド名。他コマンド
  (`list_missions`等)を実行する際、子プロセス起動コマンドとしてこれを使う。
- `configPath`: `orgh --config <configPath>` として全コマンドに渡す。
- `runsDir`: 参考情報として保持(実際の `runs_dir` は `configPath` が指すconfig.yamlの
  `runs_dir` キーが正だが、GUI表示用にキャッシュする用途を想定)。

### 2.1 各コマンドの子プロセス起動パターン

- `list_missions` / `mission_status` / `mission_events` / `doctor`:
  `orgh --config <configPath> <cmd> ... --json` を起動し、完了(exit)を待ってstdoutを
  パースして返す短命プロセス。stderrは失敗時にエラーメッセージとして`Err`に含める。
- `cancel_mission`: `orgh --config <configPath> cancel <mission_id>` を起動し完了を待つ
  (フラグファイルを置くだけなので短時間で終わる)。失敗時は非JSON出力だが、
  終了コード非0またはstderrをエラーとして扱う。
- `start_mission` / `approve_mission`: §3.1 参照(長時間プロセス・非同期)。

## 3. Tauriイベント契約

| イベント名 | ペイロード(TS型) | 発火元 |
|---|---|---|
| `mission-log` | `MissionLogEvent` = `{ missionId: string \| null, line: string }` | `start_mission`/`approve_mission`が起動した子プロセスのstdout/stderrを1行ずつ |
| `mission-updated` | `MissionUpdatedEvent` = `{ missionId: string }` | ミッション状態が変わった可能性があるタイミング(§3.2) |

### 3.1 `start_mission` / `approve_mission` の非同期フロー(最重要・曖昧さ排除)

`orgh run` / `orgh approve` はミッション完走までブロックする長時間コマンドである
(プランニング→並列タスク実行→レビュー→retroまで)。Tauriコマンドの呼び出し元
(フロントエンド)を長時間ブロックしないため、以下の非同期フローで実装すること:

1. Rust側は子プロセス(`orgh run ...` または `orgh approve <id>`)を非同期に spawn する。
2. 子プロセスのstdoutを1行ずつ読みながら、**`ORGH_MISSION_ID=<id>` という行を検出するまで**、
   読んだ行は `mission-log`(`missionId: null`)として都度emitする。
3. `ORGH_MISSION_ID=<id>` 行を検出した時点で:
   - `mission_id` を確定させる。
   - `mission-updated { missionId: <id> }` を1回emitする。
   - `start_mission` コマンド自体はこの時点で `Ok(<id>)` を**返して完了する**
     (呼び出し元をブロックし続けない)。`approve_mission` は元々mission_idが
     既知なので、このステップ2〜3は不要 — 子プロセスspawn後すぐ `Ok(())` を返してよい。
   - `mission-log` のペイロードの `missionId` はconfirmationの行を含め、以降すべて
     確定した `<id>` を使う。
4. コマンド自体が返った後も、子プロセスは背後で動き続ける。バックグラウンドタスクが
   引き続きstdout/stderrを1行ずつ `mission-log { missionId: <id>, line }` としてemitし続ける。
5. 子プロセスが終了したら、**`mission-updated { missionId: <id> }` を最低1回emitする**
   (成功/失敗どちらの終了でも)。

`start_mission` が **仮に** `ORGH_MISSION_ID` 行を一度も出さずに(異常終了などで)
プロセスが終了した場合は、コマンドの `Promise` を子プロセスの終了時点で
`Err("<stderrの内容、なければ終了コード>")` として解決する。

**mission-updated の発火タイミングの最小保証**は「(a) mission_id判明直後」
「(b) 対象プロセス終了時」の2点。それ以上の頻度(例: `mission.json`の変更を
ポーリングして都度emitする等、タスク実行中の進捗をよりリアルタイムに反映する)は
ブリッジ実装タスクの裁量で追加してよい(UIはmission-updatedを受け取るたびに
`mission_status`/`list_missions`を呼び直して再取得する設計を前提にする — イベント
ペイロード自体には状態そのものを含めない)。

### 3.2 `mission-updated` の想定発火元(まとめ)

- `start_mission` / `approve_mission` 実行中(§3.1の(3)(5))。
- 任意(裁量): ブリッジが `runs/<id>/mission.json` の変更をポーリング/監視している場合。

`cancel_mission` は同期的に完了を待つコマンドなので、UIは `cancel_mission` の
`await` が解決した後に自分で `mission_status` を呼び直す想定であり、`cancel_mission`
自体は `mission-updated` を発火する**義務を持たない**(発火してもよいが必須ではない)。

## 4. 型定義

TypeScript側の正式な型は `desktop/src/types.ts` を参照(このAPI.mdの説明と
1:1で対応させてある)。Rust側は同じ形の構造体を `#[serde(rename_all = "camelCase")]`
付きで定義すること。フィールド名・任意性(`| null` の有無)は `types.ts` を正とする。

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
      "status": "empty" | "running" | "done" | "failed" | "awaiting_approval" | "cancelled",
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
    {"name": "worker:claude_code", "ok": true, "detail": "1.2.3 / 認証: 確認済み", "kind": "connectivity", "auth_state": "ok"},
    {"name": "worker:codex", "ok": true, "detail": "0.9.0 / 認証: 未確認(このワーカー種別は認証確認に非対応)", "kind": "connectivity", "auth_state": "unverified"},
    {"name": "role:planner", "ok": true, "detail": "(= claude)", "kind": "connectivity", "auth_state": "n/a"},
    {"name": "config", "ok": true, "detail": "検証済み", "kind": "connectivity", "auth_state": "n/a"},
    {"name": "prompts_dir", "ok": true, "detail": "/path/to/prompts", "kind": "connectivity", "auth_state": "n/a"},
    {"name": "vault", "ok": true, "detail": "未設定(watch/scanを使わないなら問題なし)", "kind": "connectivity", "auth_state": "n/a"},
    {"name": "runs_dir", "ok": true, "detail": "/path/to/runs", "kind": "connectivity", "auth_state": "n/a"}
  ]
}
```
- 実装: `orgh/doctor.py` `doctor_payload()`。テキスト出力(`orgh doctor`)と同じ内部チェック結果
  (`_run_checks()`)を共有しており、テキスト/JSONで判定結果が食い違うことはない。
- `checks[].name` は固定リストではない(`workers.enabled` / `roles` の設定次第で
  `worker:<name>` / `role:<name>` が増減する)。`config` / `prompts_dir` / `vault` / `runs_dir`
  の4つは常に1件ずつ出る。
- `ok`(トップレベル)が`false`のとき、CLIの終了コードは非0。
- **`kind` / `auth_state`(第2期 P0-1で追加。G-07対応)**:
  - `kind` はこの行が何を検査しているかの分類。現行の全チェックは疎通確認
    (バイナリ`--version`起動可否・パス到達性・書き込み権限等)なので常に
    `"connectivity"`。`"auth"` は将来、疎通を介さない純粋な認証専用チェック行を
    追加する場合の予約値で、第2期時点では出力しない
    (認証状態は`worker:<name>`行に付与する`auth_state`で表現するため)。
  - `auth_state` は `worker:<name>` 行にのみ意味のある値が入る。それ以外
    (`role:<name>` / `config` / `prompts_dir` / `vault` / `runs_dir`)は常に `"n/a"`。
    値は4種:
    - `"ok"`: 実際にAPI呼び出し等で認証が有効であることを確認できた。
    - `"unverified"`: このワーカー種別では対話ログイン不要な認証確認手段が
      技術的に存在しない、または未実装(疎通確認自体は`ok`/`detail`で別途
      判定済み — G-07が問題視した「疎通のみで無条件にOK」を避けるため、
      未確認であることを明示する値であり、失敗ではない)。
    - `"failed"`: 認証切れ・認証エラーを検出した(疎通=`ok:true`でも起こりうる
      — バイナリは起動するがログインセッションが切れている等)。
    - `"n/a"`: このチェック行に認証という概念自体が適用されない。
  - **ルール(実装必須)**: `auth_state == "failed"` のとき、その行の `ok` は
    必ず `false`(認証切れを「OK」と嘘表示しないため — トップレベルの`ok`も
    連動して`false`になる)。`auth_state` が `"unverified"` / `"n/a"` のときは
    `ok` は疎通確認のみの結果を素直に反映してよい(`true`でも`false`でもよい)。
  - ワーカーCLIごとの具体的な認証確認手段(例: `claude`/`codex`それぞれの
    非対話的な認証状態確認コマンドの有無)はCLI拡張タスクが個別調査する
    (PRD第5章「リスクと未確定事項」に明記の未調査事項)。技術的に不可能と
    判明したワーカー種別は無条件に`auth_state: "unverified"`とすること
    (それ自体をエラーや`doctor`全体の失敗にしない)。

### 1.4 `orgh status <mission_id> --json`

```json
{
  "mission_id": "a1b2c3d4",
  "intent": "...",
  "status": "empty" | "running" | "done" | "failed" | "awaiting_approval" | "awaiting_human" | "cancelled",
  "tasks": [
    {
      "id": "t1", "title": "...", "status": "done", "attempts": 1, "worker": "claude_code", "deps": [],
      "human_request": "",
      "human_request_body": null
    }
  ],
  "cost_usd": 0.5,
  "budget_usd": 2.0,
  "approval_brief": {
    "summary": "タスク「...」ほかN件が<理由>ため停止中。承認すると残りM件のタスクが実行される(消費済み X.XX USD)。",
    "gated_tasks": [{"id": "t1", "title": "...", "workdir": "...", "reason": "..."}],
    "pending_task_count": 3
  },
  "verdicts": [
    {"ts": 1733500000.123, "passed": true, "reason": "要件どおり実装され、回帰も無かった"}
  ]
}
```
実装: `orgh/status_json.py` `status_payload()`。`status` の派生規則は §1.1 の list と完全に同一(`orgh/listing.py` `_derive_status()` と相互参照コメントで固定)。

`approval_brief` はオーナー裁定(台帳PROD-001: 承認接点は判断内容を一文で先に
提示し詳細は展開表示)の実装で追加。`tasks[]` に `awaiting_approval` が1件以上
あるときのみ存在するキーで、無ければGUI側は詳細を提示しようがないため従来
どおり即時承認する(graceful degradation)。`reason` は `orgh/guard.py`
`approval_reason()` が決定する。camelCase変換は
`approvalBrief`/`gatedTasks`/`pendingTaskCount`(types.ts `ApprovalBrief`/
`GatedTask`)。

`tasks[].human_request` / `tasks[].human_request_body`(GUIブリッジ層契約確定
タスクで追加。実装は `orgh/status_json.py`、`orgh humandone`/`awaiting_human`
状態導出は先行タスクmission 3af738a2実装)。`human_request` はタスクが
`awaiting_human` へ遷移した理由の一文で、該当なしは空文字列(常にキーは
存在する)。`human_request_body` は依頼本文の全文
(`artifacts/human_request_<task_id>.md`)で、`status` が `awaiting_human` の
ときのみ値が入り、それ以外は `null`。camelCase変換は
`humanRequest`/`humanRequestBody`(types.ts `TaskStatus`)。旧CLI互換のため
Rust側はどちらも欠落を許容する(`Option<String>`)。

トップレベルの `verdicts` (GUIブリッジ層契約確定タスクで追加。実装は
`orgh/status_json.py` `_read_verdicts()`、`runs/<id>/verdicts.jsonl` をそのまま
読んだ配列)。`orgh verdict` を一度も実行していないミッションは空配列。
camelCase変換は `verdicts`(types.ts `Verdict[]`、`ts`/`passed`/`reason` は
単語がキャメルケースと一致するためキー名自体は変換不要)。旧CLI互換のため
Rust側は欠落を許容する(`Option<Vec<Verdict>>`)。

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

`orgh resume <mission_id> [--retry-failed]`(既に実装済み、`orgh/cli.py`)も同様に
`run_mission()` を呼んでミッション完走までブロックする長時間プロセスである。
`approve` と同じく mission_id は引数として既知だが、**`approve` の `ORGH_APPROVED=<id>`
に相当する確認行を一切出力しない**(実行ロック競合時は `sys.exit()` で即座に
非0終了し、成功時は最後まで実行してサマリ行を出すのみ)。この非対称性を
Rustブリッジがどう扱うかは §3.1.1 で規定する。

### 1.6 `orgh report --days <N> --json`(第2期新設・CLI拡張タスクが実装)

```json
{
  "days": 7,
  "weekly": [
    {"week": "2026-W32", "total": 12, "first_pass": 9, "first_pass_pct": 75, "rework": 3, "rework_pct": 25}
  ],
  "missions": [
    {"mission_id": "a1b2c3d4", "intent": "要約なしの全文intent", "cost_usd": 1.23, "duration_sec": 340, "tasks_done": 4, "tasks_total": 5}
  ],
  "workers": [
    {"worker": "claude_code", "failed": 1, "total": 10, "failed_pct": 10}
  ]
}
```
- 実装方針: `orgh/report.py` の既存ロジック(`_load_missions` / `_weekly_stats` /
  `_mission_line` / `_worker_stats`)が保持する集計値をテキスト化せずJSON化する。
  テキスト版(`orgh report`)の出力を変更してはならない(既存CLI利用者への非破壊)。
  `--json` 指定時のみこのJSONを吐く新しい分岐を追加すること。
- `days` はCLI引数 `--days N` の値をそのままエコーバックする(GUI側の
  `report(days)` Tauriコマンドは常に具体的な日数を渡す設計のため、
  `--days` 省略時=全期間のケースは第2期のGUI経路からは呼ばれない)。
- 各パーセンテージ(`first_pass_pct` / `rework_pct` / `failed_pct`)は、テキスト版と
  **完全に同じ計算式**(`round(x / total * 100) if total else 0`、Python組み込み`round()`)
  で算出すること。GUI側では再計算・再丸めしない契約(P1-2受け入れ基準「GUI表示の
  数値がCLI出力と一致する」を担保するため、丸め処理の実装が2箇所に分散すると
  Python `round()`(銀行丸め)とJS側の丸めで結果がずれうる)。
- `weekly` は `week` の昇順(テキスト版の `sorted(weekly)` と同一順序)。
- `missions` はミッションディレクトリ名(`mission_id`)の昇順(`_load_missions` が
  `sorted(root.iterdir())` する順序をそのまま踏襲)。`intent` はテキスト版の30文字
  切り詰め(`_mission_line`)とは異なり、**切り詰めない全文**を返す(構造化データ
  として消費側に切り詰め要否を委ねるため)。
- `workers` は worker名の昇順(`sorted(worker_stats)`)。**worker値が`null`
  (タスクにworkerが未割当)のタスクは集計から除外すること**(テキスト版
  `_worker_stats` はNoneキーも辞書に入れてしまい `sorted()` がNoneと文字列の
  比較でTypeErrorになりうる既知の潜在バグがあるが、JSON版ではこれを踏襲せず
  除外して正しく動作させる — 新規追加分のみのバグ修正であり、テキスト版の
  出力は変更しない)。
- 対象期間にミッションが1件も無い場合はエラーではなく
  `{"days": N, "weekly": [], "missions": [], "workers": []}`。

### 1.7 `orgh playbooks --json`(第2期新設・CLI拡張タスクが実装)

```json
{
  "playbooks": [
    {
      "name": "coding",
      "path": "/abs/path/playbooks/coding.md",
      "body": "# ...\n- 資産生成(SVG/データ/CSS等)を... <!-- m:7307189e d:2026-08-05 -->\n",
      "entries": [
        {"text": "資産生成(SVG/データ/CSS等)を複数タスクへ並列分解し...", "mission_id": "7307189e", "date": "2026-08-05"},
        {"text": "Retroが自動追記する。手で書き足してもいい(むしろ推奨)。", "mission_id": null, "date": null}
      ]
    }
  ]
}
```
- 実装方針: `orgh/planner.py` `_playbooks_dir(cfg)`(= `cfg.get("playbooks_dir", "playbooks")`)
  を対象ディレクトリとし、その**直下**の `*.md` を対象に列挙する(`sorted(playbooks_dir.glob("*.md"))`
  と同じ規則。`orgh/gc.py` が使う `_backup/` `_archive/` サブディレクトリは非再帰なので
  自然に対象外になる)。
- `name` はファイル名から拡張子`.md`を除いたもの(例: `coding.md` → `"coding"`)。
- `path` は絶対パス。
- `body` はファイル全文(改行含めそのまま)。
- `entries` は各行を走査し、**行頭(前後空白除去後)が `-` で始まる行のみ**を
  エントリとして抽出する(`orgh/planner.py` `retro()` が `line.startswith("-")` の
  行にのみ `<!-- m:<mission_id> d:<date> -->` を追記するのと対になる規則。
  見出し行・空行・地の文はエントリ化しない=`body`側でのみ参照可能)。
  各エントリについて、行末の `<!-- m:<id> d:<date> -->` 形式のHTMLコメント
  (正規表現目安: `<!--\s*m:(\S+)\s+d:(\S+)\s*-->\s*$`)を検出できた場合は
  `mission_id`/`date` に抽出値を入れ、`text` からはこのコメント部分(と直前の
  空白)を除去する。コメントが無い行(手動追記・retro以外の追記)は
  `mission_id: null, date: null` とし、`text` は行頭の `"- "` を除いた全文。
- `playbooks_dir` が存在しない、または `*.md` が1件も無い場合はエラーにせず
  `{"playbooks": []}` を返す(P1-3受け入れ基準: 空状態は「まだ記録がありません」
  等のGUI表示にするため、CLI側でエラーにしない)。

**P1-3実現方式の採用決定(PRD第5章の未確定事項に対する裁定)**: PRDは
「新規CLIコマンド追加」と「Tauriブリッジが`settings.json`と同様にファイルシステムを
直接読む方式」の二択を未決としていたが、本契約では**前者(CLI側に
`orgh playbooks --json` を新設し、Rustブリッジはそれを叩くだけ)を採用する**。
理由: (1) Rustが`config.yaml`(`playbooks_dir`キー等)を独自にパースする必要が無くなり、
`configPath`を渡してCLIに問い合わせるだけで済む既存の全コマンド(`list_missions`/
`mission_status`/`doctor`等)と同じ構造に揃えられる。(2) `-` 始まり行の抽出や
`<!-- m:... d:... -->` タグの解析ロジックを、追記側(`orgh/planner.py` retro())と
同じPython側に置くことで、フォーマット変更時の二重実装・二重メンテを避けられる。

### 1.8 `orgh verdict <mission_id> --pass|--fail --reason <text>`(GUIブリッジ層契約確定タスクで追加)

JSON出力を持たない(既存の `cancel`/`humandone` と同様、成否は終了コード/
stderrで判定する)。標準出力にはドラフト件数などの人間可読メッセージのみ
(GUIは無視してよい)。成功時は終了コード0で `runs/<mission_id>/verdicts.jsonl`
へ1行追記し、`orgh/criteria.py` `distill_verdict()` が判断基準台帳の下書き
(`criteria/_drafts/*.json`)を生成する。この下書きは自動では本台帳へ反映
されず、`orgh criteria approve` を経由するオーナー操作が必要(ワンタップ
承認ガバナンス)。
- `--pass`/`--fail` は排他必須。`--reason` は必須(空文字列も可)。
- 対象ミッションが存在しない場合は非0終了・stderrにエラーメッセージ。

### 1.9 `orgh criteria list --json` / `orgh criteria approve <name>` / `orgh criteria reject <name>`(GUIブリッジ層契約確定タスクで追加)

`orgh criteria list --json`:
```json
{
  "entries": [
    {"category": "design", "id": "DESIGN-001", "strength": "norm", "text": "...", "source_mission": "4d048081", "date": "2026-08-10"}
  ],
  "drafts": [
    {"name": "a1b2c3d4-1", "path": "/abs/path/criteria/_drafts/a1b2c3d4-1.json", "category": "process", "strength": "pref", "text": "...", "raw": {"category": "process", "prefix": "PROCESS", "strength": "pref", "text": "..."}}
  ],
  "skipped": [
    {"path": "/abs/path/criteria/_drafts/broken.json", "reason": "JSONDecodeError: ..."}
  ]
}
```
- 実装: `orgh/criteria.py` `criteria_list_payload()`(`orgh/cli.py` の
  `criteria list --json` 分岐)。`orgh list --json`/`orgh report --json` 等と
  同じ作法で、パース不能な台帳行・壊れた下書きJSONは例外で落とさず
  `skipped` へ退避する(黙殺すると原因不明の「0件」になるため)。
- `entries[].strength` は `"norm" | "pref"` の2値。`source_mission`/`date` は
  台帳行にメタコメント(`<!-- src:<mission_id> d:<date> -->`)が無い手動追記
  行では `null`。
- `drafts[].name` が `criteriaApprove`/`criteriaReject` へ渡すキー
  (`orgh criteria list` で確認 → `orgh criteria approve <name>` で本台帳へ反映、
  という設計上のワンタップ承認フロー)。`raw` は下書きJSONの生データを
  そのまま透過する(想定外キーが増えてもGUIが情報を失わないため)。
- 台帳・下書きが1件も無くてもエラーにせず
  `{"entries": [], "drafts": [], "skipped": []}` を返す。

`orgh criteria approve <name>` / `orgh criteria reject <name>`: JSON出力を
持たない同期コマンド(§1.8の`verdict`と同様、成否は終了コード/stderrで判定)。
`approve` は下書きを本台帳(`criteria/<category>.md`)へ追記して下書きファイルを
削除、`reject` は `criteria/_drafts/rejected/` へ退避する(削除ではない —
棄却理由の見直し・復活を可能にするため)。対象の下書きが存在しない場合は
非0終了。

### 1.10 `orgh humandone <mission_id> <task_id> --note <text>`(GUIブリッジ層契約確定タスクで追加)

JSON出力を持たない(§1.8の`verdict`と同様)。`awaiting_human` タスクの
人間による完了報告を、通常のworker成果と同じくReviewerに掛ける
(`orgh/planner.py` `review()`)。
- レビュー合格: タスクは `done` になり、`run_mission()` を呼んでミッション
  残りタスクの実行を再開する。これは `orgh resume` と同様にミッション
  完走までブロックしうる長時間処理だが、本タスク(GUIブリッジ層契約確定)は
  §3.1/§3.1.1のような確認行方式・非同期ブリッジは要求せず、既存の
  非ブリッジ系コマンド(`list_missions`等)と同じ「Rustの同期
  `#[tauri::command]` で完了を待つ」経路に統一する契約とする(発行元の
  タスク指示による明示的な設計選択)。実行時間次第でTauriのメインスレッドが
  ブロックされうるため、フロントエンドUI実装タスクは`humanDone`呼び出し中に
  操作不能である旨をローディング表示すること。GUI側はコマンドの `await`
  完了をもって結果を判断し、以後は `mission_status` を呼び直して最新状態を
  反映すること。
- レビュー不合格: タスクは再び `awaiting_human` に戻り、新しい
  `human_request`/`human_request_body` が設定される(再試行回数の上限なし)。
- 対象タスクが存在しない、または `status` が `awaiting_human` でない場合は
  非0終了・stderrにエラーメッセージ。ミッション実行ロック競合時(他プロセスが
  実行中)も非0終了。

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
| `resume_mission` | `mission_id: string`, `retry_failed: boolean` | なし(`void`) | `orgh resume <id> [--retry-failed]` を起動(§3.1.1・**§3.1と非同期フローが異なる点に注意**) |
| `cancel_mission` | `mission_id: string` | なし(`void`) | `orgh cancel <id>` を実行し完了を待つ(短時間で終わる) |
| `doctor` | なし | `DoctorReport` | `orgh doctor --json` の出力そのもの |
| `report` | `days: number` | `ReportPayload` | `orgh report --days <days> --json` の出力そのもの(camelCase変換のみ、§1.6) |
| `playbooks` | なし | `PlaybookPayload` | `orgh playbooks --json` の出力そのもの(camelCase変換のみ、§1.7) |
| `owner_verdict` | `mission_id: string`, `passed: boolean`, `reason: string` | なし(`void`) | `orgh verdict <mission_id> --pass\|--fail --reason <reason>` を実行し完了を待つ(§1.8) |
| `criteria_list` | なし | `CriteriaPayload`(entries+drafts+skipped) | `orgh criteria list --json` の出力そのもの(camelCase変換のみ、§1.9) |
| `criteria_approve` | `name: string` | なし(`void`) | `orgh criteria approve <name>` を実行し完了を待つ(§1.9) |
| `criteria_reject` | `name: string` | なし(`void`) | `orgh criteria reject <name>` を実行し完了を待つ(§1.9) |
| `human_done` | `mission_id: string`, `task_id: string`, `note: string` | なし(`void`) | `orgh humandone <mission_id> <task_id> --note <note>` を実行し完了を待つ(§1.10。長時間ブロックしうる点に注意) |
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
- `runsDir`: **表示用キャッシュ専用フィールド。いかなるCLI呼び出しの引数にも
  使わない**(下記「P0-2: runsDirの方針」参照)。実際に効く `runs_dir` は
  `configPath` が指すconfig.yamlの `runs_dir` キーが正。

**P0-2(runsDir)の方針採用決定(PRD第5章の未確定事項に対する裁定)**: PRDは
「表示区分のみで済ませる」か「実際にCLI呼び出しへ反映させる(CLI側に
`--runs-dir` 相当の上書き引数を追加する)」かを未決としていたが、本契約では
**前者(表示区分のみ・CLI呼び出しには一切反映しない)を採用する**。理由:
既存CLI利用者への非破壊を最優先するため — 後者を選ぶと`orgh/cli.py`の
複数サブコマンドに新しい上書き引数を追加する必要があり、テキストCLIの
既存引数体系に手を入れるリスクが生じる。前者なら`desktop/src-tauri/**` /
`desktop/src/**`(フロントエンド)のみで完結し、CLI側は一切変更不要
(`types.ts` の `Settings` 型もこの契約更新時点では変更しない)。
フロントエンドUI実装タスクは、SettingsPage上で `runsDir` を `orghBin`/
`configPath`(実際にCLI呼び出しに使われる)とは異なる視覚的区分
(セクション分け・注記アイコン等)で表示し、「この値はCLI呼び出しには
反映されない表示専用キャッシュである」旨を常時表示のUI要素(ホバー
ツールチップに限定しない)で明示すること(G-06対応)。

### 2.1 各コマンドの子プロセス起動パターン

- `list_missions` / `mission_status` / `mission_events` / `doctor` / `report` / `playbooks`:
  `orgh --config <configPath> <cmd> ... --json` を起動し、完了(exit)を待ってstdoutを
  パースして返す短命プロセス。stderrは失敗時にエラーメッセージとして`Err`に含める。
  (`report` は `orgh --config <configPath> report --days <days> --json`、`playbooks` は
  `orgh --config <configPath> playbooks --json`。)
- `cancel_mission`: `orgh --config <configPath> cancel <mission_id>` を起動し完了を待つ
  (フラグファイルを置くだけなので短時間で終わる)。失敗時は非JSON出力だが、
  終了コード非0またはstderrをエラーとして扱う。
- `start_mission` / `approve_mission`: §3.1 参照(長時間プロセス・非同期)。
- `resume_mission`: §3.1.1 参照(長時間プロセス・非同期。`ORGH_RESUMED=`
  確認行の検出まで成功を返さない — §3.1のapproveと同一の仕組み)。
- `owner_verdict` / `criteria_list` / `criteria_approve` / `criteria_reject` /
  `human_done`(GUIブリッジ層契約確定タスクで追加): 確認行の待受
  (`ORGH_APPROVED=`等)を必要としない同期実行。`list_missions`等と同じ
  `Command::output()` で完了を待ちJSON/終了コードを解釈する経路
  (`cli::run_json`/`cli::run_sync`)を使う。**既存の`spawn_and_bridge`/
  `ORGH_APPROVED=`確認行契約には一切手を入れない**(この5コマンドは
  そもそも確認行を出力しないCLIサブコマンドを叩くため対象外)。
  `--reason`/`--note` の値は空白・改行・日本語・先頭ハイフンいずれを
  含んでいても1個の引数配列要素として安全に子プロセスへ渡す必要がある
  (Rustの`Command::args`はシェルを経由しないため値の中身自体で
  インジェクションは起きないが、値の先頭が`-`のときPython argparseが
  別オプションと誤認し`expected one argument`で失敗する既知の挙動が
  あるため、Rust側は`--reason=<value>`/`--note=<value>`という等号つき
  単一トークン形式で組み立てる。`desktop/src-tauri/src/commands.rs`
  `build_verdict_args`/`build_human_done_args`とそのユニットテスト参照)。

## 3. Tauriイベント契約

| イベント名 | ペイロード(TS型) | 発火元 |
|---|---|---|
| `mission-log` | `MissionLogEvent` = `{ missionId: string \| null, line: string }` | `start_mission`/`approve_mission`/`resume_mission`が起動した子プロセスのstdout/stderrを1行ずつ |
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
     (呼び出し元をブロックし続けない)。`approve_mission` はmission_idが既知だが、
     承認が受理されたかは自明でない(承認待ちなし・二重実行のflock競合等でCLIが
     拒否しうる)ため、CLIが出す確認行 **`ORGH_APPROVED=<id>`** を検出するまで
     `Ok` を返さない。確認行より前に子プロセスが終了したら、stderr末尾を含む
     `Err` を返す(承認失敗を成功として画面に見せないため)。
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

### 3.1.1 `resume_mission` の非同期フロー(2026-08-10改訂: 確認行方式へ統一)

`resume_mission` も `orgh resume <mission_id> [--retry-failed]` というミッション完走まで
ブロックする長時間子プロセスを起動する。当初は確認行なしの即時Ok方式だったが、
**resumeの失敗(実行ロック競合・対象なし等)が成功として画面に見え、再クリックで
失敗プロセスを量産する欠陥**(Codexレビューp2r1)が確認されたため、
approveと同じ確認行方式へ統一した:

1. `mission_id` は引数として既に確定しているため、探索フェーズは無い。Rustは
   `orgh --config <configPath> resume <mission_id> [--retry-failed]` を非同期にspawnする。
2. CLIは実行ロック取得・状態復元・保存が完了した直後に **`ORGH_RESUMED=<id>`** を
   出力する(`orgh/cli.py` resume分岐)。Rustはこの確認行を検出するまで成功を
   返さず、確認行より前に子プロセスが終了した場合はstderr末尾込みの `Err` を返す
   (§3.1の `ORGH_APPROVED` と同一の仕組み・同一実装 `spawn_and_bridge`)。
3. 確認行の検出時に `mission-updated { missionId: <mission_id> }` を1回emitする。
4. 以降、子プロセスのstdout/stderrを1行ずつ `mission-log { missionId: <mission_id>, line }`
   としてemitし続ける。`mission_id` は最初から確定しているため、
   `resume_mission` が発火する `mission-log` の `missionId` が `null` になることは無い
   (§3.1の探索中null期間に相当するものが存在しない)。
5. 子プロセスが終了したら、**`mission-updated { missionId: <mission_id> }` を
   最低1回emitする**(成功/失敗どちらの終了でも。§3.1の(5)と同じ規則)。

(旧版にあった「確認行なし・spawn成功のみ保証」という既知の限界の記述は、
2026-08-10の `ORGH_RESUMED` 確認行導入により解消済み。`resume_mission` の
`Promise` は再開受理まで到達したことを保証し、ロック競合等の失敗は
`Err`(stderr末尾込み)としてUIへ返る。)

### 3.2 `mission-updated` の想定発火元(まとめ)

- `start_mission` / `approve_mission` 実行中(§3.1の(3)(5))。
- `resume_mission` 実行中(§3.1.1の手順3・5)。
- 任意(裁量): ブリッジが `runs/<id>/mission.json` の変更をポーリング/監視している場合。

`cancel_mission` は同期的に完了を待つコマンドなので、UIは `cancel_mission` の
`await` が解決した後に自分で `mission_status` を呼び直す想定であり、`cancel_mission`
自体は `mission-updated` を発火する**義務を持たない**(発火してもよいが必須ではない)。

## 4. 型定義

TypeScript側の正式な型は `desktop/src/types.ts` を参照(このAPI.mdの説明と
1:1で対応させてある)。Rust側は同じ形の構造体を `#[serde(rename_all = "camelCase")]`
付きで定義すること。フィールド名・任意性(`| null` の有無)は `types.ts` を正とする。

## 5. ステータス値の日本語表示ラベル対応表(第2期 P0-6・G-13対応)

内部値(API通信・フィルタ条件・イベント判定等)は**英語のまま変更しない**。
`StatusBadge`(一覧・詳細画面双方、`MissionSummary.status` / `MissionStatus.status` /
`TaskStatus.status` のいずれにも使う共通コンポーネントを想定)が画面表示する
ラベル文字列**のみ**を以下の対応表に従って日本語化する。9種類の内部値のうち
`empty`/`running`/`done`/`failed`/`awaiting_approval`/`cancelled` はミッション単位
(`MissionListStatus`/`MissionRunStatus`)にも現れ、`pending`/`review`/`skipped` は
タスク単位(`TaskStatus.status`、`string`型)にのみ現れる。1つの対応表を両方に
共通で使うこと(ステータス値の名前空間はミッション/タスクで共通のため)。

| 内部値(英語・不変) | 表示ラベル(日本語) |
|---|---|
| `pending` | 待機中 |
| `running` | 実行中 |
| `review` | レビュー中 |
| `awaiting_approval` | 承認待ち |
| `done` | 完了 |
| `failed` | 失敗 |
| `cancelled` | キャンセル済み |
| `skipped` | スキップ |
| `empty` | タスクなし |

上記9件は本タスクの発行元が指定した既定値をそのまま採用する(PRD第5章が
「実装時にオーナー確認が望ましい」としていた未確定事項だが、本契約作成時点で
既定案からの変更理由が無いため、既定通り確定させる)。`TaskStatus.status` は
`types.ts` 上 `string` 型(将来値の追加に壊れないための設計、既存コメント参照)
のため、この対応表に無い未知の値が来た場合はフロントエンド側で内部値を
そのままフォールバック表示すること(未知値でクラッシュさせない)。
`StatusBadge`の色分け・パルス表示(進行中を示す視覚効果)は本対応表と独立した
既存ロジックであり、ラベル文言の変更によって変える必要はない(回帰無しの
受け入れ基準)。

# デスクトップGUI: 未知ステータス耐性の確認(awaiting_human対応)

2026-08-11、`awaiting_human`(人間依頼)ステータスと`orgh status --json`の
`human_requests`キーがバックエンドに追加されたことを受け、デスクトップGUIが
これらの未知の値でクラッシュしないかを確認した。**GUIにawaiting_human専用の
表示・導線を追加することは本ミッションのスコープ外**であり、ここでは「壊れ
ないこと」の確認と、壊れる箇所があった場合のみの最小フォールバックを扱う。

## 確認したファイル

- `desktop/src/components/StatusBadge.tsx`
- `desktop/src/types.ts`
- `desktop/src/pages/MissionDetailPage.tsx`
- `desktop/src/api.ts`
- `desktop/src-tauri/src/models.rs`(Rustブリッジ側のJSON deserialize契約。
  クラッシュ有無の判定に必須のため追加で確認)

## 確認した挙動と結論

### 1. `StatusBadge.tsx` — 未知ステータス文字列
- `TONES`マップに存在しないキーで参照すると `toneFor()` は
  `TONES[status] ?? { label: status, color: "var(--text-dim)", bg: "var(--surface-hover)" }`
  という**既存のフォールバックにより**、undefined参照は発生しない。
- `awaiting_human` は`TONES`に未登録のため、ラベルは生の文字列
  `"awaiting_human"`、色は中立(text-dim / surface-hover)で表示される。
  pulse指定も無いため点滅もしない。
- **結論: 壊れない。既存実装が既に安全側のフォールバックを持っていた。
  修正不要。**

### 2. `orgh/status_json.py` の `human_requests` キー / Rustブリッジ
- `desktop/src-tauri/src/models.rs` の `MissionStatus` 構造体は
  `#[serde(deny_unknown_fields)]` を付けていない(serdeの既定はunknownフィールド
  無視)。`status`フィールドも文字列版のenumではなく素の`String`。
  そのため `orgh status --json` の出力に新キー `human_requests` が増えても、
  またトップレベルの`status`値が`"awaiting_human"`という未知の文字列に
  なっても、Rust側のJSONデシリアライズはエラーにならず黙って無視/通過する。
- **結論: 壊れない。GUIブリッジは`human_requests`キーを単に無視して
  `mission_status()`を正常に返す(取りこぼすだけで例外にはならない)。**

### 3. `desktop/src/types.ts` — ステータス共用体型
- `MissionListStatus` / `MissionRunStatus` は元々リテラル共用体型で、
  `"awaiting_human"` を含んでいなかった。
- TS側は`invoke<T>()`の戻り値をランタイム検証せず型アサーションするだけ
  (`api.ts`の`invokeReal`)であるため、値が共用体に無くても**実行時クラッシュ
  は起きない**。ただし型としての正確性を欠き、将来この値で分岐するコードを
  書いた際に型エラーで守ってもらえない状態だった。
- タスク指示で明示的に許可されている「型エラーを防ぐための追加」として、
  `MissionListStatus` と `MissionRunStatus` の両方に `"awaiting_human"` を
  追加した(表示ロジックの追加は無し。型定義のみの変更)。

### 4. `MissionDetailPage.tsx` — 承認/再開ボタンの条件式
- `hasAwaitingApproval = status?.tasks.some((t) => t.status === "awaiting_approval")`
  — awaiting_humanタスクが混在しても`awaiting_approval`と完全一致でしか
  trueにならないため、awaiting_humanで誤って承認ボタンが活性化することはない。
- `canResume = status.status === "cancelled" || status.status === "failed"`
  — ミッションstatusが`"awaiting_human"`のときはどちらにも一致せず、
  再開ボタンは表示されない(意図しない再開導線は出ない)。
- キャンセルボタンの活性条件`status.status !== "running" && status.status !== "awaiting_approval"`
  は、mission.statusが`awaiting_human`の場合は非活性側(disabled)になる。
  これはGUIからのキャンセル操作を阻む挙動だが、クラッシュや誤動作ではなく
  「ボタンが押せないだけ」の安全側フォールバックであり、CLIの`orgh cancel`は
  引き続き使える。awaiting_human用の専用導線を作らないという本ミッションの
  制約から、ここは意図的に未対応のまま残す(改修候補としてHANDOFF.mdに記載)。
- **結論: 壊れない。承認・再開ボタンの誤表示は無い。**

### 5. タスク一覧テーブル・DependencyGraph
- `TaskStatus.status` は元々 `string` 型(意図的にリテラル共用体にしていない
  — コメントに「将来値が増えても壊れないよう」と明記済み)。`StatusBadge`と
  同じフォールバックで表示されるため問題なし。

## 入れたフォールバック

- **表示ロジックのフォールバック追加は無し**(既存の`StatusBadge`が既に
  安全側の実装だったため)。
- `desktop/src/types.ts` の `MissionListStatus` / `MissionRunStatus` に
  `"awaiting_human"` を追加(型エラー防止のための型定義更新のみ。表示・
  導線ロジックへの変更は無し)。

## ビルド確認

`cd desktop && npm run build`(`tsc && vite build`)を実行し、終了コード0を
確認した(2026-08-11)。node_modulesはリポジトリに含まれないため、既存の
`../desktop/node_modules`(package.json/package-lock.jsonが本worktreeと同一
であることを確認済み)を一時的に使って検証し、検証後は作業ツリーから削除
した。

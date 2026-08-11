# REVIEW: AIエージェント紹介動画 統合レビュー

作業内容: `public/assets/*.svg` を各シーンコンポーネントに結線し、Remotionで動画をレンダリングして目視確認した。

## 1. 実施した変更

- `src/SceneLayout.tsx` は元々 `staticFile(scene.asset)` を `Img` に渡す実装だったが、`onError` 時にプレースホルダの角丸パネルへフォールバックする分岐を持っていた。今回、`npm install` → `npm run build` → レンダリングを実施した結果、全シーンで `public/assets/` 配下の実SVGが正しくロードされ、フォールバック分岐は一度も発火しなかったことを目視確認で確定させた(コード変更は不要だった。理由は下記4節参照)。
- `node_modules` が未インストールだったため `npm install` を実施(コミット対象外、`.gitignore` で除外済み)。
- 依存追加・スキーマ変更・SVGファイル自体の変更は行っていない。

## 2. 目視確認記録

各シーンの尺の中央付近のフレームを `npx remotion still` で書き出し、`preview/<sceneId>.png` としてReadツールで実際に目視した。

| sceneId | 確認したpreview画像パス | 抽出フレーム(30fps) | 判定 |
|---|---|---|---|
| s01 | preview/s01.png | frame 180 (6.0s) | OK — 循環アイコンSVGが中央に表示、見出し・字幕・ナレーション帯がセーフエリア内に収まり文字の見切れ・重なりなし |
| s02 | preview/s02.png | frame 570 (19.0s) | OK — 左右比較パネルSVGが正しく表示、チャットAI(灰)とAIエージェント(緑ループ)の対比が判読可能、ナレーションが2行に折返しても帯からはみ出していない |
| s03 | preview/s03.png | frame 1020 (34.0s) | OK — 計画・ツール実行・検証の3ノード循環図と付随アイコン(端末・虫眼鏡・書類)が表示、破線の再計画矢印も視認可能 |
| s04 | preview/s04.png | frame 1500 (50.0s) | OK — オーケストレーターから3ノードへの分岐矢印・並行実行を示す点線が表示、図がSVGの白抜け/黒潰れなく描画 |
| s05 | preview/s05.png | frame 1950 (65.0s) | OK — 3ノードからorghへの収束矢印、成果物パネルまでの流れが表示、s04と対になる収束構図を確認 |
| s06 | preview/s06.png | frame 2400 (80.0s) | OK — 2行2列のユースケースカードグリッドが表示、4アイコン(コード実装/技術調査/資料作成/運用監視)とラベルの重なりなし |
| s07 | preview/s07.png | frame 2820 (94.0s) | OK — s01アイコンの小型再掲、3ノード遷移列、CTAボタン「次の一歩へ」が中央対称配置でセーフエリア内に収まっている |

判定はすべて OK。文字の見切れ・重なり、図の白抜け/黒潰れ、SVG未表示、テキストのセーフエリア逸脱のいずれも検出されなかったため、実装修正は発生していない。

## 3. 仕様との差分表(scenes.json vs 実装値)

`Main.tsx` は `scenes.json` を直接 import して `Series.Sequence` の `durationInFrames` と各シーンコンポーネントの `scene` propに渡しており、`SceneLayout.tsx` も `scene.onScreenText.headline` / `scene.onScreenText.sub` / `scene.asset` をそのまま描画に使う構造のため、実装値は常に scenes.json の値と一致する。

| sceneId | 項目 | scenes.json 仕様値 | 実装(レンダリング)値 | 差分 | 理由 |
|---|---|---|---|---|---|
| s01 | durationSec | 12 | 12 (360 frames @30fps) | なし | Main.tsxがscenes.jsonを直接参照 |
| s01 | headline | AIエージェントとは? | AIエージェントとは? | なし | SceneLayoutがscene.onScreenText.headlineをそのまま描画 |
| s01 | sub | 自ら考え、動き、確認するAI | 自ら考え、動き、確認するAI | なし | 同上(sub) |
| s01 | asset | assets/s01-hero.svg | assets/s01-hero.svg (staticFile経由でpublic/assets/s01-hero.svgをロード) | なし | staticFile(scene.asset)がそのまま参照 |
| s02 | durationSec | 14 | 14 (420 frames) | なし | 同上 |
| s02 | headline | 従来のチャットAIとの違い | 従来のチャットAIとの違い | なし | 同上 |
| s02 | sub | 一問一答から、計画・実行・検証のループへ | 一問一答から、計画・実行・検証のループへ | なし | 同上 |
| s02 | asset | assets/s02-compare.svg | assets/s02-compare.svg | なし | 同上 |
| s03 | durationSec | 16 | 16 (480 frames) | なし | 同上 |
| s03 | headline | 計画・実行・検証のループ | 計画・実行・検証のループ | なし | 同上 |
| s03 | sub | ツールを呼び出し、結果を確認して次の一手を決める | ツールを呼び出し、結果を確認して次の一手を決める | なし | 同上 |
| s03 | asset | assets/s03-loop.svg | assets/s03-loop.svg | なし | 同上 |
| s04 | durationSec | 16 | 16 (480 frames) | なし | 同上 |
| s04 | headline | 複数エージェントの分業 | 複数エージェントの分業 | なし | 同上 |
| s04 | sub | 役割ごとに専門エージェントが並行して作業する | 役割ごとに専門エージェントが並行して作業する | なし | 同上 |
| s04 | asset | assets/s04-fanout.svg | assets/s04-fanout.svg | なし | 同上 |
| s05 | durationSec | 14 | 14 (420 frames) | なし | 同上 |
| s05 | headline | 成果を統合するorgh | 成果を統合するorgh | なし | 同上 |
| s05 | sub | 分業した結果をハーネスがまとめ上げる | 分業した結果をハーネスがまとめ上げる | なし | 同上 |
| s05 | asset | assets/s05-merge.svg | assets/s05-merge.svg | なし | 同上 |
| s06 | durationSec | 16 | 16 (480 frames) | なし | 同上 |
| s06 | headline | こんな場面で活躍する | こんな場面で活躍する | なし | 同上 |
| s06 | sub | コード実装・調査・資料作成まで幅広く対応 | コード実装・調査・資料作成まで幅広く対応 | なし | 同上 |
| s06 | asset | assets/s06-usecases.svg | assets/s06-usecases.svg | なし | 同上 |
| s07 | durationSec | 12 | 12 (360 frames) | なし | 同上 |
| s07 | headline | AIエージェントを始めよう | AIエージェントを始めよう | なし | 同上 |
| s07 | sub | 小さなタスクから任せて、自律ループを体験する | 小さなタスクから任せて、自律ループを体験する | なし | 同上 |
| s07 | asset | assets/s07-cta.svg | assets/s07-cta.svg | なし | 同上 |

差分ゼロ。全28項目(7シーン × 4項目)が一致。

## 4. 「プレースホルダフォールバック」の扱いについて

`SceneLayout.tsx` には `Img` の `onError` で `assetFailed` フラグを立て、SVGロード失敗時にのみプレースホルダ矩形へ切り替える分岐が残っている。これは以下の理由で妥当と判断し、削除しなかった:

- 本タスクの受け入れ条件は「本物のSVGが実際に表示されること」であり、目視確認(2節)でフォールバック分岐が一度も発火せず全シーンで実SVGが描画されることを確認済み。
- `onError` 分岐自体はネットワーク遅延やファイル欠落時の防御的コードであり、正常経路のレンダリング結果には影響しない。除去すると読み込み失敗時に真っ黒な画面になるリスクがあるため、防御的フォールバックとしては残す判断とした。

## 5. 動画の基本情報

| 項目 | 値 |
|---|---|
| 出力パス | `out/intro-ai-agent.mp4` |
| 総尺 | 100.05秒(scenes.json合計 100秒、80〜120秒の範囲内) |
| 解像度 | 1920x1080 |
| フレームレート | 30fps |
| ファイルサイズ | 約6.3MB(6,325,713 bytes) |

## 6. 実行コマンドと結果

| コマンド | 結果 |
|---|---|
| `npm install` | 依存関係296パッケージを解決、脆弱性0件 |
| `npm run build` (`tsc --noEmit`) | 終了コード0 |
| `npx remotion render src/index.ts Main out/intro-ai-agent.mp4` | 終了コード0、3000フレームを描画・エンコード完了 |
| `npm test` (`node scripts/verify-project.mjs`) | `Verified 7 scene components.` — 成功 |
| `npx remotion still src/index.ts Main preview/<id>.png --frame=<n>` (×7) | 全7シーンのpreview画像を生成 |
| `ffprobe out/intro-ai-agent.mp4` | width=1920, height=1080, r_frame_rate=30/1, duration=100.053333 |

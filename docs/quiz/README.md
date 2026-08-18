# orgh 理解度クイズ

orghの仕様理解を深め、習熟度を測るためのクイズアプリ。ビルドもサーバも不要で、
`docs/quiz/index.html` をブラウザで開けば動く(依存ゼロの素のHTML/CSS/JS)。

```bash
xdg-open docs/quiz/index.html   # macOS は open
```

## できること

- カテゴリ(アーキテクチャ/状態遷移/ガバナンス/予算/隔離/知識/実行基盤/ソース連携/CLI/設定/Desktop)と
  難易度(基礎/応用/内部実装)で出題範囲を絞る
- **学習モード**: 1問ごとに正誤・解説・出典を表示
- **試験モード**: 最後にまとめて採点
- **苦手優先**: これまで間違えた回数の多い設問から出題
- 結果画面でカテゴリ別正答率・弱点カテゴリ・全問の見直し・間違いのみ再挑戦
- 履歴と設問ごとの間違い回数は `localStorage`(キー `orgh-quiz-v1`)に保存。
  保存できない環境ではメモリ上だけで動作する

キーボード: `1`–`9` で選択、`Enter` で回答/次へ。

## 設問バンクの育て方

設問は `questions.js` の `window.ORGH_QUIZ` がSSOT。1問はこの形:

```js
{
  id: "state-terminal",          // 一意。履歴のキーになるので変えない
  category: "state",             // categories[].id のいずれか
  difficulty: "basic",           // basic | applied | internals
  type: "single",                // single(正解1つ) | multi(正解2つ以上)
  question: "…",
  choices: ["…", "…"],
  answer: [0],                   // choices のindex
  explanation: "…",              // なぜそうなのか
  sources: ["orgh/state.py"]     // リポジトリ内の実在パス
}
```

仕様が変わったら該当設問と `sources` を直す。形式と出典の実在は
`tests/test_quiz_bank.py` が検証するので、追加・修正後は次を実行する:

```bash
.venv/bin/python -m pytest tests/test_quiz_bank.py -q
```

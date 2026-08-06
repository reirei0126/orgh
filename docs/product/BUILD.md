# BUILD.md — orgh 説明資料PDFビルド記録

## 概要

`docs/product/orgh-first-guide.html`(非エンジニア向け入門)と `docs/product/orgh-deep-dive.html`(エンジニア向け技術詳解)の2本の自己完結HTMLを、ヘッドレスChrome(`--headless --print-to-pdf`)でPDF化した。入力HTML 2本 → 出力PDF 2本の1対1変換であり、HTML側の内容・構成には一切手を加えていない。

## 生成物一覧

| ファイルパス | バイト数 | ページ数 | 生成日時 |
|---|---:|---:|---|
| `docs/product/orgh-first-guide.pdf` | 867,403 バイト | 5ページ | 2026-08-06 18:25:32 JST |
| `docs/product/orgh-deep-dive.pdf` | 9,294,145 バイト | 8ページ | 2026-08-06 18:25:39 JST |

両ファイルとも `file` コマンドで `PDF document, version 1.4` と判定され、先頭バイトは `%PDF-1.4` で有効なPDFであることを確認済み。サイズはいずれも受け入れ基準の51,200バイトを大きく上回っている。

## 再生成コマンド

指定されたコマンドをそのまま実行し、追加オプション(`--headless=new` や `--disable-gpu` 等)なしで初回から成功した。リポジトリルートをカレントディレクトリとして実行すること。

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --no-pdf-header-footer --print-to-pdf=docs/product/orgh-first-guide.pdf docs/product/orgh-first-guide.html
```

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --no-pdf-header-footer --print-to-pdf=docs/product/orgh-deep-dive.pdf docs/product/orgh-deep-dive.html
```

実行時、標準エラー出力にGPU/サンドボックス関連の警告(`task_policy_set` や `SharedImageManager::ProduceOverlay` 等)が出力されるが、いずれもmacOS上のヘッドレスChromeでよく見られる無害な警告であり、PDF生成の成否には影響しない。両コマンドとも終了コード0で `N bytes written to file ...` のメッセージを出して正常終了している。

## 実行環境

- Google Chrome: `Google Chrome 151.0.7922.75`(`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --version` の出力そのまま)
- OS: macOS 15.5(Build 24F74)

## 注意事項

- 入力HTML(`orgh-first-guide.html`, `orgh-deep-dive.html`)はいずれも外部リソース(CDN上のCSS/フォント/画像/スクリプト等)に依存しない自己完結ファイルであり、オフライン環境でもヘッドレスChromeで正しくレンダリング・PDF化できる。
- PDFはA4縦・カラー印刷を前提としており、HTML側で `-webkit-print-color-adjust: exact` 相当の指定によって背景色・強調色などが印刷時にも省略されずそのまま出力される想定である。印刷余白・ヘッダーフッターは `--no-pdf-header-footer` により付与していない。
- 本ビルドではHTMLソース・既存の `.md` ドキュメント(README.md, docs配下の既存ファイル)は一切変更していない。新規作成したのは本ファイル(`docs/product/BUILD.md`)と2本のPDFのみ。

## 追記: orgh-pitch.pdf / orgh-techbook.pdf の生成(2026-08-06)

`docs/product/orgh-pitch.html`(ピッチ資料)と `docs/product/orgh-techbook.html`(技術書)の2本を、上記と同じ手順(ヘッドレスChrome、`--headless --no-pdf-header-footer --print-to-pdf`、リポジトリルートを起点とした相対パス指定、`file://` 不要)でPDF化した。HTML側の内容・構成には一切手を加えていない。

### 生成物一覧

| ファイルパス | バイト数 | ページ数 | 生成日時 |
|---|---:|---:|---|
| `docs/product/orgh-pitch.pdf` | 9,009,828 バイト | 6ページ | 2026-08-06 20:19 JST |
| `docs/product/orgh-techbook.pdf` | 5,074,027 バイト | 8ページ | 2026-08-06 19:26 JST |

両ファイルとも `file` コマンドで `PDF document, version 1.4` と判定され、有効なPDFであることを確認済み。サイズはいずれも受け入れ基準の51,200バイトを大きく上回っている。

### 実行コマンド

指定されたコマンドをそのまま実行し、追加オプションなしで初回から成功した。リポジトリルートをカレントディレクトリとして実行すること。

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --no-pdf-header-footer --print-to-pdf=docs/product/orgh-pitch.pdf docs/product/orgh-pitch.html
```

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --no-pdf-header-footer --print-to-pdf=docs/product/orgh-techbook.pdf docs/product/orgh-techbook.html
```

実行時、標準エラー出力にIPH(In-Product Help)関連の警告やGPU/サンドボックス関連の警告(`task_policy_set` 等)が出力されるが、既存資料のビルド時と同様に無害であり、PDF生成の成否には影響しない。両コマンドとも `N bytes written to file ...` のメッセージを出して正常終了している。

- Google Chrome: `Google Chrome 151.0.7922.75`(既存ビルド時と同一バージョン)
- 本追記作業ではHTMLソース(`orgh-pitch.html`, `orgh-techbook.html`)・既存の `.md` ドキュメントは一切変更していない。新規作成したのは2本のPDF(`docs/product/orgh-pitch.pdf`, `docs/product/orgh-techbook.pdf`)のみで、本ファイルへは追記のみ行った。

## 追記: orgh-pitch.pdf のページ数検証(2026-08-06 20:19 JST)

`docs/product/orgh-pitch.html` は16:9スライド形式(`.slide` 要素1つ=1ページ、`@page{ size:1280px 720px; }`)へ全面改修済み(HTML先頭のHTMLコメント「改善ログ(v4/16:9)」参照、本検証作業以前からの既存改修)。この構成でのPDF再生成・ページ数一致を検証した。今回の検証ではページ数がスライド数と一致したため、`orgh-pitch.html` 自体への追加編集(`pdf-fix` コメントの付与を含む)は行っていない。

- スライド数(HTML側の真実源): `grep -c 'class="slide' docs/product/orgh-pitch.html` → **6**
- 生成コマンド(上記「実行コマンド」のorgh-pitch.pdf向けコマンドと同一、再掲):
  ```bash
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --no-pdf-header-footer --print-to-pdf=docs/product/orgh-pitch.pdf docs/product/orgh-pitch.html
  ```
  出力: `9009828 bytes written to file docs/product/orgh-pitch.pdf`(終了コード0)
- ページ数を3手法でクロスチェックし、いずれも **6ページ** で一致(HTMLのスライド数と完全一致):
  - `pdfinfo docs/product/orgh-pitch.pdf` → `Pages: 6`
  - `mdls -name kMDItemNumberOfPages docs/product/orgh-pitch.pdf` → `kMDItemNumberOfPages = 6`
  - Python正規表現で `/Count` を直接抽出(`re.findall(rb'/Count\s+(\d+)', data)`)→ `[b'6']`
  - 補足: `strings docs/product/orgh-pitch.pdf | grep -c '/Type */Page[^s]'` は0を返すが、これは生成されたPDF内部でページオブジェクトがオブジェクトストリーム(compressed object streams, PDF 1.5+機能相当)として格納されており `strings` では平文検出できないためで、上記3手法の一致により実ページ数6は確定している。
- ファイルサイズ: 9,009,828 バイト(受け入れ基準51,200バイトを大きく上回る)
- 判定: ページ数(6)とHTMLスライド数(6)が完全一致したため、`orgh-pitch.html` の追加修正は不要だった。

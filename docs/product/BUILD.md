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
| `docs/product/orgh-pitch.pdf` | 10,583,569 バイト | 6ページ | 2026-08-06 19:26 JST |
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

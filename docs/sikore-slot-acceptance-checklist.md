# sikore-slot リール図柄アート刷新 — 人間検収チェックリスト

> 注記: `docs/_evidence/` のgit証拠3ファイルはworkerの権限制約により人間が代行作成した(詳細は `docs/_evidence/sikore-slot-git-evidence-note.md`)。

対象: `scripts/gen-symbols.mjs` の改修による7図柄（seven/gem/cherry/star/money/bell/drum）SVG定義刷新。
実行すると `public/symbols/` に 512×512 の透過PNGが7枚生成される。
根拠: `sikore-slot/SYMBOLS.md` §1（技術要件）・§2（7図柄仕様・格の序列）。

---

## 1. 検収手順（Mac・ターミナル）

以下を `sikore-slot` リポジトリのルートで順番に実行する。
`<mission_id>` `<task_id>` は実際に払い出された値に置き換えること（プレースホルダのまま実行しない）。

```bash
# 1. リポジトリに移動し、最新を取得
cd /Users/uesugirei/projects/sikore-slot
git fetch origin

# 2. 検収対象ブランチをチェックアウト
git checkout orgh/<mission_id>/<task_id>

# 3. 依存関係を確認（未インストールの場合のみ）
npm install

# 4. 図柄生成スクリプトを実行
node scripts/gen-symbols.mjs

# 5. 生成結果を確認する（macOSプレビューで一括オープン）
open public/symbols/seven.png public/symbols/gem.png public/symbols/cherry.png \
     public/symbols/star.png public/symbols/money.png public/symbols/bell.png \
     public/symbols/drum.png
```

---

## 2. 機械チェック項目（コピペ可）

```bash
# 2-1. 作業ツリーの差分がPNG生成のみであることを確認
#   期待出力: public/symbols/ 配下の7ファイルのみが表示される（?? または M）。
#   scripts/gen-symbols.mjs 以外のソースファイルが差分に出ていないこと。
git status --short

# 2-2. 7PNGすべてが存在し、ファイルサイズが0でないこと
for f in seven gem cherry star money bell drum; do
  ls -l "public/symbols/${f}.png"
done

# 2-2'. サイズ0のファイルがあれば検出（何も出力されなければOK）
find public/symbols -maxdepth 1 -name "*.png" -size 0

# 2-3. PNGの寸法が512x512であること（sipsはmacOS標準コマンド）
for f in seven gem cherry star money bell drum; do
  sips -g pixelWidth -g pixelHeight "public/symbols/${f}.png"
done

# 2-4. 透過（アルファチャンネル）を持つことの簡易確認
for f in seven gem cherry star money bell drum; do
  sips -g hasAlpha "public/symbols/${f}.png"
done
```

判定基準:
- [ ] `git status --short` に `public/symbols/*.png` 以外の変更・新規ファイルが出ていない
- [ ] 7ファイルすべてが `ls -l` に表示され、サイズが0バイトでない
- [ ] `find ... -size 0` の出力が空である
- [ ] 7ファイルすべて `pixelWidth: 512` `pixelHeight: 512` である
- [ ] 7ファイルすべて `hasAlpha: yes` である

---

## 3. 目視チェック項目（全図柄共通）

暗いリール窓を想定し、`#12121c`（通常時）・`#2a0044`（リーチ時）相当の暗い背景に7PNGを並べて確認する。

- [ ] 主光源の方向（ハイライト・陰影の向き）が7図柄で揃っている
- [ ] アウトライン（縁取り）の太さが7図柄で揃っている
- [ ] 暗背景（#12121c）に置いたとき、7図柄すべてが背景に沈まず浮いて見える
- [ ] リーチ背景（#2a0044）に置いたときも同様に視認できる
- [ ] セーフエリア（キャンバスの約88%＝四辺約30pxの余白）を超えて図柄本体がはみ出していない
- [ ] 接地シャドウ・後光などの装飾が不自然な位置・不自然な濃さになっていない
- [ ] 7種を並べたときに「同一シリーズ」に見える質感・線の統一感がある
- [ ] WIN図柄4種（seven/gem/cherry/star）と非揃い3種（money/bell/drum）の格差が発光量・リッチさの差として見える

---

## 4. 目視チェック項目（図柄別）

### seven
- [ ] 金属質の金の「7」であり、後光または炎の意匠をまとっている
- [ ] WIN・最高位にふさわしく、7種中もっとも発光量・リッチさが高い（赤の差し色を含む）
- [ ] 既存パチンコ/パチスロ機の「7」意匠の模倣に見えない（特定機種を想起させない）

### gem
- [ ] 宝珠（如意宝珠）またはカットジュエルの意匠で、透明感・屈折のきらめきが表現されている
- [ ] 色相が青〜紫系である
- [ ] WIN・高位として、moneyやbellより発光量・リッチさが高い

### cherry
- [ ] 実2つ＋茎の古典的なチェリー構図になっている
- [ ] つややかな赤色でハイライトが表現されている
- [ ] WINとして非揃い3種より発光量・リッチさが高い

### star
- [ ] 星または光芒の意匠で、金〜白系の発光が表現されている
- [ ] シンプルな形状でも輝き（グロー・ハイライト）が重視されている
- [ ] WINとして非揃い3種より発光量・リッチさが高い

### money
- [ ] 小判または金子の束の意匠で、実在紙幣のデザイン転用がない
- [ ] 金色でコミカル寄りの表現になっている（過度にリッチすぎずWIN4種と差がある）
- [ ] 非揃い図柄として、WIN4種より発光量が控えめである

### bell
- [ ] 神社の本坪鈴または梵鐘をモチーフにした和解釈の意匠になっている
- [ ] 落ち着いた金銅色の金属質で表現されている
- [ ] 非揃い図柄として、WIN4種より発光量が控えめである

### drum
- [ ] 木魚・太鼓・リールドラムのいずれかをモチーフにし、仏道トーンの遊び枠として愛嬌がある
- [ ] アプリ起動時に3つ並ぶ「顔」として単体でも視認性・印象が成立している
- [ ] 非揃い図柄として、WIN4種より発光量が控えめである

---

## 5. 縮小時チェック（74px想定）

手順:

```bash
# macOSプレビュー等で74x74相当に縮小したサムネイルを作る例（sipsで一時ファイルを生成）
mkdir -p /tmp/sikore-symbols-74
for f in seven gem cherry star money bell drum; do
  sips -z 74 74 "public/symbols/${f}.png" --out "/tmp/sikore-symbols-74/${f}.png"
done
open /tmp/sikore-symbols-74
```

Finderのアイコン表示またはプレビューで7枚を横一列に並べ、実機のリール距離感を想定して確認する。

判定基準:
- [ ] 74px表示で7図柄それぞれのモチーフが何であるか判別できる（seven/gem/cherry/star/money/bell/drumの区別がつく）
- [ ] 74px表示でWIN4種と非揃い3種の格差（発光量の差）が視認できる
- [ ] 74px表示で図柄のシルエットが潰れて団子状の塊に見えていない
- [ ] 74px表示でアウトラインが背景と同化して輪郭が消えていない

---

## 6. 差し戻し基準

以下のいずれかに該当する場合、mainへマージせず差し戻す。

- 「2. 機械チェック項目」の判定基準を1つでも満たさない場合（ファイル欠落、サイズ0、寸法が512×512でない、アルファチャンネルなし、`gen-symbols.mjs` 以外の差分が存在する場合を含む）
- 「3. 目視チェック項目（全図柄共通）」の項目のうち、セーフエリア超過またはWIN/非揃いの発光量格差が確認できない項目が1つでも存在する場合
- 「4. 目視チェック項目（図柄別）」で、各図柄のモチーフ仕様（SYMBOLS.md §2 記載のモチーフ案・色・格）に明確に反する図柄が1つでも存在する場合
- SYMBOLS.md §4 の著作権ガードレールに抵触する場合（既存パチンコ/パチスロ機・アニメ作品の図柄意匠の模倣、実機素材のトレース・転用、実在ブランド・キャラクター・人物の描き込みのいずれかに該当する場合）
- 「5. 縮小時チェック」で74px表示時に7図柄の判別ができない図柄が1つでも存在する場合

# orgh ハンドオフ(2026-08-10 更新)

## 2026-08-10 スプリント: 判断基準台帳とペルソナ検収ゲート

- **判断基準台帳(criteria)**: `criteria_dir`(既定`criteria`)配下に台帳行
  `- ID [norm]: ... <!-- src:x d:date -->` を保持し、Reviewer・ペルソナ検収の
  文脈に日付降順で自動注入。`orgh verdict <mission_id> --pass|--fail --reason "..."`
  でオーナー裁定を`verdicts.jsonl`とledger(`mission.owner_verdict`)に記録し、
  `criteria/_drafts/<mission_id>-<n>.json` へ台帳差分の下書きを蒸留生成する
  (採番衝突は自動回避)。`orgh criteria list` で下書き+現行台帳を確認、
  `orgh criteria approve <name>` で本台帳へ反映、`orgh criteria reject <name>` で
  `_drafts/rejected/` へ退避(同名衝突は`.2`/`.3`連番)。本台帳への反映経路は
  approveのみ
- **ペルソナ検収ゲート**: `personas.enabled: [consumer, designer]` を設定すると、
  依存されない最終タスク(`apply: final_task`)にReviewer合格後、実ブラウザ/
  スクショ証拠つきの裁定が追加される。証拠なしの合格主張は`ValueError`で
  ロールリトライ、ペルソナ名のtypo(プロンプト欠如)はリトライせず即failed。
  不合格は`[<persona>ペルソナ検収] `プレフィックスで既存の差し戻しループへ
  合流。ledgerイベントは`task.persona_review`/`task.persona_exhausted`。
  ロール設定は`roles.persona_consumer`/`persona_designer`/`criteria_distill`
  (未指定時デフォルト注入、`bin`はreviewer継承)
- **運用手順**: ミッション完走→`orgh verdict`で裁定→`orgh criteria list`で
  下書き確認→`orgh criteria approve`/`reject`。ペルソナ検収を使うには
  `config.yaml`の`personas.enabled`に`consumer`/`designer`を追加するのみ
  (空配列なら従来動作のまま無効)
- **既知の会計上の割り切り**: `task_budget_usd`はworker実行コストのみを
  キャップし、ロール(persona_*/criteria_distill含む)のコストはミッション
  全体の`budget_usd`でのみ制約される。ペルソナ検収コストがタスク単位の
  予算上限に反映されない点は改修候補
- テスト: 195→222件(全緑)
- 戦略設計書: [docs/strategy/2026-08-10-value-strategy-design.md](docs/strategy/2026-08-10-value-strategy-design.md) /
  実装計画: [docs/plans/2026-08-10-criteria-personas-plan.md](docs/plans/2026-08-10-criteria-personas-plan.md)
- **改修候補(申し送り)**:
  - orgh report の first-pass/rework 指標が task.persona_review を見ない
    (ペルソナ差し戻しが初回合格として計上される)→ 柱1の成立条件検証の前に
    _weekly_stats へ折り込み要
  - task.persona_review イベントに evidence を記録していない
    (ゲートの監査可能性のため store.log に evidence を追加)
  - personas無効化後もmission.jsonのpersonasが残りresumeでゲートが走る
    (ミッションレベル一貫性としては妥当、仕様として明記)
  - 失敗ロール呼び出しコストの未計上とペルソナ再実行のコスト増幅
    (task_budget_usdはworker専用キャップ)

---

## 2026-08-07〜08-10 スプリント(前スプリント)

- **ミッション3本完走→検収→mainマージ済み**: 8e096d63(デスクトップGUI第1期+コア堅牢化、23.6USD)/ a385f876(機能精査監査、12.0USD)/ 02a434ad(GUI第2期ギャップ分析+PRD、7.9USD)
- **Codexレビュー→修正ループ**: GUI 10ラウンド50指摘+監査7ラウンド29指摘、全件検証・修正。orghコアの重大修正多数(approve二重実行のflockロック、ガード先行迂回、ORGH_APPROVED確認行契約、statusの実行中偽装解消、キャンセル系レース群、retro決着ゲート)。pytest 190(+63)
- **監査の決着**: 89機能でKEEP 58/WATCH 29/CANDIDATE 2→オーナー裁定で**削除0件**(ShellAdapterは「モデル非依存方針」で維持、cleanupは「マージ/退避確認後のみ」の条件つき運用化を承認)。台帳=docs/audit/pruning-ledger.md
- **GUI第2期の入力が揃った**: docs/gui-phase2/(ギャップ28件・PRD-PHASE2.md)。P0は「嘘をつくUI」2件(doctorの認証未確認OK表示/runsDirダミーフィールド)。実装ミッションはこのPRDから着火可能
- **watchデーモンはマージ後コードで再起動済み**(2026-08-10)。起動ログ: runs/watch-console.log
- **新ハーネス教訓(未修正)**: Plannerがworkdirをリポ直下に向けたタスクはworktree自動コミットから漏れる(02a434adのt1成果は未追跡置き去り→手動救出、t2はmainへ直接コミットe14a3bc)。②の受け渡し規約とworkdir指定の整合が改修候補
- cleanup運用化の条件「マージ確認の安全ガード」も改修候補(worktree.py: 現状--force+branch -D無条件)

---

# (旧)orgh ハンドオフ(2026-08-05 更新)

実運用フェーズ第2週の引き継ぎ。次セッションはここから読む。
前版(タスクA〜D体制)は完了済み。git logの「実運用で発見」コミット群が変更の実体。

## このスプリント(08-03〜08-05)でやったこと

### ハーネス改修(全て実運用データ起点・テスト127件グリーン)

- **projects_map**(3b5dd0d): ノートにリポパスが無いとPlannerがworkdir "."を出し
  orgh自身で実行される欠陥(7307189e t1が誤リポ走査で3.13 USD浪費)への対処。
  vault側の対応表(`vault/orgh/projects-map.md`)をPlanner文脈に注入
- **codexの自己完結リトライ**(5f3d8bb): resume不可workerが差し戻し時に文脈を失い
  「進めてよいですか?」と質問して死ぬ問題。adapterがsupports_resumeを宣言
- **reviewer max_turns 30**(4f7707a): ビルド再実行を伴うレビューが15で上限死
- **resume完走時のretro実行**(7076ae7): resumeで完走したミッションの教訓が
  playbookに残らないギャップ。RETRO_DONEマーカーで二重追記防止
- **①インフラエラーのattempt非消費リトライ**(664f294): ネットワーク断で
  3attempt≒6.4USD浪費した事例。実測署名のみ検出、上限3回・待機60s
- **④レビューのみリトライ**(53fe4e0): reviewer死でworker成果ごとfailedになる問題
- **②worktree成果物受け渡し**(4aed415): 合格時にタスクブランチへ自動コミット
  (`orgh(<mission>/<task>)`)+依存タスクは依存元ブランチをマージして開始。
  最終タスクのブランチに全成果が積まれ、検収・マージが1ブランチで完結する
- **③REPLANのacceptance制約**(f18d870): 開始前から存在する状態で必ず落ちる
  条件の禁止(t3が未追跡ファイル起因のgitチェックで永久失敗した事例)

### ミッション7307189e(sikore-slot筐体UI刷新)の顛末

全6タスク完走(総額28.68 USD)→ **機械検証は全合格なのに目視検収でUI崩壊が発覚**
(レバー不可視・リール真っ黒)。ユーザー指定のQAワークフローを実施:
全38ユーザーストーリーの棚卸し→カノニカル追跡表→実ブラウザR1テスト→修正23件→R2再テスト。
ドラフト承認済み。成果は sikore-slot の `orgh/7307189e/t5` ブランチ、コミット7dcdb92。
追跡表: `sikore-slot/.orgh-worktrees/7307189e-t5/docs/qa/feature-tracker.csv`。
**mainマージ・デプロイは未実施(ユーザー判断待ち)**。

### 組織学習(playbook)の現在地

- retro是正は機能: 予算トリビアが消え、構造的教訓のみが蒸留されている
  (planning.md 2件、coding.md 2件=共有インターフェース先行定義+UI目視必須)
- D(増幅の数字判定)は初回実測済みだが、N=10・同一週・交絡多数で時期尚早。
  定性的証拠は3つ(retro品質反転・REPLANの前提自己訂正・失敗の資産化6コミット)

## 後続TODO(優先順)

1. **watchデーモンの再起動確認**: configは起動時読込のため、projects_map追加より
   前に起動したwatchには反映されていない。`ps aux | grep "orgh.*watch"` で起動時刻を
   確認し、古ければCtrl-C→ `cd ops && ../.venv/bin/orgh --config ../config.yaml watch`
2. **クリーンな新ミッション2〜3本 → `orgh report` で増幅の数字判定**(D本番)。
   ②の自動コミット受け渡しの実地検証を兼ねる(マルチタスクミッション推奨)
3. **sikore-slotのマージ/デプロイ判断**(ユーザー): `orgh/7307189e/t5` → main。
   残課題はfeature-tracker.csvの「将来課題」参照(iOS実機の音・振動、履歴無上限等)
4. d0d795d4(別軸ノート「スロット筐体のUIが全然現実感ない。」)はcancel済み。
   再開したいときはresumeではなく**ノートを編集して再着火**(watchは内容ハッシュ管理。
   新Plannerがprojects_map込みで正しく計画し直す)
5. サブミッション再帰はDの数字実測後(合意順は不変)

## 後回しでよい改善候補(旧版から継続+新規)

- 観測性: 実行中タスクがmission.jsonでpending表示のまま(真実はledger側)
- REPLAN経緯が結果ノートに出ない(差し戻し理由に併記すべき)
- watchのCtrl-Cが実行中workerの完了を待つ(SIGINT→procreg.terminateにすべき)
- doctorに実プロンプト1発の疎通チェック
- usePerfTierのiPhone一律lite判定(sikore-slot側課題)
- worktree掃除: 検収済みミッションは `orgh cleanup <id>`

## 運用上の注意

- **並行セッション**: org-harnessを同時に触る別セッションが実在し、未コミット作業が
  消えた実例あり(履歴のリベースも発生)。作業は細かく即コミット。開始時にgit logで
  他セッションの痕跡を確認。別セッションは公開準備(英語サマリ・MIT、a11a60f)を進行中
- git identityのホスト名自動検出が壊れることがある(リポローカルに設定済み)。
  orghの自動コミットは明示identity(orgh <orgh@local>)を使う
- watch起動はopsディレクトリから(リポ直下だとworkdir "."が自己改変ガードに触れる)
- 課金: claude -p はサブスク認証のため実費なし。月次クレジット制が再開されたら
  budget_usd を実費上限として復活させること

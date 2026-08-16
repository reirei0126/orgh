# orgh 全体解説 — 何を解決し、どう作られているか(2026-08-16時点)

> 対象読者: オーナー自身。①事業オーナー ②プロダクトオーナー ③システム開発者 ④ヘビーユーザー の
> 4つの視点で、現状のorghを一枚に固定する。数字は全て実測(ledger由来)。
> 一次情報: `docs/strategy/direction-2026-08.md`(方向性) / `harness-landscape-2026-08.md`(競争環境) /
> `criteria/`(規範台帳) / `README.md`(操作)。

**一言定義: orgh = 受け入れ条件を満たすまで、人間・AI・外部実行系による仕事を検収駆動で完遂させる制御層。**

---

## 1. 事業オーナーの視点 — なぜ存在するか

### 解決する問題

AIエージェントは強力だが、**道具である限り「使っている時間」しか働かない**。個人(one-person org)の
実行力は本人の可処分時間で頭打ちになる。かつ、AIに仕事を丸投げすると2つの新しい問題が生まれる:

1. **品質の問題**: AIは「できました」と言うが、受け入れ条件を満たしている保証がない
2. **信頼の問題**: 何にいくら使い、何が起き、なぜその判断をしたのか追跡できない

orghの価値仮説: **人間の関与を「書く・承認する・検収する」の3接点に圧縮し、
それ以外(計画・実行・品質担保・学習)を検収駆動で自走させれば、個人が組織の実行力を持てる。**

### 競争環境での立ち位置(反証調査済み・誇張なし)

各構成要素には商用の直撃品が存在する(CodeRabbit Learnings=学習ルール、HumanLayer=人間承認、
Qodo/Kiro/Spec Kit=AC駆動検収、OpenClaw=個人常時稼働)。**個別要素の完成度では負けている**。
正確に主張できる差別化は3つだけ:

- **組み合わせ**: 検収ゲート × 承認制で代謝する規範台帳 × 成果物を出す人間ワーカー、を1システムで
- **代謝**: 蓄積したルールの統合・矛盾解消・棚上げ(他製品は蓄積のみで腐敗対策が見えない)
- **越境性**: コード以外(事業文書・動画・ピッチ・出品準備・意思決定ケース保守)まで同じ検収に載る

戦略原則(ARCH-003/004): 実行の配管は土台(Claude Code等)にいずれ食われる。orghは
**制御意味論(いつ再開できるか・重複をどう防ぐか・承認待ちをどう永続化するか)**だけを所有し、
実行メカニズムは検証済みの代替が現れ次第委譲する。「作るより消すを正とする」。

### 実測(2026-08-16時点)

| 指標 | 値 |
|---|---|
| 累計ミッション | 39本(runs/保持は30本=gc代謝後。全タスクdone系が主、failed 5本) |
| 累計コスト | 約677 USD(サブスク枠。1タスク実測 0.3〜0.7 USD、大型は数USD) |
| 初回attempt合格率 | W32: 84% / W33: 80%(65/81) |
| verdict(オーナー裁定)取得率 | 60%(15/25)→ 目標90%(Phase 2完了条件) |
| 検収の逃し(escape) | 報告済み0件(計器は今週稼働開始) |
| テスト | 519件(全緑) |
| 規範台帳(criteria) | 33件(norm/pref、オーナー承認制) |
| 教訓(playbooks) | 7ファイル(retro自動追記+gc代謝) |

**この方針が誤りだと分かる条件**(反証条件)も明文化してある: 6か月escapeゼロなら検収層は過剰、
Phase 1完了後も介入頻度が下がらなければ価値仮説が偽、等(direction §8)。

---

## 2. プロダクトオーナーの視点 — 何がどう動くか

### コアループ(製品の本体)

```
 Obsidianノート(#go)
      │ watch が検知(数秒)
      ▼
 Planner ── タスクDAG+構造化AC(id/検証方式/期待証拠)を計画
      │ 永続キュー(runs/_queue/)へ投入
      ▼
 Workers ── 並列実行(git worktree分離・グローバル並行数制御)
      │ 成果物+セッション文脈
      ▼
 検収ゲート ── Reviewer+ペルソナ(消費者/デザイナー)の直列裁定
      │  ├─ 合格 → タスクブランチへコミット → done
      │  ├─ 差し戻し → 同一workerセッションへ文脈ごと戻す(最大attempts回)
      │  ├─ REPLAN: → Plannerが再設計(1回まで)
      │  ├─ HUMAN: → 人間依頼(awaiting_human)へ転換
      │  └─ ESCALATE(設計済み) → 決定自体の見直しを人間へ
      ▼
 Retro ── 教訓をplaybooksへ / verdict裁定はcriteria台帳の下書きへ
      └── 次のミッションのPlanner/Reviewerが賢くなる(学習ループ)
```

### 人間の3接点(+通知)

| 接点 | 仕組み | 状態 |
|---|---|---|
| **書く** | Obsidianノート1枚(#goで着火)。書式は自由だが「必読・制約・Done when」構成が効く | 稼働 |
| **承認する** | 自己改変ガード(orgh自身を触るミッションは人間承認まで停止・**configで無効化不可**) | 稼働 |
| **検収する** | `orgh verdict --pass/--fail --category` 。failはescapeとして記録され検収器の成績になる | 稼働 |
| (依頼される) | AIに恒常的に不可能な作業は `awaiting_human` で人間がワーカーになる。完了報告(`humandone`)も同じReviewer検収を通る | 稼働 |
| (通知) | 承認待ち・人間依頼・完了がSlackへ(webhook)。未裁定ミッションは永続一覧で再発見可能 | 稼働(2026-08-16〜) |

### 学習系(orghの差別化の本丸)

- **playbooks/**(作業のやり方): Retroが自動追記 → gcが定期的に**代謝**(統合・矛盾は新しい方・
  使わないものは棚上げ)。※自動注入は「統治線の二重化」として廃止予定(direction §3.3)
- **criteria/**(判断の規範): verdict裁定から自動蒸留 → **下書き止まり** → オーナーがワンタップ承認して
  初めて規範になる。Reviewer/ペルソナのプロンプトに注入され、**検収官が引用したIDが記録される**
  (どの規範が実際に効いているかの統計)。改訂はsupersede(置き換え履歴つき)

### ロードマップの現在地

- **Phase 0〜2: 完了**(2026-08-15〜16)。制御層の正当性(状態の真実性・通知・能力宣言)と
  測定の計器(構造化AC・規範版固定・escape記録・引用統計)
- **Phase 3: 検証済みで改訂**。L1 exporter凍結(手動摩擦が小さい)、非git成果物の受け渡し契約と
  L3書き戻しを優先(実ケース検証でgit境界問題を実測したため)
- **凍結中**: 装飾GUI・公開プラグイン・クラウドworker・モデルルーティング(全て再開条件つき)
- **着火条件待ち**: A9実物観察工程(目視品質escapeが3件で着火)

---

## 3. システム開発者の視点 — 作り

### リポジトリ構成

```
org-harness/
├── orgh/                     # コア(Python・約5,900行・外部依存ほぼなし)
│   ├── watcher.py            # 検知・計画・キュー投入(実行はしない)
│   ├── executor.py           # キュー消化デーモン(daemonスレッド・gcはアイドル時)
│   ├── queue.py              # 永続有界キュー(runs/_queue/、flock claim)
│   ├── slots.py              # グローバル並行数セマフォ(flock、プロセス死で自動解放)
│   ├── lease.py              # 生存lease(heartbeat 30s/失効120s→unknown)
│   ├── orchestrator/         # 執行パッケージ(R-3で653行の神モジュールを分割)
│   │   ├── scheduler.py      #   DAG解決・並列dispatch・ミッションライフサイクル
│   │   ├── task_executor.py  #   attemptループ・worker起動・成果コミット
│   │   ├── review_pipeline.py#   Reviewer+ペルソナ直列裁定・ロールリトライ
│   │   ├── cancellation.py   #   CANCELフラグ(唯一の停止信号)
│   │   ├── budget_policy.py  #   予算プール・超過停止
│   │   └── transitions.py    #   状態遷移の単一経路
│   ├── planner.py            # Planner/Reviewer/Retro/ペルソナのロール呼び出し(JSON修復つき)
│   ├── notify.py             # 人間接点イベント(冪等event_id・Slack互換text・best-effort)
│   ├── criteria.py           # 判断基準台帳(下書き→承認・supersede・引用統計)
│   ├── state.py              # Mission/Task/Budget/RunStore・config検証・TERMINAL正準
│   ├── adapters/             # worker抽象(claude_code/codex/shell)・秘密env strip・capability allowlist
│   └── sources/              # 入力抽象(Obsidian実装: 着火判定・書き戻し・結果ノート)
├── desktop/                  # Tauri GUI(検収裁定・人間依頼・基準台帳・一覧)
├── prompts/ playbooks/ criteria/  # ロール指示・教訓・規範(全てMarkdown)
├── runs/                     # 全ミッションの永続記録(下記)
└── tests/                    # 519件(mockバイナリでLLM代役・実subprocessのkill試験含む)
```

### 実行モデル(プロセスと責務)

```
orgh watch(常駐・PID 1本)
 ├─ watcherスレッド: vault走査(5秒) → 着火判定 → Planner(LLM) → mission.json保存 → キュー投入
 └─ executorスレッド: キューclaim(flock) → run_mission
      └─ run_mission: mission lock(flock) → prompts/criteriaスナップショット
          → schedulerがDAGを解き ThreadPool で task_executor を並列dispatch
          → 各taskはattemptループ(worker subprocess → 検収 → 差し戻し/確定)
          → lease heartbeat(30秒)を書き続ける
別プロセス: orgh run/approve/resume/humandone(CLI)・GUI — 全て同じmission lockで排他
```

- **キューが境界**: watch再起動でも実行は失われない(claim中エントリはflock解放で自動復帰、
  `store.load()` が実行中系→pendingへ巻き戻し。ただし**lease失効時のみ**)
- **並行制御は3層**: mission lock(同一ミッションの二重実行防止) / loop.parallel(ミッション内) /
  global slots(全プロセス横断のworker総枠。config未設定なら無効)

### タスク状態機械

```
pending → queued → running → review → done
                  ↑    │        │ ├→ (差し戻し) → running(同一セッション再開)
                  │    │        │ ├→ REPLAN → pending相当(再設計後)
                  │    │        │ └→ HUMAN → awaiting_human ←→ humandone(Reviewer検収)
                  │    └ (権限起因失敗) → awaiting_human(capability.blocked・機械的)
                  │
   awaiting_approval(自己改変ガード) / awaiting_external_approval(A7設計済み・未実装)
   terminal: done / failed / cancelled / skipped
   表示専用: unknown(実行中系なのにlease失効=生死不明。pending/failedに丸めない)
```

### 監査と再現性(runs/<mission_id>/)

| ファイル | 役割 |
|---|---|
| `mission.json` | 状態の永続(タスク・コスト・予算) |
| `ledger.jsonl` | **全イベントの追記ログ**(task.start/review/escape/notify/承認/コスト…監査の正本) |
| `artifacts/` | worker出力全文・人間依頼書・context digest |
| `prompts/` `criteria/` | 実行開始時点のスナップショット(版ずれ防止・再現性) |
| `.lease` `.run.lock` `CANCEL` `APPROVED` | 生存証明・排他・停止信号・承認 |

### 安全機構(多層)

1. **自己改変ガード**: orgh自身を指すworkdirは人間承認まで停止。config・watcher経由でも回避不可
2. **検収役の隔離**: Reviewer等は `--setting-sources user` でworker生成物(CLAUDE.md等)を読まない(買収防止)
3. **秘密strip**: worker環境変数から秘密パターンを除去(認証に必要な既定keepあり)
4. **capability allowlist**: 固定argvの事前承認+権限起因失敗の機械的human転換。
   **セキュリティ境界ではない**とコード・configに明記(UX改善)
5. **予算**: ミッション/タスク上限(現在はオーナー裁定で無制限)・cancel後の課金停止
6. **既知の弱点(明記)**: sandbox/egress制御なし・worktreeは権限境界ではない・単一マシン・
   git管理外の成果物受け渡し未解決(Phase 3a'で対処予定)

### テスト戦略

LLMはmockバイナリ(`tests/mocks/claude`)が代役(環境変数で差し戻し・REPLAN・インフラ断等を再現)。
flock・kill -9・二重実行は**実subprocess**で検証。検収系の規範(worktree検収・マージ後再実行・
再起動=有効化)は criteria 台帳にもなっており、人間側の検収手順と機械の検収が同じ規範を共有する。

---

## 4. ヘビーユーザーの視点 — 日常の作法

### ミッションノートの書き方(効くパターン)

実績あるノートは全てこの構成(A5〜M4・Stage 3で実証):

```markdown
# タイトル(何をどこまで)
対象パスと一言のゴール
## 背景(実害)     ← なぜやるかを実例で。Plannerの判断材料になる
## 必読           ← 仕様書・設計原則へのポインタ(ノートに内容を書き写さない)
## 設計指針       ← 「この方式で」まで指定する(方式自由にすると探索で溶ける)
## 制約(厳守)     ← 直列/並列、触ってはいけないファイル、互換性要件
## 受け入れ条件(Done when) ← 機械的に判定できる形。バリデータexit 0が最強
## 検収(人間・後工程)     ← 人間が最後に何を確認するか
#go
```

コツ: **エラー列挙よりバリデータ**(人間の列挙は間違える — 実測済み)。**タスク分割の制約を書く**
(同一ファイル群なら「直列で」)。**worker指定**が必要なら明示(worker: codex等)。

### コマンド早見(日常運用で使う順)

```bash
orgh watch                     # 常駐(検知+実行)。再起動はミッション0件の窓で
orgh list / orgh status <id>   # 状態(lease連動。unknownは生死不明=要確認)
orgh approve <id>              # 自己改変ガードの解除(承認ブリーフが先に出る)
orgh verdict <id> --pass|--fail --category visual|factual|premise|other --reason "…"
                               # オーナー裁定。failはescape記録=検収器の成績になる
orgh humandone <id> <task> --note "…"  # 人間依頼の完了報告(Reviewer検収を通る)
orgh resume <id> [--retry-failed]      # 再開(lease失効時のみ巻き戻し)
orgh criteria list|approve|reject|supersede  # 規範台帳の運用
orgh report                    # 合格率・verdict取得率・escape・コスト
orgh doctor                    # 疎通・設定・unknown復旧の診断
```

### 失敗時の回収パターン(実証済み)

| 状況 | 対処 |
|---|---|
| attempts枯渇だが修正が特定済み | タスクpromptに指摘を追記 → status=pending・attempts=0 → キュー再投入(`task.owner_replan` をledgerへ) |
| 計画の前提が壊れている | prompt/acceptanceを修正して同上(オーナーによるREPLAN相当) |
| unknown(生死不明) | 自動再実行しない。成果物ブランチ・ledger末尾・プロセス有無を突合してからresume |
| awaiting_humanが誤発 | 対象コマンドをcapability_allowlistへ追加(固定argvのみ) |
| ミッション実行をセッションから切り離したい | 承認をlock内で行い、実行はキュー投入でexecutorへ委譲 |

### してはいけないこと

- **criteria/*.md をエントリの手編集で改訂する**(改訂は `orgh criteria supersede` で履歴を残す。注入がエントリ行のみになったため見出し・注釈は書けるが、エントリ行と紛らわしい書式は避ける)
- 実行中ミッションがある窓でのwatch再起動(graceful drainは無い。ミッション0件を確認してから)
- `pending`/`failed` への手動丸め(unknownには理由がある)
- 検収を経ない成果物の直接編集(PROD-003: やむを得ない場合は編集記録を成果物内に残す)

---

## 5. この文書の更新

本書は2026-08-16時点のスナップショット。以後の変化は `HANDOFF.md`(セッション単位)と
`docs/strategy/direction-2026-08.md`(方向性)が先行し、本書は節目で改版する。

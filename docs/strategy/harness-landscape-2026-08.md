# orgh 競争環境分析 — 世の中のハーネスの中での強み・弱み(2026-08-14)

> 目的: orghが世の中のエージェントハーネスの中でどこが強く、どこが弱いかを観点別に判定し、
> 強み伸長・弱み充填の優先順位を出す。判定は本リポの実装・実運用の実態(2026-08時点、
> ミッション30本超・執行アーキ改修完了)と、2026年8月時点の外部調査に基づく。
> 作成: オーナー依頼によるセッション分析(出典は末尾)。

## 0. 比較対象の地図

| カテゴリ | 代表 | 性格 |
|---|---|---|
| A. コーディングハーネス | Claude Code(業界1位・per-subagentモデル制御)、Codex、**Devin**(ticket→PR全自動・Knowledge/Playbooks・企業向け)、OpenHands(OSS・コンテナ隔離) | タスク遂行の完成度で競う |
| B. オーケストレーションFW | LangGraph(状態グラフ・HITLプリミティブ)、CrewAI(役割ベース)、AutoGen/AG2 | 開発者が組む部品。**品質ゲートや承認は標準装備しない** |
| C. パーソナル常時稼働 | **OpenClaw**(347k stars・ローカル・Markdown記憶・メッセージアプリUX・heartbeat) | orghのニッチの最近傍。ただしアシスタント型 |
| D. 研究フロンティア | Reflexion、Accumulated Behavioral Rules(arXiv:2607.13091)、Verify-Gated Completion(arXiv:2605.17998) | orghが実装済みの領域に研究が追いついてきている |

## 1. 観点マップと判定

判定: ◎=独自的に先行 / ○=強い(並みより上) / △=並 / ✕=劣後

| # | 観点 | 判定 | orghの現在地 | 世間の最先端との差分 |
|---|---|---|---|---|
| 1 | 起点UX(仕事がどこから始まるか) | ○ | Obsidianノート+#goで着火。思考の場が起票の場 | Devin=ticket/Slack、OpenClaw=チャット。個人の思考置き場から直接、は独自だが並走者あり |
| 2 | 計画・分解 | △ | Planner→タスクDAG、REPLAN(1回)、worker:human計画 | LangGraphは人手グラフ、Devinは自動計画。決定的な差なし |
| 3 | 実行の隔離・並列 | △ | git worktree分離+missionロック+グローバルセマフォ(R-2)+永続キュー(R-1) | 並行制御の作り込みは強いが、**隔離の強度**はOpenHands(コンテナ)/Devin(クラウドVM)に負ける。worktreeは権限境界ではない(脅威モデル明記済み) |
| 4 | **検収ゲート** | ◎ | 受け入れ条件ドリブン。Reviewer+ペルソナ直列裁定、不合格は**文脈ごと同一セッションへ差し戻し**、REPLAN/HUMAN分岐、証拠チャネル原則 | FW勢はcriticパターン止まり(枠組み任せ)。研究では Verify-Gated Completion がまさにこの方向=**orghは先行実装済み**。商用でここまでの直列検収を標準にしたものは見当たらない |
| 5 | **組織学習** | ◎ | retro→playbook追記+**代謝**(gcで統合・矛盾解消・棚上げ)、**criteria台帳**(オーナー裁定を蒸留→承認制で規範化、DESIGN/QA/PROD/SAFETY 20件超) | 最近傍はDevin Knowledge(自動想起はあるが人手キュレーション中心・裁定蒸留はない)。arXiv:2607.13091(レビュー指摘→行動ルール蓄積)が同方向=研究が追いつきつつある。**「裁定→規範」の自動蒸留+人間承認**の二段構えは独自 |
| 6 | 安全・ガバナンス | ○ | 自己改変ガード(**configで無効化不可**)、検収役の隔離(--setting-sources)、秘密env strip、予算プール、キャンセルの単一信号設計 | 関所の「不可侵性」は珍しい。ただしsandbox/egress制御は無い(✕成分。OpenHands/Devinに劣後) |
| 7 | 観測・監査 | ○ | 全イベントledger、コスト実測(タスク/ミッション/週次report)、prompts snapshot(再現性) | 個人用途では十分以上。企業級(SSO・SCIM・監査エクスポート=Devin)は無いが不要域 |
| 8 | **人間接点** | ◎寄り○ | **awaiting_human/humandone**(人間を正式なワーカーとしてDAGに組み込み、成果は同じReviewer検収を通す。PROD-003が人間にも効いた実績)、承認ブリーフ(PROD-001)、GUI | 「人間へのタスク依頼が状態機械として一級市民」は他に見ない。**ただし通知が無く依頼に気づけない**(✕成分) |
| 9 | スケール・運用 | ✕ | 単一マシン・単一オーナー。並列2ミッション+worker枠4で運用中 | Devin/OpenHandsはクラウドでN並列。チーム利用・リモート実行なし |
| 10 | エコシステム・接続性 | ✕ | worker adapter 3種(claude/codex/shell)。**MCP未対応**、通知連携なし、コミュニティなし | 2026年はMCPがツール接続の標準。ここに乗っていないのは孤立リスク |
| 11 | ドメインの幅 | ○ | コード外を実運用済み(動画・ピッチ資料・事業文書・BOOTH出品準備・ゲームUI)。executor Skill群+職種別playbook | コーディング特化勢より広い。「個人の全仕事の組織」という設計思想が実績で裏付く |
| 12 | 品質バーの天井 | △(世界共通未解決) | TC全PASSでもオーナーの求める絵力に届かない事例(quality-bar-vs-criteria)。ただし**基準側を改訂する機構**(gestalt差し戻しに基準特定義務)まで持つ | どのハーネスも「観測可能な基準」の外にある品質(センス・絵力)は未解決。orghは台帳と実物観察プロセス(DESIGN-005)で半歩先 |

## 2. 総合判定

**orghの核心的独自性は「検収ゲート(4) × 組織学習(5) × 人間込みDAG(8)」の三点セット。**
各要素の萌芽は研究・商用に存在するが、3つを噛み合わせて(検収の裁定が台帳になり、台帳が次の検収を強くし、通らない仕事は人間へ正式に回る)個人規模で実運用しているものは、調査範囲では見当たらない。研究フロンティア(D)がこの方向へ向かっていることは、方角の正しさの証拠と読む。

**構造的な弱みは「境界」と「接続」に集中している。**
①実行境界(sandbox/egressなし)②外界接続(MCP・通知なし)③スケール境界(単一マシン)。
いずれも「個人が自分のマシンで自分の仕事を回す」前提では顕在化しにくいが、公開・拡大の瞬間に全部が壁になる。

**存在論的リスク: 土台ハーネスとの機能重複。**
Claude Code本体がsubagent・workflow・skills・スケジューラを取り込み続けており、「タスクを並列で回す」だけならorghの優位は縮む一方。orghの生存戦略は下のレイヤーで戦わないこと — **「ハーネスの上の品質・学習・ガバナンス層」**(どのハーネスをworkerに使ってもよい)に特化する。adapter設計は既にその形をしている。

### 2.1 上半分/下半分の境界(オーナー裁定 2026-08-14 → ARCH-001/002 として台帳化)

| | 内容 | 方針 |
|---|---|---|
| **上半分(orghの本体)** | 検収ゲート(受け入れ条件・直列裁定・文脈保持差し戻し)/ criteria台帳と代謝 / 人間をノードに含むDAG(awaiting_human) / 監査可能性(ledger・実測) | ここにだけ投資する。土台が強くなっても価値が減らない |
| **下半分(配管)** | watcher・queue・slots(並列制御)・worktree隔離・プロセス管理・スケジューリング | **新規実装は原則しない**。土台が同等機能を出したら削除・委譲を検討(作るより消すを正とする) |

判定の手順: 機能追加の計画時に「Claude Codeが次版でこれを出したら、この実装は不要になるか?」を問う。
YESなら下半分 → adapter委譲の設計を先に検討してから着手可否を決める(ARCH-002)。

**反転の論理**: 境界を正直に保つ限り、土台の進化は競合ではなくレバレッジになる。
orghのworkerは土台ハーネスそのものなので、**CCが強くなるほどorghのworkerが強くなる**。
競争が起きるのは、下半分に投資し続けた場合だけ。

今週実装したR-1(queue/executor)・R-2(slots)は下半分に該当する。当座の実害(watchのブロッキング・
多重起動の暴走)を解いた橋であり、**いずれ捨てる前提の資産**として扱う。

## 3. 強みを伸ばす(優先順)

1. **台帳と代謝の深化** — 品質バー問題(12)への挑戦として、DESIGN-005(実物観察→正解仕様→TC)を標準工程化し、「参照との並置比較を人間/ペルソナが判定する工程」を検収の一級要素にする。ここは世界の誰も解けていないので、半歩の先行が最大の差別化になる
2. **人間込みDAGの完成** — awaiting_human/承認に通知(Slack/push)を付けるだけで、8は◎に確定する。実装は小さい
3. **誠実性の対外化** — ledger実測のレシート(ミッション別コスト・合格率)を公開フォーマット化。「盛れない構造」はマーケティング資産(ツイート反応の実験と接続)

## 4. 弱みを埋める(優先順・工数感つき)

| 優先 | 施策 | 埋まる観点 | 工数感 |
|---|---|---|---|
| 1 | Slack/push通知(awaiting_human・承認・完了) | 8 | 小 |
| 2 | worker権限プリセット(読み取りgit等の事前承認。b6503b9a t3の実証済み問題) | 8 | 小 |
| 3 | 状態表示のledger/procreg突合(「嘘をつくUI」一族) | 7 | 中 |
| 4 | **MCP対応**(workerのツール接続をMCP標準へ) | 10 | 中 |
| 5 | sandbox実行オプション(コンテナ隔離+egress制御。脅威モデルの明記済み負債) | 6→○ | 大 |
| 6 | モデルルーティング(役割×難易度で安価モデルへ振る。コスト構造の最適化) | 9,7 | 中 |
| 7 | リモート実行(クラウドworker) | 9 | 大(必要になってから) |

## 出典(2026-08-14閲覧)

- [Top Agent Harnesses: Claude Code vs Codex(aimultiple)](https://aimultiple.com/agent-harness) / [Best AI Coding Agents 2026(firecrawl)](https://www.firecrawl.dev/blog/best-ai-coding-agents)
- [Claude Code vs OpenHands(lowcode.agency)](https://www.lowcode.agency/blog/claude-code-vs-openhands)
- [Devin料金・機能(pensero)](https://pensero.ai/blog/devin-pricing) / [Devin Release Notes 2026(releasebot)](https://releasebot.io/updates/devin) / [Cognition製品更新(公式)](https://cognition.com/blog/sept-24-product-update)
- [CrewAI vs AutoGen vs LangGraph 2026(dev.to)](https://dev.to/agdex_ai/crewai-vs-autogen-vs-langgraph-which-multi-agent-framework-in-2026-51m6) / [同 完全ガイド(dev.to)](https://dev.to/pockit_tools/langgraph-vs-crewai-vs-autogen-the-complete-multi-agent-ai-orchestration-guide-for-2026-2d63)
- [Self-Improving AI Coding Agents Through Accumulated Behavioral Rules(arXiv:2607.13091)](https://arxiv.org/abs/2607.13091)
- [Verify-Gated Completion as Admission Control(arXiv:2605.17998)](https://arxiv.org/pdf/2605.17998)
- [What is OpenClaw(DigitalOcean)](https://www.digitalocean.com/resources/articles/what-is-openclaw) / [OpenClaw(Wikipedia)](https://en.wikipedia.org/wiki/OpenClaw)

# orgh 競争環境分析 — 世の中のハーネスの中での強み・弱み(2026-08-14)

> 目的: orghが世の中のエージェントハーネスの中でどこが強く、どこが弱いかを観点別に判定し、
> 強み伸長・弱み充填の優先順位を出す。判定は本リポの実装・実運用の実態(2026-08時点、
> ミッション30本超・執行アーキ改修完了)と、2026年8月時点の外部調査に基づく。
> 作成: オーナー依頼によるセッション分析(出典は末尾)。
>
> **改訂 2026-08-15**: オーナーの反証要求(「本当か? 他に同じものは無いのか?」)を受けて先行事例を
> 敵対的に再調査した結果、**初版の◎判定3件はすべて誇張だったため下方修正**した。各観点に直撃の
> 先行品(CodeRabbit Learnings / HumanLayer / Qodo / Kiro / Spec Kit / Tessl)が存在する。
> §1.5「先行事例カタログ」を新設し、残る差別化点を狭く正確に定義し直した。

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
| 1 | 起点UX(仕事がどこから始まるか) | △(初版○から降格) | Obsidianノート+#goで着火。思考の場が起票の場 | **2026年に「Agent OS」として一大トレンド化**: Obsidianを記憶層に据え、夜間にタスクを積んで朝に成果を受け取る個人向けスタックの解説記事・テンプレートが多数流通(no-code中心)。ノート起点そのものは差別化にならない。**差は品質ゲートの有無** |
| 2 | 計画・分解 | △ | Planner→タスクDAG、REPLAN(1回)、worker:human計画 | LangGraphは人手グラフ、Devinは自動計画。決定的な差なし |
| 3 | 実行の隔離・並列 | △ | git worktree分離+missionロック+グローバルセマフォ(R-2)+永続キュー(R-1) | 並行制御の作り込みは強いが、**隔離の強度**はOpenHands(コンテナ)/Devin(クラウドVM)に負ける。worktreeは権限境界ではない(脅威モデル明記済み) |
| 4 | 検収ゲート | ○(初版◎から降格) | 受け入れ条件ドリブン。Reviewer+ペルソナ直列裁定、不合格は**文脈ごと同一セッションへ差し戻し**、REPLAN/HUMAN分岐、証拠チャネル原則 | **AC駆動は2026年に一大カテゴリ化**: Kiro(EARS記法でAC自動生成→タスク→並列実装)、GitHub Spec Kit(Constitution→Specify→Plan→Tasks)、Tessl(spec-as-source・承認後に仕様準拠を検証)、Qodo(pre-merge多エージェント検収+ルール体系、F1 60.1%)。**残る差別化は「敵対的な別ロールが裁定し、落ちたら同一workerセッションへ文脈ごと戻す」実行時ループと、ペルソナ検収の直列化**。仕様策定の作法自体は既に商用標準 |
| 5 | 組織学習 | ○(初版◎から降格) | retro→playbook追記+**代謝**(gcで統合・矛盾解消・棚上げ)、**criteria台帳**(裁定を蒸留→承認制で規範化) | **直撃の先行品あり**: CodeRabbit **Learnings**(レビュー返信を組織横断の永続ルール化・専用ダッシュボード・「PR固有か team-wide か」の選別指針まで整備)、Qodo「self-learning rules system」、Devin Knowledge。**残る差別化は3点のみ**: ①規範化に**明示的な人間承認ゲート**(CodeRabbitは自動取り込み) ②**代謝**(統合・矛盾解消・棚上げ。他に類例を確認できず) ③**コード以外の領域**(事業判断・プロダクト規範まで同じ台帳に載る) |
| 6 | 安全・ガバナンス | ○ | 自己改変ガード(**configで無効化不可**)、検収役の隔離(--setting-sources)、秘密env strip、予算プール、キャンセルの単一信号設計 | 関所の「不可侵性」は珍しい。ただしsandbox/egress制御は無い(✕成分。OpenHands/Devinに劣後) |
| 7 | 観測・監査 | ○ | 全イベントledger、コスト実測(タスク/ミッション/週次report)、prompts snapshot(再現性) | 個人用途では十分以上。企業級(SSO・SCIM・監査エクスポート=Devin)は無いが不要域 |
| 8 | 人間接点 | ○(初版◎寄りから降格) | **awaiting_human/humandone**(人間をワーカーとしてDAGに組み込み、成果は同じReviewer検収を通す)、承認ブリーフ(PROD-001) | **HITL承認は2026年の標準装備**: HumanLayer(承認を一級の関数呼び出しとしてSlack/メールへルーティング、拒否理由をcontextへ戻す、過去履歴から自動承認を学習)、OpenAI Agents SDK / Microsoft Agent Framework / Cloudflare Agents すべてHITLプリミティブを持つ。n8n・Temporalも人間ステップあり。**残る差別化は「人間が"承認者"ではなく"成果物を出すワーカー"であり、その成果物がAIと同じ検収ゲートを通る」点のみ**(HumanLayerは承認/入力であって成果物の検収ではない)。**しかも通知ルーティングはHumanLayerが持ちorghは持たない=この観点は部分的に劣後** |
| 9 | スケール・運用 | ✕ | 単一マシン・単一オーナー。並列2ミッション+worker枠4で運用中 | Devin/OpenHandsはクラウドでN並列。チーム利用・リモート実行なし |
| 10 | エコシステム・接続性 | ✕ | worker adapter 3種(claude/codex/shell)。**MCP未対応**、通知連携なし、コミュニティなし | 2026年はMCPがツール接続の標準。ここに乗っていないのは孤立リスク |
| 11 | ドメインの幅 | ○ | コード外を実運用済み(動画・ピッチ資料・事業文書・BOOTH出品準備・ゲームUI)。executor Skill群+職種別playbook | コーディング特化勢より広い。「個人の全仕事の組織」という設計思想が実績で裏付く |
| 12 | 品質バーの天井 | △(世界共通未解決) | TC全PASSでもオーナーの求める絵力に届かない事例(quality-bar-vs-criteria)。ただし**基準側を改訂する機構**(gestalt差し戻しに基準特定義務)まで持つ | どのハーネスも「観測可能な基準」の外にある品質(センス・絵力)は未解決。orghは台帳と実物観察プロセス(DESIGN-005)で半歩先 |

## 1.5 先行事例カタログ(反証調査 2026-08-15)

「orghにしかない」を主張する前に必ず確認する既存品。**各観点に直撃品が存在する**。

| 先行品 | 何を持っているか | orghの主張への打撃 | orghが勝っている点(あれば) |
|---|---|---|---|
| **CodeRabbit Learnings** | レビュー返信を組織横断の永続ルールとして蓄積し以後のレビューに自動適用。専用ダッシュボード(app.coderabbit.ai/learnings)。「PR固有 vs team-wide」の選別指針も提供 | **組織学習◎の否定**。「裁定→規範→次の検収が強くなる」ループは既に商用出荷済み | 規範化に人間承認ゲートがある / 代謝(統合・矛盾解消・棚上げ)がある / コード以外も載る |
| **HumanLayer** | 人間承認を一級の関数呼び出しに。Slack/メールへルーティング、拒否理由をエージェントのcontextへ戻す、履歴から自動承認を学習 | **人間接点◎の否定**。しかも**通知ルーティングはorghに無い機能** | 人間が「承認者」でなく「成果物を出すワーカー」で、その成果物が同じ検収を通る |
| **Qodo(旧Codium)** | pre-merge検収ゲート、多エージェント並列レビュー(bug/security/quality/test)、self-learningルール体系、F1 60.1%の実測 | **検収ゲート◎の否定**。多エージェント検収+ルール学習の商用実装 | ペルソナ(非エンジニア視点)検収 / 差し戻しが同一workerセッションへ文脈ごと戻る |
| **Kiro(AWS)** | 要件(EARS記法のAC)→設計→タスクの3文書を自動生成し並列エージェントで実装 | **AC駆動の独自性の否定**。仕様駆動は2026年の標準作法 | 実行時の検収ループ(Kiroは計画時の仕様化が主) |
| **GitHub Spec Kit / Tessl** | Constitution→Specify→Plan→Tasks→Implement の工程化 / spec-as-source+承認後の仕様準拠検証 | 同上。**"Constitution"という規範層の概念も既出** | 規範が裁定から自動蒸留される(Spec Kitは人手記述) |
| **Devin(Cognition)** | Knowledge(組織文脈の自動想起)、Playbooks、企業級ガバナンス | 学習・自律の商用最先端 | 検収の直列裁定 / コスト透明性 |
| **Agent OS(Obsidian系スタック)** | Obsidian記憶+夜間ミッションキュー+朝に成果。2026年のトレンドとして多数の解説・テンプレ | **起点UXの独自性の否定** | 品質ゲート・台帳・監査の有無(no-code勢は持たない) |
| **n8n / Temporal / SanctifAI** | 人間ステップを含むDAG実行、耐久実行、人間ワーカー群(400+ workforce)の組み込み | 「人間をDAGに入れる」自体は既存概念 | 人間の成果物がAIと同一の検収を通る点 |

### 結論の書き直し

**「世界初」「他に無い」は成り立たない。** 各構成要素はすべて、より洗練された形で商用出荷されている
(ダッシュボード・通知ルーティング・ベンチマークスコアの点では**先行品の方が上**)。

正確に言えるのは次の3つだけ:

1. **組み合わせの希少性**: 「検収ゲート × 承認制で代謝する規範台帳 × 成果物を出す人間ワーカー」を
   **1つの個人システムで、コード以外の領域まで**通して回している例は、調査範囲では確認できなかった。
   ただし「確認できなかった」であって「存在しない」ではない(個人の非公開システムは観測不能)
2. **代謝の希少性**: 蓄積したルールを**統合・矛盾解消・棚上げする**機構は、CodeRabbit/Qodo/Devinの
   いずれにも確認できなかった(蓄積はするが腐敗対策が見えない)。orghが4ミッション目でノイズ反転を
   実測してGCを実装した経緯は、この問題が実在することの証拠でもある
3. **越境性**: 上記のどれもコード(またはPR)の文脈に閉じている。事業判断・プロダクト規範・
   制作物の品質基準まで同じ台帳・同じ検収に載せている点は、構造上の違い

### 取り込むべきもの(先行品から盗む)

反証調査の副産物として、**orghが明らかに劣る点と、その解法が既に世に存在する**ことが分かった。

| 取り込む | 出典 | 対応する弱み |
|---|---|---|
| 承認・依頼の**通知ルーティング**(Slack/メール、拒否理由のcontext還流) | HumanLayer | §4優先1(既知の最大の穴) |
| 「一時的 vs 恒久」の**選別指針**と、基準ごとの**適用実績の可視化** | CodeRabbit Learnings | criteria台帳の"効いているかの観測"(閲覧UI自体は `#/criteria` に実装済み) |
| ACの**記法標準化**(EARS等)で検収可能性を機械的に担保 | Kiro | 品質バー問題(観点12)への実務的アプローチ |
| 検収の**ベンチマーク**(F1等の実測で検収器自体の性能を測る) | Qodo | 検収の質が測れていない(orghの盲点) |

## 2. 総合判定

**orghの相対的な立ち位置は「検収ゲート(4) × 代謝する規範台帳(5) × 成果物を出す人間ワーカー(8)」の
組み合わせと、その越境性(コード以外)。** ただし §1.5 のとおり**各要素には商用の直撃品があり、
個別の完成度では負けている**。独自性を主張できるのは組み合わせと代謝と越境性に限る。
研究フロンティア(D)と商用の動き(CodeRabbit/Qodo/Kiro)が同方向であることは、方角の正しさの証拠であると
同時に、**この領域が急速に商品化されつつある**という警告でもある。

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

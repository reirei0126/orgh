# orgh ユースケース棚卸し インベントリ

本ドキュメントは `docs/audit/usecases.json` の内容を人間向けの表に整理したものである。抽出元は CLAUDE.md(本リポジトリ直下には存在せず、README.md / HANDOFF.md / docs/ 配下がSSOT相当の一次情報源)、`docs/deep-dive.md`、`docs/orgh-first-guide.md`、`docs/threat-model.md`、`playbooks/*.md`、`prompts/*.md`、`orgh/*.py` の実装、および `runs/` `ops/` 配下の実運用痕跡(mission.json / ledger.jsonl / CANCEL / APPROVED フラグ等)である。

区分の定義:

- **active**: ドキュメント記載があり、かつ `runs/` `ops/` 配下に実際の実行痕跡(mission.json・ledger.jsonl・フラグファイル等)が確認できるもの。
- **assumed**: ドキュメントまたはコード上に機能として存在するが、実行痕跡が確認できない、または明確に「未実装/未使用」と自己申告されているもの。
- **obsolete**: 過去には実際に使われていた(または使われる想定だった)が、現在は運用上意図的に無効化されているもの。

## 一覧表

| usecase_id | title | actor | status | 根拠(evidence抜粋) |
|---|---|---|---|---|
| UC-01 | ノート起点のフルミッション実行(orgh run --note) | human | active | README.md:62, orgh/cli.py:96-103, runs/0f9d5591/mission.json |
| UC-02 | 直接指示起点のフルミッション実行(orgh run --intent) | human | active | README.md:65, orgh/cli.py:104-107, ops/demo/runs/2bdf2bee/mission.json |
| UC-03 | Obsidian vault監視デーモンによる自動着火(orgh watch) | cron | active | README.md:90-103, orgh/sources/obsidian.py:58, runs/_watch_state.json |
| UC-04 | 自己改変ガード + 人間承認ゲート(orgh approve) | human | active | orgh/guard.py:25, runs/a385f876/APPROVED, runs/8e096d63/APPROVED |
| UC-05 | ミッションのキャンセル(orgh cancel / vault #cancel) | human | active | orgh/cli.py:158-167, runs/d0d795d4/CANCEL |
| UC-06 | レビュー不合格時の差し戻し改善ループ(attempts + resume) | worker | active | orgh/orchestrator.py:108, runs/8e096d63/mission.json, runs/0f9d5591/mission.json |
| UC-07 | REPLANエスカレーション(計画欠陥の再設計) | planner | active | orgh/planner.py:153, runs/7307189e/ledger.jsonl, runs/d0d795d4/ledger.jsonl |
| UC-08 | Retroによる教訓抽出とplaybook蓄積 | planner | active | orgh/planner.py:126, playbooks/coding.md:1-2, playbooks/planning.md:1-4 |
| UC-09 | worktree分離による並列タスク実行とブランチ成果物受け渡し | worker | active | orgh/worktree.py:32, config.yaml:48-51, .orgh-worktrees(本ミッションの実行環境自体) |
| UC-10 | タスク/ミッション単位のコスト計測(Budget.charge) | worker | active | orgh/state.py:154, orgh/state.py:172, runs/7307189e/mission.json(spent_usd=28.87) |
| UC-11 | 予算上限超過による自動停止(現在は無効化) | human | obsolete | config.yaml:45-46, README.md:123-131, HANDOFF.md:74-75 |
| UC-12 | orgh reportによる合格率・差し戻し率の計器算出 | human | assumed | README.md:175-182, HANDOFF.md:48 |
| UC-13 | orgh gcによるplaybook代謝・runsアーカイブ | cron | assumed | orgh/watcher.py:27, orgh/gc.py:115, runs/_gc_state.json |
| UC-14 | orgh doctorによる事前疎通確認 | human | assumed | orgh/cli.py:66-72, orgh/doctor.py:51, README.md:77-78 |
| UC-15 | orgh自身の機能追加・ドキュメント整備(自己改善ミッション) | human | active | ops/demo/runs/099e281b/mission.json, ops/demo/runs/6fe49f2f/mission.json, README.md:7-18 |
| UC-16 | デスクトップGUIプロトタイプ探索(Tauri) | human | active | runs/8e096d63/mission.json |
| UC-17 | 外部ターゲットリポジトリの開発・改修(projects_map経由) | human | active | runs/b6503b9a/mission.json, runs/db8e54e5/mission.json, HANDOFF.md:10-12 |
| UC-18 | プロダクト説明資料・ピッチ資料の生成(dogfooding) | human | active | ops/demo/runs/2bdf2bee/mission.json, ops/demo/runs/8d93c967/mission.json, docs/product/BUILD.md |
| UC-19 | Codexワーカーによるマルチエージェント実行 | planner | active | orgh/adapters/base.py:104, config.yaml:16, runs/d0d795d4/mission.json |
| UC-20 | 実ブラウザ目視QAをacceptanceに組み込む運用規律 | worker | active | playbooks/coding.md:2, HANDOFF.md:27-34 |
| UC-21 | orgh cleanupによるworktree/ブランチ掃除 | human | assumed | orgh/cli.py:146-148, orgh/worktree.py:112, HANDOFF.md:64 |
| UC-22 | サブミッション再帰(設計済み・実行層未実装) | planner | assumed | README.md:198, orgh/state.py:190 |
| UC-23 | ShellAdapter経由の任意CLI LLM利用(gemini等) | worker | assumed | orgh/adapters/base.py:119-121, config.example.yaml:31, config.yaml:16 |
| UC-24 | Notion等の代替入力ソースアダプタ | human | assumed | orgh/sources/base.py:1-6, docs/deep-dive.md:85 |

## statusサマリ

- **active**: 16件 — UC-01〜UC-10, UC-15〜UC-20(実運用の `runs/` `ops/` 配下に実行痕跡あり)
- **assumed**: 7件 — UC-12, UC-13, UC-14, UC-21, UC-22, UC-23, UC-24(ドキュメント/コード上は存在するが実施痕跡が薄い、または明確に未実装)
- **obsolete**: 1件 — UC-11(過去は実費運用の予算ガードとして機能していたが、サブスク認証移行に伴い意図的にnull設定へ変更済み)

合計24件。

## ドキュメントには書かれているが実施痕跡が見つからないもの

以下は README.md / docs/deep-dive.md / HANDOFF.md 等に明記されている機能・運用手順だが、`runs/` `ops/` 配下の実行痕跡(mission.json・ledger.jsonl・生成ファイル・vault側のresults/reports)を横断的に確認した限り、実行された証拠が見つからなかったもの(usecases.jsonでは`assumed`に分類):

1. **`orgh report`(計器算出)** — README.md:175-182 に「改善ループが効いているか=増幅が実在するかを測る最重要メトリクス」と明記されているが、HANDOFF.md:48 では「クリーンな新ミッション2〜3本→`orgh report`で増幅の数字判定(D本番)」がまだ未着手の後続TODOとして記載されている。`--vault`オプションで書き出されるはずの `<vault>/orgh/reports/<date>.md` も vault 側に存在しない。
2. **`orgh gc`の実consolidation** — `orgh/gc.py`のdocstringが明言する4段階(バックアップ→古い教訓の退避→LLMによる重複統合→runsアーカイブ)のうち、`runs/_gc_state.json`にはベースライン書き込み1件のタイムスタンプがあるのみで、`playbooks/_backup/`・`playbooks/_archive/`・`runs/_archive/`のいずれも存在しない。ドキュメント自身が「初回パスはgcを走らせない」仕様であることを認めており、この初回パス以降の実consolidationがまだ発生していないと判断できる。
3. **`orgh doctor`の実行ログ** — README.mdに「事前疎通確認。『全タスク謎のfailed』の前に」と明記される予防的コマンドだが、永続的な出力を残さない設計のため、リポジトリ内・vault内のどちらにも実行痕跡となる副産物が存在しない。
4. **`orgh cleanup`の実行** — HANDOFF.mdの「後回しでよい改善候補」に「worktree掃除: 検収済みミッションは`orgh cleanup <id>`」と挙げられたまま未実施であり、`.orgh-worktrees/`配下には過去の完了・キャンセル済みミッション(2d953f15, 8e096d63等)のworktreeが実際に削除されずに残存している。
5. **サブミッション再帰** — README.md:198が「Budget設計は対応済み、実行層は未実装」と自己申告しており、`orgh/state.py`のBudget.split()を呼び出す再帰実行のオーケストレーションコードはリポジトリ中に見当たらない。
6. **ShellAdapter経由の他CLI LLM(gemini等)利用** — `config.example.yaml`にコメント付きで拡張枠が用意されているが、実運用の`config.yaml`の`workers.enabled`は`[claude_code, codex]`のみで、全ミッション・全タスク(`runs/`・`ops/demo/runs/`を横断して確認)を通じてworker="shell"のタスクは1件も見つからなかった。
7. **Notion等の代替入力ソースアダプタ** — `orgh/sources/base.py`冒頭のコメントが「将来の入力ソース(Notion等)はREGISTRYにアダプタを足すだけで差し替えられる(Notionアダプタ自体はここでは実装しない)」と明言する設計上の拡張点であり、`docs/deep-dive.md:85`も「現時点で実装済みなのはObsidianAdapterのみ」と確認している。実装コード・利用実績のいずれも存在しない。

## 補足: 分類にあたっての判断

- リポジトリ直下に本リポジトリ自身の `CLAUDE.md` は存在しなかった(`find` で確認済み)。ユーザーのグローバル `~/.claude/CLAUDE.md` はorgh固有のSSOT定義を持たないため、本タスクでは README.md を実質的なSSOT、`docs/deep-dive.md` を実装トレース済みの二次情報源として優先的に参照した。
- `runs/` と `ops/` は `.gitignore` でトラッキング対象外(gitignore:5, gitignore:11)だが、実運用のミッション記録が置かれる実在ディレクトリであるため、リポジトリ本体(`/Users/uesugirei/projects/org-harness`)の絶対パスで根拠として引用した。本タスクの作業worktree(`.orgh-worktrees/a385f876-t1`)にはこれらの未トラッキングディレクトリが存在しないため、相対パスでは実在確認ができない制約による。
- `runs/8e096d63`(デスクトップGUI試作)や `runs/7307189e`(sikore-slot UI刷新)のように、ミッション自体は完走・承認済みでも成果物がmainへ未マージのケースは、「実施痕跡が確認できる」という基準に基づき`active`に分類した。マージの可否はこのタスクの範囲外である。

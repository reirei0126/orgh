# orgh — 自律増幅型AI組織ハーネス

Obsidian/メモ → 意図解釈 → 計画(DAG) → Claude Code / Codex セッション並列起動 → レビュー → 差し戻し改善ループ → 学習の蒸留、までを1コマンドで回す。

## 組織構造

```
Obsidian vault ──ingest──> Planner(Opus)  ……… 経営層: タスクDAG設計
                              │ tasks.json
                              ▼
                       Orchestrator ────────── 並列dispatch (ThreadPool)
                        │        │
                 Claude Code   Codex   (+shell枠で任意LLM)  … 実働層
                        │        │
                              ▼
                       Reviewer(Sonnet) …… 品質ゲート: acceptance判定
                        pass │ fail → feedbackを --resume で同一セッションに差し戻し
                              ▼
                       Retro ──> playbooks/*.md …… 組織知の蒸留(増幅の核)
```

「増幅」の実装は2点:
1. **改善ループ**: レビューfailはClaude Codeの`session_id`を`--resume`して文脈を保ったまま修正させる(最大`max_attempts`回)
2. **Playbooks**: Retroがミッションごとの教訓を`playbooks/`に追記し、次回以降のPlanner/Worker全員のプロンプトに自動注入される。回すほど組織が賢くなる

## セットアップ

```bash
pip install -e .
cp config.example.yaml config.yaml   # vaultパスとworker設定を編集
```

前提: `claude`(Claude Code CLI)と`codex`がPATHにあり認証済み。

`prompts_dir` / `playbooks_dir` は config で指定する(パッケージ相対ではなくconfig駆動)。
非editableでインストールした場合や作業ディレクトリがリポ外の場合は、絶対パスで指定すること。

## 使い方

```bash
# vault内のミッション候補(inbox配下 or #missionタグ)を一覧
orgh scan

# ノート起点でフル実行(plan→execute→review loop→retro)
orgh run --note "オントロジーレイヤーMVP"

# ノートなしで直接指示
orgh run --intent "このリポジトリのテストカバレッジを60%まで上げる"

# 中断・失敗したミッションの再開 / 状況確認
orgh resume <mission_id>
orgh status <mission_id>
```

実行結果は `runs/<mission_id>/` に永続化(mission.json / ledger.jsonl / artifacts/)。

## 設計判断メモ

- **ObsidianはMCPではなくファイル直読み**。MCPのsandbox問題を回避し、wikilink1ホップまで辿って文脈ダイジェストを構築
- **モデル三層に対応**: `roles.planner=opus`, workers=sonnet がデフォルト。長時間自律スプリントは`model: fable`に切替
- **Reviewerにも Read/Bash を許可** — 報告文ではなく実ファイル・テスト実行で判定させる
- **アダプタは3行で増やせる** (`orgh/adapters/base.py` の REGISTRY)

## 育て方(推奨ループ)

1. まず小さいミッションで2〜3周回す
2. `runs/*/ledger.jsonl` を見て差し戻しパターンを確認
3. `prompts/*.md` と `playbooks/` を手で編集 — ここがこのハーネスの「経営」

## テスト

```bash
pip install -e ".[test]"
pytest tests/
```

モックバイナリ方式のSTスイート(`tests/mocks/claude`・`tests/mocks/codex`)が走る。~30秒。

## 既知の割り切り / 次の拡張候補

- git worktree分離は未実装(現状は`workdir`指定のみ)。並列タスクが同一リポを触るなら worktree per task を`_run_task`に足す
- Codexにはresume相当がないため差し戻しはプロンプト再構築で対応
- 予算ガード: ledgerに`cost_usd`は記録済み。上限超過でmission停止する閾値をloopに足すだけ

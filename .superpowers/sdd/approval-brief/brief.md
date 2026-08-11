# 承認ブリーフ実装(2026-08-11 オーナー承認済み設計)

オーナー裁定(台帳 PROD-001 [norm]): 「承認・検収などのオーナー接点では、求める判断の内容を端的な一文で先に提示し、詳細はオーナーが求めたときに展開表示する。判断材料を探させるUIは不合格とする。」
実例: mission 1adf234e で承認ボタンを押す際、何を承認するのか分からなかった。

方式はLLM不使用・決定論的生成。作業は worktree /Users/uesugirei/projects/org-harness-approval-brief(ブランチ feat/approval-brief)のみ。Pythonテスト: `~/projects/org-harness/.venv/bin/python -m pytest`(worktreeルートから)。ベースライン: 267 passed。TDD(各タスク: 失敗テスト→実装→合格)。

## T1. コア: guard.approval_reason + status_json.approval_brief

**orgh/guard.py** に追加:
```python
def approval_reason(cfg: dict, workdir: str) -> str | None:
    """needs_approvalがTrueになる理由を人間可読の一文で返す(発火しなければNone)。
    判定ロジックはneeds_approvalと同一規則を保つこと。"""
```
返す文言(例): `orgh自身のパッケージ ({path}) を書き換える` / `prompts_dir ({path}) 配下を書き換える` / `playbooks_dir ({path}) 配下を書き換える`。needs_approval は approval_reason(...) is not None のラッパに書き換えて判定規則の二重管理を排除(既存テストの挙動不変が絶対条件)。

**orgh/status_json.py** の status_payload に追加: awaiting_approval タスクが1件以上あるとき
```python
"approval_brief": {
    "summary": "タスク「<最初のタイトル>」ほかN件が<reason>ため停止中。承認すると残りM件のタスクが実行される(消費済み X.XX USD)。",
    "gated_tasks": [{"id", "title", "workdir", "reason"}],
    "pending_task_count": M,   # awaiting + pending の合計(承認で動き出す数)
}
```
(1件のみなら「ほかN件」を省く。reasonは approval_reason の出力)。awaiting なしなら approval_brief キー自体を含めない(GUI後方互換)。status_payload は cfg を受け取っていないので、シグネチャを `status_payload(mission, cfg=None)` に拡張(cfg=Noneなら approval_brief を省略=既存呼び出し互換)。cli.py の status --json 呼び出しに cfg を渡す。

テスト(tests/test_status_json.py と tests/test_governance.py の既存様式に合わせる): (a) awaiting タスクありで summary に タイトル・理由・消費額 が含まれる (b) awaiting なしで approval_brief キーが無い (c) approval_reason の3分岐(pkg / prompts_dir / playbooks_dir)と非発火None (d) needs_approval の既存テストが無変更で通る。

## T2. CLI: orgh approve の確認ゲート

cli.py の approve dispatch(283行目〜)を変更:
- `--yes` フラグを追加(approve の add_parser のところ)
- waiting 判定後・APPROVED作成の**前**に、T1のブリーフ(summary + gated_tasks の title/workdir 一覧)を print
- `--yes` が無く、かつ `sys.stdin.isatty()` の場合のみ `input("承認して実行する? [y/N]: ")` で確認。y/Y以外は「承認を中止した」と出して sys.exit(APPROVEDを作らない)
- `--yes` または非TTY(watch・パイプ経由)は従来どおり即続行 — **`ORGH_APPROVED=` 確認行の契約と出力順は絶対に変えない**(GUIブリッジが検知している。ブリーフ表示は確認行より前に出ること)
- 非TTYで--yes無しの場合も即続行とする(後方互換優先。ブリーフは表示される)

**desktop/src-tauri/src/cli.rs**: approve_mission の spawn 引数に `--yes` を追加(90行目付近の長時間子プロセス起動。resume側は触らない)。Rustのビルド確認は `cargo check`(src-tauri で。フルビルド不要)。

テスト: (a) --yes で従来動作+ブリーフがstdoutに出る (b) 非TTY(テストはこれ)で--yes無しでも続行しブリーフが出る (c) 既存の test_governance の approve 系が無変更で通る(要確認: subprocess経由ならTTYでないので互換のはず)。

## T3. GUI: 承認ダイアログ(desktop/src)

MissionDetailPage.tsx の「✓ 承認する」ボタン(212行目付近)を変更:
- 押下で即 approveMission せず、**確認ダイアログ**を開く: status --json の approval_brief.summary を大きく1文表示 + 「詳細を見る」折りたたみ(gated_tasks の title/workdir/reason 一覧、消費済みコスト)+ [承認して実行] [キャンセル]
- [承認して実行] で既存の approveMission フローへ(busy状態・spinner等の既存挙動維持)
- approval_brief が無い(旧CLI/データ)場合は従来どおり即時approve(graceful degradation)
- mocks.ts のモックミッションに approval_brief を追加し、ブラウザモード(isTauriRuntime=false)で動作すること
- スタイルは styles.css の既存トークン/クラスに合わせる。新規依存の追加禁止

**検証(QA-001 [norm] が適用される: 視覚検証なしの合格は不可)**:
1. `cd desktop && npm run build`(tsc + vite build)が通る
2. `npm run dev` をバックグラウンド起動し、ヘッドレスChromeで承認待ちモックミッションの詳細ページを開き、ダイアログ表示状態のスクリーンショットを撮って**Readで実視認**する(レイアウト崩れ・文字化けがないこと)。スクショは `/private/tmp/claude-501/-Users-uesugirei-projects/8fe6a488-62fa-4fb5-a086-cced3dddd9e9/scratchpad/` 配下に保存(リポ内に置かない)。ダイアログを開くのにモック環境で操作が必要なら、URLクエリやモック初期状態で承認待ちミッションを表示できるようにしてよい(mocksの範囲で)
3. 終了時に dev サーバを止める

## T4. 仕上げ

- HANDOFF.md 冒頭の 2026-08-11 セクションに追記: 承認ブリーフ実装(PROD-001の初適用)+ 改修候補2件の新規追記「watch再起動が実行中ミッションを巻き込む(graceful drainなし)」「死んだミッションがorgh listで[running]表示され続ける(プロセス生存確認なし)」(a2d8d01a 21時間ゾンビ事例より)
- README の使い方に approve の確認ゲートを1行

## 完了条件

Python全suite ≥267+新規、0 failures。desktop は tsc/vite build 成功 + cargo check 成功 + スクショ実視認の記録。レポートを /Users/uesugirei/projects/org-harness-approval-brief/.superpowers/sdd/approval-brief/report.md に(RED/GREEN証跡、スクショのパスと視認所見を含む)。コミットは T1-T2 / T3 / T4 の粒度を目安に日本語既存様式で。

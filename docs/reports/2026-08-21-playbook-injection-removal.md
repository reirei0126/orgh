# playbooks自動注入の廃止(統治線をcriteriaへ一本化) — 完了報告

日付: 2026-08-21
対象: `org-harness`(orgh)リポジトリ
決定根拠: `docs/strategy/direction-2026-08.md` §3.3、`docs/strategy/raison-detre-2026-08.md` §5-R1

## 1. やったこと(サマリ)

Planner/Worker双方のプロンプトへの playbooks 自動注入を廃止した。承認制の
`criteria` 台帳との統治線二重化を解消し、playbooks は「Retroが自動追記し
gcが代謝するが、プロンプトには一切現れない参照ドキュメント」に位置づけを
変更した。教訓を実際の規範として効かせたい場合の経路は
「`criteria` 下書き(verdictから自動蒸留)→ オーナー承認」の一本のみである
(既存機構。今回新設していない)。

- `orgh/planner.py` の `_playbook_context()`(注入専用関数)を削除。付随して
  未使用になった `_META_RE`(注入時の日付ソートにのみ使用)も削除。
- `plan()` から `playbooks=_playbook_context(cfg)` の注入を除去。
- `worker_prompt()` から `playbooks=_playbook_context(cfg, 4000)` の注入を除去。
- `prompts/planner.md` / `prompts/worker_preamble.md` から `{playbooks}`
  プレースホルダとその見出し(「組織の過去の学び(Playbooks)」等)を削除し、
  `.format()` 呼び出し側と整合させた。
- `_playbooks_dir()` は `orgh/playbooks_json.py` が import しているため維持。
- 廃止しなかったもの(仕様どおり無変更): `orgh/planner.py` の retro 追記処理、
  `orgh/gc.py` の代謝処理全体(diffゼロ、AC-4で確認済み)、`orgh/cli.py` の
  `orgh playbooks` 表示、`orgh/playbooks_json.py`、`orgh/state.py` の
  `playbooks_dir` 設定、`orgh/guard.py` の書き込みガード、`desktop/` のGUI表示系。

## 2. 網羅grep結果(分類表)

対象: `orgh/ prompts/ tests/ docs/ desktop/ README.md`(`.orgh-worktrees/`・
`playbooks/_backup/`・`playbooks/_archive/`・`__pycache__` を除外)。
検索パターン: `playbooks_dir|playbook|_playbook_context`(大小文字無視)。
総ヒット数 455行。ファイル単位で分類し、代表的な内容と判定根拠を付す。

**分類凡例**
- **注入系(廃止済み)**: Planner/Workerのプロンプトへplaybooks内容を注入するコード・記述。今回すべて削除・修正した。**残存ゼロ**(下表のとおり全ファイルが保全系)。
- **保全系(残存)**: retro追記・gc代謝・CLI表示・GUI表示・config項目・guard・歴史文書など、injection以外の正当な残存。

| ファイル | 件数 | 分類 | 内容 |
|---|---|---|---|
| `orgh/gc.py` | 24 | 保全系 | playbook代謝(backup/archive/consolidate)。**無変更**(AC-4で`git diff --stat`ゼロを確認) |
| `orgh/planner.py` | 12 | 保全系 | retro追記・`_playbooks_dir()`・`_PLAYBOOK_NAME_RE`(パストラバーサル防御)。注入コード(`_playbook_context`)は本タスクで削除済み |
| `orgh/playbooks_json.py` | 11 | 保全系 | `orgh playbooks --json`のペイロード組み立て。`_playbooks_dir` importのみ維持、注入関数は使用していない |
| `orgh/cli.py` | 10 | 保全系 | `orgh playbooks`/`orgh gc`サブコマンド定義 |
| `orgh/executor.py` | 4 | 保全系 | 自動gcの定期起動(ミッション非実行時のみ) |
| `orgh/criteria.py` | 4 | 保全系(別系統) | criteria台帳自身の書式・詰め方をplaybookと比較する設計コメント。criteria自身の注入機構(こちらは意図的に存続)であり、playbooks注入とは無関係 |
| `orgh/state.py` | 3 | 保全系 | `playbooks_dir`設定フィールドの定義(dataclass) |
| `orgh/guard.py` | 3 | 保全系 | 自己改変ガードの`playbooks_dir`書き込み保護 |
| `prompts/retro.md` | 1 | 保全系 | Retro応答スキーマの`playbook_name`フィールド説明 |
| `prompts/gc.md` | 1 | 保全系 | 統合Retro(GC)対象playbook名のテンプレ変数 |
| `prompts/planner.md` | 0 | — | `{playbooks}`プレースホルダは削除済み(本タスクで対応) |
| `prompts/worker_preamble.md` | 0 | — | 同上 |
| `tests/test_playbooks_json.py` | 43 | 保全系 | `orgh playbooks --json`契約試験(無変更) |
| `tests/test_paths.py` | 12 | 保全系 | config駆動パス試験+新設のAC-2試験(`TestPlaybooksNotInjected`、非注入の検証) |
| `tests/test_gc.py` | 9 | 保全系 | gc/retro試験。`TestInjectionCap`(注入capの試験)は削除(本タスク、理由は§3) |
| `tests/test_governance.py` | 6 | 保全系 | guardの`playbooks_dir`書き込み保護試験 |
| `tests/test_criteria_feedback.py` | 5 | 保全系 | retro出力(`playbook_name`)からのcriteria蒸留試験 |
| `tests/test_hardening.py` | 4 | 保全系 | `playbook_name`バリデーション(パストラバーサル防御)試験 |
| `tests/test_packaging.py` | 2 | 保全系 | config駆動パスのパッケージング試験 |
| `tests/mocks/claude` | 2 | 保全系 | retro/gcロールへのモック応答 |
| `tests/test_status_json.py` / `test_st_scenarios.py` / `conftest.py` | 各1 | 保全系 | fixture・状態表示試験 |
| `README.md` | 14 | 保全系(更新済み) | 本タスクで「自動注入は廃止済み・criteria承認経路」に書き換え |
| `docs/deep-dive.md` | 17 | 保全系(更新済み) | 2.2節・2.8節・アーキ図の注入記述を修正、`_playbook_context()`削除を反映 |
| `docs/product/orgh-deep-dive-2026-08.md` | 4 | 保全系(更新済み) | 「廃止予定」→「廃止済み(2026-08-21)」に更新 |
| `docs/orgh-first-guide.md` | 2 | 保全系(更新済み) | 非エンジニア向けガイド。「ノートは自動で読み込まれない」「criteria承認で規範化」を明記 |
| `docs/threat-model.md` | 1 | 保全系 | 自己改変ガードの保護対象としての`playbooks_dir`言及(注入と無関係) |
| `docs/strategy/raison-detre-2026-08.md` / `direction-2026-08.md` / `harness-landscape-2026-08.md` / `2026-08-10-value-strategy-design.md` | 7/1/4/3 | 保全系(決定文書・不変更) | 廃止という決定そのものを記述した文書。決定当時の文脈として正確なため変更不要 |
| `docs/plans/2026-08-10-criteria-personas-plan.md` | 6 | 保全系(歴史記録・不変更) | 完了済み実装計画書 |
| `docs/refactor/plans/2026-08-12-*.md` | 2/1 | 保全系(歴史記録・不変更) | 完了済みリファクタ計画書 |
| `docs/journal/2026-08-12-session-log.md` | 2 | 保全系(歴史記録・不変更) | 過去セッションログ |
| `docs/audit/*.json` `*.md`(features/usecases/usage-evidence/usecase-inventory/feature-inventory/pruning-ledger) | 計52 | 保全系(凍結監査台帳・不変更) | 2026-08-07/08-10に人間承認済みで決着した監査記録。日付入りの歴史的スナップショットのため不変更 |
| `docs/gui-phase2/*.md` | 計16 | 保全系(GUI設計書・不変更) | PlaybooksPage等の表示系GUI仕様。desktop表示系は変更対象外(指示どおり) |
| `docs/product/*.html`(orgh-deep-dive/orgh-techbook/pitch-engineer/orgh-first-guide) | 計62 | 保全系(静的成果物・不変更) | 対応する`.md`のHTML書き出し版と見られる過去のプロダクト資料。本タスクのスコープ(README・本文docs)からは対象外と判断し不変更。**要オーナー確認**: 内容が古いままの場合は別途HTML再生成が必要 |
| `desktop/**`(`PlaybooksPage.tsx`・`types.ts`・`router.ts`・`App.tsx`・`MissionDetailPage.tsx`・`*.rs`・integration test) | 計67 | 保全系(GUI表示系・不変更) | タスク指示により変更対象外。すべて閲覧表示のみで、プロンプト注入とは無関係と確認済み(`inject`/`注入`でのgrepではヒットなし) |
| `desktop/API.md` / `desktop/docs/VERIFY-PHASE2.md` / `VERIFY-PHASE3.md` | 13/19/6 | 保全系(表示系API契約・検証記録・不変更) | `orgh playbooks --json`のGUI表示契約と過去の実機検証記録。注入とは無関係 |

**結論**: 注入系(廃止済み)に分類されるヒットは**0件**。`grep -rn '{playbooks}' prompts/` と
`grep -rn '_playbook_context' orgh/` はいずれも終了コード1(ヒット0)を確認済み(§4のAC-3参照)。

## 3. 修正したテスト一覧

| ファイル | 修正内容 | 理由 |
|---|---|---|
| `tests/test_paths.py` | `test_worker_prompt_uses_config_prompts_dir`: センチネルテンプレートから`{playbooks}`トークンを削除 | `worker_preamble.md`が`playbooks`引数を受け取らなくなったため、テンプレート側の未使用プレースホルダを残すと`.format()`が`KeyError`になる |
| `tests/test_paths.py` | `test_playbooks_dir_config_driven`(playbooks_dir配下の内容が注入されることを検証)を**削除**し、`TestPlaybooksNotInjected.test_worker_prompt_excludes_playbooks_dir_content`(注入されないことを検証)に置き換え | 「注入される」ことを前提にした旧テストは新仕様と正反対の主張になるため、そのまま緩めるのではなく検証方向を反転させた新テストへ差し替えた。AC-2の要求(worker側)を満たす |
| `tests/test_paths.py` | `test_missing_playbooks_dir_is_tolerated`(playbooks_dir欠落時に`"no playbooks yet"`が出力されることを検証)を**削除** | `worker_prompt()`がplaybooks_dirを一切参照しなくなったため、テスト対象の挙動自体が存在しなくなった(削除ではなく仕様変更ではなく機能削除そのものに追従した削除) |
| `tests/test_paths.py` | `TestPlaybooksNotInjected.test_plan_prompt_excludes_playbooks_dir_content`を新設(`planner._ask_json`をmonkeypatchして実際にPlannerへ渡るプロンプト文字列を捕捉し、目印文字列が含まれないことを検証) | AC-2の要求(Planner側)を満たす。`tests/test_projects_map.py`の`TestPlannerInjection`と同じ手法(既存パターンの踏襲) |
| `tests/test_gc.py` | `TestInjectionCap.test_cap_keeps_newest_lessons`(`planner._playbook_context(cfg, max_chars=200)`を直接呼び、日付降順capで最新教訓が生き残ることを検証)を**削除** | 検証対象の`_playbook_context()`自体を本タスクで削除したため、テストの前提となる関数が存在しなくなった。capという概念自体が注入専用ロジックであり、代替対象が無い(削除以外の選択肢がない) |
| `tests/test_gc.py` | モジュールdocstringから「注入時のcapは『日付降順で詰める』」の一文を削除 | 廃止した注入capの説明が残ると実装と乖離するため |

いずれのファイルも「勝手な削除」ではなく、対象の生産コード(`_playbook_context()`・
`{playbooks}`プレースホルダ)を本タスクで削除したことに追従した削除・置き換えである。

## 4. AC別の検証結果

- **AC-1**: `pytest`(リポルート、venv経由)= `667 passed`、終了コード0。
- **AC-2**: `pytest -k "excludes_playbooks_dir_content"` = `2 passed`(Planner側・Worker側それぞれ1件ずつ)。
- **AC-3**: `grep -rn '{playbooks}' prompts/` → ヒット0・終了コード1。`grep -rn '_playbook_context' orgh/` → ヒット0・終了コード1。
- **AC-4**: `pytest tests/test_gc.py tests/test_playbooks_json.py` = `16 passed`。`git diff --stat orgh/gc.py` = 出力なし(空)。
- **AC-5**: 本ファイル自体が該当(§2の分類表・§3の修正テスト一覧・§5の変更ファイル一覧・§6のpytest結果)。
- **AC-6**: README.md「組織構造」節・「playbookの代謝」節、`docs/orgh-first-guide.md`に「プロンプトへの自動注入は廃止済み(または『自動的に読み込まれるわけではない』)」と「criteria下書き→オーナー承認」の両方を明記済み。

## 5. 変更ファイル一覧

```
 BACKLOG.md                              |  2 +-   (完了マーキング)
 README.md                               | 15 +++++-----  (playbooks位置づけの更新)
 docs/deep-dive.md                       | 18 ++++++------  (注入記述の修正・2.8節書き換え)
 docs/orgh-first-guide.md                |  4 +--   (非注入・criteria承認経路の明記)
 docs/product/orgh-deep-dive-2026-08.md  |  4 ++-   (「廃止予定」→「廃止済み」)
 orgh/planner.py                         | 35 +----------------------  (_playbook_context削除・呼び出し2箇所除去)
 prompts/planner.md                      |  3 --   ({playbooks}プレースホルダ削除)
 prompts/worker_preamble.md              |  3 --   ({playbooks}プレースホルダ削除)
 tests/test_gc.py                        | 13 ---------  (TestInjectionCap削除・docstring修正)
 tests/test_paths.py                     | 49 +++++++++++++++++++++++----------  (テスト差し替え・新設)
 docs/reports/2026-08-21-playbook-injection-removal.md | 新規(本ファイル)
```

`orgh/gc.py` は指示どおり無変更(AC-4で確認)。`playbooks/coding.md`等の
実データは、テスト実行時に既知の非hermetic fixture(`tests/conftest.py`の
`cfg`がデフォルトで実リポジトリの`playbooks/`を指す)により一時的に書き換わる
ことがあるが、最終的に`git checkout -- playbooks/`で元に戻し、成果物としての
差分には含めていない(この問題自体は`playbooks/coding.md`に既存の教訓として
記録済みで、本タスクのスコープ外のため未対応)。

## 6. pytest最終実行結果

```
$ pytest
667 passed in 31.73s
終了コード: 0
```

補助実行(AC個別確認、いずれも上記の一部として再掲):
```
$ pytest -k "excludes_playbooks_dir_content"
2 passed, 665 deselected

$ pytest tests/test_gc.py tests/test_playbooks_json.py
16 passed
```

# workdir独立リポ判定ガード(workdir_guard)

## 背景

2026-08-12の実運用で、ミッションのworkdirに「公開リポ `decision-os-mvp` の内側にある、gitignore対象のサブディレクトリ」(例: `<decision-os-mvp>/private/cases/003-orgh-portfolio`)を指定してミッションを実行したところ、`orgh/worktree.py` の `ensure_task_worktree` が **親リポ(decision-os-mvp)を対象に** `git worktree add` でworktreeとブランチ(`orgh/<mission>/<task>`)を作成し、workerの成果物が親リポのルート相対パスでコミットされた。非公開の成果物が公開リポのブランチに混入する事故であり、pushしていれば公開事故になっていた。

`orgh/workdir_guard.py` は、workdirが「独立したgitリポジトリのルート」かどうかを分類し(`INDEPENDENT_ROOT` / `NESTED_IN_OTHER_REPO` / `NOT_A_REPO`)、入れ子(親リポの内側)の場合に安全側へ倒すための判定関数(`classify_workdir`)と拒否エラー生成(`guard_workdir` / `WorkdirGuardError`)だけを提供する。**実行経路(`orchestrator._attempt_loop` や `worktree.ensure_task_worktree`)への結線は本ドキュメント作成時点では未実施であり、別タスクで行う。**

## 採用した設計

検討した3案は次の通り。

- **(a) 実行前検査で拒否**: `classify_workdir` の結果が `NESTED_IN_OTHER_REPO` のとき、`guard_workdir` が親リポのパス・危険性・直し方を明示した `WorkdirGuardError` を送出して実行を止める。
- **(b) workdir直下に独立リポを自動 `git init`**: 検討したが不採用。
- **(c) config / projects_map での明示オプトイン**: `worktree.allow_nested_workdir`(既定 `false`)として `WorktreeCfg`(`orgh/state.py`)に追加し、逃げ道として採用。

最終的に **(a)を既定の挙動とし、(c)を明示オプトインの逃げ道として組み合わせる** 設計を採用した。(b)の自動initは、ユーザーのディスク状態(gitignore対象ディレクトリの中身)を無断で書き換える副作用が大きく、そもそも事故の原因が「workdirが独立リポであるべきという前提をorgh側が検査せず黙って進めたこと」である以上、既定動作でさらに黙示的な操作(自動git init)を重ねるのは同じ種類のリスクを増やすだけであり、既定には不適と判断した。(a)は失敗を早期に・分かりやすく止められ、(c)は「意図して親リポの内側で作業したい」という正当なケース(例: モノレポの一部をworkdirにする運用)を config.yaml 側の明示的な一行で救済できる。オプトインは既存の `WorktreeCfg` dataclass(`enabled` / `base_ref` / `root`)と同じ配置・同じ型検証経路(`_check_section` / `_TYPE_MAP`)に `allow_nested_workdir: bool = False` を追加する形で実装しており、既存のconfig読み込みの作法から逸脱していない。

## 却下した代替案の理由

**(b) 自動 `git init` を却下した理由**: workdirが親リポの内側にあるという状態は、多くの場合「Plannerがworkdir解決を誤った」か「意図せず商品リポの内側を作業対象に指定してしまった」ことの兆候であり、正しい対処は多くの場合「そもそも別の場所を使うべきだった」である。この状態を検出した瞬間に自動でgit管理下に置いてしまうと、(1) ユーザーが把握していない`.git`ディレクトリが商品リポの内側に生成される、(2) 本来workdirとして意図されていなかった場所での作業がそのまま進行してしまい、誤りに気づく機会そのものを奪う、という新たな副作用を生む。既定動作としては安全側に倒し、必要なら人間が `git init` するか、workdirを指定し直す(a)の方が事故の再発防止に資すると判断した。

**(c) 単独では不採用とした理由**: オプトインだけを既定として提供し検査自体を任意にすると、既存のミッション定義・Planner生成物が何もしなければ従来通り無検査で通ってしまい、今回のような事故を防げない。検査(a)を既定にした上で、(c)は「検査に引っかかったが実際には意図した構成である」ケースのための明示的な例外経路として組み合わせる位置づけとした。

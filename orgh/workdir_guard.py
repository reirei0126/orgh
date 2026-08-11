"""workdir独立リポ判定ガード。

背景: 2026-08-12の実運用事故。ミッションのworkdirに「公開リポの内側にある
gitignore対象サブディレクトリ」を指定したところ、worktree.py の worktree分離
(`ensure_task_worktree`)が親リポを対象に `git worktree add` してしまい、
非公開の成果物が親リポのブランチへコミットされた(pushしていれば公開事故)。

このモジュールは workdir が「独立したgitリポジトリのルート」かどうかを分類し、
そうでない(=親リポに入れ子)場合に安全側へ倒すための判定とエラー生成だけを
提供する。実行経路(orchestrator._attempt_loop / worktree.ensure_task_worktree)
への結線は別タスクで行う。

設計判断(却下した代替案は docs/workdir-guard.md 参照):
入れ子workdirは既定で拒否する。config.yaml の worktree.allow_nested_workdir
を明示的に true にしたときだけ、意図した入れ子作業として許可する。
"""
from __future__ import annotations

import os
import subprocess

INDEPENDENT_ROOT = "independent_root"
NESTED_IN_OTHER_REPO = "nested_in_other_repo"
NOT_A_REPO = "not_a_repo"


class WorkdirGuardError(ValueError):
    """workdirが独立リポのルートでなく、オプトインも無いために実行を拒否する。"""


def _git(workdir, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(workdir), *args],
                          capture_output=True, text=True)


def classify_workdir(workdir) -> tuple[str, str | None]:
    """workdirを (INDEPENDENT_ROOT / NESTED_IN_OTHER_REPO / NOT_A_REPO) に分類する。

    戻り値は (分類, 検出したリポジトリのルートの実パス)。NOT_A_REPOのときルートは
    None。比較はシンボリックリンク差異で誤判定しないよう os.path.realpath で行う。
    `git rev-parse --show-toplevel` は .gitignore の対象可否に関わらず親方向の
    リポジトリルートを返すため、gitignore対象サブディレクトリでもNESTEDとして
    正しく検出できる(親リポ側の `git check-ignore` の結果には依存しない)。
    """
    wd = os.path.realpath(str(workdir))
    r = _git(wd, "rev-parse", "--show-toplevel")
    if r.returncode != 0:
        return NOT_A_REPO, None
    toplevel = os.path.realpath(r.stdout.strip())
    if toplevel == wd:
        return INDEPENDENT_ROOT, toplevel
    return NESTED_IN_OTHER_REPO, toplevel


def rejection_message(workdir, parent_root: str) -> str:
    """入れ子workdirの拒否エラー本文。親リポのパス・危険性・直し方を必ず含む。"""
    return (
        f"orgh: workdir {workdir} は独立したgitリポジトリのルートではない。\n"
        f"検出した親リポジトリ: {parent_root}\n"
        f"このまま実行すると、worktree分離は親リポジトリ ({parent_root}) を"
        f"対象に `git worktree add` し、worker成果物が親リポジトリのルート"
        f"相対パスでコミットされる(workdirがgitignore対象のサブディレクトリ"
        f"であっても同じ扱いになる)。\n"
        f"直し方:\n"
        f"  1. {workdir} で `git init` して独立したgitリポジトリのルートにする\n"
        f"  2. または、独立したリポジトリのルートをworkdirとして指定し直す\n"
        f"  3. 親リポジトリの内側での作業を意図している場合のみ、config.yaml で"
        f" worktree.allow_nested_workdir: true を明示指定する(既定は無効)"
    )


def guard_workdir(cfg: dict, workdir) -> None:
    """入れ子workdirを検出したら WorkdirGuardError を送出する。

    INDEPENDENT_ROOT と NOT_A_REPO(非gitリポは worktree.py 側が既存動作で
    フォールバックするだけで、親リポを巻き込む危険は無い)は許可する。
    NESTED_IN_OTHER_REPO は、config.worktree.allow_nested_workdir が明示的に
    true でない限り拒否する。
    """
    kind, parent_root = classify_workdir(workdir)
    if kind != NESTED_IN_OTHER_REPO:
        return
    wt_cfg = (cfg or {}).get("worktree") or {}
    if wt_cfg.get("allow_nested_workdir"):
        return
    raise WorkdirGuardError(rejection_message(workdir, parent_root))

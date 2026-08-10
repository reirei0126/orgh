"""git worktreeによるタスク分離(HANDOFF タスク1)。

- worktree.enabled かつ task.workdir がgitリポの場合、タスクごとに分離
  worktree(<root>/<mission_id>-<task_id>)とブランチ(orgh/<mission_id>/<task_id>)
  を用意し、Task.workdir / Task.branch を差し替える
- 差し戻し再実行・resumeは既存のworktreeをそのまま再利用する(セッションと
  成果を捨てない)
- 非gitリポ・enabled:false は呼び出し側(orchestrator)で現行動作にフォール
  バックする。ここでは非gitリポの場合に警告を print するだけ
- ミッション終了時にworktreeは消さない。掃除は cleanup_mission_worktrees が担う
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

# 同一リポへの並列 `git worktree add` を直列化(git側の索引破損を避ける)
_LOCK = threading.Lock()


def _git(workdir, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(workdir), *args],
                          capture_output=True, text=True)


def is_git_repo(workdir) -> bool:
    r = _git(workdir, "rev-parse", "--is-inside-work-tree")
    return r.returncode == 0 and r.stdout.strip() == "true"


def ensure_task_worktree(wt_cfg: dict, mission_id: str, task) -> tuple[Path, str] | None:
    """taskを分離worktreeに割り当てる。フォールバック時は None。"""
    # 差し戻し再実行・resume: 既に割り当て済みならそのまま再利用
    if task.branch and Path(task.workdir).exists():
        return Path(task.workdir), task.branch

    workdir = task.workdir
    if not is_git_repo(workdir):
        print(f"orgh: {workdir} はgitリポではないためworktree分離をスキップする")
        return None

    root = Path(wt_cfg.get("root", ".orgh-worktrees"))
    if not root.is_absolute():
        root = Path(workdir) / root
    path = (root / f"{mission_id}-{task.id}").resolve()
    branch = f"orgh/{mission_id}/{task.id}"
    base_ref = wt_cfg.get("base_ref", "HEAD")

    with _LOCK:
        if path.exists():
            return path, branch
        branch_exists = _git(workdir, "rev-parse", "--verify", "--quiet",
                             f"refs/heads/{branch}").returncode == 0
        if branch_exists:
            r = _git(workdir, "worktree", "add", str(path), branch)
        else:
            r = _git(workdir, "worktree", "add", str(path), "-b", branch, base_ref)
        if r.returncode != 0:
            print(f"orgh: git worktree add に失敗、フォールバックする "
                 f"({r.stderr.strip()})")
            return None
        # 依存タスクの成果ブランチを取り込んでから開始する(成果物の受け渡し。
        # 実運用7307189e: 未コミット散在でt2がt1の仕様書を見られなかった事例への対処)。
        # 再利用worktree(上のearly return)ではマージしない: 作業途中の状態に
        # 後からマージを重ねると衝突リスクの方が大きい
        if not branch_exists:
            for line in merge_dep_branches(path, mission_id, task.deps):
                print(f"orgh: {task.id} {line}")

    return path, branch


def merge_dep_branches(workdir, mission_id: str, deps) -> list[str]:
    """依存タスクのブランチ(orgh/<mission>/<dep>)をworkdirへマージし実施ログを返す。
    ブランチが無い依存(worktree無効時代のタスク等)はスキップ。衝突はabortして
    スキップし、タスク実行自体は止めない(成果は劣化するが検収で気づける)。"""
    logs: list[str] = []
    for d in deps:
        br = f"orgh/{mission_id}/{d}"
        if _git(workdir, "rev-parse", "--verify", "--quiet",
                f"refs/heads/{br}").returncode != 0:
            continue
        r = _git(workdir, "-c", "user.name=orgh", "-c", "user.email=orgh@local",
                 "merge", "--no-edit", br)
        if r.returncode == 0:
            logs.append(f"dep取り込み: {br}")
        else:
            _git(workdir, "merge", "--abort")
            logs.append(f"dep取り込み衝突(スキップ): {br} ({r.stderr.strip()[:120]})")
    return logs


def commit_task_result(task, mission_id: str) -> str | None:
    """レビュー合格タスクの成果をタスクブランチへコミットし、短縮ハッシュを返す。
    変更が無ければNone。identityは環境非依存の明示指定(ホスト名変化で
    自動検出が壊れた実例があるため)。"""
    if not task.branch:
        return None
    wd = task.workdir
    _git(wd, "add", "-A")
    if _git(wd, "diff", "--cached", "--quiet").returncode == 0:
        return None  # 変更なし
    r = _git(wd, "-c", "user.name=orgh", "-c", "user.email=orgh@local",
             "commit", "-q", "-m", f"orgh({mission_id}/{task.id}): {task.title}")
    if r.returncode != 0:
        print(f"orgh: {task.id} 成果コミットに失敗 ({r.stderr.strip()[:200]})")
        return None
    return _git(wd, "rev-parse", "--short", "HEAD").stdout.strip()


def cleanup_mission_worktrees(mission) -> list[str]:
    """ミッションの全タスクについてworktreeとブランチを削除し、実施ログを返す。"""
    logs: list[str] = []
    for t in mission.tasks:
        if not t.branch:
            continue
        path = Path(t.workdir)
        if not path.exists():
            continue

        common_dir = _git(path, "rev-parse", "--path-format=absolute",
                          "--git-common-dir")
        if common_dir.returncode != 0:
            logs.append(f"{t.id}: 主リポの特定に失敗 ({common_dir.stderr.strip()})")
            continue
        main_repo = Path(common_dir.stdout.strip()).parent

        # 安全ガード(オーナー裁定 2026-08-10の運用条件): 未マージブランチは
        # worktreeごと保持する。--force+branch -Dは未退避の成果を回復困難に消すため
        merged = _git(main_repo, "merge-base", "--is-ancestor",
                      t.branch, "HEAD")
        if merged.returncode != 0:
            logs.append(
                f"{t.id}: branch {t.branch} は主リポHEADへ未マージのため"
                f"worktree・branchとも保持した(マージまたは退避後に再実行)")
            continue

        rm = _git(main_repo, "worktree", "remove", "--force", str(path))
        if rm.returncode == 0:
            logs.append(f"{t.id}: worktree {path} を削除した")
        else:
            logs.append(f"{t.id}: worktree削除に失敗 ({rm.stderr.strip()})")

        br = _git(main_repo, "branch", "-D", t.branch)
        if br.returncode == 0:
            logs.append(f"{t.id}: branch {t.branch} を削除した")
        else:
            logs.append(f"{t.id}: branch削除に失敗 ({br.stderr.strip()})")

    return logs

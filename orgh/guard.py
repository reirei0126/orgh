"""自己改変ガード(HANDOFF タスク7)。

タスクの workdir が orgh 自身を指す場合、自動実行せず awaiting_approval で
停止させる。orgh approve <mission_id> だけが続行の手段で、watcherからの
自動着火でも承認をスキップできない。意図的に config での無効化手段を設けない。

判定規則:
- orghパッケージディレクトリ: workdirがその内側 or パッケージを含む場合に発動
  (orghリポ/インストールディレクトリを対象にしたミッションを捕捉する。
  config・prompts・playbooksがorghリポに同居する自己ホスト構成はこれで守られる)
- prompts_dir / playbooks_dir: workdirがその内側を指す場合に発動
  (運用ディレクトリにprompts/やconfig.yamlを置く正規構成のタスクまで
  巻き込まないよう、「workdirが保護対象を含む」方向は適用しない)
"""
from __future__ import annotations

from pathlib import Path


def package_dir() -> Path:
    import orgh
    return Path(orgh.__file__).resolve().parent


def approval_reason(cfg: dict, workdir: str) -> str | None:
    """needs_approvalがTrueになる理由を人間可読の一文で返す(発火しなければNone)。
    判定ロジックはneeds_approvalと同一規則を保つこと(needs_approvalはこの
    関数のNone判定へのラッパとして実装し、二重管理を避ける)。"""
    wd = Path(workdir).expanduser().resolve()

    pkg = package_dir()
    if wd == pkg or wd.is_relative_to(pkg) or pkg.is_relative_to(wd):
        return f"orgh自身のパッケージ ({pkg}) を書き換える"

    for key, default, label in (("prompts_dir", "prompts", "prompts_dir"),
                                ("playbooks_dir", "playbooks", "playbooks_dir")):
        p = Path(cfg.get(key, default)).expanduser().resolve()
        if wd == p or wd.is_relative_to(p):
            return f"{label} ({p}) 配下を書き換える"
    return None


def needs_approval(cfg: dict, workdir: str) -> bool:
    return approval_reason(cfg, workdir) is not None

"""オーナー判断基準台帳(戦略設計書 柱2の最小版)。

playbooks(作業のやり方の教訓)と対をなす「判断の一般原則」の置き場。
形式はplaybooksと同系のMarkdown行+メタタグで、ユーザーが直接編集できる。
更新ガバナンスは「下書き+ワンタップ承認」: 自動生成は _drafts/ 止まりで、
本台帳への反映は必ず orgh criteria approve(=オーナー操作)を通る。
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

_ENTRY_RE = re.compile(r"^- ([A-Z]+)-(\d{3}) \[(norm|pref)\]:")
_META_RE = re.compile(r"<!-- src:(\S+) d:(\d{4}-\d{2}-\d{2}) -->")


def criteria_dir(cfg: dict) -> Path:
    return Path(cfg.get("criteria_dir", "criteria")).expanduser()


def _ledger_files(cdir: Path) -> list[Path]:
    """_始まり(_drafts/_rejected等)は台帳走査から除外する。"""
    if not cdir.is_dir():
        return []
    return sorted(p for p in cdir.glob("*.md") if not p.name.startswith("_"))


def criteria_context(cfg: dict, max_chars: int = 4000) -> str:
    """台帳をReviewer/ペルソナのプロンプトへ注入する(playbookと同じ日付降順詰め)。"""
    entries: list[tuple[str, str]] = []
    for p in _ledger_files(criteria_dir(cfg)):
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            m = _META_RE.search(line)
            entries.append((m.group(2) if m else "0000-00-00", line))
    entries.sort(key=lambda e: e[0], reverse=True)
    picked, total = [], 0
    for _, line in entries:
        total += len(line) + 1
        if total > max_chars and picked:
            break
        picked.append(line)
    return "\n".join(picked) if picked else "(no criteria yet)"


def next_id(cdir: Path, prefix: str) -> str:
    """全台帳ファイル横断でprefixの最大番号+1(3桁ゼロ埋め)。"""
    top = 0
    for p in _ledger_files(cdir):
        for line in p.read_text().splitlines():
            m = _ENTRY_RE.match(line)
            if m and m.group(1) == prefix:
                top = max(top, int(m.group(2)))
    return f"{prefix}-{top + 1:03d}"


def append_entry(cdir: Path, category: str, prefix: str, strength: str,
                 text: str, src: str) -> str:
    cdir.mkdir(parents=True, exist_ok=True)
    line = (f"- {next_id(cdir, prefix)} [{strength}]: {text} "
            f"<!-- src:{src} d:{date.today().isoformat()} -->")
    with open(cdir / f"{category}.md", "a") as f:
        f.write(line + "\n")
    return line

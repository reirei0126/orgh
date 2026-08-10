"""orgh playbooks --json 用のペイロード組み立て(機械可読)。

P1-3(desktop/API.md §1.7)。`orgh/planner.py` の `retro()` が
`<!-- m:<mission_id> d:<date> -->` を追記する対象(`line.startswith("-")` の行)
と対になる規則でエントリを抽出する。
"""
from __future__ import annotations

import re
from pathlib import Path

from .planner import _playbooks_dir

_TAG_RE = re.compile(r"<!--\s*m:(\S+)\s+d:(\S+)\s*-->\s*$")


def _parse_entries(body: str) -> list[dict]:
    entries: list[dict] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        m = _TAG_RE.search(stripped)
        if m:
            mission_id, date = m.group(1), m.group(2)
            text = _TAG_RE.sub("", stripped).rstrip()
        else:
            mission_id, date = None, None
            text = stripped
        if text.startswith("- "):
            text = text[2:]
        elif text.startswith("-"):
            text = text[1:]
        entries.append({"text": text, "mission_id": mission_id, "date": date})
    return entries


def playbooks_payload(cfg: dict) -> dict:
    """playbooks_dir 直下の *.md を列挙し、本文とエントリ抽出結果を返す純関数。

    playbooks_dir が存在しない、または *.md が1件も無い場合はエラーにせず
    {"playbooks": []} を返す(GUIの空状態表示のため)。
    """
    d = _playbooks_dir(cfg)
    if not d.is_dir():
        return {"playbooks": []}

    playbooks = []
    for p in sorted(d.glob("*.md")):
        body = p.read_text()
        playbooks.append({
            "name": p.stem,
            "path": str(p.resolve()),
            "body": body,
            "entries": _parse_entries(body),
        })
    return {"playbooks": playbooks}

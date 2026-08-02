"""Ingest: Obsidian vault / メモディレクトリを走査し、
1) ミッション候補ノート(inboxフォルダ or #mission タグ)
2) 文脈ダイジェスト(関連ノートの要約素材)
を抽出する。MCP不要・ファイル直読み。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")


@dataclass
class Note:
    path: Path
    title: str
    body: str
    tags: list[str]
    links: list[str]


def _parse(p: Path) -> Note:
    text = p.read_text(errors="ignore")
    tags = re.findall(r"(?<!\S)#([\w/-]+)", text)
    m = FRONTMATTER_RE.match(text)
    if m and (tm := re.search(r"tags:\s*\[?([^\]\n]+)", m.group(1))):
        tags += [t.strip(" '\"") for t in tm.group(1).split(",")]
    return Note(p, p.stem, text, tags, WIKILINK_RE.findall(text))


def scan_vault(vault: str | Path, inbox: str = "inbox",
               mission_tag: str = "mission") -> tuple[list[Note], dict[str, Note]]:
    """returns (mission candidate notes, title->Note index of whole vault)"""
    vault = Path(vault).expanduser()
    index: dict[str, Note] = {}
    candidates: list[Note] = []
    for p in vault.rglob("*.md"):
        if any(part.startswith(".") for part in p.parts):
            continue
        n = _parse(p)
        index[n.title] = n
        in_inbox = inbox in (part.lower() for part in p.parts)
        if in_inbox or mission_tag in n.tags:
            candidates.append(n)
    return candidates, index


def build_context_digest(note: Note, index: dict[str, Note],
                         depth: int = 1, max_chars: int = 24000) -> str:
    """ミッションノート + wikilinkで辿れる関連ノートを連結してPlannerに渡す素材を作る。"""
    seen, queue, chunks = {note.title}, list(note.links), []
    chunks.append(f"# MISSION NOTE: {note.title}\n{note.body}")
    for _ in range(depth):
        nxt = []
        for t in queue:
            if t in seen or t not in index:
                continue
            seen.add(t)
            ln = index[t]
            chunks.append(f"\n# LINKED: {ln.title}\n{ln.body[:4000]}")
            nxt += ln.links
        queue = nxt
    digest = "\n".join(chunks)
    return digest[:max_chars]

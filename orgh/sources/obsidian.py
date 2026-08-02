"""Obsidian vault 入力ソースアダプタ(HANDOFF タスク3)。

旧 ingest.py(vault走査・文脈ダイジェスト構築)と旧 watcher.py の vault固有部分
(WatchState・stabilize判定)をここに集約する。MCP不要・ファイル直読み。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from ..results import ResultsNote
from .base import MissionFeedback, SourceAdapter

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


def is_triggered(note: Note, trigger_tag: str = "go") -> bool:
    """明示着火判定(HANDOFF タスク4)。

    inbox配置や mission_tag だけでは着火しない。ノート本文のインラインタグ
    #<trigger_tag>、または frontmatterに `orgh: <trigger_tag>` がある場合のみ
    着火する。
    """
    if trigger_tag in note.tags:
        return True
    m = FRONTMATTER_RE.match(note.body)
    if m and re.search(rf"^orgh:\s*{re.escape(trigger_tag)}\s*$", m.group(1), re.M):
        return True
    return False


def append_callout(note_path: Path, line: str) -> None:
    """元ノート末尾にコールアウト1行を追記する(競合安全writeback)。"""
    with open(note_path, "a") as f:
        f.write(f"\n{line}\n")


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


def _hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


class WatchState:
    def __init__(self, runs_dir: str):
        self.fp = Path(runs_dir) / "_watch_state.json"
        self.data: dict[str, str] = (
            json.loads(self.fp.read_text()) if self.fp.exists() else {}
        )

    def is_processed(self, p: Path) -> bool:
        return self.data.get(str(p)) == _hash(p)

    def mark(self, p: Path) -> None:
        self.data[str(p)] = _hash(p)
        self.fp.parent.mkdir(parents=True, exist_ok=True)
        self.fp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1))


def _stabilized(p: Path, seconds: int) -> bool:
    return time.time() - p.stat().st_mtime >= seconds


class ObsidianAdapter(SourceAdapter):
    """Obsidian vault をファイル直読みする SourceAdapter 実装。"""

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        vcfg = cfg.get("vault") or {}
        self.vault = vcfg.get("path")
        self.inbox = vcfg.get("inbox", "inbox")
        self.mission_tag = vcfg.get("mission_tag", "mission")
        self.trigger_tag = vcfg.get("trigger_tag", "go")
        self.stabilize = cfg.get("watch", {}).get("stabilize_seconds", 20)
        self.writeback_enabled = cfg.get("watch", {}).get("writeback", True)
        self.ws = WatchState(cfg.get("runs_dir", "runs"))
        self._index: dict[str, Note] = {}  # 直近scanのtitle->Note(build_context/find用)
        self._candidates: list[Note] = []  # 直近scanの候補一覧(find用)

    # --- ミッション候補 -----------------------------------------------------
    def list_candidates(self) -> list[Note]:
        cands, index = scan_vault(self.vault, self.inbox, self.mission_tag)
        self._index = index
        self._candidates = cands
        return cands

    def should_trigger(self, note: Note) -> bool:
        return (is_triggered(note, self.trigger_tag)
                and _stabilized(note.path, self.stabilize))

    def find(self, query: str):
        if not self._index:
            self.list_candidates()
        note = self._index.get(query)
        if note:
            return note
        return next(
            (n for n in self._candidates if query.lower() in n.title.lower()),
            None)

    # --- 文脈と書き戻し -----------------------------------------------------
    def build_context(self, note: Note) -> str:
        if not self._index:
            self.list_candidates()
        return build_context_digest(note, self._index)

    def writeback(self, note: Note, mission) -> None:
        if self.writeback_enabled:
            append_callout(
                note.path, f"> 🚀 orgh: [[orgh/results/{mission.id}]]")
            self.mark_processed(note)  # 追記でhashが変わるため

    def notify_failure(self, note: Note, message: str) -> None:
        if self.writeback_enabled:
            append_callout(
                note.path,
                f"> [!failure] orgh: 計画の生成に失敗({message})。"
                f"ノートを編集して保存すると再着火します")
            self.mark_processed(note)  # 追記でhashが変わるため

    def feedback(self, mission_id: str) -> MissionFeedback:
        return ResultsNote(self.cfg, mission_id)

    # --- 着火済み管理 -------------------------------------------------------
    def mark_processed(self, note: Note) -> None:
        self.ws.mark(note.path)

    def is_processed(self, note: Note) -> bool:
        return self.ws.is_processed(note.path)

    def describe(self) -> str:
        return f"obsidian vault {self.vault}"

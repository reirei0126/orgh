"""オーナー判断基準台帳(戦略設計書 柱2の最小版)。

playbooks(作業のやり方の教訓)と対をなす「判断の一般原則」の置き場。
形式はplaybooksと同系のMarkdown行+メタタグで、ユーザーが直接編集できる。
更新ガバナンスは「下書き+ワンタップ承認」: 自動生成は _drafts/ 止まりで、
本台帳への反映は必ず orgh criteria approve(=オーナー操作)を通る。
"""
from __future__ import annotations

import json
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


def _next_draft_start(drafts_dir: Path, mission_id: str) -> int:
    """既存の <mission_id>-<n>.json を走査し、次に使う番号(最大+1)を返す。
    同一ミッションへ複数回 verdict した際に、番号を1から振り直して
    未承認の既存下書きを上書きしないための採番。"""
    top = 0
    if drafts_dir.is_dir():
        for p in drafts_dir.glob(f"{mission_id}-*.json"):
            m = re.match(rf"^{re.escape(mission_id)}-(\d+)\.json$", p.name)
            if m:
                top = max(top, int(m.group(1)))
    return top + 1


def list_drafts(cfg: dict) -> list[Path]:
    d = criteria_dir(cfg) / "_drafts"
    return sorted(d.glob("*.json")) if d.is_dir() else []


def _draft_path(cfg: dict, name: str) -> Path:
    fp = criteria_dir(cfg) / "_drafts" / f"{name}.json"
    if not fp.is_file():
        raise FileNotFoundError(
            f"draft not found: {fp}. orgh criteria list で確認せよ")
    return fp


def approve_draft(cfg: dict, name: str) -> str:
    """下書きを本台帳へ反映する(ワンタップ承認の実体)。"""
    fp = _draft_path(cfg, name)
    p = json.loads(fp.read_text())
    line = append_entry(criteria_dir(cfg), p["category"], p["prefix"],
                        p.get("strength", "pref"), p["text"], src=name)
    fp.unlink()
    return line


def reject_draft(cfg: dict, name: str) -> Path:
    """棄却は削除ではなく退避(棄却理由の見直し・復活を可能にする)。

    ファイル名衝突時(同ミッションへの再度の下書き生成)は数字サフィックスで
    既存を保護する(上書き防止)。"""
    fp = _draft_path(cfg, name)
    dst_dir = criteria_dir(cfg) / "_drafts" / "rejected"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / fp.name

    # 衝突回避: 既存ファイルがあれば .2, .3, ... のサフィックスを追加
    if dst.exists():
        base = dst.stem  # "m123-1" from "m123-1.json"
        suffix = 2
        while True:
            dst = dst_dir / f"{base}.{suffix}.json"
            if not dst.exists():
                break
            suffix += 1

    fp.rename(dst)
    return dst


def distill_verdict(cfg: dict, mission_id: str, intent: str,
                    passed: bool, reason: str) -> list[Path]:
    """オーナー裁定から台帳差分の下書きを生成する(本台帳には書かない)。"""
    from .planner import _ask_json, _read_prompt, role_with_default
    cfg = role_with_default(cfg, "criteria_distill", {
        "model": "sonnet", "max_turns": 5, "allowed_tools": "Read"})
    tmpl = _read_prompt(cfg, "criteria_distill.md")
    prompt = tmpl.format(intent=intent,
                         verdict="合格" if passed else "不合格",
                         reason=reason, criteria=criteria_context(cfg))
    data = _ask_json(cfg, "criteria_distill", prompt)
    drafts_dir = criteria_dir(cfg) / "_drafts"
    proposals = data.get("proposals") or []
    out: list[Path] = []
    if proposals:
        drafts_dir.mkdir(parents=True, exist_ok=True)
        start = _next_draft_start(drafts_dir, mission_id)
        for i, p in enumerate(proposals, start):
            fp = drafts_dir / f"{mission_id}-{i}.json"
            fp.write_text(json.dumps(p, ensure_ascii=False, indent=1))
            out.append(fp)
    return out

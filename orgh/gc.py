"""orgh gc: playbookの代謝(HANDOFF タスク6)。

追記onlyのplaybookは矛盾・重複・陳腐化した教訓が淘汰されず、8000字capにより
新しい教訓ほど切り捨てられていた(増幅が数ヶ月でノイズ増幅に反転する)。
`orgh gc` は以下を厳守の順序で行う:

1. バックアップ(必須・最初): playbooks/_backup/<date>/ へ全量コピー。
   失敗(_backup がファイルとして存在する等)したら OSError を送出して即中断し、
   playbooksには一切触れない
2. 古い教訓の退避: 180日より古い教訓行を playbooks/_archive/ へ退避(削除しない)
3. 統合Retro: 退避後の各playbookファイルについて重複統合・矛盾解消(新日付優先)
   を prompts/gc.md 経由で1回実行し、全置換
4. runs/ 保持ポリシー: retention_days(既定90)を超えた古いミッションディレクトリを
   runs/_archive/ へ移動(削除しない)
"""
from __future__ import annotations

import json
import re
import shutil
import time
from datetime import date, timedelta
from pathlib import Path

from . import planner

ARCHIVE_AFTER_DAYS = 180  # 6ヶ月無参照の教訓は退避

_META_RE = re.compile(r"<!-- m:(\S+) d:(\d{4}-\d{2}-\d{2}) -->")


def _playbooks_dir(cfg: dict) -> Path:
    return Path(cfg.get("playbooks_dir", "playbooks")).expanduser()


def _playbook_files(playbooks_dir: Path) -> list[Path]:
    """_backup/_archive 配下は非対象(直下の*.mdのみをglobするため自然に除外される)。"""
    return sorted(playbooks_dir.glob("*.md"))


def _backup(playbooks_dir: Path) -> Path:
    """全量バックアップ。失敗したらOSErrorがそのまま伝播し、以降の処理は走らない。"""
    backup_dir = playbooks_dir / "_backup" / date.today().isoformat()
    backup_dir.mkdir(parents=True, exist_ok=True)
    for fp in _playbook_files(playbooks_dir):
        shutil.copy2(fp, backup_dir / fp.name)
    return backup_dir


def _archive_old_lessons(playbooks_dir: Path) -> list[str]:
    """180日より古い教訓行をplaybooks/_archive/へ退避(削除ではなく追記+除去)。"""
    logs: list[str] = []
    archive_dir = playbooks_dir / "_archive"
    cutoff = date.today() - timedelta(days=ARCHIVE_AFTER_DAYS)
    for fp in _playbook_files(playbooks_dir):
        lines = fp.read_text().splitlines()
        keep, old = [], []
        for line in lines:
            m = _META_RE.search(line)
            if m and date.fromisoformat(m.group(2)) < cutoff:
                old.append(line)
            else:
                keep.append(line)
        if not old:
            continue
        archive_dir.mkdir(parents=True, exist_ok=True)
        with open(archive_dir / fp.name, "a") as f:
            f.write("\n".join(old) + "\n")
        fp.write_text("\n".join(keep) + ("\n" if keep else ""))
        logs.append(f"archived {len(old)} old lessons from {fp.name}")
    return logs


def _consolidate(cfg: dict, playbooks_dir: Path) -> list[str]:
    """退避後の各ファイルを統合Retro(prompts/gc.md)で全置換する。"""
    logs: list[str] = []
    tmpl = planner._read_prompt(cfg, "gc.md")
    for fp in _playbook_files(playbooks_dir):
        body = fp.read_text()
        if not body.strip():
            continue
        prompt = tmpl.format(name=fp.stem, body=body)
        data = planner._ask_json(cfg, "retro", prompt)
        lessons = data.get("lessons", "")
        if lessons:
            fp.write_text(lessons.rstrip("\n") + "\n")
            logs.append(f"consolidated {fp.name}")
    return logs


def _gc_runs(cfg: dict) -> list[str]:
    """runs/ 保持ポリシー: retention_days超のミッションをruns/_archive/へ退避。"""
    logs: list[str] = []
    runs_dir = Path(cfg.get("runs_dir", "runs"))
    if not runs_dir.is_dir():
        return logs
    retention_days = cfg.get("gc", {}).get("retention_days", 90)
    cutoff = time.time() - retention_days * 86400
    archive_dir = runs_dir / "_archive"
    for d in sorted(runs_dir.iterdir()):
        if not d.is_dir() or d.name == "_archive":
            continue
        try:
            data = json.loads((d / "mission.json").read_text())
            created_at = data["created_at"]
        except (OSError, KeyError, json.JSONDecodeError):
            continue  # 読めなければスキップ
        # 未決着(承認待ち・人間依頼待ち・未着手/実行中残り)ミッションは古くても
        # 保持する。移動するとapprove/humandone/resumeがFileNotFoundErrorで拾えず
        # 作業が孤立する。終端(done/failed/cancelled)と空(タスク0件で孤立作業
        # なし)のみアーカイブ対象(created_at基準だけの誤判定を防ぐ)
        from .listing import _derive_status
        status = _derive_status(data.get("tasks", []))
        if status not in ("done", "failed", "cancelled", "empty"):
            continue
        if created_at < cutoff:
            archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d), str(archive_dir / d.name))
            logs.append(f"archived mission {d.name} -> runs/_archive/")
    return logs


def run_gc(cfg: dict) -> list[str]:
    """gc全体を実行し、実施ログ行を返す(printはcli側の責務)。"""
    logs: list[str] = []
    playbooks_dir = _playbooks_dir(cfg)
    if playbooks_dir.is_dir():
        backup_dir = _backup(playbooks_dir)
        logs.append(f"backup: {backup_dir}")
        logs.extend(_archive_old_lessons(playbooks_dir))
        logs.extend(_consolidate(cfg, playbooks_dir))
    logs.extend(_gc_runs(cfg))
    return logs

"""orgh watch: vaultを監視し、新規/更新ノートを検知して自動でミッションを回すデーモン。

- ポーリングだが間隔は数秒(バッチではなくイベント駆動に近い体験)
- 書き込み途中のノートを拾わないよう「内容がstabilize_seconds変化しなかったら着火」
- 処理済みはcontent hashで管理(runs/_watch_state.json)。ノートを編集し直せば再着火する
- 完了後、ノート末尾に結果コールアウトを追記(Obsidian上で結果が見える)
"""
from __future__ import annotations

import hashlib
import json
import time
import traceback
from pathlib import Path

from . import ingest, planner
from .orchestrator import run_mission
from .state import RunStore


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


def _writeback(note_path: Path, mission) -> None:
    done = sum(t.status == "done" for t in mission.tasks)
    lines = [f"\n> [!{'success' if done == len(mission.tasks) else 'warning'}] "
             f"orgh mission `{mission.id}` — {done}/{len(mission.tasks)} done"]
    for t in mission.tasks:
        mark = {"done": "✅", "failed": "❌"}.get(t.status, "⏳")
        lines.append(f"> {mark} {t.title}")
    with open(note_path, "a") as f:
        f.write("\n".join(lines) + "\n")


def _stabilized(p: Path, seconds: int) -> bool:
    return time.time() - p.stat().st_mtime >= seconds


def watch(cfg: dict) -> None:
    wcfg = cfg.get("watch", {})
    interval = wcfg.get("interval", 5)
    stabilize = wcfg.get("stabilize_seconds", 20)
    writeback = wcfg.get("writeback", True)
    runs_dir = cfg.get("runs_dir", "runs")
    ws = WatchState(runs_dir)

    print(f"watching {cfg['vault']['path']} (interval={interval}s, "
          f"stabilize={stabilize}s). Ctrl-C to stop.")
    while True:
        try:
            cands, index = ingest.scan_vault(
                cfg["vault"]["path"],
                cfg["vault"].get("inbox", "inbox"),
                cfg["vault"].get("mission_tag", "mission"),
            )
            for note in cands:
                if ws.is_processed(note.path) or not _stabilized(note.path, stabilize):
                    continue
                print(f"\n== new mission note: {note.title} ==")
                ws.mark(note.path)  # 先にmark: 失敗ループでの連続着火を防ぐ
                try:
                    digest = ingest.build_context_digest(note, index)
                    intent = f"ノート「{note.title}」の内容を実行可能な成果に落とし込む"
                    mission = planner.plan(cfg, intent, digest)
                    store = RunStore(runs_dir, mission.id)
                    store.log("watch.triggered", note=str(note.path))
                    mission = run_mission(cfg, mission, store)
                    planner.retro(cfg, mission)
                    if writeback:
                        _writeback(note.path, mission)
                        ws.mark(note.path)  # writeback分でhashが変わるので再mark
                    print(f"mission {mission.id} finished")
                except Exception:
                    print(f"mission failed for {note.title}:\n{traceback.format_exc()}")
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nstopped.")
            return

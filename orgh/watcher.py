"""orgh watch: vaultを監視し、新規/更新ノートを検知して自動でミッションを回すデーモン。

- ポーリングだが間隔は数秒(バッチではなくイベント駆動に近い体験)
- 書き込み途中のノートを拾わないよう「内容がstabilize_seconds変化しなかったら着火」
- 処理済みはcontent hashで管理(runs/_watch_state.json)。ノートを編集し直せば再着火する
- 明示着火(HANDOFF タスク4): config `vault.trigger_tag`(既定"go")。inbox配置や
  mission_tagだけでは着火しない。ノート本文のインラインタグ #go、または
  frontmatterの `orgh: go` がある場合のみ着火する(mission_tagは候補としての
  認識にとどまる)
- 競合安全writeback: 元ノートへの書き込みは着火直後の1回・結果ノートへのリンク
  1行のみ。以後の進行・結果・失敗理由は orgh/results/<mission_id>.md
  (ResultsNote)に集約する
- 着火前失敗(mission_id採番前のPlanner失敗等)は元ノートに [!failure] コール
  アウトを追記して通知し、ノートを再編集すれば再着火できるようにする
"""
from __future__ import annotations

import hashlib
import json
import time
import traceback
from pathlib import Path

from . import ingest, planner
from .orchestrator import run_mission
from .results import ResultsNote
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


def _stabilized(p: Path, seconds: int) -> bool:
    return time.time() - p.stat().st_mtime >= seconds


def watch(cfg: dict) -> None:
    wcfg = cfg.get("watch", {})
    interval = wcfg.get("interval", 5)
    stabilize = wcfg.get("stabilize_seconds", 20)
    writeback = wcfg.get("writeback", True)
    runs_dir = cfg.get("runs_dir", "runs")
    trigger_tag = cfg["vault"].get("trigger_tag", "go")
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
                if not ingest.is_triggered(note, trigger_tag):
                    continue
                if ws.is_processed(note.path) or not _stabilized(note.path, stabilize):
                    continue
                print(f"\n== new mission note: {note.title} ==")
                ws.mark(note.path)  # 先にmark: 失敗ループでの連続着火を防ぐ
                try:
                    digest = ingest.build_context_digest(note, index)
                    intent = f"ノート「{note.title}」の内容を実行可能な成果に落とし込む"
                    mission = planner.plan(cfg, intent, digest)
                except Exception as e:
                    print(f"plan failed for {note.title}:\n{traceback.format_exc()}")
                    if writeback:
                        ingest.append_callout(
                            note.path,
                            f"> [!failure] orgh: 計画の生成に失敗({str(e)[:120]})。"
                            f"ノートを編集して保存すると再着火します")
                        ws.mark(note.path)  # 追記でhashが変わるため再mark
                    continue

                store = RunStore(runs_dir, mission.id)
                store.log("watch.triggered", note=str(note.path))
                results = ResultsNote(cfg, mission.id)
                results.update(mission)  # 着火直後に進行ノートを生成
                if writeback:
                    ingest.append_callout(
                        note.path, f"> 🚀 orgh: [[orgh/results/{mission.id}]]")
                    ws.mark(note.path)  # writeback分でhashが変わるので再mark
                try:
                    # poll_cancel: 結果ノートの#cancelタグ(スマホから停止)を検知
                    mission = run_mission(cfg, mission, store,
                                          on_update=results.update,
                                          poll_cancel=results.cancel_requested)
                    planner.retro(cfg, mission)
                    store.save(mission)
                except Exception:
                    print(f"mission failed for {note.title}:\n{traceback.format_exc()}")
                results.finalize(mission, store)
                print(f"mission {mission.id} finished")
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nstopped.")
            return

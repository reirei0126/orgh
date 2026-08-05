"""orgh watch: 入力ソースを監視し、新規/更新ノートを検知して自動でミッションを
回すデーモン。

- 入力ソースへのアクセスは SourceAdapter(orgh/sources/base.py)経由のみ。
  ソース固有の走査・着火判定・書き戻しロジックはアダプタ実装側に閉じる
  (将来 Notion 等を追加する場合は SourceAdapter実装を REGISTRY に足すだけでよい)
- ポーリングだが間隔は数秒(バッチではなくイベント駆動に近い体験)
- 着火可否(安定化・明示着火タグ等)・処理済み管理・書き戻しは
  すべてアダプタの should_trigger / is_processed / mark_processed /
  writeback / notify_failure に委譲する
- ミッション進行・結果・キャンセル検知はアダプタが返す MissionFeedback
  (feedback())に委譲する
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

from . import gc, planner
from .orchestrator import run_mission
from .sources.base import get_source
from .state import RunStore


def _maybe_gc(cfg: dict, runs_dir: str, gc_interval_days) -> None:
    """playbookの代謝を定期的に自動実行する(HANDOFF タスク6)。

    stateファイルが無ければ現在時刻をベースラインとして書き込むだけで、
    gcは走らせない(初回パスでいきなり実playbooksを書き換えないため)。
    """
    if not gc_interval_days:
        return
    state_fp = Path(runs_dir) / "_gc_state.json"
    now = time.time()
    if not state_fp.exists():
        state_fp.parent.mkdir(parents=True, exist_ok=True)
        state_fp.write_text(json.dumps({"last_gc": now}))
        return
    last_gc = json.loads(state_fp.read_text()).get("last_gc", now)
    if now - last_gc < gc_interval_days * 86400:
        return
    try:
        for line in gc.run_gc(cfg):
            print(line)
    except Exception as e:
        print(f"gc failed: {e!r}")
    state_fp.write_text(json.dumps({"last_gc": now}))


def watch(cfg: dict) -> None:
    wcfg = cfg.get("watch", {})
    interval = wcfg.get("interval", 5)
    runs_dir = cfg.get("runs_dir", "runs")
    src = get_source(cfg)

    print(f"watching {src.describe()} (interval={interval}s). Ctrl-C to stop.")
    while True:
        try:
            for note in src.list_candidates():
                if src.is_processed(note) or not src.should_trigger(note):
                    continue
                print(f"\n== new mission note: {note.title} ==")
                src.mark_processed(note)  # 先にmark: 失敗ループでの連続着火防止
                try:
                    digest = src.build_context(note)
                    intent = f"ノート「{note.title}」の内容を実行可能な成果に落とし込む"
                    mission = planner.plan(cfg, intent, digest)
                except Exception as e:
                    print(f"plan failed for {note.title}:\n{traceback.format_exc()}")
                    src.notify_failure(note, str(e)[:120])
                    continue

                store = RunStore(runs_dir, mission.id)
                store.log("watch.triggered", note=str(note.path))
                fb = src.feedback(mission.id)
                fb.update(mission)  # 着火直後に進行状態を生成
                src.writeback(note, mission)
                try:
                    # poll_cancel: フィードバック側のキャンセル指示(#cancelタグ等)を検知
                    mission = run_mission(cfg, mission, store,
                                          on_update=fb.update,
                                          poll_cancel=fb.cancel_requested)
                    planner.retro(cfg, mission)
                    store.save(mission)
                    (store.dir / "RETRO_DONE").touch()
                except Exception:
                    print(f"mission failed for {note.title}:\n{traceback.format_exc()}")
                fb.finalize(mission, store)
                print(f"mission {mission.id} finished")
            _maybe_gc(cfg, runs_dir, wcfg.get("gc_interval_days", 14))
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nstopped.")
            return

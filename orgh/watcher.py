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

import time
import traceback
import os
from pathlib import Path

from . import planner
from .queue import enqueue, pending
from .sources.base import get_source
from .state import RunStore


def watch(cfg: dict) -> None:
    wcfg = cfg.get("watch", {})
    interval = wcfg.get("interval", 5)
    runs_dir = cfg.get("runs_dir", "runs")

    # 単一インスタンス強制(2026-08-22): watchの二重起動は同一ノートの重複計画を
    # 生む(実害: 9b18f62f=0bf56737の重複、計画費1.97USD)。ノート側のmark_processedは
    # プロセス間の排他ではないため、runs/直下のflockで多重起動そのものを拒否する。
    # ロックはプロセス生存中保持され、死ねばOSが自動解放する(stale lockなし)。
    import fcntl as _fcntl
    Path(runs_dir).mkdir(parents=True, exist_ok=True)
    _instance_lock = open(Path(runs_dir) / ".watch.lock", "a+")
    try:
        _fcntl.flock(_instance_lock, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(
            "orgh watch は既に起動している(runs/.watch.lock が取得できない)。"
            "多重起動は同一ノートの重複計画を生むため拒否する。")
    _instance_lock.write(f"{os.getpid()}\n")
    _instance_lock.flush()

    src = get_source(cfg)

    print(f"watching {src.describe()} (interval={interval}s). Ctrl-C to stop.")
    while True:
        try:
            for note in src.list_candidates():
                if src.is_processed(note) or not src.should_trigger(note):
                    continue
                if len(pending(runs_dir)) >= wcfg.get("queue_limit", 20):
                    # キュー満杯: mark_processed前に見送る(次パスで再試行)。
                    # Planner呼び出しのコストを無駄にしないため先に投入余地を確認。
                    # 同一パスの残候補も満杯のため打ち切る
                    print(f"[warn] mission queue full — 着火を見送る(次パスで再試行)")
                    break
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
                # executor(別プロセス/別スレッド)が読めるように永続化してから投入
                # (従来はrun_mission内の初回saveに依存していた)
                store.save(mission)
                fb = src.feedback(mission.id)
                fb.update(mission)  # 着火直後に進行状態を生成
                src.writeback(note, mission)
                # 実行はexecutor(orgh/executor.py)がキュー消化で行う(R-1分離)。
                # 有界性は計画前の事前チェックで担保済み。計画コストを支払った後は
                # limit=Noneで必ず投入する(ここでFalse見送りにすると、計画中に別
                # プロデューサがキューを埋めた場合にmark_processed済みノートが
                # 実行されないまま消費される=サイレントなミッション損失)
                enqueue(runs_dir, mission.id, note_path=str(note.path),
                        limit=None)
                store.log("watch.enqueued")
                print(f"mission {mission.id} queued")
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nstopped.")
            return
        except Exception:
            # デーモンは死なせない: gc状態ファイル破損・入力ソースのI/O一時失敗
            # などの未捕捉例外でwatchが停止すると、以降ノート等を投稿しても自動
            # 着火しなくなる(サイレント運用停止)。ログを残し次ループへ継続する
            print(f"watch loop error(継続する):\n{traceback.format_exc()}")
            time.sleep(interval)

"""orgh executor: runs/_queue/ を消化するミッション実行デーモン(R-1)。

watch(検知・計画・キュー投入)から実行を分離する:
- watch は長時間ミッションにブロックされず、新規ノートを数秒以内に検知できる
- executor を再起動してもキュー内容(runs/_queue/ のファイル)は失われない
- executor のクラッシュはOSのflock解放でclaimが自動解除され、エントリは
  次の claim で再実行される(store.load() の実行中系→pending巻き戻しで再開)
- 同一ミッションの二重実行は従来どおり mission lock(flock)が防ぐ

起動形態: `orgh executor`(独立デーモン)。`orgh watch` は既定で本モジュールを
同プロセスの別スレッドに併走させる(単一デーモン運用の互換。この形態では
watch停止で実行中ミッションも止まる — 完全な独立ライフサイクルが必要なら
`orgh watch --watch-only` + 別プロセスの `orgh executor` で運用する)。
"""
from __future__ import annotations

import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import planner
from .orchestrator import run_mission
from .queue import claim_next
from .sources.base import get_source
from .state import RunStore


def process_entry(cfg: dict, entry: dict) -> None:
    """キューエントリ1件のミッション実行一式(旧watchループから移設・挙動同一)。

    feedback(結果ノート更新・#cancel検知)は mission_id から再構築する。
    mission lock 衝突(run_missionのSystemExit)は呼び出し元へ透過する
    (別プロセスが実行中=そちらが完遂・finalizeする)。"""
    mission_id = entry["mission_id"]
    runs_dir = cfg.get("runs_dir", "runs")
    store = RunStore(runs_dir, mission_id)
    mission = store.load()
    fb = get_source(cfg).feedback(mission_id)
    try:
        mission = run_mission(cfg, mission, store,
                              on_update=fb.update,
                              poll_cancel=fb.cancel_requested)
        # 承認待ちで停止したミッションを未完了のままretroしない
        # (決着時のみ・RETRO_DONEで二重防止。cliと共通ゲート)
        planner.retro_if_finished(cfg, mission, store)
    except SystemExit:
        raise
    except Exception:
        print(f"mission failed for {mission_id}:\n{traceback.format_exc()}")
    fb.finalize(mission, store)
    print(f"mission {mission_id} finished")


def _consume(cfg: dict, entry: dict, release) -> None:
    """1エントリの消化とclaim解放。エントリは常に消化済み(削除)にする:
    旧watchも失敗ミッションを再試行しなかった(resumeはオーナー操作)。
    プロセス死による中断だけが、flock解放によりエントリを自然に残す。"""
    try:
        process_entry(cfg, entry)
    except SystemExit as e:
        print(f"executor: {entry['mission_id']} は他プロセスが実行中のためスキップ: {e}")
    except Exception:
        print(f"executor error for {entry['mission_id']}:\n{traceback.format_exc()}")
    finally:
        release(done=True)


def drain(cfg: dict) -> int:
    """キューを同期的に空になるまで消化する(ST・手動運用用)。消化件数を返す。"""
    n = 0
    runs_dir = cfg.get("runs_dir", "runs")
    while (got := claim_next(runs_dir)) is not None:
        entry, release = got
        _consume(cfg, entry, release)
        n += 1
    return n


def serve(cfg: dict) -> None:
    """デーモンループ: watch.parallel_missions 並列でキューを消化し続ける。"""
    wcfg = cfg.get("watch", {})
    interval = wcfg.get("interval", 5)
    workers = wcfg.get("parallel_missions", 2)
    runs_dir = cfg.get("runs_dir", "runs")
    print(f"executor: runs/_queue を消化する (parallel_missions={workers}, "
          f"interval={interval}s). Ctrl-C to stop.")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        inflight: dict = {}
        while True:
            try:
                for key, fut in list(inflight.items()):
                    if fut.done():
                        inflight.pop(key)
                while len(inflight) < workers:
                    got = claim_next(runs_dir)
                    if got is None:
                        break
                    entry, release = got
                    inflight[entry["mission_id"]] = pool.submit(
                        _consume, cfg, entry, release)
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\nexecutor stopping — 実行中ミッションの完了を待つ")
                return   # withブロックのexitがinflightの完了を待つ
            except Exception:
                # デーモンは死なせない(watchと同じ方針)
                print(f"executor loop error(継続する):\n{traceback.format_exc()}")
                time.sleep(interval)

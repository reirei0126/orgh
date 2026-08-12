"""orgh executor: runs/_queue/ を消化するミッション実行デーモン(R-1)。

watch(検知・計画・キュー投入)から実行を分離する:
- watch は長時間ミッションにブロックされず、新規ノートを数秒以内に検知できる
- executor を再起動してもキュー内容(runs/_queue/ のファイル)は失われない
- executor のクラッシュはOSのflock解放でclaimが自動解除され、エントリは
  次の claim で再実行される(store.load() の実行中系→pending巻き戻しで再開)
- 同一ミッションの二重実行は従来どおり mission lock(flock)が防ぐ

起動形態: `orgh executor`(独立デーモン)。`orgh watch` は既定で本モジュールを
同プロセスの別スレッドに併走させる(単一デーモン運用の互換。この形態では
watch停止で実行中ミッションも中断される — 中断分はキューに残り再起動で再開。
完全な独立ライフサイクルが必要なら `orgh watch --watch-only` + 別プロセスの
`orgh executor` で運用する)。
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from pathlib import Path

from . import gc, planner
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


def _maybe_gc(cfg: dict, runs_dir: str, gc_interval_days) -> None:
    """playbookの代謝を定期的に自動実行する(HANDOFF タスク6)。

    stateファイルが無ければ現在時刻をベースラインとして書き込むだけで、
    gcは走らせない(初回パスでいきなり実playbooksを書き換えないため)。
    呼び出し側はミッション非実行時(アイドル)に限定すること: gcのplaybooks
    書き換えと実行中ミッションのretro追記が競合するとlost updateになる
    (旧watchは単一スレッドの直列実行でこの排他を暗黙に担保していた)。"""
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


def serve(cfg: dict) -> None:
    """デーモンループ: watch.parallel_missions 並列でキューを消化し続ける。

    ミッションはdaemonスレッドで実行する(ThreadPoolExecutorは使わない:
    インタプリタ終了フックがworkerスレッドをjoinするため、Ctrl-C後も
    実行中ミッションが完了するまでプロセスが終了しない)。Ctrl-C/プロセス
    終了で実行中ミッションは中断されるが、claimはflock解放で自動的に戻り、
    再起動時にキューから再開する(store.load()の実行中系巻き戻し)。"""
    wcfg = cfg.get("watch", {})
    interval = wcfg.get("interval", 5)
    workers = wcfg.get("parallel_missions", 1)
    runs_dir = cfg.get("runs_dir", "runs")
    print(f"executor: runs/_queue を消化する (parallel_missions={workers}, "
          f"interval={interval}s). Ctrl-C to stop.")
    inflight: dict[str, threading.Thread] = {}
    while True:
        try:
            for key, th in list(inflight.items()):
                if not th.is_alive():
                    inflight.pop(key)
            while len(inflight) < workers:
                got = claim_next(runs_dir)
                if got is None:
                    break
                entry, release = got
                th = threading.Thread(
                    target=_consume, args=(cfg, entry, release),
                    daemon=True, name=f"orgh-mission-{entry['mission_id']}")
                inflight[entry["mission_id"]] = th
                th.start()
            if not inflight:
                # gcはミッション非実行時のみ(playbooks書き換えとretro追記の排他)
                _maybe_gc(cfg, runs_dir, wcfg.get("gc_interval_days", 14))
            time.sleep(interval)
        except KeyboardInterrupt:
            if inflight:
                print(f"\nexecutor stopped — 実行中 {len(inflight)} 件は中断"
                      f"(claimはflock解放で戻り、再起動でキューから再開する)")
            else:
                print("\nexecutor stopped.")
            return
        except Exception:
            # デーモンは死なせない(watchと同じ方針)
            print(f"executor loop error(継続する):\n{traceback.format_exc()}")
            time.sleep(interval)

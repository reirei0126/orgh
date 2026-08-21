"""watch単一インスタンス強制(runs/.watch.lock)の検証。

実害(2026-08-22): watch二重起動により同一ノートが重複計画された(9b18f62f)。
mark_processedはプロセス間排他ではないため、flockで多重起動自体を拒否する。
QA-016: 実プロセス2本での競合を再現する(モックで済まさない)。
"""
import fcntl
import subprocess
import sys
import textwrap
from pathlib import Path


def _hold_lock_script(runs_dir: Path) -> str:
    return textwrap.dedent(f"""
        import fcntl, time, sys
        f = open(r"{runs_dir}/.watch.lock", "a+")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print("held", flush=True)
        time.sleep(30)
    """)


def test_second_watch_is_rejected(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    # プロセス1がロック保持
    p1 = subprocess.Popen([sys.executable, "-c", _hold_lock_script(runs)],
                          stdout=subprocess.PIPE, text=True)
    try:
        assert p1.stdout.readline().strip() == "held"
        # プロセス2(watch相当のロック取得)は即拒否される
        f = open(runs / ".watch.lock", "a+")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            acquired = False
        assert acquired is False
    finally:
        p1.kill()
        p1.wait()


def test_lock_released_when_process_dies(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    p1 = subprocess.Popen([sys.executable, "-c", _hold_lock_script(runs)],
                          stdout=subprocess.PIPE, text=True)
    assert p1.stdout.readline().strip() == "held"
    p1.kill()
    p1.wait()
    # プロセス死でOSがロックを解放し、次のwatchが起動できる
    f = open(runs / ".watch.lock", "a+")
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises if not released


def test_watch_exits_with_message(tmp_path, monkeypatch):
    """watch()自体が二重起動時にSystemExitすることを確認。"""
    import pytest
    from orgh import watcher
    runs = tmp_path / "runs"
    runs.mkdir()
    # 先にロックを握る
    holder = open(runs / ".watch.lock", "a+")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    cfg = {"runs_dir": str(runs), "watch": {"interval": 0.01},
           "workers": {}, "vault": {"path": str(tmp_path), "inbox": "inbox"}}
    with pytest.raises(SystemExit):
        watcher.watch(cfg)

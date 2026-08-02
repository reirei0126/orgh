"""⑤ watcher ST: 着火・stabilize・再着火防止・writeback(HANDOFF タスク0a)。

watcher.watch() は無限ループなので time.sleep をKeyboardInterruptに差し替え、
「1回のwatch()呼び出し = 1スキャンパス」として検証する。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from orgh import watcher


@pytest.fixture
def vault(tmp_path) -> Path:
    v = tmp_path / "vault"
    (v / "inbox").mkdir(parents=True)
    return v


# watch.interval に入れるセンチネル。time.sleep がこの値で呼ばれたときだけ
# ループを打ち切る(subprocess等が内部で呼ぶ time.sleep を誤爆させない)
_INTERVAL_SENTINEL = 7.654321


@pytest.fixture
def wcfg(cfg, vault) -> dict:
    cfg["vault"] = {"path": str(vault), "inbox": "inbox",
                    "mission_tag": "mission"}
    cfg["watch"] = {"interval": _INTERVAL_SENTINEL,
                    "stabilize_seconds": 20, "writeback": True}
    return cfg


@pytest.fixture
def one_pass(monkeypatch):
    """watch()のループ末尾のsleep(interval)で抜けさせ、1パスだけ実行させる。"""
    real_sleep = time.sleep

    def _sleep(seconds):
        if seconds == _INTERVAL_SENTINEL:
            raise KeyboardInterrupt
        real_sleep(seconds)
    monkeypatch.setattr(watcher.time, "sleep", _sleep)


def _mission_dirs(runs_dir: str) -> list[Path]:
    root = Path(runs_dir)
    if not root.exists():
        return []
    return [p for p in root.iterdir() if p.is_dir()]


def _age(p: Path, seconds: int = 60) -> None:
    past = time.time() - seconds
    os.utime(p, (past, past))


class TestWatcher:
    def test_fresh_note_not_triggered_before_stabilize(self, wcfg, vault,
                                                       one_pass,
                                                       mock_state_dir):
        note = vault / "inbox" / "テストミッション.md"
        note.write_text("やること\n")  # mtime=今 → stabilize未達
        watcher.watch(wcfg)
        assert _mission_dirs(wcfg["runs_dir"]) == []

    def test_stabilized_note_triggers_and_writes_back(self, wcfg, vault,
                                                      one_pass,
                                                      mock_state_dir):
        note = vault / "inbox" / "テストミッション.md"
        note.write_text("やること\n")
        _age(note)
        watcher.watch(wcfg)

        dirs = _mission_dirs(wcfg["runs_dir"])
        assert len(dirs) == 1
        ledger = (dirs[0] / "ledger.jsonl").read_text()
        assert "watch.triggered" in ledger
        # writeback: ノート末尾に結果コールアウト
        body = note.read_text()
        assert "orgh mission" in body
        assert "✅" in body

    def test_no_retrigger_on_processed_note(self, wcfg, vault, one_pass,
                                            mock_state_dir):
        note = vault / "inbox" / "テストミッション.md"
        note.write_text("やること\n")
        _age(note)
        watcher.watch(wcfg)
        assert len(_mission_dirs(wcfg["runs_dir"])) == 1

        _age(note)  # stabilize条件を再び満たしても
        watcher.watch(wcfg)
        assert len(_mission_dirs(wcfg["runs_dir"])) == 1  # 再着火しない

    def test_edited_note_retriggers(self, wcfg, vault, one_pass,
                                    mock_state_dir):
        note = vault / "inbox" / "テストミッション.md"
        note.write_text("やること\n")
        _age(note)
        watcher.watch(wcfg)
        assert len(_mission_dirs(wcfg["runs_dir"])) == 1

        with open(note, "a") as f:
            f.write("\n追記した\n")  # content hashが変わる
        _age(note)
        watcher.watch(wcfg)
        assert len(_mission_dirs(wcfg["runs_dir"])) == 2

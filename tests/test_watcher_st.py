"""⑤ watcher ST: 着火・stabilize・再着火防止・writeback。

HANDOFF タスク4で契約更新: 着火は明示(#go タグ)、元ノートへのwritebackは
着火時のリンク1行のみ(進行・結果は結果ノート側。tests/test_vault_feedback.py)。

watcher.watch() は無限ループなので time.sleep をKeyboardInterruptに差し替え、
「1回のwatch()呼び出し = 1スキャンパス」として検証する。
"""
from __future__ import annotations

from orgh import watcher

from .conftest import age, mission_dirs


class TestWatcher:
    def test_fresh_note_not_triggered_before_stabilize(self, wcfg, vault,
                                                       one_pass,
                                                       mock_state_dir):
        note = vault / "inbox" / "テストミッション.md"
        note.write_text("やること #go\n")  # mtime=今 → stabilize未達
        watcher.watch(wcfg)
        assert mission_dirs(wcfg["runs_dir"]) == []

    def test_stabilized_note_triggers_and_writes_link(self, wcfg, vault,
                                                      one_pass,
                                                      mock_state_dir):
        note = vault / "inbox" / "テストミッション.md"
        note.write_text("やること #go\n")
        age(note)
        watcher.watch(wcfg)

        dirs = mission_dirs(wcfg["runs_dir"])
        assert len(dirs) == 1
        ledger = (dirs[0] / "ledger.jsonl").read_text()
        assert "watch.triggered" in ledger
        # writeback: 元ノートには結果ノートへのリンク1行のみ(競合安全)
        body = note.read_text()
        assert f"[[orgh/results/{dirs[0].name}]]" in body
        assert "✅" not in body

    def test_no_retrigger_on_processed_note(self, wcfg, vault, one_pass,
                                            mock_state_dir):
        note = vault / "inbox" / "テストミッション.md"
        note.write_text("やること #go\n")
        age(note)
        watcher.watch(wcfg)
        assert len(mission_dirs(wcfg["runs_dir"])) == 1

        age(note)  # stabilize条件を再び満たしても
        watcher.watch(wcfg)
        assert len(mission_dirs(wcfg["runs_dir"])) == 1  # 再着火しない

    def test_edited_note_retriggers(self, wcfg, vault, one_pass,
                                    mock_state_dir):
        note = vault / "inbox" / "テストミッション.md"
        note.write_text("やること #go\n")
        age(note)
        watcher.watch(wcfg)
        assert len(mission_dirs(wcfg["runs_dir"])) == 1

        with open(note, "a") as f:
            f.write("\n追記した\n")  # content hashが変わる
        age(note)
        watcher.watch(wcfg)
        assert len(mission_dirs(wcfg["runs_dir"])) == 2

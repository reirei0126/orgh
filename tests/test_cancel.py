"""HANDOFF タスク4b: プロセスレジストリと orgh cancel / #cancel タグ。

- アダプタはPopen化され、mission_id→実行中プロセスのレジストリを保持する
- orgh cancel <mission_id>: CANCELフラグ+未着手をcancelledに
- 実行中ミッションはフラグ検知で実行中subprocessをterminateし停止する
- 結果ノートに #cancel タグが付いたらwatcherが検知して同処理(スマホから停止)
- cancel後の orgh resume はフラグを解除し cancelled を pending に戻して続行する
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml

from orgh import cli, procreg, watcher
from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore

from .conftest import age, mission_dirs, read_ledger


def _task(id: str, deps: list[str] | None = None,
          sleep: int | None = None) -> dict:
    prompt = f"作業せよ [[MARK:{id}]]"
    if sleep:
        prompt += f" [[SLEEP:{sleep}]]"
    return {"id": id, "title": f"task {id}", "prompt": prompt,
            "worker": "claude_code", "deps": deps or [],
            "acceptance": ["mock acceptance"], "workdir": "."}


def _mission(tasks: list[dict]) -> Mission:
    return Mission.new(intent="cancel試験", context_digest="(test)",
                       tasks=tasks)


class TestProcessRegistry:
    def test_register_and_terminate(self):
        p = subprocess.Popen([sys.executable, "-c",
                              "import time; time.sleep(60)"])
        try:
            procreg.register("regtest", p)
            assert procreg.terminate("regtest") == 1
            p.wait(timeout=10)
            assert p.returncode != 0  # SIGTERMで止まった
        finally:
            if p.poll() is None:
                p.kill()

    def test_unregister_removes_handle(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        procreg.register("regtest2", p)
        p.wait(timeout=10)
        procreg.unregister("regtest2", p)
        assert procreg.terminate("regtest2") == 0


class TestCliCancelOffline:
    """実行中プロセスがいないミッションへの cancel(フラグ+状態変更)。"""

    def test_pending_tasks_become_cancelled(self, cfg, mock_state_dir,
                                            tmp_path, monkeypatch):
        m = _mission([_task("c1"), _task("c2", deps=["c1"])])
        store = RunStore(cfg["runs_dir"], m.id)
        store.save(m)

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True))
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "cancel", m.id])
        cli.main()

        assert (store.dir / "CANCEL").exists()
        loaded = json.loads((store.dir / "mission.json").read_text())
        assert [t["status"] for t in loaded["tasks"]] == [
            "cancelled", "cancelled"]


class TestCancelRunningMission:
    def test_flag_terminates_running_and_cancels_pending(self, cfg,
                                                         mock_state_dir):
        m = _mission([_task("c1", sleep=30), _task("c2", deps=["c1"])])
        store = RunStore(cfg["runs_dir"], m.id)

        th = threading.Thread(target=run_mission, args=(cfg, m, store),
                              daemon=True)
        start = time.time()
        th.start()
        # c1のworkerが走り出すまで待つ
        deadline = time.time() + 15
        while time.time() < deadline:
            if any(e["event"] == "task.start" and e["task"] == "c1"
                   for e in read_ledger(cfg["runs_dir"], m.id)):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("c1 never started")

        (store.dir / "CANCEL").touch()
        th.join(timeout=20)
        assert not th.is_alive()
        assert time.time() - start < 25  # SLEEP:30を待たずに止まった

        by_id = {t.id: t for t in m.tasks}
        assert by_id["c1"].status == "cancelled"
        assert by_id["c1"].attempts == 1        # 再attemptしない
        assert by_id["c2"].status == "cancelled"  # 未着手はdispatchされない
        assert any(e["event"] == "mission.cancelled"
                   for e in read_ledger(cfg["runs_dir"], m.id))

    def test_resume_after_cancel_completes(self, cfg, mock_state_dir,
                                           tmp_path, monkeypatch):
        m = _mission([_task("c1"), _task("c2", deps=["c1"])])
        store = RunStore(cfg["runs_dir"], m.id)
        for t in m.tasks:
            t.status = "cancelled"
        store.save(m)
        (store.dir / "CANCEL").touch()

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True))
        monkeypatch.setattr(sys, "argv", [
            "orgh", "--config", str(cfg_path), "resume", m.id])
        cli.main()

        assert not (store.dir / "CANCEL").exists()  # フラグ解除
        reloaded = store.load()
        assert [t.status for t in reloaded.tasks] == ["done", "done"]


class TestCancelFromVault:
    """結果ノートへの #cancel タグ付与(スマホ操作の模擬)でミッションが止まる。"""

    def test_cancel_tag_in_results_note_stops_mission(self, wcfg, vault,
                                                      one_pass,
                                                      mock_state_dir,
                                                      monkeypatch):
        monkeypatch.setenv("MOCK_PLAN_JSON", json.dumps(
            {"tasks": [_task("c1", sleep=30)]}, ensure_ascii=False))
        note = vault / "inbox" / "ミッション.md"
        note.write_text("やること #go\n")
        age(note)

        results_dir = vault / "orgh" / "results"

        def add_cancel_tag():
            deadline = time.time() + 15
            while time.time() < deadline:
                notes = list(results_dir.glob("*.md")) \
                    if results_dir.exists() else []
                if notes:
                    time.sleep(0.3)  # run_missionが走り出すのを待つ
                    with open(notes[0], "a") as f:
                        f.write("\n#cancel\n")
                    return
                time.sleep(0.05)

        saboteur = threading.Thread(target=add_cancel_tag, daemon=True)
        saboteur.start()
        start = time.time()
        watcher.watch(wcfg)
        assert time.time() - start < 25  # SLEEP:30を待たずに戻った

        [mdir] = mission_dirs(wcfg["runs_dir"])
        loaded = json.loads((mdir / "mission.json").read_text())
        assert loaded["tasks"][0]["status"] == "cancelled"
        # 結果ノートに中止が反映されている(finalizeで#cancel追記は上書きされる)
        body = (results_dir / f"{mdir.name}.md").read_text()
        assert "⊘ 中止" in body

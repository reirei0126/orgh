"""スリープ復帰検知とハングworkerの自動回収(H0①, orgh/orchestrator/sleep_recovery.py)。

実害: 2026-08-17 ミッションae3ee54a t2実行中にMacがスリープし、workerの
subprocessがネットワーク接続を握ったまま応答を返さなくなった。8時間の
無進捗を人手のkillで回収した。この再発を人手介入なしで防ぐための機構を
固定する。

時刻の注入について: reclaim_hung_workers()/detect_sleep_gap()はgap/now/
last_heartbeatを直接引数で受け取る設計のため、実時間のsleepには一切
依存せず、飛び幅を直接与えて検証する。
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from orgh import lease, procreg
from orgh.orchestrator import run_mission, sleep_recovery
from orgh.orchestrator.scheduler import ready
from orgh.state import Mission, RunStore, Task
from orgh.status_json import status_payload
from orgh.worktree import ensure_task_worktree

from .conftest import read_ledger


@pytest.fixture
def repo(tmp_path) -> Path:
    """コミット済みファイルを持つ試験用gitリポ(tests/test_worktree.pyと同じ作法)。"""
    d = tmp_path / "target-repo"
    d.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "config", "user.email",
                    "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(d), "config", "user.name",
                    "orgh-test"], check=True)
    (d / "shared.txt").write_text("base\n")
    subprocess.run(["git", "-C", str(d), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", "base"],
                   check=True)
    return d


def _running_task(mission_id: str, task_id: str, wt_cfg: dict,
                  repo: Path) -> Task:
    """gitリポ(repo)を主リポにしたタスク分離worktreeを持つ、実行中(running)
    のTaskを組み立てる(ensure_task_worktreeは実物のgitコマンドで
    worktree/branchを作るため、_has_committed_work()の判定を実物のgit状態で
    検証できる)。"""
    task = Task(id=task_id, title=f"task {task_id}", prompt="作業せよ",
               worker="claude_code", status="running", attempts=1,
               workdir=str(repo))
    path, branch = ensure_task_worktree(wt_cfg, mission_id, task)
    task.workdir, task.branch = str(path), branch
    return task


class TestDeadWorkerUncommittedIsReclaimed:
    """AC-1: 死亡worker+未コミット → sleep.detected → worker.reclaimed →
    attempt失敗記録 → 次のattempt開始。"""

    def test_full_sequence_and_next_attempt_starts(self, cfg, repo,
                                                    mock_state_dir):
        wt_cfg = {"enabled": True}
        task = _running_task("m-dead", "t1", wt_cfg, repo)
        mission = Mission(id="m-dead", intent="sleep recovery試験(dead)",
                          context_digest="(test)", tasks=[task])
        store = RunStore(cfg["runs_dir"], "m-dead")
        store.save(mission)
        store.log("task.start", task="t1", worker="claude_code", attempt=1)

        key = sleep_recovery.task_registry_key("m-dead", "t1")
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait(timeout=5)
        procreg.register(key, proc)
        try:
            futures = {"t1": object()}
            full_cfg = {**cfg, "worktree": wt_cfg}
            sleep_recovery.reclaim_hung_workers(full_cfg, store, mission,
                                                futures, gap=700.0)
        finally:
            procreg.unregister(key, proc)

        events = [e["event"] for e in read_ledger(cfg["runs_dir"], "m-dead")]
        assert "sleep.detected" in events
        assert "worker.reclaimed" in events
        assert events.index("sleep.detected") < events.index("worker.reclaimed")
        # 直前(reclaim前)のtask.startより後ろでreclaimイベントが記録されている
        assert events.index("task.start") < events.index("worker.reclaimed")

        # attempt失敗として記録され、次のattemptに進める状態(pending)へ戻る
        assert task.status == "pending"
        assert "t1" not in futures
        assert task.id in {t.id for t in ready(mission)}

        # 次のattemptが実際に開始・完走することを固定する(次のattempt開始)
        run_mission(full_cfg, mission, store)
        assert task.status == "done"
        starts = [e for e in read_ledger(cfg["runs_dir"], "m-dead")
                 if e["event"] == "task.start"]
        assert len(starts) == 2
        assert starts[0]["attempt"] == 1   # reclaim前(死んだ)attempt
        assert starts[1]["attempt"] == 2   # reclaim後の新しいattempt


class TestAliveWorkerIsUntouched:
    """AC-2: 生存・進捗中のworkerには何も起きない(回収イベント無し・kill無し)。"""

    def test_alive_worker_causes_no_reclaim_and_is_not_killed(
            self, cfg, repo, mock_state_dir):
        wt_cfg = {"enabled": True}
        task = _running_task("m-alive", "t1", wt_cfg, repo)
        mission = Mission(id="m-alive", intent="sleep recovery試験(alive)",
                          context_digest="(test)", tasks=[task])
        store = RunStore(cfg["runs_dir"], "m-alive")
        store.save(mission)

        key = sleep_recovery.task_registry_key("m-alive", "t1")
        proc = subprocess.Popen([sys.executable, "-c",
                                 "import time; time.sleep(5)"])
        try:
            procreg.register(key, proc)
            futures = {"t1": object()}
            full_cfg = {**cfg, "worktree": wt_cfg}
            sleep_recovery.reclaim_hung_workers(full_cfg, store, mission,
                                                futures, gap=700.0)

            events = [e["event"] for e in read_ledger(cfg["runs_dir"], "m-alive")]
            assert "worker.reclaimed" not in events
            assert "task.sleep_unknown" not in events
            assert task.status == "running"
            assert "t1" in futures
            assert proc.poll() is None, "生存中のworkerが終了させられている"
        finally:
            procreg.unregister(key, proc)
            proc.kill()
            proc.wait(timeout=10)


class TestCommittedBranchDefersToAwaitingHuman:
    """AC-3: 死亡worker+タスクブランチにコミット済み成果あり →
    自動回収せず、既存の人間確認導線(awaiting_human。orgh humandoneで
    復旧できる・orgh list/status/doctorが正しく表示する)へ委ねる。

    2026-08-19 レビュー差し戻し: 当初はTask.statusへ生の文字列"unknown"を
    書き込んでいたが、これはorghの既存契約(tests/test_unknown_status.py)を
    破り、orgh list/status/doctorの表示・復旧経路をすべて素通りしてミッション
    が永久にrunning表示され続ける不具合だった(A5契約違反)。ここでは
    Task.statusが実際に"awaiting_human"になり、orgh/orchestrator/
    transitions.pyの既存機構(human_request・orgh humandoneでの復旧)に
    正しく乗ることを固定する。"""

    def test_committed_work_defers_to_awaiting_human(self, cfg, repo,
                                                      mock_state_dir):
        wt_cfg = {"enabled": True}
        task = _running_task("m-committed", "t1", wt_cfg, repo)
        # workerが死ぬ直前に成果をコミット済みだった状況を再現する
        wd = task.workdir
        Path(wd, "partial.txt").write_text("in-progress work\n")
        subprocess.run(["git", "-C", wd, "add", "-A"], check=True)
        subprocess.run(["git", "-C", wd, "-c", "user.name=orgh",
                        "-c", "user.email=orgh@local", "commit", "-q",
                        "-m", "partial work"], check=True)

        mission = Mission(id="m-committed", intent="sleep recovery試験(committed)",
                          context_digest="(test)", tasks=[task])
        store = RunStore(cfg["runs_dir"], "m-committed")
        store.save(mission)
        attempts_before = task.attempts

        key = sleep_recovery.task_registry_key("m-committed", "t1")
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait(timeout=5)
        procreg.register(key, proc)
        try:
            futures = {"t1": object()}
            full_cfg = {**cfg, "worktree": wt_cfg}
            sleep_recovery.reclaim_hung_workers(full_cfg, store, mission,
                                                futures, gap=700.0)
        finally:
            procreg.unregister(key, proc)

        events = [e["event"] for e in read_ledger(cfg["runs_dir"], "m-committed")]
        assert "sleep.detected" in events
        assert "worker.reclaimed" not in events, (
            "コミット済み成果があるのに自動回収されてしまっている")
        assert "task.sleep_ambiguous" in events
        assert "task.awaiting_human" in events

        # 生の"unknown"ではなく、既存の人間確認状態機械(awaiting_human)に
        # 正しく乗っている(orgh list/status/doctor/humandoneが機能する状態)
        assert task.status == "awaiting_human"
        assert task.human_request, "human_requestが空で orgh status に何も出ない"
        # HUMAN:転換・capability_blockedと同じ規約(refund_attempt=True。
        # 判定不能な状況はworkerの実力不足ではないためattemptを消費しない)
        assert task.attempts == attempts_before - 1

        # レビュー差し戻しで指摘された実機不具合の直接固定: 生の"unknown"を
        # 書いていたときは status_payload() が誤って"running"を返し続けて
        # いた(ミッションが終了しているのに永久に実行中と誤表示される、
        # A5違反)。awaiting_humanへ正しく乗ったことでミッションレベルの
        # 状態も正しく導出されることを確認する
        payload = status_payload(mission, full_cfg)
        assert payload["status"] == "awaiting_human"
        assert payload["status"] != "running"

        # orgh/cli.pyのhumandoneコマンドの前提条件(task.status ==
        # "awaiting_human")を満たしており、人間が実際に復旧操作できる
        assert task.status == "awaiting_human"


class TestPidAliveAgainstRealSubprocess:
    """AC-4: 実際にkill -9した本物のsubprocessに対する生存判定が誤検知しない
    (lease.pid_alive を流用。sleep_recoveryの生死判定はこれを直接使う)。"""

    def test_pid_alive_reflects_real_process_lifecycle(self):
        proc = subprocess.Popen([sys.executable, "-c",
                                 "import time; time.sleep(30)"])
        try:
            assert lease.pid_alive(proc.pid) is True, (
                "生存中のプロセスを死亡と誤判定した")
            os.kill(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)  # reapしてゾンビにしない(実際のreap挙動)
            assert lease.pid_alive(proc.pid) is False, (
                "kill -9で終了・reap済みのプロセスを生存と誤判定した")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)


class TestDetectSleepGap:
    """しきい値境界の直接確認(lease.LEASE_EXPIRY_SECは変更しない・流用のみ)。"""

    def test_below_threshold_is_none(self):
        assert sleep_recovery.detect_sleep_gap(
            now=1000.0, last_heartbeat=1000.0 - sleep_recovery.SLEEP_GAP_SEC + 1
        ) is None

    def test_at_or_above_threshold_returns_gap(self):
        gap = sleep_recovery.detect_sleep_gap(
            now=1000.0, last_heartbeat=1000.0 - sleep_recovery.SLEEP_GAP_SEC)
        assert gap == sleep_recovery.SLEEP_GAP_SEC


class TestReclaimFlagScopedToAttempt:
    """誤った二重実行の防止: reclaimフラグは対応するattempt番号のみを止め、
    後続の新しいattemptには影響しない(task_executor.pyのwas_reclaimedチェック
    が読む契約そのものを直接固定する)。"""

    def test_flag_matches_only_the_reclaimed_attempt(self, tmp_path):
        store = RunStore(tmp_path / "runs", "m-flag")
        # reclaim_hung_workersが確定するのと同じ形式(中身=attempt番号)で、
        # 公開APIのreclaim_flag_path()経由でフラグを立てる
        sleep_recovery.reclaim_flag_path(store, "t1").write_text("1")

        assert sleep_recovery.was_reclaimed(store, "t1", 1) is True
        # 次のattempt(2)は同じフラグの影響を受けない
        assert sleep_recovery.was_reclaimed(store, "t1", 2) is False

    def test_no_flag_is_not_reclaimed(self, tmp_path):
        store = RunStore(tmp_path / "runs", "m-noflag")
        assert sleep_recovery.was_reclaimed(store, "t1", 1) is False

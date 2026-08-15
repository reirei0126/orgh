"""永続lease層(orgh/lease.py)と、RunStore.load(reset_inflight=True)の
実行中系巻き戻しがlease生死に応じて変わることの単体試験。

時刻はすべて now= 引数で注入し、実時間のsleepには依存しない。
"""
from __future__ import annotations

import os
import time

from orgh import lease
from orgh.orchestrator import run_mission
from orgh.state import Mission, RunStore, Task

BASE_TS = 1_000_000.0


def _task(id: str, status: str) -> Task:
    return Task(id=id, title=f"task {id}", prompt="p", status=status)


def _mission(tasks: list[Task]) -> Mission:
    return Mission(id="mlease01", intent="lease試験", context_digest="(test)",
                   tasks=tasks)


def _real_mission(task_ids_with_deps: list[tuple[str, list[str]]]) -> Mission:
    """run_mission()で実際に流せるMission(Planner由来のtask dictを経由)。"""
    return Mission.new(intent="scheduler lease配線試験", context_digest="(test)",
                        tasks=[
                            {"id": tid, "title": f"task {tid}",
                             "prompt": f"作業せよ [[MARK:{tid}]]",
                             "worker": "claude_code", "deps": deps,
                             "acceptance": ["mock acceptance"], "workdir": "."}
                            for tid, deps in task_ids_with_deps
                        ])


class TestLeaseHeartbeatAndExpiry:
    def test_is_alive_right_after_heartbeat(self, tmp_path):
        run_dir = tmp_path / "run"
        lease.acquire(run_dir, now=BASE_TS)
        lease.heartbeat(run_dir, now=BASE_TS + 1)
        assert lease.is_alive(run_dir, now=BASE_TS + 1) is True

    def test_is_expired_past_expiry_threshold(self, tmp_path):
        run_dir = tmp_path / "run"
        lease.acquire(run_dir, now=BASE_TS)
        past_expiry = BASE_TS + lease.LEASE_EXPIRY_SEC + 1
        assert lease.is_alive(run_dir, now=past_expiry) is False

    def test_is_alive_exactly_at_threshold_boundary(self, tmp_path):
        run_dir = tmp_path / "run"
        lease.acquire(run_dir, now=BASE_TS)
        at_threshold = BASE_TS + lease.LEASE_EXPIRY_SEC
        assert lease.is_alive(run_dir, now=at_threshold) is True

    def test_no_lease_file_is_not_alive(self, tmp_path):
        run_dir = tmp_path / "run"
        assert lease.is_alive(run_dir, now=BASE_TS) is False

    def test_corrupt_lease_file_is_not_alive_not_raising(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir(parents=True)
        (run_dir / "lease.json").write_text("{not valid json")
        assert lease.is_alive(run_dir, now=BASE_TS) is False
        assert lease.read(run_dir) is None

    def test_release_removes_lease(self, tmp_path):
        run_dir = tmp_path / "run"
        lease.acquire(run_dir, now=BASE_TS)
        lease.release(run_dir)
        assert lease.read(run_dir) is None
        # 存在しない状態でのreleaseは例外を出さない
        lease.release(run_dir)

    def test_acquire_generates_new_generation_each_call(self, tmp_path):
        run_dir = tmp_path / "run"
        first = lease.acquire(run_dir, now=BASE_TS)
        second = lease.acquire(run_dir, now=BASE_TS + 1)
        assert first.generation != second.generation

    def test_heartbeat_preserves_pid_and_generation(self, tmp_path):
        run_dir = tmp_path / "run"
        acquired = lease.acquire(run_dir, now=BASE_TS)
        updated = lease.heartbeat(run_dir, now=BASE_TS + 5)
        assert updated.pid == acquired.pid
        assert updated.generation == acquired.generation
        assert updated.heartbeat_at == BASE_TS + 5

    def test_heartbeat_without_prior_acquire_falls_back_to_acquire(
            self, tmp_path):
        run_dir = tmp_path / "run"
        result = lease.heartbeat(run_dir, now=BASE_TS)
        assert result.pid == os.getpid()
        assert lease.read(run_dir) is not None

    def test_write_is_atomic_no_leftover_tmp_file(self, tmp_path):
        run_dir = tmp_path / "run"
        lease.acquire(run_dir, now=BASE_TS)
        names = {p.name for p in run_dir.iterdir()}
        assert names == {"lease.json"}

    def test_constants_are_defined_with_expected_values(self):
        assert lease.HEARTBEAT_INTERVAL_SEC == 30
        assert lease.LEASE_EXPIRY_SEC == 120


class TestRunStoreLoadRespectsLease:
    """RunStore.load(reset_inflight=True) の実行中系巻き戻しは、leaseが
    失効している場合のみ適用される(生きているプロセスの状態を偽らない)。"""

    def test_alive_lease_keeps_inflight_status(self, tmp_path):
        # RunStore.load()はlease.is_alive()をnow未指定(実時刻)で呼ぶため、
        # ここでは実時刻を直接使う(実際に待つわけではなく、その場でheartbeat_at
        # に「今」を書き込むだけ)
        store = RunStore(tmp_path / "runs", "mlease01")
        m = _mission([_task("t1", "running")])
        store.save(m)
        now = time.time()
        lease.acquire(store.dir, now=now)
        lease.heartbeat(store.dir, now=now)

        reloaded = store.load(reset_inflight=True)
        assert reloaded.tasks[0].status == "running"

    def test_expired_lease_still_rewinds_inflight_to_pending(self, tmp_path):
        # heartbeat_atを実時刻からLEASE_EXPIRY_SEC超過分だけ過去へ直接書き込む
        # ことで、実際に待たずに「失効済み」の状態を作る
        store = RunStore(tmp_path / "runs", "mlease01")
        m = _mission([_task("t1", "running"), _task("t2", "queued"),
                      _task("t3", "review")])
        store.save(m)
        stale = time.time() - lease.LEASE_EXPIRY_SEC - 1
        lease.acquire(store.dir, now=stale)

        reloaded = store.load(reset_inflight=True)
        assert reloaded.tasks[0].status == "pending"
        assert reloaded.tasks[1].status == "pending"
        assert reloaded.tasks[2].status == "pending"

    def test_no_lease_at_all_still_rewinds_as_before(self, tmp_path):
        # lease.jsonが存在しない(旧ミッション、または未実行)場合も従来どおり
        # 巻き戻す(後方互換)
        store = RunStore(tmp_path / "runs", "mlease01")
        m = _mission([_task("t1", "running")])
        store.save(m)

        reloaded = store.load(reset_inflight=True)
        assert reloaded.tasks[0].status == "pending"

    def test_reset_inflight_false_ignores_lease_entirely(self, tmp_path):
        # reset_inflight=False(読み取り専用照会)はlease状態に関わらず生の
        # 永続状態をそのまま返す(従来どおり)
        store = RunStore(tmp_path / "runs", "mlease01")
        m = _mission([_task("t1", "running")])
        store.save(m)

        reloaded = store.load(reset_inflight=False)
        assert reloaded.tasks[0].status == "running"


class TestSchedulerLeaseWiring:
    """run_mission()がミッション開始時にleaseをacquireし、実行中は生きたまま
    保ち、正常終了時にreleaseすることの結合試験(モックworkerで実行)。"""

    def test_lease_alive_during_run_and_released_after(
            self, cfg, mock_state_dir):
        m = _real_mission([("t1", []), ("t2", ["t1"])])
        store = RunStore(cfg["runs_dir"], m.id)
        seen_during_run = []

        def on_update(mission):
            seen_during_run.append(lease.read(store.dir) is not None)

        run_mission(cfg, m, store, on_update=on_update)

        assert seen_during_run, "on_updateが一度も呼ばれていない(試験構成ミス)"
        assert all(seen_during_run), (
            "実行中はleaseが存在しているはずだが、少なくとも1回消えていた")
        assert lease.read(store.dir) is None, (
            "正常終了後はleaseがreleaseされているはず")

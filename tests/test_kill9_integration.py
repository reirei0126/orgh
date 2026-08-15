"""kill -9 (SIGKILL) 統合試験: 実サブプロセスでミッション実行プロセスを
本当に殺し、orgh list / orgh status の表示と resume の安全性を固定する。

このタスクで固定する3点(タスクの①②③に対応):
  ①(TestRunningSurvivesGraceWindow) kill -9直後、失効猶予内では表示が
    running のまま(unknownへ即降格しない)
  ②(TestUnknownAfterLeaseExpiry) lease失効後は orgh list / orgh status
    (JSON双方)で unknown になる
  ③(TestResumeDoesNotDoubleExecute) 殺したあとのresumeで、既にdone済みの
    タスクが再実行されない(二重実行が起きない)

時刻の進め方について: 実時間で120秒(lease.LEASE_EXPIRY_SEC)待つ代わりに、
lease.heartbeat(store.dir, now=<過去の時刻>) でlease.jsonのheartbeat_atを
直接過去へ書き換える(既存pid/generationは保持する)ことで「失効した」
状態を即座に作る。

2026-08-15 consumerペルソナ実機レビューでの差し戻しを受けた修正について:
当初の①は、テストプロセス自身が子プロセスの直接の親でありproc.wait()を
意図的に呼ばずゾンビ状態を保つ作為でpid生存チェックを誤魔化しており、実際の
デーモン終了パターン(orgh watch/executorをkill -9すると、シェルのジョブ
管理・systemd・launchd等の親が通常数百ms〜数秒でreapし、os.kill(pid,0)が
即座に失敗する)を代表していなかった。実機で `orgh --config ... list` /
`status` を叩くと、レビュー時点の実装(lease.is_alive()がheartbeat鮮度と
pid生存のANDで判定)では失効猶予内でも即座にunknownになってしまうことが
確認された。

対応(orgh/lease.py): is_alive()とis_alive_lenient()を分離した。
- is_alive(): 従来通りheartbeat鮮度とpid生存のAND。RunStore.load専用
  (orgh/state.py)。ここで早まって「死んでいる」と判定しても、実際にまだ
  生きていればミッションロック(flock)が新規実行そのものを拒否するため
  安全(二重実行の実際の安全網はflock側にある)。
- is_alive_lenient(): heartbeat鮮度のみ(pidは見ない)。orgh/listing.py・
  orgh/status_json.pyの表示判定専用。flockのような安全網が無い表示系では、
  kill -9直後にpidが即座に消えても失効猶予の間は判断を保留する。

本ファイルの①は、この修正が実機のkill -9パターンで機能することを、
レビュアーと同じ検証手段(実サブプロセスを即座にreapし、実際の
`orgh --config ... list`/`status` CLIサブプロセスを起動して出力を見る)で
固定する。②以降は元からproc.wait()で明示的に刈り取ってから検証しており、
この変更の影響を受けない(heartbeat_atのバックデートがis_alive_lenient()を
単独でFalseにする)。

2026-08-15 consumerペルソナ実機レビュー(2回目)での差し戻しを受けた追加修正:
`orgh/cli.py` の `_summary()`(`orgh status` のプレーンテキスト出力・
`orgh run`/`resume`/`approve`等の完了サマリが共有する経路)が、
`orgh/listing.py`・`orgh/status_json.py`(寛容判定 is_alive_lenient採用)とは
不一致な厳格判定 `lease.is_alive()` を使っており、失効猶予内に
「`orgh list`=running なのに `orgh status`(--jsonなし)=unknown」という
表示矛盾が起きていた。`_summary()` の lease_dead 判定を `is_alive_lenient()`
へ揃えて修正し、①のテストにプレーンテキスト `orgh status`(--jsonなし)の
実CLI呼び出しによる固定を追加した(既存のJSON経路チェックだけではこの
サーフェスを検知できていなかった)。
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from orgh import doctor, lease
from orgh.listing import list_missions
from orgh.orchestrator import run_mission
from orgh.state import RunStore
from orgh.status_json import status_payload

from .conftest import read_calls, read_ledger, write_config

REPO = Path(__file__).resolve().parent.parent
CHILD = str(REPO / "tests" / "helpers" / "run_mission_child.py")

_WAIT_DEADLINE_SEC = 20


def _run_cli(cfg: dict, tmp_path: Path, *args: str) -> str:
    """実際の `orgh --config <cfg> <args>` をサブプロセスとして起動し、
    標準出力の生テキストを返す。orgh.cliをモジュールとして解決できるよう
    PYTHONPATHにリポジトリルートを渡す(pip install不要でこのworktree
    そのものを対象にする)。"""
    cfg_path = write_config(tmp_path, cfg)
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    r = subprocess.run(
        [sys.executable, "-m", "orgh.cli", "--config", str(cfg_path), *args],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=15)
    assert r.returncode == 0, (
        f"orgh {' '.join(args)} が失敗 (rc={r.returncode}): {r.stderr}")
    return r.stdout


def _run_cli_json(cfg: dict, tmp_path: Path, *args: str) -> dict:
    """_run_cli()の出力をJSONとしてパースする(--json付き呼び出し用)。"""
    return json.loads(_run_cli(cfg, tmp_path, *args))


def _task(id: str, deps: list[str] | None = None,
          prompt: str | None = None) -> dict:
    return {
        "id": id, "title": f"task {id}",
        "prompt": prompt or f"作業せよ [[MARK:{id}]]",
        "worker": "claude_code", "deps": deps or [],
        "acceptance": ["mock acceptance"], "workdir": ".",
    }


def _spawn_mid_execution(cfg: dict, tmp_path: Path,
                         mission_id: str) -> subprocess.Popen:
    """k1完了・k2実行中(SLEEP中)の状態まで進めた実子プロセスを返す
    (まだkillしない)。呼び出し元がkillとwait()のタイミングを制御する。

    start_new_session=True で子プロセスを新しいセッション(プロセスグループ)
    のリーダーにする。k2のworker実行はさらにその子(mockのclaude subprocess)
    として起動されるため、単純にリーダーpidだけをkillすると、SLEEP中の
    mock subprocessが孤児として生き残り30秒間バックグラウンドで動き続けて
    しまう(後始末漏れ・tmp_path削除後の書き込み失敗の原因になる)。
    _sigkill_group()でプロセスグループ全体を一括killしてこれを防ぐ。
    """
    tasks = [
        _task("k1"),
        _task("k2", prompt="長い作業 [[MARK:k2]] [[SLEEP:30]]"),
        _task("k3", deps=["k2"]),
    ]
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(
        {"cfg": cfg, "mission_id": mission_id, "tasks": tasks},
        ensure_ascii=False))

    # cwdはリポ外(tmp)にする: workdir "." がorghリポを指すと自己改変ガード対象
    proc = subprocess.Popen([sys.executable, CHILD, str(spec)],
                            cwd=str(tmp_path),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True)
    deadline = time.time() + _WAIT_DEADLINE_SEC
    while time.time() < deadline:
        ledger = read_ledger(cfg["runs_dir"], mission_id)
        k1_passed = any(e["event"] == "task.review"
                        and e["task"] == "k1" and e["passed"]
                        for e in ledger)
        k2_started = any(e["event"] == "task.start"
                         and e["task"] == "k2" for e in ledger)
        if k1_passed and k2_started:
            break
        time.sleep(0.05)
    else:
        _sigkill_group(proc)
        proc.wait(timeout=10)
        raise AssertionError("child process never reached k2 start")
    time.sleep(0.2)  # k1完了後のsave(mission.json更新)を確実に跨ぐ
    return proc


def _sigkill_group(proc: subprocess.Popen) -> None:
    """子プロセスとその子(mock workerのsubprocess)を丸ごとSIGKILLする。
    start_new_session=Trueにより proc.pid はそのままプロセスグループID
    でもあるため、killpgで一括終了できる。既に死んでいる(グループの全
    メンバーが終了・回収済み)場合、OSはProcessLookupErrorだけでなく
    (pgidが実体を持たなくなったことに対して)PermissionErrorを返すことが
    あるため両方を無視する(冪等な後始末呼び出しなので握りつぶしてよい)。"""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


class TestRunningSurvivesGraceWindow:
    """①: kill -9直後、失効猶予内ではlist/statusともrunningのまま。

    レビュアーの実機再現手順に合わせ、killしたら直ちにproc.wait()で刈り取る
    (ゾンビ状態を作為的に維持しない — シェル/systemd/launchd等の親が実際に
    数百ms〜数秒でreapする挙動を模す)。それでもrunning表示が保たれることを、
    プロセス内呼び出し(list_missions/status_payload)と、実際の
    `orgh --config ... list --json` / `status --json` / `status`(--json無し
    のプレーンテキスト)の3つのCLIサブプロセス経路すべてで確認する。
    プレーンテキスト経路(orgh/cli.py の `_summary()`)は、list/status(JSON)
    が使う`is_alive_lenient()`とは別に厳格判定`is_alive()`を使っていたため
    「listはrunning・statusはunknown」という食い違いが起きていた
    (2026-08-15 consumerペルソナ実機レビュー2回目で指摘、`_summary()`を
    `is_alive_lenient()`へ統一して修正)。既知の表示サーフェスを1つでも
    未検証のまま残すと同種の不一致が再発しうるため、ここで3経路とも固定する。
    """

    def test_list_and_status_stay_running_right_after_sigkill(
            self, cfg, mock_state_dir, tmp_path):
        mission_id = "kill9-grace"
        proc = _spawn_mid_execution(cfg, tmp_path, mission_id)
        _sigkill_group(proc)
        proc.wait(timeout=10)  # 直ちに刈り取る(実際のreap挙動を模す)

        heartbeat_age = time.time() - lease.read(
            Path(cfg["runs_dir"]) / mission_id).heartbeat_at
        assert heartbeat_age < lease.LEASE_EXPIRY_SEC, (
            "テストの前提が崩れている: heartbeatが既に失効猶予を超えている")

        out = list_missions(cfg["runs_dir"])
        m = next(x for x in out if x["mission_id"] == mission_id)
        assert m["status"] == "running"

        store = RunStore(cfg["runs_dir"], mission_id)
        reloaded = store.load(reset_inflight=False)
        payload = status_payload(reloaded, cfg)
        assert payload["status"] == "running"
        by_id = {t["id"]: t for t in payload["tasks"]}
        assert by_id["k2"]["status"] == "running"

        # 実際のCLIサブプロセス経由でも同じ結果になることを確認する
        # (レビュアーが実機で検証した手順そのもの)。list/status(JSON)に加え、
        # プレーンテキストのorgh status(--json無し)も別サーフェスとして
        # 明示的にチェックする(過去の教訓: 既知の表示サーフェスは受け入れ
        # 基準に個別に明記しないと後続で漏れる)。
        list_out = _run_cli_json(cfg, tmp_path, "list", "--json")
        cli_m = next(x for x in list_out["missions"]
                    if x["mission_id"] == mission_id)
        assert cli_m["status"] == "running"

        status_json_out = _run_cli_json(cfg, tmp_path, "status", mission_id,
                                        "--json")
        assert status_json_out["status"] == "running"

        status_text_out = _run_cli(cfg, tmp_path, "status", mission_id)
        assert "[unknown]" not in status_text_out, (
            "プレーンテキストのorgh status(--json無し)が失効猶予内なのに"
            f"unknownを出した(list/status--jsonとの表示不一致): "
            f"{status_text_out!r}")
        assert "[running]" in status_text_out


class TestUnknownAfterLeaseExpiry:
    """②: lease失効後、list/status(JSON・プレーンテキスト共)ともunknownになる。"""

    def test_list_and_status_json_show_unknown_after_expiry(
            self, cfg, mock_state_dir, tmp_path):
        mission_id = "kill9-unknown"
        proc = _spawn_mid_execution(cfg, tmp_path, mission_id)
        _sigkill_group(proc)
        proc.wait(timeout=10)  # 確実に刈り取ってから進める(実死亡の確定)

        store = RunStore(cfg["runs_dir"], mission_id)
        # 実時間を120秒待つ代わりに、既存pid/generationを保ったまま
        # heartbeat_atだけ過去へ書き換える(lease.pyの公開APIのみ使用)
        stale = time.time() - lease.LEASE_EXPIRY_SEC - 1
        lease.heartbeat(store.dir, now=stale)

        out = list_missions(cfg["runs_dir"])
        m = next(x for x in out if x["mission_id"] == mission_id)
        assert m["status"] == "unknown"

        reloaded = store.load(reset_inflight=False)
        payload = status_payload(reloaded, cfg)
        assert payload["status"] == "unknown"
        by_id = {t["id"]: t for t in payload["tasks"]}
        assert by_id["k2"]["status"] == "unknown"

        # プレーンテキストのorgh status(--json無し、orgh/cli.py _summary())
        # 経路も、失効確定後は正しくunknownを出すことを実CLIで確認する
        # (①で「猶予内は出さない」ことを固定した対の確認: 猶予明けには
        # ちゃんと出る必要がある)
        status_text_out = _run_cli(cfg, tmp_path, "status", mission_id)
        assert "[unknown]" in status_text_out
        assert "[running]" not in status_text_out

        # ボーナス検証: orgh doctorの復旧導線にもこのミッションが乗る
        # (orgh/doctor.py 側の実装が実killedプロセスに対しても機能することの確認)
        diag_payload = doctor.doctor_payload(cfg)
        diag = next(c for c in diag_payload["checks"]
                   if c["name"] == f"unknown_mission:{mission_id}")
        # 復旧要否は人間が判断する情報提示であって環境異常ではないため、
        # doctor全体のok(=環境健全性)は道連れにしない(designerペルソナ
        # 実機レビュー2026-08-15の是正: 認証失敗等の本当のNGと混同されない
        # ようok=True/prefix="--"で出す。テキスト側は下のCLI検証で確認)
        assert diag["ok"] is True
        assert diag["diagnostics"]["lease"]["process_alive"] is False
        task_ids = {t["id"] for t in diag["diagnostics"]["tasks"]}
        assert {"k1", "k2", "k3"} <= task_ids

        # テキスト出力(orgh doctor、--json無し)側の可読性も固定する:
        # (1) "NG"ではなく"--"接頭辞(環境異常と混同しない)
        # (2) ledger末尾の各行にtaskフィールドがあり、どのタスクの出来事か
        #     文字面だけで判別できる
        # (3) lease行にheartbeat_atが出る(いつから止まっているか分かる)
        # (4) 生epoch秒の浮動小数ではなく、orgh listと同じ人間可読書式で出る
        lines, _ = doctor.run_doctor(cfg)
        diag_line = next(l for l in lines
                         if f"unknown_mission:{mission_id}" in l)
        assert diag_line.startswith("-- "), (
            f"復旧情報がNG接頭辞のまま環境異常と見分けがつかない: {diag_line!r}")

        ledger_lines = [l for l in lines if l.strip().startswith("task.")]
        assert ledger_lines, "ledger末尾のテキスト行が出力されていない"
        for l in ledger_lines:
            assert "task=" in l, f"ledger行からtaskが読み取れない: {l!r}"
            assert "task=-" not in l, f"task=- (欠損)のまま出ている: {l!r}"

        lease_line = next(l for l in lines if "lease: pid=" in l)
        assert "heartbeat_at=" in lease_line, (
            f"lease行にheartbeat_atが無く、いつ止まったか判断できない: "
            f"{lease_line!r}")

        raw_epoch = re.compile(r"ts=\d{9,}\.\d+")
        assert not any(raw_epoch.search(l) for l in lines), (
            "生epoch秒のままの時刻表示が残っている"
            "(orgh listと同じ人間可読書式に揃えるべき)")


class TestResumeDoesNotDoubleExecute:
    """③: 殺したあとのresumeで、done済みタスクが再実行されない。"""

    def test_resume_after_expiry_reruns_only_inflight_task(
            self, cfg, mock_state_dir, tmp_path, monkeypatch):
        mission_id = "kill9-resume"
        proc = _spawn_mid_execution(cfg, tmp_path, mission_id)
        _sigkill_group(proc)
        proc.wait(timeout=10)

        store = RunStore(cfg["runs_dir"], mission_id)
        stale = time.time() - lease.LEASE_EXPIRY_SEC - 1
        lease.heartbeat(store.dir, now=stale)

        # resume前: k1はdoneのまま、k2(実行中に死んだ)はpendingへ巻き戻る
        loaded = store.load(reset_inflight=True)
        by_id = {t.id: t for t in loaded.tasks}
        assert by_id["k1"].status == "done"
        assert by_id["k2"].status == "pending"

        monkeypatch.setenv("MOCK_NO_SLEEP", "1")  # k2の[[SLEEP:30]]を無効化
        run_mission(cfg, loaded, store)

        assert all(t.status == "done" for t in loaded.tasks)

        # 二重実行が起きていないこと: 既にdone済みのk1はresumeで一切
        # 再実行されない(worker呼び出し・ledger task.startともちょうど1回)。
        # k2はkillされた1回目のattemptが未完了(mockのSLEEP中に
        # プロセスグループごと死んだためworker呼び出し自体は記録されない)
        # のままresumeで仕切り直された1回だけが完走しており、これは
        # クラッシュ後の正常なリトライであって二重実行ではない
        # (「同じ完了成果が2回作られる」ことがないのが本来の不変条件)。
        calls = read_calls(Path(mock_state_dir))
        worker_calls = [c for c in calls if c.get("role") == "worker"]
        marker_counts: dict[str, int] = {}
        for c in worker_calls:
            marker_counts[c["marker"]] = marker_counts.get(c["marker"], 0) + 1
        assert marker_counts.get("k1") == 1, (
            f"k1(既にdone)が resume で再実行された: {marker_counts}")
        assert marker_counts.get("k2") == 1, (
            f"k2の完走したworker呼び出しが複数回記録されている"
            f"(二重実行の疑い): {marker_counts}")
        assert marker_counts.get("k3") == 1

        # ledger上も、既にdone済みだったk1のtask.startはちょうど1回のまま
        # (resumeで再着火されていない)。まだ一度も走っていなかったk3も1回。
        # k2は「killされた1回目(未完了) + resumeで完走した2回目」の2回で
        # 正しい(1回目はattempts消費のみでworker呼び出しには至っていない)
        ledger = read_ledger(cfg["runs_dir"], mission_id)
        starts = [e for e in ledger if e["event"] == "task.start"]
        start_counts: dict[str, int] = {}
        for e in starts:
            start_counts[e["task"]] = start_counts.get(e["task"], 0) + 1
        assert start_counts["k1"] == 1, (
            f"k1(既にdone)のtask.startがresumeで増えた: {start_counts}")
        assert start_counts["k3"] == 1
        assert start_counts["k2"] == 2, (
            "k2はkillされた1回目(未完了)+resumeで完走した2回目のはずが"
            f"想定と異なる: {start_counts}")

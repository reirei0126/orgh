"""永続lease層: ミッション実行プロセスの生死を再起動をまたいで判定する。

背景(実害): orghの実行中/死亡/孤児の判定材料は従来3つあったが、いずれも
再起動後の生存証拠にならない。
  - orgh/procreg.py はプロセス内メモリのレジストリで、プロセスが死ぬ/
    再起動すると消える
  - ledgerの task.start は「開始した」証拠であって「まだ生きている」証拠
    ではない
  - mission.json はタスク完了時にしか保存されない
このモジュールは runs/<mission_id>/lease.json に heartbeat_at を定期的に
書き込み、他プロセス(GUI/CLI/再起動後のorgh自身)が「実行中に見えるタスクの
背後で本当にプロセスが生きているか」を判定できるようにする。

書き込みは一時ファイル+os.replaceで原子的に行う(部分書き込みされたJSONを
他プロセスが読むのを防ぐ)。読み取り側はファイル欠損・JSON破損を例外にせず
「leaseなし」として扱う。
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

# heartbeat更新間隔(秒)。schedulerのポーリングループ(POLL_INTERVAL=0.5秒、
# orgh/orchestrator/scheduler.py)は、この間隔ごとにleaseファイルを書き直す
# (0.5秒ごとに毎回書くとディスクI/Oが過剰なため間引く)。
# 暫定値: 「表示のズレが数十秒以内に収まってほしい」を目安にした初期値で、
# オーナーが運用実績を見て調整することを想定している
HEARTBEAT_INTERVAL_SEC = 30

# lease失効しきい値(秒)。最終heartbeatからこの秒数を超えて更新がなければ
# プロセスは死んでいるとみなす。HEARTBEAT_INTERVAL_SEC(30秒)の4倍を取り、
# GCの一時停止・CPU過負荷等でheartbeatの発行が1〜数回連続で遅延しても
# 誤って失効判定しない余裕を持たせた。これも暫定値でオーナー調整の余地がある
LEASE_EXPIRY_SEC = 120

_LEASE_FILENAME = "lease.json"


@dataclass
class Lease:
    """runs/<mission_id>/lease.json の内容。

    generation はプロセス起動ごとに一度だけ生成する一意なID(uuid4)で、以後
    同一プロセス内では不変。PID再利用(死んだプロセスのpidを無関係な別
    プロセスがOSに引き継がれる)によってゾンビleaseを「生きている」と
    誤判定するのを防ぐため、pid生存チェックと組み合わせて使う識別子として
    公開している。heartbeat_at はUTC epoch秒。
    """
    pid: int
    generation: str
    heartbeat_at: float


def _lease_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / _LEASE_FILENAME


def _write(run_dir: str | Path, lease: Lease) -> None:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = run_dir / f".{_LEASE_FILENAME}.tmp"
    tmp.write_text(json.dumps({
        "pid": lease.pid,
        "generation": lease.generation,
        "heartbeat_at": lease.heartbeat_at,
    }, ensure_ascii=False))
    os.replace(tmp, _lease_path(run_dir))


def acquire(run_dir: str | Path, now: float | None = None) -> Lease:
    """新しい起動世代でleaseを取得する。ミッション実行プロセスの起動時に一度
    呼ぶ。既存leaseがあれば無条件に上書きする(二重実行防止はミッションlock
    の役目で、ここでの重複チェックはスコープ外)。"""
    lease = Lease(pid=os.getpid(), generation=uuid.uuid4().hex,
                  heartbeat_at=now if now is not None else time.time())
    _write(run_dir, lease)
    return lease


def heartbeat(run_dir: str | Path, now: float | None = None) -> Lease:
    """heartbeat_atを更新する。呼び出し元は既にacquire済みの同一プロセスで
    あるため、既存leaseがあればpid/generationはそのまま引き継ぐ。leaseが
    見つからない(未acquire、または他プロセスに削除された)場合はacquireと
    同じ動作にフォールバックする。"""
    ts = now if now is not None else time.time()
    current = read(run_dir)
    if current is None:
        return acquire(run_dir, now=ts)
    lease = Lease(pid=current.pid, generation=current.generation,
                  heartbeat_at=ts)
    _write(run_dir, lease)
    return lease


def read(run_dir: str | Path) -> Lease | None:
    """leaseファイルを読む。存在しない・JSON破損・キー欠損はすべて『leaseなし』
    (None)として扱う(他プロセスの書き込み途中を例外で落とさないため)。"""
    try:
        data = json.loads(_lease_path(run_dir).read_text())
        return Lease(pid=int(data["pid"]), generation=str(data["generation"]),
                     heartbeat_at=float(data["heartbeat_at"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def release(run_dir: str | Path) -> None:
    """leaseファイルを削除する(ミッション正常終了時)。存在しなくても何もしない。"""
    try:
        _lease_path(run_dir).unlink()
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    """OSレベルでpidのプロセスが存在するか。シグナル0番は実際には配送されず、
    カーネルの存在チェックのみが働く(POSIX標準の生存確認手法)。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # 別ユーザ所有だが存在はする(orghを複数ユーザで動かす運用は想定外
        # だが、安全側=生存扱いにしておく)
        return True
    except OSError:
        return False
    return True


def is_alive(run_dir: str | Path, now: float | None = None) -> bool:
    """leaseが『生きている』か判定する。

    条件は (1) heartbeat_atがLEASE_EXPIRY_SEC以内 かつ (2) 記録されたpidの
    プロセスがOS上に存在すること、の両方。両方を要求する理由:
    heartbeat_atだけだと更新間隔中の一時的な遅延で誤って失効扱いになりうる
    一方、pid生存チェックだけだとPID再利用によるゾンビleaseの誤判定を防げ
    ない。nowを注入可能にしているのはテストで実時間を待たずに失効/生存を
    固定して検証するため。
    """
    lease = read(run_dir)
    if lease is None:
        return False
    ts = now if now is not None else time.time()
    if ts - lease.heartbeat_at > LEASE_EXPIRY_SEC:
        return False
    return _pid_alive(lease.pid)

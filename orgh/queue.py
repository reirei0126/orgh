"""永続有界ミッションキュー(R-1: watch/executor分離)。

runs/_queue/<mission_id>.json をエントリとするファイルキュー。runs/配下の
ファイル永続の流儀に合わせ、プロセス再起動・クラッシュで内容が失われない。

- enqueue: tmp書き→renameの原子的作成。上限(limit)超は投入拒否(False)。
  既存IDへの二重投入は冪等にTrue(watchの再パスで安全)
- claim: エントリファイルへのflock(EX|NB)。fd保持中は他プロセスがスキップ
  する。コンシューマのクラッシュ(kill -9含む)ではOSがflockを解放するため
  エントリは自動的に再claim可能に戻る(固着しない)
- 完了(done=True)でエントリ削除、失敗(done=False)はclaim解除のみ
  (再試行可能に残す)
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
from pathlib import Path

_ID_RE = re.compile(r"[A-Za-z0-9_-]+\Z")


def _qdir(runs_dir: str | Path) -> Path:
    return Path(runs_dir) / "_queue"


def _entries(d: Path) -> list[Path]:
    """FIFO順(作成時刻→名前)のエントリファイル一覧。

    glob〜statの間に他プロセスの消化(unlink)が挟まりうるため、statの
    FileNotFoundErrorは「消えたエントリ」としてスキップする。"""
    if not d.is_dir():
        return []
    keyed = []
    for f in d.glob("*.json"):
        try:
            keyed.append((f.stat().st_mtime_ns, f.name, f))
        except FileNotFoundError:
            continue
    return [f for _, _, f in sorted(keyed, key=lambda x: (x[0], x[1]))]


def enqueue(runs_dir: str | Path, mission_id: str,
            note_path: str | None = None, limit: int | None = 20) -> bool:
    """ミッションをキューへ投入する。満杯ならFalse(呼び出し側が見送る)。
    limit=None は無制限: 事前チェック済みで「計画コストを支払った後は必ず投入
    したい」プロデューサ(watch)が使う。"""
    if not _ID_RE.fullmatch(mission_id):
        raise ValueError(f"invalid mission_id: {mission_id!r}")
    d = _qdir(runs_dir)
    d.mkdir(parents=True, exist_ok=True)
    target = d / f"{mission_id}.json"
    if target.exists():
        return True
    if limit is not None and len(_entries(d)) >= limit:
        return False
    tmp = d / f".{mission_id}.tmp"
    tmp.write_text(json.dumps(
        {"mission_id": mission_id, "note_path": note_path,
         "enqueued_at": time.time()}, ensure_ascii=False))
    tmp.rename(target)
    return True


def claim_next(runs_dir: str | Path):
    """最古の未claimエントリを確保する。

    返り値は (entry_dict, release) か None。release(done=True) でエントリを
    削除、release(done=False) でclaimだけ解除して再試行可能に残す。
    """
    for f in _entries(_qdir(runs_dir)):
        try:
            fp = open(f, "r+")
        except FileNotFoundError:
            continue                      # 消化直後の競合: 次へ
        try:
            fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fp.close()
            continue                      # 他プロセスがclaim中
        # done済み・同名再作成の検知はパスの存在ではなくinode同一性で行う
        # (パスだけ見ると、孤児inodeを掴んだまま同名の新エントリと二重実行しうる)
        try:
            if os.fstat(fp.fileno()).st_ino != os.stat(f).st_ino:
                fp.close()
                continue
        except FileNotFoundError:
            fp.close()                    # claim競合の隙間でdone済み
            continue
        try:
            entry = json.loads(fp.read())
        except json.JSONDecodeError:
            # 壊れたエントリはflock保持中に隔離する(解放後だと二重コンシューマの
            # rename競合でFileNotFoundErrorが漏れる)
            try:
                f.rename(f.with_suffix(".bad"))
            except FileNotFoundError:
                pass
            fp.close()
            continue

        def release(done: bool, _fp=fp, _f=f) -> None:
            if done:
                _f.unlink(missing_ok=True)
            _fp.close()                   # closeでflockも解放される

        return entry, release
    return None


def pending(runs_dir: str | Path) -> list[dict]:
    """FIFO順のエントリ一覧(watchの満杯チェックとlisting/statusのqueued判定が使う)。"""
    out = []
    for f in _entries(_qdir(runs_dir)):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return out

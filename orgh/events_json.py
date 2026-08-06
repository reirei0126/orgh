"""orgh events <mission_id> --json 用のペイロード組み立て(機械可読)。

ledger.jsonl を直接読む(RunStore.load() は mission.json 前提かつ実行中系
ステータスの巻き戻し副作用を持つため、ここでは使わない)。
"""
from __future__ import annotations

import json
from pathlib import Path


# tail読みで一度に遡るバイト数。1イベント行は概ね数百バイトなので
# 100件のtailには十分。足りなければ倍々で追加読みする
_TAIL_CHUNK = 256 * 1024


def _iter_valid(lines: list[str]) -> list[dict]:
    """イベントとして妥当な行のみ採用する。

    JSONとして読める行でも `null` や `[]` のような非イベント形はスキップする
    (1行混じるだけでGUI側のLedgerEventデシリアライズが全件失敗するため)。
    """
    events: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict) or \
                not isinstance(ev.get("ts"), (int, float)) or \
                not isinstance(ev.get("event"), str):
            continue
        events.append(ev)
    return events


def events_payload(runs_dir: str | Path, mission_id: str,
                    tail: int = 100) -> dict:
    """mission_id の ledger.jsonl を読み、末尾 tail 件を返す純関数。

    壊れた行(JSONとして読めない行・イベント形でない行)はスキップする。
    tail指定時はファイル末尾からチャンク単位で読む(GUIが数秒おきにポーリング
    するため、ledgerの成長に比例して全読みしない)。
    """
    fp = Path(runs_dir) / mission_id / "ledger.jsonl"
    if not fp.exists():
        return {"mission_id": mission_id, "events": []}

    if tail is None:
        return {"mission_id": mission_id,
                "events": _iter_valid(fp.read_text().splitlines())}
    if tail <= 0:
        return {"mission_id": mission_id, "events": []}

    size = fp.stat().st_size
    chunk = _TAIL_CHUNK
    with open(fp, "rb") as f:
        while True:
            start = max(0, size - chunk)
            f.seek(start)
            data = f.read().decode("utf-8", errors="replace")
            lines = data.splitlines()
            if start > 0:
                # チャンク先頭の行は途中から始まっている可能性があるため捨てる
                lines = lines[1:]
            events = _iter_valid(lines)
            if len(events) >= tail or start == 0:
                return {"mission_id": mission_id, "events": events[-tail:]}
            chunk *= 2

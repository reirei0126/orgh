"""orgh events <mission_id> --json 用のペイロード組み立て(機械可読)。

ledger.jsonl を直接読む(RunStore.load() は mission.json 前提かつ実行中系
ステータスの巻き戻し副作用を持つため、ここでは使わない)。
"""
from __future__ import annotations

import json
from pathlib import Path


def events_payload(runs_dir: str | Path, mission_id: str,
                    tail: int = 100) -> dict:
    """mission_id の ledger.jsonl を読み、末尾 tail 件を返す純関数。

    壊れた行(JSONとして読めない行)はスキップする。
    """
    fp = Path(runs_dir) / mission_id / "ledger.jsonl"
    events: list[dict] = []
    if fp.exists():
        for line in fp.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if tail is not None:
        events = events[-tail:] if tail > 0 else []

    return {"mission_id": mission_id, "events": events}

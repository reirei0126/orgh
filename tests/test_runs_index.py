"""runs索引化(ヘルスレビュー deferred: list/report線形走査)。
終端ミッションはmtime署名でキャッシュし全読みを避ける。結果は非キャッシュと同一。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from orgh import listing
from orgh.listing import list_missions_report


def _mk(runs, mid, status, created_ts=1000.0, finished_ts=None):
    d = runs / mid
    d.mkdir(parents=True)
    (d / "mission.json").write_text(json.dumps({
        "id": mid, "intent": mid, "context_digest": "",
        "tasks": [{"id": "t1", "title": "x", "prompt": "p",
                   "worker": "claude_code", "deps": [], "status": status,
                   "attempts": 1}],
        "budget": {"limit_usd": None, "spent_usd": 1.0}}))
    ev = [{"ts": created_ts, "event": "task.start", "task": "t1"}]
    if finished_ts:
        ev.append({"ts": finished_ts, "event": "mission.finished", "done": ["t1"]})
    (d / "ledger.jsonl").write_text("\n".join(json.dumps(e) for e in ev))
    return d


def test_index_created_and_reused(tmp_path):
    runs = tmp_path / "runs"
    _mk(runs, "done1", "done", 1000.0, 1500.0)
    r1 = list_missions_report(runs)
    assert (runs / "_index.json").exists()
    assert r1["missions"][0]["mission_id"] == "done1"
    # 2回目: _summarize_mission を呼ばず索引から返す
    called = {"n": 0}
    real = listing._summarize_mission
    listing._summarize_mission = lambda d: (called.__setitem__("n", called["n"] + 1), real(d))[1]
    try:
        r2 = list_missions_report(runs)
    finally:
        listing._summarize_mission = real
    assert called["n"] == 0  # 終端ミッションは再集計されない
    assert r2["missions"] == r1["missions"]


def test_cache_invalidated_on_change(tmp_path):
    runs = tmp_path / "runs"
    d = _mk(runs, "m1", "done", 1000.0, 1500.0)
    list_missions_report(runs)
    time.sleep(0.01)
    # mission.jsonを書き換え(cost変更)→署名が変わり再集計される
    data = json.loads((d / "mission.json").read_text())
    data["budget"]["spent_usd"] = 9.9
    (d / "mission.json").write_text(json.dumps(data))
    r = list_missions_report(runs)
    assert r["missions"][0]["cost_usd"] == 9.9


def test_running_mission_not_cached(tmp_path):
    runs = tmp_path / "runs"
    _mk(runs, "run1", "running", 1000.0)
    list_missions_report(runs)
    idx = json.loads((runs / "_index.json").read_text())
    assert "run1" not in idx  # 実行中はキャッシュ対象外


def test_result_matches_uncached(tmp_path):
    runs = tmp_path / "runs"
    _mk(runs, "aaa", "done", 1000.0, 1200.0)
    _mk(runs, "zzz", "done", 9000.0, 9200.0)
    _mk(runs, "run1", "running", 5000.0)
    cached = list_missions_report(runs)
    (runs / "_index.json").unlink()
    uncached = list_missions_report(runs)
    assert cached["missions"] == uncached["missions"]
    # 起票日時の新しい順
    assert [m["mission_id"] for m in cached["missions"]] == ["zzz", "run1", "aaa"]

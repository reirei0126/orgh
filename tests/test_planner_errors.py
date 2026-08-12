"""実運用で発見: 役割呼び出し失敗時に result が空だと原因が見えない。

claude headlessは max_turns 超過等で is_error かつ result空 を返すことがある。
その場合は raw(封筒JSON全体。subtypeに失敗理由が入っている)を
エラーメッセージへ含めること。
"""
from __future__ import annotations

import pytest

from orgh import planner
from orgh.adapters.base import WorkerResult


class _EmptyFailureAdapter:
    def run(self, *a, **kw):
        return WorkerResult(ok=False, output="",
                            raw='{"subtype":"error_max_turns","is_error":true}')


class TestAskJsonObservability:
    def test_empty_output_failure_includes_raw(self, cfg, monkeypatch):
        monkeypatch.setattr(planner, "get_adapter",
                            lambda *a, **kw: _EmptyFailureAdapter())
        with pytest.raises(RuntimeError, match="error_max_turns"):
            planner._ask_json(cfg, "planner", "x")


class _MalformedThenValidAdapter:
    """1回目は壊れたJSON、2回目から正しいJSONを返す。実測(mission 8bc7ce00 t3の
    replan)で、LLMの長文JSON応答が途中の書式エラーでJSONDecodeErrorになり
    タスクがfailedに化けた再現。"""

    def __init__(self, fail_times: int = 1):
        self.calls: list[str] = []
        self._fail_times = fail_times

    def run(self, prompt, **kw):
        self.calls.append(prompt)
        if len(self.calls) <= self._fail_times:
            return WorkerResult(ok=True, output='{"a": 1, "b" 2}',  # ','欠落
                                cost_usd=0.5)
        return WorkerResult(ok=True, output='{"a": 1, "b": 2}', cost_usd=0.5)


class TestAskJsonMalformedRetry:
    def test_malformed_json_is_retried_with_correction(self, cfg, monkeypatch):
        ad = _MalformedThenValidAdapter(fail_times=1)
        monkeypatch.setattr(planner, "get_adapter", lambda *a, **kw: ad)
        out = planner._ask_json(cfg, "planner", "x")
        assert out == {"a": 1, "b": 2}
        assert len(ad.calls) == 2
        # 再要求プロンプトには元指示と修正指示の両方が含まれること
        assert "x" in ad.calls[1]
        assert "JSON" in ad.calls[1]

    def test_gives_up_after_three_attempts(self, cfg, monkeypatch):
        import json as _json
        ad = _MalformedThenValidAdapter(fail_times=99)
        monkeypatch.setattr(planner, "get_adapter", lambda *a, **kw: ad)
        with pytest.raises(_json.JSONDecodeError):
            planner._ask_json(cfg, "planner", "x")
        assert len(ad.calls) == 3

    def test_all_attempts_are_charged(self, cfg, monkeypatch):
        ad = _MalformedThenValidAdapter(fail_times=1)
        monkeypatch.setattr(planner, "get_adapter", lambda *a, **kw: ad)
        sink: list[float] = []
        planner._ask_json(cfg, "planner", "x", cost_sink=sink)
        assert sink == [0.5, 0.5]

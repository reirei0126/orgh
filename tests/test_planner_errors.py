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

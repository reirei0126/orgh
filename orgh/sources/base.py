"""入力層の SourceAdapter 抽象化(HANDOFF タスク3)。

watcher / cli はこのインターフェース経由でのみ入力ソースに触れる。
Obsidian vault 固有のロジックは sources/obsidian.py に閉じる。
将来の入力ソース(Notion等)は REGISTRY にアダプタを足すだけで差し替えられる
(Notionアダプタ自体はここでは実装しない — 拡張点の確保のみ)。
"""
from __future__ import annotations

from typing import Any


class MissionFeedback:
    """ミッション進行のソース側フィードバック(結果ノート等)。既定は何もしない。"""

    def update(self, mission) -> None:
        pass

    def finalize(self, mission, store) -> None:
        pass

    def cancel_requested(self) -> bool:
        return False


class SourceAdapter:
    """入力ソースの共通インターフェース。

    Note型はアダプタ実装の内部表現でよいが、title / path 属性を持つこと
    (cli の一覧表示と検索が使う)。
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg

    # --- ミッション候補 -----------------------------------------------------
    def list_candidates(self) -> list[Any]:
        """ミッション候補の列挙(orgh scan 用。着火条件は問わない)。"""
        raise NotImplementedError

    def should_trigger(self, note) -> bool:
        """候補を今すぐ着火してよいか(明示着火タグ・安定化などの判定)。"""
        raise NotImplementedError

    def find(self, query: str):
        """タイトル(部分一致可)でノートを1件探す。無ければ None。"""
        raise NotImplementedError

    # --- 文脈と書き戻し -----------------------------------------------------
    def build_context(self, note) -> str:
        """Plannerに渡す文脈ダイジェストの構築。"""
        raise NotImplementedError

    def writeback(self, note, mission) -> None:
        """着火の結果をソースへ書き戻す(元ノートへのリンク1行など)。"""
        raise NotImplementedError

    def notify_failure(self, note, message: str) -> None:
        """mission_id採番前の失敗(Planner失敗等)をソースへ通知する。"""
        raise NotImplementedError

    def feedback(self, mission_id: str) -> MissionFeedback:
        """進行・結果・キャンセル検知のフィードバック窓口。既定は無効(no-op)。"""
        return MissionFeedback()

    # --- 着火済み管理 -------------------------------------------------------
    def mark_processed(self, note) -> None:
        raise NotImplementedError

    def is_processed(self, note) -> bool:
        raise NotImplementedError

    def describe(self) -> str:
        """監視対象の人間向け説明(watch起動時のログ用)。"""
        return type(self).__name__


def get_source(cfg: dict) -> SourceAdapter:
    """config の source.type でアダプタを選択する(既定 obsidian)。"""
    from .obsidian import ObsidianAdapter

    registry = {"obsidian": ObsidianAdapter}
    stype = (cfg.get("source") or {}).get("type", "obsidian")
    if stype not in registry:
        raise KeyError(
            f"unknown source type '{stype}'. available: {list(registry)}")
    return registry[stype](cfg)

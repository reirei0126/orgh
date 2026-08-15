"""Orchestrator: DAGに従いWorkerを並列起動する実行系のfacade。

実体は責務別のサブモジュールにある(R-3分割, docs/refactor/execution-architecture.md):
- scheduler        — DAG解決・並列dispatch・ミッションライフサイクル
- task_executor    — 1タスクのattemptループ・worker起動・成果コミット
- review_pipeline  — reviewer+persona検収の直列裁定・ロールリトライ
- cancellation     — CANCELフラグの検知・開始・待機(横断ポリシー)
- budget_policy    — 予算プールの用意と超過停止(横断ポリシー)

公開APIは run_mission / acquire_mission_lock / TERMINAL。アンダースコア付き
aliasは既存テストの「直接import・直接呼び出し」互換のためだけに残している。
**monkeypatchの標的にはならない**: 実行は各サブモジュールのグローバル解決を
通るため、このfacadeのaliasを差し替えても実挙動は変わらない。patchは定義元
(orgh.orchestrator.task_executor 等)に当てること。新規コードは各サブ
モジュールから公開名をimportすること。
"""
from .cancellation import CancelledDuringRole as _CancelledDuringRole
from .review_pipeline import review_with_retry as _review_with_retry
from .scheduler import (TERMINAL, acquire_mission_lock, run_mission,
                        assign_personas as _assign_personas)
from .task_executor import (full_worker_prompt as _full_worker_prompt,
                            is_capability_error as _is_capability_error,
                            is_infra_error as _is_infra_error,
                            retry_prompt as _retry_prompt,
                            run_task as _run_task)

__all__ = ["TERMINAL", "acquire_mission_lock", "run_mission"]

"""task_executorへのcopyback結線(direction-2026-08 §4 3a')。

コアロジック(manifest照合・パス閉包・原子コピー)は orgh/copyback.py に置いたまま
ここでは「いつ発動し、どう記録し、失敗時にタスクをどう扱うか」だけを担う:

- 発動条件: workerがworktree直下に orgh-manifest.json を出力した場合のみ。
  無ければ start_review_gate() は None を返し、呼び出し側(task_executor)は
  従来経路を一切変えない(後方互換が最優先)。成果物自体は worktree 直下の
  `_orgh_staging/`(既定。manifestの`staging_dir`キーで変更可)に置く契約。
- start_review_gate() と finalize()(→run_copyback())はいずれも同一の
  t.workdir(worktree直下)をverify_manifest()に渡す。staging_dirはmanifestの
  内容から都度導出されるため、staging凍結の前提のもとで両呼び出しの解決結果は
  一致する(orgh/copyback.pyのverify_manifest/run_copyback参照)。
- 実行順: manifest照合(=copyback.manifest ledgerイベント)は検収開始時
  (review遷移直後)に行い、以後stagingを凍結扱いとする。実際のコピーは
  検収合格後にのみ行い、run_copyback() 内部でコピー直前の再検証も行う
  (その結果も copyback.manifest として二重に記録し、監査の正本である
  ledgerだけを見れば両時点の照合結果が追える状態にする)。
- 宛先(dest_root)は manifest JSON トップレベルの "dest_root" キー(絶対パス
  文字列)から読む。verify_manifest() はfiles一覧の照合にしか関心を持たない
  ため、宛先の指定方法自体はorchestrator側(=このモジュール)の関心。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ..copyback import (
    DEFAULT_STAGING_DIR,
    MANIFEST_FILENAME,
    CopybackError,
    run_copyback,
    snapshot_tree,
    verify_manifest,
)
from ..state import RunStore, Task
from .transitions import enter_awaiting_human, transition


def has_manifest(t: Task) -> bool:
    return (Path(t.workdir) / MANIFEST_FILENAME).exists()


def _worktree_repo_root(workdir: str) -> Path | None:
    """t.workdir が `<repo>/.orgh-worktrees/<mission>-<task>` 形の場合、
    `.orgh-worktrees` の親(=対象リポのルート)を返す。純粋なパス演算のみ
    (gitコマンド不要)。その形でなければNone。"""
    parts = Path(workdir).parts
    if ".orgh-worktrees" not in parts:
        return None
    idx = parts.index(".orgh-worktrees")
    if idx == 0:
        return None
    return Path(*parts[:idx])


def _git_repo_root_candidate(workdir: str) -> Path | None:
    """git-common-dirの親から本体リポを導く補助経路。gitが無い/失敗する場合は
    静かにNoneを返す(例外を外へ出さない)。"""
    try:
        r = subprocess.run(
            ["git", "-C", str(workdir), "rev-parse",
             "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return Path(r.stdout.strip()).parent
    except Exception:
        return None


def _detect_misplacement(t: Task) -> Path | None:
    """has_manifest(t)がFalseのとき、実リポ直下への誤配置(escape第2号
    実測 runs/af7c4832)を疑い、候補ディレクトリに manifest と staging の
    両方が存在すればその候補パスを返す。候補が無ければNone(挙動不変)。"""
    candidates: list[Path] = []
    primary = _worktree_repo_root(t.workdir)
    if primary is not None:
        candidates.append(primary)
    secondary = _git_repo_root_candidate(t.workdir)
    if secondary is not None and secondary not in candidates:
        candidates.append(secondary)
    for c in candidates:
        if (c / MANIFEST_FILENAME).exists() and (c / DEFAULT_STAGING_DIR).exists():
            return c
    return None


def check_misplaced(store: RunStore, cfg: dict, t: Task) -> bool:
    """has_manifest(t)がFalseの場合に呼ぶ。誤配置を検知したら
    copyback.misplaced をledgerへ記録し、awaiting_humanへ差し戻してTrueを
    返す(呼び出し側はレビューへ進まずtaskを返すこと)。誤配置候補が無ければ
    何もせずFalse(=従来動作)。"""
    misplaced_root = _detect_misplacement(t)
    if misplaced_root is None:
        return False
    store.log("copyback.misplaced", task=t.id, misplaced_root=str(misplaced_root))
    enter_awaiting_human(
        store, cfg, t,
        f"copyback成果物(orgh-manifest.json / {DEFAULT_STAGING_DIR})が割り当て"
        f"られたworktree直下ではなく実リポ直下({misplaced_root})に作られた"
        f"疑いがある(機械検知。escape第2号 runs/af7c4832 相当)。",
        refund_attempt=False)
    return True


def _read_dest_root(workdir: str) -> str | None:
    """manifestの"dest_root"(worker記載の書き戻し先・絶対パス)を読む。
    欠落・非文字列・相対パスはすべてNone(呼び出し側でcopyback.partial扱い)。"""
    manifest_path = Path(workdir) / MANIFEST_FILENAME
    try:
        raw = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    dest = raw.get("dest_root")
    if isinstance(dest, str) and dest and Path(dest).is_absolute():
        return dest
    return None


def start_review_gate(store: RunStore, t: Task) -> dict[str, Any] | None:
    """検収開始時(review遷移直後)に呼ぶ。manifest無しはNone(=copyback非発動)。

    manifestありの場合、この時点でstagingを再検証して copyback.manifest を
    記録し、宛先の"実行開始前"スナップショットを取る(以後の変化が
    copyback_conflictの検知対象になる)。戻り値のdictは合格後に finalize()
    へそのまま渡すこと。
    """
    if not has_manifest(t):
        return None
    verification = verify_manifest(t.workdir)
    store.log("copyback.manifest", task=t.id, stage="review_start",
              **verification.as_ledger_payload())
    dest_root = _read_dest_root(t.workdir)
    baseline_snapshot = snapshot_tree(dest_root) if dest_root else None
    return {"dest_root": dest_root, "baseline_snapshot": baseline_snapshot}


def finalize(store: RunStore, cfg: dict, t: Task, ctx: dict[str, Any]) -> bool:
    """検収合格後に呼ぶ。staging→dest_rootへ実際にコピーし、結果をledgerへ
    記録してタスク状態を決める。戻り値True: 呼び出し側はdone確定してよい。
    戻り値False: 既にfailed/awaiting_humanへ遷移済み(呼び出し側はdoneにしない)。
    """
    dest_root = ctx.get("dest_root")
    if not dest_root:
        store.log("copyback.partial", task=t.id, dest_root=None,
                  reason="manifestのdest_rootが未指定または絶対パスでない")
        transition(store, t, "failed",
                  notes="copyback: manifestのdest_rootが未指定または絶対パスでない")
        return False

    allowed_roots = list((cfg.get("copyback") or {}).get("allowed_roots") or [])
    try:
        verification, result = run_copyback(
            t.workdir, dest_root, allowed_roots,
            baseline_snapshot=ctx.get("baseline_snapshot"))
    except CopybackError as e:
        store.log("copyback.partial", task=t.id, dest_root=dest_root,
                  reason=str(e))
        transition(store, t, "failed", notes=f"copyback: 宛先が拒否された: {e}")
        return False

    store.log("copyback.manifest", task=t.id, stage="pre_copy",
              **verification.as_ledger_payload())

    if result.status == "completed":
        store.log("copyback.completed", task=t.id, **result.as_ledger_payload())
        return True

    if result.status == "conflict":
        store.log("copyback.conflict", task=t.id, **result.as_ledger_payload())
        # ⚠ 事前hash突合による検知であり、セキュリティ保証ではない(同時書き込み
        # や悪意ある置き換えを確実に捉えるものではない。強制可能な土台
        # (sandbox等)が入るまでの「忘れないための検知」に留まる)
        enter_awaiting_human(
            store, cfg, t,
            f"copyback競合: 宛先がworker実行中に変化した可能性がある(暫定検知/"
            f"セキュリティ保証ではない)。{result.reason}",
            refund_attempt=False)
        return False

    # "partial"(コピー途中失敗・hash不一致による人間裁定)と
    # "manifest_invalid"(コピー直前の再検証で不整合が見つかった)はどちらも
    # 「配達未完了」として同一の扱いにする(専用ledgerイベントを持たない)
    store.log("copyback.partial", task=t.id, **result.as_ledger_payload())
    transition(store, t, "failed",
              notes=f"copyback失敗(partial): {result.reason}")
    return False

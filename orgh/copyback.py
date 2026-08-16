"""copyback契約: git管理外の成果物領域への安全な書き戻し(direction-2026-08 §4 3a')。

対象領域がgit管理外(例: decision-osの private/cases/)の場合、orghのworktree→
branch→diff受け渡しが全て空振りするため、workerがworktree(staging)直下に出力する
`orgh-manifest.json`(相対パス・サイズ・SHA-256の一覧)を照合しながら、staging→宛先
ルートへ原子的にコピーバックする。orchestratorへの結線は別モジュール(後続タスク)。

契約の要点:
- staging限定実行が前提。staging外(worker実行対象の宛先そのもの)への直接書き込み
  防止はここでは強制できない(sandbox/filesystem強制が無い)。
- パスは正規化のうえ、staging/宛先いずれのルートにも閉包させる。絶対パス・`..`・
  symlink・manifest未列挙ファイルはすべて拒否する。
- コピーは「一時ディレクトリへ全量配置→再検証→rename」の順で行い、途中失敗時に
  宛先が半端な状態で汚染されないようにする(= copyback_partial)。
- ⚠ 宛先の事前hashとの突合による競合検知(copyback_conflict)は暫定運用であり、
  セキュリティ保証ではない(同じhashでも同時書き込みや悪意ある置き換えは検知できない。
  強制可能な土台(sandbox等)が入るまでの「忘れないための検知」でしかない)。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_FILENAME = "orgh-manifest.json"


class CopybackError(ValueError):
    """呼び出し側の契約違反(allowed_roots外の宛先指定など)。続行不能。"""


@dataclass
class ManifestEntry:
    """manifestの1エントリ(正規化済み相対パス・サイズ・SHA-256)。"""
    path: str
    size: int
    sha256: str


@dataclass
class ManifestVerification:
    """`copyback.manifest` ledgerイベントの情報源。

    ok: 全件がmanifestと一致し、閉包・symlink違反・未列挙ファイルが無ければTrue
    entries: 検証済みのManifestEntry一覧(正規化済みpath)
    rejected: {元のmanifest記載path(または実ファイルの相対path): 拒否理由}
              絶対パス/'..'/symlink/manifest未列挙ファイル/要素型不正など
    mismatches: {正規化path: 差分の説明} サイズまたはSHA-256が不一致
    missing: manifestに記載があるがstagingに実体が無いパスの一覧
    """
    ok: bool
    entries: list[ManifestEntry] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)
    mismatches: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def as_ledger_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "file_count": len(self.entries),
            "rejected": self.rejected,
            "mismatches": self.mismatches,
            "missing": self.missing,
        }


@dataclass
class CopybackResult:
    """`copyback.completed` / `copyback.partial` / `copyback.conflict` ledgerイベントの情報源。

    status: "completed" | "partial" | "conflict" | "manifest_invalid"
    dest_root: 宛先ルート(文字列)
    copied: 実際にコピーした正規化済み相対パス
    skipped: 既に宛先にhash一致で存在するためskipした相対パス(冪等再実行)
    blocked: 宛先に既存かつhash不一致のため自動上書きせず人間裁定へ回した相対パス
             (`copyback_conflict` 相当の"third-partyが書き換えた宛先"もここに乗る)
    failed: コピー処理中に例外で失敗した相対パス
    reason: 人間可読な失敗・停止理由(partial/conflict/manifest_invalid時)
    呼び出し側は status に応じて `copyback.completed`/`copyback.partial`/
    `copyback.conflict` のいずれかをledgerに追記し、"partial"/"conflict" の場合は
    タスクをdoneにせず、blocked/failed/reasonを人間裁定材料として提示する。
    """
    status: str
    dest_root: str
    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    reason: str | None = None

    def as_ledger_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "dest_root": self.dest_root,
            "copied": self.copied,
            "skipped": self.skipped,
            "blocked": self.blocked,
            "failed": self.failed,
            "reason": self.reason,
        }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_relpath_reason(root: Path, rel: str) -> str | None:
    """rel が root 内へ閉包し、'..'/絶対パス/symlinkを含まないかを検査する。

    問題なければNone、問題があれば拒否理由の文字列を返す。
    """
    if not isinstance(rel, str) or not rel:
        return "パスが空または不正"
    p = PurePosixPath(rel)
    if p.is_absolute():
        return "絶対パスは拒否"
    parts = p.parts
    if not parts or any(part == ".." for part in parts):
        return "'..'を含むパスは拒否"
    cur = root
    for part in parts:
        cur = cur / part
        if cur.is_symlink():
            return "symlinkは拒否"
    try:
        resolved = (root / rel).resolve(strict=False)
        resolved_root = root.resolve(strict=False)
    except OSError:
        return "パス解決に失敗"
    if not resolved.is_relative_to(resolved_root):
        return "ルート外へ閉包していない"
    return None


def _walk_files(root: Path):
    """root配下の全ファイル相対パス(posix形式)を列挙する。symlinkディレクトリは
    再帰せず、symlinkそのものを「ファイル相当」として列挙する(閉包検査に委ねる)。
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dp = Path(dirpath)
        kept_dirs = []
        extra_files = []
        for d in dirnames:
            if (dp / d).is_symlink():
                extra_files.append(d)
            else:
                kept_dirs.append(d)
        dirnames[:] = kept_dirs
        for name in list(filenames) + extra_files:
            full = dp / name
            yield full.relative_to(root).as_posix()


def verify_manifest(staging_dir: Path | str,
                     manifest_filename: str = MANIFEST_FILENAME) -> ManifestVerification:
    """staging直下のmanifestを読み、実ファイルと再計算した size/SHA-256 を突合する。

    検収開始時・コピー直前のいずれからも呼ばれる想定(呼ぶたびに全量再計算する
    ="staging凍結の検証"であり、キャッシュは持たない)。
    """
    staging_dir = Path(staging_dir)
    manifest_path = staging_dir / manifest_filename
    if not manifest_path.exists():
        return ManifestVerification(
            ok=False, rejected={manifest_filename: "manifestファイルが存在しない"})
    try:
        raw = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return ManifestVerification(
            ok=False, rejected={manifest_filename: f"manifestの読み取りに失敗: {e}"})

    items = raw.get("files") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return ManifestVerification(
            ok=False, rejected={manifest_filename: "'files'がリストでない"})

    entries: list[ManifestEntry] = []
    rejected: dict[str, str] = {}
    mismatches: dict[str, str] = {}
    missing: list[str] = []
    listed: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            rejected[str(item)] = "manifest要素がマップでない"
            continue
        rel = item.get("path")
        size = item.get("size")
        sha256 = item.get("sha256")
        label = rel if isinstance(rel, str) else str(rel)
        if not isinstance(rel, str) or not isinstance(size, int) or \
                isinstance(size, bool) or not isinstance(sha256, str):
            rejected[label] = "path/size/sha256の型が不正"
            continue

        reason = _safe_relpath_reason(staging_dir, rel)
        if reason:
            rejected[rel] = reason
            continue

        normalized = "/".join(PurePosixPath(rel).parts)
        listed.add(normalized)
        full = staging_dir / normalized
        if not full.exists():
            missing.append(normalized)
            continue
        if full.is_symlink() or not full.is_file():
            rejected[normalized] = "symlinkまたは通常ファイルでない"
            continue
        actual_size = full.stat().st_size
        actual_hash = _sha256(full)
        if actual_size != size or actual_hash != sha256:
            mismatches[normalized] = (
                f"size={actual_size}(期待{size}) sha256={actual_hash}(期待{sha256})")
            continue
        entries.append(ManifestEntry(path=normalized, size=size, sha256=sha256))

    for rel in _walk_files(staging_dir):
        if rel == manifest_filename:
            continue
        if rel not in listed:
            rejected[rel] = "manifest未列挙ファイル"

    ok = not rejected and not mismatches and not missing
    return ManifestVerification(ok=ok, entries=entries, rejected=rejected,
                                mismatches=mismatches, missing=missing)


def snapshot_tree(root: Path | str) -> dict[str, str]:
    """root配下の全通常ファイルの {正規化相対パス: SHA-256} を返す。

    copybackの原子性契約(§4 3a')における「宛先の事前hash記録」に使う。
    workerの実行開始前に取得したスナップショットを `run_copyback` の
    `baseline_snapshot` に渡すと、実行中の宛先変化を検知できる
    (⚠ 暫定運用でありセキュリティ保証ではない。モジュールdocstring参照)。
    """
    root = Path(root)
    if not root.exists():
        return {}
    out: dict[str, str] = {}
    for rel in _walk_files(root):
        full = root / rel
        if full.is_symlink() or not full.is_file():
            continue
        out[rel] = _sha256(full)
    return out


def _check_allowed_root(dest_root: Path, allowed_roots: list[str]) -> None:
    dest_resolved = dest_root.resolve(strict=False)
    for root in allowed_roots or []:
        root_path = Path(root)
        if not root_path.is_absolute():
            continue
        root_resolved = root_path.resolve(strict=False)
        if dest_resolved == root_resolved or dest_resolved.is_relative_to(root_resolved):
            return
    raise CopybackError(
        f"copyback: 宛先 {dest_root} が config.copyback.allowed_roots のいずれにも"
        "含まれない(direction-2026-08 §4 3a')")


def _copy_file(src: Path, dst: Path) -> None:
    """1ファイルをコピーする(テストからmonkeypatchして失敗注入する接合点)。"""
    shutil.copy2(src, dst)


def run_copyback(staging_dir: Path | str, dest_root: Path | str,
                  allowed_roots: list[str], *,
                  baseline_snapshot: dict[str, str] | None = None,
                  manifest_filename: str = MANIFEST_FILENAME,
                  ) -> tuple[ManifestVerification, CopybackResult]:
    """manifestを再検証し、staging→dest_rootへ原子的にコピーバックする。

    手順(§4 3a'契約どおり):
    1. dest_rootがallowed_roots配下か検査(外れていればCopybackError)
    2. manifestをstagingに対して再計算・再検証(=コピー直前の再検証)
    3. baseline_snapshotが渡されていれば、宛先の該当ファイルが記録時から
       変化していないか突合する。変化していれば `copyback_conflict`
       (⚠ 暫定運用でありセキュリティ保証ではない)
    4. 宛先ファイルごとにhash一致ならskip、不一致(既存かつ違う内容)なら
       blockedとして人間裁定へ回し、この時点で停止する(自動上書きしない)
    5. 残る新規ファイルを一時ディレクトリへ全量コピーし、再検証してから
       rename で最終宛先へ配置する(=copyback_partialの回避: 途中失敗時は
       renameフェーズへ進まないため宛先は書き換わらない)

    戻り値は (ManifestVerification, CopybackResult) のタプル。呼び出し側は
    前者を `copyback.manifest`、後者のstatusに応じて `copyback.completed` /
    `copyback.partial` / `copyback.conflict` のledgerイベントに使う。
    """
    staging_dir = Path(staging_dir)
    dest_root = Path(dest_root)
    _check_allowed_root(dest_root, allowed_roots)

    verification = verify_manifest(staging_dir, manifest_filename)
    if not verification.ok:
        return verification, CopybackResult(
            status="manifest_invalid", dest_root=str(dest_root),
            reason=(f"manifest検証失敗: rejected={sorted(verification.rejected)} "
                    f"mismatches={sorted(verification.mismatches)} "
                    f"missing={sorted(verification.missing)}"))

    if baseline_snapshot is not None:
        current = snapshot_tree(dest_root)
        changed = sorted(p for p, h in baseline_snapshot.items() if current.get(p) != h)
        if changed:
            return verification, CopybackResult(
                status="conflict", dest_root=str(dest_root), blocked=changed,
                reason="宛先がworker実行中に変化した(暫定検知/セキュリティ保証ではない)")

    dest_root.mkdir(parents=True, exist_ok=True)

    plan_copy: list[ManifestEntry] = []
    skipped: list[str] = []
    blocked: list[str] = []
    for entry in verification.entries:
        dest_reason = _safe_relpath_reason(dest_root, entry.path)
        if dest_reason:
            blocked.append(entry.path)
            continue
        dest_path = dest_root / entry.path
        if dest_path.exists():
            if dest_path.is_symlink() or not dest_path.is_file():
                blocked.append(entry.path)
                continue
            if (dest_path.stat().st_size == entry.size and
                    _sha256(dest_path) == entry.sha256):
                skipped.append(entry.path)
                continue
            blocked.append(entry.path)
            continue
        plan_copy.append(entry)

    if blocked:
        return verification, CopybackResult(
            status="partial", dest_root=str(dest_root),
            skipped=sorted(skipped), blocked=sorted(blocked),
            reason="既存の宛先ファイルとhashが不一致のため自動上書きを停止(人間裁定)")

    if not plan_copy:
        return verification, CopybackResult(
            status="completed", dest_root=str(dest_root), skipped=sorted(skipped))

    tmp_dir = Path(tempfile.mkdtemp(prefix=".orgh-copyback-", dir=str(dest_root)))
    copied: list[str] = []
    failed: list[str] = []
    try:
        for entry in plan_copy:
            tmp_target = tmp_dir / entry.path
            tmp_target.parent.mkdir(parents=True, exist_ok=True)
            src = staging_dir / entry.path
            try:
                _copy_file(src, tmp_target)
            except OSError as e:
                failed.append(entry.path)
                return verification, CopybackResult(
                    status="partial", dest_root=str(dest_root),
                    skipped=sorted(skipped), failed=failed,
                    reason=f"コピー中に失敗 ({entry.path}): {e}")

        for entry in plan_copy:
            if _sha256(tmp_dir / entry.path) != entry.sha256:
                failed.append(entry.path)
        if failed:
            return verification, CopybackResult(
                status="partial", dest_root=str(dest_root),
                skipped=sorted(skipped), failed=sorted(failed),
                reason="一時ディレクトリでの再検証時にhash不一致")

        for entry in plan_copy:
            final = dest_root / entry.path
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_dir / entry.path, final)
            copied.append(entry.path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return verification, CopybackResult(
        status="completed", dest_root=str(dest_root),
        copied=sorted(copied), skipped=sorted(skipped))

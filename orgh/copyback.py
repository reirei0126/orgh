"""copyback契約: git管理外の成果物領域への安全な書き戻し(direction-2026-08 §4 3a')。

対象領域がgit管理外(例: decision-osの private/cases/)の場合、orghのworktree→
branch→diff受け渡しが全て空振りするため、workerがworktree直下の`_orgh_staging/`
(既定。manifestの`staging_dir`キーで変更可)配下に出力した成果物を、
`orgh-manifest.json`(worktree直下、またはstaging直下。相対パス・サイズ・
SHA-256の一覧)と照合しながらstaging→宛先ルートへ原子的にコピーバックする。
orchestratorへの結線は別モジュール(orgh/orchestrator/copyback_gate.py)。

契約の要点:
- `orgh-manifest.json` の所在は2箇所を許容する: worktree直下(第1優先)と
  staging直下(第2優先)。workerがstaging配下に置いてしまってもゲートが
  空振りしないための救済であり、両所在で内容が同一なら「直下相当」として
  直下を採用、内容が異なれば conflict として人間裁定へ回す(どちらかを
  勝手に採用しない)。探索規則の詳細は resolve_manifest() のdocstring参照。
- `files[].path` は、staging
  サブディレクトリ(既定 `_orgh_staging`。manifestの `staging_dir` キーで
  worktree直下からの相対パスとして変更可。manifestがstaging内にあっても
  `staging_dir` の解決基準は常にworktree直下)からの相対パスとして解釈する。
  実worktreeにはgit管理下の通常ファイルが多数存在するが、`_orgh_staging/`
  配下以外は verify_manifest() の走査・照合・未列挙拒否の対象外であり、
  拒否もコピー対象にもならない(staging専用サブディレクトリ契約)。
- staging限定実行が前提。staging外(worker実行対象の宛先そのもの)への直接書き込み
  防止はここでは強制できない(sandbox/filesystem強制が無い)。
- パスは正規化のうえ、staging_dir自身・manifest各エントリのpath・宛先パスの
  いずれも該当ルート(worktree/staging/宛先)に閉包させる。絶対パス・`..`・
  symlink・manifest未列挙ファイルはすべて拒否する。
- コピーは「一時ディレクトリへ全量配置→再検証→rename」の順で行い、途中失敗時に
  宛先が半端な状態で汚染されないようにする(= copyback_partial)。
- 宛先に既存ファイルがある場合の扱いは三分岐:
  (a) 内容がstaging側と一致 → skip(冪等再実行)
  (b) 内容は違うが `baseline_snapshot`(検収開始時の宛先スナップショット)に
      記録があり現在のhashがその記録と一致 → 「第三者に触られていない既存ファイル
      の更新」とみなし上書きを許可する(一時ディレクトリ→再検証→`os.replace`
      の原子的経路をそのまま通るため、途中失敗時に宛先は汚染されない)
  (c) それ以外(baseline未提供/baselineに無いパス/baseline記録と食い違う)
      → blockedとして人間裁定へ回す(自動上書きしない)
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
DEFAULT_STAGING_DIR = "_orgh_staging"


class CopybackError(ValueError):
    """呼び出し側の契約違反(allowed_roots外の宛先指定など)。続行不能。"""


@dataclass
class ManifestEntry:
    """manifestの1エントリ(正規化済み相対パス・サイズ・SHA-256)。"""
    path: str
    size: int
    sha256: str


MANIFEST_LOCATION_ROOT = "worktree_root"
MANIFEST_LOCATION_STAGING = "staging"


@dataclass
class ManifestResolution:
    """manifestの所在解決の結果(resolve_manifest()の戻り値)。

    path: 採用したmanifestの絶対パス。未発見およびconflict時はNone
          (conflict時にどちらかを勝手に採用しないため)
    location: "worktree_root" | "staging" | None(未発見/conflict時)
    conflict: 直下とstagingの両方にmanifestがあり、バイト内容が異なる場合True
    root_path: worktree直下の候補パス(存在有無に関わらず算出値)
    root_exists: 直下候補が実在するか
    staging_paths: 実在したstaging側候補manifestのパス一覧(探索順)
    reason: conflict時などの人間可読な説明(日本語)
    """
    path: Path | None = None
    location: str | None = None
    conflict: bool = False
    root_path: Path | None = None
    root_exists: bool = False
    staging_paths: list[Path] = field(default_factory=list)
    reason: str | None = None

    @property
    def found(self) -> bool:
        """どちらかの位置に採用可能なmanifestがあるか(conflict時はFalse)。"""
        return self.path is not None


@dataclass
class ManifestVerification:
    """`copyback.manifest` ledgerイベントの情報源。

    ok: 全件がmanifestと一致し、閉包・symlink違反・未列挙ファイルが無ければTrue
    entries: 検証済みのManifestEntry一覧(正規化済みpath。staging_dirからの相対)
    rejected: {元のmanifest記載path(または実ファイルの相対path): 拒否理由}
              絶対パス/'..'/symlink/manifest未列挙ファイル/要素型不正など
              (staging_dir自身の閉包違反は"staging_dir"キーで報告される)
    mismatches: {正規化path: 差分の説明} サイズまたはSHA-256が不一致
    missing: manifestに記載があるがstagingに実体が無いパスの一覧
    staging_dir: 解決済みのstaging絶対パス(worktree直下 + manifestの
                 `staging_dir`キー、既定`_orgh_staging`)。manifest自体が
                 読めない/'files'が不正/staging_dirが閉包違反の場合はNone。
                 run_copyback()はここに記録された同一の解決結果をコピー元
                 として使う(verifyとcopyでの解決のずれを防ぐ)。
    manifest_location: manifestの発見位置("worktree_root" | "staging")。
                 未発見・conflictの場合はNone(ledgerへそのまま記録される)。
    """
    ok: bool
    entries: list[ManifestEntry] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)
    mismatches: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    staging_dir: Path | None = None
    manifest_location: str | None = None

    def as_ledger_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "file_count": len(self.entries),
            "rejected": self.rejected,
            "mismatches": self.mismatches,
            "missing": self.missing,
            "manifest_location": self.manifest_location,
        }


@dataclass
class CopybackResult:
    """`copyback.completed` / `copyback.partial` / `copyback.conflict` ledgerイベントの情報源。

    status: "completed" | "partial" | "conflict" | "manifest_invalid"
    dest_root: 宛先ルート(文字列)
    copied: 実際にコピーした正規化済み相対パス(新規配達に加え、baseline記録と
            一致する=第三者に触られていない既存ファイルへの更新配達も含む)
    skipped: 既に宛先にhash一致で存在するためskipした相対パス(冪等再実行)
    blocked: 宛先に既存かつhash不一致で、かつbaseline記録から不変とも確認できず、
             自動上書きせず人間裁定へ回した相対パス
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


def _declared_staging_dir(manifest_path: Path, worktree_dir: Path) -> Path | None:
    """manifestの`staging_dir`キーをworktree_dirからの相対として解決する。

    読めない/型が不正/閉包違反(絶対パス・'..'・symlink)の場合はNone。
    manifest所在の探索段階で使う軽量な先読みであり、本検証は
    verify_manifest()側で改めて行う(ここでの失敗は「候補なし」に潰す)。
    """
    try:
        raw = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    value = raw.get("staging_dir")
    if not isinstance(value, str) or not value:
        return None
    if _safe_relpath_reason(worktree_dir, value) is not None:
        return None
    return worktree_dir / "/".join(PurePosixPath(value).parts)


def resolve_manifest(worktree_dir: Path | str,
                     manifest_filename: str = MANIFEST_FILENAME) -> ManifestResolution:
    """manifestの所在を解決する(worktree直下が第1優先、staging直下が第2優先)。

    探索規則(実装どおり):
    1. 第1候補は `<worktree>/orgh-manifest.json`(=従来の契約位置)。
    2. 第2候補は staging 直下の manifest。staging側を探す時点ではまだ
       manifestを読めていないため、`DEFAULT_STAGING_DIR`(`_orgh_staging`)は
       必ず探索する。加えて第1候補が実在する場合はその内容の `staging_dir`
       キーを先読みし、既定と異なりかつworktree内へ閉包していれば、その
       解決先の直下も候補に加える(候補は 既定 → 宣言値 の順)。
       第1候補が無い場合は先読み元が無いため、探索は既定stagingのみとなる。
    3. 第1候補のみ実在 → 直下を採用(location="worktree_root")。
    4. 第2候補のみ実在 → staging側を採用(location="staging")。
       複数のstaging候補が実在する場合は探索順で最初のものを採用する。
    5. 両方実在する場合、バイト内容を比較する:
       - 全staging候補が第1候補とバイト一致 → conflictではなく「直下相当」
         として直下を採用(location="worktree_root")。
       - 1件でも内容が異なる → conflict=True を返し、pathはNoneのままとする
         (曖昧さを通さない=どちらかを勝手に採用しない)。呼び出し側は
         人間裁定へ回すこと。
    6. どちらも実在しない → found=False(path=None, conflict=False)。

    比較はJSONの意味論ではなくバイト列で行う(整形差も「内容が異なる」と
    みなす保守的な判定)。
    """
    worktree_dir = Path(worktree_dir)
    root_path = worktree_dir / manifest_filename
    root_exists = root_path.is_file()

    staging_candidates: list[Path] = [worktree_dir / DEFAULT_STAGING_DIR]
    if root_exists:
        declared = _declared_staging_dir(root_path, worktree_dir)
        if declared is not None and declared not in staging_candidates:
            staging_candidates.append(declared)

    staging_paths: list[Path] = []
    for cand in staging_candidates:
        mp = cand / manifest_filename
        if mp.is_file() and mp not in staging_paths:
            staging_paths.append(mp)

    if root_exists and staging_paths:
        try:
            root_bytes = root_path.read_bytes()
            differing = [mp for mp in staging_paths
                         if mp.read_bytes() != root_bytes]
        except OSError as e:
            return ManifestResolution(
                conflict=True, root_path=root_path, root_exists=True,
                staging_paths=staging_paths,
                reason=f"manifestの読み取りに失敗し所在を裁定できない: {e}")
        if differing:
            return ManifestResolution(
                conflict=True, root_path=root_path, root_exists=True,
                staging_paths=staging_paths,
                reason=("manifestがworktree直下とstaging("
                        + ", ".join(str(p) for p in differing)
                        + ")の両方に存在し内容が異なる"))
        # 内容が同一なら「直下相当」として直下を採用する(conflictではない)
        return ManifestResolution(
            path=root_path, location=MANIFEST_LOCATION_ROOT,
            root_path=root_path, root_exists=True, staging_paths=staging_paths)

    if root_exists:
        return ManifestResolution(
            path=root_path, location=MANIFEST_LOCATION_ROOT,
            root_path=root_path, root_exists=True)

    if staging_paths:
        return ManifestResolution(
            path=staging_paths[0], location=MANIFEST_LOCATION_STAGING,
            root_path=root_path, root_exists=False, staging_paths=staging_paths)

    return ManifestResolution(root_path=root_path, root_exists=False)


def verify_manifest(worktree_dir: Path | str,
                     manifest_filename: str = MANIFEST_FILENAME) -> ManifestVerification:
    """manifest(worktree直下が第1優先、staging直下が第2優先。resolve_manifest()
    参照)を読み、staging(既定`_orgh_staging`。manifestの`staging_dir`キーで
    変更可)配下の実ファイルと再計算したsize/SHA-256を突合する。

    manifestがstaging内にあっても`staging_dir`は常にworktree_dirからの相対
    として解決する(解決基準は従来どおりworktree_dir)。staging直下のmanifest
    自身は走査対象から除外され、「manifest未列挙ファイル」として拒否されない。

    走査・照合・未列挙拒否の対象はstagingサブディレクトリ配下のみであり、
    worktree直下のgit管理下ファイル等(staging外)は無視する(拒否もコピー対象
    にもしない)。

    検収開始時・コピー直前のいずれからも呼ばれる想定(呼ぶたびに全量再計算する
    ="staging凍結の検証"であり、キャッシュは持たない)。
    """
    worktree_dir = Path(worktree_dir)
    resolution = resolve_manifest(worktree_dir, manifest_filename)
    if resolution.conflict:
        return ManifestVerification(
            ok=False,
            rejected={manifest_filename: resolution.reason or
                      "manifestが直下とstagingの両方に存在し内容が異なる"})
    if resolution.path is None:
        return ManifestVerification(
            ok=False, rejected={manifest_filename: "manifestファイルが存在しない"})
    manifest_path = resolution.path
    location = resolution.location
    try:
        raw = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return ManifestVerification(
            ok=False, manifest_location=location,
            rejected={manifest_filename: f"manifestの読み取りに失敗: {e}"})

    if isinstance(raw, dict):
        items = raw.get("files")
        staging_dir_raw: Any = raw.get("staging_dir", DEFAULT_STAGING_DIR)
    else:
        items = raw
        staging_dir_raw = DEFAULT_STAGING_DIR

    if not isinstance(items, list):
        return ManifestVerification(
            ok=False, manifest_location=location,
            rejected={manifest_filename: "'files'がリストでない"})

    if not isinstance(staging_dir_raw, str) or not staging_dir_raw:
        return ManifestVerification(
            ok=False, manifest_location=location,
            rejected={"staging_dir": "staging_dirが空または文字列でない"})

    # staging_dirの解決基準は常にworktree_dir(manifestがstaging内にある場合も
    # manifestの所在ディレクトリ基準にはしない)
    staging_reason = _safe_relpath_reason(worktree_dir, staging_dir_raw)
    if staging_reason:
        return ManifestVerification(
            ok=False, manifest_location=location,
            rejected={"staging_dir": staging_reason})

    staging_dir = worktree_dir / "/".join(PurePosixPath(staging_dir_raw).parts)

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

    # staging直下のmanifest自身(2箇所対応で許容している所在)は成果物では
    # ないため未列挙拒否の対象にしない
    excluded = {staging_dir / manifest_filename, *resolution.staging_paths}
    for rel in _walk_files(staging_dir):
        if rel == manifest_filename or (staging_dir / rel) in excluded:
            continue
        if rel not in listed:
            rejected[rel] = "manifest未列挙ファイル"

    ok = not rejected and not mismatches and not missing
    return ManifestVerification(ok=ok, entries=entries, rejected=rejected,
                                mismatches=mismatches, missing=missing,
                                staging_dir=staging_dir,
                                manifest_location=location)


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


def run_copyback(worktree_dir: Path | str, dest_root: Path | str,
                  allowed_roots: list[str], *,
                  baseline_snapshot: dict[str, str] | None = None,
                  manifest_filename: str = MANIFEST_FILENAME,
                  ) -> tuple[ManifestVerification, CopybackResult]:
    """manifestを再検証し、staging(worktree直下の`_orgh_staging/`。manifestの
    `staging_dir`キーで変更可)→dest_rootへ原子的にコピーバックする。

    manifestの所在は verify_manifest() 経由で resolve_manifest() が解決する
    (worktree直下が第1優先、staging直下が第2優先。両所在で内容が異なる場合は
    conflictとして manifest_invalid で停止する)。staging_dirの解決基準は
    manifestの所在に関わらず常に worktree_dir。

    手順(§4 3a'契約どおり):
    1. dest_rootがallowed_roots配下か検査(外れていればCopybackError)
    2. manifestをworktree_dirに対して再計算・再検証し、staging_dirを解決する
       (=コピー直前の再検証。コピー元にはこの解決結果をそのまま使い、
       verify/copyでstaging_dirの解決がずれないようにする)
    3. baseline_snapshotが渡されていれば、宛先の該当ファイルが記録時から
       変化していないか突合する。変化していれば `copyback_conflict`
       (⚠ 暫定運用でありセキュリティ保証ではない)
    4. 宛先ファイルごとに三分岐で判定する:
       (a) 宛先の内容がstaging側と一致(size/sha256一致)→ skip
       (b) 内容は不一致だが、`baseline_snapshot` に当該相対パスの記録があり、
           宛先の現在のsha256がその記録値と一致する(=検収開始時から第三者に
           変更されていない)→ 上書きを許可し、コピー計画に載せる
       (c) それ以外(baseline未提供/baselineに記録が無いパス/記録値と現在値が
           食い違う)→ blockedとして人間裁定へ回し、この時点で停止する
           (自動上書きしない)
    5. 残る配達対象((b)の上書きを含む)を一時ディレクトリへ全量コピーし、再検証してから
       rename で最終宛先へ配置する(=copyback_partialの回避: 途中失敗時は
       renameフェーズへ進まないため宛先は書き換わらない)

    戻り値は (ManifestVerification, CopybackResult) のタプル。呼び出し側は
    前者を `copyback.manifest`、後者のstatusに応じて `copyback.completed` /
    `copyback.partial` / `copyback.conflict` のledgerイベントに使う。
    """
    worktree_dir = Path(worktree_dir)
    dest_root = Path(dest_root)
    _check_allowed_root(dest_root, allowed_roots)

    verification = verify_manifest(worktree_dir, manifest_filename)
    if not verification.ok:
        return verification, CopybackResult(
            status="manifest_invalid", dest_root=str(dest_root),
            reason=(f"manifest検証失敗: rejected={sorted(verification.rejected)} "
                    f"mismatches={sorted(verification.mismatches)} "
                    f"missing={sorted(verification.missing)}"))
    staging_dir = verification.staging_dir

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
            dest_hash = _sha256(dest_path)
            if dest_path.stat().st_size == entry.size and dest_hash == entry.sha256:
                skipped.append(entry.path)
                continue
            # 内容不一致。baselineに記録があり現在値がそれと一致する場合のみ
            # 「検収開始時から第三者に触られていない既存ファイルの更新」として
            # 上書きを許可する(それ以外は従来どおり人間裁定)。
            if (baseline_snapshot is not None and
                    baseline_snapshot.get(entry.path) == dest_hash):
                plan_copy.append(entry)
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

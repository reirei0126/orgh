"""オーナー判断基準台帳(戦略設計書 柱2の最小版)。

playbooks(作業のやり方の教訓)と対をなす「判断の一般原則」の置き場。
形式はplaybooksと同系のMarkdown行+メタタグで、ユーザーが直接編集できる。
更新ガバナンスは「下書き+ワンタップ承認」: 自動生成は _drafts/ 止まりで、
本台帳への反映は必ず orgh criteria approve(=オーナー操作)を通る。
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from .events_json import events_payload

_ENTRY_RE = re.compile(r"^- ([A-Z]+)-(\d{3}) \[(norm|pref)\]:")
_LEDGER_ENTRY_RE = re.compile(r"^- ([A-Z]+-\d{3}) \[(norm|pref)\]: (.*)$")
_META_RE = re.compile(r"<!-- src:(\S+) d:(\d{4}-\d{2}-\d{2}) -->")
# エントリ行のメタコメントに書ける失効タグ。src:/d: の本体コメントとは別の
# 独立したHTMLコメント(例: `<!-- superseded_by:ARCH-003 -->`)として書く
# 前提。_META_REを拡張せず単純な部分一致で探すことで、src:/d:の解析を
# 壊さずに既存33件(supersededタグ無し)との後方互換を保つ。
_SUPERSEDED_RE = re.compile(r"superseded_by:([A-Z]+-\d{3})")
# prefixは_ENTRY_REが `[A-Z]+` しか認識しないため、それより緩い正規表現を許すと
# next_id走査から漏れて同一IDが再発行される(Fix 1が閉じたはずの欠陥クラス)
_SAFE_PREFIX_RE = re.compile(r"^[A-Z]+$")
# categoryは先頭が `_` だと _ledger_files() の除外対象(_drafts等)と衝突し、
# 承認済みのはずの行がcriteria_context/next_idから見えなくなる
_SAFE_CATEGORY_RE = re.compile(r"^[A-Za-z0-9-][A-Za-z0-9_-]*$")
_VALID_STRENGTHS = {"norm", "pref"}


def criteria_dir(cfg: dict) -> Path:
    return Path(cfg.get("criteria_dir", "criteria")).expanduser()


def criteria_read_dir(cfg: dict) -> Path:
    """実行時スナップショットがあればそれを、なければ本台帳を返す。"""
    if "_criteria_read_dir" in cfg:
        return Path(cfg["_criteria_read_dir"]).expanduser()
    return criteria_dir(cfg)


def _ledger_files(cdir: Path) -> list[Path]:
    """_始まり(_drafts/_rejected等)は台帳走査から除外する。"""
    if not cdir.is_dir():
        return []
    return sorted(p for p in cdir.glob("*.md") if not p.name.startswith("_"))


def _project_ledger_root(cdir: Path) -> Path:
    return cdir / "projects"


def _project_ledger_files(cdir: Path) -> list[Path]:
    """criteria/projects/*.md 全件(全slug横断、list/list_payload等の監査系
    専用)。注入系(criteria_context)は特定slugの1ファイルのみを見る
    _project_ledger_file()を使い、他プロジェクトの台帳を絶対に混ぜない。"""
    pdir = _project_ledger_root(cdir)
    if not pdir.is_dir():
        return []
    return sorted(p for p in pdir.glob("*.md") if not p.name.startswith("_"))


def _project_ledger_file(cdir: Path, slug: str) -> Path | None:
    """指定slugのプロジェクト台帳ファイル(存在すれば)。他slugのファイルは
    参照しない——config一つの取り違えで他プロジェクトの内部方針が漏れる
    設計を避けるため、常にこの1ファイルだけを対象にする。"""
    p = _project_ledger_root(cdir) / f"{slug}.md"
    return p if p.is_file() else None


_GLOBAL_RESERVED_PREFIXES = frozenset(
    {"ARCH", "DESIGN", "DOMAIN", "ENG", "PROD", "QA", "SAFETY"})


def _existing_project_prefixes(cdir: Path, exclude_slug: str) -> set[str]:
    """exclude_slug自身の台帳を除く、他プロジェクト台帳が既に使っている
    接頭辞の集合(衝突判定用)。exclude_slug自身の既存エントリは、再承認時に
    同じ接頭辞を返せるよう衝突とみなさない。"""
    prefixes: set[str] = set()
    for p in _project_ledger_files(cdir):
        if p.stem == exclude_slug:
            continue
        for line in p.read_text().splitlines():
            m = _ENTRY_RE.match(line)
            if m:
                prefixes.add(m.group(1))
    return prefixes


def derive_project_prefix(cdir: Path, slug: str) -> str:
    """プロジェクト台帳(criteria/projects/<slug>.md)のID接頭辞をslugから
    機械的に導出する。

    導出規則(決定的):
    1. slug中の英字のみを抽出し大文字化する(数字・ハイフン・アンダースコアは
       除去)。3文字に満たない場合は 'X' で3文字まで埋める(英字が皆無の
       slugでも "XXX" を基底候補として扱えるようにするため)。
    2. 基底候補は先頭3文字(例: "agentmenu" -> "AGM")。

    衝突回避(基底候補が既存の接頭辞と衝突する場合、以下の順で決定的にずらす):
    3. 先頭4文字を候補にする(例: "agentmenu" -> "AGEN")。
    4. それでも衝突するなら、3文字候補の先頭2文字はそのままに、
       末尾1文字だけを 'A'..'Z' の順に総当たりし、最初に衝突しない
       ものを採用する(例: AGM -> AGA, AGB, ... 衝突しないものまで)。
       この段で必ずどこかで衝突しない候補が見つかる(A-Zの26通りに対し
       既存接頭辞の総数は現実的にそれよりずっと少ない)。

    衝突判定の対象は、既存のグローバル接頭辞(ARCH/DESIGN/DOMAIN/ENG/PROD/
    QA/SAFETY、固定集合)と、slug自身を除く他プロジェクト台帳が既に使って
    いる接頭辞(criteria/projects/*.mdを実走査)。slug自身の既存エントリの
    接頭辞は衝突とみなさない(同一slugへの再承認で毎回同じ接頭辞を返す
    決定性を保つため)。
    """
    letters = "".join(ch for ch in slug.upper() if ch.isalpha())
    padded = (letters + "XXXX")[:4]
    base = padded[:3]
    reserved = _GLOBAL_RESERVED_PREFIXES | _existing_project_prefixes(cdir, slug)

    if base not in reserved:
        return base

    ext = padded[:4]
    if ext != base and ext not in reserved:
        return ext

    for suffix in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        candidate = base[:2] + suffix
        if candidate not in reserved:
            return candidate
    raise ValueError(
        f"slug={slug!r} の接頭辞導出に失敗した(候補が全て既存接頭辞と衝突)")


def project_slug(cfg: dict, workdir: str | Path | None) -> str | None:
    """ミッション/タスクのworkdir(絶対パス想定)末尾ディレクトリ名を
    プロジェクト台帳のslugとして返す。以下はグローバルのみ注入の現行挙動へ
    フォールバックするためNoneを返す:
    - workdirが空/"."(プロジェクト未指定)
    - criteria_dirを含むリポのルート(=orgh自身)を指す場合
    - 導出したslugが安全な文字集合(_SAFE_CATEGORY_RE、パストラバーサル
      防止・_ledger_filesの`_`始まり除外規約との衝突防止)に合致しない場合
    """
    if not workdir or str(workdir) == ".":
        return None
    path = Path(workdir).expanduser().resolve()
    own_root = criteria_dir(cfg).expanduser().resolve().parent
    if path == own_root:
        return None
    slug = path.name
    if not slug or not _SAFE_CATEGORY_RE.match(slug):
        return None
    return slug


def _entries_from_files(files: list[Path]) -> list[tuple[str, str]]:
    """指定ファイル群のエントリ行のみを(date, line)で返す(日付ソートなし)。"""
    entries: list[tuple[str, str]] = []
    for p in files:
        for line in p.read_text().splitlines():
            if not line.strip() or not _LEDGER_ENTRY_RE.match(line):
                continue
            m = _META_RE.search(line)
            entries.append((m.group(2) if m else "0000-00-00", line))
    return entries


def _ledger_entries(cfg: dict) -> list[tuple[str, str]]:
    """グローバル台帳のエントリ行(_LEDGER_ENTRY_REにマッチする行)のみを
    (date, line)で返す。見出し・注釈等の非エントリ行は無視する。superseded
    エントリも含める(next_id走査・list表示側で必要なため、除外は
    criteria_context側で行う)。"""
    entries = _entries_from_files(_ledger_files(criteria_read_dir(cfg)))
    entries.sort(key=lambda e: e[0], reverse=True)
    return entries


def _pack(entries: list[tuple[str, str]], max_chars: int) -> list[str]:
    """日付降順で詰め、max_charsを超えた時点で打ち切る(playbookと同じ作法)。"""
    picked, total = [], 0
    for _, line in entries:
        total += len(line) + 1
        if total > max_chars and picked:
            break
        picked.append(line)
    return picked


def _max_inject_chars(cfg: dict) -> int:
    """注入上限。config `criteria_max_inject_chars`(既定4000)。台帳が上限を
    超えると古いエントリから無言で注入対象外になるため、全件注入したい場合は
    configで拡大する(2026-08-16時点の全量は約5,300字)。"""
    return cfg.get("criteria_max_inject_chars") or 4000


def criteria_context(cfg: dict, max_chars: int | None = None,
                     workdir: str | Path | None = None) -> str:
    """台帳のエントリ行のみをReviewer/ペルソナのプロンプトへ注入する
    (playbookと同じ日付降順詰め)。見出し・注釈等の非エントリ行と、
    superseded_by付きエントリ(失効済み)は注入しない。

    workdirを渡すと、project_slug(cfg, workdir)が導出するプロジェクト台帳
    (criteria/projects/<slug>.md、その1ファイルのみ・他プロジェクトは
    絶対に混ぜない)をグローバルに上乗せする。注入上限max_charsは両層の
    合算に適用し、詰め順は「プロジェクト台帳を先に全件、残り枠にグローバル
    を日付降順で」——プロジェクト台帳は恒久保有コアとしてグローバルより
    優先して守る。workdir未指定時(既定)は従来と完全に同一の出力になる。
    """
    if max_chars is None:
        max_chars = _max_inject_chars(cfg)
    global_active = [(d, line) for d, line in _ledger_entries(cfg)
                     if not _SUPERSEDED_RE.search(line)]

    slug = project_slug(cfg, workdir)
    project_lines: list[str] = []
    if slug is not None:
        pfile = _project_ledger_file(criteria_read_dir(cfg), slug)
        if pfile is not None:
            project_entries = sorted(
                _entries_from_files([pfile]), key=lambda e: e[0], reverse=True)
            project_lines = [line for d, line in project_entries
                             if not _SUPERSEDED_RE.search(line)]

    if project_lines:
        # プロジェクト台帳は上限を超えても全件維持する(先に無条件で詰める)。
        used = sum(len(line) + 1 for line in project_lines)
        remaining = max_chars - used
        global_lines: list[str] = []
        total = 0
        for _, line in global_active:
            total += len(line) + 1
            if total > remaining:
                break
            global_lines.append(line)
        picked = project_lines + global_lines
    else:
        picked = _pack(global_active, max_chars)
    return "\n".join(picked) if picked else "(no criteria yet)"


def criteria_ids(cfg: dict, max_chars: int | None = None,
                 workdir: str | Path | None = None) -> set[str]:
    """criteria_context(cfg, max_chars, workdir)が実際にプロンプトへ注入する
    基準IDの集合。裁定応答の criteria_cited 検証(捏造ID破棄)に使う — 注入
    されていないIDを裁定が引用したと言い張っても、この集合に無ければ
    信用しない。"""
    ids: set[str] = set()
    for line in criteria_context(cfg, max_chars=max_chars,
                                 workdir=workdir).splitlines():
        m = _LEDGER_ENTRY_RE.match(line)
        if m:
            ids.add(m.group(1))
    return ids


def next_id(cdir: Path, prefix: str) -> str:
    """全台帳ファイル横断でprefixの最大番号+1(3桁ゼロ埋め)。"""
    top = 0
    for p in _ledger_files(cdir):
        for line in p.read_text().splitlines():
            m = _ENTRY_RE.match(line)
            if m and m.group(1) == prefix:
                top = max(top, int(m.group(2)))
    return f"{prefix}-{top + 1:03d}"


def append_entry(cdir: Path, category: str, prefix: str, strength: str,
                 text: str, src: str) -> str:
    cdir.mkdir(parents=True, exist_ok=True)
    line = (f"- {next_id(cdir, prefix)} [{strength}]: {text} "
            f"<!-- src:{src} d:{date.today().isoformat()} -->")
    with open(cdir / f"{category}.md", "a") as f:
        f.write(line + "\n")
    return line


def _find_entry_line(cdir: Path, entry_id: str) -> tuple[Path, list[str], int] | None:
    """entry_idに一致するエントリ行を、グローバル+全プロジェクト台帳を
    横断して探す(supersedeがグローバル↔プロジェクト間でも機能するように)。
    見つかれば (ファイル, split("\\n")した全行, 行index) を返す。
    split("\\n")を使うのは、書き戻し時に対象行以外を1文字も変えずに
    再結合するため(splitlines()は改行種別・末尾改行の情報を失う)。"""
    for p in _ledger_files(cdir) + _project_ledger_files(cdir):
        lines = p.read_text().split("\n")
        for i, line in enumerate(lines):
            m = _LEDGER_ENTRY_RE.match(line)
            if m and m.group(1) == entry_id:
                return p, lines, i
    return None


def supersede_entry(cfg: dict, old_id: str, new_id: str) -> str:
    """旧IDのエントリ行に superseded_by:<新ID> メタタグを付与する(書き込み側)。

    criteria_context/list/next_idの読み取り側は_SUPERSEDED_RE前提で実装済み
    (このモジュール冒頭のコメント参照)。ここでは対象エントリ行のみを書き換え、
    他の行・他ファイルは一切変更しない。検証(新ID実在・旧ID実在・二重
    supersede禁止・自己参照禁止)は全てファイル書き換え前に行い、失敗時は
    台帳を一切書き換えない。
    """
    if old_id == new_id:
        raise ValueError(f"old_id と new_id が同一です(自己参照は禁止): {old_id}")

    cdir = criteria_dir(cfg)
    if _find_entry_line(cdir, new_id) is None:
        raise ValueError(f"new_id が台帳に実在しません: {new_id}")

    found = _find_entry_line(cdir, old_id)
    if found is None:
        raise ValueError(f"old_id が台帳に存在しません: {old_id}")
    path, lines, idx = found
    line = lines[idx]
    already = _SUPERSEDED_RE.search(line)
    if already:
        raise ValueError(
            f"{old_id} は既に {already.group(1)} へsupersede済みです"
            f"(二重supersedeは禁止)")

    lines[idx] = f"{line} <!-- superseded_by:{new_id} -->"
    path.write_text("\n".join(lines))
    return f"{old_id} -> {new_id} へsupersede完了 ({path.name})"


def _next_draft_start(drafts_dir: Path, mission_id: str) -> int:
    """既存の <mission_id>-<n>.json を走査し、次に使う番号(最大+1)を返す。
    同一ミッションへ複数回 verdict した際に、番号を1から振り直して
    未承認の既存下書きを上書きしないための採番。"""
    top = 0
    if drafts_dir.is_dir():
        for p in drafts_dir.glob(f"{mission_id}-*.json"):
            m = re.match(rf"^{re.escape(mission_id)}-(\d+)\.json$", p.name)
            if m:
                top = max(top, int(m.group(1)))
    return top + 1


def list_drafts(cfg: dict) -> list[Path]:
    d = criteria_dir(cfg) / "_drafts"
    return sorted(d.glob("*.json")) if d.is_dir() else []


def _draft_path(cfg: dict, name: str) -> Path:
    fp = criteria_dir(cfg) / "_drafts" / f"{name}.json"
    if not fp.is_file():
        raise FileNotFoundError(
            f"draft not found: {fp}. orgh criteria list で確認せよ")
    return fp


def _validate_draft_fields(p: dict, fp: Path) -> None:
    """distillLLMが生成したcategory/prefix/strengthは信用しない(検証済み脆弱性対応)。

    category/prefixはファイル名(criteria_dir/{category}.md)や台帳ID接頭辞に
    直接使われるため、パストラバーサル("../../ESCAPED"等)や記号混入を拒否する。
    単なる「安全な文字集合」では不十分で、台帳自身の走査契約に合わせて絞る:
    - prefixは _ENTRY_RE が `[A-Z]+` の接頭辞しか認識しないため、小文字混じり
      (例: "design")を許すとledger行がnext_idの走査から漏れ、同じ番号が
      再発行されてID引用契約を破壊する(Fix 1が閉じたはずの欠陥クラス)
    - categoryは先頭 `_` を許すと _ledger_files() の除外対象(_drafts等)と
      衝突し、承認済みのはずの行がcriteria_context/next_idから見えなくなる
    strengthは _ENTRY_RE が `norm|pref` しか認識しないため、それ以外
    (例: "強制")を許すとledger行が走査から漏れ、next_idが同じ番号を
    再発行してID引用契約(重複DESIGN-001等)を破壊する。
    違反時は下書きファイルの場所を示すValueErrorとし、オーナーが手で
    直して再承認できるようにする。
    """
    prefix = p.get("prefix")
    if not isinstance(prefix, str) or not _SAFE_PREFIX_RE.match(prefix):
        raise ValueError(
            f"draft {fp}: prefix が不正な値です ({prefix!r})。"
            f"英大文字のみ許可(台帳IDの接頭辞規約 [A-Z]+ に合わせる)。"
            f"下書きファイルを直接編集してから再承認せよ: {fp}")
    category = p.get("category")
    if not isinstance(category, str) or not _SAFE_CATEGORY_RE.match(category):
        raise ValueError(
            f"draft {fp}: category が不正な値です ({category!r})。"
            f"英数字・アンダースコア・ハイフンのみ許可(先頭に`_`は不可、"
            f"_drafts等の除外規約と衝突するため)。"
            f"下書きファイルを直接編集してから再承認せよ: {fp}")
    strength = p.get("strength", "pref")
    if strength not in _VALID_STRENGTHS:
        raise ValueError(
            f"draft {fp}: strength が不正な値です ({strength!r})。"
            f"norm/pref のいずれかのみ許可。"
            f"下書きファイルを直接編集してから再承認せよ: {fp}")


def approve_draft(cfg: dict, name: str, project: str | None = None) -> str:
    """下書きを本台帳へ反映する(ワンタップ承認の実体)。

    project(slug)省略時は従来どおりグローバル台帳(下書きのcategory/prefix)
    へ反映し挙動は完全不変。project指定時は criteria/projects/<slug>.md へ
    追記し、IDは derive_project_prefix() が決定的に導出する接頭辞で採番する
    (append_entry内のnext_idがプロジェクト層の全ファイル横断で走査するため、
    同一IDの再発行は起きない)。下書きのcategory/prefix/strengthに対する
    _validate_draft_fields()の検証はこの経路でも同等に効く(textとstrength
    のみ使うが、他フィールドが不正な下書きはオーナーが直すべきだから)。
    """
    fp = _draft_path(cfg, name)
    p = json.loads(fp.read_text())
    _validate_draft_fields(p, fp)

    if project is None:
        line = append_entry(criteria_dir(cfg), p["category"], p["prefix"],
                            p.get("strength", "pref"), p["text"], src=name)
        fp.unlink()
        return line

    if not _SAFE_CATEGORY_RE.match(project):
        raise ValueError(
            f"--project の値が不正です ({project!r})。"
            f"英数字・アンダースコア・ハイフンのみ許可(先頭に`_`は不可、"
            f"パストラバーサル文字は不可)。")
    cdir = criteria_dir(cfg)
    pdir = _project_ledger_root(cdir)
    pfile = pdir / f"{project}.md"
    if not pfile.is_file():
        print(f"新規プロジェクト台帳を作成します: {pfile}")
    prefix = derive_project_prefix(cdir, project)
    line = append_entry(pdir, project, prefix, p.get("strength", "pref"),
                        p["text"], src=name)
    fp.unlink()
    return line


def reject_draft(cfg: dict, name: str) -> Path:
    """棄却は削除ではなく退避(棄却理由の見直し・復活を可能にする)。

    ファイル名衝突時(同ミッションへの再度の下書き生成)は数字サフィックスで
    既存を保護する(上書き防止)。"""
    fp = _draft_path(cfg, name)
    dst_dir = criteria_dir(cfg) / "_drafts" / "rejected"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / fp.name

    # 衝突回避: 既存ファイルがあれば .2, .3, ... のサフィックスを追加
    if dst.exists():
        base = dst.stem  # "m123-1" from "m123-1.json"
        suffix = 2
        while True:
            dst = dst_dir / f"{base}.{suffix}.json"
            if not dst.exists():
                break
            suffix += 1

    fp.rename(dst)
    return dst


def criteria_usage(cfg: dict) -> dict[str, dict]:
    """全missionの裁定イベントからcriteria IDごとの引用実績を返す。"""
    usage: dict[str, dict] = {}
    runs_dir = Path(cfg.get("runs_dir", "runs")).expanduser()
    if not runs_dir.is_dir():
        return usage

    # gcで runs/_archive/<mission>/ へ退避済みの過去ledgerも実績に含める。
    for ledger_path in runs_dir.rglob("ledger.jsonl"):
        run_dir = ledger_path.parent
        for event in events_payload(
                run_dir.parent, run_dir.name, tail=None)["events"]:
            if event["event"] not in {"task.review", "task.persona_review"}:
                continue
            cited = event.get("criteria_cited")
            if not isinstance(cited, list):
                continue
            # 回数はIDの出現数ではなく、そのIDを含む裁定イベント数。
            for criterion_id in {item for item in cited if isinstance(item, str)}:
                item = usage.setdefault(
                    criterion_id, {"citation_count": 0, "last_cited_ts": None})
                item["citation_count"] += 1
                if (item["last_cited_ts"] is None
                        or event["ts"] > item["last_cited_ts"]):
                    item["last_cited_ts"] = event["ts"]
    return usage


def _usage_fields(item: dict | None) -> dict:
    count = item["citation_count"] if item else 0
    last_ts = item["last_cited_ts"] if item else None
    last_date = (datetime.fromtimestamp(last_ts, timezone.utc).date().isoformat()
                 if last_ts is not None else None)
    return {"citation_count": count, "last_cited_date": last_date}


def _render_list_lines(entries: list[tuple[str, str]], usage: dict,
                       max_chars: int) -> list[str]:
    picked = _pack(entries, max_chars)
    rendered: list[str] = []
    for line in picked:
        match = _LEDGER_ENTRY_RE.match(line)
        fields = _usage_fields(usage.get(match.group(1)))
        rendered.append(
            f"<!-- id:{match.group(1)} 引用回数:{fields['citation_count']} "
            f"最終引用日:{fields['last_cited_date'] or '-'} -->")
        superseded = _SUPERSEDED_RE.search(line)
        rendered.append(
            f"{line} [superseded → {superseded.group(1)}]" if superseded
            else line)
    return rendered


def criteria_list_text(cfg: dict, max_chars: int = 100000) -> str:
    """各台帳行の直前に、走査しやすい独立した引用実績行を付ける。

    criteria_context()と異なり、supersededエントリも列挙し
    `[superseded → <ID>]` を付記する(履歴を台帳内に残し監査の連続性を
    保つ)。オーナーの監査用途のため、criteria/projects/ 配下の全プロジェクト
    台帳を横断して(注入とは異なり、slug絞り込みなしで)列挙する。"""
    usage = criteria_usage(cfg)
    cdir = criteria_dir(cfg)
    rendered = _render_list_lines(_ledger_entries(cfg), usage, max_chars)
    for p in _project_ledger_files(cdir):
        entries = sorted(_entries_from_files([p]), key=lambda e: e[0],
                         reverse=True)
        section = _render_list_lines(entries, usage, max_chars)
        if section:
            rendered.append(f"--- project:{p.stem} ---")
            rendered.extend(section)
    return "\n".join(rendered) if rendered else "(no criteria yet)"


def criteria_list_payload(cfg: dict, include_usage: bool = False) -> dict:
    """`orgh criteria list --json` 用の機械可読ペイロード。

    本台帳(criteria/<category>.md)と下書き(criteria/_drafts/*.json)を
    それぞれエントリ化する。distill LLMの出力ではなく人間が直接編集する
    ファイルが入力元のため、orgh list --json(listing.py)と同じ作法で
    パース不能な行・ファイルは例外で落とさずskipし、原因をskippedへ残す。
    """
    cdir = criteria_dir(cfg)
    entries: list[dict] = []
    skipped: list[dict] = []

    def _parse_into(p: Path, category: str, layer_fields: dict | None) -> None:
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            m = _LEDGER_ENTRY_RE.match(line)
            if not m:
                skipped.append({"path": str(p),
                                "reason": f"unparseable line: {line!r}"})
                continue
            entry_id, strength, rest = m.group(1), m.group(2), m.group(3)
            meta = _META_RE.search(rest)
            if meta:
                text = rest[:meta.start()].rstrip()
                source_mission, entry_date = meta.group(1), meta.group(2)
            else:
                text, source_mission, entry_date = rest.strip(), None, None
            entry = {
                "category": category, "id": entry_id, "strength": strength,
                "text": text, "source_mission": source_mission,
                "date": entry_date,
            }
            superseded = _SUPERSEDED_RE.search(rest)
            if superseded:
                entry["superseded_by"] = superseded.group(1)
            if layer_fields:
                entry.update(layer_fields)
            entries.append(entry)

    for p in _ledger_files(cdir):
        _parse_into(p, p.stem, None)

    # プロジェクト台帳(全slug横断、オーナーの監査用途)。layer/projectで
    # グローバルエントリと識別できるようにする一方、既存のグローバル
    # エントリの形状(キー集合)は変えない(後方互換)。
    for p in _project_ledger_files(cdir):
        _parse_into(p, p.stem, {"layer": "project", "project": p.stem})

    if include_usage:
        usage = criteria_usage(cfg)
        for entry in entries:
            entry.update(_usage_fields(usage.get(entry["id"])))

    drafts: list[dict] = []
    for fp in list_drafts(cfg):
        try:
            raw = json.loads(fp.read_text())
            if not isinstance(raw, dict):
                raise ValueError("draft is not a JSON object")
        except (OSError, ValueError) as e:
            skipped.append({"path": str(fp), "reason": f"{type(e).__name__}: {e}"})
            continue
        drafts.append({
            "name": fp.stem, "path": str(fp),
            "category": raw.get("category"), "strength": raw.get("strength"),
            "text": raw.get("text"), "raw": raw,
        })

    return {"entries": entries, "drafts": drafts, "skipped": skipped}


def distill_verdict(cfg: dict, mission_id: str, intent: str,
                    passed: bool, reason: str,
                    workdir: str | Path | None = None) -> list[Path]:
    """オーナー裁定から台帳差分の下書きを生成する(本台帳には書かない)。

    workdirを渡すと project_slug(cfg, workdir) が導出するslug候補を
    各下書きの "project_slug_hint" フィールドに付記する(承認時に
    `orgh criteria approve <name> --project <slug>` で選べるようにする
    ためのヒントであり、approve_draft自体はこのフィールドを読まない)。
    workdir省略時(既定)は付記しない——グローバル承認しか想定しない
    既存下書き・既存呼び出しとの後方互換を保つ。
    """
    from .planner import _ask_json, _read_prompt, role_with_default
    cfg = role_with_default(cfg, "criteria_distill", {
        "model": "sonnet", "max_turns": 5, "allowed_tools": "Read"})
    tmpl = _read_prompt(cfg, "criteria_distill.md")
    prompt = tmpl.format(intent=intent,
                         verdict="合格" if passed else "不合格",
                         reason=reason, criteria=criteria_context(cfg))
    data = _ask_json(cfg, "criteria_distill", prompt)
    drafts_dir = criteria_dir(cfg) / "_drafts"
    proposals = data.get("proposals") or []
    slug = project_slug(cfg, workdir)
    out: list[Path] = []
    if proposals:
        drafts_dir.mkdir(parents=True, exist_ok=True)
        start = _next_draft_start(drafts_dir, mission_id)
        for i, p in enumerate(proposals, start):
            if slug is not None:
                p = {**p, "project_slug_hint": slug}
            fp = drafts_dir / f"{mission_id}-{i}.json"
            fp.write_text(json.dumps(p, ensure_ascii=False, indent=1))
            out.append(fp)
    return out

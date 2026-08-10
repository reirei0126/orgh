# 判断基準台帳(最小版)+ペルソナ検収ゲート 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 戦略設計書(docs/strategy/2026-08-10-value-strategy-design.md)の実行順序1〜2 — オーナー判断基準を保持・成長させる基準台帳の最小版と、消費者+デザイナーペルソナによる検収ゲートをorghコアに実装する。

**Architecture:** 基準台帳は playbooks と同型のMarkdown行形式+日付降順注入(`orgh/criteria.py` 新設)。オーナー裁定は `orgh verdict` CLIで記録し、蒸留ロール(claude -p 1発)が台帳差分の下書きを `criteria/_drafts/` に生成、`orgh criteria approve` で本台帳へ反映(下書き+ワンタップ承認ガバナンス)。ペルソナ検収は Reviewer 合格後の追加ゲートとして `_attempt_loop` に挿入し、不合格は既存の差し戻しループ(`_retry_prompt`)に流す。ペルソナ裁定は evidence(スクショ等の証拠パス)なしの合格を無効とする(証拠チャネル原則)。

**Tech Stack:** Python 3.10+(既存orghコア)、pytest+モックclaudeバイナリ(tests/mocks/claude)、追加依存なし。

## Global Constraints

- 新規外部依存を追加しない(stdlib+既存構成のみ)
- 既存configで挙動が一切変わらないこと: `criteria_dir` 未設定・`personas.enabled` 空なら全て従来動作(後方互換)
- Task/Mission状態の変更は必ず `with store.lock:` で囲む(state.py の規約)
- コメント・docstring・ledgerイベント名は既存コードの日本語スタイルに合わせる
- 各タスク完了時に `pytest` 全緑(既存190件+新規)を確認してからコミット
- コミットは orgh リポの慣例に従う(例: `feat: ...` / `fix: ...` 日本語本文)
- プロンプトファイルの役割マーカー規約: モックは本文中の `(Planner)` `(Reviewer)` 等で分岐する。新設プロンプトにも `(CriteriaDistill)` `(Persona:consumer)` `(Persona:designer)` を本文に含めること

---

### Task 1: criteria.py コア(台帳の読み書きと文脈注入)

**Files:**
- Create: `orgh/criteria.py`
- Modify: `orgh/state.py`(ConfigSchema に `criteria_dir: str = "criteria"` を追加。`runs_dir`/`prompts_dir` の並び、95行目付近)
- Test: `tests/test_criteria.py`

**Interfaces:**
- Produces: `criteria_dir(cfg: dict) -> Path` / `criteria_context(cfg: dict, max_chars: int = 4000) -> str` / `next_id(cdir: Path, prefix: str) -> str` / `append_entry(cdir: Path, category: str, prefix: str, strength: str, text: str, src: str) -> str`
- 台帳行形式(playbooksのメタタグと同系): `- DESIGN-001 [norm]: 視覚検証なしの合格を信用しない <!-- src:7307189e d:2026-08-10 -->`。strength は `norm`(絶対規範)/`pref`(選好)。カテゴリ=ファイル名stem(`criteria/design.md` 等)。`_` 始まりのディレクトリ・ファイル(`_drafts/` 等)は台帳走査から除外

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_criteria.py
"""基準台帳(criteria)の読み書きと文脈注入。戦略設計書 柱2の最小版。"""
from __future__ import annotations

from pathlib import Path

from orgh.criteria import append_entry, criteria_context, criteria_dir, next_id


class TestLedger:
    def test_empty_dir_returns_placeholder(self, tmp_path):
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        assert criteria_context(cfg) == "(no criteria yet)"

    def test_append_and_next_id(self, tmp_path):
        cdir = tmp_path / "criteria"
        line = append_entry(cdir, "design", "DESIGN", "norm",
                            "視覚検証なしの合格を信用しない", src="7307189e")
        assert "DESIGN-001 [norm]:" in line
        assert "src:7307189e" in line
        assert (cdir / "design.md").read_text().count("DESIGN-001") == 1
        assert next_id(cdir, "DESIGN") == "DESIGN-002"

    def test_next_id_scans_across_files(self, tmp_path):
        cdir = tmp_path / "criteria"
        append_entry(cdir, "design", "DESIGN", "norm", "a", src="m1")
        append_entry(cdir, "general", "DESIGN", "pref", "b", src="m2")
        assert next_id(cdir, "DESIGN") == "DESIGN-003"

    def test_context_packs_newest_first(self, tmp_path):
        cdir = tmp_path / "criteria"
        (cdir).mkdir()
        (cdir / "design.md").write_text(
            "- DESIGN-001 [norm]: 古い基準 <!-- src:m1 d:2020-01-01 -->\n"
            "- DESIGN-002 [norm]: 新しい基準 <!-- src:m2 d:2026-08-10 -->\n")
        ctx = criteria_context({"criteria_dir": str(cdir)}, max_chars=60)
        assert "新しい基準" in ctx      # 新しい行が優先で生き残る
        assert "古い基準" not in ctx

    def test_drafts_dir_excluded_from_context(self, tmp_path):
        cdir = tmp_path / "criteria"
        (cdir / "_drafts").mkdir(parents=True)
        (cdir / "_drafts" / "x.md").write_text("- FAKE-001 [norm]: 下書き\n")
        (cdir / "design.md").write_text(
            "- DESIGN-001 [norm]: 本採用 <!-- src:m1 d:2026-08-10 -->\n")
        ctx = criteria_context({"criteria_dir": str(cdir)})
        assert "本採用" in ctx and "下書き" not in ctx
```

- [ ] **Step 2: 落ちることを確認** — Run: `pytest tests/test_criteria.py -v` / Expected: FAIL(`ModuleNotFoundError: orgh.criteria`)

- [ ] **Step 3: 最小実装**

```python
# orgh/criteria.py
"""オーナー判断基準台帳(戦略設計書 柱2の最小版)。

playbooks(作業のやり方の教訓)と対をなす「判断の一般原則」の置き場。
形式はplaybooksと同系のMarkdown行+メタタグで、ユーザーが直接編集できる。
更新ガバナンスは「下書き+ワンタップ承認」: 自動生成は _drafts/ 止まりで、
本台帳への反映は必ず orgh criteria approve(=オーナー操作)を通る。
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

_ENTRY_RE = re.compile(r"^- ([A-Z]+)-(\d{3}) \[(norm|pref)\]:")
_META_RE = re.compile(r"<!-- src:(\S+) d:(\d{4}-\d{2}-\d{2}) -->")


def criteria_dir(cfg: dict) -> Path:
    return Path(cfg.get("criteria_dir", "criteria")).expanduser()


def _ledger_files(cdir: Path) -> list[Path]:
    """_始まり(_drafts/_rejected等)は台帳走査から除外する。"""
    if not cdir.is_dir():
        return []
    return sorted(p for p in cdir.glob("*.md") if not p.name.startswith("_"))


def criteria_context(cfg: dict, max_chars: int = 4000) -> str:
    """台帳をReviewer/ペルソナのプロンプトへ注入する(playbookと同じ日付降順詰め)。"""
    entries: list[tuple[str, str]] = []
    for p in _ledger_files(criteria_dir(cfg)):
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            m = _META_RE.search(line)
            entries.append((m.group(2) if m else "0000-00-00", line))
    entries.sort(key=lambda e: e[0], reverse=True)
    picked, total = [], 0
    for _, line in entries:
        total += len(line) + 1
        if total > max_chars and picked:
            break
        picked.append(line)
    return "\n".join(picked) if picked else "(no criteria yet)"


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
```

state.py の ConfigSchema(95行目付近、`prompts_dir` の下)に1行追加:

```python
    criteria_dir: str = "criteria"
```

- [ ] **Step 4: 合格確認** — Run: `pytest tests/test_criteria.py tests/test_config.py -v` / Expected: PASS(config未知キー警告が出ないことも test_config で担保される)

- [ ] **Step 5: Commit** — `git add orgh/criteria.py orgh/state.py tests/test_criteria.py && git commit -m "feat(criteria): 判断基準台帳のコア(台帳形式・ID採番・日付降順の文脈注入)"`

---

### Task 2: Reviewerへの基準注入と引用義務

**Files:**
- Modify: `orgh/planner.py`(`review()` 120-129行目を分割: プロンプト構築を `build_review_prompt()` に抽出し criteria を注入)
- Modify: `prompts/reviewer.md`
- Test: `tests/test_criteria.py`(クラス追加)

**Interfaces:**
- Consumes: Task 1 の `criteria_context(cfg)`
- Produces: `build_review_prompt(cfg: dict, task: Task) -> str`(review() 内部から使用。テスト可能にするための抽出)
- reviewer.md の新プレースホルダ `{criteria}`。**注意: str.format は未使用kwargを無視するので、ユーザーが旧版reviewer.mdを使い続けても壊れない(後方互換)**

- [ ] **Step 1: 失敗するテストを書く**(tests/test_criteria.py に追加)

```python
from orgh.planner import build_review_prompt
from orgh.state import Task


class TestReviewerInjection:
    def test_review_prompt_contains_criteria(self, tmp_path, cfg):
        cdir = tmp_path / "criteria"
        append_entry(cdir, "design", "DESIGN", "norm",
                     "視覚検証なしの合格を信用しない", src="7307189e")
        cfg["criteria_dir"] = str(cdir)
        t = Task(id="t1", title="UI改修", prompt="やる",
                 acceptance=["画面が表示される"])
        p = build_review_prompt(cfg, t)
        assert "DESIGN-001" in p
        assert "基準" in p          # 台帳セクションの見出しが存在する

    def test_review_prompt_without_ledger(self, cfg, tmp_path):
        cfg["criteria_dir"] = str(tmp_path / "none")
        t = Task(id="t1", title="x", prompt="y", acceptance=["z"])
        assert "(no criteria yet)" in build_review_prompt(cfg, t)
```

- [ ] **Step 2: 落ちることを確認** — Run: `pytest tests/test_criteria.py -v` / Expected: FAIL(`ImportError: build_review_prompt`)

- [ ] **Step 3: 実装** — planner.py の `review()` を分割:

```python
from .criteria import criteria_context


def build_review_prompt(cfg: dict, task: Task) -> str:
    tmpl = _read_prompt(cfg, "reviewer.md")
    return tmpl.format(title=task.title, prompt=task.prompt,
                       acceptance="\n".join(f"- {a}" for a in task.acceptance),
                       output=task.last_output[:12000],
                       criteria=criteria_context(cfg))


def review(cfg: dict, task: Task, workdir: str,
          budget: Budget | None = None,
          registry_key: str | None = None) -> tuple[bool, str]:
    data = _ask_json(cfg, "reviewer", build_review_prompt(cfg, task),
                     workdir=workdir, budget=budget, registry_key=registry_key)
    return bool(data.get("pass")), data.get("feedback", "")
```

prompts/reviewer.md の「判定手順」の下に追記(既存文面は変更しない):

```markdown
3. 下記のオーナー判断基準に違反する成果物は、acceptanceを満たしていても差し戻せ。
   差し戻すときはfeedbackに違反した基準ID(例: DESIGN-001)を引用せよ

## オーナー判断基準(台帳)
{criteria}
```

- [ ] **Step 4: 合格確認** — Run: `pytest tests/test_criteria.py tests/test_st_scenarios.py -v` / Expected: PASS(STは旧経路の無変化を担保)

- [ ] **Step 5: Commit** — `git commit -am "feat(criteria): Reviewerへの基準台帳注入と基準ID引用義務"`

---

### Task 3: オーナー裁定の記録と蒸留(orgh verdict)

**Files:**
- Create: `prompts/criteria_distill.md`
- Modify: `orgh/criteria.py`(`distill_verdict()` 追加)
- Modify: `orgh/cli.py`(`verdict` サブコマンド。39-62行目の add_parser 群と同スタイル)
- Modify: `tests/mocks/claude`(`(CriteriaDistill)` 分岐追加)/ `tests/conftest.py`(MOCK_ENV_VARS に `MOCK_CRITERIA_JSON` 追加)
- Test: `tests/test_criteria.py`(クラス追加)

**Interfaces:**
- Consumes: `planner._ask_json(cfg, role, prompt, budget=None)`(既存)、`RunStore(runs_dir, mission_id)`(既存)
- Produces: `distill_verdict(cfg: dict, mission_id: str, intent: str, passed: bool, reason: str) -> list[Path]` — 生成した下書きファイルのパス群を返す。下書きはJSON: `{"category": "design", "prefix": "DESIGN", "strength": "norm", "text": "..."}` を `criteria/_drafts/<mission_id>-<n>.json` へ
- CLI: `orgh verdict <mission_id> --pass|--fail --reason <text>` — verdicts.jsonl追記 + ledgerに `mission.owner_verdict` + 蒸留下書き生成
- ロール `criteria_distill` は config の roles に無ければデフォルト `{"model": "sonnet", "max_turns": 5, "allowed_tools": "Read"}` を注入(後方互換)

- [ ] **Step 1: プロンプトを書く**

```markdown
# prompts/criteria_distill.md
あなたは判断基準の書記官(CriteriaDistill)。オーナーが下した検収裁定から、
**今後の全ミッションの裁定で再利用できる一般原則**だけを台帳下書きとして抽出せよ。
このミッション固有の一過性の事情・具体数値は抽出するな。既存台帳と重複する
原則も抽出するな。基準を満たす原則がなければproposalsは空配列にせよ。

strength は norm(違反したら合格にできない絶対規範)か pref(選好)を選べ。
prefix はカテゴリの大文字英字(例: DESIGN, PROD, ENG)。

## ミッション
{intent}
## オーナー裁定
{verdict}: {reason}
## 既存台帳(重複禁止の参照用)
{criteria}

## 出力(JSONのみ)
{{
  "proposals": [
    {{"category": "design", "prefix": "DESIGN", "strength": "norm",
      "text": "原則の一文"}}
  ]
}}
```

- [ ] **Step 2: 失敗するテストを書く**(tests/test_criteria.py に追加)

```python
import json

from orgh.criteria import distill_verdict


class TestVerdictDistill:
    def test_fail_verdict_generates_draft(self, cfg, mock_state_dir,
                                          tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        monkeypatch.setenv("MOCK_CRITERIA_JSON", json.dumps({
            "proposals": [{"category": "design", "prefix": "DESIGN",
                           "strength": "norm",
                           "text": "視覚検証なしの合格を信用しない"}]},
            ensure_ascii=False))
        drafts = distill_verdict(cfg, "m123", "筐体UI刷新",
                                 passed=False, reason="レバー不可視・リール真っ黒")
        assert len(drafts) == 1
        body = json.loads(drafts[0].read_text())
        assert body["prefix"] == "DESIGN"
        # 本台帳にはまだ載らない(下書き+承認ガバナンス)
        assert criteria_context(cfg) == "(no criteria yet)"

    def test_empty_proposals_writes_nothing(self, cfg, mock_state_dir,
                                            tmp_path, monkeypatch):
        cfg["criteria_dir"] = str(tmp_path / "criteria")
        monkeypatch.setenv("MOCK_CRITERIA_JSON", '{"proposals": []}')
        assert distill_verdict(cfg, "m1", "x", passed=True, reason="良い") == []
```

- [ ] **Step 3: 落ちることを確認** — Run: `pytest tests/test_criteria.py::TestVerdictDistill -v` / Expected: FAIL(`ImportError: distill_verdict`)

- [ ] **Step 4: 実装**

まず planner.py にロールのデフォルト注入ヘルパを追加する(**`bin` はreviewerロールから継承する**。conftestのモック構成やカスタムバイナリ環境で、新ロールごとにbin再指定を不要にするため。これが無いとテストが実claudeバイナリを呼んでしまう):

```python
def role_with_default(cfg: dict, role: str, default: dict) -> dict:
    """rolesに未定義のロールへデフォルト設定を注入したcfgコピーを返す。
    binはreviewerロールを継承する(モック・カスタムバイナリ環境の互換)。"""
    roles = {**cfg.get("roles", {})}
    if role not in roles:
        base = {k: v for k, v in roles.get("reviewer", {}).items()
                if k == "bin"}
        roles[role] = {**base, **default}
    return {**cfg, "roles": roles}
```

criteria.py に追加(循環import回避のため planner は関数内import):

```python
import json


def distill_verdict(cfg: dict, mission_id: str, intent: str,
                    passed: bool, reason: str) -> list[Path]:
    """オーナー裁定から台帳差分の下書きを生成する(本台帳には書かない)。"""
    from .planner import _ask_json, _read_prompt, role_with_default
    cfg = role_with_default(cfg, "criteria_distill", {
        "model": "sonnet", "max_turns": 5, "allowed_tools": "Read"})
    tmpl = _read_prompt(cfg, "criteria_distill.md")
    prompt = tmpl.format(intent=intent,
                         verdict="合格" if passed else "不合格",
                         reason=reason, criteria=criteria_context(cfg))
    data = _ask_json(cfg, "criteria_distill", prompt)
    drafts_dir = criteria_dir(cfg) / "_drafts"
    out: list[Path] = []
    for i, p in enumerate(data.get("proposals") or [], 1):
        drafts_dir.mkdir(parents=True, exist_ok=True)
        fp = drafts_dir / f"{mission_id}-{i}.json"
        fp.write_text(json.dumps(p, ensure_ascii=False, indent=1))
        out.append(fp)
    return out
```

cli.py にサブコマンド追加(既存の add_parser 群・dispatch と同スタイル):

```python
    vp = sub.add_parser("verdict")   # オーナー検収裁定の記録と基準蒸留
    vp.add_argument("mission_id")
    g = vp.add_mutually_exclusive_group(required=True)
    g.add_argument("--pass", dest="passed", action="store_true")
    g.add_argument("--fail", dest="passed", action="store_false")
    vp.add_argument("--reason", required=True)
```

dispatch側(main()内の既存 `if args.cmd == ...: ...; return` 群に追加。cli.py冒頭のimport群に `import time` と `from .criteria import distill_verdict` を追加すること):

```python
    if args.cmd == "verdict":
        store = RunStore(cfg.get("runs_dir", "runs"), args.mission_id)
        mission = store.load(reset_inflight=False)  # 読むだけ。実行状態は触らない
        with open(store.dir / "verdicts.jsonl", "a") as f:
            f.write(json.dumps({"ts": time.time(), "passed": args.passed,
                                "reason": args.reason}, ensure_ascii=False) + "\n")
        store.log("mission.owner_verdict", passed=args.passed,
                  reason=args.reason[:500])
        drafts = distill_verdict(cfg, args.mission_id, mission.intent,
                                 args.passed, args.reason)
        for fp in drafts:
            print(f"draft: {fp}")
        print(f"下書き{len(drafts)}件。orgh criteria list で確認、"
              f"orgh criteria approve <name> で本台帳へ反映")
        return
```

(`RunStore.load(self, reset_inflight: bool = True) -> Mission` — state.py:261。cli.pyのdocstring先頭のコマンド一覧にも `orgh verdict` / `orgh criteria` の2行を追記すること)

tests/mocks/claude に分岐追加(`(GC)` 分岐の直前):

```python
    if "(CriteriaDistill)" in prompt:
        _log_call(state, {"role": "criteria_distill", "marker": marker})
        out = os.environ.get("MOCK_CRITERIA_JSON") or json.dumps(
            {"proposals": []}, ensure_ascii=False)
        print(_envelope(out, session_id="sess-distill"))
        return 0
```

conftest.py の MOCK_ENV_VARS に `"MOCK_CRITERIA_JSON"` を追加。

- [ ] **Step 5: 合格確認** — Run: `pytest tests/test_criteria.py -v` / Expected: PASS
- [ ] **Step 6: CLI疎通確認** — Run: `pytest tests/test_st_scenarios.py -v && python -c "from orgh.cli import main"` / Expected: PASS・ImportErrorなし
- [ ] **Step 7: Commit** — `git add -A && git commit -m "feat(criteria): orgh verdict — オーナー裁定の記録と台帳下書きの蒸留生成"`

---

### Task 4: 下書きの承認・棄却CLI(orgh criteria)

**Files:**
- Modify: `orgh/criteria.py`(`list_drafts()` / `approve_draft()` / `reject_draft()`)
- Modify: `orgh/cli.py`(`criteria` サブコマンド)
- Test: `tests/test_criteria.py`(クラス追加)

**Interfaces:**
- Consumes: Task 1 の `append_entry()` / `criteria_dir()`
- Produces: `list_drafts(cfg) -> list[Path]` / `approve_draft(cfg, name: str) -> str`(反映した台帳行を返す)/ `reject_draft(cfg, name: str) -> Path`(`_drafts/rejected/` への移動先を返す。**削除はしない** — 棄却理由の見直し(復活)を可能にするため)
- CLI: `orgh criteria list` / `orgh criteria approve <name>` / `orgh criteria reject <name>`(name は `<mission_id>-<n>` 拡張子なし)

- [ ] **Step 1: 失敗するテストを書く**

```python
from orgh.criteria import approve_draft, list_drafts, reject_draft


def _make_draft(cdir: Path, name: str) -> Path:
    d = cdir / "_drafts"
    d.mkdir(parents=True, exist_ok=True)
    fp = d / f"{name}.json"
    fp.write_text(json.dumps({"category": "design", "prefix": "DESIGN",
                              "strength": "norm", "text": "原則X"},
                             ensure_ascii=False))
    return fp


class TestCriteriaCli:
    def test_approve_moves_draft_to_ledger(self, tmp_path):
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        _make_draft(Path(cfg["criteria_dir"]), "m123-1")
        line = approve_draft(cfg, "m123-1")
        assert "DESIGN-001" in line
        assert "原則X" in criteria_context(cfg)
        assert list_drafts(cfg) == []          # 下書きは消費済み

    def test_reject_keeps_record(self, tmp_path):
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        _make_draft(Path(cfg["criteria_dir"]), "m123-1")
        moved = reject_draft(cfg, "m123-1")
        assert moved.exists() and "rejected" in str(moved)
        assert criteria_context(cfg) == "(no criteria yet)"

    def test_approve_missing_draft_raises(self, tmp_path):
        cfg = {"criteria_dir": str(tmp_path / "criteria")}
        import pytest
        with pytest.raises(FileNotFoundError):
            approve_draft(cfg, "nope-1")
```

- [ ] **Step 2: 落ちることを確認** — Run: `pytest tests/test_criteria.py::TestCriteriaCli -v` / Expected: FAIL

- [ ] **Step 3: 実装**(criteria.py に追加)

```python
def list_drafts(cfg: dict) -> list[Path]:
    d = criteria_dir(cfg) / "_drafts"
    return sorted(d.glob("*.json")) if d.is_dir() else []


def _draft_path(cfg: dict, name: str) -> Path:
    fp = criteria_dir(cfg) / "_drafts" / f"{name}.json"
    if not fp.is_file():
        raise FileNotFoundError(
            f"draft not found: {fp}. orgh criteria list で確認せよ")
    return fp


def approve_draft(cfg: dict, name: str) -> str:
    """下書きを本台帳へ反映する(ワンタップ承認の実体)。"""
    fp = _draft_path(cfg, name)
    p = json.loads(fp.read_text())
    line = append_entry(criteria_dir(cfg), p["category"], p["prefix"],
                        p.get("strength", "pref"), p["text"], src=name)
    fp.unlink()
    return line


def reject_draft(cfg: dict, name: str) -> Path:
    """棄却は削除ではなく退避(棄却理由の見直し・復活を可能にする)。"""
    fp = _draft_path(cfg, name)
    dst_dir = criteria_dir(cfg) / "_drafts" / "rejected"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / fp.name
    fp.rename(dst)
    return dst
```

cli.py:

```python
    cp = sub.add_parser("criteria")
    cp.add_argument("action", choices=["list", "approve", "reject"])
    cp.add_argument("name", nargs="?")
```

dispatch(import群に `from .criteria import approve_draft, criteria_context, list_drafts, reject_draft` を追加):

```python
    if args.cmd == "criteria":
        if args.action == "list":
            for fp in list_drafts(cfg):
                print(f"[draft] {fp.stem}: {fp.read_text()}")
            print("--- 台帳 ---")
            print(criteria_context(cfg, max_chars=100000))
            return
        if not args.name:
            raise SystemExit("approve/reject には name が必要(orgh criteria list で確認)")
        if args.action == "approve":
            print(approve_draft(cfg, args.name))
        else:
            print(f"rejected -> {reject_draft(cfg, args.name)}")
        return
```

- [ ] **Step 4: 合格確認** — Run: `pytest tests/test_criteria.py -v` / Expected: PASS
- [ ] **Step 5: Commit** — `git commit -am "feat(criteria): orgh criteria list/approve/reject — 下書き+ワンタップ承認ガバナンス"`

---

### Task 5: ペルソナ設定スキーマとfinal_task自動割り当て

**Files:**
- Modify: `orgh/state.py`(`PersonasCfg` dataclass追加+`ConfigSchema.personas` / `Task.personas` フィールド追加、216行目 `replans` の下)
- Modify: `orgh/orchestrator.py`(`_assign_personas()` 追加、`_run_mission_locked` 400行目 `store.save(mission)` の直前で呼ぶ)
- Test: `tests/test_personas.py`

**Interfaces:**
- Produces: `Task.personas: list[str]`(デフォルト空)/ config `personas: {enabled: [...], apply: "final_task"}` / `_assign_personas(cfg: dict, mission: Mission) -> None`
- 割り当て規則: `personas.enabled` が空なら何もしない。final_task = 誰のdepsにも現れないタスク。Plannerが明示した `personas` は上書きしない

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_personas.py
"""ペルソナ検収ゲート(戦略設計書 柱1)。final_task割り当てと検収ループ。"""
from __future__ import annotations

from orgh.orchestrator import _assign_personas, run_mission
from orgh.state import Mission, RunStore


def _task(id: str, deps=None, **kw) -> dict:
    return {"id": id, "title": f"task {id}", "prompt": f"作業 [[MARK:{id}]]",
            "worker": "claude_code", "deps": deps or [],
            "acceptance": ["mock acceptance"], "workdir": ".", **kw}


class TestAssign:
    def test_final_task_gets_personas(self):
        m = Mission.new(intent="x", context_digest="",
                        tasks=[_task("t1"), _task("t2", deps=["t1"])])
        _assign_personas({"personas": {"enabled": ["consumer"]}}, m)
        assert m.tasks[0].personas == []          # 中間タスクは対象外
        assert m.tasks[1].personas == ["consumer"]

    def test_disabled_is_noop(self):
        m = Mission.new(intent="x", context_digest="", tasks=[_task("t1")])
        _assign_personas({}, m)
        assert m.tasks[0].personas == []

    def test_planner_explicit_wins(self):
        m = Mission.new(intent="x", context_digest="",
                        tasks=[_task("t1", personas=["designer"])])
        _assign_personas({"personas": {"enabled": ["consumer"]}}, m)
        assert m.tasks[0].personas == ["designer"]
```

- [ ] **Step 2: 落ちることを確認** — Run: `pytest tests/test_personas.py -v` / Expected: FAIL

- [ ] **Step 3: 実装**

state.py(Task末尾に追加):

```python
    personas: list[str] = field(default_factory=list)  # 検収ゲートのペルソナ名(空=通常レビューのみ)
```

同じく state.py の config schema 群に:

```python
@dataclass
class PersonasCfg:
    """ペルソナ検収ゲート(消費者・デザイナー等)。enabledが空なら完全無効。"""
    enabled: list[str] = field(default_factory=list)
    apply: str = "final_task"    # 現状はfinal_taskのみ(依存されないタスクに適用)
```

`ConfigSchema` に `personas: PersonasCfg | None = None` を追加。

orchestrator.py:

```python
def _assign_personas(cfg: dict, mission: Mission) -> None:
    """final_task(誰のdepsにも現れないタスク)へ検収ペルソナを割り当てる。
    Plannerが明示指定したタスクは尊重して上書きしない。"""
    enabled = (cfg.get("personas") or {}).get("enabled") or []
    if not enabled:
        return
    dep_ids = {d for t in mission.tasks for d in t.deps}
    for t in mission.tasks:
        if t.id not in dep_ids and not t.personas:
            t.personas = list(enabled)
```

`_run_mission_locked` の `store.save(mission)`(400行目)の直前に `_assign_personas(cfg, mission)` を挿入。

- [ ] **Step 4: 合格確認** — Run: `pytest tests/test_personas.py tests/test_config.py tests/test_st_scenarios.py -v` / Expected: PASS
- [ ] **Step 5: Commit** — `git commit -am "feat(personas): ペルソナ設定スキーマとfinal_taskへの自動割り当て"`

---

### Task 6: persona_review(証拠チャネル原則つき裁定)

**Files:**
- Create: `prompts/persona_consumer.md` / `prompts/persona_designer.md`
- Modify: `orgh/planner.py`(`persona_review()` 追加)
- Modify: `tests/mocks/claude`(`(Persona:` 分岐)/ `tests/conftest.py`(MOCK_ENV_VARS追加)
- Test: `tests/test_personas.py`(クラス追加)

**Interfaces:**
- Consumes: `_ask_json` / `_read_prompt` / `criteria_context`(既存)、`role_with_default(cfg, role, default) -> dict`(Task 3でplanner.pyに追加済み)
- Produces: `persona_review(cfg, persona: str, task: Task, workdir: str, budget=None, registry_key=None) -> tuple[bool, str]`。ロール設定は `cfg["roles"][f"persona_{persona}"]`、無ければデフォルト `{"model": "sonnet", "max_turns": 30, "allowed_tools": "Read,Bash,Glob,Grep"}` を注入
- 裁定JSON契約: `{"pass": bool, "feedback": str, "evidence": [実際に確認した証拠のパスや実行コマンドの文字列]}`。**pass=true かつ evidence空 は ValueError**(証拠なし合格=ハンコ裁定の禁止。呼び出し側のロールリトライで再裁定される)。pass=false の evidence空 は許容(起動不能等はそれ自体が指摘)
- モック分岐: プロンプト中の `(Persona:<name>)` で識別。環境変数 `MOCK_PERSONA_REJECT_ONCE`(マーカー列: 初回のみ差し戻し)/ `MOCK_PERSONA_ALWAYS_FAIL` / `MOCK_PERSONA_NO_EVIDENCE`(pass=trueをevidence空で返す=違反ケース)

- [ ] **Step 1: プロンプト2本を書く**

```markdown
# prompts/persona_consumer.md
あなたは消費者ペルソナ(Persona:consumer)。この成果物を「初めて触る一般ユーザー」
として実際に使い、体験として合格かを裁定せよ。エンジニアのレビューは既に合格して
いる。あなたの仕事はコードを読むことではなく**触って確かめる**ことである。

裁定手順(証拠チャネル原則):
1. 成果物を実際に起動・操作せよ(ビルド、ローカルサーバ起動、CLI実行等をBashで行う)
2. 画面のある成果物はヘッドレスChrome等でスクリーンショットを撮り、Readで**必ず目視**せよ
   例: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --screenshot=shot.png --window-size=1280,800 <URL or file>
3. evidenceには実際に確認した証拠(スクショのパス・実行したコマンド)を列挙せよ。
   **証拠なしの合格裁定は無効として棄却される**
4. 下記のオーナー判断基準に違反する体験は不合格とし、feedbackに基準IDを引用せよ

## タスク: {title}
## 指示内容
{prompt}
## 受け入れ条件(参考。あなたの裁定軸は体験品質)
{acceptance}
## workerの最終報告
{output}
## オーナー判断基準(台帳)
{criteria}

## 出力(JSONのみ)
{{
  "pass": true/false,
  "feedback": "不合格なら、workerが即修正に着手できる具体的な体験上の指摘。合格なら空文字",
  "evidence": ["確認に使ったスクショのパス・実行コマンド"]
}}
```

```markdown
# prompts/persona_designer.md
あなたはデザイナーペルソナ(Persona:designer)。この成果物の**完成度・磨き**が
製品水準かを裁定せよ。「動く」は合格理由にならない。視覚的一貫性・余白・
タイポグラフィ・状態変化(hover/エラー/空状態)の詰めを見る。

裁定手順(証拠チャネル原則):
1. 画面のある成果物は必ずスクリーンショットを撮ってReadで目視せよ(複数状態・複数画面)
   例: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --screenshot=shot.png --window-size=1280,800 <URL or file>
2. 画面のない成果物(CLI・文書等)は出力の実物を確認し、その体裁を裁定せよ
3. evidenceには確認した証拠を列挙せよ。**証拠なしの合格裁定は無効として棄却される**
4. 下記のオーナー判断基準(特にDESIGN系)に違反したら不合格とし、基準IDを引用せよ

## タスク: {title}
## 指示内容
{prompt}
## 受け入れ条件(参考。あなたの裁定軸は完成度)
{acceptance}
## workerの最終報告
{output}
## オーナー判断基準(台帳)
{criteria}

## 出力(JSONのみ)
{{
  "pass": true/false,
  "feedback": "不合格なら具体的な完成度の指摘(どの画面のどこが、どう未達か)。合格なら空文字",
  "evidence": ["確認に使ったスクショのパス・実行コマンド"]
}}
```

- [ ] **Step 2: 失敗するテストを書く**(tests/test_personas.py に追加)

```python
import pytest

from orgh.planner import persona_review
from orgh.state import Task


def _t(id="p1") -> Task:
    return Task(id=id, title="UI", prompt=f"作業 [[MARK:{id}]]",
                acceptance=["a"], last_output="done")


class TestPersonaReview:
    def test_pass_with_evidence(self, cfg, mock_state_dir):
        ok, fb = persona_review(cfg, "consumer", _t(), workdir=".")
        assert ok and fb == ""

    def test_no_evidence_pass_is_invalid(self, cfg, mock_state_dir,
                                         monkeypatch):
        monkeypatch.setenv("MOCK_PERSONA_NO_EVIDENCE", "p1")
        with pytest.raises(ValueError, match="証拠"):
            persona_review(cfg, "consumer", _t(), workdir=".")

    def test_fail_without_evidence_is_valid(self, cfg, mock_state_dir,
                                            monkeypatch):
        monkeypatch.setenv("MOCK_PERSONA_ALWAYS_FAIL", "p1")
        ok, fb = persona_review(cfg, "designer", _t(), workdir=".")
        assert not ok and "MARK" in fb
```

- [ ] **Step 3: 落ちることを確認** — Run: `pytest tests/test_personas.py::TestPersonaReview -v` / Expected: FAIL

- [ ] **Step 4: 実装**

planner.py に追加:

```python
_PERSONA_ROLE_DEFAULT = {"model": "sonnet", "max_turns": 30,
                         "allowed_tools": "Read,Bash,Glob,Grep"}


def persona_review(cfg: dict, persona: str, task: Task, workdir: str,
                   budget: Budget | None = None,
                   registry_key: str | None = None) -> tuple[bool, str]:
    """ペルソナ検収(戦略設計書 柱1)。証拠なしの合格裁定はValueErrorで無効化する
    (同じLLMが自分に頷くだけのハンコ裁定の禁止)。呼び出し側のロールリトライで
    再裁定され、リトライ枯渇時はworker成果を保持したままfailedになる。"""
    role = f"persona_{persona}"
    cfg = role_with_default(cfg, role, _PERSONA_ROLE_DEFAULT)
    tmpl = _read_prompt(cfg, f"{role}.md")
    prompt = tmpl.format(title=task.title, prompt=task.prompt,
                         acceptance="\n".join(f"- {a}" for a in task.acceptance),
                         output=task.last_output[:12000],
                         criteria=criteria_context(cfg))
    data = _ask_json(cfg, role, prompt, workdir=workdir, budget=budget,
                     registry_key=registry_key)
    evidence = data.get("evidence") or []
    if data.get("pass") and not evidence:
        raise ValueError(
            f"persona {persona} が証拠なしで合格裁定を返した(証拠チャネル原則違反)")
    return bool(data.get("pass")), data.get("feedback", "")
```

(planner.py 冒頭に `from .criteria import criteria_context` — Task 2 で追加済み)

tests/mocks/claude に分岐追加(`(Reviewer)` 分岐の直前に置く):

```python
    pm = re.search(r"\(Persona:(\w+)\)", prompt)
    if pm:
        persona = pm.group(1)
        reject_once = marker in _env_set("MOCK_PERSONA_REJECT_ONCE")
        always_fail = marker in _env_set("MOCK_PERSONA_ALWAYS_FAIL")
        no_evidence = marker in _env_set("MOCK_PERSONA_NO_EVIDENCE")
        once_flag = state / f"persona_once_{persona}_{marker}"
        if no_evidence:
            verdict = {"pass": True, "feedback": "", "evidence": []}
        elif always_fail or (reject_once and not once_flag.exists()):
            once_flag.touch()
            verdict = {"pass": False,
                       "feedback": f"ペルソナ差し戻し [[MARK:{marker}]]",
                       "evidence": ["shot.png"]}
        else:
            verdict = {"pass": True, "feedback": "", "evidence": ["shot.png"]}
        _log_call(state, {"role": "persona", "persona": persona,
                          "marker": marker, "passed": verdict["pass"]})
        print(_envelope(json.dumps(verdict, ensure_ascii=False),
                        session_id=f"sess-persona-{persona}"))
        return 0
```

conftest.py の MOCK_ENV_VARS に `"MOCK_PERSONA_REJECT_ONCE", "MOCK_PERSONA_ALWAYS_FAIL", "MOCK_PERSONA_NO_EVIDENCE"` を追加。

- [ ] **Step 5: 合格確認** — Run: `pytest tests/test_personas.py -v` / Expected: PASS
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(personas): persona_review — 証拠チャネル原則つきペルソナ裁定(consumer/designer)"`

---

### Task 7: 検収ゲートのorchestrator統合

**Files:**
- Modify: `orgh/orchestrator.py`(`_review_with_retry` 107-131行目を汎用化し、`_attempt_loop` の合格分岐 263-286行目にペルソナループを挿入)
- Test: `tests/test_personas.py`(STクラス追加)

**Interfaces:**
- Consumes: Task 6 の `persona_review()`、Task 5 の `Task.personas`
- Produces: ledgerイベント `task.persona_review`(task, persona, passed)/ ロールリトライイベント `role.retry`(role=`persona_<name>`)
- 挿入位置と順序: reviewer合格 → ペルソナを `t.personas` の順に直列実行 → 全合格で従来のcommit/done処理へ。1つでも不合格なら reviewer不合格と同じ差し戻しループ(`_retry_prompt`)へ。ペルソナのfeedbackがREPLAN:で始まっても**REPLANエスカレーションはしない**(計画欠陥の裁定はReviewerの責務。feedbackに `[<persona>ペルソナ検収]` プレフィックスを付けてworkerに渡す)
- ペルソナ呼び出し自体の失敗(証拠なし合格ValueError含む)はロールリトライ(reviewer同様 retries=2)。枯渇時は reviewer枯渇と同様に worker成果を保持して failed

- [ ] **Step 1: 失敗するテストを書く**(tests/test_personas.py に追加)

```python
class TestPersonaGateST:
    def _cfg(self, cfg):
        cfg["personas"] = {"enabled": ["consumer", "designer"]}
        cfg["loop"]["infra_retry_wait"] = 0
        return cfg

    def test_persona_reject_once_then_pass(self, cfg, mock_state_dir,
                                           monkeypatch):
        """consumer差し戻し→worker修正→再レビュー→全ペルソナ合格→done。"""
        monkeypatch.setenv("MOCK_PERSONA_REJECT_ONCE", "g1")
        m = Mission.new(intent="x", context_digest="", tasks=[_task("g1")])
        run_mission(self._cfg(cfg), m, RunStore(cfg["runs_dir"], m.id))
        t = m.tasks[0]
        assert t.status == "done"
        assert t.attempts == 2                    # 差し戻しで1回増える
        events = [e for e in read_ledger(cfg["runs_dir"], m.id)
                  if e["event"] == "task.persona_review"]
        assert any(not e["passed"] for e in events)
        assert events[-1]["passed"]

    def test_persona_always_fail_exhausts_attempts(self, cfg, mock_state_dir,
                                                   monkeypatch):
        monkeypatch.setenv("MOCK_PERSONA_ALWAYS_FAIL", "g2")
        m = Mission.new(intent="x", context_digest="", tasks=[_task("g2")])
        run_mission(self._cfg(cfg), m, RunStore(cfg["runs_dir"], m.id))
        assert m.tasks[0].status == "failed"
        assert "ペルソナ" in m.tasks[0].review_notes

    def test_no_evidence_pass_retries_then_fails_keeping_output(
            self, cfg, mock_state_dir, monkeypatch):
        """証拠なし合格はロールリトライ→枯渇でfailed。worker成果は保持。"""
        monkeypatch.setenv("MOCK_PERSONA_NO_EVIDENCE", "g3")
        m = Mission.new(intent="x", context_digest="", tasks=[_task("g3")])
        run_mission(self._cfg(cfg), m, RunStore(cfg["runs_dir"], m.id))
        t = m.tasks[0]
        assert t.status == "failed"
        assert t.last_output           # 成果は捨てられていない
        retries = [e for e in read_ledger(cfg["runs_dir"], m.id)
                   if e["event"] == "role.retry"
                   and e["role"] == "persona_consumer"]
        assert len(retries) == 2

    def test_disabled_personas_no_calls(self, cfg, mock_state_dir):
        """personas未設定なら従来動作(ペルソナ呼び出しゼロ)。"""
        m = Mission.new(intent="x", context_digest="", tasks=[_task("g4")])
        run_mission(cfg, m, RunStore(cfg["runs_dir"], m.id))
        assert m.tasks[0].status == "done"
        personas = [c for c in read_calls(mock_state_dir)
                    if c["role"] == "persona"]
        assert personas == []
```

(import は既存の `from .conftest import read_calls, read_ledger` を利用。tests/test_review_retry.py と同型)

- [ ] **Step 2: 落ちることを確認** — Run: `pytest tests/test_personas.py::TestPersonaGateST -v` / Expected: FAIL(persona呼び出しが起きずdone/イベント欠落)

- [ ] **Step 3: 実装**

orchestrator.py — `_review_with_retry` を汎用化(既存の呼び出し・例外系・キャンセル系の挙動は変えない):

```python
def _role_call_with_retry(cfg: dict, store: RunStore, t: Task, role: str,
                          fn, retries: int = 2, wait: float = 60):
    """ロール呼び出し(reviewer/persona)の失敗はロールのみリトライする。
    worker実行はやり直さない(成果とコストを捨てない)。"""
    last: Exception | None = None
    for i in range(retries + 1):
        if _cancel_flag(store).exists():
            raise _CancelledDuringRole(f"cancelled before/during {role}")
        try:
            return fn()
        except Exception as e:
            if _cancel_flag(store).exists():
                raise _CancelledDuringRole(f"{role} terminated by cancel") from e
            last = e
            if i < retries:
                store.log("role.retry", role=role, task=t.id,
                          retry=i + 1, error=repr(e)[:300])
                if _cancellable_sleep(store, wait):
                    raise _CancelledDuringRole("cancelled during retry wait") from e
    raise last  # type: ignore[misc]


def _review_with_retry(cfg, store, t, budget, retries=2, wait=60):
    return _role_call_with_retry(
        cfg, store, t, "reviewer",
        lambda: review(cfg, t, workdir=t.workdir, budget=budget,
                       registry_key=store.dir.name),
        retries=retries, wait=wait)
```

`_attempt_loop` の合格分岐: 現在の `store.log("task.review", ...)` (262行目)と `if passed:` の間にペルソナゲートを挿入する。

```python
        store.log("task.review", task=t.id, passed=passed)
        if passed and t.personas:
            for persona in t.personas:
                try:
                    p_ok, p_fb = _role_call_with_retry(
                        cfg, store, t, f"persona_{persona}",
                        lambda p=persona: persona_review(
                            cfg, p, t, workdir=t.workdir, budget=budget,
                            registry_key=store.dir.name),
                        wait=infra_wait)
                except _CancelledDuringRole:
                    raise
                except Exception as e:
                    # 証拠なし合格の連発等。reviewer枯渇と同様に成果は保持してfailed
                    with store.lock:
                        t.status = "failed"
                        t.review_notes = (f"ペルソナ検収({persona})の呼び出しが失敗"
                                          f"(リトライ上限超過)。worker成果は保持済み: "
                                          f"{e!s:.300}")
                    store.log("task.persona_exhausted", task=t.id,
                              persona=persona, error=repr(e)[:500])
                    return t
                store.log("task.persona_review", task=t.id, persona=persona,
                          passed=p_ok)
                if not p_ok:
                    passed = False
                    feedback = f"[{persona}ペルソナ検収] {p_fb}"
                    with store.lock:
                        t.review_notes = feedback   # attempts枯渇時に原因が残るように
                    break
        if passed:
            ...  # 既存のcommit/done処理(変更しない)
```

`from .planner import persona_review` を orchestrator.py のimport群に追加。
ペルソナ由来のfeedbackはプレフィックス付きのため `feedback.startswith("REPLAN:")` に該当せず、既存の差し戻しループへ自然に流れる(設計どおり)。

- [ ] **Step 4: 合格確認** — Run: `pytest tests/test_personas.py -v` / Expected: PASS
- [ ] **Step 5: 全体回帰** — Run: `pytest -q` / Expected: 全緑(既存190+新規が全てPASS)
- [ ] **Step 6: Commit** — `git commit -am "feat(personas): 検収ゲートのorchestrator統合 — reviewer合格後のペルソナ直列裁定と差し戻し"`

---

### Task 8: 設定例・ドキュメント整備

**Files:**
- Modify: `config.example.yaml`(criteria_dir・personas・rolesのペルソナ/蒸留設定の記載)
- Modify: `HANDOFF.md`(冒頭に新セクション: 今回の実装と運用手順)
- Modify: `README.md`(「使い方」に verdict/criteria の2コマンド追記)

**Interfaces:**
- Consumes: Task 1〜7 の全成果(名称・デフォルト値を正確に転記すること)

- [ ] **Step 1: config.example.yaml に追記**(`playbooks_dir` の下)

```yaml
criteria_dir: criteria       # オーナー判断基準台帳。Reviewer/ペルソナ検収に注入され、
                             # orgh verdict の裁定から下書きが自動生成される
                             # (本台帳への反映は orgh criteria approve のみ)

personas:                    # ペルソナ検収ゲート(戦略設計書 柱1)
  enabled: []                # 例: [consumer, designer]。空なら完全無効(従来動作)
  apply: final_task          # 依存されない最終タスクに適用(現状これのみ)

# roles にペルソナ・蒸留ロールを追加できる(未指定時のデフォルトは以下と同値)
#   persona_consumer: {model: sonnet, max_turns: 30, allowed_tools: "Read,Bash,Glob,Grep"}
#   persona_designer: {model: sonnet, max_turns: 30, allowed_tools: "Read,Bash,Glob,Grep"}
#   criteria_distill: {model: sonnet, max_turns: 5, allowed_tools: "Read"}
```

- [ ] **Step 2: README.md の「使い方」コマンド一覧に追記**

```bash
# ミッション完走後、オーナーとして検収裁定を記録(基準台帳の下書きが自動生成される)
orgh verdict <mission_id> --fail --reason "レバーが見えない。視覚検証されていない"

# 下書きの確認と承認/棄却(承認されたものだけが以後の全裁定に注入される)
orgh criteria list
orgh criteria approve <mission_id>-1
```

- [ ] **Step 3: HANDOFF.md 冒頭に新スプリントセクションを追記**(様式は既存の「2026-08-07〜08-10スプリント」に合わせ、実装内容・テスト件数・運用手順・戦略設計書と本計画へのリンクを記載)

- [ ] **Step 4: 動作確認** — Run: `pytest -q && orgh criteria list` / Expected: 全緑・台帳空表示で正常終了
- [ ] **Step 5: Commit** — `git add -A && git commit -m "docs: criteria/personasの設定例・使い方・HANDOFF更新"`

---

## スコープ外(このプランではやらない)

- 反論する組織(オーナー要望と基準の矛盾検出→実行前議論)— 柱2の完全版。基準台帳が数十件に育ってから
- 企画室(壁打ち→分解の上流ペルソナ)・セールス/マーケ/敵対ペルソナ
- `orgh report` へのオーナー一発合格率の組み込み(データ源 verdicts.jsonl は本プランで整う)
- GUI(デスクトップ)への verdict/criteria 画面の追加
- watchデーモン経由の検収通知(柱3は運用で先行)

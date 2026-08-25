"""Planner / Reviewer / Retro。
すべて claude -p (headless) を1発叩いてJSONを返させる薄いラッパ。
プロンプト本文は prompts/*.md に外出し(ユーザーが育てる部分)。
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from .adapters.base import get_adapter
from .criteria import criteria_context, criteria_ids
from .slots import acquire_slot
from .state import TERMINAL, Budget, Mission, Task, acceptance_lines

# retroのplaybook_name(LLM由来)は playbooks/<name>.md のファイル名に直挿し
# されるため、単一の安全なファイル名だけを許す(../prompts/reviewer 等で
# playbooks外へ追記し将来のプロンプトを永続汚染する経路を塞ぐ。criteria.pyの
# _SAFE_CATEGORY_RE と同方針)
_PLAYBOOK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _prompts_dir(cfg: dict) -> Path:
    # _prompts_read_dir はミッション実行中のスナップショット(runs/<id>/prompts)。
    # prompts_dir自体を差し替えると自己改変ガードの保護対象判定まで変わって
    # しまうため、読み取り先だけを別キーで上書きする
    override = cfg.get("_prompts_read_dir")
    if override:
        return Path(override)
    return Path(cfg.get("prompts_dir", "prompts")).expanduser()


def _playbooks_dir(cfg: dict) -> Path:
    return Path(cfg.get("playbooks_dir", "playbooks")).expanduser()


def _read_prompt(cfg: dict, name: str) -> str:
    fp = _prompts_dir(cfg) / name
    try:
        return fp.read_text()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"prompt template not found: {fp}. config の prompts_dir を確認せよ")


def _projects_context(cfg: dict) -> str:
    """プロジェクトマップ(対象リポの絶対パス⇔説明の対応表)をPlannerに注入する。

    ノートに対象リポのパスが書かれていないと Planner は workdir "." を出力し、
    orgh自身のリポで実行されてしまう(実運用7307189eで実証)。マップは
    ユーザーがvault側で育てる前提のためconfigのパス指定(projects_map)で受ける。
    """
    fp = cfg.get("projects_map")
    if not fp:
        return "(no project map)"
    p = Path(fp).expanduser()
    if not p.is_file():
        return "(no project map)"
    text = p.read_text().strip()
    return text or "(no project map)"


def role_with_default(cfg: dict, role: str, default: dict) -> dict:
    """rolesに未定義のロールへデフォルト設定を注入したcfgコピーを返す。
    binはreviewerロールを継承する(モック・カスタムバイナリ環境の互換)。"""
    roles = {**cfg.get("roles", {})}
    if role not in roles:
        base = {k: v for k, v in roles.get("reviewer", {}).items()
                if k == "bin"}
        roles[role] = {**base, **default}
    return {**cfg, "roles": roles}


def _ask_json(cfg: dict, role: str, prompt: str, workdir: str = ".",
              budget: Budget | None = None,
              registry_key: str | None = None,
              cost_sink: list | None = None) -> dict:
    # 役割呼び出し(planner/reviewer/retro/replan/persona等)は cwd に worker が
    # 書いた CLAUDE.md / .claude/settings.json があっても取り込まない。
    # setting-sources を user のみに絞ることで project/local ソース(=worktree内の
    # worker生成物)を無視し、検収役が"買収"される経路を塞ぐ。役割の指示は
    # prompts/ から来るため、ambient なプロジェクト設定に従う必要はない。
    role_cfg = {**cfg["roles"][role], "setting_sources": "user"}
    adapter = get_adapter("claude_code", {**cfg["workers"],
                          "claude_code": role_cfg})
    # LLMの長文JSON応答は確率的に壊れる(実測: mission 8bc7ce00 t3のreplanが
    # 約5KB応答の途中の書式エラーでJSONDecodeError → タスクfailed)。ロール
    # 呼び出し自体は成功しているためinfra retryでは救えない。ここで修正指示
    # 付きの再要求を最大2回行う。res.okの失敗は従来どおり即raise。
    ask = prompt
    last_err: Exception | None = None
    # JSON修復ループがcancel後に新しいsubprocessを起こさないためのフラグ。
    # procreg.terminateは1度きりのsweepなので、以降起動する子は掃除されず
    # cancel後も課金が続く。runs/<mission>/CANCEL の有無で毎回ガードする
    cancel_flag = None
    if registry_key:
        cancel_flag = (Path(cfg.get("runs_dir", "runs"))
                       / registry_key / "CANCEL")
    for _ in range(3):
        if cancel_flag is not None and cancel_flag.exists():
            raise RuntimeError(f"{role}: キャンセル済みのため実行を中止した")
        # registry_key(mission_id)を渡すとprocregへ登録され、orgh cancelの
        # terminate対象になる。ミッション実行中に走るrole(reviewer/replan)は
        # 登録しないとキャンセルが効かず、キャンセル後に成果が確定してしまう
        # ロールのグローバル枠(R-2、workersとは別pool)。枠待ち中のキャンセルは
        # SlotAbortedで抜け、呼び出し元のロールリトライがCANCELフラグを見て
        # CancelledDuringRoleへ変換する
        with acquire_slot(cfg.get("runs_dir", "runs"),
                          (cfg.get("loop") or {}).get("global_role_parallel"),
                          pool="roles",
                          should_abort=(cancel_flag.exists
                                        if cancel_flag is not None else None)):
            res = adapter.run(ask, workdir=workdir, registry_key=registry_key)
        # budget.chargeとcost_sinkへの計上は「if not res.ok: raise」より前に置く
        # (フォローアップ4a): 失敗したロール呼び出しでもLLM側は課金済みのため、
        # raiseを先にするとそのコストがどこにも計上されず消える。
        # Budget.charge は amount が None/0 でも安全(内部でif not amount: returnする)
        if budget is not None:
            budget.charge(res.cost_usd)
        if cost_sink is not None:
            cost_sink.append(res.cost_usd or 0.0)
        if not res.ok:
            # resultが空のことがある(max_turns超過等)。rawのsubtypeに理由が残る
            detail = res.output[:500] or res.raw[-500:]
            raise RuntimeError(f"{role} failed: {detail}")
        m = re.search(r"\{.*\}", res.output, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError as e:
                last_err = e
        else:
            last_err = ValueError(
                f"{role} returned no JSON:\n{res.output[:800]}")
        ask = (f"{prompt}\n\n【再要求】前回の応答はJSONとして解析できなかった"
               f"(エラー: {last_err})。前置き・説明文・コードフェンスを付けず、"
               "有効なJSONオブジェクト1個のみを出力すること。")
    raise last_err


# prompts/planner.mdが例示する2パターン両方を検出する(「予算上限: 15 USD」
# 「予算15ドルまで」)。デザイナー検収の指摘: 旧regexは「予算上限」の literal
# を必須にしており、prompt側が正当な表現として例示した「予算Nドルまで」
# (上限を含まない)を検出できず、その言い回しに限り安全網が機能しない
# 断線が残っていた。金額の単位($/USD/ドル/円)を要求することで、
# 「予算15%削減」のような無関係な数値混入を誤検知しない
_BUDGET_DECLARATION_RE = re.compile(
    r"予算(?:上限)?\s*[:：]?\s*(?:\$\s*\d+(?:\.\d+)?"
    r"|\d+(?:\.\d+)?\s*(?:USD|ドル|円))")

# config.model_allowlist未設定時の既定(config.example.yaml/orgh/state.pyの
# ConfigSchemaと同じ値を保つ)
DEFAULT_MODEL_ALLOWLIST = ["haiku", "sonnet", "opus"]


def lint_plan(data: dict, note_text: str | None = None,
             model_allowlist: list[str] | None = None) -> list[str]:
    """計画JSON(dict)をPythonコードのみで機械検査する(LLMに問い合わせない)。

    違反理由の日本語一文のリストを返す(違反なしなら空リスト)。

    規則1: visual_quality が真、かつ tasks の先頭要素の kind が "reference"
    でない場合に違反1件(DESIGN-005: 正解先行 — 実物を観察→正解仕様を文書化
    →そこからテストケースを導出)。tasks が空・型不正のときは違反を返さない
    (既存の失敗経路に委ねる)。

    規則2: note_text(ノート原文=intent/context_digest相当のテキスト)に
    「予算上限: N USD」等の予算宣言があるのに、計画の budget_usd が null の
    場合に違反1件(実測: mission 620402d6でPlannerが予算宣言を計画に載せず
    実行時の上限が効かなかった二重断線の1つ目)。note_text 省略時(既定None)は
    このチェックをスキップする(後方互換: 呼び出し元がノート原文を渡さない
    限り挙動不変)。

    規則3: タスクに model が指定(非None・非空)されているのに model_reason
    が空/欠落なら違反1件(過剰なモデル使用を避けるための「逸脱には理由を
    残す」運用を機械強制する)。

    規則4: model が model_allowlist(既定 ["haiku", "sonnet", "opus"]。
    config.model_allowlistで上書き可能)に無い値なら違反1件。

    規則3/4とも、tasks が list でない/空、要素が dict でない場合は違反を
    返さず既存の失敗経路に委ねる(規則1と同じ流儀)。
    """
    if model_allowlist is None:
        model_allowlist = DEFAULT_MODEL_ALLOWLIST
    violations: list[str] = []
    tasks = data.get("tasks")
    if isinstance(tasks, list) and tasks:
        for t in tasks:
            if not isinstance(t, dict):
                continue
            model = t.get("model")
            if not model:
                continue
            if not t.get("model_reason"):
                violations.append(
                    f"タスク{t.get('id', '?')!r}: modelが指定されている"
                    f"({model!r})のにmodel_reasonが空/欠落している。モデル"
                    "選択の逸脱には理由を残す運用に反する。model_reasonへ"
                    "選択理由を1行で書いて再設計せよ"
                )
            if model not in model_allowlist:
                violations.append(
                    f"タスク{t.get('id', '?')!r}: model={model!r}が許可リスト"
                    f"{model_allowlist!r}に無い。許可リスト内のモデルへ"
                    "変更して再設計せよ"
                )
    if (data.get("visual_quality") and isinstance(tasks, list) and tasks):
        first = tasks[0]
        if not (isinstance(first, dict) and first.get("kind") == "reference"):
            violations.append(
                "visual_quality=trueだが先頭タスクがkind=\"reference\"(参照="
                "正解仕様の作成タスク)になっていない。DESIGN-005(正解先行: "
                "実物を観察→正解仕様を文書化→そこからテストケースを導出)に"
                "従い、先頭に参照作成タスクを置いて再設計せよ"
            )
    if (note_text and _BUDGET_DECLARATION_RE.search(note_text)
            and data.get("budget_usd") is None):
        violations.append(
            "ノート本文に予算宣言(例: 「予算上限: N USD」)があるが計画の"
            "budget_usdがnull(見積もり超過を防ぐ上限が実行時に反映されない)。"
            "ノート本文の予算宣言を読み取りbudget_usdへ設定して再設計せよ"
        )
    return violations


def plan(cfg: dict, intent: str, context_digest: str,
        budget: Budget | None = None) -> Mission:
    if budget is None:
        lcfg = cfg.get("loop", {})
        budget = Budget(limit_usd=lcfg.get("budget_usd"),
                        task_budget_usd=lcfg.get("task_budget_usd"),
                        source="config")
    tmpl = _read_prompt(cfg, "planner.md")
    prompt = tmpl.format(intent=intent, context=context_digest,
                         projects=_projects_context(cfg),
                         workers=", ".join(cfg["workers"]["enabled"]))
    note_text = f"{intent}\n{context_digest}"
    model_allowlist = cfg.get("model_allowlist") or DEFAULT_MODEL_ALLOWLIST
    data = _ask_json(cfg, "planner", prompt, budget=budget)
    violations = lint_plan(data, note_text=note_text,
                           model_allowlist=model_allowlist)
    if violations:
        print("orgh: plan lint違反を検出、再計画を1回要求する: "
              + "; ".join(violations))
        retry_prompt = (
            f"{prompt}\n\n【再計画要求】前回の計画はplan lintで以下の理由により"
            "差し戻された:\n"
            + "\n".join(f"- {v}" for v in violations)
            + "\n上記を満たすようタスクDAGを再設計し、説明文・コードフェンスを"
              "付けずJSONオブジェクト1個のみを出力すること。")
        data = _ask_json(cfg, "planner", retry_prompt, budget=budget)
        violations = lint_plan(data, note_text=note_text,
                               model_allowlist=model_allowlist)
        if violations:
            print("orgh: 再計画の応答も plan lint に違反した。人間エスカレー"
                  "ションへ引き継ぐ: " + "; ".join(violations))
    # ノートの予算宣言(Planner接続): 数値のbudget_usdがあればミッション予算の
    # 上限へ反映する(実行時のsetup_budgetがconfig既定より優先させる)
    declared_budget = data.get("budget_usd")
    if (isinstance(declared_budget, (int, float))
            and not isinstance(declared_budget, bool) and declared_budget > 0):
        budget.limit_usd = float(declared_budget)
        budget.source = "note"
    mission = Mission.new(intent=intent, context_digest=context_digest,
                          tasks=data["tasks"],
                          visual_quality=bool(data.get("visual_quality", False)),
                          decision_gates=data.get("decision_gates"))
    mission.plan_lint_violations = violations
    mission.budget = budget
    return mission


def build_review_prompt(cfg: dict, task: Task,
                        workdir: str | Path | None = None) -> str:
    """プロンプトテンプレートへ判断基準を注入してReviewerプロンプトを構築する。"""
    tmpl = _read_prompt(cfg, "reviewer.md")
    return tmpl.format(title=task.title, prompt=task.prompt,
                       acceptance=acceptance_lines(task),
                       output=task.last_output[:12000],
                       criteria=criteria_context(cfg, workdir=workdir))


_AC_VERDICT_VALUES = frozenset({"pass", "fail", "not_applicable"})


def _sanitize_ac_verdicts(raw: Any, task: Task) -> tuple[list[dict], int]:
    """ReviewerがLLM由来で返す ac_verdicts を検証・矯正する(信用しない)。

    - リストでなければ何も無かったものとして扱う(([], 0))
    - 各要素はdictで id/verdict/reason を持つこと。id はtask.acceptanceに
      実在するACのidであること。verdictはpass|fail|not_applicableのみ。
      reasonは空でない文字列であること。1つでも欠ければその要素を落とす
    - 例外は投げない。戻り値は (サニタイズ済み配列, 落とした要素数)
    """
    if not isinstance(raw, list):
        return [], 0
    valid_ids = {ac["id"] for ac in task.acceptance
                if isinstance(ac, dict) and isinstance(ac.get("id"), str)}
    out: list[dict] = []
    dropped = 0
    for item in raw:
        if not isinstance(item, dict):
            dropped += 1
            continue
        ac_id = item.get("id")
        verdict = item.get("verdict")
        reason = item.get("reason")
        if (not isinstance(ac_id, str) or ac_id not in valid_ids
                or verdict not in _AC_VERDICT_VALUES
                or not isinstance(reason, str) or not reason.strip()):
            dropped += 1
            continue
        out.append({"id": ac_id, "verdict": verdict, "reason": reason[:500]})
    return out, dropped


def _sanitize_criteria_cited(raw: Any, valid_ids: set[str]) -> list[str]:
    """裁定応答の criteria_cited(実際に参照した基準IDの配列)を検証する
    (信用しない)。そのタスクの裁定プロンプトに実際に注入された基準ID
    (valid_ids)に含まれないID(捏造)は黙って捨て、有効なIDだけを残す。
    キー欠落・型不正(配列でない)は例外にせず空配列として扱う。
    """
    if not isinstance(raw, list):
        return []
    return [cid for cid in raw if isinstance(cid, str) and cid in valid_ids]


def review(cfg: dict, task: Task, workdir: str,
          budget: Budget | None = None,
          registry_key: str | None = None,
          cost_sink: list | None = None
          ) -> tuple[bool, str, list[dict], int, list[str]]:
    data = _ask_json(cfg, "reviewer",
                     build_review_prompt(cfg, task, workdir=workdir),
                     workdir=workdir, budget=budget, registry_key=registry_key,
                     cost_sink=cost_sink)
    ac_verdicts, ac_verdicts_dropped = _sanitize_ac_verdicts(
        data.get("ac_verdicts"), task)
    criteria_cited = _sanitize_criteria_cited(
        data.get("criteria_cited"), criteria_ids(cfg, workdir=workdir))
    return (bool(data.get("pass")), data.get("feedback", ""),
           ac_verdicts, ac_verdicts_dropped, criteria_cited)


_PERSONA_ROLE_DEFAULT = {"model": "sonnet", "max_turns": 30,
                         "allowed_tools": "Read,Bash,Glob,Grep"}


def persona_review(cfg: dict, persona: str, task: Task, workdir: str,
                   budget: Budget | None = None,
                   registry_key: str | None = None,
                   cost_sink: list | None = None,
                   criteria_cited_sink: list | None = None
                   ) -> tuple[bool, str, list[str]]:
    """ペルソナ検収(戦略設計書 柱1)。証拠なしの合格裁定はValueErrorで無効化する
    (同じLLMが自分に頷くだけのハンコ裁定の禁止)。呼び出し側のロールリトライで
    再裁定され、リトライ枯渇時はworker成果を保持したままfailedになる。

    戻り値は (pass, feedback, evidence) の3要素。evidenceは呼び出し側が
    ledger(task.persona_review)に記録し、ゲートの監査可能性を担保する
    (フォローアップ2: これまでは検証にしか使わずledgerへ残していなかった)。

    criteria_cited(実際に参照した基準ID)は戻り値のタプルに足さず
    criteria_cited_sink(cost_sinkと同型の出力先リスト)へ積む: 既存の
    3要素タプル前提の呼び出し元(直接呼ぶ既存テスト含む)を壊さないため。
    """
    role = f"persona_{persona}"
    cfg = role_with_default(cfg, role, _PERSONA_ROLE_DEFAULT)
    tmpl = _read_prompt(cfg, f"{role}.md")
    prompt = tmpl.format(title=task.title, prompt=task.prompt,
                         acceptance=acceptance_lines(task),
                         output=task.last_output[:12000],
                         criteria=criteria_context(cfg, workdir=workdir))
    data = _ask_json(cfg, role, prompt, workdir=workdir, budget=budget,
                     registry_key=registry_key, cost_sink=cost_sink)
    evidence = data.get("evidence") or []
    if data.get("pass") and not evidence:
        raise ValueError(
            f"persona {persona} が証拠なしで合格裁定を返した(証拠チャネル原則違反)")
    if criteria_cited_sink is not None:
        criteria_cited_sink.extend(_sanitize_criteria_cited(
            data.get("criteria_cited"), criteria_ids(cfg, workdir=workdir)))
    return bool(data.get("pass")), data.get("feedback", ""), evidence


def retro(cfg: dict, mission: Mission) -> str:
    """完了ミッションから学びを抽出して playbooks/ に追記 → 次回以降の全員が賢くなる。"""
    tmpl = _read_prompt(cfg, "retro.md")
    summary = "\n".join(
        f"- [{t.status}] {t.title} (attempts={t.attempts}) "
        f"review: {t.review_notes[:200]}"
        for t in mission.tasks
    )
    prompt = tmpl.format(intent=mission.intent, summary=summary)
    data = _ask_json(cfg, "retro", prompt, budget=mission.budget)
    name = data.get("playbook_name", "general")
    if not isinstance(name, str) or not _PLAYBOOK_NAME_RE.match(name):
        # 不正名はretroの学びを捨てず既定ファイルへ寄せる(汚染は防ぎつつ教訓は残す)
        print(f"orgh: 不正なplaybook_name {name!r} を general に矯正した")
        name = "general"
    body = data.get("lessons", "")
    if body:
        pdir = _playbooks_dir(cfg).resolve()
        pdir.mkdir(parents=True, exist_ok=True)
        fp = (pdir / f"{name}.md").resolve()
        if not fp.is_relative_to(pdir):  # 多層防御(正規表現を素通りしても)
            raise ValueError(f"playbook書き込み先がplaybooks/外: {name!r}")
        today = date.today().isoformat()
        tagged = [
            f"{line} <!-- m:{mission.id} d:{today} -->"
            if line.startswith("-") else line
            for line in body.split("\n")
        ]
        with open(fp, "a") as f:
            f.write("\n".join(tagged) + "\n")
        return str(fp)
    return ""


def retro_if_finished(cfg: dict, mission: Mission, store,
                      only_if_all_done: bool = False) -> str | None:
    """ミッションが決着した場合のみretroを実行する共通ゲート(run/approve/resume/watch)。

    awaiting_approvalを残したままretroすると、未完了内容から教訓が保存され
    RETRO_DONEマーカーで承認後の真の結果が反映されなくなる(Codexレビューr2指摘)。
    失敗・キャンセルで決着したミッションは従来どおり教訓化の対象(失敗の資産化)。

    only_if_all_done=True は resume 経路用: resumeは失敗タスクの再試行経路なので、
    失敗のまま終わった時点でretroしてしまうと、後に再resumeで完走したときの
    真の教訓がRETRO_DONEに阻まれる(test_st_scenariosで固定済みの仕様)。
    """
    terminal = ("done",) if only_if_all_done else TERMINAL
    marker = store.dir / "RETRO_DONE"
    if marker.exists() or not mission.tasks or \
            not all(t.status in terminal for t in mission.tasks):
        return None
    # retroもミッションのprompts/スナップショットを読む(実行本体と同じ契約で
    # 動かす。ライブ版を読むと長時間ミッション後のretroだけ版ずれしうる)
    snap = store.dir / "prompts"
    if snap.is_dir():
        cfg = {**cfg, "_prompts_read_dir": str(snap)}
    print("== retro ==")
    fp = retro(cfg, mission)
    store.save(mission)
    marker.touch()
    print(f"playbook updated: {fp or '(no lessons)'}")
    try:
        from .criteria_feedback import distill_mission_feedback
        workdir = next(
            (t.workdir for t in mission.tasks if t.workdir), None)
        drafts = distill_mission_feedback(
            cfg, mission.id, mission.intent, workdir=workdir)
        print(f"criteria drafts distilled: {len(drafts)}")
    except Exception as e:
        print(f"orgh: criteria feedback蒸留に失敗した(best-effort、無視): {e}")
    return fp


def replan_task(cfg: dict, task: Task, reason: str,
                budget: Budget | None = None,
                registry_key: str | None = None) -> dict:
    """REPLANエスカレーション: 計画の欠陥が指摘されたタスクの指示と受け入れ条件を
    Plannerに再設計させる(HANDOFF タスク5)。"""
    tmpl = _read_prompt(cfg, "replan.md")
    prompt = tmpl.format(title=task.title, prompt=task.prompt,
                         acceptance=acceptance_lines(task),
                         reason=reason)
    return _ask_json(cfg, "planner", prompt, budget=budget,
                     registry_key=registry_key)


def _elide(text: str, limit: int) -> str:
    """limit文字を超える一文を末尾省略する。素朴な文字数カットだと英数字の
    単語途中で切れて可読性が落ちる(例: "headlessな" → "head…")ため、
    切れ目が英数字列の途中に来た場合はその単語ごと落とす。"""
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    m = re.search(r"[A-Za-z0-9]+$", cut)
    if m and m.start() > 0:
        cut = cut[:m.start()]
    return cut.rstrip() + "…"


def build_human_request(mission_id: str, task: Task, reason: str) -> tuple[str, str]:
    """人間依頼書を組み立てる(awaiting_human基盤)。

    オーナー裁定 PROD-001 準拠: 1行目に端的な依頼一文を置き、詳細はその後に
    見出し付きで展開する(判断材料を探させない)。戻り値は
    (依頼一文, 依頼書本文の全文)。worker: "human" のdispatch時と、
    実行中のHUMAN:転換の両方から呼ばれる(reasonの由来だけが異なる)。
    """
    reason_flat = " ".join(reason.split())
    brief = _elide(f"「{task.title}」の完了に人間の対応が必要: {reason_flat}", 100)
    acceptance = acceptance_lines(task) or "- (未指定)"
    body = (
        f"{brief}\n\n"
        f"## 何をするか\n{task.prompt}\n\n"
        f"## なぜ人間が必要か\n{reason}\n\n"
        f"## 完了時に提出する証拠\n{acceptance}\n\n"
        f"## 完了報告\n"
        f"作業が完了したら以下を実行して orgh に完了を伝えること:\n"
        f"```\norgh humandone {mission_id} {task.id} --note \"実施内容の要約\"\n```\n"
    )
    return brief, body


def worker_prompt(cfg: dict, task: Task) -> str:
    tmpl = _read_prompt(cfg, "worker_preamble.md")
    prompt = tmpl.format(title=task.title, prompt=task.prompt,
                        acceptance=acceptance_lines(task))
    if task.decision_context:
        # 承認時にオーナーが確定させたdecision_gates回答(orgh approve --answer)。
        # workerが同じ問いを人間へ再度返すのを防ぐため、決定済みである旨を明示する
        prompt += (
            "\n\n## オーナーが確定済みの決定事項\n"
            f"{task.decision_context}\n\n"
            "これらは決定済みであり、workerはこの件について人間へ確認を返しては"
            "ならない。"
        )
    return prompt

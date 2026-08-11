"""Planner / Reviewer / Retro。
すべて claude -p (headless) を1発叩いてJSONを返させる薄いラッパ。
プロンプト本文は prompts/*.md に外出し(ユーザーが育てる部分)。
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from .adapters.base import get_adapter
from .criteria import criteria_context
from .state import Budget, Mission, Task

_META_RE = re.compile(r"<!-- m:(\S+) d:(\d{4}-\d{2}-\d{2}) -->")


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


def _playbook_context(cfg: dict, max_chars: int = 8000) -> str:
    """過去のRetroで蒸留された組織知をPlanner/Workerに注入する(増幅の核)。

    capは「先頭から切り捨て」ではなく「日付降順で詰める」: 全playbookの全行を
    メタデータ日付でソートし、新しい教訓から順にmax_charsへ詰める。こうすると
    playbookが育つほど古い教訓から溢れ、常に最新の教訓が注入に生き残る。
    """
    playbooks_dir = _playbooks_dir(cfg)
    if not playbooks_dir.is_dir():
        return "(no playbooks yet)"
    entries: list[tuple[str, str]] = []  # (date, line) メタデータ無しは最古扱い
    for p in sorted(playbooks_dir.glob("*.md")):
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            m = _META_RE.search(line)
            entries.append((m.group(2) if m else "0000-00-00", line))
    entries.sort(key=lambda e: e[0], reverse=True)

    picked: list[str] = []
    total = 0
    for _, line in entries:
        total += len(line) + 1  # 結合時の改行分
        if total > max_chars and picked:
            break
        picked.append(line)
    return "\n".join(picked) if picked else "(no playbooks yet)"


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
    adapter = get_adapter("claude_code", {**cfg["workers"],
                          "claude_code": cfg["roles"][role]})
    # registry_key(mission_id)を渡すとprocregへ登録され、orgh cancelの
    # terminate対象になる。ミッション実行中に走るrole(reviewer/replan)は
    # 登録しないとキャンセルが効かず、キャンセル後に成果が確定してしまう
    res = adapter.run(prompt, workdir=workdir, registry_key=registry_key)
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
    if not m:
        raise ValueError(f"{role} returned no JSON:\n{res.output[:800]}")
    return json.loads(m.group(0))


def plan(cfg: dict, intent: str, context_digest: str,
        budget: Budget | None = None) -> Mission:
    if budget is None:
        lcfg = cfg.get("loop", {})
        budget = Budget(limit_usd=lcfg.get("budget_usd"),
                        task_budget_usd=lcfg.get("task_budget_usd"))
    tmpl = _read_prompt(cfg, "planner.md")
    prompt = tmpl.format(intent=intent, context=context_digest,
                         playbooks=_playbook_context(cfg),
                         projects=_projects_context(cfg),
                         workers=", ".join(cfg["workers"]["enabled"]))
    data = _ask_json(cfg, "planner", prompt, budget=budget)
    mission = Mission.new(intent=intent, context_digest=context_digest,
                          tasks=data["tasks"])
    mission.budget = budget
    return mission


def build_review_prompt(cfg: dict, task: Task) -> str:
    """プロンプトテンプレートへ判断基準を注入してReviewerプロンプトを構築する。"""
    tmpl = _read_prompt(cfg, "reviewer.md")
    return tmpl.format(title=task.title, prompt=task.prompt,
                       acceptance="\n".join(f"- {a}" for a in task.acceptance),
                       output=task.last_output[:12000],
                       criteria=criteria_context(cfg))


def review(cfg: dict, task: Task, workdir: str,
          budget: Budget | None = None,
          registry_key: str | None = None,
          cost_sink: list | None = None) -> tuple[bool, str]:
    data = _ask_json(cfg, "reviewer", build_review_prompt(cfg, task),
                     workdir=workdir, budget=budget, registry_key=registry_key,
                     cost_sink=cost_sink)
    return bool(data.get("pass")), data.get("feedback", "")


_PERSONA_ROLE_DEFAULT = {"model": "sonnet", "max_turns": 30,
                         "allowed_tools": "Read,Bash,Glob,Grep"}


def persona_review(cfg: dict, persona: str, task: Task, workdir: str,
                   budget: Budget | None = None,
                   registry_key: str | None = None,
                   cost_sink: list | None = None) -> tuple[bool, str, list[str]]:
    """ペルソナ検収(戦略設計書 柱1)。証拠なしの合格裁定はValueErrorで無効化する
    (同じLLMが自分に頷くだけのハンコ裁定の禁止)。呼び出し側のロールリトライで
    再裁定され、リトライ枯渇時はworker成果を保持したままfailedになる。

    戻り値は (pass, feedback, evidence) の3要素。evidenceは呼び出し側が
    ledger(task.persona_review)に記録し、ゲートの監査可能性を担保する
    (フォローアップ2: これまでは検証にしか使わずledgerへ残していなかった)。
    """
    role = f"persona_{persona}"
    cfg = role_with_default(cfg, role, _PERSONA_ROLE_DEFAULT)
    tmpl = _read_prompt(cfg, f"{role}.md")
    prompt = tmpl.format(title=task.title, prompt=task.prompt,
                         acceptance="\n".join(f"- {a}" for a in task.acceptance),
                         output=task.last_output[:12000],
                         criteria=criteria_context(cfg))
    data = _ask_json(cfg, role, prompt, workdir=workdir, budget=budget,
                     registry_key=registry_key, cost_sink=cost_sink)
    evidence = data.get("evidence") or []
    if data.get("pass") and not evidence:
        raise ValueError(
            f"persona {persona} が証拠なしで合格裁定を返した(証拠チャネル原則違反)")
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
    body = data.get("lessons", "")
    if body:
        _playbooks_dir(cfg).mkdir(parents=True, exist_ok=True)
        fp = _playbooks_dir(cfg) / f"{name}.md"
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
    terminal = ("done",) if only_if_all_done else (
        "done", "failed", "cancelled", "skipped")
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
    return fp


def replan_task(cfg: dict, task: Task, reason: str,
                budget: Budget | None = None,
                registry_key: str | None = None) -> dict:
    """REPLANエスカレーション: 計画の欠陥が指摘されたタスクの指示と受け入れ条件を
    Plannerに再設計させる(HANDOFF タスク5)。"""
    tmpl = _read_prompt(cfg, "replan.md")
    prompt = tmpl.format(title=task.title, prompt=task.prompt,
                         acceptance="\n".join(f"- {a}" for a in task.acceptance),
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
    acceptance = "\n".join(f"- {a}" for a in task.acceptance) or "- (未指定)"
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
    return tmpl.format(title=task.title, prompt=task.prompt,
                       acceptance="\n".join(f"- {a}" for a in task.acceptance),
                       playbooks=_playbook_context(cfg, 4000))

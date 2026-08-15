"""Run state & ledger. Everything the org knows lives on disk, restartable.

- config: 起動時にdataclassスキーマで検証(未知キー警告・必須キー欠落エラー)
- mission.json: tmp書き込み→os.replace のアトミック永続化
- ledger追記とmission状態の変更は RunStore.lock(単一ロック)で保護
- ロード時に実行中系ステータス(running/queued/review)をpendingへ巻き戻す
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
import warnings
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

from . import lease


class ConfigError(ValueError):
    """必須キー欠落・型不一致など、続行不能なconfig欠陥。"""


class ConfigWarning(UserWarning):
    """未知キーなど、無視して続行できるconfigの疑義。"""


# ---------------------------------------------------------------- config schema
@dataclass
class VaultCfg:
    path: str = ""
    inbox: str = "inbox"
    mission_tag: str = "mission"
    trigger_tag: str = "go"


@dataclass
class LoopCfg:
    parallel: int = 3
    max_attempts: int = 3
    task_timeout: int = 3600
    budget_usd: float | None = None       # ルートミッション全体の上限(null=無制限)
    task_budget_usd: float | None = None  # 1タスク上限(null=無制限)。
    # worker+レビュー/ペルソナのロールコストを含むタスク総コスト(失敗呼び出し
    # 含む)が対象(フォローアップ4で変更。旧: worker実行コストのみが対象で
    # ロールコストはミッション予算にのみ計上されていた)
    infra_max_retries: int = 3            # ネットワーク等インフラエラーのattempt非消費リトライ上限
    infra_retry_wait: float = 60          # 同リトライ前の待機秒
    global_parallel: int | None = None    # 全orghプロセス横断のworker同時数上限(null=無効)。
    # runs/_slots/ のflockセマフォで強制(R-2)。loop.parallelは1ミッション内の枠、
    # こちらはプロセスをまたいだ総枠
    global_role_parallel: int | None = None  # 同、ロール(planner/reviewer/persona等)の別枠(null=無効)


@dataclass
class WatchCfg:
    interval: float = 5
    stabilize_seconds: float = 20
    writeback: bool = True
    gc_interval_days: float | None = 14   # この日数ごとに自動でorgh gc相当を実行(null=無効)
    queue_limit: int = 20                 # runs/_queue/ の有界上限(満杯時は着火見送り・次パス再試行)
    parallel_missions: int = 1            # executorの同時ミッション消化数(R-1)。
    # 既定1=旧watchの直列実行と同一挙動(並列消化はopt-in)


@dataclass
class WorktreeCfg:
    enabled: bool = False
    base_ref: str = "HEAD"
    root: str = ".orgh-worktrees"


@dataclass
class SourceCfg:
    """入力ソースの選択(HANDOFF タスク3)。将来Notion等を差し替え可能にする拡張点。"""
    type: str = "obsidian"


@dataclass
class GcCfg:
    """orgh gc(playbookの代謝とruns保持)の設定(HANDOFF タスク6)。"""
    retention_days: int = 90   # これより古いミッションはruns/_archive/へ退避


@dataclass
class PersonasCfg:
    """ペルソナ検収ゲート(消費者・デザイナー等)。enabledが空なら完全無効。"""
    enabled: list[str] = field(default_factory=list)
    apply: str = "final_task"    # 現状はfinal_taskのみ(依存されないタスクに適用)


@dataclass
class NotifyCfg:
    """人間接点イベント通知(A1out)。既定は無効(webhook_url=null=挙動不変)。
    配送保証(再送・順序・署名)は持たない(方向性文書2026-08 §3.1 A1out)。"""
    webhook_url: str | None = None   # POST先。null=webhook無効(ledgerのnotify.emittedのみ記録)
    timeout: float = 5.0             # POSTのタイムアウト秒


@dataclass
class ConfigSchema:
    """既知のトップレベルキー。workers/rolesは名前が自由なため深掘りしない。"""
    workers: dict | None = None          # 必須
    roles: dict | None = None
    vault: VaultCfg | None = None
    loop: LoopCfg | None = None
    watch: WatchCfg | None = None
    worktree: WorktreeCfg | None = None
    source: SourceCfg | None = None
    gc: GcCfg | None = None
    personas: PersonasCfg | None = None
    notify: NotifyCfg | None = None
    runs_dir: str = "runs"
    prompts_dir: str = "prompts"
    criteria_dir: str = "criteria"
    playbooks_dir: str = "playbooks"
    projects_map: str | None = None      # 対象リポの絶対パス⇔説明の対応表(Planner注入)


_REQUIRED_KEYS = ("workers",)
_SECTION_SCHEMAS = {"vault": VaultCfg, "loop": LoopCfg, "watch": WatchCfg,
                    "worktree": WorktreeCfg, "source": SourceCfg, "gc": GcCfg,
                    "personas": PersonasCfg, "notify": NotifyCfg}
# from __future__ import annotations により field.type は文字列
_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "int": int, "float": (int, float), "str": str, "bool": bool,
    "float | None": (int, float),
    "int | None": int,
    "str | None": str,
    "list[str]": list,   # 要素型はisinstanceでは表現できないため_check_sectionで別途検査
}
_LIST_ELEM_TYPE_MAP: dict[str, type] = {
    "list[str]": str,
}


def _check_section(name: str, value: Any, schema_cls: type) -> None:
    if not isinstance(value, dict):
        raise ConfigError(f"config: {name} はマップで指定すること")
    known = {f.name: f for f in fields(schema_cls)}
    for k, v in value.items():
        if k not in known:
            warnings.warn(ConfigWarning(
                f"config: 未知のキー {name}.{k} を無視する"))
            continue
        expected = _TYPE_MAP.get(known[k].type)
        if expected and v is not None and not isinstance(v, expected):
            raise ConfigError(
                f"config: {name}.{k} の型が不正 "
                f"(期待 {known[k].type}, 実際 {type(v).__name__}: {v!r})")
        elem_type = _LIST_ELEM_TYPE_MAP.get(known[k].type)
        if elem_type and isinstance(v, list) and not all(
                isinstance(e, elem_type) for e in v):
            raise ConfigError(
                f"config: {name}.{k} の要素型が不正 "
                f"(期待 {known[k].type}, 実際 {v!r})")


def validate_config(data: Any) -> dict:
    if not isinstance(data, dict):
        raise ConfigError("config全体がマップになっていない")
    for k in _REQUIRED_KEYS:
        if k not in data:
            raise ConfigError(f"config: 必須キー {k} がない")

    top = {f.name: f for f in fields(ConfigSchema)}
    for k in data:
        if k not in top:
            warnings.warn(ConfigWarning(f"config: 未知のキー {k} を無視する"))
    for name, cls in _SECTION_SCHEMAS.items():
        if data.get(name) is not None:
            _check_section(name, data[name], cls)
    for name in ("workers", "roles"):
        if data.get(name) is not None and not isinstance(data[name], dict):
            raise ConfigError(f"config: {name} はマップで指定すること")
    for name in ("runs_dir", "prompts_dir", "playbooks_dir", "projects_map"):
        if data.get(name) is not None and not isinstance(data[name], str):
            raise ConfigError(f"config: {name} は文字列で指定すること")
    return data


def load_config(path: str | Path = "config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found. copy config.example.yaml -> config.yaml")
    return validate_config(yaml.safe_load(p.read_text()) or {})


# ------------------------------------------------------------------- run state
@dataclass
class Budget:
    """予算の共有プール(HANDOFF タスク2)。

    再帰(タスクのサブミッション分解)前提の設計: 上限をミッション単位の固定値に
    すると子ミッションごとの上限が掛け算になって破綻するため、ルートで確保した
    プールを split() で親から子へ分割し、参照渡しする。子の charge() は親へ
    伝播し、親プールの枯渇は子の exceeded() にも波及する。

    永続化されるのは limit/task_limit/spent のみ(親リンクは実行時の参照)。
    """
    limit_usd: float | None = None       # このプール(割当)の上限。None=無制限
    task_budget_usd: float | None = None  # 1タスクあたりの上限
    spent_usd: float = 0.0

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._parent: "Budget | None" = None

    def charge(self, amount: float | None) -> None:
        if not amount:
            return
        with self._lock:
            self.spent_usd += amount
        if self._parent is not None:
            self._parent.charge(amount)

    def exceeded(self) -> bool:
        if self.limit_usd is not None and self.spent_usd >= self.limit_usd:
            return True
        return self._parent.exceeded() if self._parent is not None else False

    def remaining(self) -> float | None:
        if self.limit_usd is None:
            return None
        return max(0.0, self.limit_usd - self.spent_usd)

    def split(self, limit_usd: float | None = None) -> "Budget":
        """子ミッションへの割当を切り出す(プール自体は共有のまま)。"""
        child = Budget(
            limit_usd=self.remaining() if limit_usd is None else limit_usd,
            task_budget_usd=self.task_budget_usd)
        child._parent = self
        return child


# 終端ステータスの正準定義(これ以外は実行中系としてresume時にpendingへ
# 巻き戻される)。scheduler / cli / listing / status_json / planner が共有する
TERMINAL = ("done", "failed", "cancelled", "skipped")


@dataclass
class Task:
    id: str
    title: str
    prompt: str
    worker: str = "claude_code"          # adapter name
    deps: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    workdir: str = "."
    status: str = "pending"              # pending -> running -> review -> done / failed
    attempts: int = 0
    session_id: str | None = None        # for claude --resume
    last_output: str = ""
    review_notes: str = ""
    branch: str | None = None            # worktree分離時のブランチ名
    cost_usd: float = 0.0                # このタスクの累計コスト(attempt横断)
    tools: str | None = None             # Plannerが明示付与するallowed_tools(worker既定を上書き)
    replans: int = 0                     # REPLAN再設計の回数(1タスク1回まで)
    personas: list[str] = field(default_factory=list)  # 検収ゲートのペルソナ名(空=通常レビューのみ)
    human_request: str = ""              # awaiting_human時の依頼一文(詳細は依頼書artifact)


@dataclass
class Mission:
    id: str
    intent: str
    context_digest: str
    tasks: list[Task]
    created_at: float = field(default_factory=time.time)
    budget: Budget | None = None         # 共有プール(参照渡し。再帰の前提)

    @staticmethod
    def new(intent: str, context_digest: str, tasks: list[dict]) -> "Mission":
        return Mission(
            id=uuid.uuid4().hex[:8],
            intent=intent,
            context_digest=context_digest,
            tasks=[build_task(t) for t in tasks],
        )


# task.id はartifact名・worktreeパス・gitブランチに直挿しされるため、
# パストラバーサル(../)やシェル・git参照メタ文字を含めない形式に限定する。
# LLM(Planner)由来の値を信頼せず、Mission生成・load時に強制する。
_TASK_ID_RE = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# Taskデータクラスの既知フィールド名(LLM由来のdictから未知キーを除去する)
_TASK_FIELDS = frozenset(f.name for f in fields(Task))


def build_task(data: dict) -> Task:
    """LLM(Planner/REPLAN)由来のtask dictを検証してTaskにする。

    - 未知キー(priority/description等のスキーマ揺れ)は黙って落とす
      (従来はTask(**t)がTypeErrorで即死し、runs/もコスト記録も残らなかった)
    - id は _TASK_ID_RE で強制(パストラバーサル・git参照汚染の防止)
    """
    known = {k: v for k, v in data.items() if k in _TASK_FIELDS}
    tid = known.get("id")
    if not isinstance(tid, str) or not _TASK_ID_RE.match(tid):
        raise ValueError(
            f"不正なtask.id: {tid!r}(英数字始まり・[A-Za-z0-9_-]・64字以内が必須)")
    return Task(**known)


# 実行中にクラッシュした場合、ロード時にpendingへ巻き戻す(デッドロック解消)
_INFLIGHT_STATUSES = ("queued", "running", "review")


class RunStore:
    """runs/<mission_id>/ に mission.json と ledger.jsonl を永続化。

    lock はミッション状態の変更・保存・ledger追記を守る単一ロック。
    orchestrator はタスクのフィールドを書き換える際に `with store.lock:` で囲む。
    """

    def __init__(self, root: str | Path, mission_id: str):
        self.dir = Path(root) / mission_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def save(self, mission: Mission) -> None:
        with self.lock:
            data = asdict(mission)
            tmp = self.dir / ".mission.json.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            os.replace(tmp, self.dir / "mission.json")

    def load(self, reset_inflight: bool = True) -> Mission:
        data = json.loads((self.dir / "mission.json").read_text())
        # 永続化済みmission.jsonのtaskも同じ検証を通す。id検証は書き込み時に
        # 済んでいるが、手編集・旧形式・未知キー混入への防御を読み取りにも掛ける
        data["tasks"] = [build_task(t) for t in data["tasks"]]
        if data.get("budget"):
            data["budget"] = Budget(**data["budget"])
        mission = Mission(**data)
        # 実行中系→pendingの巻き戻しはクラッシュ後の再実行(run/resume/approve)用。
        # 読み取り専用の照会(status等)でこれを適用すると実行中タスクを
        # pendingと偽るため、reset_inflight=Falseで生の永続状態を返せるようにする。
        # reset_inflight=Trueでも、永続lease(orgh/lease.py)が生きている場合は
        # 別プロセスが実際に走っている証拠なので巻き戻さない(生きている
        # プロセスの状態を偽らない)。leaseが無い/失効している場合のみ、
        # 従来どおりクラッシュ復旧として巻き戻す
        if reset_inflight and not lease.is_alive(self.dir):
            for t in mission.tasks:
                if t.status in _INFLIGHT_STATUSES:
                    t.status = "pending"
        return mission

    def log(self, event: str, **kw: Any) -> None:
        rec = {"ts": time.time(), "event": event, **kw}
        with self.lock:
            with open(self.dir / "ledger.jsonl", "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def artifact(self, name: str, content: str) -> Path:
        p = (self.dir / "artifacts").resolve()
        p.mkdir(exist_ok=True)
        # nameにtask.id等が埋め込まれるため、resolve後にartifacts配下から
        # 外れる名前(../を含む等)は拒否する(パストラバーサルの多層防御)
        fp = (p / name).resolve()
        if not fp.is_relative_to(p):
            raise ValueError(f"artifact名がartifacts/外を指す: {name!r}")
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return fp

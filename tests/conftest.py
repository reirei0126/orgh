"""ST共通フィクスチャ: モックバイナリを指すconfigと隔離されたruns/state。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MOCK_CLAUDE = str(REPO / "tests" / "mocks" / "claude")
MOCK_CODEX = str(REPO / "tests" / "mocks" / "codex")

MOCK_ENV_VARS = [
    "MOCK_STATE_DIR", "MOCK_REJECT_ONCE", "MOCK_REVIEW_ALWAYS_FAIL",
    "MOCK_WORKER_FAIL", "MOCK_PLAN_JSON", "MOCK_NO_SLEEP", "MOCK_SLEEP_ALL",
    "MOCK_PLANNER_FAIL", "MOCK_REVIEW_REPLAN", "MOCK_REVIEW_REPLAN_ALWAYS",
    "MOCK_REPLAN_JSON", "MOCK_RETRO_JSON", "MOCK_GC_JSON",
    "MOCK_INFRA_FAIL_TIMES",
]


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """テストのcwdをtmpに隔離する。workdir "." のタスクがorghリポ自身を指すと
    自己改変ガード(タスク7)が発動してしまうため、中立なcwdで実行する。"""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def mock_state_dir(tmp_path, monkeypatch) -> Path:
    """モックの呼び出し履歴・状態の置き場。MOCK_*環境変数を毎テスト初期化する。"""
    for v in MOCK_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    d = tmp_path / "mock_state"
    d.mkdir()
    monkeypatch.setenv("MOCK_STATE_DIR", str(d))
    return d


@pytest.fixture
def cfg(tmp_path, mock_state_dir) -> dict:
    return {
        "runs_dir": str(tmp_path / "runs"),
        "prompts_dir": str(REPO / "prompts"),
        "playbooks_dir": str(REPO / "playbooks"),
        "workers": {
            "enabled": ["claude_code", "codex"],
            "claude_code": {"bin": MOCK_CLAUDE, "model": "sonnet",
                            "max_turns": 10},
            "codex": {"bin": MOCK_CODEX, "extra_args": ["--full-auto"]},
        },
        "roles": {
            "planner": {"bin": MOCK_CLAUDE, "model": "opus"},
            "reviewer": {"bin": MOCK_CLAUDE, "model": "sonnet"},
            "retro": {"bin": MOCK_CLAUDE, "model": "sonnet"},
        },
        "loop": {"parallel": 3, "max_attempts": 2, "task_timeout": 60},
    }


# --- watcher系の共有フィクスチャ ---------------------------------------------
# watch.interval に入れるセンチネル。time.sleep がこの値で呼ばれたときだけ
# ループを打ち切る(subprocess等が内部で呼ぶ time.sleep を誤爆させない)
INTERVAL_SENTINEL = 7.654321


@pytest.fixture
def vault(tmp_path) -> Path:
    v = tmp_path / "vault"
    (v / "inbox").mkdir(parents=True)
    return v


@pytest.fixture
def wcfg(cfg, vault) -> dict:
    cfg["vault"] = {"path": str(vault), "inbox": "inbox",
                    "mission_tag": "mission"}
    cfg["watch"] = {"interval": INTERVAL_SENTINEL,
                    "stabilize_seconds": 20, "writeback": True}
    return cfg


@pytest.fixture
def one_pass(monkeypatch):
    """watch()のループ末尾のsleep(interval)で抜けさせ、1パスだけ実行させる。"""
    import time as _time

    from orgh import watcher

    real_sleep = _time.sleep

    def _sleep(seconds):
        if seconds == INTERVAL_SENTINEL:
            raise KeyboardInterrupt
        real_sleep(seconds)
    monkeypatch.setattr(watcher.time, "sleep", _sleep)


def mission_dirs(runs_dir: str | Path) -> list[Path]:
    root = Path(runs_dir)
    if not root.exists():
        return []
    return [p for p in root.iterdir() if p.is_dir()]


def age(p: Path, seconds: int = 60) -> None:
    """stabilize判定を満たすようにmtimeを過去に飛ばす。"""
    import os
    import time as _time
    past = _time.time() - seconds
    os.utime(p, (past, past))


def write_config(tmp_path: Path, cfg: dict) -> Path:
    """CLI試験用のconfig.yamlをタスクworkdir(tmp直下)の外に書く。
    workdirがconfigファイルを含むと自己改変ガード(タスク7)の保護対象になる
    ため、専用サブディレクトリに隔離する。"""
    import yaml
    d = tmp_path / "orgh-config"
    d.mkdir(exist_ok=True)
    p = d / "config.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    return p


def read_calls(state_dir: Path) -> list[dict]:
    fp = state_dir / "calls.jsonl"
    if not fp.exists():
        return []
    return [json.loads(l) for l in fp.read_text().splitlines() if l.strip()]


def read_ledger(runs_dir: str | Path, mission_id: str) -> list[dict]:
    fp = Path(runs_dir) / mission_id / "ledger.jsonl"
    if not fp.exists():
        return []
    return [json.loads(l) for l in fp.read_text().splitlines() if l.strip()]

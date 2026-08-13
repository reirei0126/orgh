"""HANDOFF 0b受け入れ: クリーンvenvに非editableで pip install . → orgh run が動く。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from .conftest import MOCK_CLAUDE, MOCK_CODEX

REPO = Path(__file__).resolve().parent.parent


class TestPackaging:
    def test_pip_install_noneditable_then_orgh_run(self, tmp_path,
                                                   mock_state_dir,
                                                   playbooks_dir):
        venv = tmp_path / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True,
                       capture_output=True)
        pip = venv / "bin" / "pip"
        r = subprocess.run([str(pip), "install", str(REPO)],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"pip install . failed:\n{r.stdout}\n{r.stderr}"

        # 作業ディレクトリはリポ外。prompts/playbooksはconfigで解決される
        workdir = tmp_path / "work"
        workdir.mkdir()
        cfg = {
            "runs_dir": str(workdir / "runs"),
            "prompts_dir": str(REPO / "prompts"),
            "playbooks_dir": str(playbooks_dir),
            "workers": {"enabled": ["claude_code"],
                        "claude_code": {"bin": MOCK_CLAUDE}},
            "roles": {"planner": {"bin": MOCK_CLAUDE},
                      "reviewer": {"bin": MOCK_CLAUDE},
                      "retro": {"bin": MOCK_CLAUDE}},
            "loop": {"parallel": 2, "max_attempts": 2, "task_timeout": 60},
        }
        # configはworkdirの外に置く(workdirがconfigを含むと自己改変ガード対象)
        cfg_dir = tmp_path / "orgh-config"
        cfg_dir.mkdir()
        cfg_path = cfg_dir / "config.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True))

        orgh_bin = venv / "bin" / "orgh"
        env = {**os.environ}
        env.pop("PYTHONPATH", None)
        r = subprocess.run(
            [str(orgh_bin), "--config", str(cfg_path),
             "run", "--intent", "パッケージング疎通試験"],
            cwd=str(workdir), env=env, capture_output=True, text=True,
            timeout=120)
        assert r.returncode == 0, f"orgh run failed:\n{r.stdout}\n{r.stderr}"

        # ミッションが完走して永続化されている
        runs = [p for p in (workdir / "runs").iterdir() if p.is_dir()]
        assert len(runs) == 1
        data = json.loads((runs[0] / "mission.json").read_text())
        assert all(t["status"] == "done" for t in data["tasks"])

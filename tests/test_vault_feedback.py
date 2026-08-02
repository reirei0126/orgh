"""HANDOFF タスク4a: vault完結のフィードバック設計。

- 明示着火: #go タグ(または frontmatter `orgh: go`)がないと着火しない
- 競合安全writeback: 元ノートへの書き込みは着火直後のリンク1行のみ
- 結果ノート vault/orgh/results/<mission_id>.md: 着火時刻・タスク一覧・状態・
  失敗理由(review_notes)・検収ポイント(3行以内)・成果物への導線
- 着火前失敗(Planner失敗)は元ノートに [!failure] コールアウト+再着火可の明記
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from orgh import watcher

from .conftest import age, mission_dirs


def _plan_json(*tasks: dict) -> str:
    return json.dumps({"tasks": list(tasks)}, ensure_ascii=False)


def _plan_task(id: str, workdir: str = ".", write: str | None = None) -> dict:
    prompt = f"作業せよ [[MARK:{id}]]"
    if write:
        prompt += f" [[WRITE:{write}:edited-by-{id}]]"
    return {"id": id, "title": f"task {id}", "prompt": prompt,
            "worker": "claude_code", "deps": [],
            "acceptance": ["mock acceptance"], "workdir": workdir}


def _post(vault: Path, body: str, name: str = "ミッション.md") -> Path:
    note = vault / "inbox" / name
    note.write_text(body)
    age(note)
    return note


def _results_note(vault: Path, mission_id: str) -> Path:
    return vault / "orgh" / "results" / f"{mission_id}.md"


class TestExplicitTrigger:
    """#go なしのinboxノートは着火しない(明示着火)。"""

    def test_inbox_note_without_go_does_not_trigger(self, wcfg, vault,
                                                    one_pass, mock_state_dir):
        _post(vault, "やること\n")
        watcher.watch(wcfg)
        assert mission_dirs(wcfg["runs_dir"]) == []

    def test_mission_tag_alone_is_candidate_but_not_triggered(
            self, wcfg, vault, one_pass, mock_state_dir):
        _post(vault, "やること #mission\n")
        watcher.watch(wcfg)
        assert mission_dirs(wcfg["runs_dir"]) == []

    def test_go_tag_triggers(self, wcfg, vault, one_pass, mock_state_dir):
        _post(vault, "やること #go\n")
        watcher.watch(wcfg)
        assert len(mission_dirs(wcfg["runs_dir"])) == 1

    def test_frontmatter_orgh_go_triggers(self, wcfg, vault, one_pass,
                                          mock_state_dir):
        _post(vault, "---\norgh: go\n---\nやること\n")
        watcher.watch(wcfg)
        assert len(mission_dirs(wcfg["runs_dir"])) == 1


class TestConflictSafeWriteback:
    """元ノートへの書き込みは着火直後の1回・リンク1行のみ。"""

    def test_origin_note_gets_exactly_one_link_line(self, wcfg, vault,
                                                    one_pass, mock_state_dir):
        original = "やること #go\n"
        note = _post(vault, original)
        watcher.watch(wcfg)  # ミッションはこのパス内で完走する

        [mdir] = mission_dirs(wcfg["runs_dir"])
        body = note.read_text()
        assert body.startswith(original)
        added = [l for l in body[len(original):].splitlines() if l.strip()]
        # 完走後もリンク1行だけ(進行・結果は結果ノート側に書く)
        assert added == [f"> 🚀 orgh: [[orgh/results/{mdir.name}]]"]


class TestResultsNote:
    def test_progress_states_and_failure_reason(self, wcfg, vault, one_pass,
                                                mock_state_dir, monkeypatch):
        monkeypatch.setenv("MOCK_PLAN_JSON",
                           _plan_json(_plan_task("w1"), _plan_task("w2")))
        monkeypatch.setenv("MOCK_REVIEW_ALWAYS_FAIL", "w2")
        _post(vault, "やること #go\n")
        watcher.watch(wcfg)

        [mdir] = mission_dirs(wcfg["runs_dir"])
        body = _results_note(vault, mdir.name).read_text()
        assert "着火" in body                       # 着火時刻
        assert "task w1" in body and "task w2" in body  # タスク一覧
        assert "✅" in body and "❌" in body        # 各タスクの状態
        assert "1/2" in body                        # 完了数
        assert "モック差し戻し(常時fail)" in body   # 失敗理由(review_notes)

    def test_handoff_summary_at_top_within_3_lines(self, wcfg, vault,
                                                   one_pass, mock_state_dir):
        _post(vault, "やること #go\n")
        watcher.watch(wcfg)

        [mdir] = mission_dirs(wcfg["runs_dir"])
        body = _results_note(vault, mdir.name).read_text()
        assert "## 検収ポイント" in body
        assert body.index("## 検収ポイント") < body.index("## タスク")
        section = body.split("## 検収ポイント")[1].split("##")[0]
        bullets = [l for l in section.splitlines() if l.strip().startswith("-")]
        assert 1 <= len(bullets) <= 3

    def test_text_artifacts_copied_into_vault_and_linked(self, wcfg, vault,
                                                         one_pass,
                                                         mock_state_dir):
        _post(vault, "やること #go\n")
        watcher.watch(wcfg)

        [mdir] = mission_dirs(wcfg["runs_dir"])
        copied = vault / "orgh" / "artifacts" / mdir.name / "w1_attempt1.md"
        assert copied.exists()
        body = _results_note(vault, mdir.name).read_text()
        assert f"orgh/artifacts/{mdir.name}/w1_attempt1" in body

    def test_worktree_task_lists_changed_files(self, wcfg, vault, one_pass,
                                               mock_state_dir, tmp_path,
                                               monkeypatch):
        repo = tmp_path / "target-repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)],
                       check=True)
        subprocess.run(["git", "-C", str(repo), "config",
                        "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config",
                        "user.name", "orgh-test"], check=True)
        (repo / "shared.txt").write_text("base\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"],
                       check=True)

        wcfg["worktree"] = {"enabled": True}
        monkeypatch.setenv("MOCK_PLAN_JSON", _plan_json(
            _plan_task("w1", workdir=str(repo), write="shared.txt")))
        _post(vault, "リポを編集 #go\n")
        watcher.watch(wcfg)

        [mdir] = mission_dirs(wcfg["runs_dir"])
        body = _results_note(vault, mdir.name).read_text()
        assert "shared.txt" in body  # 変更ファイル一覧(diff --stat相当)


class TestPreMissionFailure:
    """mission_id採番前の失敗(Planner失敗)も元ノートに通知される。"""

    def test_planner_failure_writes_failure_callout(self, wcfg, vault,
                                                    one_pass, mock_state_dir,
                                                    monkeypatch):
        monkeypatch.setenv("MOCK_PLANNER_FAIL", "1")
        note = _post(vault, "やること #go\n")
        watcher.watch(wcfg)

        assert mission_dirs(wcfg["runs_dir"]) == []
        body = note.read_text()
        assert "> [!failure] orgh:" in body
        assert "再着火" in body  # ノート再編集で再着火できる旨の明記

    def test_failure_does_not_loop_and_edit_retriggers(self, wcfg, vault,
                                                       one_pass,
                                                       mock_state_dir,
                                                       monkeypatch):
        monkeypatch.setenv("MOCK_PLANNER_FAIL", "1")
        note = _post(vault, "やること #go\n")
        watcher.watch(wcfg)
        age(note)
        watcher.watch(wcfg)  # 失敗コールアウト追記後も連続再着火しない
        assert mission_dirs(wcfg["runs_dir"]) == []
        assert note.read_text().count("[!failure]") == 1

        # 原因解消 + ノート再編集 → 再着火する
        monkeypatch.delenv("MOCK_PLANNER_FAIL")
        with open(note, "a") as f:
            f.write("\n直した\n")
        age(note)
        watcher.watch(wcfg)
        assert len(mission_dirs(wcfg["runs_dir"])) == 1

"""結果ノート: <vault>/orgh/results/<mission_id>.md にミッションの進行・結果を
vault完結で書き出す(HANDOFF タスク4前半)。

- update(): 着火直後・タスク完了のたびに進行状態を全文再生成する
  (検収ポイント・成果物リンクは含めない)
- finalize(): ミッション完了時に検収ポイント・成果物への導線込みで全文再生成する
- cancel_requested(): ノート本文の #cancel タグ検知。cancel機構自体はタスク4bで
  実装するため、ここでは判定ロジックだけを先置きする
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from . import listing
from .sources.base import MissionFeedback

# 結果ノートの「成果物」節へコピーする対象拡張子(テキスト系のみ)
_TEXT_EXTS = {".md", ".txt", ".json", ".yaml", ".log"}

_TASK_ICONS = {"done": "✅", "failed": "❌", "cancelled": "⊘",
               "skipped": "⊘", "awaiting_approval": "🔒",
               "awaiting_human": "🙋"}


def _task_icon(status: str) -> str:
    return _TASK_ICONS.get(status, "⏳")


class ResultsNote(MissionFeedback):
    def __init__(self, cfg: dict, mission_id: str) -> None:
        self.cfg = cfg
        self.mission_id = mission_id
        self.vault = Path(cfg["vault"]["path"]).expanduser()
        self.path = self.vault / "orgh" / "results" / f"{mission_id}.md"

    # ------------------------------------------------------------------ 公開API
    def update(self, mission) -> None:
        """進行状態を全文再生成する(検収ポイント・成果物なし)。"""
        self._write(self._render(mission, finalize=False))

    def finalize(self, mission, store) -> None:
        """検収ポイント・成果物込みで全文再生成する(ミッション終了時)。"""
        self._write(self._render(mission, store=store, finalize=True))

    def cancel_requested(self) -> bool:
        """結果ノート本文に #cancel タグが含まれるか(タスク4bで使用)。"""
        if not self.path.exists():
            return False
        return "#cancel" in self.path.read_text()

    # ------------------------------------------------------------------ 内部
    def _write(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text)

    def _overall_status(self, mission) -> tuple[str, int, int]:
        statuses = [t.status for t in mission.tasks]
        n = len(statuses)
        done = sum(1 for s in statuses if s == "done")
        if statuses and all(s == "done" for s in statuses):
            label = "✅ 完了"
        elif any(s == "failed" for s in statuses):
            label = "❌ 失敗あり"
        elif any(s == "cancelled" for s in statuses):
            label = "⊘ 中止"
        elif any(s == "awaiting_approval" for s in statuses):
            # awaiting_approval と awaiting_human が同時に存在する場合は
            # status_json.status_payload と同一の優先順位(awaiting_approval優先)
            label = "🔒 承認待ち"
        elif any(s == "awaiting_human" for s in statuses):
            label = "🙋 人間対応待ち"
        else:
            label = "⏳ 実行中"
        return label, done, n

    def _render(self, mission, store=None, finalize: bool = False) -> str:
        label, done, n = self._overall_status(mission)
        created = datetime.fromtimestamp(mission.created_at).strftime(
            "%Y-%m-%d %H:%M:%S")

        lines = [
            f"# orgh mission {mission.id}",
            "",
            f"> [!info] 状態: {label} — done {done}/{n}",
            f"> 着火: {created} / intent: {mission.intent}",
            "",
        ]

        # 自己改変ガード: 承認要求を明示(承認はターミナルからのみ)
        if any(t.status == "awaiting_approval" for t in mission.tasks):
            lines += [
                f"> [!warning] orgh自身を対象とするタスクが承認待ち。"
                f"続行するには `orgh approve {mission.id}` を実行",
                "",
            ]

        # 人間対応待ち: 依頼一文をノート上でも見せ、完了報告コマンドを案内する
        for t in mission.tasks:
            if t.status == "awaiting_human":
                lines += [
                    f"> [!warning] 「{t.title}」が人間の対応待ち: {t.human_request}\n"
                    f"> 完了したら `orgh humandone {mission.id} {t.id} "
                    f"--note \"実施内容の要約\"` を実行",
                    "",
                ]

        if finalize:
            lines += self._acceptance_lines(mission, done, n)
            lines.append("")

        lines.append("## タスク")
        for t in mission.tasks:
            lines.append(
                f"- {_task_icon(t.status)} {t.title} [{t.status}] "
                f"(attempts={t.attempts})")
            if t.status == "failed" and t.review_notes:
                lines.append(f"    - 差し戻し理由: {t.review_notes[:500]}")

        if finalize:
            artifact_lines = self._artifact_lines(mission, store)
            if artifact_lines:
                lines.append("")
                lines.append("## 成果物")
                lines += artifact_lines

        return "\n".join(lines) + "\n"

    def _acceptance_lines(self, mission, done: int, n: int) -> list[str]:
        """検収ポイント(箇条書き1〜3行)。"""
        lines = ["## 検収ポイント"]
        failed = [t for t in mission.tasks if t.status == "failed"]
        if failed:
            titles = "、".join(t.title for t in failed)
            lines.append(f"- done {done}/{n}。要確認: {titles}")
            first_notes = failed[0].review_notes[:120]
            if first_notes:
                lines.append(f"- {first_notes}")
        else:
            lines.append(f"- done {done}/{n}。全タスク完了")
        lines.append(f"- 成果物: [[orgh/artifacts/{mission.id}/]] 配下")
        # orgh verdict --pending(A1out)と同じ判定ロジックを再利用する(二重定義しない)
        pending = listing.list_pending_verdicts(
            self.cfg.get("runs_dir", "runs"))["missions"]
        lines.append(f"- 未裁定のミッションが{len(pending)}件あります")
        return lines

    def _artifact_lines(self, mission, store) -> list[str]:
        lines: list[str] = []
        if store is not None:
            src = Path(store.dir) / "artifacts"
            if src.is_dir():
                dest = self.vault / "orgh" / "artifacts" / mission.id
                for fp in sorted(src.iterdir()):
                    if fp.suffix.lower() not in _TEXT_EXTS:
                        continue
                    dest.mkdir(parents=True, exist_ok=True)
                    (dest / fp.name).write_text(fp.read_text())
                    # .md はObsidianのノートリンクとして拡張子なしのstemでリンク
                    target = fp.stem if fp.suffix.lower() == ".md" else fp.name
                    lines.append(f"- [[orgh/artifacts/{mission.id}/{target}]]")

        for t in mission.tasks:
            if not t.branch:
                continue
            summary = self._git_diff_summary(t.workdir)
            if summary:
                lines.append(f"- task {t.id} 変更ファイル:")
                lines.append("```")
                lines.append(summary)
                lines.append("```")
        return lines

    def _git_diff_summary(self, workdir: str) -> str:
        """タスクの変更概要。合格成果はタスクブランチへ自動コミットされるため、
        未コミット分(status/diff)に加え、直近の自動コミット(orgh(...))のstatも載せる。"""
        try:
            status = subprocess.run(
                ["git", "-C", workdir, "status", "--short"],
                capture_output=True, text=True, check=True)
            diffstat = subprocess.run(
                ["git", "-C", workdir, "diff", "--stat"],
                capture_output=True, text=True, check=True)
            committed_stat = ""
            head_subject = subprocess.run(
                ["git", "-C", workdir, "log", "-1", "--format=%s"],
                capture_output=True, text=True)
            if head_subject.returncode == 0 and \
                    head_subject.stdout.startswith("orgh("):
                committed = subprocess.run(
                    ["git", "-C", workdir, "diff", "--stat", "HEAD~1..HEAD"],
                    capture_output=True, text=True)
                if committed.returncode == 0:
                    committed_stat = committed.stdout.strip()
        except (subprocess.CalledProcessError, OSError):
            return ""  # git失敗時は黙って省略
        parts = [p for p in (status.stdout.strip(), diffstat.stdout.strip(),
                             committed_stat) if p]
        return "\n".join(parts)

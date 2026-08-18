"""仕様理解度クイズ(docs/quiz/)の設問バンク検証。

設問バンクはリポジトリの実装を出典とする学習用データなので、腐らせないために
形式と出典の実在をテストで固定する:
- id重複なし / カテゴリ・難易度が定義済みの値
- 選択肢が2つ以上・正解indexが範囲内・single=1個/multi=2個以上
- 解説が空でない / 出典に挙げたパスがリポジトリに実在する
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
QUIZ_DIR = REPO_ROOT / "docs" / "quiz"
BANK_JS = QUIZ_DIR / "questions.js"

VALID_DIFFICULTIES = {"basic", "applied", "internals"}
VALID_TYPES = {"single", "multi"}


def load_bank() -> dict:
    """questions.js の `window.ORGH_QUIZ = { ... };` からJSON本体を取り出す。

    アプリは file:// で直接開けるようJSファイルとして読み込む形にしているため、
    テスト側はJSラッパを剥がしてからパースする。
    """
    text = BANK_JS.read_text(encoding="utf-8")
    start = text.index("{")
    end = text.rindex("}")
    return json.loads(text[start:end + 1])


BANK = load_bank()
QUESTIONS = BANK["questions"]
CATEGORY_IDS = {c["id"] for c in BANK["categories"]}


def test_app_files_exist():
    for name in ("index.html", "quiz.js", "quiz.css", "questions.js"):
        assert (QUIZ_DIR / name).is_file()


def test_ids_are_unique():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == len(set(ids))


def test_every_category_has_questions():
    used = {q["category"] for q in QUESTIONS}
    assert used == CATEGORY_IDS


def test_categories_declare_reading():
    for c in BANK["categories"]:
        assert c["label"] and c["reading"]


@pytest.mark.parametrize("q", QUESTIONS, ids=[q["id"] for q in QUESTIONS])
class TestQuestion:
    def test_metadata(self, q):
        assert q["category"] in CATEGORY_IDS
        assert q["difficulty"] in VALID_DIFFICULTIES
        assert q["type"] in VALID_TYPES
        assert q["question"].strip()

    def test_choices_and_answer(self, q):
        choices, answer = q["choices"], q["answer"]
        assert len(choices) >= 2
        assert all(c.strip() for c in choices)
        assert len(choices) == len(set(choices))
        assert answer, "正解が空"
        assert len(answer) == len(set(answer))
        assert all(0 <= i < len(choices) for i in answer)
        if q["type"] == "single":
            assert len(answer) == 1
        else:
            assert len(answer) >= 2

    def test_explanation_and_sources(self, q):
        assert q["explanation"].strip()
        assert q["sources"], "出典が空"
        for src in q["sources"]:
            assert (REPO_ROOT / src).exists(), f"{q['id']}: 出典が実在しない {src}"

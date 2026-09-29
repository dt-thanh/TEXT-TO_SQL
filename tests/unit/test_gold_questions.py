"""The benchmark file must stay well formed as people add questions (eval/gold_questions.jsonl)."""

import json
from pathlib import Path

from src.semantic.layer import load_semantic_layer

GOLD_FILE = Path(__file__).resolve().parents[2] / "eval" / "gold_questions.jsonl"
FIELDS = {"question_id", "split", "difficulty", "tags", "question", "expected_tables",
          "expected_sql", "notes"}  # fmt: skip
LANGUAGES = {"en", "vi", "vi-no-accent"}
SKILLS = {"aggregate", "relative-date", "window", "ranking", "volatility", "period-return",
          "multi-asset", "macro", "lag", "monthly", "unanswerable", "adversarial"}  # fmt: skip
GOLD = [json.loads(line) for line in GOLD_FILE.read_text(encoding="utf-8").splitlines() if line]


def test_every_question_has_exactly_the_expected_fields() -> None:
    for gold in GOLD:
        assert set(gold) == FIELDS, gold["question_id"]


def test_question_ids_are_unique() -> None:
    ids = [g["question_id"] for g in GOLD]

    assert len(ids) == len(set(ids))


def test_split_level_and_tags_use_the_known_values() -> None:
    for gold in GOLD:
        qid, tags = gold["question_id"], set(gold["tags"])
        assert gold["split"] in {"dev", "holdout"}, qid
        assert 0 <= gold["difficulty"] <= 8, qid  # spec §27 levels; 0 = cannot be answered
        assert tags <= LANGUAGES | SKILLS, f"{qid}: unknown tag {tags - LANGUAGES - SKILLS}"
        assert len(tags & LANGUAGES) == 1, f"{qid}: needs exactly one language tag"


def test_only_questions_that_must_not_be_answered_have_no_sql() -> None:
    for gold in GOLD:
        must_not_answer = bool({"unanswerable", "adversarial"} & set(gold["tags"]))
        assert (gold["expected_sql"] is None) == must_not_answer, gold["question_id"]


def test_no_benchmark_question_is_one_of_the_verified_examples() -> None:
    # A question the model saw as an example measures copying, not skill.
    examples = {ex.question.strip().lower() for ex in load_semantic_layer().verified_queries}

    for gold in GOLD:
        assert gold["question"].strip().lower() not in examples, gold["question_id"]

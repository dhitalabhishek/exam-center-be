import logging  # noqa: N999
from io import TextIOWrapper
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def parse_questions_from_csv(file) -> list[dict[str, Any]]:
    """
    Parses questions from a CSV file in the following format:
    QUESTION, ANSWER, OPTIONS_A, OPTIONS_B, OPTIONS_C, OPTIONS_D

    ANSWER should be one of: a, b, c, d (case-insensitive)
    """
    try:
        df = pd.read_csv(TextIOWrapper(file, encoding="utf-8"))  # noqa: PD901
        logger.info("CSV file successfully read with %d rows.", len(df))
    except Exception as e:
        logger.exception("Failed to read CSV file: %s", str(e))
        raise

    questions = []
    for idx, row in df.iterrows():
        question_text = str(row.get("QUESTION", "")).strip()
        answer_letter = str(row.get("ANSWER", "")).strip().lower()

        options = {
            "a": str(row.get("OPTIONS_A", "")).strip(),
            "b": str(row.get("OPTIONS_B", "")).strip(),
            "c": str(row.get("OPTIONS_C", "")).strip(),
            "d": str(row.get("OPTIONS_D", "")).strip(),
        }

        if answer_letter not in options:
            logger.warning(
                "Row %d: Invalid answer '%s'. Must be one of a/b/c/d.",
                idx + 1,
                answer_letter,
            )

        answers = []
        for letter, text in options.items():
            if not text:
                continue
            answers.append(
                {
                    "text": text,
                    "option_letter": letter.strip().upper(),
                    "is_correct": (letter.strip().lower() == answer_letter),
                },
            )

        if not question_text:
            logger.warning("Row %d: Empty question text.", idx + 1)

        if not answers:
            logger.warning("Row %d: No valid options provided.", idx + 1)

        if question_text and answers:
            questions.append(
                {
                    "question": question_text,
                    "answers": answers,
                },
            )
            logger.debug(
                "Row %d: Parsed question with %d options.",
                idx + 1,
                len(answers),
            )

    logger.info("Total valid questions parsed: %d", len(questions))
    return questions

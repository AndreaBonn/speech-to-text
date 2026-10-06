from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from sbobina.generation_models import (
    GenerationFormat,
)
from sbobina.generation_text_questions import OralQuestionResponse, TextQuestionResponse
from sbobina.solution_points import extract_solution_points

CITATION = {"passaggio": "P1", "testo": "tre parole almeno"}


def _open(question: Mapping[str, object]) -> str:
    response = TextQuestionResponse.model_validate({"domande": [question]})
    return response.questions[0].solution


def _oral(question: Mapping[str, object]) -> str:
    response = OralQuestionResponse.model_validate({"domande": [question]})
    return response.questions[0].solution


def test_open_points_become_sentences_the_judge_splits_back() -> None:
    # F41: with one free-text "soluzione" every solution had a single point;
    # compito-v4 asks for a "punti" list (2 points in 12 of 12 measured).
    solution = _open(
        {
            "domanda": "Che cos'è?",
            "punti": [
                "gli investimenti coprono l'ammortamento",
                "Il capitale resta costante.",
            ],
            "citazioni": [CITATION],
        }
    )

    assert (
        solution
        == "Gli investimenti coprono l'ammortamento. Il capitale resta costante."
    )
    assert extract_solution_points(solution=solution, format=GenerationFormat.OPEN) == (
        "Gli investimenti coprono l'ammortamento",
        "Il capitale resta costante",
    )


def test_oral_points_become_an_outline_split_on_the_separator() -> None:
    solution = _oral(
        {
            "domanda": "Le azioni?",
            "punti": ["reintegrazione", "manutenzione"],
            "citazioni": [CITATION],
        }
    )

    assert solution == "reintegrazione | manutenzione"
    assert extract_solution_points(solution=solution, format=GenerationFormat.ORAL) == (
        "reintegrazione",
        "manutenzione",
    )


def test_a_free_text_solution_from_older_prompts_is_still_accepted() -> None:
    question = {
        "domanda": "Che cos'è?",
        "soluzione": "Una frase sola.",
        "citazioni": [CITATION],
    }

    assert _open(question) == "Una frase sola."
    assert _oral(question) == "Una frase sola."


def test_a_question_without_points_or_solution_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _open({"domanda": "Che cos'è?", "citazioni": [CITATION]})


def test_points_that_are_not_text_are_left_out() -> None:
    # Ollama ignores the schema with think=False (CLAUDE.md): a null point
    # must not become the sentence "None." (F85).
    solution = _open(
        {
            "domanda": "Che cos'è?",
            "punti": [None, 3, "Il punto vero"],
            "citazioni": [CITATION],
        }
    )

    assert solution == "Il punto vero."

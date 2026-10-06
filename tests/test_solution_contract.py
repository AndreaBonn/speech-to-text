from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from sbobina.generation_models import (
    GenerationFormat,
)
from sbobina.generation_text_questions import OralQuestionResponse, TextQuestionResponse
from sbobina.generation_validation import validate_exam_response
from sbobina.retrieval import DocumentSource, RetrievedPassage
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


def test_an_empty_solution_drops_only_its_question() -> None:
    # A28: an empty "soluzione" left the judge without any point. Like invalid
    # options, it drops that question, not the whole reply.
    passage = RetrievedPassage(
        text="tre parole almeno qui",
        source=DocumentSource(doc_id="manuale", page=1, chunk=0),
        passage_id="manuale:p1:c0",
    )
    empty = {"domanda": "Vuota?", "soluzione": "  ", "citazioni": [CITATION]}
    full = {"domanda": "Piena?", "punti": ["Un punto."], "citazioni": [CITATION]}
    response = TextQuestionResponse.model_validate({"domande": [empty, full]})

    questions, counts = validate_exam_response(response=response, passages=[passage])

    assert [q.question for q in questions] == ["Piena?"]
    assert counts == {"EMPTY_SOLUTION": 1}


def test_an_oral_point_holding_the_separator_stays_one_point() -> None:
    # A29: " | " inside a point would split it into two for the judge.
    solution = _oral(
        {
            "domanda": "Le azioni?",
            "punti": ["reintegrazione | entro un anno", "manutenzione"],
            "citazioni": [CITATION],
        }
    )

    assert extract_solution_points(solution=solution, format=GenerationFormat.ORAL) == (
        "reintegrazione, entro un anno",
        "manutenzione",
    )


def test_an_absolute_value_in_an_oral_point_is_kept() -> None:
    solution = _oral(
        {
            "domanda": "Converge?",
            "punti": ["Se \\(|q| < 1\\)", "Altrimenti no"],
            "citazioni": [CITATION],
        }
    )

    assert solution == "Se \\(|q| < 1\\) | Altrimenti no"

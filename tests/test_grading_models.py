import json
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from sbobina.generation_models import GenerationFormat
from sbobina.grading_models import (
    CoveredPoint,
    GradingError,
    Judgement,
    ProposedJudgement,
    validate_judgement,
)

POINTS = ("Il capitale resta costante", "Gli investimenti coprono gli ammortamenti")
SOLUTION = " | ".join(POINTS)
ANSWER = "Il capitale resta costante. Gli investimenti coprono gli ammortamenti."


def proposed(
    covered: list[dict[str, str]] | None = None,
    missing: list[str] | None = None,
    errors: list[dict[str, str]] | None = None,
) -> ProposedJudgement:
    return ProposedJudgement.model_validate(
        {
            "punti_coperti": covered or [],
            "punti_mancanti": missing or [],
            "errori": errors or [],
        }
    )


def test_proposed_ignores_model_outcome_and_schema_excludes_it() -> None:
    raw = {
        "punti_coperti": [],
        "punti_mancanti": list(POINTS),
        "errori": [],
        "esito": "corretta",
    }
    assert json.loads(json.dumps(raw))["esito"] == "corretta"
    response = ProposedJudgement.model_validate(raw)
    judgement, _ = validate_judgement(
        proposed=response,
        solution=SOLUTION,
        answer=ANSWER,
        format=GenerationFormat.ORAL,
    )
    assert (judgement.outcome, judgement.score) == ("errata", 0)
    assert set(response.model_dump(by_alias=True)) == {
        "punti_coperti",
        "punti_mancanti",
        "errori",
    }
    assert set(ProposedJudgement.model_json_schema()["properties"]) == {
        "punti_coperti",
        "punti_mancanti",
        "errori",
    }


@pytest.mark.parametrize("field,value", [("outcome", "corretta"), ("score", 1)])
def test_judgement_derived_fields_cannot_be_constructed_or_assigned(
    field: str, value: object
) -> None:
    kwargs: dict[str, Any] = {
        "covered_points": (),
        "missing_points": POINTS,
        "errors": (),
        field: value,
    }
    with pytest.raises(TypeError, match=field):
        Judgement(**kwargs)
    judgement = Judgement(covered_points=(), missing_points=POINTS, errors=())
    with pytest.raises(FrozenInstanceError):
        setattr(judgement, field, value)
    assert (judgement.outcome, judgement.score) == ("errata", 0)


@pytest.mark.parametrize(
    "count,has_error,expected",
    [
        (2, False, ("corretta", 1)),
        (1, False, ("parziale", 0.5)),
        (0, False, ("errata", 0)),
        (2, True, ("parziale", 0.5)),
        (0, True, ("errata", 0)),
    ],
)
def test_judgement_derives_outcome_and_score(
    count: int, has_error: bool, expected: tuple[str, float]
) -> None:
    judgement = Judgement(
        covered_points=tuple(
            CoveredPoint(point=point, evidence=point) for point in POINTS[:count]
        ),
        missing_points=POINTS[count:],
        errors=(GradingError(phrase="Il capitale cala", reason="Contradiction"),)
        if has_error
        else (),
    )
    assert (judgement.outcome, judgement.score) == expected


@pytest.mark.parametrize("count", [1, 2])
def test_judgement_any_incomplete_coverage_is_partial(count: int) -> None:
    points = (*POINTS, "Il reddito è stabile")
    judgement = Judgement(
        covered_points=tuple(CoveredPoint(point=p, evidence=p) for p in points[:count]),
        missing_points=points[count:],
        errors=(),
    )
    assert (judgement.outcome, judgement.score) == ("parziale", 0.5)


def test_missing_evidence_discards_only_unanchored_point_with_code() -> None:
    response = proposed(
        covered=[
            {"punto": POINTS[0], "prova": "Testo inventato"},
            {"punto": POINTS[1], "prova": POINTS[1]},
        ]
    )
    judgement, counts = validate_judgement(
        proposed=response,
        solution=SOLUTION,
        answer=ANSWER,
        format=GenerationFormat.ORAL,
    )
    assert judgement.covered_points == (
        CoveredPoint(point=POINTS[1], evidence=POINTS[1]),
    )
    assert judgement.missing_points == (POINTS[0],)
    assert counts == {"EVIDENCE_NOT_IN_ANSWER": 1}
    assert judgement.score == 0.5


@pytest.mark.parametrize(
    "evidence,expected_counts",
    [
        ("IL CAPITALE, RESTA COSTANTE!", {}),
        ("capitale resta costante", {}),
        ("capitale costante", {"EVIDENCE_NOT_IN_ANSWER": 1}),
        ("", {"EVIDENCE_NOT_IN_ANSWER": 1}),
        ("!!!", {"EVIDENCE_NOT_IN_ANSWER": 1}),
        # The prompt asks for 3-40 words: a one- or two-word quote is found in
        # almost any answer and would credit a point the student never made.
        ("capitale resta", {"QUOTE_LENGTH_OUT_OF_RANGE": 1}),
        ("costante", {"QUOTE_LENGTH_OUT_OF_RANGE": 1}),
    ],
)
def test_evidence_requires_contiguous_quote_of_three_to_forty_words(
    evidence: str, expected_counts: dict[str, int]
) -> None:
    judgement, counts = validate_judgement(
        proposed=proposed(covered=[{"punto": POINTS[0], "prova": evidence}]),
        solution=SOLUTION,
        answer=ANSWER,
        format=GenerationFormat.ORAL,
    )
    assert len(judgement.covered_points) == int(not expected_counts)
    assert counts == expected_counts


def test_evidence_longer_than_forty_words_is_discarded() -> None:
    long_answer = " ".join(f"parola{index}" for index in range(41))
    within = " ".join(f"parola{index}" for index in range(40))

    judgement, counts = validate_judgement(
        proposed=proposed(
            covered=[
                {"punto": POINTS[0], "prova": long_answer},
                {"punto": POINTS[1], "prova": within},
            ]
        ),
        solution=SOLUTION,
        answer=long_answer,
        format=GenerationFormat.ORAL,
    )

    assert judgement.covered_points == (CoveredPoint(point=POINTS[1], evidence=within),)
    assert counts == {"QUOTE_LENGTH_OUT_OF_RANGE": 1}


def test_error_phrase_shorter_than_three_words_is_discarded() -> None:
    judgement, counts = validate_judgement(
        proposed=proposed(
            errors=[
                {"frase": "capitale resta", "motivo": "Too short"},
                {"frase": "capitale resta costante", "motivo": "Contradiction"},
            ]
        ),
        solution=SOLUTION,
        answer=ANSWER,
        format=GenerationFormat.ORAL,
    )

    assert judgement.errors == (
        GradingError(phrase="capitale resta costante", reason="Contradiction"),
    )
    assert counts == {"QUOTE_LENGTH_OUT_OF_RANGE": 1}


def test_unanchored_points_missing_points_and_errors_are_discarded_individually() -> (
    None
):
    response = proposed(
        covered=[
            {"punto": "Il capitale costante", "prova": POINTS[0]},
            {"punto": POINTS[0], "prova": POINTS[0]},
        ],
        missing=["Testo estraneo", POINTS[1]],
        errors=[
            {"frase": "Mai scritto", "motivo": "Wrong"},
            {"frase": POINTS[1], "motivo": "Contradiction"},
        ],
    )
    judgement, counts = validate_judgement(
        proposed=response,
        solution=SOLUTION,
        answer=ANSWER,
        format=GenerationFormat.ORAL,
    )
    assert judgement.covered_points == (
        CoveredPoint(point=POINTS[0], evidence=POINTS[0]),
    )
    assert judgement.missing_points == (POINTS[1],)
    assert judgement.errors == (GradingError(phrase=POINTS[1], reason="Contradiction"),)
    assert counts == {
        "POINT_NOT_IN_SOLUTION": 1,
        "MISSING_POINT_NOT_IN_SOLUTION": 1,
        "ERROR_NOT_IN_ANSWER": 1,
    }


@pytest.mark.parametrize(
    "format,solution",
    [(GenerationFormat.ORAL, SOLUTION), (GenerationFormat.OPEN, ANSWER)],
)
def test_omitted_and_duplicate_points_do_not_inflate_coverage(
    format: GenerationFormat, solution: str
) -> None:
    item = {"punto": POINTS[0], "prova": POINTS[0]}
    judgement, _ = validate_judgement(
        proposed=proposed(covered=[item, item]),
        solution=solution,
        answer=ANSWER,
        format=format,
    )
    assert judgement.covered_points == (
        CoveredPoint(point=POINTS[0], evidence=POINTS[0]),
    )
    assert judgement.missing_points == (POINTS[1],)
    assert judgement.score == 0.5


def test_empty_solution_and_answer_have_zero_coverage() -> None:
    judgement, counts = validate_judgement(
        proposed=proposed(), solution="", answer="", format=GenerationFormat.OPEN
    )
    assert judgement == Judgement(covered_points=(), missing_points=(), errors=())
    assert (judgement.outcome, judgement.score) == ("errata", 0)
    assert counts == {}


@pytest.mark.parametrize("include_missing", [True, False])
def test_covered_point_does_not_expand_to_a_longer_solution_point(
    include_missing: bool,
) -> None:
    longer = f"{POINTS[0]} soltanto in equilibrio"
    judgement, counts = validate_judgement(
        proposed=proposed(
            covered=[{"punto": POINTS[0], "prova": POINTS[0]}],
            missing=[longer] if include_missing else [],
        ),
        solution=f"{longer} | {POINTS[0]}",
        answer=POINTS[0],
        format=GenerationFormat.ORAL,
    )
    assert judgement.covered_points == (
        CoveredPoint(point=POINTS[0], evidence=POINTS[0]),
    )
    assert judgement.missing_points == (longer,)
    assert (judgement.outcome, judgement.score) == ("parziale", 0.5)
    assert counts == {}


def test_anchored_missing_point_is_preserved_when_also_reported_covered() -> None:
    judgement, counts = validate_judgement(
        proposed=proposed(
            covered=[{"punto": POINTS[0], "prova": POINTS[0]}], missing=[POINTS[0]]
        ),
        solution=POINTS[0],
        answer=POINTS[0],
        format=GenerationFormat.ORAL,
    )
    assert judgement.covered_points == (
        CoveredPoint(point=POINTS[0], evidence=POINTS[0]),
    )
    assert judgement.missing_points == (POINTS[0],)
    assert judgement.score == 0.5
    assert counts == {}


def test_shared_fragment_is_not_promoted_to_multiple_full_points() -> None:
    points = ("Il capitale resta costante", "Il capitale cresce rapidamente")
    judgement, _ = validate_judgement(
        proposed=proposed(covered=[{"punto": "Il capitale", "prova": POINTS[0]}]),
        solution=" | ".join(points),
        answer=POINTS[0],
        format=GenerationFormat.ORAL,
    )
    assert judgement.covered_points == (
        CoveredPoint(point="Il capitale", evidence=POINTS[0]),
    )
    assert judgement.missing_points == (points[1],)
    assert judgement.score == 0.5

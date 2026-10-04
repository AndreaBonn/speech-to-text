import pytest

from sbobina.generation_models import GenerationFormat
from sbobina.solution_points import extract_solution_points


def test_extract_solution_points_oral_strips_and_discards_empty_points() -> None:
    assert extract_solution_points(
        solution="a | b | c", format=GenerationFormat.ORAL
    ) == ("a", "b", "c")
    assert extract_solution_points(
        solution="  a |  | b |   ", format=GenerationFormat.ORAL
    ) == ("a", "b")


def test_extract_solution_points_open_splits_three_sentences() -> None:
    assert extract_solution_points(
        solution=" Prima frase. Seconda frase! Terza frase? ",
        format=GenerationFormat.OPEN,
    ) == ("Prima frase", "Seconda frase", "Terza frase")


@pytest.mark.parametrize("format", tuple(GenerationFormat))
@pytest.mark.parametrize("solution", ("", " \n\t "))
def test_extract_solution_points_blank_returns_empty(
    format: GenerationFormat, solution: str
) -> None:
    assert extract_solution_points(solution=solution, format=format) == ()


def test_extract_solution_points_multiple_choice_returns_no_points() -> None:
    assert (
        extract_solution_points(solution="2", format=GenerationFormat.MULTIPLE_CHOICE)
        == ()
    )
    assert extract_solution_points(solution="2", format=GenerationFormat.OPEN) == ("2",)


@pytest.mark.parametrize(
    ("solution", "expected"),
    (
        (
            "Secondo art. 1418 il contratto è nullo. Fine.",
            ("Secondo art. 1418 il contratto è nullo", "Fine"),
        ),
        (
            "Secondo art.1418 il contratto è nullo. Fine.",
            ("Secondo art.1418 il contratto è nullo", "Fine"),
        ),
        (
            "Vedi pag. iniziale del codice. È nullo.",
            ("Vedi pag. iniziale del codice", "È nullo"),
        ),
    ),
)
def test_extract_solution_points_abbreviation_does_not_split_sentence(
    solution: str, expected: tuple[str, ...]
) -> None:
    # T040: a period followed by a digit or a lowercase word is an abbreviation.
    assert (
        extract_solution_points(solution=solution, format=GenerationFormat.OPEN)
        == expected
    )

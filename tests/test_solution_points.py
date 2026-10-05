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


@pytest.mark.parametrize(
    ("solution", "expected"),
    (
        (
            "1. Il possesso è un potere di fatto. 2. La detenzione è senza animo.",
            ("Il possesso è un potere di fatto", "La detenzione è senza animo"),
        ),
        (
            "Due requisiti:\n1) Il possesso dura da un anno.\n2) Non è violento.",
            ("Due requisiti:", "Il possesso dura da un anno", "Non è violento"),
        ),
        # A legal reference after an abbreviation is not a list (review of F1).
        (
            "Si richiama il par. 3) il termine decorre. Poi si applica l'art. 5) Il rinvio.",
            (
                "Si richiama il par. 3) il termine decorre",
                "Poi si applica l'art. 5) Il rinvio",
            ),
        ),
        # A number inside a sentence is not a list marker: "comma 2" stays.
        (
            "Si applica il comma 2. Il termine è annuale.",
            ("Si applica il comma 2", "Il termine è annuale"),
        ),
    ),
)
def test_extract_solution_points_numbered_list_items_become_points(
    solution: str, expected: tuple[str, ...]
) -> None:
    # F1: list markers ("1.", "2)") are separators, never points of their own.
    assert (
        extract_solution_points(solution=solution, format=GenerationFormat.OPEN)
        == expected
    )


def test_extract_solution_points_oral_without_separator_splits_sentences() -> None:
    # F41: the model sometimes writes an oral outline as prose; one point per
    # sentence still lets the judge tell an incomplete answer apart.
    solution = (
        "Il possesso è una situazione di fatto. Anche quello di malafede è tutelato."
    )

    assert extract_solution_points(solution=solution, format=GenerationFormat.ORAL) == (
        "Il possesso è una situazione di fatto",
        "Anche quello di malafede è tutelato",
    )
    assert extract_solution_points(
        solution="Primo | secondo. Ancora secondo", format=GenerationFormat.ORAL
    ) == ("Primo", "secondo. Ancora secondo")

import json

from sbobina.generation_text_questions import TextQuestionResponse
from sbobina.json_salvage import complete_items, keep_valid
from sbobina.study_models import StudyResponse

CITATION = {"passaggio": "P1", "testo": "tre parole almeno"}


def test_keep_valid_drops_only_the_closed_item_outside_the_schema() -> None:
    # F89: one malformed but closed item must not sink the valid ones.
    items = [
        {"soluzione": "manca la domanda", "citazioni": [CITATION]},
        {"domanda": "Piena?", "soluzione": "Sì.", "citazioni": [CITATION]},
    ]

    kept = keep_valid(
        items=items, response_model=TextQuestionResponse, field="questions"
    )

    assert kept == [items[1]]


def test_keep_valid_works_on_study_chapters() -> None:
    chapter = {
        "titolo": "A",
        "inizio": 0,
        "riassunto": [],
        "concetti": [],
        "domande": [],
    }
    no_title = {key: value for key, value in chapter.items() if key != "titolo"}

    kept = keep_valid(
        items=[no_title, chapter], response_model=StudyResponse, field="chapters"
    )

    assert kept == [chapter]


def test_complete_items_stops_at_the_item_cut_short() -> None:
    whole = json.dumps({"capitoli": [{"titolo": "A"}, {"titolo": "B"}]})

    assert complete_items(content=whole[:-8], key="capitoli") == [{"titolo": "A"}]

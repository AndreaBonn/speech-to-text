import json
from dataclasses import asdict

import pytest
from pydantic import ValidationError

from sbobina.study_models import (
    Citation,
    ConceptItem,
    DiscardCount,
    FailedBlock,
    ProposedCitation,
    QuestionItem,
    RejectionReason,
    StudyChapter,
    StudyResponse,
    StudyResult,
    SummaryItem,
)


@pytest.fixture
def response_payload() -> dict[str, object]:
    citation = {"passaggio": "S12", "testo": "causa del contratto"}
    return {
        "capitoli": [
            {
                "titolo": "Il contratto",
                "inizio": 100.0,
                "riassunto": [{"testo": "Riassunto", "citazioni": [citation]}],
                "concetti": [
                    {
                        "termine": "causa",
                        "spiegazione": "Spiegazione",
                        "citazioni": [citation],
                    }
                ],
                "domande": [{"domanda": "Quale causa?", "citazioni": [citation]}],
            }
        ]
    }


def test_study_response_parses_italian_keys_and_segment_reference(
    response_payload: dict[str, object],
) -> None:
    response = StudyResponse.model_validate_json(json.dumps(response_payload))
    chapter = response.chapters[0]
    assert chapter.title == "Il contratto"
    assert chapter.start == 100.0
    assert chapter.summary[0].text == "Riassunto"
    assert chapter.concepts[0].term == "causa"
    assert chapter.questions[0].question == "Quale causa?"
    assert chapter.summary[0].citations[0].segment_index == 12
    assert response.model_dump(by_alias=True) == response_payload


@pytest.mark.parametrize("passage", ["12", "S-1", "S12x", "s12", 12, None])
def test_proposed_citation_rejects_malformed_segment_reference(passage: object) -> None:
    with pytest.raises(ValidationError):
        ProposedCitation.model_validate(
            {"passaggio": passage, "testo": "testo citato qui"}
        )


def test_study_response_empty_chapters_accepted(
    response_payload: dict[str, object],
) -> None:
    assert len(StudyResponse.model_validate(obj=response_payload).chapters) == 1

    response = StudyResponse.model_validate(obj={"capitoli": []})

    assert response.chapters == []


@pytest.mark.parametrize(
    "field", ["titolo", "inizio", "riassunto", "concetti", "domande"]
)
def test_study_response_missing_item_fields_rejected(
    response_payload: dict[str, object],
    field: str,
) -> None:
    assert (
        StudyResponse.model_validate(obj=response_payload).chapters[0].title
        == "Il contratto"
    )

    payload = json.loads(json.dumps(response_payload))
    del payload["capitoli"][0][field]

    with pytest.raises(ValidationError) as error:
        StudyResponse.model_validate(obj=payload)

    assert [(item["loc"], item["type"]) for item in error.value.errors()] == [
        (("capitoli", 0, field), "missing")
    ]


@pytest.fixture
def study_result() -> StudyResult:
    citation = Citation(segment_index=12, quote="causa del contratto")
    chapter = StudyChapter(
        title="Il contratto",
        start=100.0,
        summary=(SummaryItem(text="Riassunto", citations=(citation,)),),
        concepts=(
            ConceptItem(term="causa", explanation="Spiegazione", citations=(citation,)),
        ),
        questions=(QuestionItem(question="Quale causa?", citations=(citation,)),),
    )
    return StudyResult(
        source_variant="corrected",
        source_revision="abc",
        model="local",
        prompt_version="studio-v1",
        generated_at="2026-10-02T10:00:00Z",
        chapters=(chapter,),
        discarded=(DiscardCount(reason=RejectionReason.QUOTE_NOT_FOUND, count=2),),
        failed_blocks=(FailedBlock(start=200.0, end=300.0),),
    )


def test_study_result_serializes_only_stable_citation_coordinates(
    study_result: StudyResult,
) -> None:
    payload = json.loads(json.dumps(asdict(study_result)))
    assert set(payload) == {
        "source_variant",
        "source_revision",
        "model",
        "prompt_version",
        "generated_at",
        "chapters",
        "discarded",
        "failed_blocks",
        "served_by",
    }
    assert payload["chapters"][0]["summary"][0]["citations"] == [
        {"segment_index": 12, "quote": "causa del contratto"}
    ]
    assert payload["discarded"] == [{"reason": "QUOTE_NOT_FOUND", "count": 2}]
    assert payload["failed_blocks"] == [{"start": 200.0, "end": 300.0}]

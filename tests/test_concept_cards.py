from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import pytest

from sbobina.card_models import LectureAnchor
from sbobina.concept_cards import concept_cards
from sbobina.study_models import Citation, ConceptItem, StudyChapter, StudyResult

JOB_ID = str(uuid4())
OTHER_JOB_ID = str(uuid4())


def study_fixture(count: int = 12) -> StudyResult:
    concepts = tuple(
        ConceptItem(
            term=f"concetto{i}",
            explanation=f"Spiegazione {i}",
            citations=(
                Citation(segment_index=i, quote=f"il concetto{i} è importante"),
                Citation(segment_index=i + 1, quote="una seconda citazione"),
            ),
        )
        for i in range(count)
    )
    return StudyResult(
        source_variant="original",
        source_revision="old",
        model="test",
        prompt_version="test",
        generated_at="",
        discarded=(),
        failed_blocks=(),
        chapters=(
            StudyChapter(
                title="Capitolo", start=0, summary=(), concepts=concepts, questions=()
            ),
        ),
    )


def test_concept_cards_twelve_concepts_copy_first_citation() -> None:
    result = study_fixture()
    drafts = concept_cards(
        result=result, job_id=JOB_ID, revision="current", source="concept"
    )
    assert isinstance(drafts, tuple) and len(drafts) == 12
    for item, draft in zip(result.chapters[0].concepts, drafts, strict=True):
        assert (draft.front, draft.back, draft.source) == (
            item.term,
            item.explanation,
            "concept",
        )
        assert draft.anchor == LectureAnchor(
            job_id=JOB_ID,
            revision="current",
            segment_index=item.citations[0].segment_index,
            quote=item.citations[0].quote,
        )
        assert (
            draft.dedup_key
            == sha256(f"{JOB_ID}:concept:{item.term}".encode()).hexdigest()
        )


def test_concept_cards_normalizes_term_and_separates_origin_and_source() -> None:
    result = study_fixture(count=1)
    concept = replace(result.chapters[0].concepts[0], term="  CONCETTO0  ")
    chapter = replace(result.chapters[0], concepts=(concept,))
    changed = replace(result, chapters=(chapter,))
    original = concept_cards(
        result=result, job_id=JOB_ID, revision="a", source="concept"
    )[0]
    normalized = concept_cards(
        result=changed, job_id=JOB_ID, revision="b", source="concept"
    )[0]
    assert original.dedup_key == normalized.dedup_key
    other_job = concept_cards(
        result=result, job_id=OTHER_JOB_ID, revision="a", source="concept"
    )[0]
    other_source = concept_cards(
        result=result, job_id=JOB_ID, revision="a", source="manual"
    )[0]
    assert len({original.dedup_key, other_job.dedup_key, other_source.dedup_key}) == 3
    assert normalized.front == "  CONCETTO0  "


def test_concept_cards_empty_and_multiple_chapters_keep_order() -> None:
    result = study_fixture(count=1)
    combined = replace(result, chapters=result.chapters * 2)
    assert (
        len(
            concept_cards(
                result=combined, job_id=JOB_ID, revision="a", source="concept"
            )
        )
        == 2
    )
    assert (
        concept_cards(
            result=replace(result, chapters=()),
            job_id=JOB_ID,
            revision="a",
            source="concept",
        )
        == ()
    )


def test_concept_cards_missing_citation_raises_value_error() -> None:
    result = study_fixture(count=1)
    assert (
        len(concept_cards(result=result, job_id=JOB_ID, revision="a", source="concept"))
        == 1
    )
    uncited = replace(result.chapters[0].concepts[0], citations=())
    invalid = replace(
        result, chapters=(replace(result.chapters[0], concepts=(uncited,)),)
    )
    with pytest.raises(ValueError, match="citazione"):
        concept_cards(result=invalid, job_id=JOB_ID, revision="a", source="concept")

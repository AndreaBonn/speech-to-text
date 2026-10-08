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


def test_concept_cards_normalized_term_preserves_dedup_key() -> None:
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


def test_concept_cards_distinct_jobs_have_distinct_dedup_keys() -> None:
    result = study_fixture(count=1)
    original = concept_cards(
        result=result, job_id=JOB_ID, revision="a", source="concept"
    )[0]

    other_job = concept_cards(
        result=result, job_id=OTHER_JOB_ID, revision="a", source="concept"
    )[0]

    assert (
        other_job.dedup_key
        == sha256(f"{OTHER_JOB_ID}:concept:concetto0".encode()).hexdigest()
    )
    assert original.dedup_key != other_job.dedup_key


def test_concept_cards_distinct_sources_have_distinct_dedup_keys() -> None:
    result = study_fixture(count=1)
    original = concept_cards(
        result=result, job_id=JOB_ID, revision="a", source="concept"
    )[0]

    other_source = concept_cards(
        result=result, job_id=JOB_ID, revision="a", source="manual"
    )[0]

    assert (
        other_source.dedup_key
        == sha256(f"{JOB_ID}:manual:concetto0".encode()).hexdigest()
    )
    assert original.dedup_key != other_source.dedup_key


def test_concept_cards_normalized_term_preserves_display_text() -> None:
    result = study_fixture(count=1)
    concept = replace(result.chapters[0].concepts[0], term="  CONCETTO0  ")
    chapter = replace(result.chapters[0], concepts=(concept,))

    normalized = concept_cards(
        result=replace(result, chapters=(chapter,)),
        job_id=JOB_ID,
        revision="a",
        source="concept",
    )[0]

    assert normalized.front == "  CONCETTO0  "


def test_concept_cards_multiple_chapters_preserve_chapter_and_concept_order() -> None:
    result = study_fixture(count=2)
    second = replace(
        result.chapters[0],
        concepts=(replace(result.chapters[0].concepts[0], term="secondo capitolo"),),
    )
    combined = replace(result, chapters=(*result.chapters, second))

    drafts = concept_cards(
        result=combined, job_id=JOB_ID, revision="a", source="concept"
    )

    assert [draft.front for draft in drafts] == [
        "concetto0",
        "concetto1",
        "secondo capitolo",
    ]


def test_concept_cards_empty_chapters_return_no_cards() -> None:
    result = study_fixture(count=1)

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

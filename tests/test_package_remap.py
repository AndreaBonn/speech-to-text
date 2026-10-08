from collections.abc import Iterator, Mapping
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from package_remap_fixtures import exported_request, shared_namespace_content
from pydantic import BaseModel

from sbobina.card_models import (
    CardCreated,
    DocumentAnchor,
    GenerationAnchor,
    LectureAnchor,
)
from sbobina.courses import MAX_COURSE_LABEL_LENGTH, course_key
from sbobina.generation_models import (
    GenerationCitation,
    GenerationRecord,
    GenerationSourceUsed,
)
from sbobina.package_models import PackageCourse
from sbobina.package_remap import PackageRemapError, remap_package
from sbobina.package_remap_types import PackageContent, RemapRequest


@pytest.fixture
def request_data(tmp_path: Path) -> RemapRequest:
    return exported_request(tmp_path=tmp_path)


def strings(value: object) -> Iterator[str]:
    if isinstance(value, (str, UUID)):
        yield str(value)
    elif isinstance(value, BaseModel):
        yield from strings(value=value.model_dump(mode="json"))
    elif is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            yield from strings(value=getattr(value, field.name))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from strings(value=key)
            yield from strings(value=item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from strings(value=item)


def entity_ids(content: PackageContent) -> set[str]:
    return {
        *([content.course_id] if content.course_id else []),
        *(str(job.id) for job in content.jobs),
        *(doc.id for doc in content.documents),
        *(gen.id for gen in content.generations),
        *(card.card_id for card in content.cards),
    }


def assert_references(content: PackageContent) -> None:
    jobs = {str(job.id) for job in content.jobs}
    documents = {doc.id for doc in content.documents}
    generations = {gen.id for gen in content.generations}
    cards = {event.card_id for event in content.cards if isinstance(event, CardCreated)}
    assert all(doc.course_id == content.course_id for doc in content.documents)
    for generation in content.generations:
        assert_generation_references(
            generation=generation, jobs=jobs, documents=documents
        )
    for event in content.cards:
        assert event.card_id in cards
        if isinstance(event, CardCreated):
            match event.anchor:
                case LectureAnchor(job_id=value):
                    assert value in jobs
                case DocumentAnchor(doc_id=value):
                    assert value in documents
                case GenerationAnchor(generation_id=value):
                    assert value in generations


def assert_generation_references(
    generation: GenerationRecord, jobs: set[str], documents: set[str]
) -> None:
    citations = [
        citation for question in generation.questions for citation in question.citations
    ]
    citations += [
        citation
        for section in generation.sections
        for sentence in section.sentences
        for citation in sentence.citations
    ]
    references: tuple[GenerationCitation | GenerationSourceUsed, ...] = (
        *citations,
        *generation.sources,
    )
    for reference in references:
        assert (
            reference.doc_id in documents
            if reference.doc_id
            else reference.job_id in jobs
        )
    assert set(generation.requested_sources.doc_ids) <= documents
    assert set(generation.requested_sources.job_ids) <= jobs


def test_remap_package_operational_ids_and_references_rewritten(
    request_data: RemapRequest,
) -> None:
    old_ids = entity_ids(content=request_data.content)
    before = tuple(strings(value=request_data))
    result = remap_package(request=request_data)
    operational = tuple(strings(value=(result.content, result.course)))
    assert any(old in text for old in old_ids for text in before)
    assert all(old not in text for old in old_ids for text in operational)
    assert tuple(strings(value=request_data)) == before
    new_ids = entity_ids(content=result.content)
    assert len(new_ids) == len(old_ids)
    assert all(
        UUID(value).version == 4 and str(UUID(value)) == value for value in new_ids
    )
    assert_references(content=result.content)
    citations = result.content.generations[0].questions[0].citations
    assert citations[0].passage_id == f"{citations[0].doc_id}:p12:c3"
    assert citations[1].passage_id == f"L{citations[1].job_id}-S42"


def test_remap_package_imported_from_preserves_original_ids(
    request_data: RemapRequest,
) -> None:
    result = remap_package(request=request_data)
    provenance = result.imported_from
    assert provenance.package_id == str(request_data.manifest.package_id)
    tables = provenance.ids
    assert set(tables.courses) == {request_data.content.course_id}
    assert set(tables.jobs) == {str(job.id) for job in request_data.content.jobs}
    assert set(tables.documents) == {doc.id for doc in request_data.content.documents}
    assert set(tables.generations) == {
        gen.id for gen in request_data.content.generations
    }
    assert set(tables.cards) == {card.card_id for card in request_data.content.cards}
    assert entity_ids(content=request_data.content) <= set(strings(value=provenance))
    assert entity_ids(content=result.content) <= set(strings(value=provenance))
    serialized = json.loads(json.dumps(obj=provenance.to_dict()))
    assert serialized["package_id"] == provenance.package_id
    assert serialized["ids"]["jobs"] == dict(tables.jobs)


def test_remap_package_b6_existing_label_gets_manifest_date(
    request_data: RemapRequest,
) -> None:
    original = course_key(label="Diritto privato")
    unchanged = remap_package(request=request_data)
    assert unchanged.course.label == "Diritto privato"
    assert unchanged.course.key == original
    result = remap_package(
        request=replace(request_data, existing_course_keys=frozenset({original}))
    )
    assert result.course.label == "Diritto privato (importato 2026-10-04)"
    assert result.course.key == course_key(label=result.course.label)
    assert result.course.key != original


def test_remap_package_reimport_generates_fresh_ids_and_unique_key(
    request_data: RemapRequest,
) -> None:
    first = remap_package(request=request_data)
    existing = frozenset(
        {first.course.key, course_key(label="Diritto privato (importato 2026-10-04)")}
    )
    second = remap_package(request=replace(request_data, existing_course_keys=existing))
    assert first.course.key in existing
    assert second.course.key not in existing
    assert entity_ids(content=first.content).isdisjoint(
        entity_ids(content=second.content)
    )
    assert first.imported_from.package_id == second.imported_from.package_id


def test_remap_package_dangling_reference_rejected(request_data: RemapRequest) -> None:
    assert_references(content=remap_package(request=request_data).content)
    bad = replace(request_data.content, jobs=())
    with pytest.raises(PackageRemapError, match="Dangling entity reference"):
        remap_package(request=replace(request_data, content=bad))


def test_remap_package_wrong_passage_prefix_rejected(
    request_data: RemapRequest,
) -> None:
    assert_references(content=remap_package(request=request_data).content)
    generation = request_data.content.generations[0]
    question = generation.questions[0]
    bad = replace(question.citations[0], passage_id=f"{uuid4()}:p12:c3")
    generation = replace(generation, questions=(replace(question, citations=(bad,)),))
    content = replace(request_data.content, generations=(generation,))
    with pytest.raises(PackageRemapError, match="passage ID"):
        remap_package(request=replace(request_data, content=content))


def test_remap_package_same_id_in_five_namespaces_stays_distinct(
    request_data: RemapRequest,
) -> None:
    content = shared_namespace_content(content=request_data.content)
    assert len(entity_ids(content=content)) == 1
    result = remap_package(request=replace(request_data, content=content))
    assert len(entity_ids(content=result.content)) == 5
    assert_references(content=result.content)


def test_remap_package_document_course_infers_source_identity(
    request_data: RemapRequest,
) -> None:
    inferred = remap_package(
        request=replace(
            request_data, content=replace(request_data.content, course_id=None)
        )
    )
    assert set(inferred.imported_from.ids.courses) == {request_data.content.course_id}


def test_remap_package_absent_source_course_allocates_identity(
    request_data: RemapRequest,
) -> None:
    populated = remap_package(request=request_data)
    assert populated.imported_from.ids.courses == {
        request_data.content.course_id: populated.course.id
    }

    empty = remap_package(request=replace(request_data, content=PackageContent()))
    assert empty.imported_from.ids.courses == {}
    assert UUID(empty.course.id).version == 4
    assert empty.content.course_id == empty.course.id


@pytest.mark.parametrize("scenario", ["duplicate", "multiple_courses", "missing_card"])
def test_remap_package_inconsistent_entities_rejected(
    request_data: RemapRequest, scenario: str
) -> None:
    assert_references(content=remap_package(request=request_data).content)
    content = request_data.content
    match scenario:
        case "duplicate":
            content = replace(content, jobs=content.jobs * 2)
        case "multiple_courses":
            content = replace(content, course_id=str(uuid4()))
        case "missing_card":
            content = replace(
                content,
                cards=tuple(
                    event
                    for event in content.cards
                    if not isinstance(event, CardCreated)
                ),
            )
    with pytest.raises(PackageRemapError):
        remap_package(request=replace(request_data, content=content))


import json


def with_label(request: RemapRequest, label: str) -> RemapRequest:
    course = PackageCourse(label=label)
    return replace(
        request, manifest=request.manifest.model_copy(update={"course": course})
    )


def test_remap_package_label_strips_control_and_bidi_characters(
    request_data: RemapRequest,
) -> None:
    # A shared package can carry U+202E to make one course name read as another.
    result = remap_package(
        request=with_label(
            request=request_data,
            label="Diritto\N{RIGHT-TO-LEFT OVERRIDE}\x00  privato\n",
        )
    )

    assert result.course.label == "Diritto privato"
    assert result.course.key == course_key(label="Diritto privato")


def test_remap_package_label_over_the_course_limit_is_rejected(
    request_data: RemapRequest,
) -> None:
    within = remap_package(
        request=with_label(request=request_data, label="a" * MAX_COURSE_LABEL_LENGTH)
    )
    assert len(within.course.label) == MAX_COURSE_LABEL_LENGTH

    with pytest.raises(PackageRemapError, match="label"):
        remap_package(
            request=with_label(
                request=request_data, label="a" * (MAX_COURSE_LABEL_LENGTH + 1)
            )
        )


@pytest.mark.parametrize("label", ["\N{RIGHT-TO-LEFT OVERRIDE}\x00", "   "])
def test_remap_package_label_empty_after_cleaning_is_rejected(
    request_data: RemapRequest, label: str
) -> None:
    with pytest.raises(PackageRemapError, match="label"):
        remap_package(request=with_label(request=request_data, label=label))


def test_remap_package_collision_suffix_fits_the_course_limit(
    request_data: RemapRequest,
) -> None:
    label = "b" * MAX_COURSE_LABEL_LENGTH
    request = with_label(request=request_data, label=label)

    result = remap_package(
        request=replace(
            request, existing_course_keys=frozenset({course_key(label=label)})
        )
    )

    assert len(result.course.label) <= MAX_COURSE_LABEL_LENGTH
    assert result.course.label.endswith(" (importato 2026-10-04)")
    assert result.course.key != course_key(label=label)

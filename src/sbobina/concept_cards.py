from hashlib import sha256

from sbobina.card_models import CardDraft, LectureAnchor
from sbobina.study_models import ConceptItem, StudyResult


def _concept_draft(
    item: ConceptItem, job_id: str, revision: str, source: str
) -> CardDraft:
    if not item.citations:
        raise ValueError("Ogni concetto deve avere almeno una citazione")
    citation = item.citations[0]
    identity = f"{job_id}:{source}:{item.term.strip().lower()}"
    return CardDraft(
        front=item.term,
        back=item.explanation,
        source=source,
        anchor=LectureAnchor(
            job_id=job_id,
            revision=revision,
            segment_index=citation.segment_index,
            quote=citation.quote,
        ),
        dedup_key=sha256(identity.encode("utf-8")).hexdigest(),
    )


def concept_cards(
    result: StudyResult, job_id: str, revision: str, source: str
) -> tuple[CardDraft, ...]:
    """Copy concepts using the first citation; deduplicate by stripped lowercase term.

    Parameters
    ----------
    result : StudyResult
        Validated study material, traversed in chapter and concept order.
    job_id : str
        Lecture origin, also the first component of the deduplication key.
    revision : str
        Revision against which the citations were validated.
    source : str
        Card source, the second key component (for example, ``concept``).
    """
    return tuple(
        _concept_draft(item=item, job_id=job_id, revision=revision, source=source)
        for chapter in result.chapters
        for item in chapter.concepts
    )

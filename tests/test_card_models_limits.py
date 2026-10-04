"""MAX_QUOTE_CHARS boundary on LectureAnchor and DocumentAnchor (S1)."""

from collections.abc import Callable
from uuid import uuid4

import pytest

from sbobina.card_models import DocumentAnchor, LectureAnchor

JOB_ID = str(uuid4())
DOC_ID = str(uuid4())


@pytest.mark.parametrize(
    "build",
    [
        lambda quote: LectureAnchor(
            job_id=JOB_ID, revision="r", segment_index=0, quote=quote
        ),
        lambda quote: DocumentAnchor(doc_id=DOC_ID, sha256="s", page=0, quote=quote),
    ],
    ids=["lecture", "document"],
)
def test_anchor_quote_over_max_chars_is_rejected_at_the_boundary(
    build: Callable[[str], LectureAnchor | DocumentAnchor],
) -> None:
    valid = build("x" * 2000)
    assert len(valid.quote) == 2000
    with pytest.raises(ValueError, match="2000 caratteri"):
        build("x" * 2001)

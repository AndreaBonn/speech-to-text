from sbobina.retrieval import DocumentSource, LectureSource, RetrievedPassage
from sbobina.source_citations import (
    DocumentCitation,
    LectureCitation,
    ProposedSourceCitation,
    SourceCitation,
    SourceRejection,
    SourceRejectionReason,
    resolve_citation,
)

DOC_TEXT = "la causa del contratto deve essere lecita e possibile secondo il codice"
LECTURE_TEXT = "il contratto è nullo quando la causa è illecita o impossibile oggi"


def _doc_passage(page: int = 214) -> RetrievedPassage:
    return RetrievedPassage(
        text=DOC_TEXT,
        source=DocumentSource(doc_id="manuale", page=page, chunk=0),
        passage_id="manuale:p214:c0",
    )


def _lecture_passage(start: float = 42.5) -> RetrievedPassage:
    return RetrievedPassage(
        text=LECTURE_TEXT,
        source=LectureSource(job_id="job-1", segment_index=3, start=start),
        passage_id="Ljob-1-S3",
    )


def test_resolve_document_citation_returns_doc_id_and_page() -> None:
    passages = [_doc_passage(page=214)]
    citation = ProposedSourceCitation(label="P1", quote="la causa del contratto")

    result = resolve_citation(passages=passages, citation=citation)

    assert result == SourceCitation(
        passage_id="manuale:p214:c0",
        quote="la causa del contratto",
        location=DocumentCitation(doc_id="manuale", page=214),
    )


def test_resolve_lecture_citation_returns_job_id_and_anchor_timestamp() -> None:
    passages = [_lecture_passage(start=42.5)]
    citation = ProposedSourceCitation(label="P1", quote="la causa è illecita")

    result = resolve_citation(passages=passages, citation=citation)

    assert result == SourceCitation(
        passage_id="Ljob-1-S3",
        quote="la causa è illecita",
        location=LectureCitation(job_id="job-1", timestamp=42.5),
    )


def test_resolve_picks_the_passage_matching_the_label() -> None:
    passages = [_doc_passage(page=1), _lecture_passage()]
    citation = ProposedSourceCitation(label="P2", quote="la causa è illecita")

    result = resolve_citation(passages=passages, citation=citation)

    assert isinstance(result, SourceCitation)
    assert result.passage_id == "Ljob-1-S3"


def test_resolve_rejects_quote_not_found_in_passage() -> None:
    passages = [_doc_passage()]
    citation = ProposedSourceCitation(label="P1", quote="parole mai scritte qui")

    result = resolve_citation(passages=passages, citation=citation)

    assert result == SourceRejection(reason=SourceRejectionReason.QUOTE_NOT_FOUND)


def test_resolve_rejects_passage_not_given_when_label_out_of_range() -> None:
    passages = [_doc_passage()]
    citation = ProposedSourceCitation(label="P5", quote="la causa del contratto")

    result = resolve_citation(passages=passages, citation=citation)

    assert result == SourceRejection(reason=SourceRejectionReason.PASSAGE_NOT_GIVEN)


def test_resolve_rejects_passage_not_given_when_label_is_malformed() -> None:
    passages = [_doc_passage()]
    citation = ProposedSourceCitation(
        label="passaggio-1", quote="la causa del contratto"
    )

    result = resolve_citation(passages=passages, citation=citation)

    assert result == SourceRejection(reason=SourceRejectionReason.PASSAGE_NOT_GIVEN)


def test_resolve_rejects_quote_shorter_than_three_words() -> None:
    passages = [_doc_passage()]
    citation = ProposedSourceCitation(label="P1", quote="la causa")

    result = resolve_citation(passages=passages, citation=citation)

    assert result == SourceRejection(reason=SourceRejectionReason.QUOTE_LENGTH)


def test_resolve_rejects_quote_longer_than_forty_words() -> None:
    passages = [_doc_passage()]
    long_quote = " ".join(["causa"] * 41)
    citation = ProposedSourceCitation(label="P1", quote=long_quote)

    result = resolve_citation(passages=passages, citation=citation)

    assert result == SourceRejection(reason=SourceRejectionReason.QUOTE_LENGTH)


def test_resolve_accepts_quote_at_three_word_boundary() -> None:
    passages = [_doc_passage()]
    citation = ProposedSourceCitation(label="P1", quote="la causa del")

    result = resolve_citation(passages=passages, citation=citation)

    assert isinstance(result, SourceCitation)


def test_resolve_accepts_quote_at_forty_word_boundary() -> None:
    text = " ".join(["causa"] * 40)
    passages = [
        RetrievedPassage(
            text=text,
            source=DocumentSource(doc_id="manuale", page=1, chunk=0),
            passage_id="manuale:p1:c0",
        )
    ]
    citation = ProposedSourceCitation(label="P1", quote=text)

    result = resolve_citation(passages=passages, citation=citation)

    assert isinstance(result, SourceCitation)


def test_resolve_normalizes_case_and_punctuation_like_study_citations() -> None:
    passages = [_doc_passage()]
    citation = ProposedSourceCitation(label="P1", quote="LA CAUSA, del Contratto!")

    result = resolve_citation(passages=passages, citation=citation)

    assert isinstance(result, SourceCitation)


def test_resolve_does_not_match_quote_split_across_non_contiguous_words() -> None:
    passages = [_doc_passage()]
    # Words exist in the passage but not contiguous in this order.
    citation = ProposedSourceCitation(label="P1", quote="contratto causa la")

    result = resolve_citation(passages=passages, citation=citation)

    assert result == SourceRejection(reason=SourceRejectionReason.QUOTE_NOT_FOUND)


def test_resolve_reattributes_a_quote_found_in_another_given_passage() -> None:
    # Measured on qwen3.5:9b (T046): a verbatim quote labelled P7 that only
    # appears in P1. The text is still in the material; only the pointer moves.
    passages = [_lecture_passage(), _doc_passage(page=9)]
    citation = ProposedSourceCitation(label="P2", quote="la causa è illecita")

    result = resolve_citation(passages=passages, citation=citation)

    assert isinstance(result, SourceCitation)
    assert result.passage_id == "Ljob-1-S3"
    assert result.location == LectureCitation(job_id="job-1", timestamp=42.5)


def test_resolve_prefers_the_labelled_passage_when_both_contain_the_quote() -> None:
    other = RetrievedPassage(
        text=DOC_TEXT,
        source=DocumentSource(doc_id="appunti", page=3, chunk=0),
        passage_id="appunti:p3:c0",
    )
    passages = [other, _doc_passage(page=214)]
    citation = ProposedSourceCitation(label="P2", quote="la causa del contratto")

    result = resolve_citation(passages=passages, citation=citation)

    assert isinstance(result, SourceCitation)
    assert result.passage_id == "manuale:p214:c0"

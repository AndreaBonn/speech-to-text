from sbobina.retrieval import DocumentSource, RetrievedPassage
from sbobina.source_sampling import sample_across_sources


def _passage(group: str, index: int, words: int = 1) -> RetrievedPassage:
    return RetrievedPassage(
        text=" ".join(["w"] * words),
        source=DocumentSource(doc_id=group, page=index, chunk=0),
        passage_id=f"{group}:p{index}:c0",
    )


def _doc(passage: RetrievedPassage) -> DocumentSource:
    # Every passage here is built by _passage: narrow the union for mypy.
    assert isinstance(passage.source, DocumentSource)
    return passage.source


def test_sample_across_sources_spreads_picks_over_start_middle_and_end() -> None:
    # 2 sources, 100 one-word passages each. Budget for exactly 6 words
    # forces 3 picks per source: with a spread (non-sequential) traversal
    # order they must land near the start, the middle and the end.
    group_a = [_passage("a", i) for i in range(100)]
    group_b = [_passage("b", i) for i in range(100)]

    sampled = sample_across_sources(groups=[group_a, group_b], budget_words=6)

    assert len(sampled) == 6
    for group in (group_a, group_b):
        indices = sorted(
            _doc(passage).page
            for passage in sampled
            if _doc(passage).doc_id == _doc(group[0]).doc_id
        )
        assert indices[0] <= 5, "manca un prelievo vicino all'inizio"
        assert indices[-1] >= 94, "manca un prelievo vicino alla fine"
        assert any(25 <= i <= 74 for i in indices), "manca un prelievo a metà"


def test_sample_across_sources_limited_budget_fills_without_overflow() -> None:
    group_a = [_passage(group="a", index=i, words=7) for i in range(20)]
    group_b = [_passage(group="b", index=i, words=11) for i in range(20)]

    sampled = sample_across_sources(groups=[group_a, group_b], budget_words=50)

    total_words = sum(len(passage.text.split()) for passage in sampled)
    # Enough passages remain: unused budget must be smaller than the shortest.
    assert 44 <= total_words <= 50


def test_sample_across_sources_output_ordered_by_group_then_source_position() -> None:
    group_a = [_passage("a", i) for i in range(5)]
    group_b = [_passage("b", i) for i in range(5)]

    sampled = sample_across_sources(groups=[group_a, group_b], budget_words=10)

    doc_ids = [_doc(passage).doc_id for passage in sampled]
    pages = [_doc(passage).page for passage in sampled]
    assert doc_ids == sorted(doc_ids)
    # within each doc_id's run, pages increase (reading order).
    a_pages = [
        page for doc_id, page in zip(doc_ids, pages, strict=True) if doc_id == "a"
    ]
    b_pages = [
        page for doc_id, page in zip(doc_ids, pages, strict=True) if doc_id == "b"
    ]
    assert a_pages == sorted(a_pages)
    assert b_pages == sorted(b_pages)


def test_sample_across_sources_skips_empty_groups() -> None:
    group_a: list[RetrievedPassage] = []
    group_b = [_passage("b", i) for i in range(3)]

    sampled = sample_across_sources(groups=[group_a, group_b], budget_words=100)

    assert len(sampled) == 3
    assert all(_doc(passage).doc_id == "b" for passage in sampled)


def test_sample_across_sources_zero_budget_returns_nothing() -> None:
    group_a = [_passage("a", i) for i in range(5)]

    sampled = sample_across_sources(groups=[group_a], budget_words=0)

    assert sampled == []


def test_sample_across_sources_no_groups_returns_nothing() -> None:
    assert sample_across_sources(groups=[], budget_words=100) == []

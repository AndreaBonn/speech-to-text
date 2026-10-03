from sbobina.retrieval import DocumentSource, RetrievedPassage
from sbobina.source_sampling import sample_across_sources


def _passage(group: str, index: int, words: int = 1) -> RetrievedPassage:
    return RetrievedPassage(
        text=" ".join(["w"] * words),
        source=DocumentSource(doc_id=group, page=index, chunk=0),
        passage_id=f"{group}:p{index}:c0",
    )


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
            int(passage.source.page)  # type: ignore[union-attr]
            for passage in sampled
            if passage.source.doc_id == group[0].source.doc_id  # type: ignore[union-attr]
        )
        assert indices[0] <= 5, "manca un prelievo vicino all'inizio"
        assert indices[-1] >= 94, "manca un prelievo vicino alla fine"
        assert any(25 <= i <= 74 for i in indices), "manca un prelievo a metà"


def test_sample_across_sources_never_exceeds_budget() -> None:
    group_a = [_passage("a", i, words=7) for i in range(20)]
    group_b = [_passage("b", i, words=11) for i in range(20)]

    sampled = sample_across_sources(groups=[group_a, group_b], budget_words=50)

    total_words = sum(len(passage.text.split()) for passage in sampled)
    assert total_words <= 50


def test_sample_across_sources_output_ordered_by_group_then_source_position() -> None:
    group_a = [_passage("a", i) for i in range(5)]
    group_b = [_passage("b", i) for i in range(5)]

    sampled = sample_across_sources(groups=[group_a, group_b], budget_words=10)

    doc_ids = [passage.source.doc_id for passage in sampled]  # type: ignore[union-attr]
    pages = [passage.source.page for passage in sampled]  # type: ignore[union-attr]
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
    assert all(passage.source.doc_id == "b" for passage in sampled)  # type: ignore[union-attr]


def test_sample_across_sources_zero_budget_returns_nothing() -> None:
    group_a = [_passage("a", i) for i in range(5)]

    sampled = sample_across_sources(groups=[group_a], budget_words=0)

    assert sampled == []


def test_sample_across_sources_no_groups_returns_nothing() -> None:
    assert sample_across_sources(groups=[], budget_words=100) == []

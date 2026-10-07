"""Reciprocal rank fusion of per-source rankings, shared by retrieval and its eval harness."""

from typing import Protocol

RRF_K = 60


class HasPassageId(Protocol):
    # A read-only property, not a plain attribute: a Protocol attribute is
    # read-write (invariant) by default, which no frozen dataclass can satisfy.
    @property
    def passage_id(self) -> str: ...


def fuse_by_rank[Fusable: HasPassageId](
    rankings: list[list[tuple[float, Fusable]]],
) -> list[Fusable]:
    """Merge per-source rankings by reciprocal rank fusion.

    Each ranking is sorted ascending by score, so a lower score ranks higher
    (bm25() convention; a similarity must be negated before it gets here).
    bm25() scores of the lecture and document tables come from different
    corpus statistics, so only positions are comparable across them.
    See https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf (k = 60).
    """
    fused: dict[str, float] = {}
    passages: dict[str, Fusable] = {}
    for ranking in rankings:
        ordered = sorted(ranking, key=lambda item: item[0])
        for position, (_score, passage) in enumerate(ordered, start=1):
            fused[passage.passage_id] = fused.get(passage.passage_id, 0.0) + 1 / (
                RRF_K + position
            )
            passages[passage.passage_id] = passage
    order = sorted(fused, key=lambda passage_id: -fused[passage_id])
    return [passages[passage_id] for passage_id in order]

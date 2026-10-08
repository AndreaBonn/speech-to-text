import numpy as np
import pytest

from sbobina.embedding_units import DocUnit, LectureUnit
from sbobina.hybrid_eval import (
    content_hash,
    dense_candidates,
    fuse_rankings,
    gold_ref,
    lecture_window_ref,
    pool_top_n,
    pooling_unit,
    ref_to_dict,
    score_lookup,
)
from sbobina.retrieval_metrics import DocumentRef, LectureRef


class TestFuseRankings:
    def test_unit_found_by_both_branches_outranks_single_branch_hit(self) -> None:
        shared = DocUnit(
            passage_id="D1", text="t", ref=DocumentRef(filename="f.pdf", page=1)
        )
        only_bm25 = DocUnit(
            passage_id="D2", text="t", ref=DocumentRef(filename="f.pdf", page=2)
        )
        only_dense = DocUnit(
            passage_id="D3", text="t", ref=DocumentRef(filename="f.pdf", page=3)
        )
        # shared ranks 2nd in bm25, 2nd in dense; only_bm25 ranks 1st in bm25
        # only (never seen by dense); only_dense ranks 1st in dense only.
        bm25 = [(1.0, only_bm25), (2.0, shared)]
        dense = [(1.0, only_dense), (2.0, shared)]

        fused = fuse_rankings(rankings=[bm25, dense])

        assert fused[0] is shared

    def test_fuses_more_than_two_rankings(self) -> None:
        shared = DocUnit(
            passage_id="D1", text="t", ref=DocumentRef(filename="f.pdf", page=1)
        )

        fused = fuse_rankings(
            rankings=[
                [(1.0, shared)],
                [(1.0, shared)],
                [(1.0, shared)],
                [(1.0, shared)],
            ]
        )

        assert fused == [shared]

    def test_empty_rankings_return_empty(self) -> None:
        assert fuse_rankings(rankings=[[], []]) == []


class TestPoolTopN:
    def test_deduplicates_shared_unit_across_systems(self) -> None:
        shared = DocUnit(
            passage_id="D1", text="t", ref=DocumentRef(filename="f.pdf", page=1)
        )
        other = DocUnit(
            passage_id="D2", text="t", ref=DocumentRef(filename="f.pdf", page=2)
        )

        pooled = pool_top_n(
            ranked_by_system={"bm25": [shared, other], "dense": [shared]},
            n=10,
            seed=42,
        )

        assert sorted(unit.passage_id for unit in pooled) == ["D1", "D2"]

    def test_truncates_to_n_per_system(self) -> None:
        units = [
            DocUnit(
                passage_id=f"D{i}",
                text="t",
                ref=DocumentRef(filename="f.pdf", page=i + 1),
            )
            for i in range(5)
        ]

        pooled = pool_top_n(ranked_by_system={"bm25": units}, n=2, seed=0)

        assert len(pooled) == 2

    def test_same_seed_is_deterministic(self) -> None:
        units = [
            DocUnit(
                passage_id=f"D{i}",
                text="t",
                ref=DocumentRef(filename="f.pdf", page=i + 1),
            )
            for i in range(8)
        ]

        first = pool_top_n(ranked_by_system={"bm25": units}, n=8, seed=7)
        second = pool_top_n(ranked_by_system={"bm25": units}, n=8, seed=7)

        assert [u.passage_id for u in first] == [u.passage_id for u in second]


_WINDOW_SPANS = [(0, 1), (2, 3)]
_WINDOW_POSITIONS = {0: 0, 2: 1, 5: 2, 8: 3}
_WINDOW_UNITS = [
    LectureUnit(
        passage_id="Ljob-W0",
        text="t",
        ref=LectureRef(job_id="job", start_s=10, end_s=30),
    ),
    LectureUnit(
        passage_id="Ljob-W1",
        text="t",
        ref=LectureRef(job_id="job", start_s=40, end_s=60),
    ),
]


class TestLectureWindowRef:
    """build_lecture_index's spans/positions/units resolve a production hit."""

    def test_first_segment_of_a_window_resolves_to_its_ref(self) -> None:
        ref = lecture_window_ref(
            segment_index=5,
            positions=_WINDOW_POSITIONS,
            spans=_WINDOW_SPANS,
            units=_WINDOW_UNITS,
        )

        assert ref == LectureRef(job_id="job", start_s=40, end_s=60)

    def test_last_segment_of_the_same_window_resolves_to_the_same_ref(self) -> None:
        ref = lecture_window_ref(
            segment_index=8,
            positions=_WINDOW_POSITIONS,
            spans=_WINDOW_SPANS,
            units=_WINDOW_UNITS,
        )

        assert ref == LectureRef(job_id="job", start_s=40, end_s=60)

    def test_segment_in_the_first_window_resolves_to_a_different_ref(self) -> None:
        ref = lecture_window_ref(
            segment_index=0,
            positions=_WINDOW_POSITIONS,
            spans=_WINDOW_SPANS,
            units=_WINDOW_UNITS,
        )

        assert ref == LectureRef(job_id="job", start_s=10, end_s=30)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            {"kind": "document", "filename": "law.pdf", "page": 7},
            DocumentRef(filename="law.pdf", page=7),
        ),
        (
            {"kind": "lecture", "job_id": "lesson", "start_s": 12.5, "end_s": 29.0},
            LectureRef(job_id="lesson", start_s=12.5, end_s=29.0),
        ),
    ],
)
def test_gold_ref_round_trip_preserves_reference(
    raw: dict[str, object], expected: DocumentRef | LectureRef
) -> None:
    ref = gold_ref(raw=raw)

    assert ref == expected
    assert ref_to_dict(ref=ref) == raw


@pytest.mark.parametrize(
    "expected",
    [
        DocUnit(passage_id="D7", text="", ref=DocumentRef(filename="law.pdf", page=7)),
        LectureUnit(
            passage_id="L2",
            text="",
            ref=LectureRef(job_id="lesson", start_s=12.5, end_s=29.0),
        ),
    ],
)
def test_pooling_unit_pool_entry_reconstructs_empty_text(
    expected: DocUnit | LectureUnit,
) -> None:
    entry = {"passage_id": expected.passage_id, "ref": ref_to_dict(ref=expected.ref)}

    actual = pooling_unit(entry=entry)

    assert actual == expected


def test_dense_candidates_known_vectors_and_empty_units_return_native_scores() -> None:
    parallel = DocUnit(
        passage_id="D1", text="parallel", ref=DocumentRef(filename="f.pdf", page=1)
    )
    orthogonal = DocUnit(
        passage_id="D2", text="orthogonal", ref=DocumentRef(filename="f.pdf", page=2)
    )
    cache = {
        content_hash(text=parallel.text): np.array([1.0, 0.0]),
        content_hash(text=orthogonal.text): np.array([0.0, 1.0]),
    }

    ranked = dense_candidates(
        units=[orthogonal, parallel], cache=cache, query_vector=[1.0, 0.0]
    )
    empty = dense_candidates(units=[], cache=cache, query_vector=[1.0, 0.0])

    assert ranked == [(0.0, orthogonal), (-1.0, parallel)]
    assert min(ranked, key=lambda hit: hit[0]) == (-1.0, parallel)
    assert empty == []


def test_score_lookup_overlapping_rankings_keep_first_score() -> None:
    first = DocUnit(
        passage_id="D1", text="first", ref=DocumentRef(filename="f.pdf", page=1)
    )
    duplicate = DocUnit(passage_id="D1", text="copy", ref=first.ref)
    second = LectureUnit(
        passage_id="L1",
        text="second",
        ref=LectureRef(job_id="job", start_s=0, end_s=10),
    )

    scores = score_lookup(
        rankings=[[], [(2.0, first)], [(-3.0, duplicate), (-1.0, second)]]
    )

    assert scores == {"D1": 2.0, "L1": -1.0}

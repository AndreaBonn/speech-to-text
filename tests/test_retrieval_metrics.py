import pytest

from sbobina.retrieval_metrics import (
    DocumentRef,
    LectureRef,
    RankedPassage,
    count_above,
    first_judged_rank,
    first_relevant_rank,
    is_relevant,
    mean_recall_at_k,
    merge_verdicts,
    mrr_at_k,
    paired_outcome,
    recall_at_k,
)


class TestIsRelevantDocument:
    def test_matches_same_filename_and_page(self) -> None:
        passage = DocumentRef(filename="manuale.pdf", page=12)
        gold = [DocumentRef(filename="manuale.pdf", page=12)]

        assert is_relevant(passage_ref=passage, gold_refs=gold) is True

    def test_rejects_different_filename(self) -> None:
        passage = DocumentRef(filename="manuale.pdf", page=12)
        gold = [DocumentRef(filename="altro.pdf", page=12)]

        assert is_relevant(passage_ref=passage, gold_refs=gold) is False

    def test_rejects_different_page(self) -> None:
        passage = DocumentRef(filename="manuale.pdf", page=12)
        gold = [DocumentRef(filename="manuale.pdf", page=13)]

        assert is_relevant(passage_ref=passage, gold_refs=gold) is False

    def test_empty_gold_refs_is_not_relevant(self) -> None:
        passage = DocumentRef(filename="manuale.pdf", page=12)

        assert is_relevant(passage_ref=passage, gold_refs=[]) is False


class TestIsRelevantLecture:
    def test_matches_full_overlap(self) -> None:
        passage = LectureRef(job_id="job-1", start_s=10.0, end_s=20.0)
        gold = [LectureRef(job_id="job-1", start_s=12.0, end_s=18.0)]

        assert is_relevant(passage_ref=passage, gold_refs=gold) is True

    def test_touching_boundary_counts_as_overlap(self) -> None:
        passage = LectureRef(job_id="job-1", start_s=10.0, end_s=20.0)
        gold = [LectureRef(job_id="job-1", start_s=20.0, end_s=30.0)]

        assert is_relevant(passage_ref=passage, gold_refs=gold) is True

    def test_adjacent_with_gap_does_not_count(self) -> None:
        passage = LectureRef(job_id="job-1", start_s=10.0, end_s=20.0)
        gold = [LectureRef(job_id="job-1", start_s=20.1, end_s=30.0)]

        assert is_relevant(passage_ref=passage, gold_refs=gold) is False

    def test_rejects_different_job_id(self) -> None:
        passage = LectureRef(job_id="job-1", start_s=10.0, end_s=20.0)
        gold = [LectureRef(job_id="job-2", start_s=10.0, end_s=20.0)]

        assert is_relevant(passage_ref=passage, gold_refs=gold) is False


class TestIsRelevantCrossType:
    def test_document_passage_never_matches_lecture_gold(self) -> None:
        passage = DocumentRef(filename="manuale.pdf", page=12)
        gold = [LectureRef(job_id="job-1", start_s=0.0, end_s=100.0)]

        assert is_relevant(passage_ref=passage, gold_refs=gold) is False

    def test_lecture_passage_never_matches_document_gold(self) -> None:
        passage = LectureRef(job_id="job-1", start_s=0.0, end_s=100.0)
        gold = [DocumentRef(filename="manuale.pdf", page=12)]

        assert is_relevant(passage_ref=passage, gold_refs=gold) is False


class TestFirstRelevantRank:
    def test_returns_one_based_rank_of_first_relevant(self) -> None:
        gold = [DocumentRef(filename="manuale.pdf", page=12)]
        ranked = [
            DocumentRef(filename="altro.pdf", page=1),
            DocumentRef(filename="manuale.pdf", page=12),
            DocumentRef(filename="terzo.pdf", page=5),
        ]

        assert first_relevant_rank(ranked_refs=ranked, gold_refs=gold) == 2

    def test_no_relevant_passage_returns_none(self) -> None:
        gold = [DocumentRef(filename="manuale.pdf", page=12)]
        ranked = [DocumentRef(filename="altro.pdf", page=1)]

        assert first_relevant_rank(ranked_refs=ranked, gold_refs=gold) is None

    def test_empty_ranked_refs_returns_none(self) -> None:
        gold = [DocumentRef(filename="manuale.pdf", page=12)]

        assert first_relevant_rank(ranked_refs=[], gold_refs=gold) is None


class TestRecallAtK:
    def test_rank_within_k_is_hit(self) -> None:
        assert recall_at_k(rank=3, k=5) == 1.0

    def test_rank_beyond_k_is_miss(self) -> None:
        assert recall_at_k(rank=8, k=5) == 0.0

    def test_rank_none_is_miss(self) -> None:
        assert recall_at_k(rank=None, k=5) == 0.0

    def test_rank_equal_to_k_is_hit(self) -> None:
        assert recall_at_k(rank=5, k=5) == 1.0


class TestMeanRecallAtK:
    def test_averages_hits_and_misses(self) -> None:
        ranks: list[int | None] = [3, 8, None, 1]

        result = mean_recall_at_k(ranks=ranks, k=5)

        assert result == 0.5

    def test_empty_ranks_returns_zero(self) -> None:
        assert mean_recall_at_k(ranks=[], k=5) == 0.0


class TestMrrAtK:
    def test_rank_one_is_full_score(self) -> None:
        assert mrr_at_k(rank=1, k=8) == 1.0

    def test_rank_three_is_reciprocal(self) -> None:

        assert mrr_at_k(rank=3, k=8) == pytest.approx(0.333, abs=1e-3)

    def test_rank_beyond_k_is_zero(self) -> None:
        assert mrr_at_k(rank=10, k=8) == 0.0

    def test_rank_none_is_zero(self) -> None:
        assert mrr_at_k(rank=None, k=8) == 0.0


class TestPairedOutcome:
    def test_system_hit_baseline_miss_is_win(self) -> None:
        result = paired_outcome(baseline_rank=10, system_rank=3, k=8)

        assert result == "win"

    def test_baseline_hit_system_miss_is_loss(self) -> None:
        result = paired_outcome(baseline_rank=3, system_rank=10, k=8)

        assert result == "loss"

    def test_both_hit_is_tie(self) -> None:
        result = paired_outcome(baseline_rank=2, system_rank=5, k=8)

        assert result == "tie"

    def test_both_miss_is_tie(self) -> None:
        result = paired_outcome(baseline_rank=None, system_rank=20, k=8)

        assert result == "tie"


class TestCountAbove:
    def test_counts_scores_at_or_above_threshold(self) -> None:
        scores = [0.9, 0.5, 0.75, 0.3]

        assert count_above(scores=scores, threshold=0.75) == 2

    def test_score_exactly_at_threshold_counts(self) -> None:
        assert count_above(scores=[0.5], threshold=0.5) == 1

    def test_empty_scores_returns_zero(self) -> None:
        assert count_above(scores=[], threshold=0.5) == 0

    def test_no_scores_above_threshold_returns_zero(self) -> None:
        assert count_above(scores=[0.1, 0.2], threshold=0.5) == 0

    def test_all_scores_above_threshold_returns_full_count(self) -> None:
        scores = [0.9, 0.8, 0.95]

        assert count_above(scores=scores, threshold=0.5) == len(scores)


PAGE_1 = DocumentRef(filename="a.pdf", page=1)
PAGE_2 = DocumentRef(filename="a.pdf", page=2)
PAGE_3 = DocumentRef(filename="a.pdf", page=3)


class TestFirstJudgedRank:
    def test_passage_voted_2_counts_as_relevant(self) -> None:
        ranked = [
            RankedPassage(passage_id="p1", ref=PAGE_1),
            RankedPassage(passage_id="p2", ref=PAGE_2),
        ]

        rank = first_judged_rank(ranked=ranked, gold_refs=[], votes={"p2": 2})

        assert rank == 2

    def test_passage_voted_1_does_not_count(self) -> None:
        ranked = [RankedPassage(passage_id="p1", ref=PAGE_1)]

        assert first_judged_rank(ranked=ranked, gold_refs=[], votes={"p1": 1}) is None

    def test_gold_reference_counts_without_a_vote(self) -> None:
        ranked = [
            RankedPassage(passage_id="p1", ref=PAGE_1),
            RankedPassage(passage_id="p3", ref=PAGE_3),
        ]

        assert first_judged_rank(ranked=ranked, gold_refs=[PAGE_3], votes={}) == 2

    def test_earliest_of_vote_and_gold_wins(self) -> None:
        ranked = [
            RankedPassage(passage_id="p1", ref=PAGE_1),
            RankedPassage(passage_id="p3", ref=PAGE_3),
        ]

        rank = first_judged_rank(ranked=ranked, gold_refs=[PAGE_3], votes={"p1": 2})

        assert rank == 1


class TestMergeVerdicts:
    def test_later_file_adds_votes_for_the_same_question(self) -> None:
        merged = merge_verdicts(
            verdict_files=[{"q1": {"p1": 2}}, {"q1": {"p2": 0}, "q2": {"p9": 1}}]
        )

        assert merged == {"q1": {"p1": 2, "p2": 0}, "q2": {"p9": 1}}

    def test_does_not_mutate_its_inputs(self) -> None:
        first = {"q1": {"p1": 2}}

        merge_verdicts(verdict_files=[first, {"q1": {"p2": 0}}])

        assert first == {"q1": {"p1": 2}}


class TestRefInvariants:
    def test_document_page_zero_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="page"):
            DocumentRef(filename="a.pdf", page=0)

    def test_document_page_one_is_accepted(self) -> None:
        assert DocumentRef(filename="a.pdf", page=1).page == 1

    def test_lecture_interval_ending_before_it_starts_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="interval"):
            LectureRef(job_id="j", start_s=10.0, end_s=5.0)

    def test_lecture_negative_start_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="interval"):
            LectureRef(job_id="j", start_s=-1.0, end_s=5.0)

    def test_lecture_zero_length_interval_is_accepted(self) -> None:
        assert LectureRef(job_id="j", start_s=5.0, end_s=5.0).end_s == 5.0

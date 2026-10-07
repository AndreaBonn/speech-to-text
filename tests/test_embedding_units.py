from sbobina.embedding_units import (
    LectureUnit,
    aggregate_lecture_hits_to_windows,
    build_lecture_units,
    content_hash,
    segment_positions,
)
from sbobina.retrieval_metrics import LectureRef
from sbobina.search_text import Passage


def make_passage(segment_index: int, start: float, text: str) -> Passage:
    return Passage(segment_index=segment_index, start=start, text=text)


class TestContentHash:
    def test_same_text_same_hash(self) -> None:
        assert content_hash("il possesso e' un diritto") == content_hash(
            "il possesso e' un diritto"
        )

    def test_different_text_different_hash(self) -> None:
        assert content_hash("testo a") != content_hash("testo b")

    def test_returns_hex_sha256(self) -> None:
        digest = content_hash("x")
        assert len(digest) == 64
        int(digest, 16)  # raises ValueError if not hex


class TestSegmentPositions:
    def test_maps_segment_index_to_list_position(self) -> None:
        segments = [make_passage(0, 0.0, "a"), make_passage(1, 1.0, "b")]

        assert segment_positions(segments=segments) == {0: 0, 1: 1}

    def test_handles_gaps_from_filtered_empty_segments(self) -> None:
        # passages_from_transcript drops empty-text segments, so
        # segment_index (original transcript position) and list position
        # diverge once a gap happened upstream.
        segments = [make_passage(0, 0.0, "a"), make_passage(2, 2.0, "b")]

        assert segment_positions(segments=segments) == {0: 0, 2: 1}


class TestBuildLectureUnits:
    def test_six_hundred_words_form_three_contiguous_units(self) -> None:
        segments = [
            make_passage(segment_index=i, start=float(i), text="word " * 50)
            for i in range(12)
        ]
        spans, units = build_lecture_units(
            job_id="job-1",
            segments=segments,
            segment_ends=[float(i + 1) for i in range(12)],
            window_words=250,
        )

        assert spans == [(0, 4), (5, 9), (10, 11)]
        assert [len(unit.text.split()) for unit in units] == [250, 250, 100]
        assert [(unit.ref.start_s, unit.ref.end_s) for unit in units] == [
            (0.0, 5.0),
            (5.0, 10.0),
            (10.0, 12.0),
        ]

    def test_single_short_transcript_is_one_window(self) -> None:
        segments = [make_passage(0, 0.0, "il possesso e' un diritto reale")]
        ends = [5.0]

        spans, units = build_lecture_units(
            job_id="job-1", segments=segments, segment_ends=ends, window_words=250
        )

        assert spans == [(0, 0)]
        assert len(units) == 1
        assert units[0].passage_id == "Ljob-1-W0"
        assert units[0].text == "il possesso e' un diritto reale"
        assert units[0].ref == LectureRef(job_id="job-1", start_s=0.0, end_s=5.0)

    def test_two_windows_use_segment_ends_not_starts(self) -> None:
        # 3 words per segment, window_words=5 closes a span as soon as it
        # reaches the target: segment 0 (3) + segment 1 (3) = 6 >= 5.
        segments = [
            make_passage(0, 0.0, "aaa bbb ccc"),
            make_passage(1, 1.0, "ddd eee fff"),
            make_passage(2, 2.0, "ggg hhh iii"),
        ]
        ends = [0.9, 1.9, 2.9]

        spans, units = build_lecture_units(
            job_id="job-1", segments=segments, segment_ends=ends, window_words=5
        )

        assert spans == [(0, 1), (2, 2)]
        assert units[0].ref == LectureRef(job_id="job-1", start_s=0.0, end_s=1.9)
        assert units[1].ref == LectureRef(job_id="job-1", start_s=2.0, end_s=2.9)
        assert units[0].passage_id == "Ljob-1-W0"
        assert units[1].passage_id == "Ljob-1-W1"


class TestAggregateLectureHitsToWindows:
    def _units(self) -> tuple[list[tuple[int, int]], list[LectureUnit]]:
        spans = [(0, 1), (2, 2)]
        units = [
            LectureUnit(
                passage_id="Ljob-1-W0",
                text="w0",
                ref=LectureRef(job_id="job-1", start_s=0.0, end_s=1.9),
            ),
            LectureUnit(
                passage_id="Ljob-1-W1",
                text="w1",
                ref=LectureRef(job_id="job-1", start_s=2.0, end_s=2.9),
            ),
        ]
        return spans, units

    def test_two_hits_in_same_window_keep_best_score(self) -> None:
        spans, units = self._units()
        positions = {0: 0, 1: 1}  # segment_index -> position, both in window 0

        result = aggregate_lecture_hits_to_windows(
            hits=[(-0.5, 0), (-2.0, 1)],
            segment_positions=positions,
            spans=spans,
            units=units,
        )

        assert result == [(-2.0, units[0])]

    def test_hits_in_different_windows_both_kept(self) -> None:
        spans, units = self._units()
        positions = {0: 0, 2: 2}

        result = aggregate_lecture_hits_to_windows(
            hits=[(-1.0, 0), (-1.0, 2)],
            segment_positions=positions,
            spans=spans,
            units=units,
        )

        assert sorted(result, key=lambda item: item[1].passage_id) == [
            (-1.0, units[0]),
            (-1.0, units[1]),
        ]

    def test_hit_on_unmapped_segment_index_is_dropped(self) -> None:
        spans, units = self._units()
        positions = {0: 0}

        result = aggregate_lecture_hits_to_windows(
            hits=[(-1.0, 99)],
            segment_positions=positions,
            spans=spans,
            units=units,
        )

        assert result == []

    def test_empty_hits_returns_empty(self) -> None:
        spans, units = self._units()

        result = aggregate_lecture_hits_to_windows(
            hits=[], segment_positions={}, spans=spans, units=units
        )

        assert result == []

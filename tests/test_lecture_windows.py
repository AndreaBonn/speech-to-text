from sbobina.lecture_windows import expand_lecture_windows
from sbobina.retrieval import DocumentSource, LectureSource, RetrievedPassage
from sbobina.search_text import Passage


def _segments(
    count: int, words_per_segment: int, *, start_index: int = 0
) -> list[Passage]:
    text = " ".join(["word"] * words_per_segment)
    return [
        Passage(segment_index=start_index + i, start=float(i), text=text)
        for i in range(count)
    ]


def _lecture_hit(job_id: str, segment_index: int, text: str) -> RetrievedPassage:
    return RetrievedPassage(
        text=text,
        source=LectureSource(job_id=job_id, segment_index=segment_index, start=0.0),
        passage_id=f"L{job_id}-S{segment_index}",
    )


def test_expand_window_contains_center_segment_within_target_range() -> None:
    # 60 segments of 20 words each, center at index 30 has only 12 words: far
    # enough from both edges that growth stops on the word target, not a
    # truncated transcript.
    segments = _segments(count=60, words_per_segment=20)
    segments[30] = Passage(segment_index=30, start=30.0, text=" ".join(["w"] * 12))
    hit = _lecture_hit(job_id="job-1", segment_index=30, text=segments[30].text)

    windows = expand_lecture_windows(
        hits=[hit], segments_by_job={"job-1": segments}, window_words=250
    )

    assert len(windows) == 1
    word_count = len(windows[0].text.split())
    assert 230 <= word_count <= 270
    assert segments[30].text in windows[0].text


def test_expand_window_keeps_citation_anchored_to_matched_segment() -> None:
    segments = _segments(count=60, words_per_segment=20)
    hit = _lecture_hit(job_id="job-1", segment_index=30, text=segments[30].text)

    windows = expand_lecture_windows(
        hits=[hit], segments_by_job={"job-1": segments}, window_words=250
    )

    assert windows[0].source == hit.source
    assert windows[0].passage_id == hit.passage_id


def test_expand_window_merges_two_nearby_segments_into_one() -> None:
    # Transcript too short (150 words) to ever reach the 250-word target: both
    # hits grow to the full transcript and must collapse to one window.
    segments = _segments(count=15, words_per_segment=10)
    hits = [
        _lecture_hit(job_id="job-1", segment_index=5, text=segments[5].text),
        _lecture_hit(job_id="job-1", segment_index=7, text=segments[7].text),
    ]

    windows = expand_lecture_windows(
        hits=hits, segments_by_job={"job-1": segments}, window_words=250
    )

    assert len(windows) == 1


def test_expand_window_truncates_at_transcript_start_without_error() -> None:
    segments = _segments(count=15, words_per_segment=10)
    hit = _lecture_hit(job_id="job-1", segment_index=0, text=segments[0].text)

    windows = expand_lecture_windows(
        hits=[hit], segments_by_job={"job-1": segments}, window_words=250
    )

    assert len(windows) == 1
    assert segments[0].text in windows[0].text
    assert len(windows[0].text.split()) == 150


def test_expand_window_truncates_at_transcript_end_without_error() -> None:
    segments = _segments(count=15, words_per_segment=10)
    hit = _lecture_hit(job_id="job-1", segment_index=14, text=segments[14].text)

    windows = expand_lecture_windows(
        hits=[hit], segments_by_job={"job-1": segments}, window_words=250
    )

    assert len(windows) == 1
    assert segments[14].text in windows[0].text


def test_expand_window_passes_document_hits_through_unchanged() -> None:
    doc_hit = RetrievedPassage(
        text="la causa del contratto",
        source=DocumentSource(doc_id="doc-1", page=1, chunk=0),
        passage_id="doc-1:p1:c0",
    )

    windows = expand_lecture_windows(
        hits=[doc_hit], segments_by_job={}, window_words=250
    )

    assert windows == [doc_hit]


def test_expand_window_returns_hit_unchanged_when_lecture_has_no_segments() -> None:
    hit = _lecture_hit(job_id="job-missing", segment_index=0, text="qualche parola")

    windows = expand_lecture_windows(hits=[hit], segments_by_job={}, window_words=250)

    assert windows == [hit]


def test_expand_window_returns_hit_unchanged_when_segment_index_not_found() -> None:
    segments = _segments(count=5, words_per_segment=10, start_index=100)
    hit = _lecture_hit(job_id="job-1", segment_index=0, text="qualche parola")

    windows = expand_lecture_windows(
        hits=[hit], segments_by_job={"job-1": segments}, window_words=250
    )

    assert windows == [hit]


def test_expand_window_empty_hits_returns_empty_list() -> None:
    assert expand_lecture_windows(hits=[], segments_by_job={}, window_words=250) == []


def test_expand_window_bridge_merges_every_window_it_touches() -> None:
    # Windows around segments 2 and 20 stay apart; the window around 11 touches
    # both, so all three must collapse into one passage, anchored on the best hit.
    segments = {
        "j": [Passage(segment_index=i, start=float(i), text=f"w{i}") for i in range(30)]
    }
    hits = [
        _lecture_hit(job_id="j", segment_index=2, text="w2"),
        _lecture_hit(job_id="j", segment_index=20, text="w20"),
        _lecture_hit(job_id="j", segment_index=11, text="w11"),
    ]

    windows = expand_lecture_windows(
        hits=hits, segments_by_job=segments, window_words=9
    )

    assert len(windows) == 1
    assert windows[0].passage_id == hits[0].passage_id
    assert windows[0].text.split() == [f"w{i}" for i in range(25)]

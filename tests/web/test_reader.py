from dataclasses import replace

import pytest
from conftest import make_segment, make_transcript, make_word

from sbobina.render import RenderOptions, group_paragraphs, render_markdown
from sbobina.web.reader import WordView, build_paragraphs, build_review_points

OPTIONS = RenderOptions(
    uncertain_threshold=0.7, paragraph_gap_s=2.0, paragraph_max_s=120.0
)


def test_build_paragraphs_threshold_and_correction_preserves_word_fields() -> None:
    words = [
        replace(make_word(" cloroplasto", 0.0, 0.5), corrected_from="clorofilla"),
        make_word(" chiaro", 0.4, 0.7),
    ]
    transcript = make_transcript([make_segment(words)])

    paragraphs = build_paragraphs(transcript=transcript, options=OPTIONS)

    assert paragraphs == [
        [
            WordView(
                index=0,
                segment=0,
                start=0.0,
                end=0.4,
                text=" cloroplasto",
                uncertain=True,
                most_uncertain=False,
                corrected_from="clorofilla",
            ),
            WordView(
                index=1,
                segment=0,
                start=0.4,
                end=0.8,
                text=" chiaro",
                uncertain=False,
                most_uncertain=False,
                corrected_from=None,
            ),
        ]
    ]


def test_build_paragraphs_most_uncertain_is_stricter_subset_of_uncertain() -> None:
    # threshold 0.7 -> uncertain below 0.7; most_uncertain below 0.35 (half).
    words = [
        make_word(" chiarissima", 0.0, 0.9),  # confident: neither flag
        make_word(" dubbia", 0.4, 0.5),  # below 0.7, not below 0.35
        make_word(" oscura", 0.8, 0.2),  # below both
    ]
    transcript = make_transcript([make_segment(words)])

    [paragraph] = build_paragraphs(transcript=transcript, options=OPTIONS)

    assert [(w.uncertain, w.most_uncertain) for w in paragraph] == [
        (False, False),
        (True, False),
        (True, True),
    ]


@pytest.mark.parametrize(
    "starts", [(0.0, 1.0, 10.0), tuple(i * 1.5 for i in range(100))]
)
def test_build_paragraphs_gap_and_duration_match_renderer(
    starts: tuple[float, ...],
) -> None:
    transcript = make_transcript(
        [
            make_segment([make_word(f" p{index}", start)])
            for index, start in enumerate(starts)
        ]
    )

    paragraphs = build_paragraphs(transcript=transcript, options=OPTIONS)
    expected = group_paragraphs(segments=transcript.segments, options=OPTIONS)

    assert len(paragraphs) == 2
    assert [[word.text for word in paragraph] for paragraph in paragraphs] == [
        [word.text for segment in paragraph for word in segment.words]
        for paragraph in expected
    ]


def test_build_review_points_consecutive_words_limits_context_to_four() -> None:
    words = [
        make_word(f" p{i}", float(i), 0.5 if i in (5, 6) else 0.99) for i in range(12)
    ]
    transcript = make_transcript([make_segment(words)])

    points = build_review_points(transcript=transcript, threshold=0.7)

    assert len(points) == 1
    point = points[0]
    assert (point.start, point.before, point.text, point.after) == (
        5.0,
        "p1 p2 p3 p4",
        "p5 p6",
        "p7 p8 p9 p10",
    )
    assert "… p1 p2 p3 p4 **p5 p6** p7 p8 p9 p10 …" in render_markdown(
        transcript=transcript, options=OPTIONS
    )


def test_build_review_points_edge_spans_and_confident_words_returns_expected() -> None:
    transcript = make_transcript(
        [
            make_segment(
                [
                    make_word(" primo", 0.0, 0.5),
                    make_word(" certo", 0.4, 0.7),
                    make_word(" ultimo", 0.8, 0.5),
                ]
            )
        ]
    )

    points = build_review_points(transcript=transcript, threshold=0.7)

    assert [(p.start, p.before, p.text, p.after) for p in points] == [
        (0.0, "", "primo", "certo ultimo"),
        (0.8, "primo certo", "ultimo", ""),
    ]
    assert build_review_points(transcript=transcript, threshold=0.5) == []


def test_build_paragraphs_empty_transcript_returns_empty_views() -> None:
    transcript = make_transcript([make_segment([make_word(" parola", 0.0)])])
    empty = replace(transcript, segments=(), duration=0.0)

    assert len(build_paragraphs(transcript=transcript, options=OPTIONS)) == 1
    assert build_paragraphs(transcript=empty, options=OPTIONS) == []
    assert build_review_points(transcript=empty, threshold=0.7) == []


def test_build_paragraphs_indexes_words_across_paragraphs() -> None:
    transcript = make_transcript(
        [
            make_segment([make_word(" a", 0.0), make_word(" b", 0.4)]),
            make_segment([make_word(" c", 10.0)]),
        ]
    )

    paragraphs = build_paragraphs(transcript=transcript, options=OPTIONS)

    assert [[w.index for w in p] for p in paragraphs] == [[0, 1], [2]]


def test_build_paragraphs_segment_index_counts_segments_not_words() -> None:
    transcript = make_transcript(
        [
            make_segment([make_word(" uno", 0.0), make_word(" due", 0.4)]),
            make_segment([make_word(" tre", 1.0), make_word(" quattro", 1.4)]),
        ]
    )

    paragraphs = build_paragraphs(transcript=transcript, options=OPTIONS)

    words = [word for paragraph in paragraphs for word in paragraph]
    assert [(word.index, word.segment) for word in words] == [
        (0, 0),
        (1, 0),
        (2, 1),
        (3, 1),
    ]


def test_build_review_points_flag_spans_with_a_most_uncertain_word() -> None:
    """R1: a point is "most doubtful" when one of its words is below half the
    job threshold, so the reader can hide the milder ones."""
    words = [
        make_word(" chiara", 0.0, 0.95),
        make_word(" dubbia", 2.0, 0.5),
        make_word(" chiara", 4.0, 0.95),
        make_word(" oscura", 30.0, 0.2),
    ]
    transcript = make_transcript([make_segment(words)])

    points = build_review_points(transcript=transcript, threshold=0.7)

    assert [(point.text, point.most_uncertain) for point in points] == [
        ("dubbia", False),
        ("oscura", True),
    ]

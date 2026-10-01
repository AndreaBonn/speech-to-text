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
                start=0.0,
                end=0.4,
                text=" cloroplasto",
                uncertain=True,
                corrected_from="clorofilla",
            ),
            WordView(
                index=1,
                start=0.4,
                end=0.8,
                text=" chiaro",
                uncertain=False,
                corrected_from=None,
            ),
        ]
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

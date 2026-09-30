from conftest import make_segment, make_transcript, make_word

from sbobina.models import Word
from sbobina.render import (
    RenderOptions,
    find_uncertain_spans,
    format_timestamp,
    mark_correction,
    mark_word,
    render_markdown,
)

OPTIONS = RenderOptions(
    uncertain_threshold=0.7, paragraph_gap_s=2.0, paragraph_max_s=120.0
)


def test_format_timestamp_uses_hours_minutes_seconds() -> None:
    assert format_timestamp(3725.9) == "01:02:05"


def test_format_timestamp_zero() -> None:
    assert format_timestamp(0.0) == "00:00:00"


def test_mark_word_keeps_prefix_and_trailing_punctuation_outside_marker() -> None:
    assert mark_word(" Sennberg,") == " [?Sennberg?],"


def test_mark_word_keeps_leading_apostrophe_outside_marker() -> None:
    assert mark_word("'equazione") == "'[?equazione?]"


def test_find_uncertain_spans_groups_consecutive_low_confidence_words() -> None:
    words = (
        make_word(" Noether", 0.0),
        make_word(" con", 0.4, 0.49),
        make_word(" leghe", 0.8, 0.66),
        make_word(" simmetrie", 1.2),
        make_word(" Sennberg", 1.6, 0.4),
    )

    spans = find_uncertain_spans(words, threshold=0.7)

    assert spans == [(1, 3), (4, 5)]


def test_find_uncertain_spans_empty_when_all_confident() -> None:
    words = (make_word(" tutto", 0.0), make_word(" chiaro", 0.4))

    assert find_uncertain_spans(words, threshold=0.7) == []


def test_render_marks_uncertain_words_in_body_and_review_list() -> None:
    transcript = make_transcript(
        [
            make_segment(
                [make_word(" principio", 0.0), make_word(" Sennberg,", 0.5, 0.49)]
            )
        ]
    )

    markdown = render_markdown(transcript, OPTIONS)

    assert "[00:00:00] principio [?Sennberg?]," in markdown
    assert "- [00:00:00] … principio **Sennberg,** …" in markdown
    assert "parole incerte: 1" in markdown


def test_render_without_uncertain_words_says_nothing_to_review() -> None:
    transcript = make_transcript([make_segment([make_word(" chiaro", 0.0)])])

    markdown = render_markdown(transcript, OPTIONS)

    assert "[?" not in markdown
    assert "Nessun punto sotto la soglia" in markdown
    assert "[00:00:00] chiaro" in markdown


def test_render_starts_new_paragraph_after_long_pause() -> None:
    transcript = make_transcript(
        [
            make_segment([make_word(" primo", 0.0)]),
            make_segment([make_word(" subito", 1.0)]),
            make_segment([make_word(" dopo", 10.0)]),
        ]
    )

    markdown = render_markdown(transcript, OPTIONS)

    assert "[00:00:00] primo subito\n\n[00:00:10] dopo" in markdown


def test_render_splits_paragraph_longer_than_max_duration() -> None:
    segments = [make_segment([make_word(f" p{i}", i * 1.5)]) for i in range(100)]
    transcript = make_transcript(segments)

    markdown = render_markdown(transcript, OPTIONS)

    assert "[00:00:00] p0" in markdown
    assert "[00:02:00] p80" in markdown


def test_mark_word_keeps_elision_apostrophe_inside_marker() -> None:
    assert mark_word(" po'") == " [?po'?]"


def test_render_shows_correction_with_original_as_superscript() -> None:
    corrected = Word(
        start=0.5, end=0.9, text=" lesione,", probability=1.0, corrected_from="legione"
    )
    transcript = make_transcript([make_segment([make_word(" la", 0.0), corrected])])

    markdown = render_markdown(transcript, OPTIONS)

    assert "[00:00:00] la lesione<sup>legione</sup>," in markdown


def test_mark_correction_escapes_html_in_what_whisper_heard() -> None:
    assert mark_correction(" lesione", "a<b") == " lesione<sup>a&lt;b</sup>"

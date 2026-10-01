from dataclasses import replace

from conftest import make_segment, make_transcript, make_word

from sbobina.book import book_paragraphs, render_book_text
from sbobina.render import RenderOptions

OPTIONS = RenderOptions(
    uncertain_threshold=0.7, paragraph_gap_s=2.0, paragraph_max_s=120.0
)


def test_book_paragraphs_drops_timestamps_and_marks() -> None:
    first = make_segment(
        [
            make_word(" Il", 0.0, probability=0.1),
            replace(make_word(" possesso", 0.4), corrected_from="processo"),
            make_word(" è", 0.8),
            make_word(" un", 1.2),
            make_word(" fatto.", 1.6),
        ]
    )
    second = make_segment([make_word(" Poi", 10.0), make_word(" altro.", 10.4)])
    transcript = make_transcript([first, second])

    paragraphs = book_paragraphs(transcript=transcript, options=OPTIONS)

    assert paragraphs == ["Il possesso è un fatto.", "Poi altro."]


def test_book_paragraphs_collapses_inner_whitespace() -> None:
    words = [make_word("  Uno", 0.0), make_word("   due", 0.4)]
    transcript = make_transcript([make_segment(words)])

    assert book_paragraphs(transcript=transcript, options=OPTIONS) == ["Uno due"]


def test_book_paragraphs_skips_paragraphs_with_only_whitespace() -> None:
    blank = make_segment([make_word(" ", 0.0)])
    text = make_segment([make_word(" Ciao.", 10.0)])
    transcript = make_transcript([blank, text])

    assert book_paragraphs(transcript=transcript, options=OPTIONS) == ["Ciao."]


def test_render_book_text_title_then_blank_line_separated_paragraphs() -> None:
    text = render_book_text(title="Diritto privato", paragraphs=["Primo.", "Secondo."])

    assert text == "Diritto privato\n\nPrimo.\n\nSecondo.\n"


def test_render_book_text_without_paragraphs_keeps_title() -> None:
    assert render_book_text(title="Vuota", paragraphs=[]) == "Vuota\n"


def test_book_paragraphs_keeps_tokens_without_leading_space_attached() -> None:
    words = [make_word(" l", 0.0), make_word("'impressione", 0.4), make_word(".", 0.8)]
    transcript = make_transcript([make_segment(words)])

    assert book_paragraphs(transcript=transcript, options=OPTIONS) == ["l'impressione."]

from sbobina.document_passages import (
    LONG_PAGE_WORD_LIMIT,
    WINDOW_OVERLAP_WORDS,
    WINDOW_WORD_COUNT,
    DocumentPassage,
    chunk_document_pages,
)
from sbobina.extracted_text import Page


def _page(text: str, no_text: bool = False) -> Page:
    return Page(text=text, no_text=no_text)


def test_short_page_becomes_a_single_passage_numbered_from_one() -> None:
    passages = chunk_document_pages(doc_id="doc1", pages=(_page("una pagina breve"),))
    assert passages == [
        DocumentPassage(
            passage_id="doc1:p1:c0", page=1, chunk=0, text="una pagina breve"
        )
    ]


def test_page_at_the_word_limit_is_not_split() -> None:
    text = " ".join(f"parola{i}" for i in range(LONG_PAGE_WORD_LIMIT))
    passages = chunk_document_pages(doc_id="doc1", pages=(_page(text),))
    assert len(passages) == 1
    assert passages[0].chunk == 0


def test_page_over_the_limit_splits_into_overlapping_windows() -> None:
    words = [f"w{i}" for i in range(LONG_PAGE_WORD_LIMIT + 1)]
    passages = chunk_document_pages(doc_id="doc1", pages=(_page(" ".join(words)),))
    assert len(passages) == 2
    assert [p.chunk for p in passages] == [0, 1]
    assert [p.page for p in passages] == [1, 1]
    first_words = passages[0].text.split()
    second_words = passages[1].text.split()
    assert len(first_words) == WINDOW_WORD_COUNT
    # The two windows overlap by exactly WINDOW_OVERLAP_WORDS words, never
    # spanning past this one page.
    assert first_words[-WINDOW_OVERLAP_WORDS:] == second_words[:WINDOW_OVERLAP_WORDS]
    assert first_words + second_words[WINDOW_OVERLAP_WORDS:] == words


def test_passage_ids_are_stable_and_scoped_to_doc_and_page() -> None:
    words = [f"w{i}" for i in range(LONG_PAGE_WORD_LIMIT + 1)]
    passages = chunk_document_pages(
        doc_id="doc9", pages=(_page("corta"), _page(" ".join(words)))
    )
    ids = [p.passage_id for p in passages]
    assert ids == ["doc9:p1:c0", "doc9:p2:c0", "doc9:p2:c1"]


def test_never_merges_text_across_two_pages() -> None:
    passages = chunk_document_pages(
        doc_id="doc1", pages=(_page("prima pagina"), _page("seconda pagina"))
    )
    assert [p.text for p in passages] == ["prima pagina", "seconda pagina"]
    assert [p.page for p in passages] == [1, 2]


def test_no_text_page_yields_no_passage() -> None:
    passages = chunk_document_pages(
        doc_id="doc1", pages=(_page("ok testo qui"), _page("", no_text=True))
    )
    assert [p.page for p in passages] == [1]


def test_empty_pages_tuple_yields_no_passages() -> None:
    assert chunk_document_pages(doc_id="doc1", pages=()) == []


def test_whitespace_only_page_yields_no_passage() -> None:
    passages = chunk_document_pages(doc_id="doc1", pages=(_page("   \n  "),))
    assert passages == []

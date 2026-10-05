from sbobina.generation_pipeline import render_passages
from sbobina.retrieval import DocumentSource, RetrievedPassage


def _passage(text: str, page: int = 1) -> RetrievedPassage:
    return RetrievedPassage(
        text=text,
        source=DocumentSource(doc_id="appunti", page=page, chunk=0),
        passage_id=f"appunti:p{page}:c0",
    )


def test_render_passages_puts_each_passage_on_one_line() -> None:
    # A short page keeps its line breaks (document_passages); sent as is, it
    # broke the "one passage per line" format and qwen degenerated into
    # quotes made of newlines or unbalanced JSON (T069: 2 of 10 exams failed).
    passages = [
        _passage(text="Serie\n\nLa serie \\[ \\sum_{n} q^n \\]\nconverge", page=1),
        _passage(text="Matrici", page=2),
    ]

    rendered = render_passages(passages=passages)

    lines = rendered.split("\n")
    assert len(lines) == 2
    assert lines[0].endswith(") Serie La serie \\[ \\sum_{n} q^n \\] converge")
    assert lines[1].endswith(") Matrici")

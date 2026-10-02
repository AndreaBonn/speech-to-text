from sbobina.generation_models import (
    GenerationCitation,
    GenerationQuestion,
    SummarySection,
    SummarySentence,
)
from sbobina.generation_render import (
    format_citation_source,
    render_exam_markdown,
    render_solutions_markdown,
    render_summary_markdown,
)


def _doc_citation(doc_id: str = "manuale", page: int = 214) -> GenerationCitation:
    return GenerationCitation(
        passage_id=f"{doc_id}:p{page}:c0",
        quote="q",
        doc_id=doc_id,
        page=page,
        job_id=None,
        timestamp=None,
    )


def _mc_question() -> GenerationQuestion:
    return GenerationQuestion(
        question="Quando la causa e' illecita?",
        options=("a", "b", "La risposta segreta", "d"),
        correct_index=2,
        solution="Perche' il manuale lo dice chiaramente, segreto.",
        citations=(_doc_citation(),),
    )


def test_render_exam_markdown_never_leaks_solution_or_correct_option() -> None:
    markdown = render_exam_markdown(questions=[_mc_question()])

    assert "segreto" not in markdown.lower()
    assert "corretta" not in markdown.lower()
    assert "a) a" in markdown
    assert "c) la risposta segreta" in markdown.lower()


def test_render_exam_markdown_handles_question_without_options() -> None:
    question = GenerationQuestion(
        question="Che cos'e' lo stato stazionario?",
        options=(),
        correct_index=None,
        solution="soluzione segreta",
        citations=(),
    )

    markdown = render_exam_markdown(questions=[question])

    assert "Che cos'e' lo stato stazionario?" in markdown
    assert "soluzione segreta" not in markdown


def test_render_solutions_markdown_shows_correct_option_and_filename_source() -> None:
    markdown = render_solutions_markdown(
        questions=[_mc_question()], doc_filenames={"manuale": "Manuale di diritto.pdf"}
    )

    assert "Risposta corretta: c) La risposta segreta" in markdown
    assert "Manuale di diritto.pdf, pagina 214" in markdown


def test_render_solutions_markdown_falls_back_to_doc_id_without_filename() -> None:
    markdown = render_solutions_markdown(questions=[_mc_question()], doc_filenames={})

    assert "manuale, pagina 214" in markdown


def test_format_citation_source_lecture_uses_mm_ss() -> None:
    citation = GenerationCitation(
        passage_id="Ljob-1-S3",
        quote="q",
        doc_id=None,
        page=None,
        job_id="job-1",
        timestamp=125.0,
    )

    assert (
        format_citation_source(citation=citation, doc_filenames={}) == "lezione, 02:05"
    )


def test_render_summary_markdown_includes_sections_sentences_and_citations() -> None:
    section = SummarySection(
        title="Avviamento",
        sentences=(
            SummarySentence(
                text="L'avviamento produce profitto.",
                citations=(_doc_citation(doc_id="manuale", page=12),),
            ),
        ),
    )

    markdown = render_summary_markdown(
        sections=[section], doc_filenames={"manuale": "Riassunto.pdf"}
    )

    assert "Avviamento" in markdown
    # Trailing period escaped like study_render.py, to not read as a markdown list marker.
    assert "L'avviamento produce profitto\\." in markdown
    assert "Riassunto.pdf, pagina 12" in markdown

"""Pure markdown rendering for generated exam tasks and summaries (T033).

compito.md never shows a solution or which option is correct: the exam and
its answer key are separate files (soluzioni.md), mirroring study_render.py's
escaping approach. A citation's readable source (filename, page, or
lezione/mm:ss) needs a doc_id -> filename mapping the caller supplies:
resolving it here would mean I/O in a module that stays pure, the same
reason study_render.py takes the transcript as an argument instead of
reading it.
"""

import html
import re
from collections.abc import Mapping, Sequence

from sbobina.generation_models import (
    GenerationCitation,
    GenerationQuestion,
    SummarySection,
)
from sbobina.retrieval import DocumentSource, RetrievalSource
from sbobina.study_blocks import study_timestamp

_OPTION_LETTERS = "abcd"
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+.!|>~-])")


def _escape_markdown(text: str) -> str:
    return _MARKDOWN_SPECIAL.sub(
        r"\\\1", html.escape(" ".join(text.split()), quote=False)
    )


def format_passage_source(source: RetrievalSource) -> str:
    """Generic label for the model's prompt: no filename lookup, no I/O."""
    if isinstance(source, DocumentSource):
        return f"documento, pagina {source.page}"
    return f"lezione, {study_timestamp(seconds=source.start)}"


def format_citation_source(
    citation: GenerationCitation, doc_filenames: Mapping[str, str]
) -> str:
    """Readable source for a persisted citation: real filename when known."""
    if citation.doc_id is not None and citation.page is not None:
        name = doc_filenames.get(citation.doc_id, citation.doc_id)
        return f"{name}, pagina {citation.page}"
    timestamp = citation.timestamp if citation.timestamp is not None else 0.0
    return f"lezione, {study_timestamp(seconds=timestamp)}"


def _render_options(options: Sequence[str]) -> list[str]:
    """``options`` is 0 or exactly 4 items (GenerationQuestion's own invariant);
    plain zip truncates to that 0 case without strict mismatching lengths."""
    return [
        f"   {letter}) {_escape_markdown(option)}"
        for letter, option in zip(_OPTION_LETTERS, options)
    ]


def render_exam_markdown(questions: Sequence[GenerationQuestion]) -> str:
    """compito.md: question and options only, never the solution."""
    lines = ["# Compito", ""]
    for number, question in enumerate(questions, start=1):
        lines.append(f"{number}. {_escape_markdown(question.question)}")
        lines.extend(_render_options(question.options))
        lines.append("")
    return "\n".join(lines) + "\n"


def _render_citation(
    citation: GenerationCitation, doc_filenames: Mapping[str, str]
) -> str:
    source = format_citation_source(citation=citation, doc_filenames=doc_filenames)
    return f"   > ({source}) {_escape_markdown(citation.quote)}"


def _render_solution(
    question: GenerationQuestion, doc_filenames: Mapping[str, str]
) -> list[str]:
    lines = []
    if question.options and question.correct_index is not None:
        letter = _OPTION_LETTERS[question.correct_index]
        option = question.options[question.correct_index]
        lines.append(f"   Risposta corretta: {letter}) {_escape_markdown(option)}")
    lines.append(f"   {_escape_markdown(question.solution)}")
    lines.extend(
        _render_citation(citation=citation, doc_filenames=doc_filenames)
        for citation in question.citations
    )
    return lines


def render_solutions_markdown(
    questions: Sequence[GenerationQuestion], doc_filenames: Mapping[str, str]
) -> str:
    """soluzioni.md: solution and cited source for every kept question."""
    lines = ["# Soluzioni", ""]
    for number, question in enumerate(questions, start=1):
        lines.append(f"{number}. {_escape_markdown(question.question)}")
        lines.extend(_render_solution(question=question, doc_filenames=doc_filenames))
        lines.append("")
    return "\n".join(lines) + "\n"


def render_summary_markdown(
    sections: Sequence[SummarySection], doc_filenames: Mapping[str, str]
) -> str:
    lines = ["# Riassunto", ""]
    for section in sections:
        lines.extend([f"## {_escape_markdown(section.title)}", ""])
        for sentence in section.sentences:
            lines.append(f"- {_escape_markdown(sentence.text)}")
            lines.extend(
                _render_citation(citation=citation, doc_filenames=doc_filenames)
                for citation in sentence.citations
            )
        lines.append("")
    return "\n".join(lines) + "\n"

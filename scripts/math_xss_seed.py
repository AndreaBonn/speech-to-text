"""Course data carrying the C4 formula XSS payloads, for verify_math_xss.py (T066).

Every surface that renders formulas gets the same text: the hostile payloads
of plan C4 plus one harmless formula (the paired positive case). Builds on the
round-trip fixtures in tests/ (a course with lectures, a document, one
generation per format and cards).
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from package_fixtures import NOW
from package_round_trip_fixtures import SourceCourse, citations, seed_round_trip_course

from sbobina.card_models import CardDraft, GenerationAnchor
from sbobina.chat_pipeline import ChatAnswer, ChatOutcome, ChatSentence
from sbobina.generation_models import (
    GenerationFormat,
    GenerationRecord,
    SummarySection,
    SummarySentence,
)
from sbobina.models import Segment, Transcript, Word, save_transcript
from sbobina.study_models import (
    Citation,
    ConceptItem,
    QuestionItem,
    StudyChapter,
    StudyResult,
    SummaryItem,
)
from sbobina.study_render import STUDY_ADAPTER
from sbobina.web.api_files import transcript_revision
from sbobina.web.card_store import create_card
from sbobina.web.chat_records import AnswerTo
from sbobina.web.chat_store import append_answer, append_question, create_chat
from sbobina.web.document_store import document_dir
from sbobina.web.generation_store import iter_generations, save_generation

MAX_FORMULA_CHARS = 2000
POSITIVE = "\\(x^2\\)"
PAYLOADS = (
    "\\(\\href{javascript:alert(1)}{x}\\)",
    "\\(\\url{javascript:alert(1)}\\)",
    "\\(\\htmlData{x=1}{y}\\)",
    "\\(\\includegraphics{x}\\)",
    "<img src=x onerror=alert(1)>",
    "\\(<img src=x onerror=alert(1)>\\)",
    "\\(\\def\\a{\\a\\a}\\a\\)",
    "\\(" + ("x+" * MAX_FORMULA_CHARS)[:MAX_FORMULA_CHARS] + "x\\)",
)
TEXT = " ".join((*PAYLOADS, POSITIVE))
# Cards cap front and back at 2000 characters: the over-long formula cannot
# be stored there at all.
CARD_TEXT = " ".join((*PAYLOADS[:-1], POSITIVE))
# The judge can only quote the student's answer, which holds this phrase.
ANSWER = "la mia risposta su questa domanda difficile"


def _hostile_generation(record: GenerationRecord) -> GenerationRecord:
    if record.format is GenerationFormat.SUMMARY:
        cited = record.sections[0].sentences[0].citations
        sentence = SummarySentence(text=TEXT, citations=cited)
        section = SummarySection(title=TEXT, sentences=(sentence,))
        return replace(record, sections=(section,))
    is_mc = record.format is GenerationFormat.MULTIPLE_CHOICE
    options = (TEXT, POSITIVE, "\\(y\\)", "\\(z\\)") if is_mc else ()
    questions = tuple(
        replace(q, question=TEXT, solution=TEXT, options=options)
        for q in record.questions
    )
    return replace(record, questions=questions)


def _seed_chat(source: SourceCourse) -> None:
    cdir, course_id = source.store.courses_dir, source.course.id
    chat = create_chat(courses_dir=cdir, course_id=course_id)
    question = append_question(
        courses_dir=cdir, course_id=course_id, chat_id=chat.id, text=TEXT
    )
    sentence = ChatSentence(text=TEXT, citations=citations(source=source)[:1])
    answer = ChatAnswer(outcome=ChatOutcome.DONE, sentences=(sentence,))
    reply = AnswerTo(question_id=question.id, answer=answer)
    append_answer(courses_dir=cdir, course_id=course_id, chat_id=chat.id, reply=reply)


def _seed_document(source: SourceCourse) -> None:
    directory = document_dir(
        courses_dir=source.store.courses_dir,
        course_id=source.course.id,
        doc_id=source.doc_id,
    )
    page = {"text": TEXT, "no_text": False, "ocr": True, "ocr_prompt": "ocr-v2"}
    content = {"pages": [page], "status": "ready", "encoding": None}
    (directory / "text.json").write_text(
        json.dumps(content, ensure_ascii=False), encoding="utf-8"
    )


def _words(text: str, start: float) -> tuple[Word, ...]:
    return tuple(
        Word(start=start + i, end=start + i + 0.5, text=" " + token, probability=1.0)
        for i, token in enumerate(text.split())
    )


def _hostile_chapter() -> StudyChapter:
    cite = (Citation(segment_index=0, quote="inizio della lezione"),)
    # A concept's term must appear in its own quote.
    concept = ConceptItem(
        term="Moto uniforme",
        explanation=TEXT,
        citations=(Citation(segment_index=1, quote="il moto uniforme rettilineo"),),
    )
    return StudyChapter(
        title=TEXT,
        start=0.0,
        summary=(SummaryItem(text=TEXT, citations=cite),),
        concepts=(concept,),
        questions=(QuestionItem(question=TEXT, citations=cite),),
    )


def _seed_study(source: SourceCourse) -> str:
    """Study materials whose items pass the citation check on read."""
    job_dir = source.store.jobs_dir / source.job_ids[0]
    segments = (
        Segment(
            start=0.0, end=10.0, words=_words(text="inizio della lezione", start=0.0)
        ),
        Segment(
            start=10.0,
            end=20.0,
            words=_words(text="il moto uniforme rettilineo", start=10.0),
        ),
    )
    transcript = Transcript(
        source="a.wav", model="m", language="it", duration=20.0, segments=segments
    )
    save_transcript(transcript=transcript, path=job_dir / "audio.json")
    (job_dir / "audio.corretto.json").unlink()
    revision = transcript_revision(
        content=(job_dir / "audio.json").read_text(encoding="utf-8")
    )
    study = StudyResult(
        source_variant="original",
        source_revision=revision,
        model="m",
        prompt_version="studio-v1",
        generated_at=NOW.isoformat(),
        chapters=(_hostile_chapter(),),
        discarded=(),
        failed_blocks=(),
    )
    (job_dir / "audio.studio.json").write_bytes(STUDY_ADAPTER.dump_json(study))
    return source.job_ids[0]


def seed(data_dir: Path) -> tuple[SourceCourse, dict[GenerationFormat, str]]:
    """Seed the course; returns it with the generation id of each format."""
    source = seed_round_trip_course(data_dir=data_dir)
    cdir = source.store.courses_dir
    generation_ids = {}
    for course_id, record in list(iter_generations(courses_dir=cdir)):
        save_generation(
            courses_dir=cdir, course_id=course_id, record=_hostile_generation(record)
        )
        generation_ids[record.format] = record.id
    anchor = GenerationAnchor(
        generation_id=generation_ids[GenerationFormat.OPEN], question_index=0
    )
    draft = CardDraft(front=CARD_TEXT, back=CARD_TEXT, source="Fisica", anchor=anchor)
    create_card(courses_dir=cdir, course_id=source.course.id, now=NOW, draft=draft)
    _seed_chat(source=source)
    _seed_document(source=source)
    _seed_study(source=source)
    return source, generation_ids

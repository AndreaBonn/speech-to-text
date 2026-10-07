"""Question-to-query translation and cross-source passage retrieval for a course.

v1 is BM25-only (adr.md § D2 decision D2): lecture segments and document
chunks of one course are ranked per source by bm25(), fused by rank and cut to a word budget.
A richer retriever (dense/hybrid) only lands if T024 measures recall@8 below
the gate.
"""

import re
from dataclasses import dataclass

from sbobina.rank_fusion import fuse_by_rank
from sbobina.search_text import FINAL_VOWELS, MIN_STEM_LENGTH, MIN_WORD_LENGTH
from sbobina.web.document_index import DocumentScope
from sbobina.web.search_index import SearchIndex

WORD_RE = re.compile(r"\w+", re.UNICODE)

# Candidates fetched per source before fusion and budget cut. Generous enough
# that a realistic budget (a few thousand words) is never starved by a source
# that ranked worse on average, without scanning the whole course.
CANDIDATE_LIMIT = 50

ITALIAN_STOPWORDS = frozenset(
    {
        "il",
        "lo",
        "la",
        "i",
        "gli",
        "le",
        "un",
        "uno",
        "una",
        "di",
        "a",
        "da",
        "in",
        "con",
        "su",
        "per",
        "tra",
        "fra",
        "e",
        "o",
        "ma",
        "che",
        "chi",
        "cui",
        "non",
        "come",
        "se",
        "è",
        "sono",
        "sei",
        "siamo",
        "siete",
        "essere",
        "ha",
        "hanno",
        "del",
        "della",
        "dello",
        "dei",
        "degli",
        "delle",
        "al",
        "allo",
        "alla",
        "ai",
        "agli",
        "alle",
        "dal",
        "dallo",
        "dalla",
        "dai",
        "dagli",
        "dalle",
        "nel",
        "nello",
        "nella",
        "nei",
        "negli",
        "nelle",
        "sul",
        "sullo",
        "sulla",
        "sui",
        "sugli",
        "sulle",
        "cos",
        "cosa",
        "quale",
        "quali",
        "questo",
        "questa",
        "questi",
        "queste",
        "quello",
        "quella",
        "quelli",
        "quelle",
        "mio",
        "tuo",
        "suo",
        "loro",
        "nostro",
        "vostro",
        "si",
        "ci",
        "vi",
        "ne",
    }
)


def question_to_fts(question: str) -> str | None:
    """Content-word OR query for a natural-language question.

    Drops Italian stopwords, prefix-stems long words the same way the
    existing lecture/document search does (see
    search_text.build_match_query), and always wraps terms in a quoted
    prefix (``"term"*``) so no FTS5 operator the user typed (NEAR, -, :,
    bare *) ever reaches SQLite unescaped. Returns None when nothing is left.
    """
    terms = []
    for word in WORD_RE.findall(question):
        lowered = word.lower()
        if len(lowered) < MIN_WORD_LENGTH or lowered in ITALIAN_STOPWORDS:
            continue
        stem = (
            lowered.rstrip(FINAL_VOWELS) if len(lowered) >= MIN_STEM_LENGTH else lowered
        )
        if stem:
            terms.append(f'"{stem}"*')
    return " OR ".join(terms) or None


@dataclass(frozen=True)
class LectureSource:
    job_id: str
    segment_index: int
    start: float


@dataclass(frozen=True)
class DocumentSource:
    doc_id: str
    page: int
    chunk: int


RetrievalSource = LectureSource | DocumentSource


@dataclass(frozen=True)
class RetrievedPassage:
    text: str
    source: RetrievalSource
    passage_id: str


@dataclass(frozen=True)
class RetrievalScope:
    """What retrieve() may read: one course, optionally narrowed further.

    selected, when not None, restricts the lecture job_ids and the document
    doc_ids to that set (a user-chosen subset of the course's sources). None
    means the whole course.
    """

    course_id: str
    job_ids: frozenset[str]
    selected: frozenset[str] | None = None


def scoped_job_ids(scope: RetrievalScope) -> frozenset[str]:
    """Scope's lecture ids, narrowed to scope.selected when the user picked some."""
    if scope.selected is None:
        return scope.job_ids
    return scope.job_ids & scope.selected


def _ranked_lecture_passages(
    index: SearchIndex, scope: RetrievalScope, match: str
) -> list[tuple[float, RetrievedPassage]]:
    job_ids = scoped_job_ids(scope=scope)
    if not job_ids:
        return []
    rows = index.lecture_passages_for_retrieval(
        match=match, job_ids=job_ids, limit=CANDIDATE_LIMIT
    )
    return [
        (
            row.score,
            RetrievedPassage(
                text=row.text,
                source=LectureSource(
                    job_id=row.job_id, segment_index=row.segment_index, start=row.start
                ),
                passage_id=f"L{row.job_id}-S{row.segment_index}",
            ),
        )
        for row in rows
    ]


def _ranked_document_passages(
    index: SearchIndex, scope: RetrievalScope, match: str
) -> list[tuple[float, RetrievedPassage]]:
    rows = index.document_passages_for_retrieval(
        match=match,
        scope=DocumentScope(course_id=scope.course_id, doc_ids=scope.selected),
        limit=CANDIDATE_LIMIT,
    )
    return [
        (
            row.score,
            RetrievedPassage(
                text=row.text,
                source=DocumentSource(
                    doc_id=row.doc_id, page=row.page, chunk=row.chunk
                ),
                passage_id=row.passage_id,
            ),
        )
        for row in rows
    ]


def cut_to_budget(
    ranked: list[RetrievedPassage], budget_words: int
) -> list[RetrievedPassage]:
    """Keep passages in rank order while the running word count fits.

    The first passage that would overflow stops the list entirely (no
    mid-passage truncation, and no skip-ahead past a worse-ranked passage).
    """
    selected: list[RetrievedPassage] = []
    used_words = 0
    for passage in ranked:
        words = len(passage.text.split())
        if used_words + words > budget_words:
            break
        selected.append(passage)
        used_words += words
    return selected


def fuse_candidates(
    index: SearchIndex, scope: RetrievalScope, question: str
) -> list[RetrievedPassage]:
    """Lecture and document passages of one course matching question, fused by rank.

    Not yet windowed (T025, see sbobina.lecture_windows) nor cut to a word
    budget: callers that need either do so afterwards, in that order, since
    the budget must count window words, not raw 10-30 word segments.
    """
    match = question_to_fts(question=question)
    if match is None:
        return []
    return fuse_by_rank(
        rankings=[
            _ranked_lecture_passages(index=index, scope=scope, match=match),
            _ranked_document_passages(index=index, scope=scope, match=match),
        ]
    )


def retrieve(
    index: SearchIndex, scope: RetrievalScope, question: str, budget_words: int
) -> list[RetrievedPassage]:
    """Passages of one course answering question, fused by rank, within budget."""
    fused = fuse_candidates(index=index, scope=scope, question=question)
    return cut_to_budget(ranked=fused, budget_words=budget_words)

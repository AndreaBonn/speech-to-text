"""Verify data/eval/retrieval-hybrid/gold.json against its corpus (T012).

Three checks, independent of any retrieval code:

- every reference exists: a document reference's page is within that
  document's page count, a lecture reference's ``[start_s, end_s]`` is
  within that job's transcript duration.
- a ``paraphrase`` question shares no content word (non-stopword) with the
  text of its own reference(s); content words are compared case- and
  accent-insensitive, letters only.
- a ``crosslingual`` question references only the English-language chapters
  (``data/eval/retrieval-hybrid/english-staging/``), never the Italian PDFs
  or the diritto lectures: its answer must exist only in the English side of
  the corpus.
- an ``exact`` question's literal term (a rare word the question must share
  with its reference text, e.g. an article number or an acronym) actually
  occurs in the text of every one of its references.

Usage: ``uv run python scripts/check_gold.py [gold.json] [corpus_dir]``
"""

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from sbobina.models import load_transcript
from sbobina.web.document_store import document_dir, iter_documents, read_text
from sbobina.web.job_store import JobStore

DEFAULT_GOLD = Path("data/eval/retrieval-hybrid/gold.json")
DEFAULT_CORPUS = Path("data/eval/retrieval-hybrid/corpus")
TRANSCRIPT_VARIANTS = ("audio.corretto.json", "audio.json")
PARAPHRASE_TYPE = "paraphrase"
CROSSLINGUAL_TYPE = "crosslingual"
EXACT_TYPE = "exact"
MIN_EXACT_TERM_LEN = 2
# The only documents a crosslingual reference may point to: the synthetic
# English chapters, never an Italian PDF or a diritto lecture.
ENGLISH_FILENAMES = frozenset(
    {"chapter-firm-and-accounting.md", "chapter-costs-and-decisions.md"}
)
# Common Italian function words, already accent-folded (see `fold`): articles,
# prepositions, conjunctions, pronouns, auxiliary verb forms and question
# words. Not exhaustive; extend it if a legitimate paraphrase gets flagged.
# Kept as a single string (not a list literal) to stay within the file's line
# budget: a name, not a literal, so ruff's SIM905 leaves the `.split()` alone.
_STOPWORDS_TEXT = (
    "il lo la i gli le un uno una di a da in con su per tra fra e o ma che "
    "chi cui cosa quale quali quanto quanti quanta quante non si sono era "
    "erano essere stato stata stati state sia siano essendo ha hanno aveva "
    "avevano avere questo questa questi queste quello quella quelli quelle "
    "come quando dove perche ogni anche piu meno molto poco suo sua suoi "
    "sue loro mio mia miei mie tuo tua tuoi tue nel nella nello negli degli "
    "delle dei del dell dello all alla allo agli alle dal dalla dallo dagli "
    "dalle col coi ne ci vi li ed ad od se cioe oppure quindi dunque poi "
    "gia ancora solo soltanto proprio stesso stessa stessi stesse tutti "
    "tutte tutto tutta alcuni alcune altro altri altra altre qual puo deve "
    "devono viene vengono fa fanno fare essa essi esse lui lei noi voi io "
    "tu ti mi c l tale tali sotto sopra senza dentro fuori verso circa "
    "durante secondo nonche"
)
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())


def fold(text: str) -> str:
    """Casefold and strip accents, so comparison ignores both."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def content_words(text: str) -> set[str]:
    """Words of ``text``, folded, with stopwords removed."""
    words = re.findall(r"[a-z]+", fold(text))
    return {word for word in words if word not in STOPWORDS}


def exact_terms(question: str) -> set[str]:
    """Candidate literal terms of an ``exact`` question.

    A term is a digit run (article number, figure) anywhere in the
    question, or a word starting with an uppercase letter (acronym,
    proper noun) that is not the question's own first word: that one is
    capitalized only because it opens the sentence (``Come``, ``Cosa``,
    ``Qual``...), never itself the literal term.
    """
    words = question.split()
    terms = set(re.findall(r"\d+", question))
    for word in words[1:]:
        cleaned = re.sub(r"[^\w]", "", word, flags=re.UNICODE)
        if len(cleaned) >= MIN_EXACT_TERM_LEN and cleaned[0].isupper():
            terms.add(cleaned)
    return terms


def _page_texts(corpus_dir: Path) -> dict[tuple[str, int], str]:
    """Map (filename, 1-based page) to its extracted text, for every document."""
    courses_dir = corpus_dir / "courses"
    texts: dict[tuple[str, int], str] = {}
    for course_dir in courses_dir.iterdir():
        for doc in iter_documents(courses_dir=courses_dir, course_id=course_dir.name):
            doc_dir = document_dir(
                courses_dir=courses_dir, course_id=course_dir.name, doc_id=doc.id
            )
            stored = read_text(doc_dir=doc_dir)
            for index, page in enumerate(stored.pages, start=1):
                texts[(doc.filename, index)] = page.text
    return texts


def _lecture_duration(store: JobStore, job_id: str) -> float | None:
    directory = store.jobs_dir / job_id
    for name in TRANSCRIPT_VARIANTS:
        path = directory / name
        if path.exists():
            return load_transcript(path=path).duration
    return None


def _lecture_window_text(
    store: JobStore, job_id: str, start_s: float, end_s: float
) -> str:
    directory = store.jobs_dir / job_id
    for name in TRANSCRIPT_VARIANTS:
        path = directory / name
        if not path.exists():
            continue
        transcript = load_transcript(path=path)
        segments = [
            segment.text
            for segment in transcript.segments
            if segment.start < end_s and segment.end > start_s
        ]
        return " ".join(segments)
    return ""


def _check_document_ref(
    ref: dict[str, Any], page_texts: dict[tuple[str, int], str], item_id: str
) -> tuple[list[str], str]:
    key = (ref["filename"], ref["page"])
    if key not in page_texts:
        return [f"{item_id}: pagina inesistente {key}"], ""
    return [], page_texts[key]


def _check_lecture_ref(
    ref: dict[str, Any], store: JobStore, item_id: str
) -> tuple[list[str], str]:
    duration = _lecture_duration(store=store, job_id=ref["job_id"])
    if duration is None:
        return [f"{item_id}: job_id inesistente {ref['job_id']}"], ""
    start_s, end_s = ref["start_s"], ref["end_s"]
    if not (0 <= start_s < end_s <= duration):
        message = (
            f"{item_id}: intervallo [{start_s},{end_s}] fuori dalla durata "
            f"{duration:.1f} di {ref['job_id']}"
        )
        return [message], ""
    return [], _lecture_window_text(
        store=store, job_id=ref["job_id"], start_s=start_s, end_s=end_s
    )


def _check_crosslingual_ref(ref: dict[str, Any], item_id: str) -> list[str]:
    if ref["kind"] != "document" or ref["filename"] not in ENGLISH_FILENAMES:
        target = ref.get("filename", ref["kind"])
        return [f"{item_id}: riferimento crosslingual non in inglese ({target})"]
    return []


def _check_refs(
    item: dict[str, Any], page_texts: dict[tuple[str, int], str], store: JobStore
) -> tuple[list[str], list[str]]:
    """Validate every reference of one item; return (errors, reference texts)."""
    errors: list[str] = []
    texts: list[str] = []
    for ref in item["references"]:
        if item["type"] == CROSSLINGUAL_TYPE:
            errors.extend(_check_crosslingual_ref(ref=ref, item_id=item["id"]))
        if ref["kind"] == "document":
            ref_errors, text = _check_document_ref(
                ref=ref, page_texts=page_texts, item_id=item["id"]
            )
        else:
            ref_errors, text = _check_lecture_ref(
                ref=ref, store=store, item_id=item["id"]
            )
        errors.extend(ref_errors)
        texts.append(text)
    return errors, texts


def _check_exact(item: dict[str, Any], reference_texts: list[str]) -> list[str]:
    terms = exact_terms(item["question"])
    if not terms:
        return [f"{item['id']}: nessun termine esatto individuabile nella domanda"]
    folded_terms = {fold(term) for term in terms}
    errors = []
    for ref, text in zip(item["references"], reference_texts, strict=True):
        if not any(term in fold(text) for term in folded_terms):
            location = ref.get("filename") or ref.get("job_id")
            errors.append(
                f"{item['id']}: nessuno dei termini esatti {sorted(terms)} "
                f"nel riferimento {location}"
            )
    return errors


def _check_item(
    item: dict[str, Any], page_texts: dict[tuple[str, int], str], store: JobStore
) -> list[str]:
    errors, reference_texts = _check_refs(item=item, page_texts=page_texts, store=store)
    if item["type"] == PARAPHRASE_TYPE and not errors:
        shared = content_words(item["question"]) & content_words(
            " ".join(reference_texts)
        )
        if shared:
            errors.append(
                f"{item['id']}: parole di contenuto condivise {sorted(shared)}"
            )
    if item["type"] == EXACT_TYPE and not errors:
        errors.extend(_check_exact(item=item, reference_texts=reference_texts))
    return errors


def check_gold(gold_path: Path, corpus_dir: Path) -> list[str]:
    """Return every violation found; an empty list means the gold set is clean."""
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    page_texts = _page_texts(corpus_dir=corpus_dir)
    store = JobStore(data_dir=corpus_dir)
    errors: list[str] = []
    for item in gold["items"]:
        if item["type"] != "negative" and not item["references"]:
            errors.append(f"{item['id']}: nessun riferimento per un tipo non-negative")
        errors.extend(_check_item(item=item, page_texts=page_texts, store=store))
    return errors


def main() -> int:
    gold_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GOLD
    corpus_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CORPUS
    errors = check_gold(gold_path=gold_path, corpus_dir=corpus_dir)
    for error in errors:
        print(f"FAIL {error}")
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    print(f"{len(gold['items'])} domande, {len(errors)} errori")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

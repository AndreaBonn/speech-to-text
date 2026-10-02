"""Measure course retrieval recall on a hand-written question set (T024).

    uv run python scripts/eval_retrieval.py <data_dir> <eval.json> [k]

For each question the retriever runs on the question's course; a hit at k is
a retrieved passage among the first k whose text contains the question's
`key` (case and accent insensitive). Prints one line per question and the
recall@k overall and per origin. Questions whose key is in no passage of the
course are reported as invalid instead of counted as misses.
"""

import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from sbobina.course_registry import find_by_key
from sbobina.retrieval import RetrievalScope
from sbobina.web.course_retrieval import WindowedQuery, course_scope, retrieve_windows
from sbobina.web.document_store import iter_documents
from sbobina.web.job_store import JobStore
from sbobina.web.search_service import search_session

LARGE_BUDGET_WORDS = 100_000


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def scope_for(store: JobStore, key: str, exclude_prefix: str | None) -> RetrievalScope:
    course = find_by_key(courses_dir=store.courses_dir, key=key)
    scope = course_scope(store=store, key=key)
    if exclude_prefix is None or course is None:
        return scope
    documents = iter_documents(courses_dir=store.courses_dir, course_id=course.id)
    kept = frozenset(
        d.id for d in documents if not d.filename.startswith(exclude_prefix)
    )
    return RetrievalScope(
        course_id=scope.course_id, job_ids=scope.job_ids, selected=kept | scope.job_ids
    )


def main() -> None:
    data_dir, eval_path = Path(sys.argv[1]), Path(sys.argv[2])
    k = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    spec = json.loads(eval_path.read_text(encoding="utf-8"))
    store = JobStore(data_dir=data_dir)
    scopes = {
        key: scope_for(store, key, options.get("exclude_filename_prefix"))
        for key, options in spec["courses"].items()
    }
    hits: dict[str, list[bool]] = defaultdict(list)
    with search_session(store=store, path=data_dir / "search.sqlite3") as index:
        for item in spec["questions"]:
            query = WindowedQuery(
                scope=scopes[item["course"]],
                question=item["q"],
                budget_words=LARGE_BUDGET_WORDS,
            )
            passages = retrieve_windows(store=store, index=index, query=query)
            key = fold(item["key"])
            ranks = [i for i, p in enumerate(passages, 1) if key in fold(p.text)]
            hit = bool(ranks) and ranks[0] <= k
            hits[item["origin"]].append(hit)
            rank = ranks[0] if ranks else "-"
            print(
                f"{'HIT ' if hit else 'MISS'} rank={rank!s:>3} [{item['origin']}] {item['q']}"
            )
    total = [h for values in hits.values() for h in values]
    for origin, values in hits.items():
        print(
            f"recall@{k} {origin}: {sum(values)}/{len(values)} = {sum(values) / len(values):.2f}"
        )
    print(f"recall@{k} all: {sum(total)}/{len(total)} = {sum(total) / len(total):.2f}")


if __name__ == "__main__":
    main()

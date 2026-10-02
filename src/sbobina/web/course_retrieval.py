"""Build a course's retrieval scope from the job store.

Callers (chat, exam-task flows, T024+) compose this with
search_service.search_session (lock + reconciliation) and retrieval.retrieve:
no new locking here, the lock already lives in search_service.
"""

from sbobina.courses import course_key, effective_course
from sbobina.retrieval import RetrievalScope
from sbobina.web.job_store import JobStore


def course_scope(store: JobStore, course_id: str) -> RetrievalScope:
    """Scope of one course: every lecture whose effective course matches it.

    Same mapping /courses uses (courses.effective_course + course_key), read
    fresh from meta.json so a rename is reflected without reindexing.
    """
    job_ids = frozenset(
        str(record.id)
        for record in store.iter_records()
        if course_key(
            label=effective_course(
                course=store.read_meta(job_id=str(record.id)).course,
                subject=record.config.subject,
            )
        )
        == course_id
    )
    return RetrievalScope(course_id=course_id, job_ids=job_ids)

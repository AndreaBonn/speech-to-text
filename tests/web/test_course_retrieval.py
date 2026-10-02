from pathlib import Path

from sbobina.web.course_retrieval import course_scope
from sbobina.web.job_models import JobConfig, LectureMeta
from sbobina.web.job_store import JobStore


def test_course_scope_collects_lectures_by_effective_course(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    explicit = store.create(config=JobConfig(subject="Fisica"))
    store.write_meta(job_id=str(explicit.id), meta=LectureMeta(course="Analisi 1"))
    fallback = store.create(config=JobConfig(subject="Analisi 1"))
    other = store.create(config=JobConfig(subject="Chimica"))

    scope = course_scope(store=store, course_id="analisi 1")

    assert scope.course_id == "analisi 1"
    assert scope.job_ids == {str(explicit.id), str(fallback.id)}
    assert str(other.id) not in scope.job_ids


def test_course_scope_is_empty_for_unknown_course(tmp_path: Path) -> None:
    store = JobStore(data_dir=tmp_path)
    store.create(config=JobConfig(subject="Fisica"))

    scope = course_scope(store=store, course_id="matematica")

    assert scope.job_ids == frozenset()

from pathlib import Path

import anyio

from sbobina.web.document_upload import discard_upload


def _upload_dir(course_dir: Path, doc_id: str) -> Path:
    doc_dir = course_dir / "documents" / doc_id
    doc_dir.mkdir(parents=True)
    (doc_dir / "upload.part").write_bytes(b"%PDF-")
    return doc_dir


def test_discard_upload_removes_the_course_it_registered(tmp_path: Path) -> None:
    course_dir = tmp_path / "courses" / "nuovo"
    doc_dir = _upload_dir(course_dir=course_dir, doc_id="a")
    (course_dir / "course.json").write_text("{}", encoding="utf-8")

    anyio.run(lambda: discard_upload(doc_dir=doc_dir, course_dir=course_dir))

    assert not course_dir.exists()


def test_discard_upload_keeps_a_course_a_concurrent_upload_still_uses(
    tmp_path: Path,
) -> None:
    course_dir = tmp_path / "courses" / "nuovo"
    failed = _upload_dir(course_dir=course_dir, doc_id="a")
    concurrent = _upload_dir(course_dir=course_dir, doc_id="b")

    anyio.run(lambda: discard_upload(doc_dir=failed, course_dir=course_dir))

    assert (failed.exists(), concurrent.exists()) == (False, True)


def test_discard_upload_into_an_existing_course_removes_only_the_document(
    tmp_path: Path,
) -> None:
    course_dir = tmp_path / "courses" / "esistente"
    doc_dir = _upload_dir(course_dir=course_dir, doc_id="a")
    (course_dir / "course.json").write_text("{}", encoding="utf-8")

    anyio.run(lambda: discard_upload(doc_dir=doc_dir, course_dir=None))

    assert (doc_dir.exists(), (course_dir / "course.json").exists()) == (False, True)

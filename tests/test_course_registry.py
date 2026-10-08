import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from sbobina.course_registry import (
    CourseExistsError,
    CourseRecord,
    CourseRequiredError,
    find_by_key,
    get_or_create,
    iter_courses,
    rename_key,
)


def test_get_or_create_same_key_preserves_record(tmp_path: Path) -> None:
    first = get_or_create(
        courses_dir=tmp_path, key="diritto privato", label="Diritto Privato"
    )

    second = get_or_create(courses_dir=tmp_path, key=first.key, label="DIRITTO PRIVATO")

    assert second == first


def test_get_or_create_new_course_assigns_uuid4(tmp_path: Path) -> None:
    record = get_or_create(courses_dir=tmp_path, key="fisica", label="Fisica")

    assert UUID(record.id).version == 4


def test_get_or_create_new_course_persists_record(tmp_path: Path) -> None:
    record = get_or_create(courses_dir=tmp_path, key="fisica", label="Fisica")

    raw = json.loads((tmp_path / record.id / "course.json").read_text(encoding="utf-8"))

    assert list(iter_courses(courses_dir=tmp_path)) == [record]
    assert raw == {
        "id": record.id,
        "key": "fisica",
        "label": "Fisica",
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def test_course_record_new_course_is_immutable(tmp_path: Path) -> None:
    record = get_or_create(courses_dir=tmp_path, key="fisica", label="Fisica")
    attribute = "label"

    with pytest.raises(FrozenInstanceError):
        setattr(record, attribute, "Altro")

    assert record.label == "Fisica"


def test_find_by_key_unknown_key_returns_none(tmp_path: Path) -> None:
    record = get_or_create(tmp_path, key="fisica", label="Fisica")

    assert find_by_key(tmp_path, key="fisica") == record
    assert find_by_key(tmp_path, key="missing") is None


@pytest.mark.parametrize("key", ["", " \t"])
def test_get_or_create_empty_key_rejects_uncategorized(
    tmp_path: Path, key: str
) -> None:
    with pytest.raises(CourseRequiredError) as caught:
        get_or_create(tmp_path, key=key, label="Senza corso")
    assert caught.value.code == "COURSE_REQUIRED"
    record = get_or_create(tmp_path, key="senza corso", label="Senza corso")
    assert list(iter_courses(tmp_path)) == [record]


@pytest.mark.parametrize("label", ["", "x" * 101, "Altro"])
def test_get_or_create_invalid_label_rejects_record(tmp_path: Path, label: str) -> None:
    with pytest.raises(ValueError):
        get_or_create(tmp_path, key="fisica", label=label)
    record = get_or_create(tmp_path, key="fisica", label="Fisica")
    assert list(iter_courses(tmp_path)) == [record]


def test_get_or_create_concurrent_calls_share_id(tmp_path: Path) -> None:
    def create_course(_: int) -> str:
        return get_or_create(tmp_path, key="fisica", label="Fisica").id

    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(create_course, range(12)))
    assert ids == [ids[0]] * 12
    assert len(list(iter_courses(tmp_path))) == 1


def test_rename_key_updates_registry_before_callback_and_keeps_documents(
    tmp_path: Path,
) -> None:
    original = get_or_create(tmp_path, key="fisica", label="Fisica")
    document = tmp_path / original.id / "documents" / "original.txt"
    document.parent.mkdir()
    document.write_text("Appunti", encoding="utf-8")
    calls: list[tuple[str, str]] = []

    def update_lectures(old: str, label: str) -> None:
        saved = find_by_key(tmp_path, key="fisica ii")
        assert saved is not None and saved.id == original.id
        calls.append((old, label))

    renamed = rename_key(
        tmp_path, old="fisica", new=" Fisica  II ", update_lectures=update_lectures
    )

    assert (renamed.id, renamed.key, renamed.label) == (
        original.id,
        "fisica ii",
        "Fisica II",
    )
    assert calls == [("fisica", "Fisica II")]
    assert renamed.created_at == original.created_at
    assert renamed.updated_at >= original.updated_at
    assert document.read_text("utf-8") == "Appunti"
    assert find_by_key(tmp_path, key="fisica") is None
    assert find_by_key(tmp_path, key="fisica ii") == renamed


def test_rename_key_callback_failure_keeps_new_registry(tmp_path: Path) -> None:
    original = get_or_create(tmp_path, key="fisica", label="Fisica")

    def fail_update(old: str, label: str) -> None:
        raise OSError("Lecture write interrupted")

    with pytest.raises(OSError, match="interrupted"):
        rename_key(tmp_path, old="fisica", new="Fisica II", update_lectures=fail_update)
    saved = find_by_key(tmp_path, key="fisica ii")
    assert saved is not None and saved.id == original.id
    assert find_by_key(tmp_path, key="fisica") is None


def test_rename_key_existing_destination_rejects_merge(tmp_path: Path) -> None:
    first = get_or_create(courses_dir=tmp_path, key="fisica", label="Fisica")
    second = get_or_create(courses_dir=tmp_path, key="diritto", label="Diritto")
    calls: list[tuple[str, str]] = []

    def update_lectures(old: str, label: str) -> None:
        calls.append((old, label))

    with pytest.raises(CourseExistsError) as caught:
        rename_key(
            courses_dir=tmp_path,
            old="fisica",
            new="Diritto",
            update_lectures=update_lectures,
        )
    assert caught.value.code == "COURSE_EXISTS"
    assert find_by_key(courses_dir=tmp_path, key="fisica") == first
    assert find_by_key(courses_dir=tmp_path, key="diritto") == second
    assert calls == []


def test_rename_key_same_key_updates_label_and_calls_back(tmp_path: Path) -> None:
    first = get_or_create(courses_dir=tmp_path, key="fisica", label="Fisica")
    calls: list[tuple[str, str]] = []

    def update_lectures(old: str, label: str) -> None:
        calls.append((old, label))

    renamed = rename_key(
        courses_dir=tmp_path,
        old="fisica",
        new="FISICA",
        update_lectures=update_lectures,
    )

    assert renamed.id == first.id
    assert renamed.label == "FISICA"
    assert calls == [("fisica", "FISICA")]


def test_rename_key_lecture_only_course_creates_new_identity(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def update_lectures(old: str, label: str) -> None:
        calls.append((old, label))

    record = rename_key(
        tmp_path, old="fisica", new="Fisica II", update_lectures=update_lectures
    )
    assert record.key == "fisica ii"
    assert calls == [("fisica", "Fisica II")]
    assert list(iter_courses(tmp_path)) == [record]


def test_rename_key_unregistered_source_conflict_creates_no_phantom(
    tmp_path: Path,
) -> None:
    destination = get_or_create(tmp_path, key="diritto", label="Diritto")
    with pytest.raises(CourseExistsError):
        rename_key(
            tmp_path,
            old="fisica",
            new="Diritto",
            update_lectures=lambda old, label: None,
        )
    assert list(iter_courses(tmp_path)) == [destination]


def test_iter_courses_corrupt_json_propagates_error(tmp_path: Path) -> None:
    record = get_or_create(tmp_path, key="fisica", label="Fisica")
    assert list(iter_courses(tmp_path)) == [record]
    (tmp_path / record.id / "course.json").write_text("broken", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        list(iter_courses(tmp_path))


NOW = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
VALID_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"


@pytest.mark.parametrize(
    ("course_id", "key", "label"),
    [
        ("not-a-uuid", "fisica", "Fisica"),
        (VALID_ID, "", "Fisica"),
        (VALID_ID, "chimica", "Fisica"),
    ],
)
def test_course_record_rejects_broken_invariants(
    course_id: str, key: str, label: str
) -> None:
    with pytest.raises(ValueError):
        CourseRecord(id=course_id, key=key, label=label, created_at=NOW, updated_at=NOW)


def test_course_record_accepts_key_matching_label() -> None:
    record = CourseRecord(
        id=VALID_ID,
        key="diritto privato",
        label="Diritto  Privato",
        created_at=NOW,
        updated_at=NOW,
    )
    assert record.key == "diritto privato"


def test_rename_key_empty_source_key_is_rejected(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    with pytest.raises(CourseRequiredError):
        rename_key(
            courses_dir=tmp_path,
            old="  ",
            new="Fisica",
            update_lectures=lambda old, new: calls.append((old, new)),
        )

    assert (calls, list(tmp_path.iterdir())) == ([], [])

import json
from pathlib import Path

import pytest
from package_import_fixtures import (
    IMPORT_TIME,
    make_package,
    office_package,
    package_members,
    rewrite_package,
    snapshot,
)

from sbobina import document_sniff
from sbobina.package_import import PackageStorageError, import_package
from sbobina.package_validate import PackageInvalidError


@pytest.mark.parametrize(
    "member",
    [
        "lectures/0/meta.json",
        "lectures/0/transcript.json",
        "lectures/0/corrected.json",
        "lectures/0/study.json",
        "documents/0/document.json",
        "documents/0/text.json",
        "generations/0.json",
        "cards/cards.jsonl",
        "documents/0/original.txt",
    ],
)
def test_import_package_invalid_content_rejected_without_changes(
    tmp_path: Path, member: str
) -> None:
    source = make_package(directory=tmp_path)
    data = tmp_path / "destination"
    valid = import_package(source=source, data_dir=data, now=IMPORT_TIME)
    assert (data / "courses" / valid.course.id).is_dir()
    before = snapshot(directory=data)
    invalid = rewrite_package(source=source, changes={member: b"\x00invalid"})
    with pytest.raises(PackageInvalidError):
        import_package(source=invalid, data_dir=data, now=IMPORT_TIME)
    assert snapshot(directory=data) == before
    assert list(data.rglob(".import-*")) == []


@pytest.mark.parametrize(
    "member",
    ["lectures/0/meta.json", "lectures/0/transcript.json", "documents/0/document.json"],
)
def test_import_package_missing_required_member_rejected(
    tmp_path: Path, member: str
) -> None:
    source = make_package(directory=tmp_path)
    assert (
        import_package(
            source=source, data_dir=tmp_path / "valid", now=IMPORT_TIME
        ).course.label
        == "Fisica"
    )
    invalid = rewrite_package(source=source, changes={member: None})
    data = tmp_path / "invalid"
    with pytest.raises(PackageInvalidError):
        import_package(source=invalid, data_dir=data, now=IMPORT_TIME)
    assert list(data.rglob("*")) == []


def test_import_package_optional_members_can_be_absent(tmp_path: Path) -> None:
    source = make_package(directory=tmp_path)
    complete = tmp_path / "complete"
    import_package(source=source, data_dir=complete, now=IMPORT_TIME)
    assert len(list(complete.rglob("audio.studio.json"))) == 2
    assert len(list(complete.rglob("original.txt"))) == 1
    members = package_members(source=source)
    omitted: dict[str, bytes | None] = {
        name: None
        for name in members
        if name.endswith(("corrected.json", "study.json", "text.json", "original.txt"))
    }
    reduced = rewrite_package(source=source, changes=omitted)
    data = tmp_path / "destination"
    result = import_package(source=reduced, data_dir=data, now=IMPORT_TIME)
    assert (data / "courses" / result.course.id / "course.json").is_file()
    assert len(list((data / "jobs").glob("*/audio.json"))) == 2
    assert list(data.rglob("audio.studio.json")) == []
    assert len(list(data.rglob("document.json"))) == 1
    assert list(data.rglob("original.txt")) == []


def test_import_package_untrusted_ids_never_become_paths(tmp_path: Path) -> None:
    source = make_package(directory=tmp_path)
    members = package_members(source=source)
    meta = json.loads(members["lectures/0/meta.json"])
    meta["id"] = "../../escaped-job"
    meta["source_name"] = "/outside/lecture.m4a"
    invalid_ids = rewrite_package(
        source=source, changes={"lectures/0/meta.json": json.dumps(meta).encode()}
    )
    data = tmp_path / "destination"
    result = import_package(source=invalid_ids, data_dir=data, now=IMPORT_TIME)
    new_id = result.imported_from.ids.jobs[meta["id"]]
    assert (data / "jobs" / new_id / "job.json").is_file()
    assert list(tmp_path.rglob("escaped-job")) == []


def test_import_package_write_failure_removes_new_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_package(directory=tmp_path)
    assert (
        import_package(
            source=source, data_dir=tmp_path / "valid", now=IMPORT_TIME
        ).course.label
        == "Fisica"
    )
    data = tmp_path / "new" / "destination"
    write = Path.write_bytes

    def fail_write(self: Path, data: bytes) -> int:
        if self.name == "audio.json":
            raise OSError("injected write failure")
        return write(self, data=data)

    monkeypatch.setattr(Path, "write_bytes", fail_write)
    with pytest.raises(PackageStorageError, match="Could not write") as raised:
        import_package(source=source, data_dir=data, now=IMPORT_TIME)
    assert str(raised.value.__cause__) == "injected write failure"
    assert list((tmp_path / "new").rglob("*")) == []
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("limit", ["MAX_ARCHIVE_BYTES", "MAX_ARCHIVE_ENTRIES"])
def test_import_package_office_limits_reject_original_and_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    source = office_package(source=make_package(directory=tmp_path))
    data = tmp_path / "destination"
    valid = import_package(source=source, data_dir=data, now=IMPORT_TIME)
    assert len(list((data / "courses" / valid.course.id).rglob("original.docx"))) == 1
    before = snapshot(directory=data)
    monkeypatch.setattr(document_sniff, limit, 1)
    with pytest.raises(PackageInvalidError) as caught:
        import_package(source=source, data_dir=data, now=IMPORT_TIME)
    assert isinstance(caught.value.__cause__, document_sniff.ArchiveTooLargeError)
    assert snapshot(directory=data) == before

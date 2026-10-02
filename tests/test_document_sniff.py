import struct
from pathlib import Path
from zipfile import ZipFile

import pytest

from sbobina.document_models import DocumentKind
from sbobina.document_sniff import (
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVE_ENTRIES,
    ArchiveTooLargeError,
    check_archive_limits,
    sniff_document,
)

CENTRAL_DIRECTORY_SIGNATURE = b"PK\x01\x02"
UNCOMPRESSED_SIZE_OFFSET = 24
LOCAL_COMPRESSION_OFFSET = 8
CENTRAL_COMPRESSION_OFFSET = 10
LOCAL_FLAGS_OFFSET = 6
CENTRAL_FLAGS_OFFSET = 8


def write_archive(path: Path, declared_size: int) -> None:
    with ZipFile(path, mode="w") as archive:
        archive.writestr("payload", b"x")
    data = bytearray(path.read_bytes())
    offset = data.index(CENTRAL_DIRECTORY_SIGNATURE) + UNCOMPRESSED_SIZE_OFFSET
    struct.pack_into("<I", data, offset, declared_size)
    path.write_bytes(data)


@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        ("lecture.bin", b"%PDF-1.7\n%%EOF", DocumentKind.PDF),
        ("notes.txt", "Perché è valido".encode(), DocumentKind.TXT),
        ("notes.MD", b"# Notes", DocumentKind.MD),
        ("notes.txt", b"", DocumentKind.TXT),
        ("fake.pdf", b"MZ\x90\x00\xff", None),
        ("fake.pdf", b"MZfake text without NUL", None),
        ("notes.docx", b"plain utf-8 text", None),
        ("notes.txt", b"hello\x00world", None),
        ("notes.md", b"hello\xffworld", None),
        ("notes.txt", b"a" * 8192 + b"\x00", None),
        ("notes.md", b"a" * 8192 + b"\xff", None),
        ("broken.docx", b"PK\x03\x04broken", None),
    ],
)
def test_sniff_document_content_identifies_kind(
    tmp_path: Path, name: str, content: bytes, expected: DocumentKind | None
) -> None:
    path = tmp_path / name
    path.write_bytes(content)
    assert sniff_document(head=content[:32], path=path, filename=name) == expected
    path.write_bytes(b"%PDF-1.7")
    assert (
        sniff_document(head=path.read_bytes(), path=path, filename=path.name)
        == DocumentKind.PDF
    )


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
            DocumentKind.DOCX,
        ),
        (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
            DocumentKind.PPTX,
        ),
        ("application/octet-stream", None),
        (None, None),
    ],
)
def test_sniff_document_zip_content_types_identifies_office(
    tmp_path: Path, content_type: str | None, expected: DocumentKind | None
) -> None:
    path = tmp_path / "office.zip"
    with ZipFile(path, mode="w") as archive:
        archive.writestr("payload", "hello")
        if content_type:
            archive.writestr(
                "[Content_Types].xml",
                f'<Types><Override ContentType="{content_type}"/></Types>',
            )
    assert (
        sniff_document(head=path.read_bytes()[:4], path=path, filename=path.name)
        == expected
    )
    path.write_bytes(b"%PDF-")
    assert (
        sniff_document(head=path.read_bytes(), path=path, filename=path.name)
        == DocumentKind.PDF
    )


@pytest.mark.parametrize("declared_size", [MAX_ARCHIVE_BYTES + 1, 1024**3])
def test_check_archive_limits_declared_bomb_rejected_without_inflation(
    tmp_path: Path, declared_size: int
) -> None:
    path = tmp_path / "bomb.zip"
    write_archive(path=path, declared_size=declared_size)
    with ZipFile(path) as archive:
        assert archive.infolist()[0].file_size == declared_size
    assert path.stat().st_size < 1024
    with pytest.raises(ArchiveTooLargeError) as caught:
        check_archive_limits(path)
    assert caught.value.code == "ARCHIVE_TOO_LARGE"
    write_archive(path=path, declared_size=MAX_ARCHIVE_BYTES)
    check_archive_limits(path)


def test_check_archive_limits_entry_count_rejects_over_limit(tmp_path: Path) -> None:
    path = tmp_path / "many.zip"
    with ZipFile(path, mode="w") as archive:
        for index in range(MAX_ARCHIVE_ENTRIES):
            archive.writestr(str(index), b"")
    check_archive_limits(path)
    with ZipFile(path, mode="a") as archive:
        archive.writestr("extra", b"")
    with pytest.raises(ArchiveTooLargeError, match="ARCHIVE_TOO_LARGE"):
        check_archive_limits(path)


def test_sniff_document_bomb_is_rejected_before_content_read(tmp_path: Path) -> None:
    path = tmp_path / "bomb.docx"
    write_archive(path=path, declared_size=1024**3)
    with pytest.raises(ArchiveTooLargeError):
        sniff_document(head=path.read_bytes()[:4], path=path, filename=path.name)


def test_check_archive_limits_total_size_rejects_sum(tmp_path: Path) -> None:
    path = tmp_path / "sum.zip"
    write_archive(path=path, declared_size=MAX_ARCHIVE_BYTES)
    with ZipFile(path, mode="a") as archive:
        archive.writestr("extra", b"x")
    with pytest.raises(ArchiveTooLargeError):
        check_archive_limits(path)


@pytest.mark.parametrize("is_encrypted", [False, True])
def test_sniff_document_unreadable_zip_returns_none(
    tmp_path: Path, is_encrypted: bool
) -> None:
    path = tmp_path / "unreadable.docx"
    with ZipFile(path, mode="w") as archive:
        archive.writestr("[Content_Types].xml", "wordprocessingml")
    assert (
        sniff_document(head=path.read_bytes()[:4], path=path, filename=path.name)
        == DocumentKind.DOCX
    )
    data = bytearray(path.read_bytes())
    central = data.index(CENTRAL_DIRECTORY_SIGNATURE)
    local_offset = LOCAL_FLAGS_OFFSET if is_encrypted else LOCAL_COMPRESSION_OFFSET
    central_offset = (
        CENTRAL_FLAGS_OFFSET if is_encrypted else CENTRAL_COMPRESSION_OFFSET
    )
    value = 1 if is_encrypted else 99
    struct.pack_into("<H", data, local_offset, value)
    struct.pack_into("<H", data, central + central_offset, value)
    path.write_bytes(data)
    assert sniff_document(head=bytes(data[:4]), path=path, filename=path.name) is None


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Appunti.MD", DocumentKind.MD),
        ("note.txt", DocumentKind.TXT),
        ("note.pdf", None),
    ],
)
def test_sniff_document_text_kind_follows_original_filename_not_storage_path(
    tmp_path: Path, filename: str, expected: DocumentKind | None
) -> None:
    # The API sniffs a temporary file with a fixed name: only the uploaded
    # filename can say whether UTF-8 text is a .md, a .txt, or a disguised file.
    path = tmp_path / "upload.part"
    path.write_bytes(b"# Titolo\n\ntesto")
    assert (
        sniff_document(head=path.read_bytes(), path=path, filename=filename) == expected
    )

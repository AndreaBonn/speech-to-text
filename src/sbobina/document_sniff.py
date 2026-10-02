import codecs
import zlib
from pathlib import Path, PurePath
from zipfile import BadZipFile, ZipFile

from sbobina.document_models import DocumentKind

MAX_ARCHIVE_BYTES = 500 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 10_000
READ_CHUNK_BYTES = 64 * 1024
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
CONTENT_TYPES_NAME = "[Content_Types].xml"
OFFICE_TYPES = {
    b"wordprocessingml": DocumentKind.DOCX,
    b"presentationml": DocumentKind.PPTX,
}
TEXT_SUFFIXES = {".txt": DocumentKind.TXT, ".md": DocumentKind.MD}
SIGNATURE_OVERLAP_BYTES = max(map(len, OFFICE_TYPES)) - 1


class ArchiveTooLargeError(ValueError):
    code = "ARCHIVE_TOO_LARGE"

    def __init__(self) -> None:
        super().__init__("ARCHIVE_TOO_LARGE")


def check_archive_limits(path: Path) -> None:
    """Reject oversized ZIP metadata without reading or extracting any entry."""
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if (
            len(entries) > MAX_ARCHIVE_ENTRIES
            or sum(entry.file_size for entry in entries) > MAX_ARCHIVE_BYTES
        ):
            raise ArchiveTooLargeError()


def _read_office_kind(archive: ZipFile) -> DocumentKind | None:
    kind = None
    tail = b""
    with archive.open(CONTENT_TYPES_NAME) as source:
        while chunk := source.read(READ_CHUNK_BYTES):
            content = tail + chunk
            for signature, candidate in OFFICE_TYPES.items():
                if signature in content:
                    kind = candidate
            tail = content[-SIGNATURE_OVERLAP_BYTES:]
    return kind


def _sniff_office(path: Path) -> DocumentKind | None:
    try:
        check_archive_limits(path=path)
        with ZipFile(path) as archive:
            return _read_office_kind(archive=archive)
    except (BadZipFile, KeyError, RuntimeError, NotImplementedError, zlib.error):
        return None


def _is_utf8_text(path: Path) -> bool:
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        with path.open("rb") as source:
            while chunk := source.read(READ_CHUNK_BYTES):
                if b"\x00" in chunk:
                    return False
                decoder.decode(chunk)
            decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return False
    return True


def sniff_document(head: bytes, path: Path, filename: str) -> DocumentKind | None:
    """Identify PDF/Office signatures or validate the whole file as UTF-8 text.

    Binary formats are told by their bytes. Text has no signature, so it is
    accepted only when the uploaded ``filename`` claims .txt or .md: a UTF-8
    file named .pdf is a disguised file, not a text document.
    """
    if head.startswith(b"%PDF-"):
        return DocumentKind.PDF
    if head.startswith(ZIP_SIGNATURES):
        return _sniff_office(path=path)
    kind = TEXT_SUFFIXES.get(PurePath(filename).suffix.casefold())
    if kind is None or not _is_utf8_text(path=path):
        return None
    return kind

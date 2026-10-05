"""Decode inventoried package content through domain loaders, without extraction."""

from dataclasses import dataclass
from hashlib import sha256
from zipfile import ZipFile

from pydantic import TypeAdapter

from sbobina.card_models import load_card_event
from sbobina.document_models import CourseDocument
from sbobina.generation_models import load_generation
from sbobina.models import transcript_from_json, transcript_to_json
from sbobina.package_export import OPTIONAL_LECTURE_FILES
from sbobina.package_models import InventoryEntry, Manifest
from sbobina.package_remap_types import PackageContent, PackageJob
from sbobina.package_validate import PackageInvalidError
from sbobina.package_zip import iter_member_bytes
from sbobina.study_render import STUDY_ADAPTER
from sbobina.web.document_store import DOCUMENT_FILENAME, TEXT_FILENAME, StoredText

JOB_ADAPTER = TypeAdapter(PackageJob)
DOCUMENT_ADAPTER = TypeAdapter(CourseDocument)
TEXT_ADAPTER = TypeAdapter(StoredText)
TRANSCRIPT_FILENAME = "audio.json"


@dataclass(frozen=True, kw_only=True)
class LoadedLecture:
    record: PackageJob
    files: dict[str, bytes]


@dataclass(frozen=True, kw_only=True)
class LoadedDocument:
    record: CourseDocument
    text: bytes | None
    original: bytes | None


@dataclass(frozen=True, kw_only=True)
class LoadedPackage:
    content: PackageContent
    lectures: tuple[LoadedLecture, ...]
    documents: tuple[LoadedDocument, ...]


def _read_member(archive: ZipFile, entry: InventoryEntry) -> bytes:
    chunks: list[bytes] = []
    size = 0
    digest = sha256()
    for chunk in iter_member_bytes(
        archive=archive, info=archive.getinfo(name=entry.path)
    ):
        size += len(chunk)
        if size > entry.size:
            raise PackageInvalidError("Package member changed after validation")
        digest.update(chunk)
        chunks.append(chunk)
    if size != entry.size or digest.hexdigest() != entry.sha256:
        raise PackageInvalidError("Package member changed after validation")
    return b"".join(chunks)


def _groups(members: dict[str, bytes], category: str) -> tuple[dict[str, bytes], ...]:
    groups: dict[str, dict[str, bytes]] = {}
    for path, payload in members.items():
        parts = path.split("/")
        if parts[0] == category:
            groups.setdefault(parts[1], {})[parts[2]] = payload
    return tuple(groups[index] for index in sorted(groups))


def _transcript_bytes(payload: bytes) -> bytes:
    transcript = transcript_from_json(content=payload.decode(encoding="utf-8"))
    return transcript_to_json(transcript=transcript).encode(encoding="utf-8")


def _load_lecture(members: dict[str, bytes]) -> LoadedLecture:
    record = JOB_ADAPTER.validate_json(members["meta.json"])
    files = {TRANSCRIPT_FILENAME: _transcript_bytes(payload=members["transcript.json"])}
    for target, member, kind in OPTIONAL_LECTURE_FILES:
        if member not in members:
            continue
        if kind == "corrected":
            files[target] = _transcript_bytes(payload=members[member])
        else:
            study = STUDY_ADAPTER.validate_json(members[member])
            files[target] = STUDY_ADAPTER.dump_json(study)
    return LoadedLecture(record=record, files=files)


def _load_document(members: dict[str, bytes]) -> LoadedDocument:
    record = DOCUMENT_ADAPTER.validate_json(members[DOCUMENT_FILENAME])
    original_name = f"original.{record.kind.value}"
    allowed = {DOCUMENT_FILENAME, TEXT_FILENAME, original_name}
    if members.keys() - allowed:
        raise PackageInvalidError("Original extension does not match document kind")
    text = None
    if TEXT_FILENAME in members:
        parsed = TEXT_ADAPTER.validate_json(members[TEXT_FILENAME])
        text = TEXT_ADAPTER.dump_json(parsed)
    return LoadedDocument(record=record, text=text, original=members.get(original_name))


def load_package(archive: ZipFile, manifest: Manifest) -> LoadedPackage:
    """Load only inventory members; missing required siblings are invalid packages."""
    members = {
        entry.path: _read_member(archive=archive, entry=entry)
        for entry in manifest.inventory
    }
    lectures = tuple(
        _load_lecture(members=group)
        for group in _groups(members=members, category="lectures")
    )
    documents = tuple(
        _load_document(members=group)
        for group in _groups(members=members, category="documents")
    )
    content = _package_content(members=members, lectures=lectures, documents=documents)
    return LoadedPackage(content=content, lectures=lectures, documents=documents)


def _package_content(
    members: dict[str, bytes],
    lectures: tuple[LoadedLecture, ...],
    documents: tuple[LoadedDocument, ...],
) -> PackageContent:
    return PackageContent(
        jobs=tuple(item.record for item in lectures),
        documents=tuple(item.record for item in documents),
        generations=tuple(
            load_generation(content=payload.decode(encoding="utf-8"))
            for path, payload in members.items()
            if path.startswith("generations/")
        ),
        cards=tuple(
            load_card_event(content=line)
            for line in members.get("cards/cards.jsonl", b"")
            .decode(encoding="utf-8")
            .splitlines()
            if line.strip()
        ),
    )

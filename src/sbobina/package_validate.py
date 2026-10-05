"""Validate package bytes without extraction; the HTTP layer limits upload size."""

import stat
import zlib
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import IO
from zipfile import BadZipFile, ZipFile, ZipInfo

from pydantic import ValidationError

from sbobina.document_sniff import MAX_ARCHIVE_BYTES
from sbobina.package_models import InventoryEntry, Manifest
from sbobina.package_zip import iter_member_bytes

MAX_PACKAGE_MEMBERS = 5_000
MAX_MEMBER_BYTES = 200 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MANIFEST_PATH = "manifest.json"
UNIX_MODE_SHIFT = 16


class PackageValidationError(ValueError):
    code = "PACKAGE_VALIDATION_ERROR"


class PackageInvalidError(PackageValidationError):
    code = "PACKAGE_INVALID"


class PackageTooLargeError(PackageValidationError):
    code = "PACKAGE_TOO_LARGE"


@dataclass(frozen=True, kw_only=True)
class ValidationLimits:
    members: int = MAX_PACKAGE_MEMBERS
    member_bytes: int = MAX_MEMBER_BYTES
    total_bytes: int = MAX_ARCHIVE_BYTES
    ratio: int = MAX_COMPRESSION_RATIO

    def __post_init__(self) -> None:
        bounds = (
            (self.members, MAX_PACKAGE_MEMBERS),
            (self.member_bytes, MAX_MEMBER_BYTES),
            (self.total_bytes, MAX_ARCHIVE_BYTES),
            (self.ratio, MAX_COMPRESSION_RATIO),
        )
        if any(value <= 0 or value > maximum for value, maximum in bounds):
            raise ValueError("Package limits must be positive and cannot exceed C5")


@dataclass(frozen=True, kw_only=True)
class ValidatedPackage:
    manifest: Manifest
    total_bytes: int


DEFAULT_LIMITS = ValidationLimits()


@dataclass(frozen=True, kw_only=True)
class _ReadResult:
    size: int
    digest: str
    data: bytes


def _safe_name(info: ZipInfo) -> str:
    name = info.orig_filename
    parts = name.split("/")
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or ".." in parts
        or PurePosixPath(name).is_absolute()
        or PureWindowsPath(name).drive
        or stat.S_ISLNK(info.external_attr >> UNIX_MODE_SHIFT)
    ):
        raise PackageInvalidError(f"Unsafe package member: {name!r}")
    return str(PurePosixPath(name))


def _index_members(archive: ZipFile, limits: ValidationLimits) -> dict[str, ZipInfo]:
    entries = archive.infolist()
    if len(entries) > limits.members:
        raise PackageTooLargeError("Too many ZIP members")
    normalized: set[str] = set()
    index = {}
    for info in entries:
        name = _safe_name(info=info)
        if name in normalized:
            raise PackageInvalidError(f"Duplicate package member: {name!r}")
        normalized.add(name)
        index[info.filename] = info
    return index


@dataclass(frozen=True, kw_only=True)
class _Reader:
    archive: ZipFile
    limits: ValidationLimits

    def read(self, info: ZipInfo, total: int, retain: bool = False) -> _ReadResult:
        size, crc, digest, chunks = 0, 0, sha256(), []
        for chunk in iter_member_bytes(archive=self.archive, info=info):
            size += len(chunk)
            self.check_size(info=info, size=size, total=total)
            digest.update(chunk)
            crc = zlib.crc32(chunk, crc)
            if retain:
                chunks.append(chunk)
        if size != info.file_size or crc != info.CRC:
            raise PackageInvalidError("ZIP member size or CRC differs from its header")
        return _ReadResult(size=size, digest=digest.hexdigest(), data=b"".join(chunks))

    def check_size(self, info: ZipInfo, size: int, total: int) -> None:
        if (
            size > self.limits.member_bytes
            or total + size > self.limits.total_bytes
            or size > info.compress_size * self.limits.ratio
        ):
            raise PackageTooLargeError("Package exceeds decompression limits")


def _inventory(
    manifest: Manifest, limits: ValidationLimits
) -> tuple[InventoryEntry, ...]:
    entries = manifest.inventory
    if len(entries) > limits.members:
        raise PackageTooLargeError("Too many manifest members")
    if len({entry.path for entry in entries}) != len(entries):
        raise PackageInvalidError("Duplicate manifest member")
    return entries


def _validate(archive: ZipFile, limits: ValidationLimits) -> ValidatedPackage:
    index = _index_members(archive=archive, limits=limits)
    if MANIFEST_PATH not in index:
        raise PackageInvalidError("Missing manifest.json")
    reader = _Reader(archive=archive, limits=limits)
    content = reader.read(info=index[MANIFEST_PATH], total=0, retain=True)
    manifest = Manifest.model_validate_json(json_data=content.data)
    total = content.size
    for entry in _inventory(manifest=manifest, limits=limits):
        if entry.path not in index:
            raise PackageInvalidError(f"Missing member: {entry.path}")
        member = reader.read(info=index[entry.path], total=total)
        if member.size != entry.size or member.digest != entry.sha256:
            raise PackageInvalidError(f"Member size or SHA256 mismatch: {entry.path}")
        total += member.size
    return ValidatedPackage(manifest=manifest, total_bytes=total)


def validate_package(
    source: Path | IO[bytes],
    limits: ValidationLimits = DEFAULT_LIMITS,
) -> ValidatedPackage:
    """Check member safety, actual byte budgets and manifest integrity.

    Parameters
    ----------
    source : Path or binary stream
        Seekable package source, never extracted; caller-owned streams stay open.
    limits : ValidationLimits
        C5 budgets, optionally reduced by the caller. The manifest counts toward
        ZIP member and byte budgets. Safe unlisted payloads are never opened.
    """
    try:
        with ZipFile(file=source, mode="r") as archive:
            return _validate(archive=archive, limits=limits)
    except (
        BadZipFile,
        zlib.error,
        RuntimeError,
        NotImplementedError,
        EOFError,
        UnicodeDecodeError,
        ValidationError,
    ) as error:
        raise PackageInvalidError(str(error)) from error

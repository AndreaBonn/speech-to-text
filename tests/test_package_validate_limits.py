import zlib
from dataclasses import replace
from io import BytesIO
from random import Random
from zipfile import ZIP_BZIP2, ZipFile, ZipInfo

import pytest
from package_validation_fixtures import (
    END_HEADER,
    MANIFEST_PATH,
    PAYLOAD_PATH,
    change_manifest,
    forge_size,
    payload_package,
    raw_member,
    unpack_package,
    zip_bytes,
)
from test_package_validate import exported, valid_manifest

from sbobina.document_sniff import READ_CHUNK_BYTES
from sbobina.package_models import Manifest
from sbobina.package_validate import (
    DEFAULT_LIMITS,
    MAX_PACKAGE_MEMBERS,
    PackageInvalidError,
    PackageTooLargeError,
    ValidationLimits,
    validate_package,
)

__all__ = ["exported"]
PAYLOAD_BYTES = 128 * 1024
RANDOM_SEED = 73
EMPTY_DEFLATE_BLOCK = bytes.fromhex("000000ffff")
EMPTY_BLOCK_COUNT = 150


def buffered_deflate_package(manifest: Manifest, payload: bytes) -> bytes:
    members = unpack_package(data=payload_package(manifest=manifest, data=payload))
    locals_, centrals = bytearray(), bytearray()
    for name, data in members:
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        compressed = compressor.compress(data) + compressor.flush()
        if name == PAYLOAD_PATH:
            compressed = EMPTY_DEFLATE_BLOCK * EMPTY_BLOCK_COUNT + compressed
        local, central = raw_member(
            name=name, data=data, compressed=compressed, offset=len(locals_)
        )
        locals_.extend(local)
        centrals.extend(central)
    end = END_HEADER.pack(
        b"PK\x05\x06", 0, 0, len(members), len(members), len(centrals), len(locals_), 0
    )
    return bytes(locals_ + centrals + end)


def test_validate_package_buffered_deflate_tail_accepted(exported: bytes) -> None:
    manifest = valid_manifest(data=exported)
    payload = b"a" * (READ_CHUNK_BYTES + 1)
    package = buffered_deflate_package(manifest=manifest, payload=payload)
    with ZipFile(file=BytesIO(package)) as archive:
        assert archive.read(name=PAYLOAD_PATH) == payload
        assert (
            len(payload)
            <= archive.getinfo(name=PAYLOAD_PATH).compress_size * DEFAULT_LIMITS.ratio
        )
    result = validate_package(source=BytesIO(package))
    assert result.manifest.inventory[0].size == len(payload)


def test_validate_package_byte_limits_accept_boundary_reject_excess(
    exported: bytes,
) -> None:
    manifest = valid_manifest(data=exported)
    data = payload_package(
        manifest=manifest, data=Random(RANDOM_SEED).randbytes(PAYLOAD_BYTES)
    )
    total = sum(len(content) for _, content in unpack_package(data=data))
    limits = ValidationLimits(member_bytes=PAYLOAD_BYTES, total_bytes=total)
    assert validate_package(source=BytesIO(data), limits=limits).total_bytes == total
    for reduced in (
        replace(limits, member_bytes=PAYLOAD_BYTES - 1),
        replace(limits, total_bytes=total - 1),
    ):
        with pytest.raises(PackageTooLargeError):
            validate_package(source=BytesIO(data), limits=reduced)


def test_validate_package_false_header_member_budget_enforced(exported: bytes) -> None:
    manifest = valid_manifest(data=exported)
    data = payload_package(
        manifest=manifest, data=Random(RANDOM_SEED).randbytes(PAYLOAD_BYTES)
    )
    result = validate_package(source=BytesIO(data))
    assert result.manifest.inventory[0].size == PAYLOAD_BYTES
    with pytest.raises(PackageTooLargeError):
        validate_package(
            source=BytesIO(forge_size(data=data)),
            limits=ValidationLimits(member_bytes=PAYLOAD_BYTES - 1),
        )
    with pytest.raises(PackageInvalidError, match="differs from its header"):
        validate_package(source=BytesIO(forge_size(data=data)))


def test_validate_package_member_count_boundary_enforced(exported: bytes) -> None:
    valid_manifest(data=exported)
    members = unpack_package(data=exported)
    members.extend(
        (f"extra/{index}", b"") for index in range(MAX_PACKAGE_MEMBERS - len(members))
    )
    assert (
        validate_package(
            source=BytesIO(zip_bytes(members=members))
        ).manifest.course.label
        == "Fisica"
    )
    with pytest.raises(PackageTooLargeError, match="Too many ZIP members"):
        validate_package(
            source=BytesIO(zip_bytes(members=[*members, ("one-too-many", b"")]))
        )


def test_validate_package_manifest_count_enforced(exported: bytes) -> None:
    manifest = valid_manifest(data=exported)
    inventory = manifest.model_dump(mode="json")["inventory"]
    hostile = change_manifest(
        data=exported, changes={"inventory": [inventory[0]] * (MAX_PACKAGE_MEMBERS + 1)}
    )
    hostile = zip_bytes(
        members=[
            (ZipInfo(filename=name) if name == MANIFEST_PATH else name, data)
            for name, data in unpack_package(data=hostile)
        ]
    )
    with pytest.raises(PackageTooLargeError, match="Too many manifest members"):
        validate_package(source=BytesIO(hostile))


def test_validate_package_corrupt_crc_and_unsupported_compression_rejected(
    exported: bytes,
) -> None:
    valid_manifest(data=exported)
    data = bytearray(exported)
    with ZipFile(file=BytesIO(exported)) as archive:
        central = data.index(b"PK\x01\x02")
        assert archive.infolist()[0].CRC > 0
    crc_offset = 16
    data[central + crc_offset] ^= 1
    with pytest.raises(PackageInvalidError, match="CRC"):
        validate_package(source=BytesIO(data))
    info = ZipInfo(filename=MANIFEST_PATH)
    info.compress_type = ZIP_BZIP2
    with pytest.raises(PackageInvalidError, match="compression"):
        validate_package(source=BytesIO(zip_bytes(members=[(info, b"{}")])))


def test_validation_limits_only_allow_stricter_budgets() -> None:
    assert replace(DEFAULT_LIMITS, members=1).members == 1
    for invalid in (0, DEFAULT_LIMITS.members + 1):
        with pytest.raises(ValueError, match="cannot exceed C5"):
            ValidationLimits(members=invalid)

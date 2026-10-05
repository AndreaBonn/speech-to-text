import json
import stat
import zlib
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest
from package_fixtures import NOW, seed_package
from package_validation_fixtures import (
    BOMB_BYTES,
    FALSE_SIZE,
    MANIFEST_PATH,
    PAYLOAD_PATH,
    change_manifest,
    forge_size,
    malformed_deflate,
    payload_package,
    unpack_package,
    zip_bytes,
)

from sbobina.package_export import ExportRequest, write_package
from sbobina.package_models import ExportOptions, Manifest
from sbobina.package_validate import (
    PackageInvalidError,
    PackageTooLargeError,
    PackageVersionError,
    ValidationLimits,
    validate_package,
)


@pytest.fixture
def exported(tmp_path: Path) -> bytes:
    data = seed_package(tmp_path=tmp_path)
    target = BytesIO()
    write_package(
        target=target,
        request=ExportRequest(
            store=data.store,
            course=data.course,
            now=NOW,
            options=ExportOptions(),
        ),
    )
    return target.getvalue()


def valid_manifest(data: bytes) -> Manifest:
    result = validate_package(source=BytesIO(data))
    assert result.manifest.course.label == "Fisica"
    assert len(result.manifest.inventory) == 12
    assert result.total_bytes > 0
    return result.manifest


def assert_rejected(data: bytes, code: str = "PACKAGE_INVALID") -> None:
    with pytest.raises((PackageInvalidError, PackageTooLargeError)) as error:
        validate_package(source=BytesIO(data))
    assert error.value.code == code


@pytest.mark.parametrize(
    "name",
    [
        "/etc/passwt",
        "../../etc/passwd",
        "lectures\\0\\meta.json",
        "C:/lectures/0/meta.json",
        "C:\\lectures\\0\\meta.json",
    ],
)
def test_validate_package_unsafe_path_rejected(exported: bytes, name: str) -> None:
    valid_manifest(data=exported)
    assert_rejected(
        data=zip_bytes(members=[*unpack_package(data=exported), (name, b"bad")])
    )


def test_validate_package_symlink_rejected(exported: bytes, tmp_path: Path) -> None:
    valid_manifest(data=exported)
    target = tmp_path / "link"
    target.symlink_to("outside")
    info = ZipInfo(filename="link")
    info.create_system = 3
    info.external_attr = target.lstat().st_mode << 16
    assert stat.S_ISLNK(info.external_attr >> 16)
    assert_rejected(
        data=zip_bytes(members=[*unpack_package(data=exported), (info, b"outside")])
    )


@pytest.mark.parametrize(
    "duplicate", ["lectures/0/meta.json", "lectures/./0/meta.json"]
)
def test_validate_package_duplicate_rejected(exported: bytes, duplicate: str) -> None:
    valid_manifest(data=exported)
    members = [*unpack_package(data=exported), (duplicate, b"duplicate")]
    if duplicate == "lectures/0/meta.json":
        with pytest.warns(UserWarning, match="Duplicate name"):
            hostile = zip_bytes(members=members)
    else:
        hostile = zip_bytes(members=members)
    assert_rejected(data=hostile)


def test_validate_package_unlisted_payload_ignored(exported: bytes) -> None:
    manifest = valid_manifest(data=exported)
    members = [*unpack_package(data=exported), ("extra.bin", b"x" * BOMB_BYTES)]
    result = validate_package(source=BytesIO(zip_bytes(members=members)))
    assert result.manifest == manifest
    assert result.total_bytes == validate_package(source=BytesIO(exported)).total_bytes
    assert_rejected(data=zip_bytes(members=[("extra.bin", b"alone")]))


@pytest.mark.parametrize("forged_crc", [False, True])
def test_validate_package_false_header_counts_real_bytes(
    exported: bytes, forged_crc: bool
) -> None:
    manifest = valid_manifest(data=exported)
    payload = b"a" * BOMB_BYTES
    data = payload_package(manifest=manifest, data=payload)
    crc = zlib.crc32(payload[:FALSE_SIZE]) if forged_crc else None
    hostile = forge_size(data=data, crc=crc)
    with ZipFile(file=BytesIO(hostile)) as archive:
        assert archive.getinfo(name=PAYLOAD_PATH).file_size == FALSE_SIZE
        if forged_crc:
            assert archive.read(name=PAYLOAD_PATH) == payload[:FALSE_SIZE]
    assert_rejected(data=hostile, code="PACKAGE_TOO_LARGE")


def test_validate_package_compression_bomb_rejected(exported: bytes) -> None:
    manifest = valid_manifest(data=exported)
    data = payload_package(manifest=manifest, data=b"a" * BOMB_BYTES)
    with ZipFile(file=BytesIO(data)) as archive:
        info = archive.getinfo(name=PAYLOAD_PATH)
        assert BOMB_BYTES / info.compress_size >= 1000
    assert_rejected(data=data, code="PACKAGE_TOO_LARGE")


@pytest.mark.parametrize("field,value", [("sha256", "0" * 64), ("size", 1)])
def test_validate_package_inventory_mismatch_rejected(
    exported: bytes, field: str, value: object
) -> None:
    manifest = valid_manifest(data=exported)
    inventory = manifest.model_dump(mode="json")["inventory"]
    inventory[0][field] = value
    assert_rejected(
        data=change_manifest(data=exported, changes={"inventory": inventory})
    )


def test_validate_package_future_version_rejected(exported: bytes) -> None:
    valid_manifest(data=exported)
    with pytest.raises(PackageVersionError) as raised:
        validate_package(
            source=BytesIO(
                change_manifest(data=exported, changes={"format_version": 2})
            )
        )
    assert raised.value.code == "PACKAGE_VERSION_UNSUPPORTED"
    assert isinstance(raised.value, PackageInvalidError)


def test_validate_package_nested_zip_is_opaque(exported: bytes) -> None:
    manifest = valid_manifest(data=exported)
    nested = zip_bytes(members=[("../../escape", b"a" * BOMB_BYTES)])
    package = payload_package(manifest=manifest, data=nested)
    result = validate_package(source=BytesIO(package))
    assert result.manifest.inventory[0].size == len(nested)
    assert_rejected(data=nested)


def test_validate_package_success_and_failure_write_nothing(
    exported: bytes, tmp_path: Path
) -> None:
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    valid_manifest(data=exported)
    assert_rejected(data=zip_bytes(members=[("../../escape", b"bad")]))
    after = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


@pytest.mark.parametrize("field", ["member_bytes", "total_bytes", "members", "ratio"])
def test_validate_package_limits_enforced(exported: bytes, field: str) -> None:
    valid_manifest(data=exported)
    limits = ValidationLimits(**{field: 1})
    with pytest.raises(PackageTooLargeError) as error:
        validate_package(source=BytesIO(exported), limits=limits)
    assert error.value.code == "PACKAGE_TOO_LARGE"


def test_validate_package_manifest_duplicates_and_missing_rejected(
    exported: bytes,
) -> None:
    manifest = valid_manifest(data=exported)
    inventory = manifest.model_dump(mode="json")["inventory"]
    assert_rejected(
        data=change_manifest(
            data=exported, changes={"inventory": [*inventory, inventory[0]]}
        )
    )
    assert_rejected(
        data=zip_bytes(
            members=[
                (name, data)
                for name, data in unpack_package(data=exported)
                if name != inventory[0]["path"]
            ]
        )
    )


def test_validate_package_invalid_manifest_and_archive_rejected(
    exported: bytes,
) -> None:
    valid_manifest(data=exported)
    assert_rejected(data=b"not a zip")
    assert_rejected(data=zip_bytes(members=[(MANIFEST_PATH, b"not json")]))
    assert_rejected(
        data=zip_bytes(members=[(MANIFEST_PATH, json.dumps(obj={}).encode())])
    )


@pytest.mark.parametrize("mode", ["padding", "truncated"])
def test_validate_package_malformed_deflate_rejected(
    exported: bytes, mode: str
) -> None:
    manifest = valid_manifest(data=exported)
    payload = b"a" * BOMB_BYTES if mode == "padding" else bytes(range(256)) * 10
    assert_rejected(
        data=malformed_deflate(manifest=manifest, payload=payload, mode=mode)
    )


def test_validate_package_payload_and_cumulative_limits(exported: bytes) -> None:
    manifest = valid_manifest(data=exported)
    payload = bytes(range(256)) * 10
    data = payload_package(manifest=manifest, data=payload)
    result = validate_package(source=BytesIO(data))
    exact = ValidationLimits(member_bytes=len(payload), total_bytes=result.total_bytes)
    assert validate_package(source=BytesIO(data), limits=exact) == result
    for limits in (
        ValidationLimits(member_bytes=len(payload) - 1),
        ValidationLimits(total_bytes=result.total_bytes - 1),
    ):
        with pytest.raises(PackageTooLargeError):
            validate_package(source=BytesIO(data), limits=limits)

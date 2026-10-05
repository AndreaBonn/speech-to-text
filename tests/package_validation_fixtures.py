import json
import struct
import zlib
from collections.abc import Sequence
from hashlib import sha256
from io import BytesIO
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from sbobina.package_models import Manifest

MANIFEST_PATH = "manifest.json"
PAYLOAD_PATH = "documents/0/original.txt"
LOCAL_SIZE_OFFSET = 22
CENTRAL_SIZE_OFFSET = 24
LOCAL_CRC_OFFSET = 14
CENTRAL_CRC_OFFSET = 16
FALSE_SIZE = 10
BOMB_BYTES = 10 * 1024 * 1024
LOCAL_HEADER = struct.Struct("<4s5H3I2H")
CENTRAL_HEADER = struct.Struct("<4s6H3I5H2I")
END_HEADER = struct.Struct("<4s4H2IH")
ZIP_VERSION = 20


def raw_member(
    name: str, data: bytes, compressed: bytes, offset: int
) -> tuple[bytes, bytes]:
    encoded = name.encode()
    metadata = (
        0,
        ZIP_DEFLATED,
        0,
        0,
        zlib.crc32(data),
        len(compressed),
        len(data),
        len(encoded),
        0,
    )
    local = LOCAL_HEADER.pack(b"PK\x03\x04", ZIP_VERSION, *metadata)
    central = CENTRAL_HEADER.pack(
        b"PK\x01\x02", ZIP_VERSION, ZIP_VERSION, *metadata, 0, 0, 0, 0, offset
    )
    return local + encoded + compressed, central + encoded


def malformed_deflate(manifest: Manifest, payload: bytes, mode: str) -> bytes:
    members = unpack_package(data=payload_package(manifest=manifest, data=payload))
    locals_, centrals = bytearray(), bytearray()
    for name, data in members:
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        compressed = compressor.compress(data) + compressor.flush()
        if name == PAYLOAD_PATH:
            compressed = (
                compressed + bytes(len(payload))
                if mode == "padding"
                else compressed[:-1]
            )
        local, central = raw_member(
            name=name, data=data, compressed=compressed, offset=len(locals_)
        )
        locals_.extend(local)
        centrals.extend(central)
    end = END_HEADER.pack(
        b"PK\x05\x06", 0, 0, len(members), len(members), len(centrals), len(locals_), 0
    )
    return bytes(locals_ + centrals + end)


def zip_bytes(members: Sequence[tuple[str | ZipInfo, bytes]]) -> bytes:
    target = BytesIO()
    with ZipFile(file=target, mode="w", compression=ZIP_DEFLATED) as archive:
        for name, data in members:
            archive.writestr(zinfo_or_arcname=name, data=data)
    return target.getvalue()


def unpack_package(data: bytes) -> list[tuple[str, bytes]]:
    with ZipFile(file=BytesIO(data)) as archive:
        return [(name, archive.read(name=name)) for name in archive.namelist()]


def payload_package(manifest: Manifest, data: bytes) -> bytes:
    raw = manifest.model_dump(mode="json")
    raw["inventory"] = [
        {
            "path": PAYLOAD_PATH,
            "kind": "original",
            "size": len(data),
            "sha256": sha256(data).hexdigest(),
        }
    ]
    return zip_bytes(
        members=[(PAYLOAD_PATH, data), (MANIFEST_PATH, json.dumps(obj=raw).encode())]
    )


def change_manifest(data: bytes, changes: dict[str, Any]) -> bytes:
    members = unpack_package(data=data)
    raw = json.loads(
        next(content for name, content in members if name == MANIFEST_PATH)
    )
    raw.update(changes)
    return zip_bytes(
        members=[
            (name, json.dumps(obj=raw).encode() if name == MANIFEST_PATH else content)
            for name, content in members
        ]
    )


def forge_size(data: bytes, *, crc: int | None = None) -> bytes:
    forged = bytearray(data)
    central = forged.index(b"PK\x01\x02")
    struct.pack_into("<I", forged, LOCAL_SIZE_OFFSET, FALSE_SIZE)
    struct.pack_into("<I", forged, central + CENTRAL_SIZE_OFFSET, FALSE_SIZE)
    if crc is not None:
        struct.pack_into("<I", forged, LOCAL_CRC_OFFSET, crc)
        struct.pack_into("<I", forged, central + CENTRAL_CRC_OFFSET, crc)
    return bytes(forged)

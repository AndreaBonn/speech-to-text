import struct
import zlib
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

import pytest

from sbobina.package_zip import _compressed_chunks, _inflate, iter_member_bytes

LOCAL_HEADER_METHOD_OFFSET = 8
PAYLOAD = b"contenuto della lezione " * 100


def _archive_bytes(compression: int) -> bytes:
    buffer = BytesIO()
    with ZipFile(file=buffer, mode="w", compression=compression) as archive:
        archive.writestr(zinfo_or_arcname="member.txt", data=PAYLOAD)
    return buffer.getvalue()


def _raw_deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return compressor.compress(data) + compressor.flush()


@pytest.mark.parametrize("compression", [ZIP_STORED, ZIP_DEFLATED])
def test_iter_member_bytes_decodes_stored_and_deflated(compression: int) -> None:
    with ZipFile(file=BytesIO(_archive_bytes(compression=compression))) as archive:
        info = archive.getinfo(name="member.txt")
        assert b"".join(iter_member_bytes(archive=archive, info=info)) == PAYLOAD


def test_iter_member_bytes_closed_archive_raises_bad_zip_file() -> None:
    archive = ZipFile(file=BytesIO(_archive_bytes(compression=ZIP_STORED)))
    info = archive.getinfo(name="member.txt")
    archive.close()

    with pytest.raises(BadZipFile, match="Closed package archive"):
        list(iter_member_bytes(archive=archive, info=info))


def test_iter_member_bytes_local_header_method_mismatch_is_rejected() -> None:
    # The central directory says STORED while the local header says DEFLATED:
    # a reader trusting either one alone would decode the other's bytes.
    data = bytearray(_archive_bytes(compression=ZIP_STORED))
    struct.pack_into("<H", data, LOCAL_HEADER_METHOD_OFFSET, ZIP_DEFLATED)
    with ZipFile(file=BytesIO(bytes(data))) as archive:
        info = archive.getinfo(name="member.txt")
        with pytest.raises(BadZipFile, match="Inconsistent ZIP local header"):
            list(iter_member_bytes(archive=archive, info=info))


def test_compressed_chunks_source_shorter_than_declared_size_is_rejected() -> None:
    assert list(_compressed_chunks(source=BytesIO(b"abcd"), size=4)) == [b"abcd"]
    with pytest.raises(BadZipFile, match="Truncated ZIP payload"):
        list(_compressed_chunks(source=BytesIO(b"abcd"), size=10))


def test_inflate_data_after_stream_end_in_a_later_chunk_is_rejected() -> None:
    stream = _raw_deflate(data=PAYLOAD)
    assert b"".join(_inflate(chunks=iter([stream]))) == PAYLOAD
    with pytest.raises(BadZipFile, match="Trailing ZIP compressed data"):
        list(_inflate(chunks=iter([stream, b"junk"])))

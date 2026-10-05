"""Bounded ZIP payload decoding independent of declared uncompressed sizes."""

import struct
import zlib
from collections.abc import Iterator
from typing import IO
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from sbobina.document_sniff import READ_CHUNK_BYTES

LOCAL_HEADER = struct.Struct("<4s5H3I2H")
HEADER_FLAGS_INDEX = 2
HEADER_METHOD_INDEX = 3
HEADER_NAME_LENGTH_INDEX = 9
HEADER_EXTRA_LENGTH_INDEX = 10


def _payload_source(archive: ZipFile, info: ZipInfo) -> IO[bytes]:
    # Let zipfile check names, encryption and overlapping offsets, but never
    # read through ZipExtFile: it truncates output to the untrusted file_size.
    with archive.open(name=info):
        pass
    source = archive.fp
    if source is None:
        raise BadZipFile("Closed package archive")
    source.seek(info.header_offset)
    header = LOCAL_HEADER.unpack(source.read(LOCAL_HEADER.size))
    if (
        header[HEADER_FLAGS_INDEX] != info.flag_bits
        or header[HEADER_METHOD_INDEX] != info.compress_type
    ):
        raise BadZipFile("Inconsistent ZIP local header")
    offset = info.header_offset + LOCAL_HEADER.size
    offset += header[HEADER_NAME_LENGTH_INDEX] + header[HEADER_EXTRA_LENGTH_INDEX]
    source.seek(offset)
    return source


def _compressed_chunks(source: IO[bytes], size: int) -> Iterator[bytes]:
    remaining = size
    while remaining:
        chunk = source.read(min(remaining, READ_CHUNK_BYTES))
        if not chunk:
            raise BadZipFile("Truncated ZIP payload")
        remaining -= len(chunk)
        yield chunk


def _inflate(chunks: Iterator[bytes]) -> Iterator[bytes]:
    decoder = zlib.decompressobj(wbits=-zlib.MAX_WBITS)
    for chunk in chunks:
        if decoder.eof:
            raise BadZipFile("Trailing ZIP compressed data")
        pending = chunk
        while pending:
            output = decoder.decompress(pending, max_length=READ_CHUNK_BYTES)
            if decoder.unused_data:
                raise BadZipFile("Trailing ZIP compressed data")
            yield output
            pending = decoder.unconsumed_tail
    # zlib can retain output even after consuming every compressed input byte.
    while output := decoder.decompress(b"", max_length=READ_CHUNK_BYTES):
        yield output
    if not decoder.eof:
        raise BadZipFile("Truncated DEFLATE stream")


def iter_member_bytes(archive: ZipFile, info: ZipInfo) -> Iterator[bytes]:
    """Decode STORED/DEFLATED payloads without trusting uncompressed lengths."""
    if info.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
        raise BadZipFile("Unsupported ZIP compression method")
    source = _payload_source(archive=archive, info=info)
    chunks = _compressed_chunks(source=source, size=info.compress_size)
    if info.compress_type == ZIP_STORED:
        yield from chunks
    else:
        yield from _inflate(chunks=chunks)

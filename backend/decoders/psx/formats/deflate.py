"""Find raw deflate-compressed streams in binary data."""

import zlib
from dataclasses import dataclass


@dataclass
class DeflateStream:
    data_start: int
    compressed_size: int
    decompressed_size: int
    data: bytes


#: The most one stream may unpack to. A stream that has not ended by then
#: is not taken.
MAX_OUTPUT = 1 << 20


def find_deflate_streams(data: bytes, search_start: int) -> list[DeflateStream]:
    """Scan data for all valid raw deflate streams starting from search_start.

    A stream is taken only where it ends (its last block within the data and
    within MAX_OUTPUT), unpacking to 10 bytes or more; the scan goes on after
    its last byte."""
    streams = []
    view = memoryview(data)
    pos = search_start

    while pos < len(data) - 2:
        try:
            d = zlib.decompressobj(-15)
            result = d.decompress(view[pos:], MAX_OUTPUT)
            if d.eof and len(result) >= 10:
                consumed = len(data) - pos - len(d.unused_data)
                streams.append(DeflateStream(
                    data_start=pos,
                    compressed_size=consumed,
                    decompressed_size=len(result),
                    data=result,
                ))
                pos += consumed
                continue
        except zlib.error:
            pass
        pos += 1

    return streams

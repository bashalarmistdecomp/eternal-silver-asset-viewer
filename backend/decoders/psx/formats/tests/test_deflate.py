"""Raw-deflate stream discovery inside a binary blob.

This is a scanner, not a parser: it walks a blob byte by byte looking for
positions where zlib will accept a raw deflate stream. The risk it carries
is false positives, so the tests below pin both that it finds real streams
at the right offsets and that it does not invent them in flat data.
"""

import zlib

from decoders.psx.formats import deflate
from decoders.psx.formats.deflate import find_deflate_streams


def _raw(payload, level=9):
    co = zlib.compressobj(level, zlib.DEFLATED, -15)
    return co.compress(payload) + co.flush()


PAYLOAD = b"LUNAR SILVER STAR STORY COMPLETE " * 8


def test_finds_a_stream_at_its_offset():
    blob = b"\x00" * 64 + _raw(PAYLOAD)
    streams = find_deflate_streams(blob, 0)
    assert any(s.data == PAYLOAD for s in streams)
    hit = next(s for s in streams if s.data == PAYLOAD)
    assert hit.data_start == 64
    assert hit.decompressed_size == len(PAYLOAD)


def test_honours_search_start():
    blob = _raw(PAYLOAD) + b"\x00" * 32 + _raw(PAYLOAD)
    second = len(_raw(PAYLOAD)) + 32
    streams = find_deflate_streams(blob, second)
    assert all(s.data_start >= second for s in streams)


def test_finds_consecutive_streams():
    blob = _raw(PAYLOAD) + _raw(PAYLOAD[::-1])
    found = [s.data for s in find_deflate_streams(blob, 0)]
    assert PAYLOAD in found
    assert PAYLOAD[::-1] in found


def test_ignores_flat_data():
    # Ten bytes is the module's minimum useful output; zeros must not
    # produce a stream that long.
    assert find_deflate_streams(b"\x00" * 4096, 0) == []


def test_short_input_is_safe():
    assert find_deflate_streams(b"", 0) == []
    assert find_deflate_streams(b"\x78", 0) == []



def test_a_stream_cut_off_by_the_end_of_the_data_is_not_taken():
    blob = _raw(PAYLOAD[::-1]) + _raw(PAYLOAD)[:-4]
    assert [s.data for s in find_deflate_streams(blob, 0)] == [PAYLOAD[::-1]]


def test_a_stream_longer_than_the_cap_is_not_taken_nor_hides_the_next(monkeypatch):
    monkeypatch.setattr(deflate, "MAX_OUTPUT", 100)
    blob = _raw(PAYLOAD) + _raw(PAYLOAD[:40])     # 264 bytes, then 40
    assert [s.data for s in find_deflate_streams(blob, 0)] == [PAYLOAD[:40]]

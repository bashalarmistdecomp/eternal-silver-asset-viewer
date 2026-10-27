"""Tier-1 tests for the STR streaming container — synthetic bytes only."""

import struct

from decoders.psx.formats import str_stream as S


def _sector(frame_no, sec_off, sec_size, frame_size, payload=b"",
            status=0x0160, type_=0x8001, width=320, height=240):
    h = struct.pack("<HHHHIIHHII", status, type_, sec_off, sec_size,
                    frame_no, frame_size, width, height, 0x38001060,
                    0x00020001)
    h += b"\0" * (S.HEADER_SIZE - len(h))
    body = payload + bytes(S.PAYLOAD_SIZE - len(payload))
    return h + body


def _audio_sector():
    """An interleaved XA sector: no STR header, as seen in _B000.STR."""
    return bytes([0x0C, 0x0C, 0x0C, 0x0C]) + bytes(S.SECTOR_SIZE - 4)


def test_header_fields_round_trip():
    h = S.parse_sector_header(_sector(7, 2, 5, 1234))
    assert (h.frame_no, h.sector_offset, h.sector_size) == (7, 2, 5)
    assert h.width == 320 and h.height == 240
    assert h.is_system_defined and h.is_mdec


def test_frame_size_is_bytes_not_long_words():
    """Sony documents long words; the shipped streams use bytes."""
    h = S.parse_sector_header(_sector(1, 0, 10, 6100))
    assert h.frame_size_bytes == 6100          # NOT 6100 * 4


def test_frame_reassembles_from_its_sectors():
    data = b"".join(_sector(1, i, 3, 8, payload=bytes([i + 1]))
                    for i in range(3))
    frames = list(S.iter_frames(data))
    assert len(frames) == 1
    f = frames[0]
    assert f.frame_no == 1 and f.sector_count == 3
    assert len(f.data) == 3 * S.PAYLOAD_SIZE
    # payload is the concatenation, in sector order
    assert f.data[0] == 1
    assert f.data[S.PAYLOAD_SIZE] == 2
    assert f.data[2 * S.PAYLOAD_SIZE] == 3


def test_bitstream_is_cropped_to_declared_size():
    data = b"".join(_sector(1, i, 2, 5, payload=b"\xAA" * 10)
                    for i in range(2))
    f = next(S.iter_frames(data))
    assert len(f.data) == 2 * S.PAYLOAD_SIZE      # uncropped
    assert f.bitstream == b"\xAA" * 5             # cropped to declared


def test_interleaved_audio_sector_does_not_break_a_frame():
    """The regression this module exists for.

    An XA sector lands mid-frame in real streams. A grouper that trusts
    every sector starts a bogus frame and LOSES the one in progress.
    """
    data = (_sector(2, 0, 3, 9) + _sector(2, 1, 3, 9)
            + _audio_sector()
            + _sector(2, 2, 3, 9))
    assert not S.looks_like_str_sector(
        S.parse_sector_header(_audio_sector()))
    frames = list(S.iter_frames(data))
    assert len(frames) == 1
    assert frames[0].frame_no == 2 and frames[0].sector_count == 3


def test_truncated_trailing_frame_is_dropped_not_emitted_short():
    data = _sector(4, 0, 3, 9) + _sector(4, 1, 3, 9)   # 2 of 3
    assert list(S.iter_frames(data)) == []


def test_probe_summarises_without_walking_every_frame():
    p = S.probe(_sector(1, 0, 10, 6100))
    assert p["mdec"] and p["width"] == 320 and p["height"] == 240
    assert p["sectors_per_frame"] == 10


def test_short_buffer_raises_rather_than_guessing():
    for bad in (b"", b"\0" * (S.HEADER_SIZE - 1)):
        try:
            S.parse_sector_header(bad)
        except ValueError:
            pass
        else:                                    # pragma: no cover
            raise AssertionError("expected ValueError")

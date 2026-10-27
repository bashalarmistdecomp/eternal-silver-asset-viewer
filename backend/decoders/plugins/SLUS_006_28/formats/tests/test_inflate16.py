"""The 16-bit-word DEFLATE variant (inflate_block_dynamic, 0x80021DD8).

The game reads the DEFLATE bitstream as 16-bit little-endian words instead
of bytes. Because both refills are LSB-first, that is bit-for-bit identical
to standard DEFLATE for Huffman-coded blocks — which makes zlib an
independent oracle for those, and these are the strongest tests in the
tier-1 set: zlib produces the stream, so only the reader is under test.

Stored blocks (btype 0) are where the two genuinely diverge, because the
game aligns to a 16-bit boundary where RFC 1951 aligns to 8. That
divergence is pinned rather than fixed: it is what the game's own code does.
"""

import random
import zlib

import pytest

from decoders.plugins.SLUS_006_28.formats import inflate16

PAYLOAD = (b"LUNAR SILVER STAR STORY COMPLETE " * 40) + bytes(range(256))


def _raw_deflate(payload, level):
    co = zlib.compressobj(level, zlib.DEFLATED, -15)
    raw = co.compress(payload) + co.flush()
    return raw + b"\x00" * (len(raw) % 2)      # the reader needs word pairs


def test_dynamic_huffman_matches_zlib():
    assert inflate16.decompress(_raw_deflate(PAYLOAD, 9)) == PAYLOAD


def test_fixed_huffman_matches_zlib():
    assert inflate16.decompress(_raw_deflate(PAYLOAD, 1)) == PAYLOAD


def test_short_payload_round_trips():
    small = b"AAAAAAAAAABBBBBBBBBBAAAAAAAAAA"
    assert inflate16.decompress(_raw_deflate(small, 9)) == small


def test_back_references_across_the_window():
    # Force long-distance matches so the 32KB ring buffer is exercised.
    payload = bytes(range(256)) * 200 + b"TAIL"
    assert inflate16.decompress(_raw_deflate(payload, 9)) == payload


def test_made_up_streams_match_zlib():
    """Short and long streams of few and many byte values, packed with
    fixed codes, dynamic ones and runs (copies that overlap what they
    copy): every one read back as zlib packed it."""
    rng = random.Random(7)
    for _ in range(60):
        values = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 40)))
        payload = bytes(rng.choice(values) for _ in range(rng.randrange(1, 3000)))
        for level, strategy in ((1, zlib.Z_FIXED), (9, zlib.Z_DEFAULT_STRATEGY),
                                (6, zlib.Z_RLE)):
            co = zlib.compressobj(level, zlib.DEFLATED, -15, 9, strategy)
            raw = co.compress(payload) + co.flush()
            assert inflate16.inflate(raw + b"\x00" * (len(raw) % 2)) == payload


def test_stored_blocks_diverge_from_rfc1951():
    """A pinned difference, not a bug.

    RFC 1951 aligns a stored block to the next BYTE; this reader aligns to
    the next 16-bit WORD, so a zlib-produced stored block decodes to
    garbage (this test's payload: 1,216 bytes in, 16,132 bytes out). If this
    test ever starts passing, the bit reader changed and the change needs to
    be justified against inflate_block_dynamic (0x80021DD8), not against zlib.
    """
    stored = _raw_deflate(PAYLOAD, 0)
    assert inflate16.decompress(stored) != PAYLOAD


def test_empty_input_does_not_hang_or_raise():
    assert inflate16.decompress(b"") == b""


def test_garbage_terminates():
    # btype 3 is invalid and must break the block loop rather than spin.
    assert isinstance(inflate16.decompress(b"\xFF" * 64), bytes)


def _copies_without_end() -> bytes:
    """A made-up dynamic block whose all-zero code is a 258-byte copy one
    back: past its end, where the reader reads zeros, it copies for ever."""
    bits = []

    def put(v, n):                          # a field, low bit first
        bits.extend((v >> i) & 1 for i in range(n))

    def code(c, n):                         # a Huffman code, high bit first
        bits.extend((c >> i) & 1 for i in reversed(range(n)))

    put(1, 1); put(2, 2)                    # last block, dynamic
    put(286 - 257, 5); put(0, 5); put(18 - 4, 4)
    # the code-length codes' order (RFC 1951 3.2.7): 16, 17, 18, 0, then
    # 8 and 7 outward to 14 and 1, then 15
    order = [16, 17, 18, 0] + [x for k in range(7) for x in (8 + k, 7 - k)] + [15]
    lengths = {1: 2, 2: 2, 18: 2}           # codes: 1 -> 00, 2 -> 01, 18 -> 10
    for s in order[:18]:
        put(lengths.get(s, 0), 3)
    code(0b10, 2); put(138 - 11, 7)         # symbols 0..137: no code
    code(0b10, 2); put(118 - 11, 7)         # 138..255: no code
    code(0b01, 2)                           # 256 (end): 2 bits
    code(0b10, 2); put(28 - 11, 7)          # 257..284: no code
    code(0b00, 2)                           # 285 (length 258): 1 bit, code 0
    code(0b00, 2)                           # distance 0 (one back): 1 bit
    data = bytearray(sum(b << k for k, b in enumerate(bits[i:i + 8]))
                     for i in range(0, len(bits), 8))
    return bytes(data + b"\0" * (len(data) & 1))


def test_a_stream_that_copies_without_end_is_refused():
    # it used to inflate to 270 MB: no stream the game could hold
    with pytest.raises(ValueError):
        inflate16.inflate(_copies_without_end())


def test_the_same_stream_is_inflated_once(monkeypatch):
    """A stream inflated again comes from what was kept; another stream is
    inflated, never answered with the first's bytes."""
    monkeypatch.setattr(inflate16, "_kept", type(inflate16._kept)())
    monkeypatch.setattr(inflate16, "_kept_bytes", 0)
    made = []
    real = inflate16.inflate
    monkeypatch.setattr(inflate16, "inflate", lambda data: made.append(data) or real(data))
    a, b = _raw_deflate(PAYLOAD, 9), _raw_deflate(PAYLOAD[::-1], 9)
    assert inflate16.decompress(a) == PAYLOAD
    assert inflate16.decompress(a) == PAYLOAD
    assert len(made) == 1
    assert inflate16.decompress(b) == PAYLOAD[::-1]
    assert len(made) == 2


def test_what_is_kept_is_bounded(monkeypatch):
    """The latest outputs up to KEEP_BYTES are kept; the oldest goes first."""
    monkeypatch.setattr(inflate16, "_kept", type(inflate16._kept)())
    monkeypatch.setattr(inflate16, "_kept_bytes", 0)
    monkeypatch.setattr(inflate16, "KEEP_BYTES", 2 * len(PAYLOAD) + 10)
    streams = [_raw_deflate(PAYLOAD[:-k], 9) for k in (1, 2, 3)]
    for s in streams:
        inflate16.decompress(s)
    assert inflate16._kept_bytes <= inflate16.KEEP_BYTES
    assert len(inflate16._kept) == 2
    made = []
    real = inflate16.inflate
    monkeypatch.setattr(inflate16, "inflate", lambda data: made.append(data) or real(data))
    assert inflate16.decompress(streams[0]) == PAYLOAD[:-1]
    assert made == [streams[0]]

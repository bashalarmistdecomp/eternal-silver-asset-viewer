"""The EXE's LZSS decompressor.

This is the very first decoder in the chain — it unwraps the compressed
game engine out of SLUS_006.28, and everything downstream (every symbol,
every record table, the byte-match target itself) sits on its output. It
has no compressor to round-trip against, so the streams below are built by
hand from the algorithm the module documents:

    bit 1        -> literal
    bit 0, 1     -> short ref: 1 byte, top 2 bits = len-2, low 6 = -offset
    bit 0, 0     -> long ref:  2 bytes BE, top 4 = len, low 12 = -offset
                    len 0 -> one more byte as len+2; that byte 0 -> end
"""

from decoders.plugins.SLUS_006_28.formats import lzss


def test_literals_only():
    # control 0b00000111: three literal bits, LSB first.
    assert lzss.decompress(bytes([0b00000111]) + b"ABC") == b"ABC"


def test_short_reference():
    # literal 'A', then short ref: length 2, offset -1 -> "AAA".
    stream = bytes([0b00000101, ord("A"), 0x3F])
    assert lzss.decompress(stream) == b"AAA"


def test_short_reference_length_encoding():
    # top two bits carry length-2, so 0b11 -> length 5.
    stream = bytes([0b00000101, ord("Z"), 0xFF])
    assert lzss.decompress(stream) == b"Z" * 6


def test_long_reference():
    # literal 'X', then long ref: length nibble 3 -> 5 bytes, offset -1.
    stream = bytes([0b00000001, ord("X"), 0x3F, 0xFF])
    assert lzss.decompress(stream) == b"X" * 6


def test_long_reference_extended_length():
    # length nibble 0 -> read one more byte as the length, +2.
    stream = bytes([0b00000001, ord("Q"), 0x0F, 0xFF, 0x08])
    assert lzss.decompress(stream) == b"Q" * 11


def test_end_of_stream_marker_stops_decoding():
    """length nibble 0 followed by a 0 length byte ends the stream.

    Trailing bytes after the marker must be ignored — the compressed region
    is padded to a sector boundary in the real EXE.
    """
    stream = bytes([0b00000001, ord("Y"), 0x0F, 0xFF, 0x00]) + b"\xDE\xAD\xBE\xEF"
    assert lzss.decompress(stream) == b"Y"


def test_overlapping_copy_is_byte_at_a_time():
    # offset -2, length 4 over "AB" must give "ABAB", not two copies of a
    # snapshot — the classic LZSS run-length idiom. The ref byte is
    # (length-2) << 6 | (-2 & 0x3F) = 0b10 << 6 | 0b111110 = 0xBE.
    stream = bytes([0b00001011, ord("A"), ord("B"), 0xBE])
    assert lzss.decompress(stream) == b"ABABAB"


def test_reference_before_the_start_yields_zeros():
    # A back-reference reaching behind the output start is what a corrupt
    # or mid-stream slice produces; it must pad rather than raise.
    stream = bytes([0b00000010, 0x3F])
    assert lzss.decompress(stream) == b"\x00\x00"


def test_empty_input():
    assert lzss.decompress(b"") == b""


def test_decompress_exe_skips_the_bootstrap(tmp_path):
    """The compressed payload starts at file offset 0x1000."""
    exe = tmp_path / "fake.exe"
    payload = bytes([0b00000111]) + b"ABC"
    exe.write_bytes(b"\xAA" * 0x1000 + payload)
    assert lzss.decompress_exe(str(exe)) == b"ABC"


def test_decompress_exe_writes_out_path(tmp_path):
    exe = tmp_path / "fake.exe"
    out = tmp_path / "out.bin"
    exe.write_bytes(b"\xAA" * 0x1000 + bytes([0b00000111]) + b"ABC")
    lzss.decompress_exe(str(exe), str(out))
    assert out.read_bytes() == b"ABC"


def _byte_at_a_time(src: bytes) -> bytes:
    """The algorithm as the module docstring reads it, a bit and a byte at a
    time: the oracle for the decompressor's slices."""
    out, si, bits, flags = bytearray(), 0, 0, 0

    def bit():
        nonlocal si, bits, flags
        if bits == 0:
            flags, si, bits = src[si], si + 1, 8
        b, flags, bits = flags & 1, flags >> 1, bits - 1
        return b

    while si < len(src):
        if bit():
            out.append(src[si])
            si += 1
            continue
        if bit():
            b = src[si]
            si += 1
            length, offset = (b >> 6) + 2, (b & 0x3F) - 0x40
        else:
            word = src[si] << 8 | src[si + 1]
            si += 2
            length, offset = word >> 12, (word & 0xFFF) - 0x1000
            if length == 0:
                length = src[si]
                si += 1
                if length == 0:
                    break
            length += 2
        at = len(out) + offset
        for _ in range(length):
            out.append(out[at] if at >= 0 else 0)
            at += 1
    return bytes(out)


def test_slices_copy_as_a_byte_at_a_time_does():
    """Made-up streams of every kind of reference, overlapping runs, runs
    from before the start and streams cut short: the same bytes, or the
    same error, as copying one byte at a time."""
    import random
    rng = random.Random(7)

    def run(fn, s):
        try:
            return fn(s)
        except IndexError:
            return IndexError

    for _ in range(3000):
        s = bytearray()
        for _ in range(rng.randrange(1, 40)):
            s.append(rng.choice([0xFF, 0x00, 0xAA, 0x55, rng.randrange(256)]))
            s += bytes(rng.randrange(256) for _ in range(rng.randrange(0, 10)))
        s = bytes(s[:rng.randrange(len(s) + 1)])
        assert run(lzss.decompress, s) == run(_byte_at_a_time, s), s.hex()

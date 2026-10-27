"""The PS-X EXE container: per-instance address translation, and
SLUS_006.28's packed program unpacked (made-up bytes, no game's)."""

import struct

from decoders.psx.analysis.exe_loader import (
    PSX_EXE_MAGIC, PSX_HEADER_SIZE, LoadedBinary,
)


def _header(start=0x80010000, size=0x800):
    """A PS-X EXE header: the magic, then entry, gp, load address, size."""
    h = bytearray(PSX_HEADER_SIZE)
    h[:8] = PSX_EXE_MAGIC
    struct.pack_into("<4I", h, 0x10, start, 0, start, size)
    return bytes(h)


def test_translation_is_per_instance_state():
    # A headered EXE: raw[0] is the header, body at text_start.
    exe = LoadedBinary(raw=b"H" * PSX_HEADER_SIZE + b"CODE",
                       text_start=0x80010100, text_size=4,
                       entry_point=0x80010100,
                       load_base=0x80010100 - PSX_HEADER_SIZE)
    assert exe.ram_to_offset(0x80010100) == PSX_HEADER_SIZE
    assert exe.offset_to_ram(PSX_HEADER_SIZE) == 0x80010100
    assert exe.code == b"CODE"
    # An overlay: raw[0] IS the base (load_base defaults to text_start).
    ovl = LoadedBinary(raw=b"CODE", text_start=0x80196000, text_size=4,
                       entry_point=0x80196000)
    assert ovl.ram_to_offset(0x80196000) == 0
    assert ovl.code == b"CODE"


def _packed(body: bytes) -> bytes:
    """An outer SSSC-style EXE made up for a test: a header, the bootstrap's
    room, then `body` as an LZSS stream of literals."""
    stream = bytearray()
    for i in range(0, len(body), 8):
        chunk = body[i:i + 8]
        stream += bytes([(1 << len(chunk)) - 1]) + chunk
    outer = _header()
    return outer + bytes(0x1000 - len(outer)) + bytes(stream)


def _inner(fill: bytes) -> bytes:
    return _header(start=0x80011000) + fill * 0x800


def test_a_program_read_again_is_not_stale(tmp_path):
    """load_exe keeps what it decompressed by the file's bytes: the same
    bytes give the same image (each call its own LoadedBinary), and a file
    rewritten with other bytes is read anew."""
    from decoders.psx.analysis.exe_loader import load_exe
    exe = tmp_path / "TEST_EXE"
    exe.write_bytes(_packed(_inner(b"A")))
    first = load_exe(exe)
    again = load_exe(exe)
    assert first is not again and first.raw == again.raw
    assert first.code == b"A" * 0x800
    exe.write_bytes(_packed(_inner(b"B")))
    assert load_exe(exe).code == b"B" * 0x800
    exe.write_bytes(_packed(_inner(b"A")))
    assert load_exe(exe).code == b"A" * 0x800

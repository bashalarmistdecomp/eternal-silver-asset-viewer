"""Tier 1 for the battle graphics containers — synthetic bytes, no game data.

What this CAN catch: a header word read at the wrong offset, the two page
height rules (graphics sets store height/4 in the code's high byte, the
party bundle stores the height itself), the party CLUT's zeroed entry,
the type count coming from the CALLER rather than the header, and the
arena's fixed geometry (BtlFrameDraw, 0x80018564).

What it CANNOT catch: whether those offsets are the loaders'. Only
re-reading BtlDataLoad (0x80018694) / BtlPartyDataLoad (0x80018A78) / BtlPartyLoad (0x8002B114) / BtlPartyImageLoad (0x800187D8)
does that. See decoders/testing.py.
"""

import struct
import zlib

import pytest

from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg


def _deflate(payload: bytes) -> bytes:
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = co.compress(payload) + co.flush()
    raw += b"\x00" * (len(raw) % 2)
    return raw + b"\x00" * (-len(raw) % 4)          # keep word alignment


def _blob(seed: int, n: int) -> bytes:
    """Compressible bytes: zlib must emit a Huffman block, never a STORED one
    (stored blocks are where inflate16 deliberately diverges, test_inflate16)."""
    return bytes((seed + i % 16) & 0xFF for i in range(n))


def _clut(seed: int) -> bytes:
    return bytes((seed + i) & 0xFF for i in range(bg.CLUT_BYTES))


def _set_bundle(types, pages, page4_code=0, junk_pairs=()):
    """header (20 u16) + blocks + CLUT A + CLUT B + pages, all word offsets."""
    hdr = [0] * 20
    body = bytearray()
    at = 0x28
    for t, blk in enumerate(types):
        z = _deflate(blk)
        hdr[2 * t], hdr[2 * t + 1] = len(blk) // 4, at // 4
        body += z
        at += len(z)
    for t, pair in junk_pairs:
        hdr[2 * t], hdr[2 * t + 1] = pair
    hdr[8], hdr[9] = at // 4, (at + 512) // 4
    body += _clut(1) + _clut(2)
    at += 1024
    for i, px in enumerate(pages):
        z = _deflate(px)
        hdr[10 + 2 * i] = (len(px) // 256 // 4) << 8
        hdr[11 + 2 * i] = at // 4
        body += z
        at += len(z)
    if page4_code:
        hdr[18] = page4_code
    return struct.pack("<20H", *hdr) + bytes(body)


def test_set_bundle_round_trips():
    blocks = [_blob(0, 64), _blob(64, 128)]
    pages = [bytes([7]) * (256 * 8), bytes([9]) * (256 * 4)]
    b = bg.parse_set_bundle(_set_bundle(blocks, pages), n_types=2)
    assert b.type_blocks == blocks
    assert b.clut_a == _clut(1) and b.clut_b == _clut(2)
    assert [(p.index, p.lines) for p in b.pages] == [(0, 8), (1, 4)]
    assert b.pages[0].pixels == pages[0]


def test_page_height_is_code_high_byte_times_four():
    b = bg.parse_set_bundle(_set_bundle([], [bytes(256 * 12)]), n_types=0)
    assert b.header[10] >> 8 == 3 and b.pages[0].lines == 12


def test_type_count_comes_from_the_caller_not_the_header():
    """The engine inflates exactly len(type list) blocks; a stale header
    pair past that is never read (it would not inflate)."""
    blocks = [_blob(3, 32)]
    buf = _set_bundle(blocks, [bytes(256 * 4)], junk_pairs=[(1, (0xFFFF, 0xFFFF))])
    assert len(bg.parse_set_bundle(buf, n_types=1).type_blocks) == 1
    with pytest.raises(ValueError):
        bg.parse_set_bundle(buf, n_types=2)


def test_reserved_lines_come_from_page_four():
    buf = _set_bundle([], [bytes(256 * 4)], page4_code=0x0600)
    assert bg.parse_set_bundle(buf, 0).reserved_lines == 24


def _party(entries, clut_at):
    """hdr = byte offset of the CLUT; entries at +2, 8 bytes each."""
    table = bytearray(struct.pack("<H", clut_at))
    blobs = bytearray()
    at = (clut_at & 0xFFFC) + 512
    for blk, px in entries:
        zb, zp = _deflate(blk), _deflate(px)
        table += struct.pack("<4H", at // 4, len(blk), (at + len(zb)) // 4, (len(px) // 256) << 8)
        blobs += zb + zp
        at += len(zb) + len(zp)
    table += b"\0" * ((clut_at & 0xFFFC) - len(table))
    return bytes(table) + _clut(5) + bytes(blobs)


def test_party_entries_and_page_height():
    entries = [(_blob(1, 40), bytes([3]) * (256 * 6)),
               (_blob(8, 40), bytes([4]) * (256 * 2))]
    buf = _party(entries, clut_at=2 + 8 * 2 + 2)
    pb = bg.parse_party_bundle(buf)
    assert list(pb.members) == [1, 2]
    assert pb.members[2].block == entries[1][0]
    assert pb.members[1].page.lines == 6               # code >> 8, NOT x4


def test_party_clut_zeroes_the_halfword_hdr_names():
    """BtlPartyDataLoad (0x80018A78) zeroes the u16 at (hdr & 0xFFFE), the CLUT starts at
    (hdr & 0xFFFC): with hdr % 4 == 2 that is entry 1, not entry 0."""
    buf = bytearray(_party([], clut_at=0x12))
    clut = bg.party_clut(bytes(buf))
    assert clut[:2] == _clut(5)[:2] and clut[2:4] == b"\0\0"
    buf[0:2] = struct.pack("<H", 0x10)
    assert bg.party_clut(bytes(buf))[:2] == b"\0\0"


def test_arena_geometry_is_func_80018564():
    pytest.importorskip("PIL")              # compose_arena needs Pillow

    # page 0 pixel = column index; page 1 pixel = column index ^ 0x80.
    p0 = bytes(x for _y in range(240) for x in range(256))
    p1 = bytes((x ^ 0x80) & 0xFF for _y in range(240) for x in range(256))
    clut = b"".join(struct.pack("<H", 0x8000 | i) for i in range(256))
    b = bg.SetBundle(type_blocks=[], clut_a=clut, clut_b=clut,
                     pages=[bg.BattlePage(0, 240, p0), bg.BattlePage(1, 240, p1)],
                     reserved_lines=0)
    img = bg.compose_arena(b)
    assert img.size == (320, 224)
    red = lambda x: img.getpixel((x, 5))[0] >> 3
    assert red(255) == 255 & 0x1F                    # page 0, column 255
    assert red(256) == (0 ^ 0x80) & 0x1F             # page 1 starts at u = 0
    assert red(319) == (63 ^ 0x80) & 0x1F


def test_party_places_as_MapBtlRun_and_BtlPartyLoad_put_them():
    """Made-up places: x = (place x - shift) * 8, y = place y * 8; an x cell
    of 0x10 or more is mirrored (0x2020), below it not (0x20); slot 5 stands
    at (0xA0, 0x68) whatever its place."""
    places = {1: (0x1C, 0x10), 2: (0x12, 0x14), 3: (0x1A, 0x11), 0xC: (0x1E, 0x12)}
    got = bg.party_places((1, 2, 3, 0, 0, 0xC), places, x_shift=4)
    assert [(p.slot, p.char_id, p.x, p.y, p.mirrored, p.cells) for p in got] == [
        (0, 1, 0x18 * 8, 0x10 * 8, True, (0x18, 0x10)),
        (1, 2, 0x0E * 8, 0x14 * 8, False, (0x0E, 0x14)),
        (2, 3, 0x16 * 8, 0x11 * 8, True, (0x16, 0x11)),
        (5, 0xC, 0xA0, 0x68, True, None)]


def test_party_places_wrap_the_byte_and_stop_at_the_first_empty_slot():
    places = {1: (2, 3), 2: (5, 5)}
    got = bg.party_places((1, 0, 2, 0, 0, 0), places, x_shift=4)
    # g_BtlPartyPlaceXCells is a byte: 2 - 4 wraps to 0xFE. MapBtlRun stops
    # at slot 1's 0, so slot 2 has no copied cells and is left out.
    assert [(p.slot, p.cells) for p in got] == [(0, (0xFE, 3))]
    # an id with no place, or of 0x1F or more, is not copied either
    assert bg.party_places((7, 0x1F, 0, 0, 0, 0), {7: (1, 1), 0x1F: (1, 1)}) == [
        bg.PartyPlace(0, 7, 8, 8, False, (1, 1))]

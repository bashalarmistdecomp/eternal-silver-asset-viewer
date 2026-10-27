"""Tier 1 for the party's field sheets — synthetic bytes, no game data —
and a tier-2 read of the disc's directory when the library holds the disc.

What this CAN catch: a directory field read at the wrong offset or in the
wrong unit (all four count 4-byte units; a picture is 64 of them a line),
the 0xCE -> row 0x1E exception, the three sheets an id below 0x1F loads and
the one an id from 0x1F up loads, the twin table's index, which sheet the
member wears by g_MapPartyKind, and the palette row each is drawn with.

What it CANNOT catch: whether those rules are the functions'. Only
re-reading MapPartySpriteDataLoad (0x80063D48), MapPartyRecordInit
(0x800649DC), sprite_page_image_add (0x8001808C) and MapRecordInit
(0x80065940) does that: both sides of every assertion here were written
together. See decoders/testing.py.
"""

import struct
import zlib

import pytest

from decoders import config
from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pf

_RAW = config.raw_dir("SLUS_006.28")


def _deflate(payload: bytes) -> bytes:
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = co.compress(payload) + co.flush()
    raw += b"\x00" * (len(raw) % 2)
    return raw + b"\x00" * (-len(raw) % 4)          # keep word alignment


def _blob(seed: int, n: int) -> bytes:
    """Compressible bytes: zlib must emit a Huffman block, never a STORED one
    (stored blocks are where inflate16 deliberately diverges, test_inflate16)."""
    return bytes((seed + i % 16) & 0xFF for i in range(n))


def _picture(seed: int, lines: int) -> bytes:
    return bytes((seed + (i % 7)) & 0xFF for i in range(256 * lines))


def _directory(sheets: dict, rows: int) -> bytes:
    """`rows` 8-byte rows, a zero word, then the packed streams. `sheets` is
    {row: (block, picture)}; a row not named gets a block and picture of
    its own."""
    head = bytearray(rows * 8 + 4)
    body = bytearray()
    at = len(head)
    for row in range(rows):
        blk, px = sheets.get(row, (_blob(row, 16), _picture(row, 4)))
        zb, zp = _deflate(blk), _deflate(px)
        struct.pack_into("<4H", head, row * 8, len(blk) // 4, at // 4,
                         len(px) // 4, (at + len(zb)) // 4)
        body += zb + zp
        at += len(zb) + len(zp)
    return bytes(head) + bytes(body)


#: A made-up g_MapTwinSpriteDataNumbers: ids 1..12 -> sprite data 0x21..0x2C.
TWINS = bytes(range(0x21, 0x2D))


def test_row_fields_count_4_byte_units_and_a_line_is_64():
    d = pf.DirectoryRow(3, data_length=100, data_place=7, image_length=64 * 20,
                        image_place=9)
    assert d.lines == 20


def test_row_count_is_bounded_by_the_first_stream():
    buf = _directory({}, rows=5)
    assert pf.row_count(buf) == 5
    rows = pf.parse_directory(buf)
    assert [r.index for r in rows] == [0, 1, 2, 3, 4]
    assert rows[0].data_place * 4 == 5 * 8 + 4      # the streams start past the 0 word
    # With no 0 word the rows still stop where the first stream begins.
    tight = bytearray(_directory({}, rows=2))
    del tight[16:20]
    for r in range(2):
        dl, dp, il, ip = struct.unpack_from("<4H", tight, r * 8)
        struct.pack_into("<4H", tight, r * 8, dl, dp - 1, il, ip - 1)
    assert pf.row_count(bytes(tight)) == 2


def test_sprite_data_row_and_the_0xce_exception():
    assert pf.sprite_data_row(1) == 0 and pf.sprite_data_row(0x1B) == 0x1A
    assert pf.sprite_data_row(0xCE) == 0x1E
    assert pf.sprite_data_row(0x1F) == 0x1E         # the same row, by id - 1
    with pytest.raises(ValueError):
        pf.sprite_data_row(0)


def test_load_sheet_gives_the_block_and_the_picture():
    blk, px = _blob(9, 64), _picture(3, 12)
    buf = _directory({2: (blk, px)}, rows=4)
    s = pf.load_sheet(buf, 3)
    assert (s.number, s.row) == (3, 2)
    assert s.block == blk
    assert (s.picture.index, s.picture.lines, s.picture.pixels) == (0, 12, px)
    with pytest.raises(ValueError):
        pf.load_sheet(buf, 5)                       # row 4 is past the directory


def test_twin_numbers_are_read_from_their_address_and_indexed_by_id():
    at = pf.TWIN_NUMBERS_ADDR - pf.EXE_BASE
    image = bytes(at) + TWINS + b"\x99"
    assert pf.twin_numbers(image) == TWINS
    with pytest.raises(ValueError):
        pf.twin_numbers(bytes(at + 4))
    assert pf.twin_number(TWINS, 1) == 0x21 and pf.twin_number(TWINS, 12) == 0x2C
    for bad in (0, 13, 0xCE):
        with pytest.raises(ValueError):
            pf.twin_number(TWINS, bad)


def test_an_id_below_0x1f_gets_own_kind_0_and_twin_sheets():
    buf = _directory({}, rows=0x2D)
    m = pf.member_sheets(buf, 2, TWINS)
    assert (m.own.number, m.own.row) == (2, 1)
    assert (m.kind_0.number, m.kind_0.row) == (0x11, 0x10)    # id + 0xF
    assert (m.twin.number, m.twin.row) == (0x22, 0x21)        # TWINS[1]
    assert m.kind == 1 and m.palette_row == 504 and m.twin_palette_row == 504


def test_an_id_from_0x1f_up_is_kind_2_with_its_own_sheet_only():
    buf = _directory({}, rows=0x1F)
    m = pf.member_sheets(buf, 0xCE, TWINS)
    assert (m.own.number, m.own.row) == (0xCE, 0x1E)
    assert m.kind_0 is None and m.twin is None
    assert m.kind == 2 and m.palette_row == 505
    assert pf.member_kind(0x1E) == 1 and pf.member_kind(0x1F) == 2


def test_g_map_party_kind_picks_the_sheet_and_the_twin():
    buf = _directory({}, rows=0x2D)
    m = pf.member_sheets(buf, 1, TWINS)
    assert m.worn(0) is m.kind_0 and not m.twin_drawn(0)
    for kind in (1, 2):
        assert m.worn(kind) is m.own and m.twin_drawn(kind)
    other = pf.member_sheets(_directory({}, rows=0x1F), 0xCE, TWINS)
    assert other.worn(1) is other.own and other.worn(0) is None
    assert not other.twin_drawn(1)


def test_party_uses_are_own_kind_0_and_twin_with_the_kinds_record_init_gives():
    # MapPartyRecordInit (0x800649DC): kind 1 below 0x1F, 2 from 0x1F up,
    # chosen before id + 0xF; the twin is kind 1, on twins[id - 1]
    uses = pf.party_uses(bytes([0x0D, 0x1E]), [1, 2, pf.ID_CE])
    assert uses[1] == [pf.PartyUse(1, "own", 1)]
    assert uses[0x10] == [pf.PartyUse(1, "party-kind-0", 1)]
    assert uses[0x0D] == [pf.PartyUse(1, "twin", 1)]
    assert uses[0x1E] == [pf.PartyUse(2, "twin", 1)]
    assert uses[pf.ID_CE] == [pf.PartyUse(pf.ID_CE, "own", 2)]
    assert pf.ID_CE + pf.KIND_0_OFFSET not in uses


@pytest.mark.disc
@pytest.mark.skipif(not (_RAW / "LUNADATA.FIL").exists(),
                    reason="the SSSC disc is not in the library")
def test_every_sheet_the_party_loader_names_reads_on_the_disc():
    from decoders.psx.analysis.exe_loader import load_exe
    from decoders.plugins.SLUS_006_28.formats.resource_table import load_resource_table
    binary = load_exe(_RAW / "SLUS_006.28")
    table = {r.index: r for r in load_resource_table(binary)}
    buf = table[pf.DIRECTORY_RESOURCE].read(_RAW / "LUNADATA.FIL")
    assert pf.row_count(buf) > pf.ID_CE_ROW
    twins = pf.twin_numbers(binary.code)
    for member in [*range(1, len(twins) + 1), pf.ID_CE]:
        m = pf.member_sheets(buf, member, twins)
        for sheet in (m.own, m.kind_0, m.twin):
            if sheet is not None:
                assert sheet.actor() is not None, (member, sheet.number)
                assert sheet.picture.lines > 0

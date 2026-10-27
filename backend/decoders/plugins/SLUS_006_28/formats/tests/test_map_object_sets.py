"""Tier 1 for the map object sets — synthetic bytes, no game data — and a
tier-2 walk over the disc's sets when the library holds the disc.

What this CAN catch: a header word or list field read at the wrong offset
or in the wrong unit (`place` counts 4-byte units from the list, `length`
4-byte units of the inflated block), the page walk's end, the
first-row-wins and below-0x100 rules, the 0x1300 split, every constant of
the draw-word rule (kind 1 / 2 / 7 / other, modes 1 / 2 / 3), kind 7's
sprite data 0, the twin rule and its table index, the enter rows' two
bytes, and which type-4 command gives row 506 and its fix-up.

What it CANNOT catch: whether those rules are the functions'. Only
re-reading MapObjectsDataLoad (0x80065418), sprite_page_list_load
(0x800182B8), MapObjectInit (0x800656CC), MapRecordInit (0x80065940),
sprite_draw (0x8001A528) and resource_palette_load (0x80020A08) does that:
both sides of every assertion here were written together. See
decoders/testing.py.
"""

import struct
import zlib

import pytest

from decoders import config
from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos

_RAW = config.raw_dir("SLUS_006.28")


def _deflate(payload: bytes) -> bytes:
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = co.compress(payload) + co.flush()
    raw += b"\x00" * (len(raw) % 2)
    return raw + b"\x00" * (-len(raw) % 4)          # keep word alignment


def _page(seed: int, lines: int, extra: int = 0) -> bytes:
    """Compressible pixels: zlib must emit a Huffman block, never a STORED
    one (where inflate16 deliberately diverges, test_inflate16)."""
    return bytes((seed + (i % 7)) & 0xFF for i in range(256 * lines + extra))


def _blob(seed: int, n: int) -> bytes:
    return bytes((seed + i % 16) & 0xFF for i in range(n))


def _def(b0=0, sprite_data=1, mode=0) -> bytes:
    d = bytearray(mos.DEFINITION_SIZE)
    d[0], d[1], d[3] = b0, sprite_data, mode
    return bytes(d)


def _definitions(defs=(), tail=b"") -> bytes:
    out = bytearray(mos.STEP_LISTS_AT)
    for i, d in enumerate(defs):
        out[i * mos.DEFINITION_SIZE:(i + 1) * mos.DEFINITION_SIZE] = d
    return bytes(out) + tail


def _set(definitions: bytes, rows, pages) -> bytes:
    """An object-set resource: the s32 words, the sprite data list with its
    blocks packed behind it, the definition block, the pages. `rows` is
    [(number, block)]."""
    head = 4 * (2 + len(pages) + 1)
    lst = bytearray(6 * (len(rows) + 1))
    lst += b"\0" * (-len(lst) % 4)
    packed = b""
    for i, (number, blk) in enumerate(rows):
        struct.pack_into("<3H", lst, 6 * i, number, len(blk) // 4,
                         (len(lst) + len(packed)) // 4)
        packed += _deflate(blk)
    body = bytes(lst) + packed
    defs_at = head + len(body)
    zdefs = _deflate(definitions)
    offs, at, zpages = [], defs_at + len(zdefs), []
    for px in pages:
        offs.append(at)
        zpages.append(_deflate(px))
        at += len(zpages[-1])
    return (struct.pack(f"<{2 + len(pages) + 1}I", defs_at, head, *offs, 0)
            + body + zdefs + b"".join(zpages))


def _actor(pieces, descs):
    """A sprite data block, one pose per piece: `pieces` = (w, h, desc, xo,
    yo), `descs` = (slot, u, v)."""
    tables = [struct.pack("<2H", 1, 0), struct.pack("<2H", 0, 1),
              b"".join(struct.pack("<2H", 1, i) for i in range(len(pieces))),
              b"".join(struct.pack("<H2hH8h", 0, w, h, d, xo, yo, 0, 0, 0, 0, 0, 0)
                       for w, h, d, xo, yo in pieces),
              b"".join(struct.pack("<6H", 0, s, 0, 0, u, v) for s, u, v in descs)]
    words, at = [], 4
    for t in tables:
        words.append(at)
        at += len(t) // 4
    words.append(at)
    return struct.pack("<6H", *words) + b"\0" * 4 + b"".join(tables)


def _command(kind: int, payload: bytes, arg: int = 0) -> bytes:
    payload += b"\0" * (-len(payload) % 4)
    return struct.pack("<II", kind | (arg << 8), len(payload)) + payload


def _map(*commands: bytes) -> bytes:
    return b"".join(commands) + bytes(8)


def _enter_table(rows: dict) -> bytes:
    out = bytearray(mos.ENTER_ROW * mos.ENTER_ROWS)
    for i, (m, s) in rows.items():
        out[i * mos.ENTER_ROW] = m
        out[i * mos.ENTER_ROW + 1] = s
    return bytes(out)


# ---------------------------------------------------------------------------
# the EXE's tables
# ---------------------------------------------------------------------------
def test_set_resources_is_a_u16_per_set_and_0_names_none():
    image = bytearray(mos.SET_RESOURCES_ADDR - mos.EXE_BASE + 0x134)
    at = mos.SET_RESOURCES_ADDR - mos.EXE_BASE
    struct.pack_into("<3H", image, at, 0, 0x200, 0)
    struct.pack_into("<H", image, at + 2 * 153, 0x2FF)
    assert mos.set_resources(bytes(image)) == {1: 0x200, 153: 0x2FF}
    with pytest.raises(ValueError):
        mos.set_resources(bytes(image[:-2]))


def test_twin_numbers_are_read_from_their_address():
    at = mos.TWIN_NUMBERS_ADDR - mos.EXE_BASE
    image = bytes(at) + bytes(range(1, 15)) + b"\xEE"
    assert mos.twin_numbers(image) == bytes(range(1, 15))
    with pytest.raises(ValueError):
        mos.twin_numbers(bytes(at + 4))


# ---------------------------------------------------------------------------
# the resource
# ---------------------------------------------------------------------------
def test_header_words_and_the_page_walk_ends_at_a_zero_word():
    raw = _set(_definitions(), [(5, _blob(1, 16))], [_page(1, 4), _page(2, 2)])
    h = mos.set_header(raw)
    assert h.sprite_data_list == 20                 # past five words
    assert len(h.pages) == 2 and h.pages[0] > h.definitions
    # No 0 word before the data the words point at: an error, not a guess.
    broken = bytearray(raw)
    struct.pack_into("<I", broken, 16, 0x1234)
    with pytest.raises(ValueError):
        mos.set_header(bytes(broken))


def test_list_rows_are_number_length_place_and_blocks_are_cut_to_length():
    a, b = _blob(3, 40), _blob(7, 24)
    raw = _set(_definitions(), [(0x40, a), (0x41, b)], [_page(1, 1)])
    rows = mos.sprite_data_rows(raw)
    assert [(r.number, r.length) for r in rows] == [(0x40, 10), (0x41, 6)]
    assert rows[0].place * 4 == 6 * 3 + 2           # past the list and its pad
    assert mos.sprite_data(raw, rows[1]) == b
    short = mos.SpriteDataRow(0x40, rows[0].length + 50, rows[0].place)
    with pytest.raises(ValueError):
        mos.sprite_data(raw, short)


def test_the_first_row_of_a_number_wins_and_0x100_up_is_not_loaded():
    a, b, c = _blob(1, 16), _blob(2, 16), _blob(3, 16)
    raw = _set(_definitions(), [(0x40, a), (0x40, b), (0x100, c)], [_page(1, 1)])
    obj = mos.parse_object_set(raw)
    assert obj.blocks == {0x40: a}
    assert len(obj.rows) == 3


def test_the_definition_block_splits_at_0x1300():
    tail = b"STEPLIST" * 4
    raw = _set(_definitions([_def(sprite_data=9)], tail), [(9, _blob(1, 16))],
               [_page(1, 1)])
    obj = mos.parse_object_set(raw)
    assert obj.definitions[1] == 9
    assert obj.step_lists == tail
    with pytest.raises(ValueError):
        mos.definition_block(_set(b"\1" * 0x100, [(9, _blob(1, 16))], [_page(1, 1)]))


def test_pages_hold_their_whole_lines_up_to_256():
    raw = _set(_definitions(), [(9, _blob(1, 16))],
               [_page(1, 3, extra=100), _page(2, 257)])
    p0, p1 = mos.set_pages(raw)
    assert (p0.index, p0.lines, len(p0.pixels)) == (0, 3, 3 * 256)
    assert (p1.index, p1.lines) == (1, 256)
    assert mos.parse_object_set(raw).page_lines == {0: 3, 1: 256}
    assert mos.parse_object_set(raw, pages=False).pages == ()


# ---------------------------------------------------------------------------
# which sprite data, which palette
# ---------------------------------------------------------------------------
def test_record_draw_by_kind():
    assert mos.record_draw(1, 0) == (0x2000, 0x20)
    assert mos.record_draw(2, 0) == (0x2100, 0x20)
    assert mos.record_draw(7, 0) == (0x2370, 0)
    assert mos.record_draw(5, 0) == (0x2200, 0x20)
    assert [mos.record_draw(k, 0).palette_row for k in (1, 2, 7, 5)] == [504, 505, 507, 506]
    assert mos.record_draw(7, 0).palette_x == 0x70
    assert mos.record_draw(1, 0).palette_x == 0


def test_record_draw_by_mode():
    assert mos.record_draw(2, 1) == (0x2900, 0x20)
    assert mos.record_draw(2, 2) == (0x2D00, 0x20)
    assert mos.record_draw(2, 1).palette_row == 505        # mode bits keep the row
    assert not mos.record_draw(2, 1).semi
    assert mos.record_draw(2, 2).semi                      # bit 10
    m3 = mos.record_draw(5, 3)
    assert m3 == (0x2000, 0x8020) and m3.palette_row == 504 and m3.semi
    assert mos.record_draw(5, 4) == (0x2200, 0x20)         # no other mode changes it


def test_object_draws_kind_sprite_data_twin_and_the_empty_byte_1():
    twins = bytes(range(0x60, 0x6E))
    defs = _definitions([
        _def(b0=0x00, sprite_data=0x40, mode=0),        # kind 1
        _def(b0=0x06, sprite_data=0x41, mode=0),        # kind 7: sprite data 0
        _def(b0=0x00, sprite_data=0x00, mode=0),        # byte 1 0: not made
        _def(b0=0xC4, sprite_data=3, mode=3),           # kind 5 (bits 6, 7 dropped), twin
    ])
    draws = mos.object_draws(defs, twins)
    assert [(d.definition, d.kind, d.sprite_data, d.twin) for d in draws] == [
        (0, 1, 0x40, None), (1, 7, 0, None), (3, 5, 3, 0x62)]
    assert draws[1].draw.palette_row == 507
    assert draws[2].draw == (0x2000, 0x8020)
    by = mos.sprite_data_draws(draws)
    assert sorted(by) == [0, 3, 0x40, 0x62]
    assert by[0x62] == [(draws[2], True)] and by[3] == [(draws[2], False)]
    with pytest.raises(ValueError):
        mos.object_draws(_definitions([_def(sprite_data=0xE)]), bytes(4))


# ---------------------------------------------------------------------------
# the map's side
# ---------------------------------------------------------------------------
def test_enter_rows_are_rows_1_on_of_the_last_command_9():
    old = _enter_table({1: (0x30, 0x31)})
    new = _enter_table({0: (0x10, 0x11), 1: (0x15, 0x16), 3: (0x20, 0),
                        mos.ENTER_ROWS - 1: (0x7F, 0x7E)})
    rows = mos.enter_rows(_map(_command(9, old), _command(9, new)))
    assert rows == [(1, 0x15, 0x16), (3, 0x20, 0), (mos.ENTER_ROWS - 1, 0x7F, 0x7E)]
    assert mos.enter_rows(_map(_command(5, b"\1" * 8))) == []


def test_map_palette_is_the_last_type_4_of_sub_1_to_0x7f_with_bit_15():
    def cols(seed):
        return struct.pack("<256H", *((seed * 31 + i * 3) & 0x7FFF for i in range(256)))
    a, b, c = cols(1), cols(2), cols(3)
    raw = _map(_command(4, _deflate(a), arg=1), _command(4, _deflate(b), arg=2),
               _command(4, _deflate(c), arg=0x80), _command(4, _deflate(c), arg=0))
    pal = mos.map_palette(raw)
    assert len(pal) == mos.PALETTE_BYTES and pal[:2] == b"\0\0"
    for i in (1, 2, 0xFF):
        assert struct.unpack_from("<H", pal, 2 * i)[0] == \
            struct.unpack_from("<H", b, 2 * i)[0] | 0x8000
    assert mos.map_palette(_map(_command(4, _deflate(a), arg=0x80))) is None


def test_palette_bit15_set_masks_by_the_index():
    cols = struct.pack("<32H", *range(1, 33))
    out = mos.palette_bit15_set(cols, count=32, mask=0xF)
    words = struct.unpack("<32H", out)
    assert words[0] == 0 and words[16] == 0
    assert words[1] == 2 | 0x8000 and words[31] == 32 | 0x8000


# ---------------------------------------------------------------------------
# pieces off the set's pages
# ---------------------------------------------------------------------------
def test_undrawn_slices_names_pieces_whose_texels_are_not_on_a_page():
    from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
    actor = sp.parse_actor_block(_actor(
        [(8, 8, 0, 0, 0), (8, 8, 1, 0, 0), (8, 8, 2, 0, 0), (16, 8, 3, 0, 0)],
        [(0, 0, 0), (5, 0, 0), (0, 0, 60), (0, 250, 0)]))
    off = mos.undrawn_slices(actor, {0: 64})
    assert [(pose, piece) for pose, piece, _why in off] == [(1, 1), (2, 2), (3, 3)]
    assert "slot 5" in off[0][2] and "64 lines" in off[1][2] and "columns" in off[2][2]


# ---------------------------------------------------------------------------
# the disc
# ---------------------------------------------------------------------------
@pytest.mark.disc
@pytest.mark.skipif(not (_RAW / "LUNADATA.FIL").exists(),
                    reason="the SSSC disc is not in the library")
def test_every_set_on_the_disc_reads_as_the_game_reads_it():
    from decoders.psx.analysis.exe_loader import load_exe
    from decoders.plugins.SLUS_006_28.formats.resource_table import load_resource_table
    from decoders.plugins.SLUS_006_28.records import areas
    binary = load_exe(_RAW / "SLUS_006.28")
    table = {r.index: r for r in load_resource_table(binary)}
    archive = _RAW / "LUNADATA.FIL"
    sets = mos.set_resources(binary.code)
    assert sets
    twins = mos.twin_numbers(binary.code)
    for n, res in sets.items():
        raw = table[res].read(archive)
        obj = mos.parse_object_set(raw)
        assert all(0 < p.lines <= mos.PAGE_LINES for p in obj.pages), n
        assert all(len(obj.blocks[r.number]) == r.length * 4 for r in obj.rows), n
        listed = {r.number for r in obj.rows}
        for d in mos.object_draws(obj.definitions, twins):
            assert d.sprite_data == 0 or d.sprite_data in listed, (n, d)
    entered = set()
    for _map_id, res in areas.map_resources(binary.code).items():
        raw = table[res].read(archive)
        entered |= {r.object_set for r in mos.enter_rows(raw) if r.object_set}
        mp = mos.map_palette(raw)
        assert mp is None or len(mp) == mos.PALETTE_BYTES
    assert entered <= set(sets)

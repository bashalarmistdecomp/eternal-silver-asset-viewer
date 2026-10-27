"""Tier 1 for world maps — synthetic layouts, no game data.

What this CAN catch: bg_block_load (0x80014F3C)'s block rules — offset 0 = 64 x tile
0, below fill_end = one fill tile repeated, below data_end = an LZSS strip
(its own end marker), otherwise raw — the 16 x 16 grid of 8 x 8 blocks
(index bx + by * 16, tile (x & 7) + (y & 7) * 8), the layout taken from the
type-5 command, and bg_first_draw (0x80014058)'s tile-value decode.

Also the attribute plane's block rules (bg_attribute_block_load (0x800154F8): 16 x 16
blocks of 16 x 16 cells, raw at or above data_end, cell (x & 15) + (y & 15)
* 16) and the second layer's fixed size.

Also the CLUT rows resource_palette_load (0x80020A08) makes of palette 0 — the fix-up's two
rules (colour 0 of a row -> the transparent word, any other stored 0 -> 1),
the overlay rows' "first n of every 16", the second layer's row (second
half, bit 15, colour 0 of every 16 clear) — and the second layer as
bg_second_draw (0x800148E0) reads it: the cell word's fields, page 3 as 4-bit texels, the
pair walk of a row (wide cells of 16 and 32 px, the compare with 0, a walk
that starts inside a 32-px cell), a mirrored cell's texels, and the
plane as row-508 indexes drawn through any row 508.

What it CANNOT catch: whether those are the rows and the page the engine
uses — only re-reading resource_palette_load / bg_first_draw / bg_second_draw does
that — nor a layer's place among the others (the ordering table), its
scroll, or its blending. See decoders/testing.py.
"""

import struct

import pytest

from decoders.plugins.SLUS_006_28.formats import world_map as wm


def _layout(offsets: dict[int, int], fill: list[int], tail: bytes = b"") -> bytes:
    """A layout: 256 offsets, fill_end / data_end, the fill tiles, then `tail`."""
    table = [0] * 256
    for idx, off in offsets.items():
        table[idx] = off
    fill_end = 0x204 + 2 * len(fill)
    body = struct.pack("<256H", *table) + struct.pack("<HH", fill_end, fill_end + len(tail))
    return body + struct.pack(f"<{len(fill)}H", *fill) + tail


def test_zero_and_fill_blocks():
    lay = _layout({1: 0x204, 17: 0x206}, fill=[0x10C1, 0x1000])
    assert wm.block_tiles(lay, 0, 0) == [0] * 64
    assert wm.block_tiles(lay, 1, 0) == [0x10C1] * 64
    assert wm.block_tiles(lay, 1, 1) == [0x1000] * 64     # index 17 = bx 1, by 1


def test_lzss_strip_ends_at_its_marker():
    # an all-literal LZSS run of two u16 tiles, then the end marker
    lit = bytes([0xFF]) + struct.pack("<HHHH", 0x0001, 0x0002, 0x0003, 0x0004)
    strip = lit + bytes([0x00, 0x00, 0x00, 0x00])           # flags 0,0: long ref len 0 + 0 = end
    lay = _layout({2: 0x206}, fill=[0x1111], tail=strip)
    tiles = wm.block_tiles(lay, 2, 0)
    assert tiles[:4] == [1, 2, 3, 4] and tiles[4:] == [0] * 60


def test_odd_raw_offset_is_refused():
    lay = _layout({3: 0x401}, fill=[0])
    with pytest.raises(ValueError):
        wm.block_tiles(lay, 3, 0)


def test_tile_plane_places_blocks_and_tiles():
    lay = _layout({16 * 2 + 3: 0x204}, fill=[0x0042])      # block bx 3, by 2
    plane = wm.tile_plane(lay)
    assert len(plane) == wm.TILES and len(plane[0]) == wm.TILES
    assert plane[2 * 8][3 * 8] == 0x42 and plane[2 * 8 + 7][3 * 8 + 7] == 0x42
    assert plane[2 * 8][3 * 8 - 1] == 0


def test_layout_is_the_type_5_command():
    payload = _layout({}, fill=[0])
    raw = struct.pack("<II", 5, len(payload)) + payload + struct.pack("<I", 0)
    assert wm.layout(raw) == payload


def test_decode_tile():
    t = wm.decode_tile(0xD1A3)          # vflip, hflip, clut 1, page 1, v 0xA0, u 3*16
    assert (t.u, t.v, t.page, t.clut, t.hflip, t.vflip) == (48, 0xA0, 1, 1, True, True)


# ---- the attribute plane (type 6) and the second layer (type 7) -------------

def _attr(offsets: dict[int, int], fill: list[int], tail: bytes = b"",
          data_end: int | None = None) -> bytes:
    """An attribute payload: 256 offsets, fill_end / data_end, fill cells,
    then `tail`. `data_end` defaults to the end of `tail` (so `tail` is an
    LZSS strip); pass the tail's own start to make it raw."""
    table = [0] * 256
    for idx, off in offsets.items():
        table[idx] = off
    fill_end = 0x204 + 2 * len(fill)
    if data_end is None:
        data_end = fill_end + len(tail)
    body = struct.pack("<256H", *table) + struct.pack("<HH", fill_end, data_end)
    return body + struct.pack(f"<{len(fill)}H", *fill) + tail


def test_attribute_zero_and_fill_blocks():
    att = _attr({1: 0x204, 17: 0x206}, fill=[0x7800, 0x4081])
    assert wm.attribute_block(att, 0, 0) == [0] * 256
    assert wm.attribute_block(att, 1, 0) == [0x7800] * 256
    assert wm.attribute_block(att, 1, 1) == [0x4081] * 256     # index 17 = bx 1, by 1


def test_attribute_raw_block_starts_at_data_end():
    cells = list(range(0x100, 0x200))
    raw = struct.pack("<256H", *cells)
    # one fill cell, so the raw block sits at 0x206 == data_end: off >= data_end
    att = _attr({2: 0x206}, fill=[0x1111], tail=raw, data_end=0x206)
    assert wm.attribute_block(att, 2, 0) == cells


def test_attribute_lzss_block_below_data_end():
    lit = bytes([0xFF]) + struct.pack("<HHHH", 0x4000, 0x7800, 0x0081, 0x8000)
    strip = lit + bytes([0x00, 0x00, 0x00, 0x00])
    att = _attr({3: 0x206}, fill=[0x1111], tail=strip)
    cells = wm.attribute_block(att, 3, 0)
    assert cells[:4] == [0x4000, 0x7800, 0x0081, 0x8000] and cells[4:] == [0] * 252


def test_attribute_odd_raw_offset_is_refused():
    att = _attr({4: 0x301}, fill=[0], data_end=0x206)
    with pytest.raises(ValueError):
        wm.attribute_block(att, 4, 0)


def test_attribute_plane_places_blocks_and_cells():
    cells = [0] * 256
    cells[5 + 9 * 16] = 0x4ABC            # cell x 5, y 9 of the block
    att = _attr({16 * 2 + 3: 0x206}, fill=[0x1111],        # block bx 3, by 2
                tail=struct.pack("<256H", *cells), data_end=0x206)
    plane = wm.attribute_plane(att)
    assert len(plane) == wm.ATTR_CELLS and len(plane[0]) == wm.ATTR_CELLS
    assert plane[2 * 16 + 9][3 * 16 + 5] == 0x4ABC
    assert plane[2 * 16 + 9][3 * 16 + 4] == 0 and plane[2 * 16 + 8][3 * 16 + 5] == 0


def test_no_attribute_command_is_the_empty_plane():
    raw = struct.pack("<I", 0)
    assert wm.attributes(raw) is None
    plane = wm.attribute_plane(None)
    assert len(plane) == 256 and all(v == 0 for row in plane for v in row)


def test_attributes_is_the_type_6_command():
    payload = _attr({}, fill=[0])
    raw = struct.pack("<II", 6, len(payload)) + payload + struct.pack("<I", 0)
    assert wm.attributes(raw) == payload


def _deflate(payload: bytes) -> bytes:
    import zlib
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    out = co.compress(payload) + co.flush()
    return out + b"\x00" * (len(out) % 2)


def test_second_layer_is_the_inflated_type_7_command():
    cells = struct.pack(f"<{wm.LAYER2_COLS * wm.LAYER2_ROWS}h",
                        *([-1] * (wm.LAYER2_COLS * wm.LAYER2_ROWS - 1) + [0x0123]))
    packed = _deflate(cells)
    raw = struct.pack("<II", 7, len(packed)) + packed + struct.pack("<I", 0)
    assert wm.second_layer(raw) == cells
    assert wm.second_layer(struct.pack("<I", 0)) is None


def test_second_layer_of_another_size_is_refused():
    packed = _deflate(b"\xff\xff" * 100)
    raw = struct.pack("<II", 7, len(packed)) + packed + struct.pack("<I", 0)
    with pytest.raises(ValueError):
        wm.second_layer(raw)


def test_palettes_are_keyed_by_the_command_arg():
    pal = bytes(range(256)) * 4                     # 1024 bytes
    packed = _deflate(pal)
    raw = (struct.pack("<II", 4 | (0 << 8), len(packed)) + packed
           + struct.pack("<I", 0))
    assert wm.palettes(raw) == {0: pal}


# ---- the CLUT rows (resource_palette_load, 0x80020A08) and the second layer (bg_second_draw, 0x800148E0) -------

def _palette(n: int = 0x200, **colours: int) -> bytes:
    """`n` colours 0x0400 + index, with `c<index>=word` overrides."""
    words = [0x0400 + i for i in range(n)]
    for key, word in colours.items():
        words[int(key[1:], 16)] = word
    return struct.pack(f"<{n}H", *words)


def test_tile_depth():
    assert wm.tile_depth(0) == 0x300
    assert wm.tile_depth(0xD6A7) == 0x3A9          # 0xD6A7 >> 2 = 0x35A9, & 0xFF = 0xA9
    assert wm.tile_depth(0x03FF) == 0x3FF and wm.tile_depth(0x0300) == 0x3C0


def test_fix_up_makes_index_0_transparent_and_other_zeros_black():
    pal = _palette(c5=0, c10a=0, c7=0x8000, c20=0x001F)
    rows = wm.tile_clut_words(pal)
    assert len(rows) == 2 and all(len(r) == 256 for r in rows)
    assert rows[0][0] == 0 and rows[1][0] == 0      # stored 0x0400 / 0x0500
    assert rows[0][5] == 1 and rows[1][0x0A] == 1   # stored 0: now an opaque black
    assert rows[0][7] == 0x8000                     # bit 15 alone is not 0
    assert rows[0][0x20] == 0x001F                  # no red key
    assert rows[0][1] == 0x0401 and rows[1][0xFF] == 0x05FF
    rgba = wm.words_rgba(rows[0])
    assert rgba[0][3] == 0 and rgba[5] == (8, 0, 0, 255) and rgba[0x20] == (0xF8, 0, 0, 255)
    assert rgba[7] == (0, 0, 0, 255)


def test_overlay_rows_keep_the_last_colours_of_every_16():
    pal = _palette(c10a=0)
    rows = wm.overlay_clut_words(pal, 10)
    assert rows[0][9] == 0 and rows[0][0xA] == 0x040A and rows[0][0xF] == 0x040F
    assert rows[0][0x19] == 0 and rows[0][0x1A] == 0x041A
    assert rows[1][0x0A] == 1                       # the fixed-up zero is kept: an opaque black
    assert sum(1 for c in rows[0] if c) == 96       # 6 of every 16
    assert wm.overlay_clut_words(pal, 8)[0][8] == 0x0408
    assert wm.overlay_keep_from(0) == 8 and wm.overlay_keep_from(1) == 10 and wm.overlay_keep_from(2) == 10


def test_layer2_cluts_are_the_second_row():
    pal = _palette(c10a=0)
    cluts = wm.layer2_clut_words(pal)
    assert len(cluts) == 16 and all(len(c) == 16 for c in cluts)
    assert cluts[0][0] == 0 and cluts[1][0] == 0            # colour 0 of every CLUT
    assert cluts[0][1] == 0x8501 and cluts[0][0xA] == 0x8001
    assert cluts[1][1] == 0x8511 and cluts[15][15] == 0x85FF


def test_a_palette_of_256_colours_gives_one_row():
    pal = _palette(0x100, c5=0)
    rows = wm.tile_clut_words(pal)
    assert len(rows) == 1 and rows[0][0] == 0 and rows[0][5] == 1 and rows[0][0xFF] == 0x04FF
    assert len(wm.overlay_clut_words(pal, 10)) == 1
    with pytest.raises(ValueError):                 # the second row is not the palette's
        wm.layer2_clut_words(pal)


def test_clut_rows_are_the_games_rows_not_the_stored_palette():
    pal = _palette(c5=0, c20=0x001F)
    packed = _deflate(pal)
    raw = struct.pack("<II", 4, len(packed)) + packed + struct.pack("<I", 0)
    rows = wm.clut_rows(raw)
    assert len(rows) == 2
    assert rows[0][0][3] == 0                       # colour 0 stored as 0x0400: the hole all the same
    assert rows[0][5] == (8, 0, 0, 255)             # stored 0 at index 5: drawn
    assert rows[0][0x20] == (0xF8, 0, 0, 255)       # 0x001F: red, drawn
    assert wm.clut_rows(struct.pack("<I", 0)) == []


def test_cell_word():
    assert wm.decode_layer2_cell(-1) is None
    c = wm.decode_layer2_cell(0x3025)
    assert (c.u, c.v, c.clut, c.depth, c.wide, c.hflip, c.vflip) == (0x28, 8, 3, 4, False, False, False)
    c = wm.decode_layer2_cell(-3585)                # 0xF1FF
    assert (c.u, c.v, c.clut, c.depth) == (0xF8, 0x78, 15, 63)
    c = wm.decode_layer2_cell(0x0E41)
    assert c.wide and c.hflip and c.vflip and (c.u, c.v, c.depth) == (8, 0x10, 8)
    assert wm.decode_layer2_cell(0) == wm.Layer2Cell(0, 0, 0, 0, False, False, False)


def test_cells_are_128_rows_of_64():
    data = struct.pack("<8192h", *([-1] * 8192))
    assert wm.layer2_is_empty(data) and wm.layer2_is_empty(None)
    words = [-1] * 8192
    words[3 * 64 + 7] = 0x0001
    cells = wm.layer2_cells(struct.pack("<8192h", *words))
    assert len(cells) == 128 and len(cells[0]) == 64 and cells[3][7] == 1
    assert not wm.layer2_is_empty(struct.pack("<8192h", *words))


def test_page_3_is_read_as_nibbles():
    page = bytearray(0x4000)
    page[0] = 0x21                                  # texels 0, 1 = 1, 2
    page[128 + 3] = 0xF0                            # line 1, texels 6, 7 = 0, 15
    sheet = wm.layer2_sheet(bytes(page))
    assert len(sheet) == 256 * 128
    assert sheet[0] == 1 and sheet[1] == 2 and sheet[256 + 6] == 0 and sheet[256 + 7] == 15
    with pytest.raises(ValueError):
        wm.layer2_sheet(bytes(100))


def test_row_walk_pairs_and_wide_cells():
    row = [-1] * 64
    row[0:3] = [0x0241, 0, 0x0005]                  # next cell 0: 16 px, 2 columns
    d = wm.layer2_row_draws(row)
    assert [(x.col, x.cells) for x in d] == [(0, 2), (2, 1)]
    row = [-1] * 64
    row[0:5] = [0x0241, -1, 0x0005, 0x0006, 0x0007]  # next cell -1 is not 0: 32 px
    d = wm.layer2_row_draws(row)
    assert [(x.col, x.cells) for x in d] == [(0, 4), (4, 1)]
    row = [-1] * 64
    row[0:2] = [-1, 0x0241]                         # 0x200 on a pair's second cell: a plain cell
    d = wm.layer2_row_draws(row)
    assert [(x.col, x.cells) for x in d] == [(1, 1)] and d[0].cell.wide
    assert len(wm.layer2_row_draws([0] * 64)) == 64  # a word of 0 is a cell


def test_a_walk_that_starts_inside_a_32_px_cell_draws_its_second_pair():
    # the retail shape: head, 1, head + 16 px, 0
    row = [-1] * 64
    row[4:8] = [0x0205, 1, 0x0207, 0]
    whole = wm.layer2_row_draws(row)
    assert [(x.col, x.cells, x.cell.u) for x in whole] == [(4, 4, 0x28)]
    late = wm.layer2_row_draws(row, first=6)        # the view's left edge is the second pair
    assert [(x.col, x.cells, x.cell.u) for x in late] == [(6, 2, 0x38), (68, 4, 0x28)]
    with pytest.raises(ValueError):
        wm.layer2_row_draws(row, first=5)


def test_render_places_and_mirrors_a_cell():
    # sheet: texel (0, 0) = 1, (7, 0) = 2 on line 0; CLUT 0 colours 1 / 2 = red / green
    page = bytearray(0x4000)
    page[0] = 0x01
    page[3] = 0x20
    pal = _palette(c101=0x001F, c102=0x03E0)
    words = [-1] * 8192
    words[2 * 64 + 5] = 0x0000                      # plain, at (40, 16)
    words[2 * 64 + 6] = 0x0400                      # x mirror, at (48, 16)
    img = wm.render_second_layer(struct.pack("<8192h", *words), bytes(page), pal)
    assert img.size == (512, 1024)
    assert img.getpixel((40, 16)) == (0xF8, 0, 0, 255) and img.getpixel((47, 16)) == (0, 0xF8, 0, 255)
    assert img.getpixel((48, 16)) == (0, 0xF8, 0, 255) and img.getpixel((55, 16)) == (0xF8, 0, 0, 255)
    assert img.getpixel((41, 16))[3] == 0 and img.getpixel((0, 0))[3] == 0   # CLUT colour 0


def test_the_layer_as_indexes_and_a_later_cell_over_an_earlier():
    # sheet line 0: texels 1, 0, 0, 2 then 0; cell 0x3000 is CLUT 3 at u = 0
    page = bytearray(0x4000)
    page[0] = 0x01
    page[1] = 0x20
    words = [-1] * 8192
    words[64 + 2] = 0x3000                          # at (16, 8)
    words[64 + 3] = 0x5000                          # CLUT 5 at (24, 8)
    idx = wm.second_layer_indexes(struct.pack("<8192h", *words), bytes(page))
    assert len(idx) == 512 * 1024
    assert idx[8 * 512 + 16] == 0x31 and idx[8 * 512 + 19] == 0x32
    assert idx[8 * 512 + 17] == 0 and idx[8 * 512 + 24] == 0x51 and not idx[0]
    # row 508 from row 1: bit 15 set, colour 0 of every CLUT 0
    cluts = wm.layer2_cluts(list(range(0x100, 0x200)))
    assert len(cluts) == 16 and cluts[3][0] == 0 and cluts[3][1] == 0x8131
    img = wm.layer2_image(idx, cluts)
    assert img.getpixel((16, 8))[3] == 255 and img.getpixel((17, 8))[3] == 0


def test_render_tiles_uses_the_words_rule_and_the_overlay_rows():
    page = bytearray(0x10000)
    for i in range(16):
        page[i] = i                                 # tile (0, 0): line 0 = indexes 0..15
    pal = _palette(c5=0)
    plane = [[0] * 128 for _ in range(128)]
    plane[1][2] = 0x2000                            # bit 13, at (32, 16)
    plane[1][3] = 0x4000                            # x mirror, at (48, 16)
    plane[1][4] = 0x1000                            # bit 12: the second row
    tiles = wm.render_tiles(plane, {0: bytes(page)}, wm.tile_clut_words(pal))
    assert tiles.getpixel((32, 16))[3] == 0         # index 0: transparent
    assert tiles.getpixel((37, 16)) == (8, 0, 0, 255)   # index 5, stored 0: black, drawn
    assert tiles.getpixel((33, 16))[3] == 255
    assert tiles.getpixel((48 + 15, 16))[3] == 0 and tiles.getpixel((48, 16))[3] == 255   # mirrored
    assert tiles.getpixel((64 + 1, 16)) == (8, 64, 8, 255)      # 0x0501 through row 1
    front = wm.render_tiles(plane, {0: bytes(page)}, wm.overlay_clut_words(pal, 10), only_overlay=True)
    assert front.getpixel((32 + 9, 16))[3] == 0 and front.getpixel((32 + 10, 16))[3] == 255
    assert front.getpixel((48, 16))[3] == 0         # no bit 13: no copy
    assert front.getpixel((0, 0))[3] == 0
    short = wm.render_tiles(plane, {0: bytes(page)}, wm.tile_clut_words(_palette(0x100)))
    assert short.getpixel((33, 16))[3] == 255 and short.getpixel((64 + 1, 16))[3] == 0   # no row 1: skipped


def test_tile_texels_are_the_indexes_render_tiles_colours():
    page = bytearray(0x10000)
    for v in range(16):
        for u in range(16):
            page[v * 256 + u] = (v * 16 + u) & 0xFF        # tile (0, 0): index = its own place
    pal = _palette(c5=0)
    plane = [[0] * 128 for _ in range(128)]
    plane[0][1] = 0x4000                                  # x mirror, at (16, 0)
    plane[0][2] = 0x8000                                  # y mirror, at (32, 0)
    plane[0][3] = 0x0300                                  # page 3: render_tiles draws nothing
    t = wm.tile_texels(plane, {0: bytes(page)}, 0, 0, 64, 16)
    assert t[0][5] == 5 and t[3][5] == 0x35               # unmirrored
    assert t[0][16] == 15 and t[0][31] == 0               # mirrored in x
    assert t[0][32] == 0xF0 and t[15][32] == 0            # mirrored in y
    assert t[7][48] == -1                                 # no page
    rows = wm.tile_clut_words(pal)
    img = wm.render_tiles(plane, {0: bytes(page)}, rows)
    rgba = wm.words_rgba(rows[0])
    for j in range(16):
        for i in range(48):
            want = rgba[t[j][i]]
            if want[3]:
                assert img.getpixel((i, j)) == want
    with pytest.raises(ValueError):
        wm.tile_texels(plane, {0: bytes(page)}, 2040, 0, 16, 1)

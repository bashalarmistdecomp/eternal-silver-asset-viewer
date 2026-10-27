"""Tier 1 for SYSTEM.DAT (LUNADATA resource 1) — synthetic bytes.

What this CAN catch: the row a command 12 lands on (0x1F4 + the word's
second byte), palette_bit15_set's rule (colour 0 made 0, every other given
bit 15, a stored 0 included), the four glyph colours cleared for n = 7 only,
the later command for a row winning, the colour rule (only the word 0 is
not drawn), and the glyph atlas: the type-2 TIM sent at once, drawn with
row 507's sub-palettes 11 to 14.

What it CANNOT catch: whether those are resource_palette_row_load's,
palette_bit15_set's, resource_tim_add's and ankprint_glyph_draw's rules;
only re-reading palette_row.c, resource_command.c and ankprint.c does that.
See decoders/testing.py.
"""

import random
import struct
import zlib

import pytest

from decoders.plugins.SLUS_006_28.formats import system_dat as sd
from decoders.testing import rgb555, u16, u32


def _packed(raw: bytes) -> bytes:
    """Raw deflate, which the 16-bit reader takes as it is for Huffman
    blocks (test_inflate16.py), padded to whole words."""
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    out = co.compress(raw) + co.flush()
    return out + b"\0" * (-len(out) % 4)


def _list(*entries: tuple[int, bytes]) -> bytes:
    out = b"".join(u32(word, len(p)) + p for word, p in entries)
    return out + u32(0)


def _row(words) -> bytes:
    return u16(*words)


def test_a_command_12_lands_on_row_0x1f4_plus_n():
    words = [rgb555(k & 31, 3, 7) for k in range(256)]
    rows = sd.palette_rows(_list((0x30C, _packed(_row(words)))))
    assert list(rows) == [503]


def test_colour_0_is_made_0_and_every_other_gets_bit_15():
    words = [0x1234] + [0] + [rgb555(5, 6, 7)] * 254
    row = sd.palette_rows(_list((0x20C, _packed(_row(words)))))[502]
    assert row[0] == 0
    assert row[1] == 0x8000                    # a stored 0 becomes black
    assert row[2] == rgb555(5, 6, 7) | 0x8000


def test_row_7_also_clears_the_four_glyph_colours():
    words = [rgb555(1, 2, 3)] * 256
    rows = sd.palette_rows(_list((0x30C, _packed(_row(words))),
                                 (0x70C, _packed(_row(words)))))
    for i in sd.GLYPH_ZEROED:
        assert rows[507][i] == 0
        assert rows[503][i] == rgb555(1, 2, 3) | 0x8000
    assert rows[507][0xA0] == rgb555(1, 2, 3) | 0x8000


def test_a_later_command_for_the_row_wins():
    a, b = [rgb555(1, 0, 0)] * 256, [rgb555(0, 1, 0)] * 256
    rows = sd.palette_rows(_list((0x30C, _packed(_row(a))), (0x30C, _packed(_row(b)))))
    assert rows[503][5] == rgb555(0, 1, 0) | 0x8000


def test_other_commands_are_passed_over():
    assert sd.palette_rows(_list((0x001, b"abcd"), (0x002, b"efgh"))) == {}


def test_a_short_row_is_refused():
    with pytest.raises(ValueError):
        sd.palette_rows(_list((0x30C, _packed(b"\1\2" * 10))))


def test_only_the_word_0_is_not_drawn():
    c = sd.colours([0, 0x8000, rgb555(31, 0, 0), rgb555(0, 31, 0, stp=1), 0x001F])
    assert c[0][3] == 0
    assert c[1] == (0, 0, 0, 255)
    assert c[2] == (248, 0, 0, 255)
    assert c[3] == (0, 248, 0, 255)
    assert c[4] == (248, 0, 0, 255)            # pure red is a colour, not a key


def test_bit15_set_takes_the_mask():
    assert sd.bit15_set([7, 7, 7, 7], mask=0x2) == [0, 0, 0x8007, 0x8007]
    assert struct.pack("<H", sd.bit15_set([0, 0])[1]) == b"\0\x80"


def _tim_4bit(texels: bytes, w: int, h: int) -> bytes:
    """A 4-bit TIM with the CLUT flag set and an empty CLUT block, as the
    glyph atlas's is: header, CLUT block (12 bytes, 0 x 0), pixel block."""
    pixels = bytes((texels[i] & 0xF) | ((texels[i + 1] & 0xF) << 4)
                   for i in range(0, len(texels), 2))
    clut = u32(12) + u16(0, 0, 0, 0)
    body = u32(12 + len(pixels)) + u16(960, 384, w // 4, h) + pixels
    return u32(0x10, 0x08) + clut + body


def test_the_glyph_atlas_is_the_tim_sent_at_once_drawn_with_sub_palettes_11_to_14():
    texels = bytes([0, 1, 2, 3] * 4)                 # 8 x 2, values 0..3
    words = [0] * 256
    for k in range(16):
        for j in range(16):
            words[16 * k + j] = rgb555(k + 1, j + 1, 0)
    res1 = _list((0x102, _packed(b"kept, not sent")),
                 (0x002, _packed(_tim_4bit(texels, 8, 2))),
                 (0x70C, _packed(_row(words))))
    tim = sd.glyph_atlas(res1)
    assert (tim.width, tim.height, tim.vram_x, tim.vram_y) == (8, 2, 960, 384)
    layers = sd.glyph_atlas_layers(res1)
    assert [label for label, _ in layers] == [f"sub-palette {k}" for k in (11, 12, 13, 14)]
    im11 = layers[0][1]
    assert im11.getpixel((0, 0))[3] == 0             # colour 0xB0: cleared, not drawn
    assert im11.getpixel((1, 0)) == ((11 + 1) << 3, (1 + 1) << 3, 0, 255)
    assert layers[3][1].getpixel((3, 1)) == ((14 + 1) << 3, (3 + 1) << 3, 0, 255)


def test_no_tim_sent_at_once_is_not_resource_1():
    with pytest.raises(ValueError):
        sd.glyph_atlas(_list((0x102, _packed(b"kept"))))


def test_parse_system_dat_names_its_layers():
    texels = bytes(16)
    words = [rgb555(3, 3, 3)] * 256
    res1 = _list((0x002, _packed(_tim_4bit(texels, 8, 2))), (0x70C, _packed(_row(words))))
    asset = sd.parse_system_dat(res1)
    assert len(asset.layers) == 4 and asset.labels[0] == "sub-palette 11"
    assert "+0x599C" in asset.info and "+0x899C" in asset.info
    assert sd.parse_system_dat(b"\1\0\0\0" + b"\0" * 12).layers == []


def _lz_literals(raw: bytes) -> bytes:
    """An lz_unpack stream of literals only (len(raw) a multiple of 8),
    then the end mark: a long reference of length byte 0."""
    out = bytearray()
    for i in range(0, len(raw), 8):
        out += b"\xff" + raw[i:i + 8]
    return bytes(out) + b"\0\0\0\0"


def _icon_block(*texels: bytes) -> bytes:
    streams = [_lz_literals(t) for t in texels]
    offsets, at = [], 2 * len(streams)
    for s in streams:
        offsets.append(at)
        at += len(s)
    return bytes(sd.ICONS) + u16(*offsets) + b"".join(streams)


def test_the_icon_table_runs_to_where_the_first_icon_begins():
    side = sd.ICON_SIDE * sd.ICON_SIDE
    blk = _icon_block(bytes(side), bytes([1]) * side, bytes([2]) * side)
    assert sd.icon_offsets(blk) == [6, 6 + 72 * 9 + 4, 6 + 2 * (72 * 9 + 4)]


def test_an_icon_is_its_unpacked_24_by_24_texels():
    texels = bytes(range(256)) * 2 + bytes(64)
    blk = _icon_block(bytes(576), texels)
    offsets = sd.icon_offsets(blk)
    assert sd.icon_pixels(blk, offsets, 1) == texels
    short = bytes(sd.ICONS) + u16(2) + _lz_literals(bytes(8))
    with pytest.raises(ValueError):
        sd.icon_pixels(short, sd.icon_offsets(short), 0)


def test_an_icon_is_drawn_through_its_row_and_dimmed_by_half():
    row = sd.colours([0, rgb555(31, 16, 8), rgb555(1, 2, 3)])
    texels = bytes([0, 1, 2]) + bytes(573)
    shown = sd.icon_image(texels, row)
    assert shown.getpixel((0, 0))[3] == 0
    assert shown.getpixel((1, 0)) == (248, 128, 64, 255)
    dimmed = sd.icon_image(texels, row, sd.ICON_DIMMED)
    assert dimmed.getpixel((1, 0)) == (120, 64, 32, 255)
    assert dimmed.getpixel((2, 0)) == (0, 8, 8, 255)
    # every texel of a made-up icon, as drawn one by one
    rng = random.Random(5)
    row = sd.colours([rng.randrange(0x10000) for _ in range(256)])
    texels = bytes(rng.randrange(256) for _ in range(576))
    for level in (sd.ICON_COLOUR, sd.ICON_DIMMED):
        drawn = sd.icon_image(texels, row, level)
        for i, t in enumerate(texels):
            r, g, b, a = row[t]
            want = tuple(min(31, (c >> 3) * level >> 7) << 3 for c in (r, g, b)) + (a,)
            assert drawn.getpixel((i % 24, i // 24)) == want


def test_the_japanese_programs_block_keeps_its_icons_elsewhere(jp_image):
    assert sd.block_places(bytes(0x100)) == (sd.PALETTE_ANIMATION_COLOURS, sd.ICONS)
    assert sd.block_places(bytes(jp_image(0x100))) == (
        sd.JP_PALETTE_ANIMATION_COLOURS, sd.JP_ICONS)
    texels = bytes([7]) * (sd.ICON_SIDE * sd.ICON_SIDE)
    blk = bytes(sd.JP_ICONS) + u16(2) + _lz_literals(texels)
    offsets = sd.icon_offsets(blk, sd.JP_ICONS)
    assert offsets == [2]
    assert sd.icon_pixels(blk, offsets, 0, sd.JP_ICONS) == texels

"""Tier 1 for STFIELD.DAT (resource 2) — synthetic bytes.

What this CAN catch: sprite_reset (0x80018DBC)'s reading of the head (words
0, 1, 3, 5, 7 as places counted in 4 bytes; 2, 4, 6 not read), colour 0 of
each sub-palette made 0 with no bit 15 set, page 10 written into (word 5 -
word 4) / 3 texel records of each bank, the image cut to whole 0x80-byte
lines and drawn low nibble first, and sprite_draw (0x8001A528)'s
sub-palette of a draw word.

What it CANNOT catch: whether those are the functions' rules, or what the
disc's resource 2 holds; only re-reading sprite_list.c does the first. See
decoders/testing.py.
"""

import struct
import zlib

import pytest

from decoders.plugins.SLUS_006_28.formats import stfield as sf
from decoders.testing import rgb555, u16


def _packed(raw: bytes) -> bytes:
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    out = co.compress(raw) + co.flush()
    return out + b"\0" * (-len(out) % 4)


def _bank(records: int, filler: int = 0x77) -> bytes:
    """A sprite data: a head of six places (x 4), then `records` texel
    records of 12 bytes from word 4 to word 5, page field = `filler`."""
    first = 4                               # records from +0x10
    end = first + records * 3               # 12 bytes = 3 words each
    head = u16(first, first, first, first, first, end)
    pad = b"\0" * (first * 4 - len(head))
    recs = b"".join(u16(0, filler, 8, 8, 8 * k, 0) for k in range(records))
    return head + pad + recs


def _resource(palette_words, banks, image: bytes, unread=(0x1111, 0x2222, 0x3333)) -> bytes:
    """Head of eight places, then the palette, the packed banks, the image."""
    parts = [u16(*palette_words)] + [_packed(b) for b in banks] + [_packed(image)]
    at = 0x10
    places = []
    for p in parts:
        places.append(at // 4)
        at += len(p)
    head = u16(places[0], places[1], unread[0], places[2], unread[1], places[3],
               unread[2], places[4])
    return head + b"".join(parts)


def _palette():
    return [rgb555(k & 31, (k >> 4) & 31, 1) for k in range(256)]


def test_the_head_places_and_the_palette():
    words = _palette()
    st = sf.parse(_resource(words, [_bank(2), _bank(1), _bank(3)], bytes(0x80 * 3)))
    for k in range(16):
        assert st.palette[16 * k] == 0                 # colour 0 of each made 0
    assert st.palette[1] == words[1]                   # no bit 15 set
    assert not any(w & 0x8000 for w in st.palette)
    assert st.head[2:7:2] == (0x1111, 0x2222, 0x3333)  # words 2, 4, 6: not read


def test_every_texel_record_of_each_bank_gets_page_10():
    st = sf.parse(_resource(_palette(), [_bank(2), _bank(1), _bank(3)], bytes(0x80)))
    for bank, n in zip(st.banks, (2, 1, 3)):
        pages = [struct.unpack_from("<H", bank, 0x10 + 12 * k + 2)[0] for k in range(n)]
        assert pages == [sf.PAGE] * n
        assert struct.unpack_from("<H", bank, 0x10 + 12 * 0 + 4)[0] == 8   # the rest kept


def test_patch_pages_counts_by_words_4_and_5():
    block = _bank(4)
    out = sf.patch_pages(block)
    assert len(out) == len(block)
    assert [struct.unpack_from("<H", out, 0x10 + 12 * k + 2)[0] for k in range(4)] == [10] * 4
    with pytest.raises(ValueError):
        sf.patch_pages(block[:0x10 + 12])               # records run past the data


def test_the_image_is_whole_lines_drawn_low_nibble_first():
    line = bytes([0x21] + [0] * 0x7F)
    st = sf.parse(_resource(_palette(), [_bank(1)] * 3, line * 2 + b"\x99" * 5))
    assert st.lines == 2 and len(st.image) == 0x100
    pic = sf.sheet_image(st, 3)
    assert pic.size == (sf.SHEET_WIDTH, 2)
    assert pic.getpixel((0, 0))[:3] == ((49 & 31) << 3, (3 & 31) << 3, 8)   # colour 0x31
    assert pic.getpixel((1, 0))[:3] == ((50 & 31) << 3, (3 & 31) << 3, 8)   # colour 0x32
    assert pic.getpixel((2, 0))[3] == 0                 # colour 0x30: made 0, not drawn


def test_a_place_outside_the_resource_is_refused():
    raw = bytearray(_resource(_palette(), [_bank(1)] * 3, bytes(0x80)))
    struct.pack_into("<H", raw, 2 * sf.IMAGE_WORD, 0xFFFF)
    with pytest.raises(ValueError):
        sf.parse(bytes(raw))
    with pytest.raises(ValueError):
        sf.parse(b"\0" * 8)


def test_sprite_draw_takes_row_and_sub_palette_from_the_word():
    assert sf.row_of(0x730) == 507 and sf.sub_palette_of(0x730) == 3
    assert sf.row_of(0x6360) == 507 and sf.sub_palette_of(0x6360) == 6
    assert sf.row_of(0x2370) == 507 and sf.sub_palette_of(0x2370) == 7
    assert all(sf.row_of(w) == 507 for _b, w, _what, _where in sf.USES)
    assert sf.bank_sub_palettes(1) == [7]
    assert sf.bank_sub_palettes(2)[:3] == [3, 0, 1]


# -- the disc, when the library holds it ----------------------------------
def _disc_resource_2():
    from decoders import config
    from decoders.plugins.SLUS_006_28.formats.lunadata import LunaDataArchive

    path = config.raw_dir("SLUS_006.28") / "LUNADATA.FIL"
    if not path.is_file():
        pytest.skip("no SSSC disc in the library")
    archive = LunaDataArchive(path)
    entry = next((e for e in archive.toc_entries if e.name == "STFIELD.DAT"), None)
    if entry is None:
        pytest.skip("no STFIELD.DAT in the archive's table")
    return archive.extract(entry)


@pytest.mark.disc
def test_on_the_disc_each_bank_is_a_sprite_data_drawn_from_page_10():
    from decoders.plugins.SLUS_006_28.formats.sprite_pages import parse_actor_block

    st = sf.parse(_disc_resource_2())
    assert st.lines > 0
    for bank in st.banks:
        data = parse_actor_block(bank)
        assert data is not None and data.pose_count > 0
        first, end = struct.unpack_from("<2H", bank, 8)
        assert all(struct.unpack_from("<H", bank, first * 4 + 12 * k + 2)[0] == sf.PAGE
                   for k in range((end - first) // 3))

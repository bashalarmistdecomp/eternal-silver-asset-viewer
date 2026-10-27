"""Tier 1 for the game's pictures — synthetic command lists, no game data;
and, when the library holds the disc, that command 2 finds the 41.

What this CAN catch: the roles by resource and picture number (resource
599's six, a bromide's two, resource 3's cards and pages), resource_tim_add
(0x800208A0)'s numbering as the pictures carry it, and the colours a
picture with no CLUT of its own is drawn with: the row the code names, as
the earlier pictures leave it (PictureBandDraw (0x8002484C)); a bromide's
show: its two pictures placed as video memory holds them, the pan's rows
(PictureStep (0x800249B0)) and the fade (screen_fade_step (0x8001C0F0)).

What it CANNOT catch: a role misread from the code that shows the picture;
only re-reading that code does that. See decoders/testing.py.
"""

import struct
import zlib

import pytest

from decoders import config
from decoders.psx.formats import tim
from decoders.testing import rgb555, u16, u32
from decoders.plugins.SLUS_006_28.formats import resource_pictures as rp
from decoders.plugins.SLUS_006_28.formats import resources as rs


def _packed(data: bytes) -> bytes:
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = co.compress(data) + co.flush()
    return raw + b"\x00" * (len(raw) % 2)


def _tim4(pixels: bytes, pix_w: int, pix_h: int, clut=None, clut_at=(0, 0)) -> bytes:
    flags = tim.MODE_4BIT | (0x08 if clut else 0)
    out = u32(tim.TIM_MAGIC, flags)
    if clut:
        body = u16(*clut)
        out += u32(12 + len(body)) + u16(*clut_at, len(clut), 1) + body
    return out + u32(12 + len(pixels)) + u16(0, 0, pix_w, pix_h) + pixels


def _list(*entries: tuple[int, bytes]) -> bytes:
    out = bytearray()
    for word, payload in entries:
        payload += b"\x00" * (-len(payload) % 4)     # the walk steps in words
        out += struct.pack("<II", word, len(payload)) + payload
    return bytes(out + struct.pack("<I", 0))


def _pic(resource, picture, vram_x=0, has_clut=True):
    return rp.Picture(resource, 0, 0 if picture is None else 1, picture, 8, 2,
                      tim.MODE_8BIT, vram_x, 0, has_clut)


def test_resource_599s_six_pictures():
    what = [rp.role(_pic(rs.DISC_CHANGE, n)).what for n in range(6)]
    assert what[0].endswith("disc 1") and what[1].endswith("disc 2")
    assert "failed" in what[2] and what[2].endswith("check") and "disc 1" in what[2]
    assert "failed" in what[3] and "disc 2" in what[3]
    assert "_SECOND.XA" in what[4]
    assert what[5].endswith("for ever")


def test_a_bromides_two_pictures():
    top = rp.role(_pic(rs.BROMIDE_BASE + 4, 0))
    bottom = rp.role(_pic(rs.BROMIDE_BASE + 4, 1, has_clut=False))
    assert (top.what, top.draw_clut) == ("bromide 4, top", None)
    assert (bottom.what, bottom.draw_clut) == ("bromide 4, bottom", rp.BROMIDE_CLUT)


def test_the_title_resource():
    assert rp.role(_pic(rp.TITLE_RESOURCE, None, vram_x=768)).what == "title page: PRESS START"
    assert rp.role(_pic(rp.TITLE_RESOURCE, 0)).what == "card shown before the title"
    assert rp.role(_pic(rp.TITLE_RESOURCE, 3)).what == "card no code shows"
    atlas = rp.role(_pic(rp.GLYPH_ATLAS_RESOURCE, None))
    assert (atlas.what, atlas.draw_clut) == ("the glyph atlas", rp.GLYPH_CLUT)


RAMP = [0] + [rgb555(i * 2, i, 31 - i) for i in range(1, 16)]


def test_a_picture_with_no_clut_takes_the_row_the_earlier_one_left():
    # Bromide-shaped: picture 0 brings row 509's colours, picture 1 has none.
    pixels = bytes([0x10, 0x32, 0x54, 0x76]) * 2
    buf = _list((0x102, _packed(_tim4(pixels, 2, 2, RAMP, (0, 509)))),
                (0x202, _packed(_tim4(pixels, 2, 2))))
    pics = rp.pictures(buf, rs.BROMIDE_BASE)
    assert [(p.picture, p.has_clut) for p in pics] == [(0, True), (1, False)]
    img, note = rp.image(buf, pics[1])
    assert "0x7f40" in note and "row 509" in note
    assert img.getpixel((0, 0))[3] == 0                 # the word 0 is not drawn
    assert img.getpixel((1, 0)) == ((RAMP[1] & 0x1F) << 3, ((RAMP[1] >> 5) & 0x1F) << 3,
                                     ((RAMP[1] >> 10) & 0x1F) << 3, 255)


def test_a_sent_tim_is_drawn_as_the_list_leaves_its_row():
    pixels = bytes([0x11]) * 8
    other = [0] + [rgb555(31, 0, 0)] * 15
    buf = _list((0x002, _packed(_tim4(pixels, 2, 2, RAMP, (0, 504)))),
                (0x002, _packed(_tim4(pixels, 2, 2, other, (0, 504)))))
    first = rp.pictures(buf, rp.TITLE_RESOURCE)[0]
    img, note = rp.image(buf, first)
    assert "row 504" in note and "later" in note
    assert img.getpixel((0, 0))[:3] == (248, 0, 0)


_DISC = config.raw_dir("SLUS_006.28")


@pytest.mark.disc
@pytest.mark.skipif(not (_DISC / "SLUS_006.28").exists(),
                    reason="SLUS_006.28 is not extracted in the library")
def test_on_the_disc_command_2_holds_the_41():
    from decoders.psx.analysis.exe_loader import load_exe
    from decoders.plugins.SLUS_006_28.formats.resource_table import load_resource_table
    table = load_resource_table(load_exe(_DISC / "SLUS_006.28"))
    found = []
    with open(_DISC / "LUNADATA.FIL", "rb") as f:
        for res in table:
            if rs.is_command_list(res.index):
                f.seek(res.offset)
                found += rp.pictures(f.read(res.size), res.index)
    by_resource = {}
    for p in found:
        by_resource.setdefault(p.resource, []).append(p.picture)
    assert len(found) == 41
    assert by_resource[rp.GLYPH_ATLAS_RESOURCE] == [None]
    assert sorted(n for n in by_resource[rp.TITLE_RESOURCE] if n is not None) == [0, 1, 2, 3, 4]
    assert by_resource[rp.TITLE_RESOURCE].count(None) == 3
    assert all(by_resource[rs.BROMIDE_BASE + k] == [0, 1] for k in range(13))
    assert by_resource[rs.DISC_CHANGE] == [0, 1, 2, 3, 4, 5]
    assert all(rp.role(p).what != "a picture" for p in found)


def test_the_japanese_title_resource_shows_five_cards_and_names_no_page():
    jp = rp.programs.JP
    assert rp.role(_pic(rp.TITLE_RESOURCE, None, vram_x=768), jp).what == "a title page"
    cards = [rp.role(_pic(rp.TITLE_RESOURCE, n), jp).what for n in range(rp.JP_CARDS)]
    assert cards[0] == "card 1 of 5 shown before the title"
    assert cards[4] == "card 5 of 5 shown before the title"
    assert rp.role(_pic(rp.GLYPH_ATLAS_RESOURCE, None), jp).what == "the glyph atlas"


# -- a bromide's show ----------------------------------------------------------

def test_the_fade_dies_away_and_grows_as_screen_fade_step_reckons_it():
    assert rp.fade_strength(rp.FADE_IN, 32, 32) == 0xFF            # black at first
    assert rp.fade_strength(rp.FADE_IN, 1, 32) == 7
    assert rp.fade_strength(rp.FADE_OUT, 32, 32) == 0               # -7, held at 0
    assert rp.fade_strength(rp.FADE_OUT, 2, 32) == 0xFF * 29 // 32
    assert rp.fade_strength(rp.FADE_OUT, 1, 32) == 0xFF             # its last frame
    assert rp.fade_strength(rp.FADE_IN, 0, 32) == 0                 # none left


def test_the_pan_goes_down_the_picture_and_back_up():
    show = rp.bromide_show()
    rows = [f.row for f in show]
    assert len(show) == rp.BROMIDE_SHOWN + rp.BROMIDE_FADE
    assert rows[0] == 0 and rows[-1] == 0                           # held at 0
    assert max(rows) == 254 and 300 < rows.index(254) < 420         # half a turn in
    assert all(a <= b for a, b in zip(rows[:rows.index(254)], rows[1:rows.index(254)]))
    dark = [f.dark for f in show]
    assert dark[0] == 0xFF and dark[rp.BROMIDE_FADE - 1] == 7
    assert set(dark[rp.BROMIDE_FADE:rp.BROMIDE_SHOWN]) == {0}
    assert dark[-1] == 0xFF


def _tim8(pixels: bytes, pix_w: int, pix_h: int, clut=None, clut_at=(0, 0), at=(0, 0)) -> bytes:
    flags = tim.MODE_8BIT | (0x08 if clut else 0)
    out = u32(tim.TIM_MAGIC, flags)
    if clut:
        body = u16(*clut)
        out += u32(12 + len(body)) + u16(*clut_at, len(clut), 1) + body
    return out + u32(12 + len(pixels)) + u16(*at, pix_w, pix_h) + pixels


def test_a_bromide_is_one_column_of_video_memory_the_screen_pans_down():
    """Picture 1 over picture 0 where they meet, each at its own place from
    x 320, as tall as the pan's last row and the screen."""
    row = [0] + [rgb555(31, 0, 0)] + [rgb555(0, 0, 31)] * 254
    top = _tim8(bytes([1]) * 4 * 6, 2, 6, row, (0, 509), (rp.BROMIDE_PAGE_X, 0))
    bottom = _tim8(bytes([2]) * 4 * 5, 2, 5, None, (0, 0), (rp.BROMIDE_PAGE_X + 2, 4))
    buf = _list((0x102, _packed(top)), (0x202, _packed(bottom)))
    img, found = rp.bromide_image(buf, rs.BROMIDE_BASE)
    assert img.size == (rp.SCREEN_W, 254 + rp.SCREEN_H)
    assert [p.picture for p, _c in found] == [0, 1]
    assert img.getpixel((0, 3)) == (248, 0, 0, 255)                 # the top
    assert img.getpixel((0, 4)) == (248, 0, 0, 255)                 # left of the bottom
    assert img.getpixel((4, 4)) == (0, 0, 248, 255)                 # the bottom, over it
    assert img.getpixel((0, 9))[3] == 0                             # nothing there

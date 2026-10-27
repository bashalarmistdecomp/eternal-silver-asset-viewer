"""What the World Maps tab hands the client to draw a map's ground from
(field_view.ground_data) — made-up words and pages, no game data.

What this CAN catch: the tile words packed little-endian in plane order,
a page cut or padded to its size, each part's place in the one blob, the
second layer passed as its indexes and row 508's colours (bit 15 set,
colour 0 of each CLUT 0) and as the blend switch, and the tile and
palette animations passed through.

What it CANNOT catch: whether the client draws them as bg_first_draw
(0x80014058) does; the app's pictures were compared with the backend's
own (formats.field_picture) on the library's discs.
"""

import struct

from PIL import Image

from decoders.plugins.SLUS_006_28.formats import field_picture as fp
from viewer_tabs import field_view as fv


def _ground(under=None, indexes=None) -> fp.Ground:
    plane = [[0x1234, 0x0001], [0x2000, 0xFFFF]]
    return fp.Ground(image=None, plane=plane, sheets={}, stp_sheets={}, layer2=under is not None,
                     notes=[], pages={0: bytes(range(10)), 1: bytes(70000)},
                     rows=[[0] * 256, list(range(0x100, 0x200))], under=under,
                     layer2_indexes=indexes)


def _part(d, name):
    at, n = d["parts"][name]
    return d["blob"][at:at + n]


def test_words_pages_and_parts():
    seeds = [{"delay": 8, "frames": 6, "count": 2, "tile": 0x21E, "source": 0}]
    palette = {"set": 3, "slots": [], "copy": None}
    d = fv.ground_data(_ground(), b"", 1, seeds, b"\x07" * 512, palette)
    assert _part(d, "words") == struct.pack("<4H", 0x1234, 0x0001, 0x2000, 0xFFFF)
    page0 = _part(d, "page0")
    assert len(page0) == 256 * 256 and page0[:10] == bytes(range(10)) and not any(page0[10:])
    assert len(_part(d, "page1")) == 256 * 256          # cut to the page
    assert [p["page"] for p in d["pages"]] == [0, 1]
    assert _part(d, "tileImages") == b"\x07" * 512
    # the parts lie back to back
    spans = sorted(d["parts"].values())
    assert all(a + n == b for (a, n), (b, _m) in zip(spans, spans[1:]))
    assert d["tiles"] == seeds and d["columns"] == 2
    assert d["rows"] == [[0] * 256, list(range(0x100, 0x200))]
    assert d["cover"] == [] and d["blend"] is False and d["layer2"] is None
    assert d["palette"] is palette


def test_the_second_layer_drawn_behind_makes_the_tiles_blend():
    under = Image.new("RGBA", (16, 16), (0, 0, 0, 255))
    d = fv.ground_data(_ground(under, bytes([0, 0x13, 0xF2]) * 7), b"", 1, [], b"")
    assert d["blend"] is True and d["palette"] is None
    assert _part(d, "layer2") == bytes([0, 0x13, 0xF2]) * 7
    l2 = d["layer2"]
    assert (l2["w"], l2["h"], len(l2["row"])) == (512, 1024, 256)
    # row 508: row 1 with bit 15 set, colour 0 of every CLUT 0
    assert l2["row"][0] == 0 and l2["row"][16] == 0 and l2["row"][0x13] == 0x8113

"""Tier 1 for the shops' stock — a synthetic EXE image, no game data.

What this CAN catch: a row read at the wrong base or stride, shop n read
from any row but n - 1, an empty place kept in the stock, the extent
(40 shops) and the two numbers the code treats apart (8 never opens, 0x22
takes no money).

What it CANNOT catch: whether 0x800A8468 is this program's table, or the
rules of ShopRun (0x80050694) and ShopListSet (0x80051768) themselves;
only re-reading shop_run.c and shop_screen.c does that. See
decoders/testing.py.
"""

import pytest

from decoders.plugins.SLUS_006_28.records import shops


def _image(rows: dict[int, bytes]) -> bytes:
    img = bytearray(shops.BASE_ADDR + shops.COUNT * shops.STRIDE - shops.EXE_BASE)
    for row, raw in rows.items():
        off = shops.BASE_ADDR + row * shops.STRIDE - shops.EXE_BASE
        img[off:off + len(raw)] = raw
    return bytes(img)


def test_shop_n_is_row_n_less_1_and_empty_places_are_left_out():
    every = shops.read_from_exe(_image({0: bytes([3, 0, 9, 0, 0, 0]),
                                        4: bytes([1, 2, 3, 4, 5, 6])}))
    assert len(every) == shops.COUNT == 40
    assert [s.number for s in every] == list(range(1, 41))
    assert every[0].places == (3, 0, 9, 0, 0, 0) and every[0].items == (3, 9)
    assert every[4].number == 5 and every[4].items == (1, 2, 3, 4, 5, 6)
    assert every[1].items == ()


def test_shop_8_never_opens_and_shop_0x22_is_free():
    every = shops.read_from_exe(_image({}))
    assert [s.number for s in every if not s.opens] == [8]
    assert [s.number for s in every if s.free] == [0x22]


def test_a_short_image_is_refused():
    with pytest.raises(ValueError):
        shops.read_from_exe(bytes(16))

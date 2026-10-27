"""The Sprites tab's page layers — made-up pages, no disc.

What this CAN catch: a page shown for one palette row with the other rows'
sprites at full strength, a texel read under two rows taking the higher,
or an unread texel painted at all.

What it CANNOT catch: which row the game draws a sprite with; that is
map_object_sets.record_draw's, tested there.
"""

from PIL import Image

from viewer_tabs.tab_providers import _DIMMED, _as_drawn, _dim_outside


def _flat(colour, size=(256, 2)):
    return Image.new("RGBA", size, colour)


def test_dim_outside_fades_only_other_texels():
    page = _flat((10, 20, 30, 255), (4, 1))
    out = _dim_outside(page, {(0, 1, 0, 2, 1)}, 0)
    assert [out.getpixel((x, 0))[3] for x in range(4)] == [int(255 * _DIMMED), 255, 255,
                                                          int(255 * _DIMMED)]
    assert out.getpixel((1, 0))[:3] == (10, 20, 30)


def test_as_drawn_takes_each_texel_from_its_own_row():
    rendered = {504: {0: _flat((255, 0, 0, 255))}, 505: {0: _flat((0, 0, 255, 255))}}
    owners = {504: {(0, 0, 0, 2, 1)}, 505: {(0, 1, 0, 2, 1), (0, 10, 1, 1, 1)}}
    (page,), shared = _as_drawn({0: 2}, rendered, owners)
    assert page.getpixel((0, 0)) == (255, 0, 0, 255)      # 504's alone
    assert page.getpixel((1, 0)) == (255, 0, 0, 255)      # both: the lower row
    assert page.getpixel((2, 0)) == (0, 0, 255, 255)      # 505's alone
    assert page.getpixel((10, 1)) == (0, 0, 255, 255)
    assert page.getpixel((5, 0))[3] == 0                  # nobody's: blank
    assert shared == 1


def test_as_drawn_keeps_a_lower_rows_texel_under_a_transparent_one():
    # Colour 0 is transparent in every row: a clear texel of one row must not
    # punch through what another row drew there.
    clear = _flat((0, 0, 0, 0))
    rendered = {504: {0: clear}, 505: {0: _flat((0, 0, 255, 255))}}
    owners = {504: {(0, 0, 0, 1, 1)}, 505: {(0, 0, 0, 1, 1)}}
    (page,), _shared = _as_drawn({0: 2}, rendered, owners)
    assert page.getpixel((0, 0)) == (0, 0, 255, 255)

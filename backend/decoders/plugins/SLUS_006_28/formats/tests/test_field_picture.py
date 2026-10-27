"""Tier 1 for a field map drawn with what stands on it — made-up pictures,
no game data.

What this CAN catch: the depth key's direction (lower on the map in
front), the queue order at one depth (the earlier on top, the twins
walked first), the twins behind every body, the cover cells a piece
reaches (both ends counted), a roof copy over a class-0x2000 sprite and
not over a class-0x4000 one in front of it, the half-and-half and black
colours, the roof copies laid out alone, and a tile animation's cells and
the images each of its frames puts on the page.

What it CANNOT catch: whether those rules are the functions'. Only
re-reading sprite_draw (0x8001A528), sprite_list_draw (0x8001A798),
bg_cover_box_set (0x80013EF0), bg_first_draw (0x80014058),
tile_animation_step (0x80026690) and tile_image_load (0x80026754) does that:
both sides of every assertion here were written together. See
decoders/testing.py.
"""

from PIL import Image

from decoders.plugins.SLUS_006_28.formats import field_motion as fmo
from decoders.plugins.SLUS_006_28.formats import field_picture as fp
from decoders.plugins.SLUS_006_28.formats import world_map as wm

WHITE, RED, GREEN, BLUE = (255, 255, 255, 255), (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)
ROOF = wm.TILE_OVERLAY


def _ground(roof_at=None) -> fp.Ground:
    plane = [[0] * 8 for _ in range(8)]
    if roof_at:
        plane[roof_at[1]][roof_at[0]] = ROOF
    t = wm.decode_tile(ROOF)
    sheet = Image.new("RGBA", wm.PAGE_SIZE[t.page], BLUE)
    return fp.Ground(image=Image.new("RGBA", (128, 128), WHITE), plane=plane,
                     sheets={(t.page, t.clut): sheet}, stp_sheets={}, layer2=False, notes=[])


def _sprite(colour, left, top, depth, size=8, **kw) -> fp.Sprite:
    return fp.Sprite(image=Image.new("RGBA", (size, size), colour), left=left, top=top,
                     depth=depth, pieces=[(left, top, size, size)], **kw)


def test_queue_order():
    assert fp.queue_of(0x46) == 0 and fp.queue_of(0x6D) == 0x27
    assert fp.queue_of(0) == 0x28 and fp.queue_of(0x10) == 0x38
    assert fp.queue_of(0x45) < fp.queue_of(0x6E)


def test_lower_on_the_map_is_in_front():
    far = _sprite(RED, 10, 10, depth=20, queue=fp.queue_of(0x10))
    near = _sprite(GREEN, 12, 12, depth=30, queue=fp.queue_of(0x11))
    img = fp.compose(_ground(), [near, far])
    assert img.getpixel((13, 13)) == GREEN
    assert fp.body_entry(30) < fp.body_entry(20)


def test_at_one_depth_the_earlier_queued_is_on_top():
    first = _sprite(RED, 10, 10, depth=20, queue=fp.queue_of(0))
    later = _sprite(GREEN, 12, 12, depth=20, queue=fp.queue_of(0x10))
    assert fp.compose(_ground(), [later, first]).getpixel((13, 13)) == RED


def test_twins_lie_behind_every_body():
    twin = _sprite(RED, 10, 10, depth=100, twin=True, queue=fp.queue_of(0x56))
    body = _sprite(GREEN, 12, 12, depth=0, queue=fp.queue_of(0x10))
    assert fp.compose(_ground(), [twin, body]).getpixel((13, 13)) == GREEN


def test_cover_cells_count_both_ends():
    s = fp.Sprite(image=Image.new("RGBA", (1, 1)), left=0, top=0, depth=40,
                  pieces=[(10, 20, 16, 8)])
    assert fp.cover_cells([s]) == {(0, 1): s.entry - 1, (1, 1): s.entry - 1}
    over = fp.Sprite(image=Image.new("RGBA", (1, 1)), left=0, top=0, depth=40,
                     pieces=[(10, 20, 16, 8)], klass=0x4000)
    assert fp.cover_cells([over]) == {}


def test_roof_copy_over_a_class_2000_sprite_only():
    under = _sprite(RED, 18, 18, depth=40, queue=fp.queue_of(0x10))
    assert fp.compose(_ground(roof_at=(1, 1)), [under]).getpixel((20, 20)) == BLUE
    assert fp.compose(_ground(), [under]).getpixel((20, 20)) == RED
    over = _sprite(GREEN, 18, 18, depth=40, queue=fp.queue_of(0x10), klass=0x4000)
    assert fp.compose(_ground(roof_at=(1, 1)), [over]).getpixel((20, 20)) == GREEN
    # a class-0x4000 sprite in front of the copy another one raised lies over it
    front = _sprite(GREEN, 18, 18, depth=60, queue=fp.queue_of(0x11), klass=0x4000)
    assert fp.compose(_ground(roof_at=(1, 1)), [under, front]).getpixel((20, 20)) == GREEN


def test_semi_and_black():
    semi = _sprite(RED, 10, 10, depth=20, semi=True)
    assert fp.compose(_ground(), [semi]).getpixel((12, 12))[:3] == (255, 127, 127)
    shade = _sprite(RED, 10, 10, depth=20, semi=True, black=True)
    assert fp.compose(_ground(), [shade]).getpixel((12, 12))[:3] == (127, 127, 127)


def test_roof_layers_hold_the_copies_alone():
    opaque, stp = fp.roof_layers(_ground(roof_at=(1, 1)))
    assert opaque.getpixel((20, 20)) == BLUE and opaque.getpixel((40, 20))[3] == 0
    assert stp is None


def test_tile_patches_frames_and_cells():
    plane = [[0] * 8 for _ in range(8)]
    plane[3][2] = plane[5][5] = 1                   # page 0, u 16, v 0: page tile 1
    page = bytes(256 * 256)
    words = [0, 0x001F, 0x03E0, 0x7C00, 0x7FFF] + [0] * 251
    g = fp.Ground(image=Image.new("RGBA", (128, 128)), plane=plane, sheets={},
                  stp_sheets={}, layer2=False, notes=[], pages={0: page}, rows=[words])
    images = b"".join(bytes([n]) * fmo.FIELD_TILE_AT for n in range(6))
    anim = fmo.TileAnimation(delay=4, frames=3, count=1, tile=1, source=2)
    (p,) = fp.tile_patches(g, [anim], images)
    assert (p.delay, p.frames) == (4, 3)
    assert p.cells == [(32, 48, 0), (80, 80, 0)]    # one tile word: one patch
    # frame k puts image source + k * count on the page: colours 2, 3, 4
    assert [pic.getpixel((5, 5)) for pic in p.pictures] == [
        (0, 248, 0, 255), (0, 0, 248, 255), (248, 248, 248, 255)]
    assert fp.tile_patches(g, [fmo.TileAnimation(4, 3, 1, 0x20, 2)], images) == []

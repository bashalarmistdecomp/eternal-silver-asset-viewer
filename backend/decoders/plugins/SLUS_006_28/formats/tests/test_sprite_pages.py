"""Tier 1 for the actor-block layout and the pose composer — synthetic bytes.

What this CAN catch: a table base read at the wrong header word, the anim
HOLD bit, and — the reason the file exists — frame +0x00 being treated as
anything but the renderer's FLAGS word. In sprite_piece_draw (0x80019DBC)
0x10 is the X-flip bit: a slice with it set is the descriptor's texels
MIRRORED (sprite_mirror_draw, 0x80016F44), never shifted.
`test_flag_0x10_mirrors_and_does_not_shift` pins that.

What it CANNOT catch: whether these rules are the function's. Only
re-reading sprite_draw (0x8001A528) / sprite_piece_draw / sprite_quad_draw (0x800174F0) does that. See
decoders/testing.py.
"""

import struct

import pytest

from PIL import Image

from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp


def _block(frames, descs, anims=((1, 0),), steps=((0, 5),), poses=None):
    """Assemble an actor block: 6-word header, then the five tables."""
    poses = poses or [(len(frames), 0)]
    body = []
    head_words = 4                     # 12 header bytes + 4 pad -> 16 bytes
    tables = [b"".join(struct.pack("<2H", *a) for a in anims),
              b"".join(struct.pack("<2H", *s) for s in steps),
              b"".join(struct.pack("<2H", *p) for p in poses),
              b"".join(struct.pack("<H2hH8h", *f) for f in frames),
              b"".join(struct.pack("<HHHHHH", 0, d[0], 0, 0, d[1], d[2]) for d in descs)]
    offs, at = [], head_words * 4
    for t in tables:
        offs.append(at // 4)
        body.append(t)
        at += len(t)
    offs.append(at // 4)
    return struct.pack("<6H", *offs) + b"\0" * 4 + b"".join(body)


def _page():
    """A 64x8 page whose pixel (x, y) is opaque with red = x, green = y."""
    img = Image.new("RGBA", (64, 8))
    img.putdata([(x, y, 0, 255) for y in range(8) for x in range(64)])
    return img


def test_header_words_place_every_table():
    blk = sp.parse_actor_block(_block(frames=[(0, 4, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0)],
                                      descs=[(0, 8, 0)]))
    assert blk is not None
    assert blk.frame_count == 1 and blk.desc_count == 1
    assert blk.slice(0).w == 4 and blk.descriptor(0) == (0, 8, 0)


def test_animation_hold_bit_and_steps():
    raw = _block(frames=[(0, 1, 1, 0) + (0,) * 8], descs=[(0, 0, 0)],
                 anims=((2, 0), (0x8000 | 1, 2)),
                 steps=((0, 12), (0, 3), (0, 40)))
    a = sp.parse_actor_block(raw).animations()
    assert [(x.count, x.hold) for x in a] == [(2, False), (1, True)]
    assert a[0].steps == ((0, 12), (0, 3)) and a[1].steps == ((0, 40),)


def test_anim_tables_are_the_raw_bytes():
    anims, steps = ((2, 0), (0x8000 | 1, 2)), ((0, 12), (0, 3), (0, 40))
    raw = _block(frames=[(0, 1, 1, 0) + (0,) * 8], descs=[(0, 0, 0)],
                 anims=anims, steps=steps)
    a, s = sp.parse_actor_block(raw).anim_tables()
    assert a == b"".join(struct.pack("<2H", *x) for x in anims)       # HOLD bit kept
    assert s == b"".join(struct.pack("<2H", *x) for x in steps)


def test_pose_and_frame_tables_are_the_raw_bytes():
    frames = [(0, 1, 1, 0) + (0,) * 8, (0x10, 4, 2, 0, -4, 0) + (0,) * 6]
    raw = _block(frames=frames, descs=[(0, 0, 0)], poses=[(2, 0), (1, 1)])
    p, f = sp.parse_actor_block(raw).pose_frame_tables()
    assert p == b"".join(struct.pack("<2H", *x) for x in [(2, 0), (1, 1)])
    assert len(f) == 2 * sp.FRAME_STRIDE
    hdr = struct.unpack_from("<6H", raw, 0)
    assert f == raw[hdr[3] << 2:hdr[4] << 2]                 # header words, x4


def test_flag_0x10_mirrors_and_does_not_shift():
    # Two 4x2 slices sharing descriptor u=8: plain at xo=-4, flipped at xo=0
    # — the symmetric-sprite pattern the old "u offset" reading misread.
    raw = _block(frames=[(0x10, 4, 2, 0, 0, 0) + (0,) * 6,
                         (0x00, 4, 2, 0, -4, 0) + (0,) * 6],
                 descs=[(0, 8, 0)])
    blk = sp.parse_actor_block(raw)
    out = sp.compose_pose(blk, _page(), sp.Pose(0, 0, 0, 2), origin=(4, 0), size=(8, 2))
    reds = [out.getpixel((x, 0))[0] for x in range(8)]
    assert reds == [8, 9, 10, 11, 11, 10, 9, 8]      # mirrored, never 12..15


def test_flag_0x20_flips_vertically():
    raw = _block(frames=[(0x20, 1, 2, 0) + (0,) * 8], descs=[(0, 3, 4)])
    out = sp.compose_pose(sp.parse_actor_block(raw), _page(), sp.Pose(0, 0, 0, 1),
                          origin=(0, 0), size=(1, 2))
    assert [out.getpixel((0, y))[1] for y in range(2)] == [5, 4]


def test_last_slice_ends_on_top():
    # Both slices cover pixel 0; slice 0 is drawn first (AddPrim head insertion).
    raw = _block(frames=[(0, 1, 1, 0) + (0,) * 8, (0, 1, 1, 1) + (0,) * 8],
                 descs=[(0, 1, 0), (0, 2, 0)])
    out = sp.compose_pose(sp.parse_actor_block(raw), _page(), sp.Pose(0, 0, 0, 2),
                          origin=(0, 0), size=(1, 1))
    assert out.getpixel((0, 0))[0] == 2


def test_descriptor_slot_selects_the_page():
    raw = _block(frames=[(0, 1, 1, 0) + (0,) * 8], descs=[(3, 5, 0)])
    other = Image.new("RGBA", (64, 8), (200, 0, 0, 255))
    out = sp.compose_pose(sp.parse_actor_block(raw), {0: _page(), 3: other},
                          sp.Pose(0, 0, 0, 1), origin=(0, 0), size=(1, 1))
    assert out.getpixel((0, 0))[0] == 200


def test_rect_slice_corners_follow_sprite_piece_edges_get():
    # kind 0x1000, mode 0x0A = x centred (2), y centred (2): half = (n+1)/2.
    s = sp.Slice(flags=0x1A00, w=4, h=4, desc=0, pts=(10, 20, 5, 3, 0, 0, 0, 0))
    (tl, tr, br, bl) = s.corners()
    assert tl == (7, 18) and br == (14, 23)          # (10±3, 20±2), +1 exclusive


def test_quad_slice_maps_the_texture():
    # kind 0x3000 with an axis-aligned 2x unscaled square: TL TR BR BL.
    raw = _block(frames=[(0x3000, 4, 2, 0, 0, 0, 3, 0, 3, 1, 0, 1)],
                 descs=[(0, 8, 0)])
    out = sp.compose_pose(sp.parse_actor_block(raw), _page(), sp.Pose(0, 0, 0, 1),
                          origin=(0, 0), size=(6, 3))
    assert out.getpixel((0, 0))[0] == 8              # TL samples (u, v)
    assert out.getpixel((0, 0))[3] == 255
    assert out.getpixel((5, 2))[3] == 0              # outside the quad stays clear


def test_pose_extent_spans_all_slices():
    raw = _block(frames=[(0, 4, 2, 0, -4, -2) + (0,) * 6, (0, 2, 2, 0, 1, 0) + (0,) * 6],
                 descs=[(0, 0, 0)])
    assert sp.pose_extent(sp.parse_actor_block(raw), sp.Pose(0, 0, 0, 2)) == (-4, -2, 3, 2)


def test_pose_extent_tpages_keeps_only_those_slices():
    raw = _block(frames=[(0, 4, 2, 0, -4, -2) + (0,) * 6, (0, 2, 2, 1, 1, 0) + (0,) * 6],
                 descs=[(0, 0, 0), (3, 0, 0)])
    blk = sp.parse_actor_block(raw)
    assert sp.pose_extent(blk, sp.Pose(0, 0, 0, 2), tpages={3}) == (1, 0, 3, 2)


def test_pose_extent_leaves_out_corners_the_gpu_cannot_reach():
    # a slice at -32768 spanning 32767 would size a canvas of gigabytes
    raw = _block(frames=[(0, 4, 2, 0, -4, -2) + (0,) * 6,
                         (0, 32767, 32767, 0, -32768, -32768) + (0,) * 6],
                 descs=[(0, 0, 0)])
    assert sp.pose_extent(sp.parse_actor_block(raw), sp.Pose(0, 0, 0, 2)) == (-4, -2, 0, 0)


def test_pose_sheet_cell_k_is_pose_k_on_one_anchor():
    # Pose 0 sits up-left of the anchor, pose 1 down-right; table entry 2
    # names no slices. One cell spans both, anchored where they meet.
    raw = _block(frames=[(0, 2, 1, 0, -2, -1) + (0,) * 6, (0, 1, 2, 1, 0, 0) + (0,) * 6],
                 descs=[(0, 4, 0), (0, 9, 0)],
                 poses=[(1, 0), (1, 1), (0, 0)])
    sheet = sp.pose_sheet(sp.parse_actor_block(raw), _page(), columns=2)
    assert (sheet.cell_w, sheet.cell_h, sheet.anchor_x, sheet.anchor_y) == (3, 3, 2, 1)
    assert sheet.image.size == (6, 6)                # 3 table entries -> 2 rows
    assert sheet.cells[2] is None
    assert sheet.image.getpixel((0, 0))[0] == 4      # pose 0, up-left of the anchor
    assert sheet.image.getpixel((3 + 2, 1))[0] == 9  # pose 1, at its cell's anchor
    assert sheet.image.getpixel((3 + 0, 0))[3] == 0  # ... and nothing of pose 0


def test_actor_box_is_btl_record_size_set():
    """The box of anim 0's FIRST step's pose, anchor included, from the raw
    (xo, w) / (yo, h) of every slice — flips and kinds ignored."""
    frames = [(0x10, 6, 4, 0, -10, -20) + (0,) * 6,      # x -10..-4, y -20..-16
              (0x3000, 8, 3, 0, 2, -5) + (0,) * 6]        # x 2..10,  y -5..-2
    raw = _block(frames=frames, descs=[(0, 0, 0)],
                 anims=((1, 1), (1, 0)), steps=((1, 4), (0, 4)),
                 poses=[(1, 0), (2, 0)])
    blk = sp.parse_actor_block(raw)
    # anim 0 -> step 1 -> pose 0 -> slice 0 only: x0 = -10, x1 = max(0, -4) = 0
    assert blk.actor_box(0) == (10, 20)
    # anim 1 -> step 0 -> pose 1 -> both slices: |-10| + 10, |-20| + 0
    assert blk.actor_box(1) == (20, 20)


def test_actor_box_counts_the_anchor():
    """A pose wholly right of / below the anchor still spans from 0."""
    raw = _block(frames=[(0, 5, 7, 0, 3, 4) + (0,) * 6], descs=[(0, 0, 0)])
    assert sp.parse_actor_block(raw).actor_box(0) == (8, 11)


def test_clut_fixup_swaps_bytes_sets_bit_15_and_clears_colour_0():
    raw = bytearray(b"".join(struct.pack(">H", i * 0x0101 & 0x7FFF) for i in range(256)))
    raw[0:2] = b"\x12\x34"                           # colour 0 becomes 0
    raw += b"\xEE" * 64                              # past the palette: never read
    pal = sp.sprite_init_palette(bytes(raw))
    assert len(pal) == sp.PALETTE_BYTES and pal[0:2] == b"\0\0"
    for i in (1, 2, 0x7F, 0xFF):
        assert struct.unpack_from("<H", pal, 2 * i)[0] == (i * 0x0101 & 0x7FFF) | 0x8000
    with pytest.raises(ValueError):
        sp.sprite_init_palette(bytes(100))


def test_the_draw_word_picks_the_palette_row():
    assert sp.SPRITE_INIT_PALETTES == {504: 0xE5, 505: 0xE6}
    assert sp.palette_row(0x2000) == 0 and sp.palette_row(0x2100) == 1
    assert sp.palette_row(0x2000 | 0x0800) == 0      # mode bits leave the row alone
    assert sp.clut_id(0x2370) == (0x1FB << 6) | (0x70 >> 4)


def test_texel_rects_are_the_textured_slices_descriptor_boxes():
    # A plain slice, a quad, an untextured kind (0x4000) and a 0-wide slice.
    raw = _block(frames=[(0, 4, 2, 0) + (0,) * 8,
                         (0x3000, 3, 3, 1, 0, 0, 3, 0, 3, 3, 0, 3),
                         (0x4000, 5, 5, 0) + (0,) * 8,
                         (0, 0, 2, 0) + (0,) * 8],
                 descs=[(0, 8, 1), (2, 16, 4)])
    assert sp.texel_rects(sp.parse_actor_block(raw)) == {(0, 8, 1, 4, 2), (2, 16, 4, 3, 3)}


def test_texel_mask_marks_one_slot_only():
    mask = sp.texel_mask({(0, 1, 2, 3, 2), (1, 0, 0, 8, 8)}, 0, (8, 8))
    on = {(x, y) for y in range(8) for x in range(8) if mask.getpixel((x, y))}
    assert on == {(x, y) for x in (1, 2, 3) for y in (2, 3)}

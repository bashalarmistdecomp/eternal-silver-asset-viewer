"""Sprite data: the block layout the field and the battle share (animations,
steps, poses, pieces, texel records), the composer that draws a pose the way
sprite_draw (0x8001A528) draws it, and the field's palette rows 504 and 505.

Where the blocks come from: a map object set's sprite data and pages
(`map_object_sets`), the party's field sheets (`party_field_sheets`), and the
battle's graphics sets and party bundle (`battle_gfx`). A block carries no
palette; sprite_draw takes one by the record's draw word (below).

See docs/spec/sprites.md and docs/spec/assets/sprites.md.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

# sprite_draw (0x8001A528) draws a record with the palette
#
#     GetClut(word & 0xFF, 0x1F8 | ((word >> 8) & 3))
#
# `word` being the record's draw word (+0x0E): bits 8-9 pick one of four
# palette rows and the low byte is the palette's x. On the field
# MapRecordInit (0x80065940) sets the word by the record's kind
# (`map_object_sets.record_draw`), and all four rows come from the disc:
#
#     504, 505   resources 0xE5 and 0xE6 through sprite_init (0x80018BFC)'s
#                fix-up (`SPRITE_INIT_PALETTES`, `sprite_init_palette`)
#     506        the map's own palette, its type-4 command
#                (resource_palette_load (0x80020A08), `map_object_sets.map_palette`)
#     507        resource 2's palette, colour 0 of every 16 zeroed
#                (sprite_reset (0x80018DBC), which sprite_init ends with)
CLUT_BASE_Y = 0x1F8          # 504
CLUT_ROWS = 4


def clut_id(word: int) -> int:
    """The GPU clut id a draw word selects."""
    x = word & 0xFF
    y = CLUT_BASE_Y | ((word >> 8) & (CLUT_ROWS - 1))
    return (y << 6) | (x >> 4)


def palette_row(word: int) -> int:
    """Which of the four palette rows a draw word selects (0-3)."""
    return (word >> 8) & (CLUT_ROWS - 1)


#: sprite_init (0x80018BFC): resource_load(0xE5) -> LoadClut(.., 0, 0x1F8) and
#: resource_load(0xE6) -> LoadClut(.., 0, 0x1F9), each after `clut_fixup`.
SPRITE_INIT_PALETTES = {504: 0xE5, 505: 0xE6}
PALETTE_BYTES = 512


def clut_fixup(raw: bytes) -> bytes:
    """sprite_init (0x80018BFC)'s fix-up of a freshly loaded palette: colour 0
    becomes 0, and colours 1..255 have their two bytes swapped and bit 15
    set. The stored palette is therefore big-endian with bit 15 clear."""
    out = bytearray(raw[:PALETTE_BYTES].ljust(PALETTE_BYTES, b"\x00"))
    out[0:2] = b"\x00\x00"
    for i in range(2, PALETTE_BYTES, 2):
        v = out[i] | (out[i + 1] << 8)
        v = (((v << 8) | (v >> 8)) & 0xFFFF) | 0x8000
        out[i] = v & 0xFF
        out[i + 1] = v >> 8
    return bytes(out)


def sprite_init_palette(raw: bytes) -> bytes:
    """Palette row 504 or 505 on the field: the first 512 bytes of resource
    0xE5 or 0xE6 (`SPRITE_INIT_PALETTES`) after `clut_fixup`."""
    if len(raw) < PALETTE_BYTES:
        raise ValueError(f"palette resource is {len(raw)} bytes, sprite_init reads {PALETTE_BYTES}")
    return clut_fixup(raw)


# ---------------------------------------------------------------------------
# Poses: composing individual characters out of a page
# ---------------------------------------------------------------------------
#
# A sprite is not a rectangle on the page — it is a stack of slices. Every number below is read
# off the renderer that draws the actor list g_SpriteList (0x800B88F4) (field AND battle actors
# go through it): sprite_list_draw (0x8001A798) walks the list, sprite_draw (0x8001A528) draws
# one entry, sprite_piece_draw (0x80019DBC) one slice.
#
#   block head   6 x u16 WORD offsets: anim, step, pose, frame, desc, end
#   anim  (4)    {u16 count, u16 first_step}; count bit 15 = HOLD on the
#                last step instead of looping            (BtlAnimationStep, 0x800272A8)
#   step  (4)    {u16 pose, u16 duration in ticks}
#   pose  (4)    {u16 count, u16 first_frame}            (sprite_draw)
#   frame (0x18) +00 u16 flags  +02 s16 w  +04 s16 h  +06 u16 desc index
#                +08..+16 eight s16: (xo, yo) for a plain slice, or the
#                corner points of a rect/quad slice     (sprite_piece_draw)
#   desc  (0x0C) +02 u16 page slot (index into g_SpritePageTPages (0x800DDD30))  +08 u8 u  +0A u8 v
#
#   for i in first+count-1 .. first:   the CALL order; AddPrim links each at the
#   HEAD of one ordering-table cell, so slice `first` is drawn FIRST (bottom)
#   and slice first+count-1 ends on top
#
# Frame +00 is NOT a u offset. An earlier reading took it for one because it
# only ever held 0 or 16 and "tracked xo": a 0x10 slice at xo=0 next to a
# plain one at xo=-16 sharing one descriptor. 0x10 is the X-FLIP bit — the
# right half of a symmetric sprite is the left half mirrored. sprite_piece_draw
# XORs `flags & 0x30` with the actor's own flip bits (actor +0x0C bits 13/14)
# and sends a flipped slice to sprite_mirror_draw (0x80016F44), whose POLY_FT4 maps the left
# edge to u+w-1 and the right edge to u-1: the texels u..u+w-1 reversed, no
# offset anywhere. `flags & 0x7000` is the slice KIND (0 = plain sprite,
# 0x1000/0x2000 = anchored rectangle, 0x3000 = free quad, 0x4000/0x5000 =
# untextured primitives this composer does not draw).

POSE_STRIDE = 4
FRAME_STRIDE = 0x18
DESC_STRIDE = 0x0C
ANIM_STRIDE = 4
STEP_STRIDE = 4
MAX_POSE_SLICES = 51        # the engine bails past this (sprite_draw (0x8001A528): slti 0x33)

ANIM_HOLD = 0x8000          # anim count bit 15 (BtlAnimationStep, 0x800272A8)
SLICE_KIND_MASK = 0x7000
SLICE_SPRITE = 0x0000       # SPRT-like: sprite_plain_draw (0x80016CF0) / sprite_mirror_draw (0x80016F44) when flipped
SLICE_RECT_A = 0x1000       # anchored rectangle: sprite_piece_edges_get (0x80019BEC) -> sprite_quad_draw (0x800174F0)
SLICE_RECT_B = 0x2000
SLICE_QUAD = 0x3000         # explicit four corners -> sprite_quad_draw (0x800174F0)
SLICE_FLIP_X = 0x10
SLICE_FLIP_Y = 0x20


@dataclass(frozen=True)
class Pose:
    """One drawable pose: a run of slice records."""
    table: int              # payload offset of the pose table it came from
    index: int              # entry within that table
    first: int              # first frame record index
    count: int              # number of slices

    @property
    def label(self) -> str:
        return f"tbl{self.table}[{self.index}]  {self.count} slices @{self.first}"


@dataclass(frozen=True)
class Slice:
    """One frame record, read the way sprite_piece_draw (0x80019DBC) reads it."""
    flags: int
    w: int
    h: int
    desc: int
    pts: tuple[int, ...]     # the eight s16 at +08..+16

    @property
    def kind(self) -> int:
        return self.flags & SLICE_KIND_MASK

    @property
    def flip_x(self) -> bool:
        return bool(self.flags & SLICE_FLIP_X)

    @property
    def flip_y(self) -> bool:
        return bool(self.flags & SLICE_FLIP_Y)

    @property
    def xo(self) -> int:
        return self.pts[0]

    @property
    def yo(self) -> int:
        return self.pts[1]

    def corners(self) -> tuple[tuple[int, int], ...] | None:
        """Destination corners TL, TR, BR, BL relative to the actor anchor.

        Plain slices are their (xo, yo, w, h) box; anchored rectangles follow
        sprite_piece_edges_get (0x80019BEC); quads take the record's own four points. Corners are
        EXCLUSIVE on the larger edge, as sprite_quad_draw (0x800174F0) makes them (it adds 1
        to the greater coordinate of each vertex pair). None for kinds this
        module does not draw.
        """
        p = self.pts
        if self.kind == SLICE_SPRITE:
            x0, y0 = p[0], p[1]
            x1, y1 = x0 + self.w, y0 + self.h
            return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        if self.kind in (SLICE_RECT_A, SLICE_RECT_B):
            x0, y0, x1, y1 = _rect_corners(self.flags, p)
            if x1 < x0:
                x0, x1 = x1, x0
            if y1 < y0:
                y0, y1 = y1, y0
            return ((x0, y0), (x1 + 1, y0), (x1 + 1, y1 + 1), (x0, y1 + 1))
        if self.kind == SLICE_QUAD:
            tl, tr, br, bl = (p[0], p[1]), (p[2], p[3]), (p[4], p[5]), (p[6], p[7])
            # sprite_quad_draw (0x800174F0)'s +1: the greater x of TL/TR and of BL/BR, the
            # greater y of TL/BL and of TR/BR.
            (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = tl, tr, br, bl
            if trx < tlx: tlx += 1
            else: trx += 1
            if brx < blx: blx += 1
            else: brx += 1
            if bly < tly: tly += 1
            else: bly += 1
            if bry < try_: try_ += 1
            else: bry += 1
            return ((tlx, tly), (trx, try_), (brx, bry), (blx, bly))
        return None


def _half_up(n: int) -> int:
    """C's `(n + (n >> 31)) >> 1` on n+1, as sprite_piece_edges_get (0x80019BEC) writes it."""
    t = n + 1
    return int(t / 2)            # truncates toward zero, like the C


def _rect_corners(flags: int, p: tuple[int, ...]) -> tuple[int, int, int, int]:
    """sprite_piece_edges_get (0x80019BEC): the rectangle an anchored slice covers (inclusive)."""
    mode = (flags & 0xF00) >> 8
    if mode == 0:
        return p[0], p[1], p[4], p[5]
    x0 = x1 = y0 = y1 = 0          # the C leaves an unset axis as stack garbage
    xm, ym = mode & 3, mode >> 2
    if xm == 1:
        x0, x1 = p[0], p[0] + p[2]
    elif xm == 2:
        x0, x1 = p[0] - _half_up(p[2]), p[0] + _half_up(p[2])
    elif xm == 3:
        x0, x1 = p[0] - p[2], p[0]
    if ym == 1:
        y0, y1 = p[1], p[1] + p[3]
    elif ym == 2:
        y0, y1 = p[1] - _half_up(p[3]), p[1] + _half_up(p[3])
    elif ym == 3:
        y0, y1 = p[1] - p[3], p[1]
    return x0, y0, x1, y1


@dataclass(frozen=True)
class Animation:
    """One entry of the anim table: a run of (pose, duration) steps.

    BtlAnimationStart (0x80027240) starts it (step = first, end = first + count), and
    BtlAnimationStep (0x800272A8) advances one step when the step's duration in ticks runs
    out: at the end it restarts (loop) — or, with count bit 15 set, stays on
    the last step (HOLD). The field's MapAnimationStart (0x80066468),
    MapPartyAnimationStep (0x80065CF8) and MapObjectsAnimationStep (0x80065FD8)
    step a table by the same rule. Which id plays when is decided by the code
    that calls BtlAnimationSet(actor, id) (0x80027208) or, on the field,
    MapAnimationSet (0x800663EC), not by this table."""
    index: int
    first: int
    count: int
    hold: bool
    steps: tuple[tuple[int, int], ...]     # (pose index, duration ticks)


@dataclass
class SpriteBlockData:
    """A decoded actor block: anim/step/pose/frame/descriptor tables.

    The same layout serves the field's sprite data (`map_object_sets`,
    `party_field_sheets`) and the battle's blocks (the graphics-set and party
    bundles, `battle_gfx`)."""
    payload: bytes
    frame_base: int
    desc_base: int
    pose_tables: list[int] = field(default_factory=list)
    anim_base: int = 0
    step_base: int = 0

    @property
    def frame_count(self) -> int:
        return max(0, (self.desc_base - self.frame_base) // FRAME_STRIDE)

    @property
    def pose_count(self) -> int:
        return max(0, (self.frame_base - self.pose_tables[0]) // POSE_STRIDE) \
            if self.pose_tables else 0

    @property
    def desc_count(self) -> int:
        return max(0, (len(self.payload) - self.desc_base) // DESC_STRIDE)

    def frame(self, i: int):
        """The record's first six fields: (flags, w, h, desc, xo, yo).

        The first field is the FLAGS word (see `Slice`), not a u offset."""
        off = self.frame_base + i * FRAME_STRIDE
        if i < 0 or off + 12 > len(self.payload):
            return None
        return struct.unpack_from("<4H2h", self.payload, off)

    def slice(self, i: int) -> Slice | None:
        off = self.frame_base + i * FRAME_STRIDE
        if i < 0 or off + FRAME_STRIDE > len(self.payload):
            return None
        flags, w, h, desc, *pts = struct.unpack_from("<H2hH8h", self.payload, off)
        return Slice(flags=flags, w=w, h=h, desc=desc, pts=tuple(pts))

    def descriptor(self, i: int):
        off = self.desc_base + i * DESC_STRIDE
        if i < 0 or off + 12 > len(self.payload):
            return None
        tpage = struct.unpack_from("<H", self.payload, off + 2)[0]
        u, v = struct.unpack_from("<HH", self.payload, off + 8)
        return tpage, u & 0xFF, v & 0xFF        # the renderer loads them (u8)

    def anim_tables(self) -> tuple[bytes, bytes] | None:
        """The anim table and the step table, byte for byte: what the battle
        setup points actor +0x28 and +0x2C at (header words 0 and 1), and
        what BtlAnimationStart (0x80027240) / BtlAnimationStep (0x800272A8) read. None if the block has no
        well-formed tables."""
        pose_base = self.pose_tables[0] if self.pose_tables else 0
        if not (0 < self.anim_base < self.step_base <= pose_base):
            return None
        return (self.payload[self.anim_base:self.step_base],
                self.payload[self.step_base:pose_base])

    def pose_frame_tables(self) -> tuple[bytes, bytes] | None:
        """The pose table and the frame table, byte for byte: what the battle
        setup points actor +0x14 and +0x18 at (payload header words 2 and 3,
        word counts, so x4), and what BtlRecordSizeSet (0x800381D8) reads (from BtlRecordInit (0x8002B770)):
        a pose entry is u16 frame count, u16 first frame; a frame record is
        FRAME_STRIDE bytes. Read from the header itself. None if the header
        does not partition them."""
        if len(self.payload) < 12:
            return None
        hdr = struct.unpack_from("<6H", self.payload, 0)
        pose_base, frame_base, desc_base = hdr[2] << 2, hdr[3] << 2, hdr[4] << 2
        if not (0 < pose_base < frame_base < desc_base <= len(self.payload)):
            return None
        return (self.payload[pose_base:frame_base], self.payload[frame_base:desc_base])

    def actor_box(self, anim: int = 0) -> tuple[int, int] | None:
        """BtlRecordSizeSet(actor, anim) (0x800381D8) — actor +0x3C and
        +0x3E: the width and height of the box that the FIRST step's pose of
        anim `anim` covers, the anchor included. Over the pose's frame
        records: x0 = min(0, xo), x1 = max(0, xo + w) and likewise y0 / y1
        from yo / h — the raw +0x08 / +0x02 / +0x0A / +0x04 fields of every
        slice, whatever its kind or flip bits — then width = |x0| + x1,
        height = |y0| + y1 (u16). The battle sets up every actor with anim 0
        (BtlRecordInit (0x8002B770), from BtlEnemyLoad (0x8002B3AC) and BtlPartyLoad (0x8002B114)) and nothing
        recomputes it in battle, so `actor_box(0)` is the +0x3C the arena
        code reads as the actor's FOOTPRINT (BtlWalkGridSlotBlock (0x8002C190) marks
        +0x3C / 8 tiles of its row, BtlWalkRun (0x8002BB5C) sizes the walker and the
        target by it). None when the block has no anim table."""
        pose_base = self.pose_tables[0] if self.pose_tables else 0
        if not (0 < self.anim_base < self.step_base <= pose_base):
            return None
        u16 = lambda off: struct.unpack_from("<H", self.payload, off)[0]
        first_step = u16(self.anim_base + ANIM_STRIDE * anim + 2)
        pose = u16(self.step_base + STEP_STRIDE * first_step)
        count = u16(pose_base + POSE_STRIDE * pose)
        first = u16(pose_base + POSE_STRIDE * pose + 2)
        s16 = lambda v: ((v & 0xFFFF) ^ 0x8000) - 0x8000
        x0 = x1 = y0 = y1 = 0
        for i in range(first, first + count):
            off = self.frame_base + FRAME_STRIDE * i
            w, h = struct.unpack_from("<2H", self.payload, off + 2)
            xo, yo = struct.unpack_from("<2h", self.payload, off + 8)
            if xo < s16(x0):
                x0 = xo & 0xFFFF
            if (x1 & 0xFFFF) < xo + w:
                x1 = (xo + w) & 0xFFFF
            if yo < s16(y0):
                y0 = yo & 0xFFFF
            if (y1 & 0xFFFF) < yo + h:
                y1 = (yo + h) & 0xFFFF
        return (abs(s16(x0)) + x1) & 0xFFFF, (abs(s16(y0)) + y1) & 0xFFFF

    def animations(self) -> list[Animation]:
        """The anim table, each entry resolved into its steps."""
        pose_base = self.pose_tables[0] if self.pose_tables else 0
        if not (0 < self.anim_base < self.step_base <= pose_base):
            return []
        n_steps = (pose_base - self.step_base) // STEP_STRIDE
        steps = [struct.unpack_from("<2H", self.payload, self.step_base + STEP_STRIDE * k)
                 for k in range(n_steps)]
        out = []
        for a in range((self.step_base - self.anim_base) // ANIM_STRIDE):
            raw_count, first = struct.unpack_from("<2H", self.payload,
                                                  self.anim_base + ANIM_STRIDE * a)
            count = raw_count & ~ANIM_HOLD & 0xFFFF
            run = tuple(tuple(s) for s in steps[first:first + count])
            out.append(Animation(index=a, first=first, count=count,
                                 hold=bool(raw_count & ANIM_HOLD), steps=run))
        return out


def _from_payload(payload: bytes) -> SpriteBlockData | None:
    # The payload head is a table of u16 **word** counts, so each entry scales
    # by 4 to give a byte offset (DAT at 0x800898EC; BtlEnemyLoad (0x8002B3AC) and
    # BtlPartyLoad (0x8002B114) set actor +0x28/+0x2C/+0x14/+0x18/+0x10 from words 0..4):
    #     +0x00 anim  +0x02 step  +0x04 pose  +0x06 frame  +0x08 descriptors
    # Reading these as byte offsets is what made the header look like it did
    # not partition the payload, and put descriptor reads at the wrong offset.
    if len(payload) < 12:
        return None
    hdr = struct.unpack_from("<6H", payload, 0)
    anim_base, step_base = hdr[0] << 2, hdr[1] << 2
    pose_base, frame_base, desc_base = (hdr[2] << 2, hdr[3] << 2, hdr[4] << 2)
    if not (0 < pose_base < frame_base < desc_base <= len(payload)):
        return None
    if not (0 < anim_base < step_base <= pose_base):
        anim_base = step_base = 0
    return SpriteBlockData(payload=payload,
                           frame_base=frame_base,
                           desc_base=desc_base,
                           pose_tables=[pose_base],
                           anim_base=anim_base,
                           step_base=step_base)


def parse_actor_block(payload: bytes) -> SpriteBlockData | None:
    """An inflated sprite data block (field or battle)."""
    return _from_payload(payload)


def list_poses(data: SpriteBlockData, max_per_table: int = 0) -> list[Pose]:
    """Enumerate the drawable poses in a block."""
    out: list[Pose] = []
    limit = max_per_table or data.pose_count
    for base in data.pose_tables:
        for k in range(limit):
            off = base + k * POSE_STRIDE
            if off + POSE_STRIDE > len(data.payload):
                break
            count, first = struct.unpack_from("<2H", data.payload, off)
            if not (1 <= count <= MAX_POSE_SLICES and
                    first + count <= data.frame_count):
                continue
            out.append(Pose(table=base, index=k, first=first, count=count))
    return out


def pose_tpages(data: SpriteBlockData, pose: Pose) -> set[int]:
    """The texture-page indices a pose's slices reference."""
    pages = set()
    for i in range(pose.first, pose.first + pose.count):
        f = data.frame(i)
        if not f:
            continue
        d = data.descriptor(f[3])
        if d:
            pages.add(d[0])
    return pages


def texel_rects(data: SpriteBlockData) -> set[tuple[int, int, int, int, int]]:
    """(page slot, u, v, w, h) of every texel rectangle the block's drawable
    poses read: a textured slice's descriptor (u, v) and its own w x h, the
    texels `compose_pose` takes for it. A page slot holds the texels of every
    sprite loaded with it, and only these are this block's."""
    out = set()
    for pose in list_poses(data):
        for i in range(pose.first, pose.first + pose.count):
            s = data.slice(i)
            if s is None or s.w <= 0 or s.h <= 0 or s.corners() is None:
                continue
            d = data.descriptor(s.desc)
            if d is not None:
                out.add((d[0], d[1], d[2], s.w, s.h))
    return out


def texel_mask(rects, slot: int, size: tuple[int, int]):
    """-> an "L" image of one page slot, 255 on the texels `rects` (as
    `texel_rects` gives them) read from it, 0 elsewhere."""
    from PIL import Image, ImageDraw

    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for s, u, v, w, h in rects:
        if s == slot and w > 0 and h > 0:
            draw.rectangle((u, v, u + w - 1, v + h - 1), fill=255)
    return mask


def _page_for(page, slot: int):
    """`page` is one rendered page, or a mapping {descriptor page slot: page}."""
    if hasattr(page, "crop"):
        return page
    return page.get(slot) if hasattr(page, "get") else None


def _affine(dst: tuple, src: tuple) -> tuple[float, ...]:
    """Coefficients mapping destination (x, y) -> source (u, v) for a triangle."""
    (x0, y0), (x1, y1), (x2, y2) = dst
    (u0, v0), (u1, v1), (u2, v2) = src
    det = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if det == 0:
        return ()
    a = ((u1 - u0) * (y2 - y0) - (u2 - u0) * (y1 - y0)) / det
    b = ((u2 - u0) * (x1 - x0) - (u1 - u0) * (x2 - x0)) / det
    d = ((v1 - v0) * (y2 - y0) - (v2 - v0) * (y1 - y0)) / det
    e = ((v2 - v0) * (x1 - x0) - (v1 - v0) * (x2 - x0)) / det
    return (a, b, u0 - a * x0 - b * y0, d, e, v0 - d * x0 - e * y0)


def _draw_quad(img, src, quad, uv) -> None:
    """Texture-map `uv` (TL, TR, BR, BL texel corners) onto `quad`.

    The GPU splits a POLY_FT4 into the triangles (v0 v1 v2) and (v1 v2 v3) —
    in primitive order v0=TL v1=TR v2=BL v3=BR — and maps each affinely, so
    a non-parallelogram quad shows the same diagonal seam the hardware does.
    """
    from PIL import Image, ImageChops, ImageDraw

    tl, tr, br, bl = quad
    ttl, ttr, tbr, tbl = uv
    for dst, tex in (((tl, tr, bl), (ttl, ttr, tbl)), ((tr, bl, br), (ttr, tbl, tbr))):
        coeffs = _affine(dst, tex)
        if not coeffs:
            continue
        warped = src.transform(img.size, Image.AFFINE, coeffs, resample=Image.NEAREST)
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).polygon([tuple(p) for p in dst], fill=255)
        warped.putalpha(ImageChops.multiply(warped.getchannel("A"), mask))
        img.alpha_composite(warped)


#: How far from the anchor a slice's corner may lie and still count: the
#: GPU takes a vertex as a signed 11-bit number (-1024..1023), so a corner
#: past it is no picture the game draws, and an extent stretched to it would
#: ask for a canvas of gigabytes.
REACH = 1024


def pose_extent(data: SpriteBlockData, pose: Pose,
                tpages: set[int] | None = None) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) a pose covers relative to the actor anchor, or None.

    It counts the slices `compose_pose` can draw: a texture descriptor, and,
    given `tpages`, one naming one of those page slots; every corner within
    REACH."""
    xs: list[int] = []
    ys: list[int] = []
    for i in range(pose.first, pose.first + pose.count):
        s = data.slice(i)
        if s is None or not (s.w and s.h):
            continue
        d = data.descriptor(s.desc)
        if d is None or (tpages is not None and d[0] not in tpages):
            continue
        c = s.corners()
        if c and all(abs(x) <= REACH and abs(y) <= REACH for x, y in c):
            xs += [p[0] for p in c]
            ys += [p[1] for p in c]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def compose_pose(data: SpriteBlockData, page, pose: Pose,
                 cell: int = 64, tpages: set[int] | None = None,
                 origin: tuple[int, int] | None = None,
                 size: tuple[int, int] | None = None):
    """Assemble one pose into an RGBA image, as sprite_draw (0x8001A528) draws it.

    `page` is one rendered texture page, or a mapping {descriptor page slot:
    page} when a pose spans several (battle sets put enemies on slots 1-3).
    `tpages`, when given, keeps only slices whose descriptor names one of
    those slots. The actor anchor lands at `origin` (default: the centre of a
    `cell` x `cell` image; `size` overrides the canvas).

    Slice `first` is drawn first (bottom) and the pose's last slice ends on
    top: the renderer calls the slices last-to-first, and AddPrim links each
    at the head of the same ordering-table cell, so the call order reverses.
    Kind 0 slices are the descriptor's (u, v, w, h) texels, mirrored when the
    record's flip bits say so; rectangles and quads are texture-mapped onto
    their corners (sprite_quad_draw, 0x800174F0). The actor-level flip (actor +0x0C bits
    13/14) is not applied — draw the result mirrored about the anchor for a
    flipped actor. Untextured kinds (0x4000, 0x5000) are skipped.
    """
    from PIL import Image, ImageOps

    w_img, h_img = size or (cell, cell)
    img = Image.new("RGBA", (w_img, h_img), (0, 0, 0, 0))
    cx, cy = origin or (cell // 2, cell // 2)
    for i in range(pose.first, pose.first + pose.count):
        s = data.slice(i)
        if s is None or not (s.w and s.h):
            continue
        d = data.descriptor(s.desc)
        if d is None:
            continue
        slot, u, v = d
        if tpages is not None and slot not in tpages:
            continue
        src = _page_for(page, slot)
        if src is None or u + s.w > src.width or v + s.h > src.height:
            continue
        corners = s.corners()
        if corners is None:
            continue
        if s.kind == SLICE_SPRITE:
            crop = src.crop((u, v, u + s.w, v + s.h))
            if s.flip_x:
                crop = ImageOps.mirror(crop)
            if s.flip_y:
                crop = ImageOps.flip(crop)
            img.paste(crop, (cx + s.xo, cy + s.yo), crop)
            continue
        uL, uR = (u + s.w, u) if s.flip_x else (u, u + s.w)
        vT, vB = (v + s.h, v) if s.flip_y else (v, v + s.h)
        quad = tuple((cx + x, cy + y) for x, y in corners)
        _draw_quad(img, src, quad, ((uL, vT), (uR, vT), (uR, vB), (uL, vB)))
    return img


@dataclass
class PoseSheet:
    """Every pose of a block on one uniform grid, anchored alike.

    Cell k (row-major, `columns` wide) is pose k of the block's pose table —
    the index an anim step names — so a player needs only the anim table and
    this sheet. The actor ANCHOR sits at (anchor_x, anchor_y) in every cell.
    `cells[k]` is {"slices", "extent"} or None for a table entry that names
    no drawable slice run."""
    image: object               # PIL RGBA
    cell_w: int
    cell_h: int
    anchor_x: int
    anchor_y: int
    columns: int
    cells: list


def pose_sheet(data: SpriteBlockData, page, columns: int = 16,
               tpages: set[int] | None = None) -> PoseSheet | None:
    """Compose every pose of a block into a `PoseSheet`, or None if none draw.

    The cell is the union of every pose's extent, so all cells share one
    anchor; poses are composed by `compose_pose` (the renderer's rules), for
    an unmirrored actor — mirror a cell about the anchor column for actor
    +0x0C bit 13 (engine column c -> 2X-1-c). `page` and `tpages` are as for
    `compose_pose`."""
    from PIL import Image

    n = data.pose_count
    poses = {p.index: p for p in list_poses(data)}
    ext = [e for e in (pose_extent(data, p, tpages) for p in poses.values()) if e]
    if not ext:
        return None
    x0, y0 = min(e[0] for e in ext), min(e[1] for e in ext)
    x1, y1 = max(e[2] for e in ext), max(e[3] for e in ext)
    cw, ch = x1 - x0, y1 - y0
    ax, ay = -x0, -y0
    rows = max(1, (n + columns - 1) // columns)
    sheet = Image.new("RGBA", (columns * cw, rows * ch), (0, 0, 0, 0))
    cells: list = []
    for k in range(n):
        p = poses.get(k)
        if p is None:
            cells.append(None)
            continue
        im = compose_pose(data, page, p, tpages=tpages, origin=(ax, ay), size=(cw, ch))
        sheet.paste(im, ((k % columns) * cw, (k // columns) * ch))
        e = pose_extent(data, p, tpages)
        cells.append({"slices": p.count, "extent": list(e) if e else None})
    return PoseSheet(image=sheet, cell_w=cw, cell_h=ch, anchor_x=ax,
                     anchor_y=ay, columns=columns, cells=cells)

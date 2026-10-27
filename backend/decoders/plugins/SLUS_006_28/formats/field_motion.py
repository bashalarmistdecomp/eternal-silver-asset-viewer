"""The field's tick for a map's objects and the party standing on its
spot: the think pass and the thinks it calls, the animation tick, and the
tile animation.

ONE FIELD FRAME -- MapFrameUpdate (0x80055840) runs MapPartyStep
(0x80056248), which ends in MapPartyAnimationStep (0x80065CF8), then
MapObjectsStep (0x800563D4): the think pass MapObjectsThink (0x8006736C)
and MapObjectsAnimationStep (0x80065FD8); its tail runs
tile_animation_step (0x80026690). `Field.tick` is that frame with no pad
held: the party stands on its spot and its animation ticks (nothing in
the walk path stops it, field-frame.md §"The animation").

THE THINK PASS -- a row thinks on passes of its own parity
(g_MapObjectsThinkPhase (0x800B87EC) steps 0..3), a row of kind below 4
only when the phase is its row & 3; a row of number 3 or 4, outside the
view limits, of kind 0 or 7 never thinks. A thinking row counts
interval_left down and at 0 calls vtbl_4658_table (0x800B4658)[number &
0x3F]; a non-zero answer re-classes it (MapAttributeClassGet (0x8006960C))
and turns its animation to its facing.

    0      MapObjectWanderStep (0x8006758C)
    1, 2   StepCommandRun (0x80067768): the step list's ops F0..F9
           (g_StepCommandFunctions (0x800B4620))
    5      MapObjectTurnStep (0x800678F4)
    6      MapObjectPartyLookStep (0x80077F1C): a look of
           g_MapObjectPartyLookFunctions (0x800B5B3C), then the sight check

THE RANDOM DRAWS -- rng_draw (0x8001C770) of the generator rng.c builds
(`Rng`); system_init (0x8001EEB8) seeds it with 0x3039.

What is not the game's: the party never moves, never sees an enemy and
is never touched (MapObjectPartySeenCheck (0x8007A58C) answers "not seen",
MapObjectTouchFind (0x8007AB64) is not run), so an enemy only looks;
every row thinks and draws as if the camera were on it (the pass passes
over rows away from the view); and each row takes as the view limits
(g_MapLimitLeft..Bottom, which MapChange and MapPartyPlace (0x80059730)
set) the first of the given rectangles it stands in, the whole plane
when none holds it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from decoders.plugins.SLUS_006_28.formats import field_objects as fo
from decoders.plugins.SLUS_006_28.records.programs import address

RNG_BOOT_SEED = 0x3039          # system_init (0x8001EEB8): rng_seed(0x3039)
RNG_MOD = 1_000_000_000
RNG_WORDS = 56                  # g_RngNumbers (0x800E0910): words 1..55 used

THINK_PHASES = 4
TURN_AFTER = 0x10               # MapObjectWanderStep / MapObjectTurnStep: blocked / think count
STEP_OPS = 10                   # StepCommandRun: (op + 0x10) & 0xFF below 10
STEP_LIST_START = 2             # MapObjectMoveSet: the cursor starts past bytes 0 and 1
TURN_EVERY = 5                  # MapObjectFacingTurnStep: a facing every 5 / interval thinks
FIELD_TILE_AT = 0x100           # tile_image_load: 0x100 bytes a tile
TILE_SIDE = 16

# MapObject.state values the looks use
READY = 0xFF                    # walking (or waiting, look 2)
TURN_THEN_WALK = 0xFE           # MapObjectRandomWalkStart: a planned turn, then the walk
STOPPED = 0x90                  # look 6: stopping; look 11: about to jump
JUMPED = 0xA0                   # look 11


def s16(v: int) -> int:
    return ((v + 0x8000) & 0xFFFF) - 0x8000


def u8(v: int) -> int:
    return v & 0xFF


def value_div(value: int, divisor: int) -> int:
    """value_div (0x80077EE8): C's division, toward zero."""
    if divisor == 0:
        return 0
    q = abs(value) // abs(divisor)
    return q if (value >= 0) == (divisor >= 0) else -q


def c_mod(a: int, b: int) -> int:
    """C's signed remainder."""
    r = abs(a) % abs(b)
    return r if a >= 0 else -r


# ---------------------------------------------------------------------------
# the generator (rng.c)
# ---------------------------------------------------------------------------
class Rng:
    """rng_seed (0x8001C5F8), rng_refill (0x8001C548), rng_next (0x8001C6B0)."""

    def __init__(self, seed: int = RNG_BOOT_SEED):
        self.words = [0] * RNG_WORDS
        self.words[55] = seed
        k = 1
        for i in range(1, 55):
            ii = (i * 21) % 55
            self.words[ii] = k
            k = seed - k
            if k < 0:
                k += RNG_MOD
            seed = self.words[ii]
        for _ in range(3):
            self.refill()
        self.cursor = 55
        self.draws = 0

    def refill(self) -> None:
        w = self.words
        for i in range(1, 25):
            j = w[i] - w[i + 31]
            w[i] = j + RNG_MOD if j < 0 else j
        for i in range(25, 56):
            j = w[i] - w[i - 24]
            w[i] = j + RNG_MOD if j < 0 else j

    def draw(self) -> int:
        """rng_draw (0x8001C770) = rng_next."""
        self.cursor += 1
        if self.cursor >= 0x38:
            self.refill()
            self.cursor = 1
        self.draws += 1
        return self.words[self.cursor]


# ---------------------------------------------------------------------------
# the plane's arithmetic
# ---------------------------------------------------------------------------
def spot_move(tables: fo.FieldTables, facing: int, dist: int, x: int, y: int) -> tuple[int, int]:
    """MapSpotMove (0x80066848): dist steps along facing ((facing - 1) & 7
    indexes the tables), the spot kept as 16 bits."""
    i = (facing - 1) & 7
    d = dist & 0xFFFF
    return s16(x + d * tables.dxs[i]), s16(y + d * tables.dys[i])


def facing_toward(x0: int, y0: int, x1: int, y1: int, facing: int) -> int:
    """MapFacingTowardGet (0x8005FBBC)."""
    facing &= 0xFFFF
    if x0 == x1 and y0 == y1:
        return 0
    if facing == 0:
        return 0
    if x0 == x1:
        return 5 if y0 < y1 else 1
    if y0 == y1:
        return 3 if x0 < x1 else 7
    adx, ady = abs(x0 - x1), abs(y0 - y1)
    if adx == ady:
        if x0 < x1:
            return 4 if y0 < y1 else 2
        return 6 if y0 < y1 else 8
    if ady < adx:
        if x0 < x1:
            if y0 < y1:
                return 4 if 4 <= facing < 8 else 3
            return 3 if 3 <= facing < 7 else 2
        if y0 < y1:
            return 6 if 3 <= facing < 7 else 7
        return 7 if 4 <= facing < 8 else 8
    if y0 < y1:
        if x0 < x1:
            return 4 if facing < 5 else 5
        return 5 if 2 <= facing < 6 else 6
    if x0 < x1:
        return 2 if 2 <= facing < 6 else 1
    return 1 if facing < 5 else 8


def box_touch(bx: int, by: int, half_w: int, half_h: int,
              px: int, py: int, probe_w: int, probe_h: int) -> int:
    """MapBoxTouchGet (0x80067BFC): 9 when the box centred (bx, by) and the
    probe overlap strictly, 0 when apart or either width is 0, else the
    probe's side the box touches (1..8)."""
    if probe_w == 0 or half_w == 0:
        return 0
    adx, ady = abs(bx - px), abs(by - py)
    w, h = half_w + probe_w, half_h + probe_h
    if w < adx or h < ady:
        return 0
    if adx < w and ady < h:
        return 9
    if adx == w:
        if ady == h:
            if px < bx:
                return 4 if py < by else 2
            return 6 if py < by else 8
        return 3 if px < bx else 7
    return 5 if py < by else 1


def side_align_count(d: int, x: int, y: int, w: int, h: int, flag: int) -> int:
    """MapSpotSideAlignCount (0x80066E64)."""
    h &= 0xFFFF
    d &= 0xFFFF
    if flag:
        r = {1: 4 - ((x - w) & 3), 8: 4 - ((x - w) & 3), 2: 4 - ((y - h) & 3),
             3: 4 - ((y - h) & 3), 4: x + w, 5: x + w, 6: y + h, 7: y + h}.get(d, 0)
    else:
        r = {1: x + w, 2: x + w, 3: y + h, 4: y + h, 5: 4 - ((x - w) & 3),
             6: 4 - ((x - w) & 3), 7: 4 - ((y - h) & 3), 8: 4 - ((y - h) & 3)}.get(d, 0)
    return r & 3


# ---------------------------------------------------------------------------
# the field
# ---------------------------------------------------------------------------
@dataclass
class Row:
    """A g_MapObjects row in the field's tick: field_objects.MapObject and
    the bytes the thinks keep (map.h)."""
    obj: fo.MapObject
    table: fo.AnimTable
    twin_table: fo.AnimTable | None
    thinks_left: int = 0        # +0x49
    target: tuple[int, int] = (0, 0)    # +0x4C, +0x4E
    stuck: str = ""             # why it no longer thinks, when it does not
    limits: tuple[int, int, int, int] = (0, fo.PLANE_LIMIT, 0, fo.PLANE_LIMIT)


@dataclass
class TileAnimation:
    """One record of g_TileAnimations (0x800E4778) (tile.h TileAnimation)."""
    delay: int
    frames: int
    count: int
    tile: int
    source: int
    timer: int = 0
    frame: int = 0
    steps: int = 0              # steps taken: 0 while the page shows its own texels

    def step(self) -> None:
        """tile_animation_step (0x80026690) for one record."""
        self.timer = u8(self.timer + 1)
        if self.timer < self.delay:
            return
        self.timer = 0
        self.frame = u8(self.frame + 1)
        if self.frame >= self.frames:
            self.frame = 0
        self.steps += 1


TILE_ANIMATION_SETS_ADDR = 0x800B016C   # g_TileAnimationSets: {first row, count} a set
TILE_ANIMATION_ROWS_ADDR = 0x800B01B4   # g_TileAnimationRows: 8-byte seed rows
TILE_ANIMATION_RECORDS = 4


def tile_animations(image: bytes, set_id: int) -> list[TileAnimation]:
    """tile_animation_set (0x800265BC): the records set `set_id` starts
    (0: none), read where the image's program keeps the tables
    (records.programs). A seed row is mode, delay, frames, count, u16 tile,
    u16 source; every seed in the program has mode 1, the one
    tile_animation_step loads tiles for."""
    if set_id == 0:
        return []
    sets = address(image, "g_TileAnimationSets", TILE_ANIMATION_SETS_ADDR)
    rows = address(image, "g_TileAnimationRows", TILE_ANIMATION_ROWS_ADDR)
    at = sets - fo.EXE_BASE + (set_id - 1) * 2
    first, n = image[at], image[at + 1]
    out = []
    for k in range(min(n, TILE_ANIMATION_RECORDS)):
        row = rows - fo.EXE_BASE + (first + k) * 8
        mode, delay, frames, count = image[row:row + 4]
        tile = int.from_bytes(image[row + 4:row + 6], "little")
        source = int.from_bytes(image[row + 6:row + 8], "little")
        if mode:
            out.append(TileAnimation(delay=delay, frames=frames, count=count,
                                     tile=tile, source=source))
    return out


def tile_place(tile: int) -> tuple[int, int, int]:
    """tile_image_load (0x80026754)'s rectangle as (page, u, v) of the
    map's 8-bit pages: page = bits 8..9, 16-px column bits 0..3, row bits 4..7."""
    return (tile >> 8) & 3, (tile & 0xF) * TILE_SIDE, tile & 0xF0


@dataclass
class Lead:
    """Party record 0 and its twin, standing."""
    x: int
    depth: int
    box: fo.Box
    anim: fo.AnimState
    table: fo.AnimTable
    twin_anim: fo.AnimState | None
    twin_table: fo.AnimTable | None


class Field:
    """A map's objects, the party lead and the tile animations, stepped one
    field frame at a time (module docstring)."""

    def __init__(self, rows: list[Row], lead: Lead | None, att: fo.Attributes,
                 tables: fo.FieldTables, block: bytes,
                 limits: list[tuple[int, int, int, int]] = (),
                 tiles: list[TileAnimation] = (), rng: Rng | None = None):
        self.rows = rows
        self.lead = lead
        self.att = att
        self.tables = tables
        self.block = block
        self.step_lists = block[fo.STEP_LISTS_AT:]
        for r in rows:
            o = r.obj
            r.limits = next((rc for rc in limits
                             if rc[0] <= o.x <= rc[1] and rc[2] <= o.depth <= rc[3]), r.limits)
        self.tiles = list(tiles)
        self.rng = rng or Rng()
        self.phase = 0
        self.ticks = 0

    # -- one frame --------------------------------------------------------

    def tick(self) -> None:
        self._party_animation()
        self._think_pass()
        self._objects_animation()
        for t in self.tiles:
            t.step()
        self.ticks += 1

    def _party_animation(self) -> None:
        """MapPartyAnimationStep (0x80065CF8) for record 0."""
        ld = self.lead
        if ld is None:
            return
        fo.anim_tick(ld.anim, ld.table)
        if ld.twin_anim is not None:
            fo.twin_sync(ld.twin_anim, ld.twin_table, ld.anim)

    def _objects_animation(self) -> None:
        """MapObjectsAnimationStep (0x80065FD8), every row drawn."""
        for r in self.rows:
            o = r.obj
            if o.kind == 0 or o.kind & 0x80:
                continue
            number = o.think & 0x3F
            if number != 3 and (number != 6 or (o.look & 0x7F) != 1 or o.length != 0):
                fo.anim_tick(o.anim, r.table)
            if o.twin_anim is not None:
                fo.twin_sync(o.twin_anim, r.twin_table, o.anim)

    def _think_pass(self) -> None:
        """MapObjectsThink (0x8006736C)."""
        for i, r in enumerate(self.rows):
            o = r.obj
            live = o.kind
            if live == 0 or live == fo.CHEST_KIND:
                continue
            number = o.think & 0x3F
            if number in (3, 4) or live & 0x80 or r.stuck:
                continue
            if (i & 1) != (self.phase & 1):
                continue
            if live < 4 and (i & 3) != self.phase:
                continue
            left, right, top, bottom = r.limits
            if o.x < left or right < o.x or o.depth < top or bottom < o.depth:
                continue
            o.interval_left = u8(o.interval_left - 1)
            if o.interval_left != 0:
                continue
            o.interval_left = o.interval
            think = THINKS.get(number)
            if think is None:
                r.stuck = f"think number {number} is not transcribed here"
                continue
            if think(self, r, i):
                o.klass = fo.class_get(self.att, 1, fo.OBJECT_TOP, o.x, o.y, o.depth, o.box,
                                       o.layer)
                self.pose_set(r, -1, o.facing)
        self.phase = self.phase + 1 if self.phase < THINK_PHASES - 1 else 0

    # -- helpers ----------------------------------------------------------

    def pose_set(self, r: Row, pose: int, facing: int) -> None:
        fo.pose_set(r.obj.anim, r.table, pose, facing & 0xFFFF)

    def free(self, o: fo.MapObject, x: int, y: int) -> bool:
        """MapAttributeFreeCheck at the row's box round (x, y)."""
        b = o.box
        return bool(fo.free_check(self.att, x + b.dx, y + b.dy, b.half_width, b.half_height,
                                  o.layer, 0))

    def in_bounds(self, o: fo.MapObject, x: int, y: int) -> bool:
        left, right, top, bottom = o.bounds
        return left <= x < right and top <= y < bottom

    def overlap_find(self, x: int, y: int, me: int) -> int:
        """MapObjectOverlapFind (0x80067AC4): 1 the lead, i + 2 row i, 0 nobody."""
        o = self.rows[me].obj
        px, py = s16(x) + o.box.dx, s16(y) + o.box.dy
        pw, ph = o.box.half_width, o.box.half_height
        ld = self.lead
        if box_touch(ld.x + ld.box.dx, ld.depth + ld.box.dy, ld.box.half_width,
                     ld.box.half_height, px, py, pw, ph) == 9:
            return 1
        dx, dy = ld.box.dx, ld.box.dy
        for i, r in enumerate(self.rows):
            q = r.obj
            if q.kind == 0 or i == me:
                continue
            if box_touch(q.x + dx, q.depth + dy, q.box.half_width, q.box.half_height,
                         px, py, pw, ph) == 9:
                return (i + 2) & 0xFFFF
        return 0

    def place(self, o: fo.MapObject, x: int, y: int) -> None:
        o.x = s16(x)
        o.y = o.depth = s16(y)

    def range_draw(self, fixed: int, low: int, high: int) -> int:
        """rng_range_draw (0x800780DC)."""
        if u8(fixed) == 0:
            fixed = low + c_mod(self.rng.draw(), high - low + 1)
        return u8(fixed)

    # -- MapSpotMoveTry and its side step (map_walk.c) ---------------------

    def spot_move_try(self, d: int, dist: int, x: int, y: int, o: fo.MapObject
                      ) -> tuple[int, int, int]:
        """MapSpotMoveTry (0x8006661C) -> (the facing moved along or 0, x, y)."""
        d &= 0xFFFF
        if d == 0:
            return 0, x, y
        t = self.tables
        x0, y0 = spot_move(t, d, dist, x, y)
        x1, y1 = spot_move(t, (d + 1) & 0xFFFF, dist, x, y)
        x2, y2 = spot_move(t, (d - 1) & 0xFFFF, dist, x, y)
        if self.free(o, x0, y0):
            return d, x0, y0
        if self.free(o, x1, y1):
            return (d & 7) + 1, x1, y1
        if self.free(o, x2, y2):
            return ((d - 2) & 7) + 1, x2, y2
        return self._side_move_try(d, dist, x, y, o)

    def _side_move_try(self, d: int, mode: int, x: int, y: int, o: fo.MapObject
                       ) -> tuple[int, int, int]:
        """MapSpotSideMoveTry (0x800668A8)."""
        t = self.tables
        b = o.box
        w, h, layer = b.half_width, b.half_height, o.layer
        att = self.att
        step_a = step_b = 1
        cnt_a = cnt_b = 0
        ax = bx = s16(x + b.dx)
        ay = by = s16(y + b.dy)
        if mode < 4:
            cd_a = side_align_count(d, ax, ay, w, h, 1)
            if cd_a == 0:
                step_a = 4
        else:
            cd_a = 0
            step_a = mode
        if mode < 4:
            cd_b = side_align_count(d, bx, by, w, h, 0)
            if cd_b == 0:
                step_b = 4
        else:
            cd_a = 0            # the C's own: cdA again, and cdB left unset
            cd_b = 0            # (taken as 0 here)
            step_b = mode

        def free(px, py):
            return fo.free_check(att, px, py, w, h, layer, 0)

        while cnt_a < 0x41 or cnt_b < 0x41:
            if cnt_b >= cnt_a:
                if cnt_a < 0x41:
                    cnt_a += step_a
                    ax, ay = spot_move(t, (d + 2) & 0xFFFF, step_a, ax, ay)
                    if ax - w < 0 or ax + w >= 0x800 or ay - h < 0 or ay + h >= 0x800:
                        cnt_a = 0x41
                    if cd_a != 0:
                        cd_a -= 1
                        if cd_a == 0:
                            step_a = 4
                if free(ax, ay):
                    tx, ty = spot_move(t, d, mode, ax, ay)
                    if free(tx, ty):
                        d = ((d + 1) & 7) + 1
                        break
                    tx, ty = spot_move(t, (d + 1) & 0xFFFF, mode, ax, ay)
                    if free(tx, ty):
                        d = ((d + 1) & 7) + 1
                        break
                elif step_a >= 4:
                    if mode < 4:
                        cnt_a -= step_a
                        ax, ay = spot_move(t, (d - 2) & 0xFFFF, step_a, ax, ay)
                        step_a = 1
                    else:
                        cnt_a = 0x41
                else:
                    cnt_a = 0x41
            if cnt_b < cnt_a:
                if cnt_b < 0x41:
                    cnt_b += step_b
                    bx, by = spot_move(t, (d - 2) & 0xFFFF, step_b, bx, by)
                    if bx - w < 0 or bx + w >= 0x800 or by - h < 0 or by + h >= 0x800:
                        cnt_b = 0x41
                    if cd_b != 0:
                        cd_b -= 1
                        if cd_b == 0:
                            step_b = 4
                if free(bx, by):
                    tx, ty = spot_move(t, d, mode, bx, by)
                    if free(tx, ty):
                        d = ((d - 3) & 7) + 1
                        break
                    tx, ty = spot_move(t, (d - 1) & 0xFFFF, mode, bx, by)
                    if free(tx, ty):
                        d = ((d - 3) & 7) + 1
                        break
                elif step_b >= 4:
                    if mode < 4:
                        cnt_b -= step_b
                        bx, by = spot_move(t, (d + 2) & 0xFFFF, step_b, bx, by)
                        step_b = 1
                    else:
                        cnt_b = 0x41
                else:
                    cnt_b = 0x41
        if cnt_a < 0x41 or cnt_b < 0x41:
            x, y = spot_move(t, d, mode, x, y)
            return d, x, y
        return 0, x, y


# ---------------------------------------------------------------------------
# the thinks (map_think.c, step_command.c)
# ---------------------------------------------------------------------------
def wander_step(f: Field, r: Row, i: int) -> int:
    """MapObjectWanderStep (0x8006758C)."""
    o = r.obj
    if o.facing == 0:
        return 1
    x, y = o.x, o.y
    n = 0
    while n < o.speed:
        sx, sy = spot_move(f.tables, o.facing, 1, x, y)
        if not f.in_bounds(o, sx, sy):
            o.turn_count = TURN_AFTER
            break
        if not f.free(o, sx, sy):
            o.turn_count = TURN_AFTER
            break
        if f.overlap_find(sx, sy, i):
            o.turn_count = u8(o.turn_count + 1)
            break
        x, y = sx, sy
        n += 1
    if n < o.speed:
        if o.turn_count >= TURN_AFTER:
            o.turn_count = 0
            o.facing = c_mod(f.rng.draw(), 8) + 1
        if n == 0:
            return 0
    else:
        o.turn_count = 0
    f.place(o, x, y)
    return 1


def turn_step(f: Field, r: Row, i: int) -> int:
    """MapObjectTurnStep (0x800678F4)."""
    o = r.obj
    o.turn_count = u8(o.turn_count + 1)
    if o.turn_count < TURN_AFTER:
        return 0
    if o.kind % 0x7F == 3 and o.anim.step + 1 < o.anim.end:
        return 0
    d = c_mod(f.rng.draw(), 8) + 1
    o.turn_count = 0
    if (o.kind & 0x7F) != 3:
        o.facing = d
        f.pose_set(r, 1, o.facing)
    else:
        fo.anim_set(o.anim, r.table, d)
    return 0


def _list_byte(f: Field, o: fo.MapObject, k: int) -> int:
    at = o.step_list + o.cursor + k
    return f.step_lists[at] if 0 <= at < len(f.step_lists) else 0


def step_command_run(f: Field, r: Row, i: int) -> int:
    """StepCommandRun (0x80067768)."""
    o = r.obj
    index = (_list_byte(f, o, 0) + 0x10) & 0xFF
    if index >= STEP_OPS:
        return 0
    return STEP_OPS_RUN[index](f, r, i)


def _op_pose(f, r, i):        # F0 StepCommandPoseSet (0x80063714)
    o = r.obj
    f.pose_set(r, _list_byte(f, o, 1), o.facing)
    o.cursor = s16(o.cursor + 2)
    return 0


def _op_facing(f, r, i):      # F1 StepCommandFacingSet (0x80063764)
    o = r.obj
    o.facing = _list_byte(f, o, 1)
    f.pose_set(r, -1, o.facing)
    o.cursor = s16(o.cursor + 2)
    return 0


def _op_hang(f, r, i):        # F2 StepCommandHang (0x8006370C): an endless loop
    r.stuck = "step op F2: the game hangs in StepCommandHang (0x8006370C)"
    return 0


def _op_move_to(f, r, i):     # F3 StepCommandMoveTo (0x800637BC)
    o = r.obj
    if o.busy == 0:
        o.goal = (_list_byte(f, o, 1) << 3, _list_byte(f, o, 2) << 3)
        o.busy = 1
        o.facing_kept = _list_byte(f, o, 4)
    return _walk_step(f, r, i)


def _op_move_by(f, r, i):     # F4 StepCommandMoveBy (0x8006382C)
    o = r.obj
    if o.busy == 0:
        b1, b2 = _list_byte(f, o, 1), _list_byte(f, o, 2)
        cx = s16(value_div(o.x, 8) + (b1 - 0x100 if b1 & 0x80 else b1))
        cy = s16(value_div(o.depth, 8) + (b2 - 0x100 if b2 & 0x80 else b2))
        if not (0 <= cx < 0x100 and 0 <= cy < 0x100):
            r.stuck = "step op F4 off the plane: the game hangs in StepCommandHang (0x8006370C)"
            return 0
        o.facing_kept = _list_byte(f, o, 4)
        o.goal = (s16(cx * 8), s16(cy * 8))
        o.busy = 1
    return _walk_step(f, r, i)


def _op_speed(f, r, i):       # F5 StepCommandSpeedSet (0x80063938)
    o = r.obj
    k = _list_byte(f, o, 1)
    t = f.tables
    o.speed = t.speed_pixels[k] if k < len(t.speed_pixels) else 0
    o.interval = t.speed_intervals[k] if k < len(t.speed_intervals) else 0
    o.cursor = s16(o.cursor + 2)
    return 0


def _op_wait(f, r, i):        # F6 StepCommandWait (0x80063990)
    o = r.obj
    if o.busy == 0:
        o.wait_left = _list_byte(f, o, 1)
        o.busy = 1
    o.wait_left = s16(o.wait_left - 1)
    if o.wait_left & 0xFFFF == 0:
        o.busy = 0
        o.cursor = s16(o.cursor + 2)
    return 0


def _op_place(f, r, i):       # F7 StepCommandPlace (0x800639F4)
    o = r.obj
    f.place(o, _list_byte(f, o, 1) << 3, _list_byte(f, o, 2) << 3)
    o.cursor = s16(o.cursor + 3)
    _op_facing(f, r, i)
    return 1


def _op_skip(f, r, i):        # F8 StepCommandScaleSkip (0x80063A4C)
    o = r.obj
    o.cursor = s16(o.cursor + 4)
    return 0


def _op_restart(f, r, i):     # F9 StepCommandRestart (0x80063A64)
    o = r.obj
    o.cursor = STEP_LIST_START
    if _list_byte(f, o, 0) == 0xF9:
        r.stuck = "step list of F9 alone: StepCommandRestart (0x80063A64) runs for ever"
        return 0
    return step_command_run(f, r, i)


def _walk_step(f: Field, r: Row, i: int) -> int:
    """StepWalkStep (0x800677D4)."""
    o = r.obj
    sx, sy = o.x, o.depth
    o.facing = facing_toward(sx, sy, o.goal[0], o.goal[1], o.facing)
    sx, sy = spot_move(f.tables, o.facing, o.speed, sx, sy)
    hit = f.overlap_find(sx, sy, i)
    if hit == 0:
        f.place(o, sx, sy)
    if o.x == o.goal[0] and o.depth == o.goal[1]:
        o.busy = 0
        o.cursor = s16(o.cursor + 5)
        if o.facing_kept != 0:
            o.facing = o.facing_kept
    f.pose_set(r, -1, o.facing_kept if o.facing_kept != 0 else o.facing)
    return hit


STEP_OPS_RUN = (_op_pose, _op_facing, _op_hang, _op_move_to, _op_move_by, _op_speed,
                _op_wait, _op_place, _op_skip, _op_restart)


# ---------------------------------------------------------------------------
# number 6: the looks (map_look.c)
# ---------------------------------------------------------------------------
def _turn_set(o: fo.MapObject, facing: int) -> None:
    """MapObjectFacingTurnSet (0x80078D00)."""
    target = facing & 0xFFFF
    count = 1
    fwd = bwd = o.facing
    o.turn_plan = 0
    while True:
        fwd = (fwd & 7) + 1
        if fwd == target:
            o.turn_plan = 0x80
            break
        bwd = ((bwd - 2) & 7) + 1
        if bwd == target:
            break
        count += 1
        if count > 8:               # a facing outside 1..8: the ring never meets it
            o.turn_plan = 0
            return
    o.turn_plan = u8(count + o.turn_plan + 1)


def _turn_step(f: Field, r: Row, i: int) -> int:
    """MapObjectFacingTurnStep (0x80078D5C)."""
    o = r.obj
    r.thinks_left = u8(r.thinks_left - 1)
    if r.thinks_left:
        return 0
    o.turn_plan = u8(o.turn_plan - 1)
    if o.turn_plan & 0x7F:
        index = o.facing & 7 if o.turn_plan & 0x80 else (o.facing - 2) & 7
        o.facing = 1 + index
        r.thinks_left = u8(value_div(TURN_EVERY, o.interval))
    else:
        state = o.state
        o.turn_plan = 0
        if state == TURN_THEN_WALK:
            r.thinks_left = u8(value_div(f.range_draw(o.length, 8, 0x10) * 8, o.speed))
            o.state = READY
        elif state == 0xFD:
            o.state = READY
        else:
            r.thinks_left = u8(value_div(0x1E if state == 0xFC else 0xF, o.interval))
    f.pose_set(r, -1, o.facing)
    return 0


def _random_walk_start(f: Field, r: Row, how: int) -> None:
    """MapObjectRandomWalkStart (0x80078B88)."""
    o = r.obj
    if how == 4:
        facing = (c_mod(f.rng.draw(), 4) << 1) | 1
    elif how == 8:
        facing = c_mod(f.rng.draw(), 8) + 1
    else:
        while True:
            facing = (c_mod(f.rng.draw(), 4) << 1) | 1
            if o.facing != (((facing & 0xFFFF) + 3) & 7) + 1:
                break
    if o.facing != (facing & 0xFFFF) and o.think & 0x40:
        _turn_set(o, facing)
        r.thinks_left = 1
        o.state = TURN_THEN_WALK
        return
    o.facing = u8(facing)
    r.thinks_left = u8(value_div(f.range_draw(o.length, 8, 0x10) * 8, o.speed))
    o.state = READY
    f.pose_set(r, -1, o.facing)


def _facing_walk(f: Field, r: Row, i: int) -> tuple[int, int]:
    """MapObjectFacingWalk (0x8007868C) -> (moved, stopped_by)."""
    o = r.obj
    stopped_by = 0
    distance = o.speed
    moved_to = None
    while distance > 0:
        sx, sy = spot_move(f.tables, o.facing, distance, o.x, o.depth)
        if f.in_bounds(o, sx, sy) and f.free(o, sx, sy):
            t = f.overlap_find(sx, sy, i)
            if t == 0:
                moved_to = (sx, sy)
                break
            stopped_by = t
        distance -= 1
    if moved_to is not None:
        f.place(o, *moved_to)
    if distance != o.speed:
        o.facing_kept = 0
    else:
        o.facing_kept = o.facing
    return int(distance != 0), stopped_by


def _toward_walk(f: Field, r: Row, i: int, gx: int, gy: int) -> int:
    """MapObjectTowardWalk (0x800782B8) (its pad vibration list start is
    left out)."""
    o = r.obj
    remaining = o.speed
    while remaining > 0:
        sx, sy = o.x, o.depth
        tries = remaining
        while tries > 0:
            if o.facing == o.facing_kept or o.facing_kept == 0:
                o.facing_kept = facing_toward(sx, sy, gx, gy, o.facing)
            d, sx, sy = f.spot_move_try(u8(o.facing_kept), tries, sx, sy, o)
            d &= 0xFFFF
            if o.facing == ((d + 3) & 7) + 1:
                d = 0
            if d != 0 and f.in_bounds(o, sx, sy) and f.overlap_find(sx, sy, i) == 0:
                remaining -= tries
                f.place(o, sx, sy)
                o.facing = u8(d)
                break
            tries -= 1
        if tries == 0:
            o.facing_kept = 0
            break
    return int(remaining != o.speed)


def _open_facing_find(f: Field, r: Row, i: int, all_facings: bool) -> int:
    """MapObjectOpenFacingFind (0x800787F0)."""
    o = r.obj
    counts = [0] * 8
    blocked = 0 if all_facings else 0x55
    left, right, top, bottom = r.limits
    ring = 1
    while blocked != 0xFF:
        for k in range(8):
            if (blocked >> k) & 1:
                continue
            sx, sy = spot_move(f.tables, k + 1, ring * 8, o.x, o.depth)
            if sx < left or sx >= right or sy < top or sy >= bottom:
                blocked |= 1 << k
                continue
            if not f.in_bounds(o, sx, sy):
                blocked |= 1 << k
                break
            if not f.free(o, sx, sy) or f.overlap_find(sx, sy, i):
                blocked |= 1 << k
                continue
            counts[k] += 1
        ring += 1
    best, facing = 0, 0
    for k in (0, 2, 4, 6, 1, 3, 5, 7):
        if best < counts[k]:
            best, facing = counts[k], k + 1
    return facing


def _side_facing(f: Field, o: fo.MapObject, reverse: int) -> int:
    """MapObjectSideFacingGet (0x80078A44)."""
    if reverse == 0:
        sx, sy = spot_move(f.tables, ((o.facing - 3) & 7) + 1, 1, o.x, o.depth)
        first_free = f.free(o, sx, sy)
        sx, sy = spot_move(f.tables, ((o.facing + 1) & 7) + 1, 1, o.x, o.depth)
        if f.free(o, sx, sy):
            return ((o.facing + 1) & 7) + 1 if not first_free else ((o.facing + 3) & 7) + 1
        if first_free:
            return ((o.facing - 3) & 7) + 1
    return ((o.facing + 3) & 7) + 1


def _random_spot_place(f: Field, r: Row, i: int) -> None:
    """MapObjectRandomSpotPlace (0x8007816C)."""
    o = r.obj
    left, right, top, bottom = o.bounds
    for _ in range(10_000):
        sx = s16(left + c_mod(f.rng.draw(), right - left + 1))
        sy = s16(top + c_mod(f.rng.draw(), bottom - top + 1))
        if not f.free(o, sx, sy):
            continue
        if f.overlap_find(sx, sy, i) == 0:
            f.place(o, sx, sy)
            return
    r.stuck = "MapObjectRandomSpotPlace found no free spot in 10000 tries"


# Looks 0, 8 and 9 are void in the C; their caller reads $v0 as the look
# they call left it, so they answer what that look answers.
def look_00(f, r, i):         # MapObjectPartyLook00Step (0x80078E74)
    return wander_step(f, r, i)


def look_01(f, r, i):         # MapObjectPartyLook01Step (0x80078E94)
    return 0


def look_02(f, r, i):         # MapObjectPartyLook02Step (0x80078E9C)
    o = r.obj
    if o.state == 0:
        r.thinks_left = u8(value_div(f.range_draw(o.length, 1, 3) * 0x1E, o.interval))
        o.state = READY
    r.thinks_left = u8(r.thinks_left - 1)
    if r.thinks_left == 0:
        if o.state == READY:
            o.facing_kept = o.facing
            o.state = u8(f.range_draw(o.count, 3, 5) + 1)
        o.state = u8(o.state - 1)
        if o.state != 0:
            d = ((f.rng.draw() & 3) * 2) | 1
        else:
            d = o.facing_kept
        if o.facing != d and o.think & 0x40:
            _turn_set(o, d)
            r.thinks_left = 1
        else:
            o.facing = u8(d)
            r.thinks_left = u8(value_div(0xF, o.interval))
        f.pose_set(r, -1, o.facing)
    return 0


def look_03(f, r, i):         # MapObjectPartyLook03Step (0x80078FD8)
    o = r.obj
    d = o.definition
    if o.state == 0:
        r.target = (d.x * 8, d.y * 8)
        o.facing_kept = o.facing
        nf = facing_toward(o.x, o.depth, r.target[0], r.target[1], o.facing)
        if nf != 0:
            if o.facing != nf and o.think & 0x40:
                _turn_set(o, nf)
                r.thinks_left = 1
                o.state = TURN_THEN_WALK
                return 0
            o.facing = nf
        o.state = READY
    ret = _toward_walk(f, r, i, r.target[0], r.target[1])
    if o.facing_kept == 0:
        if o.x == r.target[0] and o.depth == r.target[1]:
            nf = u8(d.facing + 1)
        else:
            t = ((o.facing + 3) & 7) + 1
            nf = t if t & 1 else (t & 7) + 1
        if o.facing != nf and o.think & 0x40:
            _turn_set(o, nf)
            r.thinks_left = 1
        else:
            o.facing = nf
            r.thinks_left = u8(value_div(0xF, o.interval))
        f.pose_set(r, -1, o.facing)
        o.state = 0
        o.look = (o.look & 0x80) + 2
    return ret


def look_04(f, r, i):         # MapObjectPartyLook04Step (0x800791C0)
    o = r.obj
    if o.state == 0:
        if o.facing_kept == 0:
            o.facing = _open_facing_find(f, r, i, True)
        r.thinks_left = u8(value_div(f.range_draw(o.length, 8, 0x10) * 8, o.speed))
        o.state = READY
    moved = 0
    if o.state == READY:
        moved, stopped_by = _facing_walk(f, r, i)
        if o.facing_kept == 0 and stopped_by != 1:
            o.facing = _side_facing(f, o, 1)
            f.pose_set(r, -1, o.facing)
    r.thinks_left = u8(r.thinks_left - 1)
    if r.thinks_left == 0:
        if o.state == READY:
            o.facing_kept = o.facing
            o.state = u8(f.range_draw(o.count, 3, 5) * 2 + 1)
        o.state = u8(o.state - 1)
        if o.state == 0:
            o.facing = o.facing_kept
        else:
            if o.state & 2:
                if o.think & 0x40:
                    o.turn_plan = 3
                else:
                    o.facing = ((o.facing - 3) & 7) + 1
            elif o.think & 0x40:
                o.turn_plan = 0x83
            else:
                o.facing = ((o.facing + 1) & 7) + 1
            r.thinks_left = 1 if o.turn_plan != 0 else u8(value_div(0xF, o.interval))
        f.pose_set(r, -1, o.facing)
    return moved


def look_05(f, r, i):         # MapObjectPartyLook05Step (0x800793BC)
    o = r.obj
    if o.state == 0:
        _random_walk_start(f, r, 0)
    result = 0
    if o.state == READY:
        result, stopped_by = _facing_walk(f, r, i)
        if o.facing_kept == 0 and stopped_by != 1:
            o.facing = _side_facing(f, o, o.count)
            f.pose_set(r, -1, o.facing)
        r.thinks_left = u8(r.thinks_left - 1)
        if r.thinks_left == 0:
            o.state = 0
    return result


def look_06(f, r, i):         # MapObjectPartyLook06Step (0x80079488)
    o = r.obj
    if o.state == 0:
        _random_walk_start(f, r, 0)
    result = 0
    if o.state == READY:
        result, stopped_by = _facing_walk(f, r, i)
        if o.facing_kept == 0 and stopped_by != 1:
            o.facing = _side_facing(f, o, 0)
            f.pose_set(r, -1, o.facing)
    if o.state != TURN_THEN_WALK:
        r.thinks_left = u8(r.thinks_left - 1)
        if r.thinks_left == 0:
            if o.state == READY:
                r.thinks_left = u8(value_div(f.range_draw(o.count, 1, 3) * 0x1E, o.interval))
                o.state = STOPPED
            else:
                o.state = 0
    return result


def look_07(f, r, i):         # MapObjectPartyLook07Step (0x800795A0)
    o = r.obj
    if o.state == 0:
        _random_walk_start(f, r, 0)
    result = 0
    if o.state == READY:
        result = look_06(f, r, i)
        if o.state == STOPPED:
            o.facing_kept = o.facing
            o.state = u8(f.range_draw(o.count, 3, 5) + 1)
            r.thinks_left = 1
    if o.state < 0x80:
        look_02(f, r, i)
    return result


def look_08(f, r, i):         # MapObjectPartyLook08Step (0x80079658)
    if r.obj.state == 0:
        _random_walk_start(f, r, 8)
    return look_05(f, r, i)


def look_09(f, r, i):         # MapObjectPartyLook09Step (0x800796A4)
    if r.obj.state == 0:
        _random_walk_start(f, r, 8)
    return look_06(f, r, i)


def look_0a(f, r, i):         # MapObjectPartyLook0AStep (0x800796F0)
    o = r.obj
    if o.state == 0:
        d = c_mod(f.rng.draw(), 4) * 2
        o.facing = d + 1
        if o.definition.facing & 1:
            o.facing = d + 2
        o.state = READY
    result, stopped_by = _facing_walk(f, r, i)
    if o.facing_kept == 0 and stopped_by != 1:
        o.facing = _side_facing(f, o, 0)
        f.pose_set(r, -1, o.facing)
    return result


def look_0b(f, r, i):         # MapObjectPartyLook0BStep (0x800797E8)
    o = r.obj
    if o.state == 0:
        r.thinks_left = u8(value_div(f.range_draw(o.length, 1, 3) * 0x1E, o.interval))
        o.state = READY
    r.thinks_left = u8(r.thinks_left - 1)
    result = 0
    if r.thinks_left == 0:
        if o.state == READY:
            o.state = STOPPED
            r.thinks_left = u8(value_div(0x10, o.interval))
            f.pose_set(r, 4, o.facing)
        elif o.state == STOPPED:
            o.state = JUMPED
            r.thinks_left = u8(value_div(0x10, o.interval))
            result = 1
            _random_spot_place(f, r, i)
            f.pose_set(r, 5, o.facing)
        else:
            o.state = 0
            f.pose_set(r, 1, o.facing)
    return result


def look_0c(f, r, i):         # MapObjectPartyLook0CStep (0x80079908)
    o = r.obj
    if o.state == 0:
        _random_walk_start(f, r, 8)
    result = 0
    if o.state == READY:
        result = look_06(f, r, i)
        if o.state == STOPPED:
            r.thinks_left = u8(value_div(0x10, o.interval))
            f.pose_set(r, 4, o.facing)
    elif o.state != TURN_THEN_WALK:
        result = look_0b(f, r, i)
    return result


LOOKS = (look_00, look_01, look_02, look_03, look_04, look_05, look_06, look_07, look_08,
         look_09, look_0a, look_0b, look_0c, look_00)


def look_step(f: Field, r: Row, i: int) -> int:
    """MapObjectPartyLookStep (0x80077F1C), the party unseen."""
    o = r.obj
    if o.turn_plan != 0:
        return _turn_step(f, r, i)
    k = o.look & 0x7F
    if k >= len(LOOKS):
        r.stuck = f"look {k} is past g_MapObjectPartyLookFunctions (0x800B5B3C)"
        return 0
    return LOOKS[k](f, r, i)


THINKS = {0: wander_step, 1: step_command_run, 2: step_command_run, 5: turn_step,
          6: look_step}
THINK_NAMES = {0: "MapObjectWanderStep (0x8006758C)", 1: "StepCommandRun (0x80067768)",
               2: "StepCommandRun (0x80067768)", 5: "MapObjectTurnStep (0x800678F4)",
               6: "MapObjectPartyLookStep (0x80077F1C)"}


def field_rows(objects: list[fo.MapObject], tables_of: dict[int, fo.AnimTable]) -> list[Row]:
    empty = fo.AnimTable((), ())
    return [Row(obj=o, table=tables_of.get(o.sprite_data, empty),
                twin_table=(tables_of.get(o.twin_data, empty)
                            if o.twin_anim is not None else None))
            for o in objects]


@dataclass
class Track:
    """What one sprite list entry shows, tick by tick: (tick, x, y, pose,
    class) at tick 0 and wherever one of them changed. Pose -1 draws
    nothing."""
    points: list = field(default_factory=list)

    def add(self, tick: int, state: tuple) -> None:
        if not self.points or self.points[-1][1:] != state:
            self.points.append((tick, *state))

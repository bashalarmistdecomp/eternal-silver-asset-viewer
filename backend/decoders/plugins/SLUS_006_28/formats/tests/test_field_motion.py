"""Tier 1 for the field's tick — made-up maps, rows and tables, no game data.

What this CAN catch: the generator's seeding order and in-place refill,
its draw past word 55, the facing toward a goal by octant and the facing
kept on a tie, the box test's overlap and touching sides, a tile
animation's delay and frame wrap and the set table's rows, the think
pass's phase and limits gates, a wanderer's step, its turn at its bounds
and after 0x10 blocked thinks, a step list's ops and its restart, a turn
planned the short way round and stepped one facing at a time, and the
first think of look 2.

What it CANNOT catch: whether those rules are the functions'. Only
re-reading rng_seed (0x8001C5F8), rng_refill (0x8001C548), rng_next
(0x8001C6B0), MapFacingTowardGet (0x8005FBBC), MapBoxTouchGet
(0x80067BFC), tile_animation_set (0x800265BC), tile_animation_step
(0x80026690), MapObjectsThink (0x8006736C), MapObjectWanderStep
(0x8006758C), StepCommandRun (0x80067768) and its ops,
MapObjectFacingTurnSet (0x80078D00), MapObjectFacingTurnStep (0x80078D5C)
and MapObjectPartyLook02Step (0x80078E9C) does that: both sides of every
assertion here were written together. See decoders/testing.py.
"""

import struct

from decoders.plugins.SLUS_006_28.formats import field_motion as fmo
from decoders.plugins.SLUS_006_28.formats import field_objects as fo
from decoders.plugins.SLUS_006_28.formats.tests.test_field_objects import (
    _block, _definition, _plane, _tables)


# -- the generator ------------------------------------------------------------

class _Unmixed(fmo.Rng):
    def refill(self):
        pass


def test_rng_seeding_order():
    r = _Unmixed(100)
    # word (21 i) % 55 takes k; k becomes the last word less k
    assert (r.words[55], r.words[21], r.words[42], r.words[8]) == (100, 1, 99, 999_999_902)
    assert r.cursor == 55 and r.draws == 0


def test_rng_refill_is_in_place():
    r = _Unmixed(1)
    r.words = list(range(56))
    fmo.Rng.refill(r)
    assert r.words[1] == r.words[24] == 1 - 32 + fmo.RNG_MOD
    assert r.words[25] == 25 - r.words[1] + fmo.RNG_MOD == 56      # reads the new word 1
    assert r.words[49] == 49 - 56 + fmo.RNG_MOD                    # and the new word 25


def test_rng_draw_refills_past_word_55():
    r, mirror = fmo.Rng(7), fmo.Rng(7)
    mirror.refill()
    got = [r.draw() for _ in range(55)]
    assert got == mirror.words[1:56]
    mirror.refill()
    assert r.draw() == mirror.words[1] and r.draws == 56


# -- the plane's arithmetic ---------------------------------------------------

def test_facing_toward():
    f = fmo.facing_toward
    assert f(10, 10, 10, 10, 3) == 0 and f(0, 0, 5, 5, 0) == 0
    assert (f(0, 0, 0, 9, 1), f(0, 9, 0, 0, 1), f(0, 0, 9, 0, 1), f(9, 0, 0, 0, 1)) == (5, 1, 3, 7)
    assert (f(0, 0, 4, 4, 1), f(0, 4, 4, 0, 1), f(4, 0, 0, 4, 1), f(4, 4, 0, 0, 1)) == (4, 2, 6, 8)
    # mostly right, a little down: the diagonal is kept while facing 4..7
    assert f(0, 0, 9, 2, 5) == 4 and f(0, 0, 9, 2, 1) == 3


def test_box_touch():
    t = fmo.box_touch
    assert t(100, 100, 4, 4, 103, 100, 2, 2) == 9
    assert t(100, 100, 4, 4, 120, 100, 2, 2) == 0
    assert t(100, 100, 0, 4, 100, 100, 2, 2) == 0
    assert t(100, 100, 4, 4, 94, 100, 2, 2) == 3        # touching, the box to the right
    assert t(100, 100, 4, 4, 100, 106, 2, 2) == 1       # the box above
    assert t(100, 100, 4, 4, 94, 94, 2, 2) == 4         # corner to corner


# -- the tile animation -------------------------------------------------------

def test_tile_animation_delay_and_wrap():
    a = fmo.TileAnimation(delay=3, frames=2, count=1, tile=0, source=0)
    seen = []
    for _ in range(7):
        a.step()
        seen.append((a.frame, a.steps))
    assert seen == [(0, 0), (0, 0), (1, 1), (1, 1), (1, 1), (0, 2), (0, 2)]
    every = fmo.TileAnimation(delay=0, frames=3, count=1, tile=0, source=0)
    every.step()
    every.step()
    assert (every.frame, every.steps) == (2, 2)
    assert fmo.tile_place(0x2C6) == (2, 0x60, 0xC0)


def test_tile_animations_reads_the_set_rows():
    image = bytearray(fmo.TILE_ANIMATION_ROWS_ADDR - fo.EXE_BASE + 8 * 4)
    sets = fmo.TILE_ANIMATION_SETS_ADDR - fo.EXE_BASE
    image[sets + 2:sets + 4] = bytes([1, 2])           # set 2: rows 1 and 2
    rows = fmo.TILE_ANIMATION_ROWS_ADDR - fo.EXE_BASE
    image[rows + 8:rows + 16] = bytes([1, 5, 3, 2]) + struct.pack("<2H", 0x105, 7)
    image[rows + 16:rows + 24] = bytes([0, 5, 3, 2]) + struct.pack("<2H", 0x106, 9)
    got = fmo.tile_animations(bytes(image), 2)
    assert [(a.delay, a.frames, a.count, a.tile, a.source) for a in got] == [(5, 3, 2, 0x105, 7)]
    assert fmo.tile_animations(bytes(image), 0) == []


def test_tile_animations_read_where_the_japanese_program_keeps_them(jp_image):
    from decoders.plugins.SLUS_006_28.records import programs
    sets = programs.JP_TABLES["g_TileAnimationSets"].addr - fo.EXE_BASE
    rows = programs.JP_TABLES["g_TileAnimationRows"].addr - fo.EXE_BASE
    image = jp_image(max(sets, rows) + 8 * 4)
    image[sets:sets + 2] = bytes([2, 1])                # set 1: row 2
    image[rows + 16:rows + 24] = bytes([1, 4, 2, 1]) + struct.pack("<2H", 0x107, 3)
    got = fmo.tile_animations(bytes(image), 1)
    assert [(a.delay, a.frames, a.count, a.tile, a.source) for a in got] == [(4, 2, 1, 0x107, 3)]


# -- the rows -----------------------------------------------------------------

def _lead(x=1500, y=1500) -> fmo.Lead:
    return fmo.Lead(x=x, depth=y, box=fo.Box(0, 0, 6, 4), anim=fo.AnimState(),
                    table=fo.AnimTable((), ()), twin_anim=None, twin_table=None)


def _field(defs: dict, att=None, step_lists=b"", limits=()) -> fmo.Field:
    block = _block(defs, step_lists)
    att = att or _plane()
    objs = fo.place_objects(block, att, _tables(), {})
    return fmo.Field(fmo.field_rows(objs, {}), _lead(), att, _tables(), block, limits=limits)


def _walker(**kw) -> bytes:
    # kind 2, number 0, facing 3 (right), speed entry 3: 1 px, every think
    args = dict(kind=2, number=0, speed=0, x=10, y=12, facing=2)
    args.update(kw)
    return _definition(**args)


def test_wander_steps_and_turns_at_its_bounds():
    f = _field({0: _walker()})
    r = f.rows[0]
    o = r.obj
    assert o.bounds == (64, 112, 88, 136) and (o.speed, o.interval) == (1, 1)
    assert fmo.wander_step(f, r, 0) == 1 and (o.x, o.y, o.depth) == (81, 96, 96)
    o.x = 111                                           # the next step is at right
    mirror = fmo.Rng()
    assert fmo.wander_step(f, r, 0) == 0
    assert o.x == 111 and o.facing == mirror.draw() % 8 + 1 and o.turn_count == 0


def test_wander_turns_after_0x10_blocked_thinks():
    f = _field({0: _walker(), 1: _walker(x=11)})        # row 1 stands in the way
    r = f.rows[0]
    for n in range(1, fmo.TURN_AFTER):
        assert fmo.wander_step(f, r, 0) == 0
        assert (r.obj.turn_count, r.obj.facing, f.rng.draws) == (n, 3, 0)
    fmo.wander_step(f, r, 0)
    assert r.obj.turn_count == 0 and f.rng.draws == 1


def test_the_think_pass_gates():
    f = _field({0: _walker(), 1: _walker(y=20), 2: _walker(x=30)},
               limits=[(0, 200, 0, 120), (0, 200, 140, 400)])
    xs = []
    for _ in range(5):
        f.tick()
        xs.append(tuple(r.obj.x for r in f.rows))
    # kind < 4: row i thinks on phase i & 3 only. Each row's limits are the
    # first rectangle holding it; row 2 lies in none: the whole plane.
    assert xs == [(81, 80, 240), (81, 81, 240), (81, 81, 241), (81, 81, 241), (82, 81, 241)]
    assert f.rows[0].limits == (0, 200, 0, 120) and f.rows[1].limits == (0, 200, 140, 400)
    assert f.rows[2].limits == (0, fo.PLANE_LIMIT, 0, fo.PLANE_LIMIT)
    f.rows[0].limits = (0, 50, 0, 50)                   # outside its limits: no think
    for _ in range(4):
        f.tick()
    assert f.rows[0].obj.x == 82


def test_step_list_ops_and_restart():
    ops = (bytes([0xF1, 3]) + bytes([0xF4, 2, 0, 0, 0]) + bytes([0xF6, 2]) + bytes([0xF9]))
    lists = struct.pack("<H", 2) + bytes([0, 1]) + ops
    f = _field({0: _definition(kind=2, number=1, step_list=0, x=10, y=12, facing=0)},
               step_lists=lists)
    r = f.rows[0]
    o = r.obj
    run = fmo.step_command_run
    assert (o.step_list, o.cursor) == (2, 2)
    run(f, r, 0)                                        # F1: facing 3
    assert (o.facing, o.cursor) == (3, 4)
    for _ in range(16):                                 # F4: two cells right, 1 px a think
        run(f, r, 0)
    assert (o.x, o.busy, o.cursor) == (96, 0, 9)
    run(f, r, 0)
    run(f, r, 0)                                        # F6: two thinks
    assert o.cursor == 11
    o.facing = 7
    run(f, r, 0)                                        # F9: from the top, F1 at once
    assert (o.facing, o.cursor) == (3, 4)


def test_step_list_hangs_are_kept_out():
    alone = struct.pack("<H", 2) + bytes([0, 1, 0xF9])
    f = _field({0: _definition(kind=2, number=1, step_list=0)}, step_lists=alone)
    fmo.step_command_run(f, f.rows[0], 0)
    assert "F9 alone" in f.rows[0].stuck
    off = struct.pack("<H", 2) + bytes([0, 1, 0xF4, 0x80, 0, 0, 0])
    f = _field({0: _definition(kind=2, number=1, step_list=0)}, step_lists=off)
    fmo.step_command_run(f, f.rows[0], 0)
    assert "off the plane" in f.rows[0].stuck


def test_turn_planned_the_short_way_and_stepped():
    f = _field({0: _walker(facing=0)})                  # facing 1
    r = f.rows[0]
    o = r.obj
    fmo._turn_set(o, 3)
    assert o.turn_plan == 0x83                          # forward, two facings
    fmo._turn_set(o, 7)
    assert o.turn_plan == 3                             # back, two facings
    fmo._turn_set(o, 3)
    r.thinks_left = 1
    fmo._turn_step(f, r, 0)
    assert (o.facing, o.turn_plan, r.thinks_left) == (2, 0x82, 5)
    r.thinks_left = 1
    fmo._turn_step(f, r, 0)
    assert o.facing == 3


def test_look_02_first_think():
    f = _field({0: _walker(number=6, look=(2, 0, 0, 0, 0))})
    r = f.rows[0]
    mirror = fmo.Rng()
    assert fmo.look_step(f, r, 0) == 0
    waits = (1 + mirror.draw() % 3) * 0x1E
    assert (r.obj.state, r.thinks_left) == (fmo.READY, waits - 1)

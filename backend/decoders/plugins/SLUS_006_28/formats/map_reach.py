"""What a player can see of a map: the party's lead walked from every way
into it by the field's own rules, and the camera that follows him.

THE WAYS IN -- MapChange (0x8005922C) puts the party on a map from an
11-byte MapEnterRow (any map's enter table, or a script's map change): a
spot and the view's limits. MapPartyPlace (0x80059730) moves it inside
the map from a 9-byte MapPartyPlaceRow -- row n of the type-9 payload's
rows at +0x580 (g_MapPartyPlaceRows, 0x801E7080 - 0x801E6B00), started by
a kind-2 attribute cell or by script command 0x27
(ScriptCommandMapPartyPlace (0x8005DCBC)), whose row 0 is built from the
command's own bytes: c[2] the row (0 = inline), c[5..8] the limits,
c[9] x, c[0xA] y, c[0xB] the facing, c[0xC] the sound. The doors of a
town's houses are such moves: each interior is one more way in.

THE WALK -- MapPartyBoxSet (0x8006497C): party kind 0 (the world maps)
has the box {dx 0, dy 0, w 6, h 4}, any other kind {0, -1, 8, 5}. A spot
is free when MapAttributeFreeCheck (0x800692D4) with layer 0 passes its
box: the cells x0 >> 3 .. ((x1 + 7) >> 3) - 1 by y0 >> 3 .. ((y1 + 7) >>
3) - 1 of the box (x - w .. x + w, y - h .. y + h, clamped to 0 .. 0x7FF)
hold no shape (bits 0x3800), but for a diagonal let through in its one
corner of the box (`free_mask`). The lead steps a pixel or two a frame in
eight directions (MapSpotMoveTry (0x8006661C)); the walk here takes
steps of `LATTICE` pixels, every spot inside the limits of the way in.

THE EVENTS -- MapAttributeRun (0x800590C0) acts on the first cell of the
box, in row order, whose id (cell & 0x7FF) has an argument and a kind
below 10 (MapAttributeFind (0x80069A20)): kind 1 leaves the map
(MapChange); kind 2 moves the party (MapPartyPlace, the place row); kind
5 puts it back where it was (MapPartyRingRewind (0x80066F54)) and runs
the map script's label, so the cell is a wall unless the label takes the
party away; kind 4 runs the label (MapAttributeKind4Run (0x80059C48)).
A label takes the party away when every way through it reaches a map
change (0x26, 0x5D) or a move (0x27) before it returns (`label_act`):
the walk stops on such a cell; on any other it goes on past the scene.
Kinds 3, 6, 8 and 9 (a bg change, a button, the colours) do not stop a
walk. A story bit's bg change can open a way or close one: the walk is
taken on each plane it is given (`reach`), the map as it loads and with
its changes copied in, and what they saw is put together.

THE CAMERA -- MapViewGoalGet (0x80069080): the lead is 0xA0 from the
view's left and 0x78 from its top on a 0x140 x 0xE0 screen; below limit
left + 0xA0 the view is at limit left, above limit right - 0xA0 at limit
right - 0x140 (the low test first), and the same on y with 0x78 / 0x68.
The limits are also the draw area's clip, so what shows is the view
cut to the limits. What a player can see of the map is the union of
those, over every spot of every walk.

NOT FOLLOWED -- a scene that moves the camera on its own (a script's
camera commands), a script's moves of the party other than 0x27, which
story bits a label's tests find set (both arms are taken), and which of
two bg changes over the same cells is in place (the planes given are
walked one by one).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

PLANE = 0x800
CELL = 8
CELLS = 0x100
LATTICE = 2                 # the walk's step, in pixels
SHAPE = 0x3800
FULL = 0x3800
EVENT_ID = 0x7FF
EVENT_ARG = 0x7F
EVENT_KINDS = 10            # MapAttributeFind returns ids of kind 0..9
LEAVE_KIND, MOVE_KIND, LABEL_KIND, PUSH_KIND = 1, 2, 4, 5
PLACE_ROWS_AT = 0x580       # in the type-9 payload
PLACE_ROW = 9
PLACE_ROWS = (0xA00 - PLACE_ROWS_AT) // PLACE_ROW
VIEW_W, VIEW_H = 0x140, 0xE0
VIEW_LEFT, VIEW_TOP, VIEW_BOTTOM = 0xA0, 0x78, 0x68
#: script commands (formats.event_script)
LABEL_JUMP, LABEL_CALL, LABEL_RETURN = 0x03, 0x04, 0x05
BIT_TESTS = (0x0B, 0x0C, 0x0D)          # a story-bit test: a label at +2
MAP_CHANGES = (0x26, 0x5D)              # ScriptCommandMapChange, ScriptCommandMapScriptChange
PARTY_PLACE = 0x27                      # ScriptCommandMapPartyPlace
ENDS = (0x42, 0x5E)                     # another script; a handler that returns at once
LABEL_STEPS = 0x100                     # a label's walk is cut here


def party_box(party_kind: int) -> tuple[int, int, int, int]:
    """MapPartyBoxSet: (dx, dy, half width, half height)."""
    return (0, 0, 6, 4) if party_kind == 0 else (0, -1, 8, 5)


@dataclass(frozen=True)
class Start:
    """A way in: the lead's spot and the view's limits, in pixels
    (left, right, top, bottom; right and bottom exclusive)."""
    x: int
    y: int
    limits: tuple[int, int, int, int]
    source: str


def limits_px(left: int, right: int, top: int, bottom: int) -> tuple[int, int, int, int]:
    """A row's limit bytes (8-px cells, the right and bottom ones the last
    column and row) as pixels."""
    return left * CELL, (right + 1) * CELL, top * CELL, (bottom + 1) * CELL


def place_row(payload: bytes, n: int, source: str) -> Start | None:
    """Row `n` of the map's MapPartyPlaceRows, or None past the payload
    or for a row of zeros (the spot, limits and facing all 0)."""
    at = PLACE_ROWS_AT + n * PLACE_ROW
    if not 0 <= n < PLACE_ROWS or at + PLACE_ROW > len(payload):
        return None
    _u, _sound, left, right, top, bottom, x, y, facing = payload[at:at + PLACE_ROW]
    if not any((left, right, top, bottom, x, y, facing)):
        return None                     # a row of zeros: no place
    return Start(x * CELL, y * CELL, limits_px(left, right, top, bottom), source)


def script_place(buf: bytes, offset: int) -> tuple[int, Start | None]:
    """A 0x27 command: (its row number, its own row when the number is 0)."""
    c = buf[offset:offset + 0xE]
    if len(c) < 4:
        return 0, None
    if c[2] or len(c) < 0xE:
        return c[2], None
    return 0, Start(c[9] * CELL, c[0xA] * CELL, limits_px(*c[5:9]),
                    f"script command 0x27 at {offset:#x}")


# ---------------------------------------------------------------------------
# the box test and the event under the box, for every spot of the lattice
# ---------------------------------------------------------------------------

def _axes(lo_pad: int, hi_pad: int):
    """Per lattice coordinate p: the box's low and high edge (clamped), its
    first cell and its cell count."""
    p = np.arange(0, PLANE, LATTICE)
    lo = np.maximum(p - lo_pad, 0)
    hi = np.minimum(p + hi_pad, PLANE - 1)
    first = lo >> 3
    count = ((hi + 7) >> 3) - first
    return lo, hi, first, count


def _cells(plane: np.ndarray, ty: np.ndarray, tx: np.ndarray) -> np.ndarray:
    """plane[ty, tx] broadcast, a cell off the plane read as 0."""
    ok = (ty[:, None] < CELLS) & (tx[None, :] < CELLS)
    v = plane[np.minimum(ty, CELLS - 1)[:, None], np.minimum(tx, CELLS - 1)[None, :]]
    return np.where(ok, v, 0)


def free_mask(plane: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """MapAttributeFreeCheck (layer 0) at every lattice spot, as
    [y // LATTICE, x // LATTICE] -> True where the lead's box is free."""
    dx, dy, w, h = box
    x0, x1, tx0, cols = _axes(w - dx, w + dx)
    y0, y1, ty0, rows = _axes(h - dy, h + dy)
    blocked = np.zeros((len(y0), len(x0)), dtype=bool)
    xa, xb = (x0 & 7)[None, :], ((x1 - 1) & 7)[None, :]
    ya, yb = (y0 & 7)[:, None], ((y1 - 1) & 7)[:, None]
    for i in range(3):
        for j in range(3):
            valid = (i < rows)[:, None] & (j < cols)[None, :]
            shape = _cells(plane, ty0 + i, tx0 + j) & SHAPE
            last_col = (j == cols - 1)[None, :] & (j != 0)
            if i == 0:
                tol = ((shape == 0x0800) & (xa + ya >= 7)) if j == 0 else \
                    ((shape == 0x1000) & (xb < ya) & last_col)
            else:
                last_row = (i == rows - 1)[:, None]
                tol = (last_row & (shape == 0x2000) & (xa >= yb)) if j == 0 else \
                    (last_row & last_col & (shape == 0x1800) & (xb + yb < 7))
            blocked |= valid & (shape != 0) & ~tol
    return ~blocked


def event_ids(plane: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """MapAttributeFind's answer at every lattice spot: the first id of
    the box's cells, in row order, with an argument and a kind below 10;
    0 for none."""
    dx, dy, w, h = box
    _x0, _x1, tx0, cols = _axes(w - dx, w + dx)
    _y0, _y1, ty0, rows = _axes(h - dy, h + dy)
    ev = np.zeros((len(ty0), len(tx0)), dtype=np.int32)
    for i in range(3):
        for j in range(3):
            valid = (i < rows)[:, None] & (j < cols)[None, :]
            ids = _cells(plane, ty0 + i, tx0 + j) & EVENT_ID
            hit = valid & (ev == 0) & ((ids & EVENT_ARG) != 0) & ((ids >> 7) < EVENT_KINDS)
            ev[hit] = ids[hit]
    return ev


# ---------------------------------------------------------------------------
# a map script's label: what it does first
# ---------------------------------------------------------------------------

GONE, STAYS = "gone", "stays"


def label_act(buf: bytes, commands: dict, labels: dict[int, int], label: int) -> str:
    """GONE when every way through label `label` reaches a map change or a
    move of the party before it returns; else STAYS. `commands` maps an
    offset to its event_script.Command; a story-bit test is taken both
    ways, a call is followed in and back."""
    memo: dict[int, bool] = {}
    open_: set[int] = set()

    def gone_from(at: int | None, depth: int) -> bool:
        if at is None or depth > LABEL_STEPS:
            return False
        if at in memo:
            return memo[at]
        c = commands.get(at)
        if c is None or at in open_:
            return False
        open_.add(at)
        if c.id in MAP_CHANGES or c.id == PARTY_PLACE:
            r = True
        elif c.id == LABEL_RETURN or c.id in ENDS:
            r = False
        elif c.id == LABEL_JUMP:
            r = gone_from(labels.get(c.u16(buf, 2)), depth + 1)
        elif c.id == LABEL_CALL:
            r = gone_from(labels.get(c.u16(buf, 2)), depth + 1) or gone_from(c.end, depth + 1)
        elif c.id in BIT_TESTS:
            r = gone_from(labels.get(c.u16(buf, 2)), depth + 1) and gone_from(c.end, depth + 1)
        else:
            r = gone_from(c.end, depth + 1)
        open_.discard(at)
        memo[at] = r
        return r
    return GONE if gone_from(labels.get(label), 0) else STAYS


# ---------------------------------------------------------------------------
# the walk and the camera
# ---------------------------------------------------------------------------

@dataclass
class Reach:
    """What the walks saw."""
    seen: np.ndarray            # [y, x] over the plane: True where the camera showed it
    spots: int                  # lattice spots walked
    starts: list[Start]         # the ways in walked from, moves included
    blocked: list[Start]        # ways in whose box is not free and that lead nowhere

    @property
    def bbox(self) -> tuple[int, int, int, int] | None:
        ys, xs = np.nonzero(self.seen.any(axis=1))[0], np.nonzero(self.seen.any(axis=0))[0]
        if not len(xs):
            return None
        return int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1

    @property
    def areas(self) -> list[tuple[int, int, int, int]]:
        """Each camera area walked in (a way in's limits), cut to what the
        camera showed in it: (left, top, right, bottom), top to bottom."""
        out = set()
        for st in self.starts + self.blocked:
            left, right, top, bottom = st.limits
            part = self.seen[top:bottom, left:right]
            ys, xs = np.nonzero(part.any(axis=1))[0], np.nonzero(part.any(axis=0))[0]
            if len(xs):
                out.add((left + int(xs[0]), top + int(ys[0]),
                         left + int(xs[-1]) + 1, top + int(ys[-1]) + 1))
        return sorted(out, key=lambda b: (b[1], b[0], b[3], b[2]))


def view(x: int, y: int, limits: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """MapViewGoalGet's view of a lead at (x, y), cut to the limits:
    (left, top, right, bottom), right and bottom exclusive."""
    left, right, top, bottom = limits
    vx = left if x < left + VIEW_LEFT else right - VIEW_W if x > right - VIEW_LEFT else x - VIEW_LEFT
    vy = top if y < top + VIEW_TOP else bottom - VIEW_H if y > bottom - VIEW_BOTTOM else y - VIEW_TOP
    return (max(vx, left), max(vy, top), min(vx + VIEW_W, right), min(vy + VIEW_H, bottom))


def walk(plane: list[list[int]], party_kind: int, starts: list[Start],
         label_acts: dict[int, str], places: dict[int, Start]) -> Reach:
    """Walk the lead from every start (module docstring). `label_acts`:
    the map script's label -> GONE / STAYS (`label_act`); `places`: place
    row -> its Start, for kind-2 cells."""
    grid = np.array(plane, dtype=np.int32)
    box = party_box(party_kind)
    free = free_mask(grid, box)
    ev = event_ids(grid, box)
    n = PLANE // LATTICE
    kind = ev >> 7
    arg = ev & EVENT_ARG
    gone = (kind == LEAVE_KIND) | (kind == MOVE_KIND)
    for label, act in label_acts.items():
        if act == GONE:
            gone |= ((kind == LABEL_KIND) | (kind == PUSH_KIND)) & (arg == label)
    wall = (kind == PUSH_KIND) & ~gone
    can = free & ~wall
    views: set[tuple[int, int, int, int]] = set()
    walked: dict[tuple, bytearray] = {}
    queue = deque(starts)
    queued = set(starts)
    done: list[Start] = []
    blocked: list[Start] = []
    spots = 0
    while queue:
        s = queue.popleft()
        done.append(s)
        left, right, top, bottom = s.limits
        here = walked.setdefault(s.limits, bytearray(n * n))
        sx, sy = s.x // LATTICE, s.y // LATTICE
        if not (0 <= sx < n and 0 <= sy < n) or here[sy * n + sx]:
            continue
        here[sy * n + sx] = 1
        todo = deque([(sx, sy, True)])
        lo_x, hi_x = max(left // LATTICE, 0), min((right - 1) // LATTICE, n - 1)
        lo_y, hi_y = max(top // LATTICE, 0), min((bottom - 1) // LATTICE, n - 1)
        mine = 0
        while todo:
            x, y, first = todo.popleft()
            mine += 1
            views.add(view(x * LATTICE, y * LATTICE, s.limits))
            if not first and gone[y, x]:
                if kind[y, x] == MOVE_KIND:
                    to = places.get(int(arg[y, x]))
                    if to is not None and to not in queued:
                        queued.add(to)
                        queue.append(to)
                continue
            for a in (-1, 0, 1):
                for b in (-1, 0, 1):
                    nx, ny = x + a, y + b
                    if not (lo_x <= nx <= hi_x and lo_y <= ny <= hi_y):
                        continue
                    k = ny * n + nx
                    if here[k] or not can[ny, nx]:
                        continue
                    here[k] = 1
                    todo.append((nx, ny, False))
        spots += mine
        if mine == 1:
            blocked.append(s)
    return Reach(seen=seen_mask(views), spots=spots, starts=done, blocked=blocked)


def reach(planes: list[list[list[int]]], party_kind: int, starts: list[Start],
          label_acts: dict[int, str], places: dict[int, Start]) -> Reach:
    """`walk` on each attribute plane, put together: what the camera
    showed on any of them."""
    walks = [walk(p, party_kind, starts, label_acts, places) for p in planes]
    if not walks:
        return Reach(seen=np.zeros((PLANE, PLANE), dtype=bool), spots=0, starts=[], blocked=[])
    seen = walks[0].seen.copy()
    for w in walks[1:]:
        seen |= w.seen
    done = list(dict.fromkeys(s for w in walks for s in w.starts))
    blocked = [s for s in dict.fromkeys(s for w in walks for s in w.blocked)
               if all(s in w.blocked for w in walks)]
    return Reach(seen=seen, spots=sum(w.spots for w in walks), starts=done, blocked=blocked)


def seen_mask(views: set[tuple[int, int, int, int]]) -> np.ndarray:
    """The union of the views' rectangles over the plane."""
    diff = np.zeros((PLANE + 1, PLANE + 1), dtype=np.int32)
    if views:
        v = np.array(sorted(views), dtype=np.int64).reshape(-1, 4)
        v = v[(v[:, 2] > v[:, 0]) & (v[:, 3] > v[:, 1])]
        l, t, r, b = (np.clip(v[:, k], 0, PLANE) for k in range(4))
        np.add.at(diff, (t, l), 1)
        np.add.at(diff, (t, r), -1)
        np.add.at(diff, (b, l), -1)
        np.add.at(diff, (b, r), 1)
    return diff.cumsum(axis=0).cumsum(axis=1)[:PLANE, :PLANE] > 0


def payload_places(payload: bytes) -> dict[int, Start]:
    """Every place row of a type-9 payload, by number."""
    out = {}
    for k in range(PLACE_ROWS):
        r = place_row(payload, k, f"place row {k}")
        if r is not None:
            out[k] = r
    return out

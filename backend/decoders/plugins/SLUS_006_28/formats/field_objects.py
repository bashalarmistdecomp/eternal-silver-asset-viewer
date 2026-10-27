"""Map objects on their map: where a map entry puts the people, roaming
enemies and chests of an object set, and the party; the class each stands
in; the animation each starts on; and the field tick that animates them.

ENTERING A MAP -- MapChange (0x8005922C) takes an 11-byte MapEnterRow
(map.h): row `idx` of the map being left (the table its command 9 fills,
resource_map_enter_table_set (0x80020B8C)) or one a script builds from its
own bytes (ScriptCommandMapChange (0x8005DB3C), command 0x26 with c[4] 0,
and ScriptCommandMapScriptChange (0x8005F068), command 0x5D):

    +0 map    +1 object set    +2 fade    +3 sound
    +4..+7    the view limits, 8-px cells: left, right (its last), top,
              bottom (its last): g_MapLimitLeft = left * 8,
              g_MapLimitRight = (right + 1) * 8, the same for top / bottom
    +8, +9    the party's spot, 8-px cells     +0xA  its facing less 1

In that order it runs MapSet, MapObjectsInit(set) and MapPartySpotSet with
(x * 8, y * 8, facing + 1), then sets the limits.

THE OBJECTS -- MapObjectsInit (0x800655C8) walks the set's 0x80
definitions (`Definition`) and makes one row of g_MapObjects for each whose
sprite data byte is not 0, rows packed in definition order. A definition
whose byte 2 is not 0 is left out while its event flag is set
(`story_flag`); `place_objects` makes every one, as if none were.
MapObjectInit (0x800656CC), for each:

    kind = (byte 0 & 0x3F) + 1; MapRecordInit (0x80065940) on the sprite
    data byte (0 for kind 7, the chest) with the definition's mode
    x = byte 4 * 8; draw y = ground y = byte 5 * 8
    layer = byte 0 & 0x80; think number = (byte 0 & 0x40) | byte 0xC
    facing = byte 6 + 1; box = bytes 7..0xA
    n = MapObjectMoveSet (0x80065A2C): the think's state, and the pose group
        to start on: byte 1 of the step list for think numbers 1 and 2,
        else 1
    class = MapAttributeClassGet (0x8006960C)(1, 0x20, x, y, y, box, layer)
    a chest whose facing is 5 or more turns 4 back (open) when its event
        flag is set (`chest_flag`); `place_objects` shows it closed
    MapAnimationPoseSet (0x8006633C)(row, n, facing)
    a sprite data byte below 0xF also makes a TWIN: a copy of the row put on
    g_MapTwinSpriteDataNumbers[byte - 1] and MapAnimationPoseSet(twin, n,
    byte 6 + 1)

THE PARTY -- MapPartySpotSet (0x80064B8C) remakes the party's records
(MapPartyRecordsInit (0x80064898), MapPartyRecordInit (0x800649DC)), fills
the whole position ring with one entry, the spot (MapPartyRingFill
(0x80067064): its class MapAttributeClassGet(1, 0x18, x, y, y, the lead's
box, 0)) and puts every live member on it (MapPartyRingFollow
(0x800671C4): MapAnimationPoseSet(member, 1, facing); MapPartyTwinSpotSet
(0x800672E8) the same for its twin). So the party stands on the spot as
one, the lead in front: the members are sprite list entries 0..5 and at
one depth the entry queued first is drawn in front. The lead's box is
MapPartyBoxSet (0x8006497C)'s: half 6 x 4 at (0, 0) while g_MapPartyKind
is 0, else half 8 x 5 at (0, -1).

THE CLASS -- MapAttributeClassGet answers 0x2000 or 0x4000 for where a
record stands, from the map's attribute plane (`world_map.attribute_plane`):
0x4000 at once for a record above the ground (draw y != ground y), else
the first cell under the box with bit 0x8000 decides (0x2000 when the
layer is 0 or the cell has 0x4000), else the cells above the box, else a
climb of the box up to `top` pixels through MapAttributeFreeCheck
(0x800692D4). sprite_list.c draws class 0x2000 under the roofs and 0x4000
over them (`field_picture`).

THE ANIMATION -- a record's animation is the MapRecord words +0x30..+0x3A
(`AnimState`), its sprite data's tables `AnimTable`. MapAnimationPoseSet
picks id 4 * (group - 1) + 1 + column, the column by facing (5: 0; 1, 2, 8:
1; 6, 7: 2; 3, 4: 3); MapAnimationSet (0x800663EC) starts it with
MapAnimationStart (0x80066468), keeping the timer when only the column of
a group 1..60 changed; MapObjectsAnimationStep (0x80065FD8) and
MapPartyAnimationStep (0x80065CF8) tick it once a frame and keep each twin
on its record's animation (`anim_tick`, `twin_sync`).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from decoders.plugins.SLUS_006_28.formats import command_list
from decoders.plugins.SLUS_006_28.formats.sprite_pages import (
    ANIM_HOLD, ANIM_STRIDE, STEP_STRIDE, SpriteBlockData)
from decoders.plugins.SLUS_006_28.records.programs import address

EXE_BASE = 0x80011000
TWIN_NUMBERS_ADDR = 0x80012C00      # g_MapTwinSpriteDataNumbers
SPEED_PIXELS_ADDR = 0x80012C0C      # g_MoveSpeedPixels: pixels a tick, by speed
SPEED_INTERVALS_ADDR = 0x80012C14   # g_MoveSpeedIntervals: frames between ticks
FACING_DXS_ADDR = 0x80012C1C        # g_MapFacingDxs: the step in x of facings 1..8
FACING_DYS_ADDR = 0x80012C24        # g_MapFacingDys: the step in y
_TABLE_NAMES = {TWIN_NUMBERS_ADDR: "g_MapTwinSpriteDataNumbers",
                SPEED_PIXELS_ADDR: "g_MoveSpeedPixels",
                SPEED_INTERVALS_ADDR: "g_MoveSpeedIntervals",
                FACING_DXS_ADDR: "g_MapFacingDxs", FACING_DYS_ADDR: "g_MapFacingDys"}
TABLE_BYTES = 8
TWIN_BELOW = 0xF                    # MapObjectInit: a sprite data byte below 0xF has a twin

DEFINITION_SIZE = 0x26
DEFINITION_COUNT = 0x80
STEP_LISTS_AT = DEFINITION_SIZE * DEFINITION_COUNT      # g_MapObjectStepLists

ENTER_COMMAND = 9                   # the map's enter table (command_list)
ENTER_ROW = 11
ENTER_ROWS = 0x80                   # rows 1..127; row 0 is a script's own

CHEST_KIND = 7
CHEST_OPEN_FROM = 5                 # MapObjectInit: a chest facing 5 or more opens to facing - 4
CHEST_OPEN_TURN = 4
THINK_STEP_LISTS = (1, 2)           # MapObjectMoveSet: think numbers that run a step list
THINK_LOOKS = (0, 6)                # ... and those that take bounds, speed and a look set
OBJECT_TOP = 0x20                   # MapObjectInit / MapObjectsThink: MapAttributeClassGet(1, 0x20, ...)
PARTY_TOP = 0x18                    # MapPartyRingFill: MapAttributeClassGet(1, 0x18, ...)
PLANE_LIMIT = 0x800                 # the map's 2048-px side
ANIM_NONE = 0xFFFF                  # MapRecordInit: the animation no MapAnimationSet keeps
ANIM_GROUPED = 60                   # MapAnimationSet: ids 1..60 keep the timer within a group

CLASS_UNDER = 0x2000                # drawn under the roofs (sprite_list.c)
CLASS_OVER = 0x4000

#: MapAnimationPoseSet's column for a facing; other facings leave the record alone.
FACING_COLUMNS = {5: 0, 1: 1, 2: 1, 8: 1, 6: 2, 7: 2, 3: 3, 4: 3}


# ---------------------------------------------------------------------------
# the program's tables
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FieldTables:
    """The EXE's small tables the field's movement reads."""
    twins: bytes                # g_MapTwinSpriteDataNumbers, entry n - 1 for sprite data n
    speed_pixels: bytes
    speed_intervals: bytes
    dxs: tuple[int, ...]        # signed
    dys: tuple[int, ...]


def field_tables(image: bytes) -> FieldTables:
    """The tables, each where the image's program keeps it (records.programs)."""
    def at(addr: int, n: int) -> bytes:
        addr = address(image, _TABLE_NAMES[addr], addr)
        out = bytes(image[addr - EXE_BASE:addr - EXE_BASE + n])
        if len(out) != n:
            raise ValueError(f"EXE image too short for the table at {addr:#x}")
        return out
    return FieldTables(
        twins=at(TWIN_NUMBERS_ADDR, TWIN_BELOW - 1),
        speed_pixels=at(SPEED_PIXELS_ADDR, TABLE_BYTES),
        speed_intervals=at(SPEED_INTERVALS_ADDR, TABLE_BYTES),
        dxs=struct.unpack("8b", at(FACING_DXS_ADDR, TABLE_BYTES)),
        dys=struct.unpack("8b", at(FACING_DYS_ADDR, TABLE_BYTES)))


# ---------------------------------------------------------------------------
# the definitions and the entries
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Box:
    """MapBox (map.h): a footprint's centre offset and half sizes."""
    dx: int
    dy: int
    half_width: int
    half_height: int


@dataclass(frozen=True)
class Definition:
    """One MapObjectDefinition (map.h), 0x26 bytes."""
    index: int
    kind_byte: int          # +0x00
    sprite_data: int        # +0x01
    story_bit: int          # +0x02
    mode: int               # +0x03: MapRecordInit's mode
    x: int                  # +0x04, 8-px cells
    y: int                  # +0x05
    facing: int             # +0x06, the facing less 1
    box: Box                # +0x07..+0x0A
    event: int              # +0x0B
    number: int             # +0x0C
    speed: int              # +0x0D
    bound_left: int         # +0x0E, s8
    bound_right: int        # +0x0F, u8
    bound_top: int          # +0x10, s8
    bound_bottom: int       # +0x11, u8
    step_list: int          # +0x12
    touch_reach: int        # +0x13
    look_set: bytes         # +0x14..+0x18
    second_look_set: bytes  # +0x19..+0x1D
    raw: bytes

    @property
    def kind(self) -> int:
        return (self.kind_byte & 0x3F) + 1

    @property
    def layer(self) -> int:
        return self.kind_byte & 0x80

    @property
    def think(self) -> int:
        """MapObjectInit's +0x3D: (byte 0 & 0x40) | byte 0xC."""
        return (self.kind_byte & 0x40) | self.number


def definition(block: bytes, index: int) -> Definition:
    raw = bytes(block[index * DEFINITION_SIZE:(index + 1) * DEFINITION_SIZE])
    if len(raw) < DEFINITION_SIZE:
        raise ValueError(f"definition {index} runs off the {len(block):#x}-byte block")
    return Definition(index=index, kind_byte=raw[0], sprite_data=raw[1], story_bit=raw[2],
                      mode=raw[3], x=raw[4], y=raw[5], facing=raw[6],
                      box=Box(*struct.unpack_from("<2b2B", raw, 7)), event=raw[0xB],
                      number=raw[0xC], speed=raw[0xD],
                      bound_left=struct.unpack_from("b", raw, 0xE)[0], bound_right=raw[0xF],
                      bound_top=struct.unpack_from("b", raw, 0x10)[0], bound_bottom=raw[0x11],
                      step_list=raw[0x12], touch_reach=raw[0x13],
                      look_set=raw[0x14:0x19], second_look_set=raw[0x19:0x1E], raw=raw)


def made_definitions(block: bytes) -> list[Definition]:
    """MapObjectsInit's walk: every definition whose sprite data byte is not
    0, in order (whether an event flag holds one back is the running game's)."""
    out = []
    for i in range(DEFINITION_COUNT):
        d = definition(block, i)
        if d.sprite_data:
            out.append(d)
    return out


@dataclass(frozen=True)
class MapEntry:
    """A MapEnterRow: where MapChange puts the party, with which set."""
    map: int
    object_set: int
    fade: int
    sound: int
    limits: tuple[int, int, int, int]   # left, right, top, bottom, 8-px cells
    x: int                              # 8-px cells
    y: int
    facing: int                         # the spot's facing, byte + 1 (u8)
    source: str                         # where the row is

    @property
    def spot(self) -> tuple[int, int]:
        return self.x * 8, self.y * 8

    @property
    def limit_rect(self) -> tuple[int, int, int, int]:
        """g_MapLimitLeft, Right, Top, Bottom in pixels (MapChange)."""
        left, right, top, bottom = self.limits
        return left * 8, (right + 1) * 8, top * 8, (bottom + 1) * 8


def enter_row(row: bytes, source: str) -> MapEntry:
    """An 11-byte MapEnterRow."""
    if len(row) < ENTER_ROW:
        raise ValueError(f"{source}: a MapEnterRow is {ENTER_ROW} bytes")
    return MapEntry(map=row[0], object_set=row[1], fade=row[2], sound=row[3],
                    limits=tuple(row[4:8]), x=row[8], y=row[9],
                    facing=(row[10] + 1) & 0xFF, source=source)


def table_rows(map_raw: bytes, map_id: int) -> list[tuple[int, MapEntry]]:
    """(row, entry) for rows 1..127 of a map's enter table (the command-9
    payload in effect) that name a map. MapChange (0x8005922C) reads row
    `idx` of the table the map on screen loaded: a step on an attribute
    cell of kind 1 (MapAttributeRun (0x800590C0)) or a script's command
    0x26 with c[4] not 0 takes the party from map `map_id` to the row's
    map."""
    cmd = command_list.effective(map_raw, ENTER_COMMAND)
    if cmd is None:
        return []
    out = []
    for i in range(1, ENTER_ROWS):
        row = cmd.payload[i * ENTER_ROW:(i + 1) * ENTER_ROW]
        if len(row) < ENTER_ROW:
            break
        if row[0]:
            out.append((i, enter_row(row, f"map {map_id}'s entrance {i}")))
    return out


def table_entries(map_raw: bytes, map_id: int) -> list[MapEntry]:
    """The rows of `table_rows` alone: the ways out of map `map_id`."""
    return [e for _i, e in table_rows(map_raw, map_id)]


def script_entry(buf: bytes, offset: int, source: str) -> MapEntry:
    """The row ScriptCommandMapChange (0x8005DB3C) / ScriptCommandMapScriptChange
    (0x8005F068) build from a command's own bytes: c[6] the map, c[7] the
    fade, c[8..0xB] the limits, c[0xC] x, c[0xD] y, c[0xE] the facing less
    1, c[0xF] the sound, c[0x10] the set."""
    c = buf[offset:offset + 0x11]
    if len(c) < 0x11:
        raise ValueError(f"{source}: the command runs off the script")
    return enter_row(bytes([c[6], c[0x10], c[7], c[0xF], *c[8:0xC], c[0xC], c[0xD], c[0xE]]),
                     source)


# ---------------------------------------------------------------------------
# the attribute plane's probes (map_over.c)
# ---------------------------------------------------------------------------
class Attributes:
    """The 256 x 256 attribute cells (`world_map.attribute_plane`), 8 px a
    cell; a cell off the plane reads 0, as the probes read it."""

    def __init__(self, plane: list[list[int]]):
        self.plane = plane
        self.size = len(plane)

    def cell(self, tx: int, ty: int) -> int:
        if 0 <= tx < 0x100 and 0 <= ty < 0x100 and ty < self.size and tx < len(self.plane[ty]):
            return self.plane[ty][tx]
        return 0


def free_check(att: Attributes, x: int, y: int, w: int, h: int, layer: int,
               flag: int = 0) -> int:
    """MapAttributeFreeCheck (0x800692D4): 1 when the box x - w .. x + w,
    y - h .. y + h is free, 0 when blocked."""
    if flag & 0xFF:
        return 1
    solid_all = 0x4000 if (layer & 0xFFFF) == 0 else 0
    x0, y0 = max(x - w, 0), max(y - h, 0)
    x1 = 0x7FF if x + w >= PLANE_LIMIT else x + w
    y1 = 0x7FF if y + h >= PLANE_LIMIT else y + h
    tx0, ty0 = x0 >> 3, y0 >> 3
    cols = ((x1 + 7) >> 3) - tx0
    rows = ((y1 + 7) >> 3) - ty0
    for i in range(rows):
        ty = ty0 + i
        for j in range(cols):
            tile = att.cell(tx0 + j, ty)
            solid = solid_all | (tile & 0x4000)
            shape = tile & 0x3800
            if not solid or not shape:
                continue
            if shape != 0x3800:
                if i == 0:
                    if j == 0:
                        if shape == 0x800 and (x0 & 7) + (y0 & 7) >= 7:
                            continue
                    elif j == cols - 1:
                        if shape == 0x1000 and ((x1 - 1) & 7) - (y0 & 7) < 0:
                            continue
                elif i == rows - 1:
                    if j == 0:
                        if shape == 0x2000 and (x0 & 7) - ((y1 - 1) & 7) >= 0:
                            continue
                    elif j == cols - 1:
                        if shape == 0x1800 and ((x1 - 1) & 7) + ((y1 - 1) & 7) < 7:
                            continue
            return 0
    return 1


def class_get(att: Attributes, step: int, top: int, x: int, y: int, ground: int,
              box: Box, layer: int) -> int:
    """MapAttributeClassGet (0x8006960C): 0x2000 or 0x4000 for a record
    whose anchor is (x, y) over ground y `ground`."""
    if y != ground:
        return CLASS_OVER
    dy = box.dy
    x += box.dx
    w = box.half_width
    y += dy
    h = box.half_height
    x0 = max(x - w, 0) >> 3
    y0 = max(y - h, 0) >> 3
    rows = ((y + h + 7) >> 3) - y0
    cols = ((x + w + 7) >> 3) - x0
    for i in range(rows):
        for j in range(cols):
            tile = att.cell(x0 + j, y0 + i)
            if tile & 0x8000:
                return CLASS_UNDER if layer == 0 or tile & 0x4000 else CLASS_OVER
    acc = 0
    v = (y - dy - top) >> 3
    above = y0 - v
    if above > 0:
        for i in range(above):
            for j in range(cols + above * 2):
                acc |= att.cell(x0 - above + j, i + v) & 0x4000
    # (acc holds bit 0x4000 only: its test for 0x8000 never passes.)
    if layer != 0 and not acc & 0x4000:
        return CLASS_OVER
    i = step
    while i <= top + dy - h:
        row = y - i
        if not free_check(att, x, row, w, h, layer):
            if free_check(att, x + 1, row, w, h, layer):
                x += step
            elif free_check(att, x - 1, row, w, h, layer):
                x -= step
            else:
                return CLASS_OVER
        i += step
    return CLASS_UNDER


# ---------------------------------------------------------------------------
# animation (map_animation.c)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AnimTable:
    """A sprite data block's animation rows (count word, first step) and
    steps (pose, length), as MapAnimationStart and the steppers index them."""
    rows: tuple[tuple[int, int], ...]
    steps: tuple[tuple[int, int], ...]

    def row(self, animation: int) -> tuple[int, int] | None:
        return self.rows[animation] if 0 <= animation < len(self.rows) else None

    def length(self, step: int) -> int:
        return self.steps[step][1] if 0 <= step < len(self.steps) else 0

    def pose(self, step: int) -> int | None:
        return self.steps[step][0] if 0 <= step < len(self.steps) else None

    def hold(self, animation: int) -> bool:
        r = self.row(animation)
        return bool(r and r[0] & ANIM_HOLD)


def anim_table(data: SpriteBlockData | None) -> AnimTable:
    """The tables MapRecordSpriteDataSet (0x800645A8) points a record at."""
    if data is None:
        return AnimTable((), ())
    pose_base = data.pose_tables[0] if data.pose_tables else 0
    if not (0 < data.anim_base < data.step_base <= pose_base):
        return AnimTable((), ())
    rows = tuple(struct.unpack_from("<2H", data.payload, data.anim_base + ANIM_STRIDE * a)
                 for a in range((data.step_base - data.anim_base) // ANIM_STRIDE))
    steps = tuple(struct.unpack_from("<2H", data.payload, data.step_base + STEP_STRIDE * k)
                  for k in range((pose_base - data.step_base) // STEP_STRIDE))
    return AnimTable(rows, steps)


@dataclass
class AnimState:
    """MapRecord +0x30..+0x3A, all u16. MapRecordInit leaves a record on
    animation 0xFFFF; the rest is the zeroed table's."""
    animation: int = ANIM_NONE
    before: int = 0
    timer: int = 0
    length: int = 0
    step: int = 0
    end: int = 0


def anim_start(st: AnimState, table: AnimTable, restart: bool) -> None:
    """MapAnimationStart (0x80066468). An id past the table starts nothing
    (the game would read past it)."""
    row = table.row(st.animation)
    first, count = (row[1], row[0]) if row else (0, 0)
    st.step = first & 0xFFFF
    st.end = (first + (count & 0x7FFF)) & 0xFFFF
    if restart:
        st.timer = 0
        st.length = table.length(st.step)


def anim_set(st: AnimState, table: AnimTable, animation: int) -> None:
    """MapAnimationSet (0x800663EC)."""
    animation &= 0xFFFF
    if st.animation == animation:
        return
    st.before, st.animation = st.animation, animation
    keep = (1 <= st.before <= ANIM_GROUPED and 1 <= animation <= ANIM_GROUPED
            and ((st.before - 1) & 0xFFFC) == ((animation - 1) & 0xFFFC))
    anim_start(st, table, not keep)


def pose_set(st: AnimState, table: AnimTable, pose: int, facing: int) -> None:
    """MapAnimationPoseSet (0x8006633C): pose group `pose` (0: id 0; below 0:
    the record's own group) turned to `facing`."""
    if pose == 0:
        anim_set(st, table, 0)
        return
    if pose < 0:
        base = (((st.animation - 1) & 0xFFFD) | 1) & 0xFFFF
    else:
        base = (((pose - 1) * 4) | 1) & 0xFFFF
    column = FACING_COLUMNS.get(facing & 0xFFFF)
    if column is not None:
        anim_set(st, table, base + column)


def pose_set_id(pose: int, facing: int, animation: int = ANIM_NONE) -> int | None:
    """The id MapAnimationPoseSet hands MapAnimationSet, or None when the
    facing leaves the record alone."""
    if pose == 0:
        return 0
    base = (((animation - 1) & 0xFFFD) | 1) if pose < 0 else (((pose - 1) * 4) | 1)
    column = FACING_COLUMNS.get(facing & 0xFFFF)
    return None if column is None else (base + column) & 0xFFFF


def anim_tick(st: AnimState, table: AnimTable) -> None:
    """One frame of MapObjectsAnimationStep / MapPartyAnimationStep for a
    record that ticks."""
    st.timer = (st.timer + 1) & 0xFFFF
    if st.timer < st.length:
        return
    st.step = (st.step + 1) & 0xFFFF
    if st.step >= st.end:
        if table.hold(st.animation):
            st.step = (st.step - 1) & 0xFFFF
            st.timer = 0
            st.length = table.length(st.step)
        else:
            anim_start(st, table, True)
    else:
        st.timer = 0
        st.length = table.length(st.step)


def twin_sync(twin: AnimState, twin_table: AnimTable, row: AnimState) -> None:
    """The steppers' twin: on the record's animation (MapAnimationSet), as
    far from its own end as the record is from the record's, the record's
    timer and step length."""
    anim_set(twin, twin_table, row.animation)
    twin.step = (twin.end - ((row.end - row.step) & 0xFFFF)) & 0xFFFF
    twin.timer = row.timer
    twin.length = row.length


# ---------------------------------------------------------------------------
# the objects as MapObjectsInit makes them
# ---------------------------------------------------------------------------
@dataclass
class MapObject:
    """One row of g_MapObjects (0x60 bytes, map.h) and its twin, as far as
    the field's placement, think and draw read them."""
    definition: Definition
    row: int                    # its row: the made definitions packed in order
    kind: int
    sprite_data: int            # the record's sprite data (0 for the chest)
    mode: int
    x: int
    y: int                      # the draw y
    depth: int                  # the ground y
    layer: int
    think: int                  # +0x3D
    facing: int                 # +0x3E
    box: Box
    group: int                  # MapObjectMoveSet's answer: the pose group it starts on
    klass: int                  # the 0x6000 bits of its draw word
    anim: AnimState
    twin_data: int | None = None
    twin_anim: AnimState | None = None
    # MapObjectMoveSet's state
    speed: int = 0              # +0x3F
    interval: int = 0           # +0x41
    interval_left: int = 0      # +0x40
    turn_count: int = 0         # +0x42
    look: int = 0               # +0x43
    sight_width: int = 0
    sight_length: int = 0
    length: int = 0             # +0x46
    count: int = 0
    state: int = 0
    facing_kept: int = 0        # +0x4A
    turn_plan: int = 0
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)    # +0x54 left, right, top, bottom
    step_list: int | None = None    # byte offset of its list in the step-list block
    cursor: int = 0             # +0x5A
    busy: int = 0               # +0x56
    goal: tuple[int, int] = (0, 0)  # +0x54, +0x58
    wait_left: int = 0          # +0x54
    extra: dict = field(default_factory=dict)


def move_set(obj: MapObject, d: Definition, tables: FieldTables, step_lists: bytes) -> int:
    """MapObjectMoveSet (0x80065A2C)(row, definition, 0): the think's state;
    -> the pose group the row starts on."""
    mode = obj.think & 0x3F
    ret = 1
    if mode in THINK_LOOKS:
        left = max(obj.x + d.bound_left * 8, 0)
        right = obj.x + (d.bound_right + 1) * 8
        right = 0x7FF if right >= PLANE_LIMIT else right
        top = max(obj.y + d.bound_top * 8, 0)
        bottom = obj.y + (d.bound_bottom + 1) * 8
        bottom = 0x7FF if bottom >= PLANE_LIMIT else bottom
        obj.bounds = (left, right, top, bottom)
        k = d.speed + (2 if 4 <= obj.kind < 7 else 3)
        obj.speed = tables.speed_pixels[k] if k < len(tables.speed_pixels) else 0
        obj.interval = tables.speed_intervals[k] if k < len(tables.speed_intervals) else 0
        (obj.look, obj.sight_width, obj.sight_length, obj.length,
         obj.count) = d.look_set
        obj.state = obj.facing_kept = obj.turn_plan = 0
    elif mode in THINK_STEP_LISTS:
        at = 2 * d.step_list
        if at + 2 > len(step_lists):
            raise ValueError(f"definition {d.index}: step list {d.step_list} is past "
                             f"the {len(step_lists):#x}-byte step lists")
        obj.step_list = struct.unpack_from("<H", step_lists, at)[0]
        if obj.step_list + 2 > len(step_lists):
            raise ValueError(f"definition {d.index}: step list {d.step_list} starts "
                             f"past the step lists")
        obj.speed = obj.interval = 1
        obj.facing_kept = 0
        obj.busy = 0
        obj.cursor = 2
        ret = step_lists[obj.step_list + 1]
    else:
        obj.interval = 1
    obj.interval_left = obj.interval
    return ret


def place_objects(block: bytes, att: Attributes, tables: FieldTables,
                  tables_of: dict[int, AnimTable]) -> list[MapObject]:
    """Every row MapObjectsInit makes of a definition block, as if no event
    flag were set (chests closed). `tables_of` maps a sprite data number to
    its AnimTable (a number missing starts no animation)."""
    step_lists = block[STEP_LISTS_AT:]
    out = []
    for n, d in enumerate(made_definitions(block)):
        kind = d.kind
        sheet = 0 if kind == CHEST_KIND else d.sprite_data
        x, y = d.x << 3, d.y << 3
        obj = MapObject(definition=d, row=n, kind=kind, sprite_data=sheet, mode=d.mode,
                        x=x, y=y, depth=y, layer=d.layer, think=d.think,
                        facing=(d.facing + 1) & 0xFF, box=d.box, group=1,
                        klass=CLASS_UNDER, anim=AnimState())
        obj.group = move_set(obj, d, tables, step_lists)
        obj.klass = class_get(att, 1, OBJECT_TOP, x, y, y, d.box, d.layer)
        pose_set(obj.anim, tables_of.get(sheet, AnimTable((), ())), obj.group, obj.facing)
        if d.sprite_data < TWIN_BELOW:
            if d.sprite_data - 1 >= len(tables.twins):
                raise ValueError(f"definition {d.index}: g_MapTwinSpriteDataNumbers"
                                 f"[{d.sprite_data - 1}] is past the table")
            obj.twin_data = tables.twins[d.sprite_data - 1]
            obj.twin_anim = AnimState()
            pose_set(obj.twin_anim, tables_of.get(obj.twin_data, AnimTable((), ())),
                     obj.group, (d.facing + 1) & 0xFF)
        out.append(obj)
    return out


STORY_FLAG_PEOPLE = 0x580           # MapObjectsInit: kinds 1..3, flag 0x580 + byte 2
STORY_FLAG_OTHERS = 0x680           # ... other kinds, 0x680 + index + (map - 0x65) * 0x80
STORY_MAP_BASE = 0x65
CHEST_FLAG = 0x2620                 # MapObjectInit: the chest's opened flag


def story_flag(d: Definition, map_id: int) -> int | None:
    """The event flag that keeps the definition's object out while set
    (MapObjectsInit), or None when its byte 2 is 0."""
    if d.story_bit == 0:
        return None
    if d.kind < 4:
        return STORY_FLAG_PEOPLE + d.story_bit
    return (d.index + STORY_FLAG_OTHERS + ((map_id - STORY_MAP_BASE) << 7)) & 0xFFFF


def chest_flag(d: Definition, map_id: int) -> int | None:
    """The event flag that shows a chest open (MapObjectInit), or None for
    anything else than a kind-7 definition facing 5 or more."""
    if d.kind != CHEST_KIND or ((d.facing + 1) & 0xFF) < CHEST_OPEN_FROM:
        return None
    base = map_id - 0x35 if map_id > 100 else map_id - 0x15
    return (d.index + CHEST_FLAG + (base << 5)) & 0xFFFF


# ---------------------------------------------------------------------------
# what a chest holds (MapObjectKind7Run)
# ---------------------------------------------------------------------------
#: g_MapObjectKind7Amounts (0x800B4F60): u16 amounts of money, entry
#: byte 0xB - 0xB7.
CHEST_AMOUNTS_ADDR = 0x800B4F60
CHEST_MONEY_FROM = 0xB7             # byte 0xB 1..0xB6 an item, 0xB7..0xEF money,
CHEST_LABEL_FROM = 0xF0             # 0xF0 and up a label of the map's script:
CHEST_LABEL_BASE = 0x230            # byte + 0x230
CHEST_AMOUNTS = CHEST_LABEL_FROM - CHEST_MONEY_FROM
CHEST_LOCKED_FACING = 7             # a chest facing 7 opens only once
CHEST_LOCK_FLAG = 0x267             # this story flag is set


@dataclass(frozen=True)
class ChestContents:
    """What MapObjectKind7Run (0x80067F84) does with a closed chest's
    byte 0xB."""
    what: str           # "empty", "item", "money" or "label"
    number: int         # the item; the amount's entry; the label
    opens: bool         # the chest turns open (all but a label)
    sets_flag: bool     # it sets the chest's flag (`chest_flag`) when opened


def chest_contents(d: Definition) -> ChestContents | None:
    """What examining a kind-7 definition gives, as MapObjectKind7Run
    reads its row: nothing at all for one facing below 5 (an open chest);
    byte 0xB 0 an empty chest (it opens, shows its message and sets no
    flag); 1..0xB6 that item, 0xB7..0xEF the money of entry byte - 0xB7
    of g_MapObjectKind7Amounts, and the chest's flag is set when the
    party takes it; 0xF0 and up runs label byte + 0x230 of the map's
    script (ScriptLabelRun (0x80059FDC)) and leaves the chest as it was."""
    if d.kind != CHEST_KIND or ((d.facing + 1) & 0xFF) < CHEST_OPEN_FROM:
        return None
    ev = d.event
    if ev == 0:
        return ChestContents("empty", 0, True, False)
    if ev >= CHEST_LABEL_FROM:
        return ChestContents("label", ev + CHEST_LABEL_BASE, False, False)
    if ev >= CHEST_MONEY_FROM:
        return ChestContents("money", ev - CHEST_MONEY_FROM, True, True)
    return ChestContents("item", ev, True, True)


def chest_lock_flag(d: Definition) -> int | None:
    """The story flag a chest waits for (MapObjectKind7Run: a row facing 7
    shows a message and stays shut while flag 0x267 is clear), or None."""
    if d.kind != CHEST_KIND or ((d.facing + 1) & 0xFF) != CHEST_LOCKED_FACING:
        return None
    return CHEST_LOCK_FLAG


def chest_amounts(image: bytes) -> tuple[int, ...]:
    """g_MapObjectKind7Amounts as MapObjectKind7Run reads it: the u16
    amount for each byte 0xB7..0xEF, in order."""
    at = address(image, "g_MapObjectKind7Amounts", CHEST_AMOUNTS_ADDR) - EXE_BASE
    if at < 0 or at + 2 * CHEST_AMOUNTS > len(image):
        raise ValueError("EXE image too short to hold g_MapObjectKind7Amounts")
    return struct.unpack_from(f"<{CHEST_AMOUNTS}H", image, at)


# ---------------------------------------------------------------------------
# the party on an entry's spot
# ---------------------------------------------------------------------------
PARTY_BOX_KIND_0 = Box(0, 0, 6, 4)      # MapPartyBoxSet: g_MapPartyKind 0
PARTY_BOX = Box(0, -1, 8, 5)            # ... any other
PARTY_KIND_0_OFFSET = 0xF               # MapPartyRecordInit: id + 0xF while g_MapPartyKind is 0
PARTY_MEMBER_BELOW = 0x1F               # ... kind 1 and a twin below, kind 2 from


def party_box(party_kind: int) -> Box:
    return PARTY_BOX_KIND_0 if party_kind == 0 else PARTY_BOX


@dataclass
class PartyLead:
    """Party place 0 on an entry's spot (MapPartyRecordInit, MapPartyRingFill,
    MapPartyRingFollow)."""
    entry: MapEntry
    member: int                 # the party id drawn
    kind: int                   # MapRecordInit's kind: 1 below 0x1F, else 2
    sprite_data: int            # the id, + 0xF while g_MapPartyKind is 0
    twin_data: int | None       # None while the twin is off
    x: int
    y: int
    depth: int
    facing: int
    klass: int
    anim: AnimState
    twin_anim: AnimState | None


def party_lead(entry: MapEntry, party_kind: int, member: int, att: Attributes,
               tables: FieldTables, tables_of: dict[int, AnimTable]) -> PartyLead:
    """Party place 0 as MapChange leaves it on `entry`'s spot."""
    if member < PARTY_MEMBER_BELOW:
        kind = 1
        twin = tables.twins[member - 1] if 0 < member <= len(tables.twins) else None
    else:
        kind, twin = 2, 0xD
    sheet = member + PARTY_KIND_0_OFFSET if party_kind == 0 else member
    if party_kind == 0 or sheet >= PARTY_MEMBER_BELOW:
        twin = None
    x, y = entry.spot
    table = tables_of.get(sheet, AnimTable((), ()))
    anim = AnimState()
    pose_set(anim, table, 1, 1)                 # MapPartyRecordInit
    twin_anim = None
    if twin is not None:
        twin_anim = AnimState()
        pose_set(twin_anim, tables_of.get(twin, AnimTable((), ())), 1, 1)
    klass = class_get(att, 1, PARTY_TOP, x, y, y, party_box(party_kind), 0)
    pose_set(anim, table, 1, entry.facing)      # MapPartyRingFollow
    if twin_anim is not None:
        pose_set(twin_anim, tables_of.get(twin, AnimTable((), ())), 1, entry.facing)
    return PartyLead(entry=entry, member=member, kind=kind, sprite_data=sheet,
                     twin_data=twin, x=x, y=y, depth=y, facing=entry.facing,
                     klass=klass, anim=anim, twin_anim=twin_anim)

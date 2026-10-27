"""The map object sets: the people, roaming enemies and chests a field map
shows, their sprite data and their pages, read the way the game reads them,
and the palette row each sprite is drawn with (docs/spec/assets/sprites.md
§"Map object sets — the resource and its sprites";
docs/spec/file-sector-map/lunadata-sprites.md).

WHICH RESOURCE — MapObjectsDataLoad (0x80065418) reads resource
`g_MapObjectsDataResourceNumbers[set]` (0x800B4E2C: 0x134 bytes, a u16 for
each set number 0..153, 0 for none). MapChange (0x8005922C) hands
MapObjectsInit (0x800655C8) the set an enter row names: `MapEnterRow`
(map.h), 11 bytes, byte 0 the map entered and byte 1 its object set, rows
1..127 of the table resource_map_enter_table_set (0x80020B8C) copies out
of a map's command 9 (row 0 is never read from the table: MapChange takes a
script's own row for it). `enter_rows` reads those two bytes, so a set is
named by the maps its rows enter.

THE RESOURCE — s32 words at its start, each a byte offset from it:

    [0]    the packed DEFINITION BLOCK, inflated to g_MapObjectDefinitions
           (0x800B8D20): 0x80 MapObjectDefinitions of 0x26 bytes, then from
           byte 0x1300 the step lists (g_MapObjectStepLists (0x800B8BE8) =
           the block + 0x1300, which MapObjectMoveSet (0x80065A2C) reads)
    [1]    the SPRITE DATA LIST: 6-byte MapObjectsSpriteDataRows {u16
           sprite_data, u16 length, u16 place}, ended by a number of 0. For a
           number not yet loaded and below 0x100 the packed block at
           list + place * 4 is inflated into xmalloc_heap_alloc
           (0x80022F4C)(length * 4) and becomes g_MapSpriteDataEntries
           (0x800B8C68)[number]. Entry 0 is then g_SpriteData1 (0x800DDFB0),
           resource 2's chest, whatever the set.
    [2..]  the packed PAGES, ended by a 0 word: sprite_page_list_load
           (0x800182B8) sends page n to sprite page slot n
           (g_SpritePageCorners (0x800A7F88)[n]), 256 8-bit pixels a line
           and 256 lines. A stream may hold fewer lines; the rest of that
           upload is whatever the load buffer held, not this resource.

Every stream is inflate_buffer (0x80021D6C)'s (`inflate16`). A sprite data
block is the layout `sprite_pages` reads (MapRecordSpriteDataSet
(0x800645A8) points a record at its head words 0 to 4); its texel records
already name the set's page slots, since MapObjectsDataLoad calls neither
loader that moves them.

WHICH SPRITE DATA, WHICH PALETTE — MapObjectInit (0x800656CC): a
definition whose byte 1 is not 0 makes an object of kind (byte 0 & 0x3F) + 1
on sprite data byte 1, or on sprite data 0 for kind 7, and for a byte 1
below 0xF a twin on g_MapTwinSpriteDataNumbers (0x80012C00)[byte 1 - 1]
with the same kind and mode. MapRecordInit (0x80065940) gives a record its
draw word by kind and by the mode (byte 3), and sprite_draw (0x8001A528)
draws with palette GetClut(word & 0xFF, 0x1F8 | ((word >> 8) & 3)):

    kind 1          0x2000   row 504       resource 0xE5 (sprite_init)
    kind 2          0x2100   row 505       resource 0xE6 (sprite_init)
    kind 7          0x2370   row 507, x 0x70: resource 2's palette (sprite_reset)
    any other kind  0x2200   row 506       the map's own (`map_palette`)
    mode 1, 2       OR 0x0800, 0x0C00 into the word: no other row
    mode 3          the word is 0x2000 whatever the kind: row 504

A definition's bytes 0, 1 and 3 pick its sprite data and its palette, and
they are all this module reads of it (`object_draws`); where an object
stands, how it moves and what it does are not decoded here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import NamedTuple

from decoders.plugins.SLUS_006_28.formats import command_list
from decoders.plugins.SLUS_006_28.formats.battle_gfx import BattlePage
from decoders.plugins.SLUS_006_28.formats.inflate16 import decompress as inflate16
from decoders.plugins.SLUS_006_28.records.programs import address
from decoders.plugins.SLUS_006_28.formats.sprite_pages import (
    CLUT_BASE_Y, SpriteBlockData, list_poses, parse_actor_block)

EXE_BASE = 0x80011000
#: g_MapObjectsDataResourceNumbers (0x800B4E2C): 0x134 bytes of u16.
SET_RESOURCES_ADDR = 0x800B4E2C
SET_COUNT = 0x134 // 2
#: g_MapTwinSpriteDataNumbers (0x80012C00): read as MapObjectInit reads it,
#: entry byte 1 - 1 for a byte 1 below TWIN_BELOW.
TWIN_NUMBERS_ADDR = 0x80012C00
TWIN_BELOW = 0xF

DEFINITION_SIZE = 0x26
DEFINITION_COUNT = 0x80
STEP_LISTS_AT = DEFINITION_SIZE * DEFINITION_COUNT     # 0x1300
LIST_ROW = 6
SPRITE_DATA_LIMIT = 0x100       # MapObjectsDataLoad: `id < 0x100`
PAGE_WIDTH = 256                # sprite_page_list_load: 0x80 words of 8-bit pixels
PAGE_LINES = 256                # ... by 0x100 lines

#: MapRecordInit: kind 7 is the chest, always on sprite data 0.
CHEST_KIND = 7
CHEST_SPRITE_DATA = 0
DRAW_WORDS = {1: 0x2000, 2: 0x2100, 7: 0x2370}
DRAW_WORD_OTHER = 0x2200
MODE_BITS = {1: 0x0800, 2: 0x0C00}
MODE_PALETTE_504 = 3
#: Palette rows (VRAM y) a field sprite can be drawn with.
ROW_KIND_1, ROW_KIND_2, ROW_MAP, ROW_CHEST = 504, 505, 506, 507

#: MapEnterRow: rows 1..127 of the 0x580-byte table (GameStart puts the next
#: table at g_MapEnterTable + 0x580).
ENTER_COMMAND = 9
ENTER_ROW = 11
ENTER_ROWS = 0x580 // ENTER_ROW

#: resource_palette_load (0x80020A08): a type-4 command of sub-number 1..0x7F
#: goes through palette_bit15_set (0x800207E8) to palette_rows_set
#: (0x8002061C)(6, 1, buf): row 0x1F4 + 6.
MAP_PALETTE_SUBS = range(1, 0x80)
PALETTE_BYTES = 512


def set_resources(image: bytes) -> dict[int, int]:
    """g_MapObjectsDataResourceNumbers: set number -> resource, the sets that
    name one (a 0 word names none)."""
    at = address(image, "g_MapObjectsDataResourceNumbers", SET_RESOURCES_ADDR) - EXE_BASE
    if at + 2 * SET_COUNT > len(image):
        raise ValueError("EXE image too short to hold g_MapObjectsDataResourceNumbers")
    words = struct.unpack_from(f"<{SET_COUNT}H", image, at)
    return {n: r for n, r in enumerate(words) if r}


def twin_numbers(image: bytes, count: int = TWIN_BELOW - 1) -> bytes:
    """g_MapTwinSpriteDataNumbers as MapObjectInit indexes it: the `count`
    bytes from its address (entry n - 1 for sprite data n)."""
    at = address(image, "g_MapTwinSpriteDataNumbers", TWIN_NUMBERS_ADDR) - EXE_BASE
    out = bytes(image[at:at + count])
    if len(out) != count:
        raise ValueError("EXE image too short to hold g_MapTwinSpriteDataNumbers")
    return out


# ---------------------------------------------------------------------------
# the resource
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SetHeader:
    """The s32 words an object-set resource starts with."""
    definitions: int            # [0] the packed definition block
    sprite_data_list: int       # [1] the sprite data list
    pages: tuple[int, ...]      # [2..] the packed pages, page n = slot n


def set_header(raw: bytes) -> SetHeader:
    """MapObjectsDataLoad reads words 0 and 1; sprite_page_list_load walks
    the pages from word 2 to a 0 word. The words sit in front of what they
    point at, so a walk that reaches the lowest offset named without a 0
    word is an error: the game would be taking packed data for an offset."""
    if len(raw) < 12:
        raise ValueError("object-set resource shorter than its header")
    defs, lst = struct.unpack_from("<2I", raw, 0)
    limit = min([len(raw), *(o for o in (defs, lst) if o)])
    pages, at = [], 8
    while True:
        if at + 4 > limit:
            raise ValueError(f"page list not ended by a 0 word before {limit:#x}")
        word = struct.unpack_from("<I", raw, at)[0]
        if word == 0:
            break
        pages.append(word)
        limit = min(limit, word)
        at += 4
    return SetHeader(defs, lst, tuple(pages))


class SpriteDataRow(NamedTuple):
    """One MapObjectsSpriteDataRow."""
    number: int         # the g_MapSpriteDataEntries index a definition's byte 1 names
    length: int         # the inflated block's length, 4-byte units
    place: int          # the packed block's start, 4-byte units from the list


def sprite_data_rows(raw: bytes) -> list[SpriteDataRow]:
    """The set's sprite data list, in file order, to its 0 number."""
    at = set_header(raw).sprite_data_list
    out = []
    while at + LIST_ROW <= len(raw):
        row = SpriteDataRow(*struct.unpack_from("<3H", raw, at))
        if row.number == 0:
            return out
        out.append(row)
        at += LIST_ROW
    raise ValueError("sprite data list runs off the resource without a 0 number")


def sprite_data(raw: bytes, row: SpriteDataRow) -> bytes:
    """One listed block as MapObjectsDataLoad unpacks it: the stream at
    list + place * 4, cut to its `length * 4`-byte allocation. A stream that
    gives fewer bytes is an error (the rest would be the heap's)."""
    at = set_header(raw).sprite_data_list + row.place * 4
    if not 0 < at < len(raw):
        raise ValueError(f"sprite data {row.number}: place {at:#x} is outside "
                         f"the {len(raw):#x}-byte resource")
    out = inflate16(raw[at:])
    if len(out) < row.length * 4:
        raise ValueError(f"sprite data {row.number}: inflated {len(out)} bytes, "
                         f"the loader allocates {row.length * 4}")
    return bytes(out[:row.length * 4])


def definition_block(raw: bytes) -> bytes:
    """The inflated block at word 0, whole: the 0x80 definitions, then the
    step lists from byte 0x1300."""
    block = inflate16(raw[set_header(raw).definitions:])
    if len(block) < STEP_LISTS_AT:
        raise ValueError(f"definition block is {len(block):#x} bytes, "
                         f"the 0x80 definitions take {STEP_LISTS_AT:#x}")
    return bytes(block)


def set_pages(raw: bytes) -> list[BattlePage]:
    """The set's pages, page n for sprite page slot n, each with the whole
    lines its stream holds, at most 256."""
    out = []
    for n, off in enumerate(set_header(raw).pages):
        if not 0 < off < len(raw):
            raise ValueError(f"page {n}: offset {off:#x} is outside the "
                             f"{len(raw):#x}-byte resource")
        px = inflate16(raw[off:])
        lines = min(len(px) // PAGE_WIDTH, PAGE_LINES)
        out.append(BattlePage(index=n, lines=lines, pixels=bytes(px[:lines * PAGE_WIDTH])))
    return out


@dataclass(frozen=True)
class ObjectSet:
    """An object-set resource, as MapObjectsDataLoad and sprite_page_list_load
    take it. `blocks` is the registry an empty g_MapSpriteDataEntries gets:
    the first row of a number wins, numbers from 0x100 are not loaded."""
    header: SetHeader
    definitions: bytes                  # `definition_block`
    rows: tuple[SpriteDataRow, ...]
    blocks: dict[int, bytes]
    pages: tuple[BattlePage, ...]

    @property
    def step_lists(self) -> bytes:
        return self.definitions[STEP_LISTS_AT:]

    def actor(self, number: int) -> SpriteBlockData | None:
        blk = self.blocks.get(number)
        return parse_actor_block(blk) if blk is not None else None

    @property
    def page_lines(self) -> dict[int, int]:
        return {p.index: p.lines for p in self.pages}


def parse_object_set(raw: bytes, pages: bool = True) -> ObjectSet:
    """Everything MapObjectsDataLoad and sprite_page_list_load take from the
    resource (`pages=False` leaves the pages packed)."""
    rows = sprite_data_rows(raw)
    blocks: dict[int, bytes] = {}
    for row in rows:
        if row.number < SPRITE_DATA_LIMIT and row.number not in blocks:
            blocks[row.number] = sprite_data(raw, row)
    return ObjectSet(header=set_header(raw), definitions=definition_block(raw),
                     rows=tuple(rows), blocks=blocks,
                     pages=tuple(set_pages(raw)) if pages else ())


# ---------------------------------------------------------------------------
# which sprite data, which palette
# ---------------------------------------------------------------------------
class Draw(NamedTuple):
    """The two words MapRecordInit gives a record."""
    word: int           # sprite.flags (+0x0E): the draw word
    attr: int           # sprite.attr (+0x0C)

    @property
    def palette_row(self) -> int:
        """sprite_draw's GetClut y: 0x1F8 | ((word >> 8) & 3)."""
        return CLUT_BASE_Y | ((self.word >> 8) & 3)

    @property
    def palette_x(self) -> int:
        """sprite_draw's GetClut x: the word's low byte."""
        return self.word & 0xFF

    @property
    def semi(self) -> bool:
        """`((word >> 10) | (attr >> 15)) & 1`: drawn semi-transparent."""
        return bool(((self.word >> 10) | (self.attr >> 15)) & 1)


def record_draw(kind: int, mode: int) -> Draw:
    """MapRecordInit(record, kind, mode, ...): the draw and attribute words
    (before MapAttributeClassGet's bits 0x6000, which pick no palette)."""
    word = DRAW_WORDS.get(kind, DRAW_WORD_OTHER)
    attr = 0 if kind == CHEST_KIND else 0x20
    if mode in MODE_BITS:
        word |= MODE_BITS[mode]
    elif mode == MODE_PALETTE_504:
        word = 0x2000
        attr |= 0x8000
    return Draw(word, attr)


class ObjectDraw(NamedTuple):
    """What one definition draws once made (MapObjectInit)."""
    definition: int     # its index, 0..0x7F
    kind: int           # (byte 0 & 0x3F) + 1
    mode: int           # byte 3
    sprite_data: int    # byte 1, or 0 for kind 7
    twin: int | None    # the twin's sprite data, None for no twin
    draw: Draw          # the row's and the twin's


def object_draws(definitions: bytes, twins: bytes) -> list[ObjectDraw]:
    """Every definition MapObjectsInit can make (byte 1 not 0; whether a
    story bit holds it back is the running game's), with its sprite data,
    its twin's, and its draw words. `twins` is `twin_numbers(image)`."""
    out = []
    for i in range(DEFINITION_COUNT):
        d = definitions[i * DEFINITION_SIZE:(i + 1) * DEFINITION_SIZE]
        if len(d) < DEFINITION_SIZE or d[1] == 0:
            continue
        kind = (d[0] & 0x3F) + 1
        twin = None
        if d[1] < TWIN_BELOW:
            if d[1] - 1 >= len(twins):
                raise ValueError(f"definition {i}: g_MapTwinSpriteDataNumbers"
                                 f"[{d[1] - 1}] is past the bytes given")
            twin = twins[d[1] - 1]
        out.append(ObjectDraw(definition=i, kind=kind, mode=d[3],
                              sprite_data=CHEST_SPRITE_DATA if kind == CHEST_KIND else d[1],
                              twin=twin, draw=record_draw(kind, d[3])))
    return out


def sprite_data_draws(draws: list[ObjectDraw]) -> dict[int, list[tuple[ObjectDraw, bool]]]:
    """sprite data number -> [(the definition drawing it, as its twin?)]."""
    out: dict[int, list[tuple[ObjectDraw, bool]]] = {}
    for d in draws:
        out.setdefault(d.sprite_data, []).append((d, False))
        if d.twin is not None:
            out.setdefault(d.twin, []).append((d, True))
    return out


# ---------------------------------------------------------------------------
# the map's side: its enter rows and its palette row
# ---------------------------------------------------------------------------
class EnterRow(NamedTuple):
    """Bytes 0 and 1 of a MapEnterRow."""
    index: int          # its row in the table, 1..127
    map: int            # map_number: the map entered
    object_set: int     # the set it is entered with, 0 for none


def enter_rows(map_raw: bytes) -> list[EnterRow]:
    """Rows 1..127 of a map's enter table (the command-9 payload in effect),
    those that name a map."""
    cmd = command_list.effective(map_raw, ENTER_COMMAND)
    if cmd is None:
        return []
    out = []
    for i in range(1, ENTER_ROWS):
        row = cmd.payload[i * ENTER_ROW:(i + 1) * ENTER_ROW]
        if len(row) < ENTER_ROW:
            break
        if row[0]:
            out.append(EnterRow(i, row[0], row[1]))
    return out


def palette_bit15_set(cols: bytes, count: int = 0x100, mask: int = 0xFF) -> bytes:
    """palette_bit15_set (0x800207E8): colour i with `i & mask` 0 becomes 0,
    every other colour gets bit 15."""
    out = bytearray(cols[:2 * count].ljust(2 * count, b"\0"))
    for i in range(count):
        if i & mask:
            out[2 * i + 1] |= 0x80
        else:
            out[2 * i:2 * i + 2] = b"\0\0"
    return bytes(out)


def map_palette(map_raw: bytes) -> bytes | None:
    """Palette row 506 as the map's resource leaves it: the last type-4
    command of sub-number 1..0x7F, inflated and through palette_bit15_set;
    None for a map with none."""
    found = [c for c in command_list.commands(map_raw)
             if c.type == command_list.PALETTE and c.arg in MAP_PALETTE_SUBS]
    if not found:
        return None
    return palette_bit15_set(inflate16(found[-1].payload))


def undrawn_slices(data: SpriteBlockData, page_lines: dict[int, int],
                   width: int = PAGE_WIDTH) -> list[tuple[int, int, str]]:
    """(pose, piece, why) for each textured piece of a drawable pose whose
    texels are not all on a page `page_lines` ({slot: lines}) holds: what
    `sprite_pages.compose_pose` leaves out. The game draws such a piece
    from video memory, where the texels past a page are another page's or
    stale."""
    out = []
    for pose in list_poses(data):
        for i in range(pose.first, pose.first + pose.count):
            s = data.slice(i)
            if s is None or not (s.w and s.h) or s.corners() is None:
                continue
            d = data.descriptor(s.desc)
            if d is None:
                out.append((pose.index, i, f"texel record {s.desc} is outside the block"))
                continue
            slot, u, v = d
            if slot not in page_lines:
                out.append((pose.index, i, f"page slot {slot} is not the set's"))
            elif u + s.w > width:
                out.append((pose.index, i, f"u {u} + w {s.w} runs past the "
                                           f"page's {width} columns"))
            elif v + s.h > page_lines[slot]:
                out.append((pose.index, i, f"v {v} + h {s.h} runs past the "
                                           f"{page_lines[slot]} lines of page {slot}"))
    return out

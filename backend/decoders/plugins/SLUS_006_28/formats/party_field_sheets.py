"""The party's field sprite sheets — LUNADATA resource 0x1E8 — and the
palette rows the field draws them with (docs/spec/assets/sprites.md §"The
party's field sheets — resource 0x1E8").

The battle's party is `battle_gfx` (resource 0x197). This is the field's:
the party members as they walk the maps.

THE DIRECTORY — MapPartySpriteDataLoad (0x80063D48) and
MapPartySpriteDataReload (0x800642A4) read resource 0x1E8 whole into
g_ResourceReadBuffer and index it by 8-byte SpriteDirectoryRows (sprite.h),
every field in 4-byte units:

    +0  data_length    the sprite data block: xmalloc_heap_alloc
                       (0x80022F4C)(data_length * 4)
    +2  data_place     its packed stream, from the directory's start
    +4  image_length   its picture, 64 to a line of 256 8-bit pixels:
                       sprite_page_image_add (0x8001808C) and
                       sprite_page4_image_load (0x80017EB0) send
                       image_length / 64 lines
    +6  image_place    the packed picture

Both streams are inflate_buffer (0x80021D6C)'s. The block is the layout
`sprite_pages` reads (MapRecordSpriteDataSet (0x800645A8) points a record
at its head words 0 to 4). On the disc its texel records name page 0 with
v from the picture's top: the two page loaders set the page slot and add
the line they placed the picture at, so a sheet composes against its own
picture.

WHICH ROWS — per party place, id = the low byte of g_PartyIds
(0x800B8BC0)[place] (the numbers the battle's slots take too), up to the
first 0, each loaded only while its g_MapSpriteDataEntries (0x800B8C68)
entry is empty (a map's object set may have loaded the number first):

    own     sprite data `id`, row id - 1 (row 0x1E for id 0xCE), to page
            slot 5 or 6 (sprite_page_image_add)
    kind 0  sprite data id + 0xF, row id + 0xE: only for an id below 0x1F,
            only while g_MapPartyKind (0x800B8CEE) is 0, to page slot 4
            (sprite_page4_image_load). MapSet (0x80068780) sets
            g_MapPartyKind from byte 0 of the map's area record
    twin    sprite data g_MapTwinSpriteDataNumbers (0x80012C00)[id - 1],
            row that number - 1: only for an id below 0x1F

MapPartyRecordInit (0x800649DC) puts the member on `id`, or on id + 0xF
while g_MapPartyKind is 0, and its twin, a copy of the member's record, on
the twin sprite data; the twin stays on only while g_MapPartyKind is not 0
and the id is below 0x1F. MapPartyAnimationStep (0x80065CF8) keeps the twin
on the member's animation and draws it as sprite 0x46 + place, behind the
bodies; the code never says what it shows.

THE COLOURS — MapPartyRecordInit gives a member kind 1 below 0x1F and kind 2
from 0x1F up, and its twin kind 1; MapRecordInit (0x80065940) makes those
the draw words 0x2000 and 0x2100, which sprite_draw (0x8001A528) draws with
palette rows 504 and 505 (`map_object_sets.record_draw`). On the field
those rows are resources 0xE5 and 0xE6 through sprite_init (0x80018BFC)'s
fix-up (`sprite_pages.sprite_init_palette`),
sent again by sprite_init_copy (0x80063B10) at game start and after every
battle (MapBtlRun (0x8007AE58)); during a fight row 504 holds the battle
party's palette (BtlPartyDataLoad (0x80018A78)).

What the code does not say: what the twin shows, and who id 0xCE is.

This module reads bytes handed to it — the resource and, for the twin
numbers, the EXE image.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import NamedTuple

from decoders.plugins.SLUS_006_28.formats.battle_gfx import BattlePage
from decoders.plugins.SLUS_006_28.formats.inflate16 import decompress as inflate16
from decoders.plugins.SLUS_006_28.records.programs import address
from decoders.plugins.SLUS_006_28.formats.map_object_sets import record_draw
from decoders.plugins.SLUS_006_28.formats.sprite_pages import (
    SpriteBlockData, parse_actor_block)

#: MapPartySpriteDataLoad / MapPartySpriteDataReload's literal.
DIRECTORY_RESOURCE = 0x1E8
ROW_BYTES = 8
PAGE_WIDTH = 256                # 0x80 words of 8-bit pixels
LINE_UNITS = 64                 # image_length / 64 lines

#: `id += 0xF`: the sheet a member wears while g_MapPartyKind is 0.
KIND_0_OFFSET = 0xF
#: `id < 0x1F`: the ids that get a kind-0 sheet and a twin, and kind 1.
MEMBER_LIMIT = 0x1F
#: `if (id == 0xCE) n = 0x1E; else n = id - 1;`
ID_CE = 0xCE
ID_CE_ROW = 0x1E

EXE_BASE = 0x80011000
#: g_MapTwinSpriteDataNumbers (0x80012C00): 12 bytes, one per id 1..12.
TWIN_NUMBERS_ADDR = 0x80012C00
TWIN_NUMBERS_COUNT = 12

#: MapPartyRecordInit's kinds: the member's below 0x1F and from 0x1F up,
#: and the twin's (always 1).
KIND_MEMBER, KIND_OTHER = 1, 2


@dataclass(frozen=True)
class DirectoryRow:
    """One SpriteDirectoryRow of resource 0x1E8."""
    index: int
    data_length: int            # +0
    data_place: int             # +2
    image_length: int           # +4
    image_place: int            # +6

    @property
    def lines(self) -> int:
        """The picture's lines: `image_length / 64`."""
        return self.image_length // LINE_UNITS


def row_count(buf: bytes) -> int:
    """How many rows the directory holds.

    The code never bounds a row (it is id - 1 off a party id); the rows run
    up to the first packed stream, so the count is read from the layout:
    rows are taken while they end at or before the lowest place any row so
    far names."""
    limit, n = len(buf), 0
    while (n + 1) * ROW_BYTES <= limit:
        _dl, dp, _il, ip = struct.unpack_from("<4H", buf, n * ROW_BYTES)
        if dp == 0 and ip == 0:
            break
        for place in (dp, ip):
            if place:
                limit = min(limit, place * 4)
        n += 1
    return n


def parse_directory(buf: bytes) -> list[DirectoryRow]:
    return [DirectoryRow(i, *struct.unpack_from("<4H", buf, i * ROW_BYTES))
            for i in range(row_count(buf))]


def sprite_data_row(number: int) -> int:
    """The directory row a sprite data number loads from: number - 1, row
    0x1E for 0xCE (the own and kind-0 loads; the twin load is number - 1
    with no test, and no twin number is 0xCE)."""
    if number < 1:
        raise ValueError("sprite data numbers count from 1; 0 is an empty place")
    return ID_CE_ROW if number == ID_CE else number - 1


def _inflate_exact(buf: bytes, place: int, size: int, what: str) -> bytes:
    if not 0 < place < len(buf):
        raise ValueError(f"{what}: place {place:#x} is outside the {len(buf):#x}-byte resource")
    out = inflate16(buf[place:])
    if len(out) < size:
        raise ValueError(f"{what}: inflated {len(out)} bytes, the loader takes {size}")
    return bytes(out[:size])


@dataclass(frozen=True)
class FieldSheet:
    """One row's sprite data and picture, as the loaders unpack them."""
    number: int                 # the sprite data number it is registered under
    row: int
    block: bytes
    picture: BattlePage

    def actor(self) -> SpriteBlockData | None:
        return parse_actor_block(self.block)


def load_sheet(buf: bytes, number: int) -> FieldSheet:
    """Sprite data `number` and its picture, as MapPartySpriteDataLoad and
    sprite_page_image_add unpack them. A row past the directory is an error:
    the game would read packed data as a row there."""
    row = sprite_data_row(number)
    if row >= row_count(buf):
        raise ValueError(f"sprite data {number:#x}: row {row} is past the directory")
    d = DirectoryRow(row, *struct.unpack_from("<4H", buf, row * ROW_BYTES))
    block = _inflate_exact(buf, d.data_place * 4, d.data_length * 4,
                           f"sprite data {number:#x}")
    pixels = _inflate_exact(buf, d.image_place * 4, PAGE_WIDTH * d.lines,
                            f"sprite data {number:#x} picture")
    return FieldSheet(number=number, row=row, block=block,
                      picture=BattlePage(index=0, lines=d.lines, pixels=pixels))


def twin_numbers(image: bytes) -> bytes:
    """g_MapTwinSpriteDataNumbers: the twin sprite data of ids 1..12."""
    at = address(image, "g_MapTwinSpriteDataNumbers", TWIN_NUMBERS_ADDR) - EXE_BASE
    out = bytes(image[at:at + TWIN_NUMBERS_COUNT])
    if len(out) != TWIN_NUMBERS_COUNT:
        raise ValueError("EXE image too short to hold g_MapTwinSpriteDataNumbers")
    return out


def twin_number(twins: bytes, member: int) -> int:
    """`g_MapTwinSpriteDataNumbers[id - 1]`. The loaders admit ids up to
    0x1E and would read past the 12 entries; this answers the 12."""
    if not 1 <= member <= len(twins):
        raise ValueError(f"id {member}: g_MapTwinSpriteDataNumbers holds ids 1..{len(twins)}")
    return twins[member - 1]


def member_kind(member: int) -> int:
    """MapPartyRecordInit: kind 1 below 0x1F, kind 2 from 0x1F up."""
    return KIND_MEMBER if member < MEMBER_LIMIT else KIND_OTHER


class PartyUse(NamedTuple):
    """One way MapPartyRecordInit (0x800649DC) puts a party record or its
    twin on a sprite data number."""
    member: int         # the party id
    which: str          # "own", "party-kind-0" or "twin"
    kind: int           # the kind it hands MapRecordInit (0x80065940)


def party_uses(twins: bytes, members) -> dict[int, list[PartyUse]]:
    """sprite data number -> the party ids in `members` that wear it:
    `id` (kind 1 below 0x1F, 2 from 0x1F up) while g_MapPartyKind is not 0,
    id + 0xF while it is 0 (kind 1: the kind is chosen before the add) and,
    below 0x1F, the twin (kind 1). `twins` is `twin_numbers(image)`."""
    out: dict[int, list[PartyUse]] = {}
    for m in members:
        out.setdefault(m, []).append(PartyUse(m, "own", member_kind(m)))
        if m < MEMBER_LIMIT:
            out.setdefault(m + KIND_0_OFFSET, []).append(
                PartyUse(m, "party-kind-0", KIND_MEMBER))
            out.setdefault(twin_number(twins, m), []).append(
                PartyUse(m, "twin", KIND_MEMBER))
    return out


@dataclass(frozen=True)
class MemberSheets:
    """Every sheet the field loads for one party id: `own` always, and for
    an id below 0x1F `kind_0` (worn while g_MapPartyKind is 0) and `twin`
    (drawn while it is not). The member is drawn with its kind's palette
    row, the twin with row 504 (kind 1) whatever the member's."""
    member: int
    own: FieldSheet
    kind_0: FieldSheet | None = None
    twin: FieldSheet | None = None

    @property
    def kind(self) -> int:
        return member_kind(self.member)

    @property
    def palette_row(self) -> int:
        """MapRecordInit(record, kind, 0, ...)'s row: 504 or 505."""
        return record_draw(self.kind, 0).palette_row

    @property
    def twin_palette_row(self) -> int:
        return record_draw(KIND_MEMBER, 0).palette_row

    def worn(self, party_kind: int) -> FieldSheet | None:
        """The sheet MapPartyRecordInit puts the member on: id + 0xF while
        g_MapPartyKind is 0. That add is made for any id; the loaders load
        an id + 0xF sheet only below 0x1F, so None is the case this path
        does not load."""
        return self.kind_0 if party_kind == 0 else self.own

    def twin_drawn(self, party_kind: int) -> bool:
        return party_kind != 0 and self.member < MEMBER_LIMIT


def member_sheets(buf: bytes, member: int, twins: bytes) -> MemberSheets:
    """Every sheet MapPartySpriteDataLoad loads for party id `member`.
    `twins` is `twin_numbers(image)`."""
    own = load_sheet(buf, member)
    if member >= MEMBER_LIMIT:
        return MemberSheets(member=member, own=own)
    return MemberSheets(member=member, own=own,
                        kind_0=load_sheet(buf, member + KIND_0_OFFSET),
                        twin=load_sheet(buf, twin_number(twins, member)))


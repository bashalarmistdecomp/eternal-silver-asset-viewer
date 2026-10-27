"""Map areas — the location, party kind and music each map has, and which
LUNADATA resource holds the map, from the EXE's own tables
(docs/spec/text.md §"Locations").

Every map entry runs MapSet(map_id, music, b8) (0x80068780):

    g_MapNumber (0x800B8CDC) = map_id
    rec = MapTblGet(map_id) (0x80068618)
        = g_MapTbls (0x800B5238) + 16 * (map_id < 0xA0 ? g_MapTblNumbers[map_id] (0x800B5198) : 0)
    g_MapPartyKind (0x800B8CEE) = rec[0]          the party kind (0/1/2): how the
                                 party walks the map. 0: each member takes
                                 sprite data number + 0xF and no twin
                                 (MapPartyRecordInit (0x800649DC)), one walk
                                 step a frame (MapPartyBoxSet (0x8006497C)),
                                 and MapLoad (0x80068A10) keeps 8 colours of
                                 the overlay rows, not 10; 2: members 1 to 5
                                 are switched off (MapPartyRecordsInit
                                 (0x80064898)). ScriptCommandMapPartyKindSet
                                 changes it on the map
    g_MapPlaceName (0x800B8CD8) = rec[6]          the location id — named by string 0x400 + id;
                                 0x51..0x64 (the towns) also set visited flag
                                 id + 0x28A
    g_MusicNumber (0x800B8CE6) = rec[0xF]        the BGM number (records.music), unless the
                                 caller passes one (music != 0xFF); party
                                 kind 0 with music 6 plays 7 once story bit
                                 0x3C1 is set

and the map's file comes from MapSeek (0x8006891C) -> MapResourceFind (0x80020CD0) =
resource_pair_find (0x80020C58)(g_MapResourcePairs (0x800AF364), map_id): (s16 map id, s16 resource) pairs, the
first match wins, the list ends at a resource of 0. The resource is a
general resource_table index; its map file's header byte 19 repeats the
map id.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .programs import address

EXE_BASE = 0x80011000
AREA_INDEX_ADDR = 0x800B5198    # g_MapTblNumbers (0x800B5198): u8 per map id < 0xA0
AREA_INDEX_COUNT = 0xA0
AREA_RECORD_ADDR = 0x800B5238   # g_MapTbls (0x800B5238): 16-byte area records
AREA_RECORD = 0x10
MAP_FILES_ADDR = 0x800AF364     # g_MapResourcePairs (0x800AF364): (s16 map id, s16 resource) pairs
TOWN_FIRST, TOWN_COUNT = 0x51, 0x14     # MapSet (0x80068780): id - 0x51 < 0x14
VISITED_FLAG_BASE = 0x28A               # ... sets flag id + 0x28A
LOCATION_STRING_BASE = 0x400            # MenuCardListDisp (0x800734F0): g_MapPlaceName (0x800B8CD8) + 0x400


@dataclass(frozen=True)
class Area:
    """The area record MapSet (0x80068780) copies for a map."""
    map_id: int
    record: int             # index into g_MapTbls (0x800B5238)
    party_kind: int         # +0x00 -> g_MapPartyKind (0x800B8CEE)
    tile_animation: int     # +0x04 -> tile_animation_set (0x800265BC), from MapLoad (0x80068A10)
    palette_animation: int  # +0x05 -> palette_animation_set (0x800262FC), from MapLoad
    location: int           # +0x06 -> g_MapPlaceName (0x800B8CD8)
    script: int             # +0x08 -> ScriptChange (0x80068D7C), from MapLoad (0x80068A10)
    effect: int             # +0x0B -> g_MapEffect: the second layer's mode and scroll (MapEffectSet (0x80068AC0))
    bgm: int                # +0x0F -> g_MusicNumber (0x800B8CE6)
    raw: bytes

    @property
    def is_town(self) -> bool:
        """The ids MapSet (0x80068780) marks visited (the travel menu's towns)."""
        return TOWN_FIRST <= self.location < TOWN_FIRST + TOWN_COUNT


def area_record_index(image: bytes, map_id: int) -> int:
    """MapTblGet (0x80068618)'s index: g_MapTblNumbers[map_id] (0x800B5198), or 0 from 0xA0 up."""
    if not 0 <= map_id < AREA_INDEX_COUNT:
        return 0
    return image[address(image, "g_MapTblNumbers", AREA_INDEX_ADDR) - EXE_BASE + map_id]


def area(image: bytes, map_id: int) -> Area:
    """The record MapSet (0x80068780) reads when map `map_id` is entered."""
    idx = area_record_index(image, map_id)
    off = address(image, "g_MapTbls", AREA_RECORD_ADDR) - EXE_BASE + idx * AREA_RECORD
    raw = bytes(image[off:off + AREA_RECORD])
    return Area(map_id=map_id, record=idx, party_kind=raw[0], tile_animation=raw[4],
                palette_animation=raw[5], location=raw[6],
                script=raw[8], effect=raw[0x0B], bgm=raw[0x0F], raw=raw)


def map_resources(image: bytes) -> dict[int, int]:
    """resource_pair_find (0x80020C58) over g_MapResourcePairs (0x800AF364): map id -> resource, first match wins."""
    out: dict[int, int] = {}
    off = address(image, "g_MapResourcePairs", MAP_FILES_ADDR) - EXE_BASE
    while off + 4 <= len(image):
        map_id, res = struct.unpack_from("<hh", image, off)
        if res == 0:
            break
        out.setdefault(map_id, res)
        off += 4
    return out


def map_resource(image: bytes, map_id: int) -> int | None:
    """The general resource holding map `map_id`; None = resource_pair_find (0x80020C58)'s -1."""
    return map_resources(image).get(map_id)


def maps(image: bytes) -> list[tuple[int, int, Area]]:
    """Every loadable map: (map id, resource, area), by map id."""
    return [(mid, res, area(image, mid)) for mid, res in sorted(map_resources(image).items())]

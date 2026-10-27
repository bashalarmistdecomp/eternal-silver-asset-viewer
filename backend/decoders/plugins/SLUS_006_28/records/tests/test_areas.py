"""Tier 1 for map areas — a synthetic EXE image, no game data.

What this CAN catch: MapTblGet (0x80068618)'s indirection (g_MapTblNumbers (0x800B5198) below 0xA0,
record 0 from 0xA0 up), which record bytes MapSet (0x80068780) takes (0 kind,
6 location, 0xF music), the bytes MapLoad (0x80068A10) hands on (4 the tile
animation, 5 the palette animation, 8 the script) and the effect byte MapEffectSet (0x80068AC0) reads (0xB), and resource_pair_find (0x80020C58)'s walk (first match wins, a
resource of 0 ends the list).

What it CANNOT catch: whether those are this program's tables — only
re-reading MapSet / resource_pair_find does that. See
decoders/testing.py.
"""

import struct

from decoders.plugins.SLUS_006_28.records import areas as ar


def _image(index: dict[int, int], records: dict[int, bytes], pairs: list[tuple[int, int]]) -> bytes:
    img = bytearray(ar.AREA_RECORD_ADDR - ar.EXE_BASE + 0x400)
    for mid, idx in index.items():
        img[ar.AREA_INDEX_ADDR - ar.EXE_BASE + mid] = idx
    for idx, rec in records.items():
        o = ar.AREA_RECORD_ADDR - ar.EXE_BASE + idx * ar.AREA_RECORD
        img[o:o + len(rec)] = rec
    o = ar.MAP_FILES_ADDR - ar.EXE_BASE
    for mid, res in pairs + [(0, 0)]:
        struct.pack_into("<hh", img, o, mid, res)
        o += 4
    return bytes(img)


REC = bytes([1, 0, 0, 0x15, 3, 7, 0x51, 0, 0x2C, 0, 0, 0x41, 0, 0, 0, 8])


def test_area_reads_the_indexed_record():
    img = _image({0x15: 3}, {3: REC}, [])
    a = ar.area(img, 0x15)
    assert (a.record, a.party_kind, a.location, a.script, a.bgm) == (3, 1, 0x51, 0x2C, 8)
    assert a.effect == 0x41
    assert (a.tile_animation, a.palette_animation) == (3, 7)
    assert a.is_town


def test_ids_from_0xa0_use_record_zero():
    img = _image({}, {0: bytes([2] + [0] * 15)}, [])
    assert ar.area_record_index(img, 0xA0) == 0
    assert ar.area(img, 0xC8).party_kind == 2


def test_map_resources_first_match_and_terminator():
    img = _image({}, {}, [(0x01, 4), (0x15, 0x18), (0x01, 99)])
    assert ar.map_resources(img) == {0x01: 4, 0x15: 0x18}
    assert ar.map_resource(img, 0x02) is None
    assert [m for m, _r, _a in ar.maps(img)] == [0x01, 0x15]

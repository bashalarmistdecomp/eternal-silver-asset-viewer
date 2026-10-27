"""Tier 1 for sound effects: a made-up image and made-up banks, no game data.

What this CAN catch: SoundPlay (0x800555F0)'s branches as transcribed (the
common numbers and the two that play two lower, the battle's numbers and
the two it plays otherwise, a refused number, a place's own number found
and not found in g_SoundIds), sound_effect_play (0x80024514)'s limits, and
how sound_area_get (0x80024784) and sound_pair_find (0x80023E5C) give a
map its bank (the last pair's for an area no pair names).

What it CANNOT catch: whether the tables are at those addresses in the
program, or whether a sequence sounds as the game plays it (the on-disc
tests). See decoders/testing.py.
"""

import struct

from decoders.plugins.SLUS_006_28.records import sound_effects as se

COMMON, BATTLE = se.COMMON_BANK, 358


def _image(areas: dict[int, int], pairs: list[tuple[int, int]]) -> bytes:
    img = bytearray(se.MAP_AREAS_ADDR - se.EXE_BASE + se.MAP_AREAS_COUNT + 16)
    for m, a in areas.items():
        img[se.MAP_AREAS_ADDR - se.EXE_BASE + m] = a
    at = se.PAIRS_ADDR - se.EXE_BASE
    for i, (a, r) in enumerate(pairs + [(0, 0)]):
        struct.pack_into("<hh", img, at + 4 * i, a, r)
    return bytes(img)


#: map 5 is area 2 (bank 300), map 7 area 3 (bank 301), map 8 area 9, which
#: no pair names; the battle's bank is the last pair's
TABLES = se.tables(_image({5: 2, 7: 3, 8: 9}, [(2, 300), (3, 301), (0, BATTLE)]))


def _bank_with_ids(ids) -> bytes:
    payload = struct.pack(f"<{se.IDS_COUNT}H", *(list(ids) + [0] * (se.IDS_COUNT - len(ids))))
    return struct.pack("<II", se.SOUND_IDS_COMMAND, len(payload)) + payload + bytes(8)


def _at(n, m, ids=()):
    p = se.play(TABLES, n, m, ids)
    return None if p is None else (p.bank, p.sequence, p.refused)


def test_a_map_has_its_areas_bank_and_a_battle_the_last_pairs():
    assert (TABLES.bank(5), TABLES.bank(7)) == (300, 301)
    assert TABLES.bank(8) == BATTLE                 # an area no pair names
    assert TABLES.bank(se.BATTLE_MAP) == BATTLE
    assert TABLES.area(0x200) == 0x200              # past the table, the number itself
    assert TABLES.area_banks == [300, 301]


def test_the_common_numbers_are_one_sound_everywhere():
    for m in (5, 7, se.BATTLE_MAP):
        assert _at(1, m) == (COMMON, 0, False)
        assert _at(8, m) == (COMMON, 7, False)
        assert _at(10, m) == (COMMON, 7, False)     # sequence 9, played two lower
    assert _at(11, 5) == (COMMON, 8, False)
    assert _at(24, 5) == (COMMON, 21, False)
    assert _at(25, 5) is None                       # sequence 22: past the common limit


def test_the_battles_numbers():
    assert _at(0x1F, se.BATTLE_MAP) == (BATTLE, 0, False)
    assert _at(0x7E, se.BATTLE_MAP) == (BATTLE, 0x5F, False)
    assert _at(0x7F, se.BATTLE_MAP) is None         # sequence 0x60: past the limit
    assert _at(0x82, se.BATTLE_MAP) == (BATTLE, 1, False)
    assert _at(0x18, se.BATTLE_MAP) == (COMMON, 0x15, False)
    assert _at(0x12, se.BATTLE_MAP) == (COMMON, 1, True)    # refused
    assert _at(0x1F, 5) == (COMMON, 1, True)        # a battle's number on a map is refused


def test_map_0x32_plays_its_own_bank_by_the_number():
    t = se.tables(_image({0x32: 4}, [(4, 320), (0, BATTLE)]))
    p = se.play(t, 0x1F, 0x32)
    assert (p.bank, p.sequence) == (320, 0)


def test_a_places_own_number_is_looked_up_in_its_bank():
    ids = se.sound_ids(_bank_with_ids([0x100, 0x9B, 0x103]))
    assert ids[:3] == (0x100, 0x9B, 0x103) and len(ids) == se.IDS_COUNT
    assert _at(0x9B, 5, ids) == (300, 1, False)
    assert _at(0x9B, 7, ids) == (301, 1, False)
    assert _at(0x104, 5, ids) is None               # not in g_SoundIds: nothing
    assert _at(0x9B, se.BATTLE_MAP, ids) == (COMMON, 1, True)
    assert se.sound_ids(bytes(16)) == ()
    nine = se.sound_ids(_bank_with_ids(range(0x100, 0x109)))
    assert _at(0x108, 5, nine) is None              # index 8: past sound_effect_play's 8


def test_a_stop_and_numbers_past_the_end_play_nothing():
    assert _at(0, 5) is None
    assert _at(se.LIMIT, 5) is None


def test_every_call_is_cited():
    import re
    for c in se.CALLS:
        assert re.fullmatch(r"\w+ \(0x8[0-9A-F]{7}\)", c.function), c
        assert c.what and c.number > 0

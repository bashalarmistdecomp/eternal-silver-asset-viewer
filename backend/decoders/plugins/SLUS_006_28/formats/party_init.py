"""The new-game party table — LUNADATA resource 0xE7 — and the code that
turns it into each character's level-1 battle record.

Every step is a function that was read (docs/spec/code/subsystems/battle.md
§"The party half"):

    ChrRecordsReset (0x80063B30) — run at boot by GameRun (0x800559F4) right after it
    points g_ChrRecords (0x800B8BE4) at 0x801DBF80, and again at new game (GameRecordsReset, 0x80055E78):

        FIL_0230(0xE7, buf);                  /* raw load: entry 0xE7 of the
                                                 sector table g_ResourceSectorPairs (0x800AE904)     */
        memmove(*g_ChrRecords, buf, 0x300);     /* 12 PERSISTENT records, 0x40
                                                 bytes each, by character id */
        memmove(*g_ChrPlacePresetRecords (0x800B8C74) + 8, buf + 0x342, 0x58);   /* 11 x 8 per id 1..11 */
        for (id = 1; id < 12; id++)           /* starting equipment          */
            for (slot = 1; slot < 7; slot++)
                ChrWornItemSet (0x80057FFC)(id, slot, buf[0x300 + (id-1)*6 + slot-1]);
        roster g_PartyIds (0x800B8BC0) = {1, 0, 0, 0, 0, 0};          /* character 1 alone */

    ChrWornItemSet(id, slot, item): record[0x1D + slot] = item, then
    ChrWornItemValuesAdd(id, item) (0x800587D0): the item record (g_ChrItemRows (0x800B8B94) = 0x800A9A68, stride
    0x12 — records.items) adds item[+0x0B] to selector item[+0x0C] >> 4 and
    item[+0x0A] to selector item[+0x0C] & 0xF through ChrWornItemStatAdd (0x80058910), whose
    jump table jtbl_8001288C maps selector 1..5 -> u16 +0x08/+0x0A/+0x0C/
    +0x0E/+0x10, 6 -> u8 +0x12, 7 -> u8 +0x1D, 8 -> u8 +0x13 (0: nothing).
    Plain adds, no clamp.

    BtlPartyStatsSet (0x8002A138) — at battle entry, per party slot, the battle
    record (CharStats, 0x3C bytes) is DERIVED from the persistent record and
    the equipment's item records (`battle_record`, transcribed below).

So the battle record is derived, not stored — which is why whole-record
searches of the EXE and the disc for a level-1 party record found nothing.
Checked AFTER the code path was read (the sanctioned direction): ids 1, 6
and 7 reproduce the `battle` savestate's party records byte for byte except
+0x2E..+0x31. Those are the items the character carries (chr.h ChrRecord
`items`, +0x24..+0x29, which BtlPartyStatsSet copies to +0x2E..+0x33), and
play changes them: ChrItemGive (0x800577C4) / ChrItemRemove (0x80057A54), the
battle's writing back (BtlPartyStatsStore (0x80028074)), and
ScriptCommandStoryBitsItemsReset (0x8005EF58), which copies them from this table
again.

This module reads LUNADATA bytes; the item table is the EXE's, passed in as
a lookup so the module never reaches for a file itself.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable

from ..records.programs import address

#: ChrRecordsReset (0x80063B30)'s literal: FIL_0230(0xE7, g_ResourceReadBuffer (0x800B8828)).
RESOURCE = 0xE7
RECORD = 0x40
RECORD_COUNT = 12               # memmove 0x300 bytes: ids 0..11
EQUIP_AT = 0x300                # 6 item ids per id 1..11
EQUIP_SLOTS = 6
PLACE_AT = 0x342                # memmove(*g_ChrPlacePresetRecords (0x800B8C74) + 8, buf + 0x342, 0x58)
PLACE_STRIDE = 8                # ChrPlacePresetRecord (chr.h)
CHAR_FIRST, CHAR_LAST = 1, 11   # the loops' bounds: `for (id = 1; id < 12; …)`
BATTLE_RECORD = 0x3C            # CharStats stride (BtlPartyStatsSet (0x8002A138): t0 += 0x3C)

ITEM_STRIDE = 0x12

#: ChrWornItemStatAdd (0x80058910) / jtbl_8001288C: selector -> (offset, struct format).
SELECTORS = {1: (0x08, "<H"), 2: (0x0A, "<H"), 3: (0x0C, "<H"), 4: (0x0E, "<H"),
             5: (0x10, "<H"), 6: (0x12, "B"), 7: (0x1D, "B"), 8: (0x13, "B")}

#: An item record by 1-based id. BtlPartyStatsSet (0x8002A138) reads an EMPTY slot (id 0) as
#: the 0x12 bytes before the table — `base + 0*0x12 - 0x12` — so the lookup
#: must answer 0 too (the EXE image does).
ItemLookup = Callable[[int], bytes]


@dataclass
class PartyInit:
    """Resource 0xE7, split the way ChrRecordsReset (0x80063B30) splits it."""
    records: list[bytes]                      # 12 x 0x40, by character id 0..11
    equipment: dict[int, tuple[int, ...]]     # id 1..11 -> 6 item ids (slot 1..6)
    place_presets: dict[int, bytes]           # id 1..11 -> its ChrPlacePresetRecord, from 0x342


def parse(buf: bytes) -> PartyInit:
    if len(buf) < PLACE_AT + PLACE_STRIDE * (CHAR_LAST - CHAR_FIRST + 1):
        raise ValueError(f"resource {RESOURCE:#x}: {len(buf)} bytes is too short")
    records = [bytes(buf[i * RECORD:(i + 1) * RECORD]) for i in range(RECORD_COUNT)]
    equipment, place_presets = {}, {}
    for cid in range(CHAR_FIRST, CHAR_LAST + 1):
        k = EQUIP_AT + (cid - 1) * EQUIP_SLOTS
        equipment[cid] = tuple(buf[k:k + EQUIP_SLOTS])
        s = PLACE_AT + (cid - 1) * PLACE_STRIDE
        place_presets[cid] = bytes(buf[s:s + PLACE_STRIDE])
    return PartyInit(records, equipment, place_presets)


@dataclass(frozen=True)
class PlacePreset:
    """A character's ChrPlacePresetRecord (chr.h), 8 bytes at
    *g_ChrPlacePresetRecords (0x800B8C74) + id * 8. The menu's battle-places
    and preset pages change it; MapBtlRun (0x8007AE58) copies all eight
    bytes into the battle's tables before each fight."""
    place_x: int                # +0: the battle place's x, in cells of 8 pixels
    place_y: int                # +1: its y, in cells
    presets: tuple[int, ...]    # +2..+7: three presets, each (kind, number)


def place_preset(raw: bytes) -> PlacePreset:
    return PlacePreset(place_x=raw[0], place_y=raw[1], presets=tuple(raw[2:PLACE_STRIDE]))


def _add(rec: bytearray, selector: int, amount: int) -> None:
    """ChrWornItemStatAdd (0x80058910): add `amount` to the field `selector` names."""
    if selector not in SELECTORS:
        return
    off, fmt = SELECTORS[selector]
    mask = 0xFFFF if fmt == "<H" else 0xFF
    struct.pack_into(fmt, rec, off, (struct.unpack_from(fmt, rec, off)[0] + amount) & mask)


def equip(rec: bytearray, slot: int, item_id: int, items: ItemLookup) -> None:
    """ChrWornItemSet (0x80057FFC) -> ChrWornItemValuesAdd (0x800587D0): put `item_id` in `slot` (1..6) and fold
    its two stat bonuses in. (ChrWornItemValuesAdd also raises an event flag for an
    item whose +0x05 is set — StoryBitSet(item[5] + 0x2BC) (0x800576EC); not a stat.)"""
    rec[0x1D + slot] = item_id & 0xFF
    if item_id & 0xFF:
        it = items(item_id & 0xFF)
        _add(rec, it[0x0C] >> 4, it[0x0B])
        _add(rec, it[0x0C] & 0x0F, it[0x0A])


def level1_records(init: PartyInit, items: ItemLookup) -> dict[int, bytes]:
    """ChrRecordsReset (0x80063B30)'s result: each id's persistent record, equipped."""
    out = {}
    for cid in range(CHAR_FIRST, CHAR_LAST + 1):
        rec = bytearray(init.records[cid])
        for slot, item_id in enumerate(init.equipment[cid], start=1):
            equip(rec, slot, item_id, items)
        out[cid] = bytes(rec)
    return out


@dataclass(frozen=True)
class PersistentRecord:
    """The 0x40-byte record at *g_ChrRecords (0x800B8BE4) + id*0x40, as far as code reads it."""
    hp: int                     # +0x00 (script opcode 6 sets it to +0x02)
    hp_max: int                 # +0x02
    mp: int                     # +0x04
    mp_max: int                 # +0x06
    stats: tuple[int, ...]      # +0x08/+0x0A/+0x0C/+0x0E/+0x10: selectors 1..5
    swings: int                 # +0x12 u8, selector 6
    stat_13: int                # +0x13 u8, selector 8
    level: int                  # +0x1C (ChrLevelUp (0x80028554) raises it)
    stat_1d: int                # +0x1D u8, selector 7
    equipment: tuple[int, ...]  # +0x1E..+0x23, slots 1..6 (ChrWornItemSet, 0x80057FFC)
    bytes_24: tuple[int, ...]   # +0x24..+0x29, the six carried items (chr.h items)
                                #   -> battle +0x2E..+0x33
    spells: tuple[int, ...]     # +0x2A..+0x31 -> battle +0x34..: spell-table
                                #   rows, slot by id (ChrLevelUp (0x80028554)'s jtbl_800118DC)
    exp_total: int              # +0x38 (BtlWinRun (0x80028140), ChrLevelAdd (0x8002844C))
    exp_next: int               # +0x3C, EXP to the next level (ChrLevelUp, 0x80028554)


def persistent(rec: bytes) -> PersistentRecord:
    h = lambda o: struct.unpack_from("<H", rec, o)[0]
    w = lambda o: struct.unpack_from("<I", rec, o)[0]
    return PersistentRecord(
        hp=h(0x00), hp_max=h(0x02), mp=h(0x04), mp_max=h(0x06),
        stats=tuple(h(o) for o in (0x08, 0x0A, 0x0C, 0x0E, 0x10)),
        swings=rec[0x12], stat_13=rec[0x13], level=rec[0x1C], stat_1d=rec[0x1D],
        equipment=tuple(rec[0x1E:0x24]), bytes_24=tuple(rec[0x24:0x2A]),
        spells=tuple(rec[0x2A:0x32]), exp_total=w(0x38), exp_next=w(0x3C))


#: BtlPartyStatsSet (0x8002A138)'s weapon-kind switch (jtbl_800119D8, kind = weapon item +0x0F):
#: the per-slot anim picks g_BtlPartyAttackAnimations (0x800B8BB8) (attack) /
#: g_BtlPartyStandAnimations (0x800B8BEC) (idle) / g_BtlPartyMoveAnimations (0x800B8BF4) (walk)
#: and the battle record's +0x19. Kind 3 depends on the character id; kind 5 takes +0x19 from
#: jtbl_800119F0 by id (or leaves it).
_WEAPON_KIND = {0: ((0x0B, 0x06, 0x01), 0x3B), 1: ((0x0D, 0x08, 0x03), 0x39),
                2: ((0x0D, 0x08, 0x03), 0x43), 4: ((0x0C, 0x07, 0x02), 0x4B)}
_KIND5_B19 = {1: 0x39, 2: 0x3C, 3: 0x43, 4: 0x43, 5: 0x39, 11: 0x39}   # jtbl_800119F0
_UNARMED = ((0x0A, 0x05, 0x00), 0x44)


@dataclass(frozen=True)
class BattleRecord:
    """A party member's stats (BtlStats, btl.h) as BtlPartyStatsSet (0x8002A138) builds
    them, plus the animations it picks. Bytes it does not write (+0x15
    status, +0x1E flags, +0x21, and +0x16/+0x17/+0x20/+0x22/+0x28 with no
    first worn item) are runtime state, left 0 here as a fresh record.
    `fields()` names them as btl.h does (side.party's names for +0x1A..)."""
    raw: bytes                          # 0x3C bytes
    anims: tuple[int, int, int] | None  # (attack, stand, move), or None (kind >= 6)

    def u16(self, off: int) -> int:
        return struct.unpack_from("<H", self.raw, off)[0]

    def fields(self) -> dict:
        r = self.raw
        return {
            "hp": self.u16(0x00), "hp_max": self.u16(0x02),
            "mp": self.u16(0x04), "mp_max": self.u16(0x06),
            "stat_08": self.u16(0x08), "stat_0a": self.u16(0x0A), "stat_0c": self.u16(0x0C),
            "stat_0e": self.u16(0x0E), "stat_10": self.u16(0x10),
            "attack_count": r[0x12], "walk_reach": r[0x13], "level": r[0x14],
            "least_amount": r[0x16], "attack_show": r[0x17], "walk_speed": r[0x18],
            "attack_sound": r[0x19],
            "stat_08_start": self.u16(0x1A), "stat_0a_start": self.u16(0x1C),
            "stat_1f": r[0x1F], "worn_item_kind": r[0x20],
            "worn_items": list(r[0x22:0x28]), "traits": list(r[0x28:0x2E]),
            "items": list(r[0x2E:0x34]), "spells": list(r[0x34:0x3C]),
            # g_BtlPartyAttackAnimations / g_BtlPartyStandAnimations (0x800B8BEC) /
            # g_BtlPartyMoveAnimations (0x800B8BF4)
            "animations": (dict(zip(("attack", "stand", "move"), self.anims))
                           if self.anims else None),
        }


def battle_record(rec: bytes, char_id: int, items: ItemLookup) -> BattleRecord:
    """BtlPartyStatsSet (0x8002A138) for one slot: persistent record `rec` (equipped) -> the
    battle record. Transcribed from the decomp's BtlPartyStatsSet (0x8002A138)."""
    p, c = rec, bytearray(BATTLE_RECORD)
    c[0x00:0x12] = p[0x00:0x12]                  # hp, hp max, mp, mp max, +0x08..+0x10
    c[0x1A:0x1C] = p[0x08:0x0A]                  # attack again, at +0x1A
    c[0x1C:0x1E] = p[0x0A:0x0C]                  # defence again, at +0x1C
    c[0x12], c[0x13] = p[0x12], p[0x13]
    c[0x18] = 3
    c[0x14] = p[0x1C]                            # level
    c[0x1F] = p[0x1D]                            # selector-7 field
    c[0x2E:0x34] = p[0x24:0x2A]                  # the six carried items
    c[0x34:0x3C] = p[0x2A:0x32]                  # the spell list
    anims = None
    weapon = p[0x1E]
    if weapon:
        it = items(weapon)
        c[0x22], c[0x16], c[0x17], c[0x28], c[0x20] = weapon, it[0x0B], it[0x0E], it[0x0D], it[0x0F]
        kind = it[0x0F]
        if kind in _WEAPON_KIND:
            anims, c[0x19] = _WEAPON_KIND[kind]
        elif kind == 3:
            anims = (0x0D, 0x08, 0x03) if char_id == 0x0A else (0x0E, 0x09, 0x04)
            c[0x19] = 0x3C
        elif kind == 5:
            anims = (0x0E, 0x09, 0x04)
            if char_id in _KIND5_B19:
                c[0x19] = _KIND5_B19[char_id]
    else:
        anims, c[0x19] = _UNARMED
    for k, src in enumerate(range(0x1F, 0x24)):  # equipment slots 2..6
        c[0x23 + k] = p[src]
        c[0x29 + k] = items(p[src])[0x0D]
    return BattleRecord(raw=bytes(c), anims=anims)


#: The battle-record fields a level-up moves: ChrLevelUp (0x80028554) raises the
#: persistent record, BtlPartyStatsSet (0x8002A138) copies it (+0x00..+0x13, +0x1A/+0x1C,
#: +0x14 the level, +0x34.. the spell list).
LEVEL_FIELDS = ("level", "hp", "hp_max", "mp", "mp_max", "stat_08", "stat_0a",
                "stat_0c", "stat_0e", "stat_10", "attack_count", "walk_reach",
                "stat_08_start", "stat_0a_start", "spells")

#: (record, level) -> the record raised to `level` in place:
#: ScriptCommandChrLevelItemSet (0x8005D2F0)'s "set level"
#: (records.level_up.set_level), passed in like the item table.
SetLevel = Callable[[bytearray, int], None]


def by_level(rec: bytes, char_id: int, items: ItemLookup, set_level: SetLevel,
             last: int = 99) -> dict[str, list]:
    """Persistent record `rec` at every level from its own to `last`, as
    columns: each LEVEL_FIELDS value of the battle record BtlPartyStatsSet (0x8002A138)
    builds at that level, plus the persistent EXP total / to-next. Index i
    is level `first + i`."""
    r = bytearray(rec)
    first = r[0x1C]
    cols: dict[str, list] = {k: [] for k in (*LEVEL_FIELDS, "exp_total", "exp_next")}
    for level in range(first, max(first, last) + 1):
        set_level(r, level)
        f = battle_record(bytes(r), char_id, items).fields()
        for k in LEVEL_FIELDS:
            cols[k].append(f[k])
        p = persistent(bytes(r))
        cols["exp_total"].append(p.exp_total)
        cols["exp_next"].append(p.exp_next)
    return {"first": first, **cols}


@dataclass
class PartyMemberData:
    char_id: int
    level1: PersistentRecord
    starting_equipment: tuple[int, ...]
    battle: BattleRecord
    place_preset: bytes = field(default=b"")


def party(buf: bytes, items: ItemLookup) -> list[PartyMemberData]:
    """Resource 0xE7 -> every id's level-1 persistent and battle records."""
    init = parse(buf)
    recs = level1_records(init, items)
    return [PartyMemberData(char_id=cid, level1=persistent(recs[cid]),
                            starting_equipment=init.equipment[cid],
                            battle=battle_record(recs[cid], cid, items),
                            place_preset=init.place_presets[cid])
            for cid in range(CHAR_FIRST, CHAR_LAST + 1)]


def exe_items(image: bytes, base_addr: int | None = None,
              image_base: int = 0x80011000) -> ItemLookup:
    """An ItemLookup over the EXE image's item table (records.items' BASE_ADDR;
    the pointers g_BtlItemRows (0x800B863C) / g_ChrItemRows (0x800B8B94) both hold it). Id 0 answers the 0x12
    bytes before the table, as BtlPartyStatsSet (0x8002A138)'s unguarded read does.
    `base_addr` defaults to where `image`'s program keeps it."""
    if base_addr is None:
        base_addr = address(image, "g_BtlItemTable", 0x800A9A68)
    def lookup(item_id: int) -> bytes:
        off = base_addr - image_base + (item_id - 1) * ITEM_STRIDE
        return image[off:off + ITEM_STRIDE]
    return lookup

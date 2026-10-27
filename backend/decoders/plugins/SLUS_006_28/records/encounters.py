"""Encounter tables — which graphics set and enemy formation a battle loads.

EXE-static, and read by `BtlEnemyLoad (0x8002B3AC)` (the enemy half of battle entry)
and `BtlDataLoad (0x80018694)` (the graphics loader); every layout statement below is
a line of one of them (docs/spec/code/subsystems/battle.md §"Battle entry
graphics"):

    p     = &g_BtlNumberRows[g_BtlNumber * 2];   /* encounter id -> {u8 set, u8 formation} */
    types = &g_BtlEnemySetIds[p[0] * 4];         /* set -> up to 4 enemy ids, 0 ends       */
    form  = &g_BtlEnemyGroups[p[1] * 0x18];      /* formation record                        */
    BtlDataLoad(p[0]);                           /* resource g_BtlDataResources[set] (u16, 0 = none) */

    for (i = 0; i < 4 && types[i]; i++)     /* every listed type gets a block          */
        inflate type i of the bundle;
    for (i = 0, k = 6; i < 8 && form[i]; i++, k++) {      /* enemy actor slots 6..13 */
        m = 0; while (m < 3 && types[m] != form[i]) m++;  /* NOT found -> block 3     */
        g_BtlSlotIds[k] = form[i];
        actor[k]: anim tables from block m; +0x0C = 0x20; +0x0E = 0x2100;
                  +0x06 = form[i + 8] * 8;
                  +0x0A = clamp(form[i + 16] * 8, 0x70, 0xB0); +0x08 = +0x0A;
                  if (+0x06 >= 0xC0) +0x0C = 0x2020;      /* bit 13 = mirror       */
        BtlAnimationSet(actor[k], 0);           /* anim 0                */
    }

(g_BtlNumberRows 0x800AC172, g_BtlNumber 0x800B8C79, g_BtlEnemySetIds 0x800AC370,
g_BtlEnemyGroups 0x800AA974, g_BtlDataResources 0x800A7E18, g_BtlSlotIds 0x800E48E0,
BtlAnimationSet 0x80027208.)

The positions are the actor ANCHOR (the point slice offsets are relative
to), not a sprite's top-left.

**Extents (the code bounds none of them; these are layout readings).** The
encounter and type-list tables are 1-BASED with the compiler's base
folding — `&tbl[(id - 1) * 2]` compiles to `(tbl - 2) + id * 2`, so the
symbol the code names sits one entry BEFORE the data:

  * formations: 256 records, 0..255, `0x800AA974 .. 0x800AC174`
  * encounters: ids 1..255 at `0x800AC174 .. 0x800AC372` — exactly where
    the formation table ends, which is what places id 1 there. "Encounter
    0" would read formation 255's last two bytes.
  * type lists: sets 1..51 at `0x800AC374 .. 0x800AC440` (after the
    encounter table + 2 bytes of 4-alignment). 51 is the largest set any
    encounter names; the bytes after do not have the 0-terminated shape.
  * set resources: u16, sets 0..51 (0 = no set), `0x800A7E18`; entry 52
    onward stops being a resource number.

**The script's encounter rows.** `tables_json` also carries
g_ScriptMapBtlRows (0x800B366C) — the 8-byte rows the event script's BATTLE command starts a
fight from (ScriptCommandMapBtlRun (0x8005DFF0): the encounter, MapBtlRun (0x8007AE58)'s arg1, the row's
own party list). The reader is `formats.event_script.encounter_rows`, the
module that owns that table; this one only puts its rows beside the
encounter tables, because what a fight is set up from (the party's x
shift among it) reads both.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from decoders.plugins.SLUS_006_28.formats import event_script as es

from .programs import address

EXE_BASE = 0x80011000           # where the EXE's header loads its image

ENCOUNTER_ADDR = 0x800AC172     # as the code names it (= data - 2)
ENCOUNTER_STRIDE = 2
ENCOUNTER_FIRST, ENCOUNTER_LAST = 1, 255
#: battle.md: BtlSpecialCheck (0x80038500) / BtlActionAttackRun
#: (0x80031060) treat ids >= 0xEB as the boss class (a re-picked target
#: every swing).
BOSS_CLASS_FIRST = 0xEB

TYPE_LIST_ADDR = 0x800AC370     # as the code names it (= data - 4)
TYPE_LIST_STRIDE = 4
SET_FIRST, SET_LAST = 1, 51

FORMATION_ADDR = 0x800AA974
FORMATION_STRIDE = 0x18
FORMATION_COUNT = 256
FORMATION_SLOTS = 8

SET_RESOURCE_ADDR = 0x800A7E18

#: BtlEnemyLoad (0x8002B3AC)'s per-actor constants.
ENEMY_SLOT_FIRST = 6
POS_UNIT = 8
Y_MIN, Y_MAX = 0x70, 0xB0
MIRROR_X_FROM = 0xC0            # +0x0C = 0x2020 at or right of this x
TYPE_MATCH_SLOTS = 3            # ids are matched against types[0..2] only
FALLBACK_TYPE = 3               # ... and anything else uses block 3
ENEMY_DRAW_FLAGS = 0x2100       # actor +0x0E -> CLUT row 505, Y-sorted depth


def _at(img: bytes, addr: int, n: int) -> bytes:
    off = addr - EXE_BASE
    if off < 0 or off + n > len(img):
        raise ValueError(f"{addr:#x}+{n} is outside the EXE image")
    return img[off:off + n]


@dataclass(frozen=True)
class Encounter:
    id: int
    set: int
    formation: int


@dataclass(frozen=True)
class FormationSlot:
    actor_slot: int         # CharStats / actor slot (6..13)
    enemy_id: int           # g_BtlSlotIds (0x800E48E0) value; template row id - 1
    x: int                  # actor +0x06, anchor x in pixels
    y: int                  # actor +0x0A after the clamp
    y_unclamped: int
    mirrored: bool          # actor +0x0C bit 13


@dataclass(frozen=True)
class Formation:
    index: int
    slots: tuple[FormationSlot, ...]
    raw: bytes


def encounter(img: bytes, eid: int) -> Encounter:
    if not ENCOUNTER_FIRST <= eid <= ENCOUNTER_LAST:
        raise ValueError(f"encounter ids run {ENCOUNTER_FIRST}..{ENCOUNTER_LAST}")
    s, f = _at(img, address(img, "g_BtlNumberRows", ENCOUNTER_ADDR) + eid * ENCOUNTER_STRIDE, 2)
    return Encounter(id=eid, set=s, formation=f)


def type_list(img: bytes, set_id: int) -> tuple[int, ...]:
    """The set's enemy type ids, in bundle-block order (0-terminated, <= 4)."""
    if not SET_FIRST <= set_id <= SET_LAST:
        raise ValueError(f"graphics sets run {SET_FIRST}..{SET_LAST}")
    raw = _at(img, address(img, "g_BtlEnemySetIds", TYPE_LIST_ADDR) + set_id * TYPE_LIST_STRIDE, 4)
    out = []
    for b in raw:
        if b == 0:
            break
        out.append(b)
    return tuple(out)


def type_slot(types: tuple[int, ...], enemy_id: int) -> int:
    """Which of the set's blocks an enemy draws from (BtlEnemyLoad (0x8002B3AC)'s search).

    Only the first three entries are compared; an id that matches none of
    them — the fourth type, or a stranger — falls through to block 3."""
    for m in range(min(TYPE_MATCH_SLOTS, len(types))):
        if types[m] == enemy_id:
            return m
    return FALLBACK_TYPE


def set_resource(img: bytes, set_id: int) -> int:
    """LUNADATA resource index BtlDataLoad (0x80018694) loads for a set; 0 = none."""
    if not 0 <= set_id <= SET_LAST:
        raise ValueError(f"graphics sets run 0..{SET_LAST}")
    at = address(img, "g_BtlDataResources", SET_RESOURCE_ADDR)
    return struct.unpack("<H", _at(img, at + 2 * set_id, 2))[0]


def formation(img: bytes, index: int) -> Formation:
    if not 0 <= index < FORMATION_COUNT:
        raise ValueError(f"formations run 0..{FORMATION_COUNT - 1}")
    at = address(img, "g_BtlEnemyGroups", FORMATION_ADDR)
    raw = _at(img, at + index * FORMATION_STRIDE, FORMATION_STRIDE)
    slots = []
    for i in range(FORMATION_SLOTS):
        eid = raw[i]
        if eid == 0:
            break
        x = raw[8 + i] * POS_UNIT
        y_raw = raw[16 + i] * POS_UNIT
        slots.append(FormationSlot(actor_slot=ENEMY_SLOT_FIRST + i, enemy_id=eid,
                                   x=x, y=min(max(y_raw, Y_MIN), Y_MAX),
                                   y_unclamped=y_raw, mirrored=x >= MIRROR_X_FROM))
    return Formation(index=index, slots=tuple(slots), raw=bytes(raw))


def all_encounters(img: bytes) -> list[Encounter]:
    return [encounter(img, e) for e in range(ENCOUNTER_FIRST, ENCOUNTER_LAST + 1)]


def max_enemy_id(img: bytes) -> int:
    """The largest enemy id any formation record names.

    BtlEnemyLoad (0x8002B3AC) copies a formation's ids into g_BtlSlotIds (0x800E48E0) and the copier
    BtlEnemyStatsSet (0x8002A638) reads template row id - 1 for each, so every template row
    up to this one is reachable by the code — a LOWER bound on the
    template table, not its extent."""
    return max(s.enemy_id
               for i in range(FORMATION_COUNT)
               for s in formation(img, i).slots)


def tables_json(img: bytes) -> dict:
    """Encounters 1..255, formations 0..255 and sets 1..51 as JSON-ready
    lists."""
    return {
        "encounters": [{"id": e.id, "set": e.set, "formation": e.formation}
                       for e in all_encounters(img)],
        "formations": [{"index": f.index,
                        "slots": [{"actor_slot": s.actor_slot, "enemy_id": s.enemy_id,
                                   "x": s.x, "y": s.y, "y_unclamped": s.y_unclamped,
                                   "mirrored": s.mirrored} for s in f.slots]}
                       for f in (formation(img, i) for i in range(FORMATION_COUNT))],
        "sets": [{"set": s, "resource": set_resource(img, s),
                  "types": list(type_list(img, s))}
                 for s in range(SET_FIRST, SET_LAST + 1)],
        # the event script's BATTLE rows (g_ScriptMapBtlRows (0x800B366C),
        # ScriptCommandMapBtlRun (0x8005DFF0) — read by formats.event_script): the
        # encounter, MapBtlRun (0x8007AE58)'s arg1 (the party's x shift) and the
        # row's own party list
        "script_rows": [{"row": r.row, "encounter": r.encounter, "x_shift": r.x_shift,
                         "party": list(r.party)} for r in es.encounter_rows(img)],
    }

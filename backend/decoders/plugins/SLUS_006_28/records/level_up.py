"""The party's level-up — the EXE's gain / EXP tables and the code that
applies them to a persistent party record (formats.party_init's 0x40-byte
record at *g_ChrRecords (0x800B8BE4) + id * 0x40).

Transcribed from the code (docs/spec/code/subsystems/battle.md §"Level-ups"):

    ChrLevelUp(id, rec) (0x80028554)  — ONE level:
        L = rec[0x1C]                        # the OLD level, g_BtlTargetSlot (0x800B8C5D)
        hdr = g_ChrLevelGainTable (0x800ACA38) + (id - 1) * 0x14   # ten big-endian u16 offsets
        gain(w) = g_ChrLevelGainTable[BE16(hdr[w]) + L]          (ChrLevelGainGet, 0x80028520)
        +0x02 max HP += gain(0)              (ChrLevelGainAdd (0x800289E0): cap 999)
        +0x06 max MP += gain(1)              — not for ids 7 and 9
        +0x08..+0x10 += gain(2..6), cap 999; the u8 at +0x14..+0x18 too,
                                               saturating at 255
        +0x12 and +0x19 += gain(7); +0x13 and +0x1A += gain(8)  (u8, wrap)
        +0x1C = L + 1
        +0x3C = BE32(g_ChrLevelGainTable + BE16(hdr[9]) + L * 4)   # EXP to the next
        then the first spell row (g_BtlSpellRows (0x800AA734) = spell-table row 1, 0x32 rows,
        stride 0x0C) whose +0x07 is the id (id 0xB matches 1's rows) and
        whose +0x00 is the NEW level is learned: rec[0x2A + slot] = row, the
        slot from jtbl_800118DC by id (`spell_slot`).

    ChrLevelAdd(id, n) (0x8002844C)  — n levels, unless the
        record is already at 99: each one adds +0x3C to the total +0x38
        (capped 9999999) and runs ChrLevelUp; reaching 99 zeroes +0x3C.

    ScriptCommandChrLevelItemSet (0x8005D2F0), sub-command 0 — "set this character to
        level N", what a join scene runs: N below the current level first
        reloads the id's raw record from resource 0xE7; then
        ChrLevelAdd(id, N - level) and HP / MP refilled to their maxima.

The win screen's loop (BtlWinRun, 0x80028140) spends battle EXP through the same
ChrLevelUp, one level per pass.

Checked against data the code did not read: the level-1 spell lists in
resource 0xE7 sit exactly at the slots jtbl_800118DC gives ids 1-6 and 11,
and every level-1 +0x38 + +0x3C sums to the table's first entry (20).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .programs import address

EXE_BASE = 0x80011000           # where the EXE's header loads its image
GAINS_ADDR = 0x800ACA38         # g_ChrLevelGainTable (0x800ACA38): per-id headers, then the byte pool
HEADER = 0x14                   # ten big-endian u16 offsets from GAINS_ADDR
SPELL_ROWS_ADDR = 0x800AA734     # g_BtlSpellRows (0x800AA734) = records.spells BASE_ADDR + one row
SPELL_STRIDE = 0x0C
SPELL_SCAN = 0x32               # ChrLevelUp (0x80028554) walks 50 rows
CHAR_FIRST, CHAR_LAST = 1, 11   # the ids resource 0xE7 equips (party_init)
LEVEL_CAP = 0x63                # ChrLevelAdd (0x8002844C) / BtlWinRun (0x80028140): no level past 99
STAT_CAP = 0x3E7                # ChrLevelGainAdd (0x800289E0) and the inline +0x08..+0x10 clamps
EXP_CAP = 0x98967F              # 9999999
NO_MP = (7, 9)                  # ChrLevelUp (0x80028554) skips gain(1) for these ids
SPELL_ALIAS = {0x0B: 1}         # id 0xB learns id 1's rows

#: Header word -> what it raises (ChrLevelUp (0x80028554)'s order).
WORDS = ("hp_max", "mp_max", "attack", "defence", "speed", "magic",
         "magic_defence", "swings", "stat_13", "exp_next")


def spell_slot(char_id: int, row: int) -> int:
    """jtbl_800118DC, indexed by id - 1: where a learned spell-table row lands
    in the record's eight-slot list (+0x2A). Ids 7-10 and anything past 11
    take no case — the asm then reuses a stale register — so no slot is
    defined for them (this EXE's table never reaches that path: their rows
    are all learned at level 1, which no level-up arrives at)."""
    if char_id in (1, 0x0B):
        return row - 1
    if char_id == 2:
        return row - 9 if row < 0x0D else row - 0x27
    base = {3: 0x0D, 4: 0x15, 5: 0x1D, 6: 0x21}.get(char_id)
    if base is None:
        raise ValueError(f"id {char_id}: jtbl_800118DC has no slot case "
                         f"(learning row {row} would use a stale register)")
    return row - base


@dataclass(frozen=True)
class Gains:
    """What one level added — the bytes ChrLevelUp (0x80028554) leaves in g_ChrLevelUpGains (0x800E49D0)
    for the win screen (+1 HP, +2 MP, +3..+7 the stats, +8/+9, +0xA row)."""
    hp: int
    mp: int
    stats: tuple[int, int, int, int, int]
    swings: int
    stat_13: int
    learned: int                 # spell-table row, 0 = none


def _be16(image: bytes, addr: int) -> int:
    return struct.unpack_from(">H", image, addr - EXE_BASE)[0]


def _header(image: bytes, char_id: int) -> int:
    if not CHAR_FIRST <= char_id <= CHAR_LAST:
        raise ValueError(f"id {char_id}: no level-up header (ids {CHAR_FIRST}..{CHAR_LAST})")
    return address(image, "g_ChrLevelGainTable", GAINS_ADDR) + (char_id - 1) * HEADER


def gain(image: bytes, char_id: int, word: int, level: int) -> int:
    """ChrLevelGainGet (0x80028520): header word `word`'s byte for a record at `level`."""
    off = _be16(image, _header(image, char_id) + 2 * word)
    return image[address(image, "g_ChrLevelGainTable", GAINS_ADDR) + off + level - EXE_BASE]


def exp_next(image: bytes, char_id: int, level: int) -> int:
    """The +0x3C a level-up from `level` writes: EXP from level + 1 to + 2."""
    off = _be16(image, _header(image, char_id) + 2 * 9)
    base = address(image, "g_ChrLevelGainTable", GAINS_ADDR)
    return struct.unpack_from(">I", image, base + off + level * 4 - EXE_BASE)[0]


def _add16(rec: bytearray, off: int, amount: int) -> None:
    v = (struct.unpack_from("<H", rec, off)[0] + amount) & 0xFFFF
    struct.pack_into("<H", rec, off, STAT_CAP if v >= STAT_CAP + 1 else v)


def level_up(rec: bytearray, char_id: int, image: bytes) -> Gains:
    """ChrLevelUp (0x80028554): raise persistent record `rec` (in place) by one level."""
    level = rec[0x1C]
    g = lambda w: gain(image, char_id, w, level)
    hp = g(0)
    _add16(rec, 0x02, hp)
    mp = 0
    if char_id not in NO_MP:
        mp = g(1)
        _add16(rec, 0x06, mp)
    stats = []
    for k in range(5):
        s = g(2 + k)
        _add16(rec, 0x08 + 2 * k, s)
        rec[0x14 + k] = min(0xFF, rec[0x14 + k] + s)
        stats.append(s)
    sw, s13 = g(7), g(8)
    rec[0x12] = (rec[0x12] + sw) & 0xFF
    rec[0x19] = (rec[0x19] + sw) & 0xFF
    rec[0x13] = (rec[0x13] + s13) & 0xFF
    rec[0x1A] = (rec[0x1A] + s13) & 0xFF
    rec[0x1C] = (level + 1) & 0xFF
    struct.pack_into("<I", rec, 0x3C, exp_next(image, char_id, level))
    learned = 0
    who = SPELL_ALIAS.get(char_id, char_id)
    for i in range(SPELL_SCAN):
        a = address(image, "g_BtlSpellRows", SPELL_ROWS_ADDR) + i * SPELL_STRIDE - EXE_BASE
        if image[a + 7] == who and image[a] == rec[0x1C]:
            learned = i + 1
            slot = spell_slot(char_id, learned) & 0xFF
            if slot >= 8:
                raise ValueError(f"id {char_id}: row {learned} lands outside the list")
            rec[0x2A + slot] = learned
            break
    return Gains(hp, mp, tuple(stats), sw, s13, learned)


def raise_levels(rec: bytearray, char_id: int, n: int, image: bytes) -> list[Gains]:
    """ChrLevelAdd (0x8002844C): `n` levels (u8), each paid for with exactly +0x3C EXP."""
    out: list[Gains] = []
    n &= 0xFF
    if rec[0x1C] >= LEVEL_CAP or n == 0:
        return out
    while n:
        total = struct.unpack_from("<I", rec, 0x38)[0] + struct.unpack_from("<I", rec, 0x3C)[0]
        struct.pack_into("<I", rec, 0x38, min(total & 0xFFFFFFFF, EXP_CAP))
        out.append(level_up(rec, char_id, image))
        n -= 1
        if rec[0x1C] >= LEVEL_CAP:
            struct.pack_into("<I", rec, 0x3C, 0)
            break
    return out


def set_level(rec: bytearray, char_id: int, level: int, image: bytes) -> None:
    """ScriptCommandChrLevelItemSet (0x8005D2F0) sub-command 0, the raising branch: bring `rec` up to
    `level` and refill HP / MP. Lowering reloads the raw 0xE7 record first
    (party_init), which this module does not reach for."""
    if level < rec[0x1C]:
        raise ValueError(f"level {level} is below the record's {rec[0x1C]}: "
                         "ScriptCommandChrLevelItemSet (0x8005D2F0) reloads resource 0xE7 for that")
    if level == rec[0x1C]:
        return
    raise_levels(rec, char_id, level - rec[0x1C], image)
    rec[0x00:0x02] = rec[0x02:0x04]
    rec[0x04:0x06] = rec[0x06:0x08]

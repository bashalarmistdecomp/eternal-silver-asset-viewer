"""Spell rows — 0x0C (12) bytes each; row n is spell n (BtlSpellRow, btl.h).

The table is g_BtlSpellRows (0x800AA734), 0x32 rows in the EXE's static data,
never written, so it is read straight from the EXE image with no emulator.
(Image base is `0x80011000`, the address the EXE's header loads it at.) The
battle reaches spell n at g_BtlSpellRowsByNumber (0x800AA728) + n * 0x0C, the
address one row before the table, and this module reads from that address
too: row n is spell n, and row 0 is the 12 bytes before the table, which no
spell number reaches.

The cast, BtlActionSpellRun (0x8002E718), reads it:

    spell = g_BtlSpellRowsByNumber + g_BtlActionNumber (0x800B8C67) * 0x0C   # the spell's number
    BtlActionRowRun (0x80031ABC)();                                          # runs the row (below)
    g_BtlTargetSlot (0x800B8C5D) = g_BtlActingSlot (0x800B8C26)
    if (BtlTargetTraitCheck (0x80037648)(0, 0x1B, 0, 0) == 1)               # the caster has trait 0x1B
        stats[caster].mp -= (spell->cost + 1) / 2
    else
        stats[caster].mp -= spell->cost                                      # lbu, so u8

The row does not hold the action itself but its function_number (+0x02),
plus parameters. BtlActionRowRun (0x80031ABC) loads the parameters into a
common set of globals (PARAM_GLOBALS) and then calls the function:

    if (g_BtlActionFunctionNumber (0x800B8C18) < 0x5F) scene_state_table[g_BtlActionFunctionNumber - 1](arg);

scene_state_table (0x800B2EF8) is the battle's table of row functions (the
register keeps the name it inherited; they are not scene states). Function
number 3 is its third, BtlTargetHpShareAddRun (0x80031ED4), the heal, which
works out its own amount (`max(40% of hp_max, 40) + roll`): a row's
parameters are defaults a function may ignore or replace, as the heal
replaces `power` (+0x05). See docs/spec/code/subsystems/battle.md
§"Magic — the spell table and the heal". Export schema:
docs/spec/battle-data.md §"The spell rows — `BtlSpellRow`".

TABLE EXTENT: 0x32 rows, spells 1..50 (btl.h `BtlSpellRow`; ChrLevelUp
(0x80028554) walks the same 0x32, `records.level_up`). Read from
g_BtlSpellRowsByNumber, that makes COUNT = 0x33 rows: row 0, then spells
1..50.

The row number IS the spell's number: g_BtlActionNumber for an action of
kind 3, and the number the string table names (string 0x1B6 + n,
BtlActionStringDisp (0x8004987C)). show_number (+0x06) is a different
number: BtlActionRowRun puts it in g_BtlActionShowNumber (0x800B8C0F), and
it names the show BtlShowNumberRun (0x8007BB80) plays.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._layout import field_notes, parse_fields
from .programs import address

# g_BtlSpellRowsByNumber (0x800AA728): one row before g_BtlSpellRows (0x800AA734),
# so row n is spell n.
BASE_ADDR = 0x800AA728
EXE_BASE = 0x80011000           # where the EXE's header loads its image
STRIDE = 0x0C
COUNT = 0x32 + 1                # row 0, then spells 1..0x32
INDEX_GLOBAL = "g_BtlActionNumber (0x800B8C67)"     # the spell's number selects the row

#: (offset, kind, name, note), btl.h's BtlSpellRow.
FIELDS = [
    (0x00, "u8", "level",            "the level the spell is learned at: ChrLevelUp (0x80028554) learns the rows of its id whose level is the new one; 1 = held from the start (resource 0xE7's records carry those). BtlActingSpellPick (0x800393F0) takes a spell only when the slot's level is not below it"),
    (0x01, "u8", "target_modes",     "two target modes. Low nibble the battle's: BtlActionTargetAdjust (0x8002ED34) kind 3 picks the target rule by it — BtlTargetByModeGet (0x800397B4) for a cast with no target (0 the caster, 1 the nearest enemy, 2-7 BtlPartyTargetPick (0x8003995C) over the party), BtlTargetModeAdjust (0x8002EB78) to check a chosen one (3 keep an inactive, 4 a statused, 5 one below hp_max, 6 below mp_max, 7 status-free; else any active); BtlMenuActionCheck (0x800493F8) makes g_BtlMenuTargetMode (0x800B8D3E) of it. High nibble the field menu's (ChrSpellUseGet (0x80058698) modes 2 and 3)"),
    (0x02, "u8", "function_number",  "BtlActionRowRun (0x80031ABC) puts it in g_BtlActionFunctionNumber (0x800B8C18) and calls entry number - 1 of scene_state_table (0x800B2EF8) (below 0x5F)"),
    (0x03, "u8", "use_place",        "two numbers. Low nibble: the entry of battle_state_table (0x800B5B1C) that MenuUseRun (0x80076444) calls for the spell outside a battle. High nibble: the place among the character's eight spells that ScriptCommandChrSpellSet (0x8005EE30) writes the spell into"),
    (0x04, "u8", "cost",             "the mp the spell costs: BtlActionSpellRun (0x8002E718) takes it off (lbu), halved and rounded up for a caster with trait 0x1B; outside a battle MenuUseRun (0x80076444) halves it the same way for a character wearing item 0x88 in place 5 or 6"),
    (0x05, "u8", "power",            "BtlActionRowRun (0x80031ABC) puts it in g_BtlActionPower (0x800B8C2C); the row's function may replace it (the heal does)"),
    (0x06, "u8", "show_number",      "the spell's show number: BtlActionRowRun (0x80031ABC) puts it in g_BtlActionShowNumber (0x800B8C0F), the show BtlShowNumberRun (0x8007BB80) plays. Not the spell's number, which is the row's"),
    (0x07, "u8", "chr_id",           "the id of the character the spell belongs to (1 for id 0xB too): ChrLevelUp (0x80028554) walks the table for the rows of its id; ScriptCommandChrSpellSet (0x8005EE30) stops on an error when the spell asked for is not the character's"),
    (0x08, "u8", "bit_number",       "BtlActionRowRun (0x80031ABC) puts it in g_BtlActionBitNumber (0x800B8C10). Number n stands for bit 1 << (n - 1) of an enemy target's resist_mask and weak_mask (BtlTargetTraitCheck (0x80037648)): 1 to 7 for BtlHitAmountSet (0x80030070) and BtlTargetHpAmountTake (0x80035FD8) (the amount halved or doubled), 9 to 14 for BtlStatusTakeCheck (0x80035378) (a status taking or not)"),
    (0x09, "u8", "area_half_width",  "half the width of the spell's area, in cells of 8 pixels: BtlActionRowRun (0x80031ABC) and BtlMenuTargetMark (0x8004746C) put it in g_BtlAreaHalfWidth (0x800B8C2E); BtlTargetAreaMark (0x80035B50) marks the slots in 2 * it + 1 cells across"),
    (0x0A, "u8", "area_half_height", "half the height of the spell's area, in cells: g_BtlAreaHalfHeight (0x800B8C30), set as area_half_width is; BtlTargetAreaMark (0x80035B50) marks 2 * it + 1 rows"),
    (0x0B, "u8", "blocked_by_status_20", "not 0 for a spell that cannot be cast while the caster's status has bit 0x20: BtlMenuActionCheck (0x800493F8) refuses it, BtlActingSpellUsableGet (0x8004EF4C) (through BtlSpellByte0BGet (0x8005066C)) passes it over for a status of exactly 0x20, BtlActionTargetAdjust (0x8002ED34) kind 3 replaces the action through BtlActionFallbackSet (0x8002F3A0)"),
]

NOTES = field_notes(FIELDS)

#: Fields that hold two nibbles; a table shows them in hex.
HEX_FIELDS = ("target_modes", "use_place")

# Every byte has a reader (FIELDS).
UNREAD_OFFSETS = ()

# BtlActionRowRun (0x80031ABC) runs every action kind through ONE parameter set.
# For reference, which global each spell field lands in:
PARAM_GLOBALS = {
    "function_number": "g_BtlActionFunctionNumber (0x800B8C18)",
    "power": "g_BtlActionPower (0x800B8C2C)",
    "show_number": "g_BtlActionShowNumber (0x800B8C0F)",
    "bit_number": "g_BtlActionBitNumber (0x800B8C10)",
    "area_half_width": "g_BtlAreaHalfWidth (0x800B8C2E)",
    "area_half_height": "g_BtlAreaHalfHeight (0x800B8C30)",
}


@dataclass
class SpellRecord:
    number: int          # the spell's number: the row, g_BtlActionNumber (0x800B8C67) for kind 3
    values: dict
    raw: bytes

    @property
    def is_empty(self) -> bool:
        return not any(self.raw)


def parse_record(buf: bytes, number: int) -> SpellRecord:
    if len(buf) < STRIDE:
        raise ValueError(f"need {STRIDE:#x} bytes, got {len(buf):#x}")
    return SpellRecord(number, parse_fields(buf, FIELDS), bytes(buf[:STRIDE]))


def parse_table(buf: bytes, count: int = COUNT) -> list[SpellRecord]:
    return [parse_record(buf[i * STRIDE:(i + 1) * STRIDE], i)
            for i in range(count)]


def read_from_exe(image: bytes, count: int = COUNT) -> list[SpellRecord]:
    """Parse straight out of the EXE code image (code.bin)."""
    base = address(image, "g_BtlSpellRowsByNumber", BASE_ADDR)
    off = base - EXE_BASE
    need = off + count * STRIDE
    if not 0 <= off or len(image) < need:
        raise ValueError(
            f"image of {len(image):#x} bytes does not cover {base:#x}"
            f" .. +{count * STRIDE:#x} (need {need:#x})")
    return parse_table(image[off:need], count)


def to_dict(rec: SpellRecord) -> dict:
    return {
        "number": rec.number,
        **rec.values,
        "empty": rec.is_empty,
        "raw": rec.raw.hex(),
    }

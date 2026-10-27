"""Enemy attack / special CLASS records — 8 bytes each, indexed by class.

The third parameter table `BtlActionRowRun (0x80031ABC)` loads (the other two are the
spell table, `records.spells`, and the item table, `records.items`). It
sits at the fixed address `0x800AC640` in the EXE's static data, so it is
read straight out of the EXE image. A battle record
names a class in two places:

    +0x1C  attack class   kind 2 (attack): an enemy whose +0x1C is nonzero
                          does not take the plain attack BtlActionAttackRun (0x80031060) —
                          BtlActionKindRun (0x8002E12C) sends it to BtlActionRowRun, which
                          loads g_BtlActionNumber (0x800B8C67) = +0x1C and this row
    +0x1D  special class  kind 7 (special): BtlEnemyKind7Pick (0x8004CF48) plans kind 7,
                          BtlEnemyActionAdjust (0x80029510) copies +0x1D into g_BtlSlotPlannedNumbers (0x800E4920), and
                          BtlActionKindRun sends kind 7 to BtlActionRowRun

(template +0x12 / +0x13 through the battle-entry copier — battle.md
§"The enemies' rows — `g_BtlEnemyRows` (`0x800A8768`), and
`BtlEnemyStatsSet`"). A class's NAME is string `class | 0x300`
(BtlActionStringDisp (0x8004987C), kind 7; `formats.system_strings`,
category enemy_special).

Every reader of g_BtlAttackRows (0x800AC640):

    BtlActionRowRun   +0x01..+0x06 -> the common parameter set:
        g_BtlActionFunctionNumber (0x800B8C18) = +1 (effect id: scene_state_table[effect - 1](), < 0x5F)
        g_BtlActionPower (0x800B8C2C) = +2   g_BtlAreaHalfWidth (0x800B8C2E) = +3   g_BtlAreaHalfHeight (0x800B8C30) = +4
        g_BtlActionBitNumber (0x800B8C10) = +5   g_BtlActionShowNumber (0x800B8C0F) = +6
    BtlActionTargetAdjust (0x8002ED34)   +0x00, kind 2 (nonzero class) and kind 7: the TARGET
        MODE. 2 = keep the target if it is an active slot < 14, else
        BtlTargetByModeGet(2) (0x800397B4); 7 = keep it if it is also status-free, else
        BtlTargetByModeGet(7) — and with no status-free party member at all,
        BtlEnemyActionFallbackSet (0x80036A18); anything else = keep the target as planned
    BtlEnemyKind7Pick   +0x00 == 7 and the chosen party target's status is
        exactly 4, 8 or 0x30 -> plan kind 2 instead of kind 7

Byte +0x07 is never read (and is 0 in every row).

TABLE EXTENT (measured, not assumed): 127 rows, 0x800AC640..0x800ACA38 —
the next byte is the level-up table g_ChrLevelGainTable (0x800ACA38) (`records.level_up`), and
127 = the zero row + the 126 enemy-special strings 0x301..0x37E. Rows 0,
2, 23 and 105 are all zero. Row 0 is not a "no special" sentinel the code
checks: a kind-7 action with class 0 loads effect 0 and calls
scene_state_table[-1], the zero word at 0x800B2EF4. Only the boss ids
(>= 0x6E) carry a zero +0x1D with an AI type that can plan kind 7, and
they fight only in boss-class encounters, where BtlEnemyActionSpecialSet (0x800417E4) plans
instead (battle.md §"Enemy specials").

Spec: docs/spec/code/subsystems/battle.md §"Enemy specials".
"""

from __future__ import annotations

from dataclasses import dataclass

from ._layout import field_notes, parse_fields
from .programs import address

BASE_ADDR = 0x800AC640          # g_BtlAttackRows (0x800AC640) — fixed, no pointer symbol
EXE_BASE = 0x80011000           # where the EXE's header loads its image
STRIDE = 0x08
COUNT = 127                     # rows 0..126; 0x800ACA38 is records.level_up's
NAME_STRING_BASE = 0x300        # string id = class | 0x300 (BtlActionStringDisp (0x8004987C), kind 7)

#: BtlActionTargetAdjust (0x8002ED34)'s target modes (+0x00).
TARGET_ANY_ACTIVE = 2
TARGET_STATUS_FREE = 7

FIELDS = [
    (0x00, "u8", "target_mode",      "BtlActionTargetAdjust (0x8002ED34) / BtlEnemyKind7Pick (0x8004CF48): 2 = an active slot, 7 = an active status-free party member, else the planned target stands"),
    (0x01, "u8", "effect_id",        "g_BtlActionFunctionNumber (0x800B8C18): 1-based scene_state_table index (BtlActionRowRun (0x80031ABC), < 0x5F)"),
    (0x02, "u8", "effect_magnitude", "g_BtlActionPower (0x800B8C2C): the resolver's percent bonus / the magic formula's level multiplier"),
    (0x03, "u8", "effect_param1",    "g_BtlAreaHalfWidth (0x800B8C2E): nonzero makes the hit-check handlers run BtlTargetReachCheck (0x800379AC) (arena geometry)"),
    (0x04, "u8", "effect_param2",    "g_BtlAreaHalfHeight (0x800B8C30): nonzero makes BtlTargetHitRun (0x80032958) run the evasion check BtlHitTry (0x8002FF0C)"),
    (0x05, "u8", "element_id",       "g_BtlActionBitNumber (0x800B8C10): 1-7 damage element (BtlHitAmountSet (0x80030070) / BtlTargetHpAmountTake (0x80035FD8)), 9-14 status element (BtlStatusTakeCheck, 0x80035378)"),
    (0x06, "u8", "spell_id",         "g_BtlActionShowNumber (0x800B8C0F): the presentation BtlShowNumberRun (0x8007BB80) plays"),
]
NOTES = field_notes(FIELDS)

UNREAD_OFFSETS = (0x07,)

#: Which global each field lands in (BtlActionRowRun, 0x80031ABC).
PARAM_GLOBALS = {
    "effect_id": "g_BtlActionFunctionNumber (0x800B8C18)",
    "effect_magnitude": "g_BtlActionPower (0x800B8C2C)",
    "effect_param1": "g_BtlAreaHalfWidth (0x800B8C2E)",
    "effect_param2": "g_BtlAreaHalfHeight (0x800B8C30)",
    "element_id": "g_BtlActionBitNumber (0x800B8C10)",
    "spell_id": "g_BtlActionShowNumber (0x800B8C0F)",
}


@dataclass
class AttackClass:
    class_id: int        # the g_BtlActionNumber (0x800B8C67) value that selects this row
    values: dict
    raw: bytes

    @property
    def is_empty(self) -> bool:
        return not any(self.raw)

    @property
    def name_string(self) -> int:
        """The string id the special's banner prints (class | 0x300)."""
        return self.class_id | NAME_STRING_BASE


def parse_record(buf: bytes, class_id: int) -> AttackClass:
    if len(buf) < STRIDE:
        raise ValueError(f"need {STRIDE:#x} bytes, got {len(buf):#x}")
    return AttackClass(class_id, parse_fields(buf, FIELDS), bytes(buf[:STRIDE]))


def parse_table(buf: bytes, count: int = COUNT) -> list[AttackClass]:
    return [parse_record(buf[i * STRIDE:(i + 1) * STRIDE], i) for i in range(count)]


def read_from_exe(image: bytes, count: int = COUNT) -> list[AttackClass]:
    """Parse straight out of the EXE code image (code.bin)."""
    base = address(image, "g_BtlAttackRows", BASE_ADDR)
    off = base - EXE_BASE
    need = off + count * STRIDE
    if len(image) < need:
        raise ValueError(
            f"image of {len(image):#x} bytes does not cover {base:#x}"
            f" .. +{count * STRIDE:#x} (need {need:#x})")
    return parse_table(image[off:need], count)


def to_dict(rec: AttackClass) -> dict:
    return {
        "class_id": rec.class_id,
        **rec.values,
        "name_string": rec.name_string,
        "empty": rec.is_empty,
        "raw": rec.raw.hex(),
    }

"""The enemies' rows — 0x26 (38) bytes each, g_BtlEnemyRows (0x800A8768),
a table in the EXE's data that nothing writes (BtlEnemyRow, btl.h).

**The layout is read off the copier.** BtlEnemyStatsSet (0x8002A638) is the
only function that reads g_BtlEnemyRows, and it calls nothing:

    for (i = 6; i < 14; i++) {                        /* enemy slots; 0..5 the party */
        if (g_BtlSlotIds[i] (0x800E48E0) == 0) break;  /* 0 ends the list           */
        row = g_BtlEnemyRows + (g_BtlSlotIds[i] - 1) * 38;   /* ids are 1-based     */
        ... 27 field copies into the slot's stats ...
    }

so the stride is 0x26 by the code's own arithmetic, the index is `id - 1`,
and g_BtlSlotIds is the encounter's per-slot enemy id list.

**The stats are not a copy of the row**: the copier spreads and reorders
the 38 bytes into the slot's 0x3C-byte stats (BtlStats, btl.h), and
stores hp twice, as hp and hp_max (COPIER_MAP). Each row field has btl.h's
BtlEnemyRow name, which is also the name of the stats field it lands in:
FIELDS gives each one's destination, BATTLE_FIELDS the code that reads it
there.

  * The stats' mp and status (+0x15) are not written by the copier.
  * +0x19, pad_19, is the one row byte the copier does not read.

**The extent.** The copier bounds the id only by the `u8` it is read
from, so the row count comes from the register: g_BtlEnemyRows runs
0x12EE bytes, up to the next symbol, g_BtlItemRowsByNumber (0x800A9A56).
That is 127 whole rows (ids 1..127) and 0x14 bytes over. The 0x14 bytes
are not a row: id 128 would read them together with the 0x12 bytes of
g_BtlItemRowsByNumber. The reader stops after row 126 and leaves them out.

docs/spec/code/subsystems/battle.md §"The enemies' rows — `g_BtlEnemyRows`
(`0x800A8768`), and `BtlEnemyStatsSet`". Export schema:
docs/spec/battle-data.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._layout import field_notes, parse_fields
from .programs import address

BASE_ADDR = 0x800A8768
EXE_BASE = 0x80011000           # where the EXE's header loads its image
STRIDE = 0x26
#: The register's extent of g_BtlEnemyRows: 0x12EE bytes, up to
#: g_BtlItemRowsByNumber (0x800A9A56).
SIZE = 0x12EE
COUNT = SIZE // STRIDE          # 127 whole rows: enemy ids 1..127
TAIL = SIZE % STRIDE            # 0x14 bytes after the last row; not a row

#: (offset, kind, name, note), btl.h's BtlEnemyRow. Widths are the copier's
#: load widths (`lbu` u8, `lhu` u16). "-> +0xNN" in a note is the field's
#: place in the slot's BtlStats, read off BtlEnemyStatsSet (0x8002A638)'s stores.
FIELDS = [
    (0x00, "u8",  "action_pick",   "-> +0x1A side.enemy.action_pick"),
    (0x01, "u8",  "level",         "-> +0x14 level"),
    (0x02, "u16", "hp",            "-> +0x00 hp and +0x02 hp_max: stored twice, so an enemy starts with all its hp"),
    (0x04, "u16", "stat_08",       "-> +0x08 stat_08"),
    (0x06, "u16", "stat_0a",       "-> +0x0A stat_0a"),
    (0x08, "u16", "stat_0c",       "-> +0x0C stat_0c"),
    (0x0A, "u16", "stat_0e",       "-> +0x0E stat_0e"),
    (0x0C, "u16", "stat_10",       "-> +0x10 stat_10"),
    (0x0E, "u8",  "walk_reach",    "-> +0x13 walk_reach"),
    (0x0F, "u8",  "least_amount",  "-> +0x16 least_amount"),
    (0x10, "u8",  "attack_count",  "-> +0x12 attack_count"),
    (0x11, "u8",  "trait",         "-> +0x1B side.enemy.trait"),
    (0x12, "u8",  "attack_number", "-> +0x1C side.enemy.attack_number"),
    (0x13, "u8",  "kind7_number",  "-> +0x1D side.enemy.kind7_number"),
    (0x14, "u8",  "walk_sound",    "-> +0x1E side.enemy.walk_sound"),
    (0x15, "u8",  "walk_speed",    "-> +0x18 walk_speed"),
    (0x16, "u8",  "attack_show",   "-> +0x17 attack_show"),
    (0x17, "u8",  "attack_sound",  "-> +0x19 attack_sound"),
    (0x18, "u8",  "action_sound",  "-> +0x1F side.enemy.action_sound"),
    (0x19, "u8",  "pad_19",        "not copied: the one row byte BtlEnemyStatsSet (0x8002A638) does not read, and nothing else reads the table"),
    (0x1A, "u16", "experience",    "-> +0x24 side.enemy.experience"),
    (0x1C, "u16", "money",         "-> +0x26 side.enemy.money"),
    (0x1E, "u8",  "win_item_1",    "-> +0x20 side.enemy.win_item_1"),
    (0x1F, "u8",  "win_rate_1",    "-> +0x21 side.enemy.win_rate_1"),
    (0x20, "u8",  "win_item_2",    "-> +0x22 side.enemy.win_item_2"),
    (0x21, "u8",  "win_rate_2",    "-> +0x23 side.enemy.win_rate_2"),
    (0x22, "u16", "weak_mask",     "-> +0x28 side.enemy.weak_mask"),
    (0x24, "u16", "resist_mask",   "-> +0x2A side.enemy.resist_mask"),
]

#: row offset -> (width, BtlStats offset), transcribed from
#: BtlEnemyStatsSet (0x8002A638). hp appears twice because the copier stores it twice.
COPIER_MAP = (
    (0x00, 1, 0x1A), (0x01, 1, 0x14), (0x02, 2, 0x02), (0x02, 2, 0x00),
    (0x04, 2, 0x08), (0x06, 2, 0x0A), (0x08, 2, 0x0C), (0x0A, 2, 0x0E),
    (0x0C, 2, 0x10), (0x0E, 1, 0x13), (0x0F, 1, 0x16), (0x10, 1, 0x12),
    (0x11, 1, 0x1B), (0x12, 1, 0x1C), (0x13, 1, 0x1D), (0x14, 1, 0x1E),
    (0x17, 1, 0x19), (0x18, 1, 0x1F), (0x15, 1, 0x18), (0x16, 1, 0x17),
    (0x1A, 2, 0x24), (0x1C, 2, 0x26), (0x1E, 1, 0x20), (0x1F, 1, 0x21),
    (0x20, 1, 0x22), (0x21, 1, 0x23), (0x22, 2, 0x28), (0x24, 2, 0x2A),
)

#: The stats record the copier writes into (BtlStats, btl.h).
CHARSTATS_STRIDE = 0x3C
#: Stats slots 0..5 are the party, 6..13 the encounter's enemies.
ENEMY_SLOT_FIRST = 6
ENEMY_SLOT_LIMIT = 14
#: g_BtlSlotIds, the per-slot id array the copier indexes; 0 ends the list.
ENCOUNTER_IDS_ADDR = 0x800E48E0


def build_charstats(template: bytes) -> bytes:
    """Apply BtlEnemyStatsSet (0x8002A638)'s copy to one row -> a 0x3C BtlStats record.

    A transcription of the copier's body, so an app can show what a battle
    starts from. Bytes the copier does not write are left zero: it writes
    into a record already prepared, so this is the copier's part of the
    record, not all of it (the status, +0x15, does not come from the row).
    """
    if len(template) < STRIDE:
        raise ValueError(f"need {STRIDE:#x} bytes, got {len(template):#x}")
    rec = bytearray(CHARSTATS_STRIDE)
    for src, width, dst in COPIER_MAP:
        rec[dst:dst + width] = template[src:src + width]
    return bytes(rec)


#: Every stats field the copier writes — (BtlStats offset, kind, name,
#: note) — by its btl.h name, with the code that reads it there, at the
#: width that code loads it. +0x1A..+0x2D are a union by side
#: (side.party / side.enemy); the names are side.enemy's, the only side a
#: row fills.
BATTLE_FIELDS = [
    (0x00, "u16", "hp",            "hits take it down (BtlHitAmountTake (0x80030650)); the copier starts it at hp_max"),
    (0x02, "u16", "hp_max",        "heals stop at it (BtlTargetHpShareAddRun (0x80031ED4) and the other heals)"),
    (0x08, "u16", "stat_08",       "BtlHitAmountSet (0x80030070): what the acting slot's hit amount starts from"),
    (0x0A, "u16", "stat_0a",       "BtlHitAmountSet (0x80030070): the target's stat_0a is taken off a hit's amount"),
    (0x0C, "u16", "stat_0c",       "BtlTurnOrderMake (0x8002F4B0) (lhu): the round's order is sorted by +0x0C plus rng_mask_below(0x3FF, the highest +0x0C / 10) (0x8003A0D4), highest first; a slot whose status has a bit of 0x0C keys on the draw alone"),
    (0x0E, "u16", "stat_0e",       "BtlStat0EHitAmountSet (0x80035EF8) (lhu): what the acting slot's other kind of amount starts from; BtlStatusTakeCheck (0x80035378): the acting slot's +0x0E plus the power less the target's +0x0E is the chance a status takes"),
    (0x10, "u16", "stat_10",       "BtlStat0EHitAmountSet (0x80035EF8) (lhu): the target's stat_10 is taken off the stat-0E amount"),
    (0x12, "u8",  "attack_count",  "BtlActionAttackRun (0x80031060) walks and hits this many times; BtlHitAmountSet (0x80030070) applies a kind-3 amount's percentage this many times less 1"),
    (0x13, "u8",  "walk_reach",    "BtlWalkSet (0x8002BAA4) -> g_BtlWalkBlockReach (0x800E4B1F): the cells BtlWalkRun (0x8002BB5C) / BtlWalkDistanceFill (0x8002D254) let the slot walk in one action (halved under status 0x10 for a party slot, held at 0x28); also a hit check's reach (BtlTargetReachCheck, 0x800379AC)"),
    (0x14, "u8",  "level",         "BtlHitAmountSet (0x80030070): the level gap adds to a hit's amount (lbu); BtlStat0EHitAmountSet (0x80035EF8): level times the power"),
    (0x16, "u8",  "least_amount",  "BtlHitAmountSet (0x80030070): the acting slot's amount is raised to it when below it"),
    (0x17, "u8",  "attack_show",   "for an acting slot of 6 or more and not 0, BtlAttackHitShow (0x800314B8) / BtlAttackMissShow (0x80031378) hand it to BtlActingShowRun (0x8003A158) in place of the attack animation; BtlAttackWalkRun (0x80031244): 0x98/0x9A/0x9B/0xA4/0xA5/0xAC/0xAF/0xB1 do not walk, 0x9D/0xA7 ask BtlTargetReachCheck (0x800379AC), anything else walks (BtlWalkRun, 0x8002BB5C)"),
    (0x18, "u8",  "walk_speed",    "BtlWalkSet (0x8002BAA4) -> g_BtlWalkBlock (0x800E4B10) +0x0E; BtlWalkPathFollow (0x8002CA78): 1 / 2 / 3 / other -> a cell every 1 / 2 / 4 / 8 frames"),
    (0x19, "u8",  "attack_sound",  "BtlAttackAnimationRun (0x800315A8) plays it (SoundPlay (0x800555F0)); BtlActingShowRun (0x8003A158) makes it g_BtlActionSound (0x800B8CC0) for an action of kind 2"),
    (0x1A, "u8",  "action_pick",   "BtlEnemyActionPick (0x8004CAB8) (lbu) switches on it: 1 to 32 a pick with a target rule, 0 and above 32 a default by draws; BtlActionTargetAdjust (0x8002ED34) sends 2/7/12/17/26 to the nearest party slot"),
    (0x1B, "u8",  "trait",         "BtlTargetTraitCheck (0x80037648): an enemy target's one trait, tested against the traits it is asked for; BtlHitStrongTry (0x80038310) and BtlHitStatusUpdate (0x80030A04) read the acting slot's"),
    (0x1C, "u8",  "attack_number", "not 0: BtlActionKindRun (0x8002E12C) sends the enemy's kind-2 (attack) action to BtlActionRowRun (0x80031ABC), which runs this row of g_BtlAttackRows (0x800AC640) in place of the plain attack BtlActionAttackRun (0x80031060); 0 is the plain attack. The game shows no name for it (BtlActionStringDisp (0x8004987C) names an enemy's kind 7 only)"),
    (0x1D, "u8",  "kind7_number",  "BtlEnemyActionAdjust (0x80029510) gives a slot whose planned kind is 7 this number (g_BtlSlotPlannedNumbers (0x800E4920)); BtlEnemyKind7Pick (0x8004CF48) reads its g_BtlAttackRows (0x800AC640) row's target mode, BtlActionRowRun (0x80031ABC) the rest (records.attack_classes); its name is string number | 0x300 (BtlActionStringDisp, 0x8004987C)"),
    (0x1E, "u8",  "walk_sound",    "BtlWalkSet (0x8002BAA4) -> g_BtlWalkBlock (0x800E4B10) +0x10 for a walker of slot 5 or more (0x2A for the party); BtlWalkPathFollow (0x8002CA78) plays it (SoundPlay (0x800555F0)) unless it is 0xFF"),
    (0x1F, "u8",  "action_sound",  "BtlActingShowRun (0x8003A158) makes it g_BtlActionSound (0x800B8CC0) for an action of any kind but 2"),
    (0x20, "u8",  "win_item_1",    "BtlWinItemsGive (0x80028A54) (lbu): the first item a won battle may give for this enemy; it must be 1..0xA4, or neither item is tried"),
    (0x21, "u8",  "win_rate_1",    "BtlWinItemsGive (0x80028A54) -> BtlWinItemRateCheck (0x80028A0C): given when rng_7f_draw (0x8003A0B4) is not above it"),
    (0x22, "u8",  "win_item_2",    "BtlWinItemsGive (0x80028A54): tried only when win_item_1's draw fails"),
    (0x23, "u8",  "win_rate_2",    "BtlWinItemsGive (0x80028A54) -> BtlWinItemRateCheck (0x80028A0C), as win_rate_1"),
    (0x24, "u16", "experience",    "BtlWinRewardSum (0x80028D78) (lhu): summed over the enemy slots that still hold an id at the win, held at 99,999, then set against the party (BtlWinRun, 0x80028140)"),
    (0x26, "u16", "money",         "BtlWinRewardSum (0x80028D78) (lhu): summed the same way and added to the money *g_GameMoney (0x800B8C08), held at 9,999,999"),
    (0x28, "u16", "weak_mask",     "BtlTargetTraitCheck (0x80037648) answers 2 when the mask it is asked for meets this (tested after resist_mask); BtlHitAmountSet (0x80030070) doubles a party slot's attack on the enemy when the bit its first trait gives is set here"),
    (0x2A, "u16", "resist_mask",   "BtlTargetTraitCheck (0x80037648) answers 1 when the mask it is asked for meets this, before weak_mask is tested; BtlHitAmountSet (0x80030070) halves that attack when the bit is set here"),
]


def battle_record(template: bytes) -> dict:
    """-> the stats a battle starts the enemy with, by their btl.h names.

    `build_charstats` (the copier) followed by a read of BATTLE_FIELDS."""
    return parse_fields(build_charstats(template), BATTLE_FIELDS)


def template_index(enemy_id: int) -> int:
    """Encounter enemy id -> row in this table. Ids are 1-based (id - 1)."""
    if enemy_id <= 0:
        raise ValueError("id 0 terminates the encounter list; it has no row")
    return enemy_id - 1


NOTES = field_notes(FIELDS)
BATTLE_NOTES = field_notes(BATTLE_FIELDS)


@dataclass
class EnemyTemplate:
    index: int
    values: dict
    raw: bytes

    @property
    def is_empty(self) -> bool:
        return not any(self.raw)


def parse_record(buf: bytes, index: int) -> EnemyTemplate:
    if len(buf) < STRIDE:
        raise ValueError(f"need {STRIDE:#x} bytes, got {len(buf):#x}")
    return EnemyTemplate(index, parse_fields(buf, FIELDS), bytes(buf[:STRIDE]))


def parse_table(buf: bytes, count: int = COUNT) -> list[EnemyTemplate]:
    return [parse_record(buf[i * STRIDE:(i + 1) * STRIDE], i)
            for i in range(count)]


def read_from_exe(image: bytes, count: int = COUNT) -> list[EnemyTemplate]:
    """Parse straight out of the EXE code image (code.bin): every whole row
    unless `count` asks for fewer."""
    base = address(image, "g_BtlEnemyRows", BASE_ADDR)
    off = base - EXE_BASE
    need = off + count * STRIDE
    if off < 0 or len(image) < need:
        raise ValueError(
            f"image of {len(image):#x} bytes does not cover {base:#x}"
            f" .. +{count * STRIDE:#x} (need {need:#x})")
    return parse_table(image[off:need], count)


def to_dict(rec: EnemyTemplate) -> dict:
    return {
        "index": rec.index,
        **rec.values,
        "battle_record": battle_record(rec.raw),
        "empty": rec.is_empty,
        "raw": rec.raw.hex(),
    }

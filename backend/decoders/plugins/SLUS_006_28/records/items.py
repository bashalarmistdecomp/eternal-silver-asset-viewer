"""The item rows — 0x12 (18) bytes each, item number n at row n - 1
(BtlItemRow, btl.h).

The table is g_BtlItemTable (0x800A9A68), 0xB6 rows in the EXE's data,
never written, so it is read straight from the EXE image. The code reaches
this one table three ways: through the pointer g_BtlItemRows (0x800B863C)
in the battle, through g_ChrItemRows (0x800B8B94) in the menus, the shop
and the Chr functions, and as g_BtlItemRowsByNumber (0x800A9A56) +
number * 0x12, the address one row before the table.

The table has 0xB6 (182) rows, items 1..182: ChrItemUseGet (0x80058088)
answers -2 for an item number of 0 or above 0xB6, and the table ends where
the spell rows g_BtlSpellRows (0x800AA734) begin (`records.spells`).

FIELDS says what reads each field. Three bytes hold two numbers, one in
each nibble: target_modes (+0x06), use_picture (+0x07) and bonus_stats
(+0x0C). A worn item's two bonuses go to the stats bonus_stats selects;
the battle's unequip path, BtlWornItemRemove (0x80038BFC), reads them so:

    row = *g_BtlItemRows + (item - 1) * 0x12
    low nibble  of row->bonus_stats -> selector, amount row->bonus_1_power
    high nibble of row->bonus_stats -> selector, amount row->bonus_2

ChrWornItemValuesAdd (0x800587D0) adds them to the character's record
through ChrWornItemStatAdd (0x80058910); ChrWornItemValuesRemove
(0x8005886C) takes them off, and in a battle BtlWornItemStatLower
(0x800389C4) takes them off the slot's stats too (STAT_SELECTORS).

Evidence: docs/spec/battle-data.md §"Where the tables are" and §"The item
rows"; docs/spec/code/subsystems/battle.md §"Worn items".
"""

from __future__ import annotations

from dataclasses import dataclass

from ._layout import field_notes, parse_fields
from .programs import address

POINTER_SYMBOL = "g_BtlItemRows (0x800B863C)"   # u32 -> table base; how the battle reaches it
BASE_ADDR = 0x800A9A68          # g_BtlItemTable, where that pointer lands
EXE_BASE = 0x80011000           # where the EXE's header loads its image
STRIDE = 0x12
ID_BASE = 1                     # item 0 = an empty worn place
COUNT = 0xB6                    # ChrItemUseGet (0x80058088): item numbers 1..0xB6

#: (offset, kind, name, note), btl.h's BtlItemRow.
FIELDS = [
    (0x00, "u16", "price",           "ShopItemDisp (0x80052C0C) marks the item when it costs more than the money *g_GameMoney (0x800B8C08); ShopDealRun (0x80053194) takes it off the money"),
    (0x02, "u16", "sell_price",      "what giving the item up adds to the money (ShopDealRun (0x80053194)); 0: it cannot be given up (ChrItemUseGet (0x80058088) mode 2)"),
    (0x04, "u8",  "kind",            "below 5 the item is worn, in worn place kind + 1 (character record +0x1E + kind; kind 4 has places 5 and 6); 5 and up it is carried, 6 cannot be given up (ShopItemDisp (0x80052C0C), ChrItemListSort (0x80058B3C))"),
    (0x05, "u8",  "story_bit",       "not 0: ChrWornItemValuesAdd (0x800587D0) sets story bit story_bit + 0x2BC when the item is put on, ChrWornItemValuesRemove (0x8005886C) clears it when it comes off"),
    (0x06, "u8",  "target_modes",    "two target modes. Low nibble the battle's: BtlMenuActionCheck (0x800493F8) makes g_BtlMenuTargetMode (0x800B8D3E) of it, BtlActionTargetAdjust (0x8002ED34) hands it to BtlTargetByModeGet (0x800397B4) / BtlTargetModeAdjust (0x8002EB78). High nibble the field menu's (ChrItemUseGet (0x80058088) mode 3, MenuItemUseStep (0x8006E05C)): 9 not usable, below 5 no target, 5 and up a target to pick"),
    (0x07, "u8",  "use_picture",     "two numbers for the field menu's use. Low nibble: the entry of battle_state_table (0x800B5B1C) that MenuUseRun (0x80076444) calls for the item. High nibble: the picture MenuUsePictureRun (0x8007690C) plays (movie high nibble + 0x37)"),
    (0x08, "u8",  "function_number", "the item used as an action: BtlActionRowRun (0x80031ABC) puts it in g_BtlActionFunctionNumber (0x800B8C18), entry number - 1 of scene_state_table (0x800B2EF8); 0 for an item a battle cannot use, which BtlMenuActionCheck (0x800493F8) refuses"),
    (0x09, "u8",  "show_number",     "the item used as an action: BtlActionRowRun (0x80031ABC) puts it in g_BtlActionShowNumber (0x800B8C0F), the show BtlShowNumberRun (0x8007BB80) plays"),
    (0x0A, "u8",  "bonus_1_power",   "a union. bonus_1: the bonus to the stat bonus_stats' low nibble selects (ChrWornItemValuesAdd (0x800587D0), ChrWornItemValuesRemove (0x8005886C), BtlWornItemRemove (0x80038BFC)). power: for an item number of 0x9C or more, BtlActionRowRun (0x80031ABC) puts it in g_BtlActionPower (0x800B8C2C)"),
    (0x0B, "u8",  "bonus_2",         "the bonus to the stat bonus_stats' high nibble selects; BtlPartyStatsSet (0x8002A138) also takes the first worn item's as the slot's least_amount"),
    (0x0C, "u8",  "bonus_stats",     "two stat selectors, 0 none (STAT_SELECTORS): low nibble bonus_1's, high nibble bonus_2's (ChrWornItemStatAdd (0x80058910), BtlWornItemStatLower (0x800389C4))"),
    (0x0D, "u8",  "trait",           "BtlPartyStatsSet (0x8002A138) copies each worn item's into the slot's side.party.traits"),
    (0x0E, "u8",  "attack_show",     "BtlPartyStatsSet (0x8002A138) copies the first worn item's into the slot's attack_show, which nothing reads for a party slot"),
    (0x0F, "u8",  "worn_item_kind",  "0 to 5 for an item of kind 0, 0 for any other: BtlPartyStatsSet (0x8002A138) copies the first worn item's into side.party.worn_item_kind and picks the slot's attack, stand and move animations and attack_sound by it"),
    (0x10, "u16", "wearers",         "who may wear it: bit n - 1 for each party number n (ChrItemUseGet (0x80058088) mode 1, ShopItemDisp (0x80052C0C), ShopItemLineUpSet (0x800521F8))"),
]

NOTES = field_notes(FIELDS)

#: Fields that hold two nibbles or bits; a table shows them in hex.
HEX_FIELDS = ("target_modes", "use_picture", "bonus_stats", "wearers")

#: bonus_stats' selectors -> the stats field each one changes, as
#: BtlWornItemStatLower (0x800389C4) names it in BtlStats. In the
#: character's record (ChrRecord, chr.h) selector 7 is stat_1d; the others
#: have the same names there.
STAT_SELECTORS = {
    1: "stat_08", 2: "stat_0a", 3: "stat_0c", 4: "stat_0e",
    5: "stat_10", 6: "attack_count", 7: "stat_1f", 8: "walk_reach",
}


@dataclass
class ItemRecord:
    item_id: int      # 1-based, as the game numbers items
    values: dict
    raw: bytes

    @property
    def modifiers(self) -> list[dict]:
        sel = self.values["bonus_stats"]
        out = []
        for nib, amount_key in ((sel & 0xF, "bonus_1_power"),
                                ((sel >> 4) & 0xF, "bonus_2")):
            if nib:
                out.append({
                    "selector": nib,
                    "stat": STAT_SELECTORS.get(nib, f"unknown_{nib}"),
                    "amount": self.values[amount_key],
                })
        return out


def parse_record(buf: bytes, item_id: int) -> ItemRecord:
    if len(buf) < STRIDE:
        raise ValueError(f"need {STRIDE:#x} bytes, got {len(buf):#x}")
    return ItemRecord(item_id, parse_fields(buf, FIELDS), bytes(buf[:STRIDE]))


def parse_table(buf: bytes, count: int = COUNT) -> list[ItemRecord]:
    return [parse_record(buf[i * STRIDE:(i + 1) * STRIDE], ID_BASE + i)
            for i in range(count)]


def read_from_exe(image: bytes, count: int = COUNT) -> list[ItemRecord]:
    """Parse straight out of the EXE code image (code.bin)."""
    base = address(image, "g_BtlItemTable", BASE_ADDR)
    off = base - EXE_BASE
    need = off + count * STRIDE
    if off < 0 or len(image) < need:
        raise ValueError(
            f"image of {len(image):#x} bytes does not cover {base:#x}"
            f" .. +{count * STRIDE:#x} (need {need:#x})")
    return parse_table(image[off:need], count)


def to_dict(rec: ItemRecord) -> dict:
    return {
        "id": rec.item_id,
        **rec.values,
        "modifiers": rec.modifiers,
        "empty": not any(rec.raw),
        "raw": rec.raw.hex(),
    }

"""The battle tables, read from the opened disc's program for the Data tables tab.

Every table here is static data in the program file (the EXE), apart from
the party, which is LUNADATA resource 0xE7 put through the code that loads
and equips it. Each comes back as a document:

    {"_meta": {...where it came from, field notes...}, "records": [...]}

or, for the two that are not record arrays (battle_runtime, party), the
document's own keys beside `_meta`. Nothing is written to disk.

    enemy_templates   EXE 0x800A8768 — the enemy stat templates
    items             EXE 0x800A9A68 — 0xB6 rows, reached through g_BtlItemRows (0x800B863C)
    spells            EXE 0x800AA728 — g_BtlSpellRowsByNumber (0x800AA728): row n is spell n
    attack_classes    EXE 0x800AC640 — the enemy class rows BtlActionRowRun (0x80031ABC) loads
    battle_runtime    the field's facing steps MapSpotMove (0x80066848) reads (not
                      the battle's), the RNG's functions, spell 33's row
    party             LUNADATA 0xE7 through ChrRecordsReset (0x80063B30) and BtlPartyStatsSet (0x8002A138),
                      every level through ChrLevelAdd (0x8002844C) (records.level_up)

The addresses above are SLUS_006.28's; each table is read, and its place
given, where the image's program keeps it (records.programs).

The live stat table the battle keeps in RAM (`char_stats`) is not here: it
is save state, not data on the disc.
"""

from __future__ import annotations

from pathlib import Path

RECORDS = "decoders.plugins.SLUS_006_28.records"
FORMATS = "decoders.plugins.SLUS_006_28.formats"
#: Spell 33's row in the spell table (battle.md §Magic).
SPELL_33_ROW = 33


def _meta(producer: str, exe_name: str, **source) -> dict:
    return {"source": {"kind": "exe-image", "producer": producer,
                       "image": exe_name, **source}}


def build(image: bytes, exe_name: str, resources: dict, archive: Path) -> dict[str, dict]:
    """-> {table name: document}, in the order the tab lists them.

    `image` is the program's text as `exe_loader.load_exe(...).code` lays it
    out; `resources` the LUNADATA resource table (index -> entry)."""
    from decoders.plugins.SLUS_006_28.formats import party_init
    from decoders.plugins.SLUS_006_28.records import (
        attack_classes, battle_constants, encounters, enemy_templates, items,
        level_up, spells)
    from decoders.plugins.SLUS_006_28.records.programs import address

    docs: dict[str, dict] = {}

    meta = _meta(f"{RECORDS}.enemy_templates", exe_name,
                 table_base=hex(address(image, "g_BtlEnemyRows", enemy_templates.BASE_ADDR)),
                 stride=enemy_templates.STRIDE, count=enemy_templates.COUNT)
    meta["count_basis"] = (
        f"the register's extent of g_BtlEnemyRows: {enemy_templates.SIZE:#x} bytes, up to "
        f"g_BtlItemRowsByNumber (0x800A9A56), = {enemy_templates.COUNT} rows of "
        f"{enemy_templates.STRIDE:#x} and {enemy_templates.TAIL:#x} bytes over, which are "
        "not a row and are not shown")
    # BtlEnemyLoad (0x8002B3AC) -> BtlEnemyStatsSet (0x8002A638) reads row id - 1
    # for each id a formation names.
    meta["formation_ids_up_to"] = encounters.max_enemy_id(image)
    meta["field_notes"] = enemy_templates.NOTES
    meta["caveat"] = (
        "The fields carry btl.h's names (BtlEnemyRow). `battle_record` is the row "
        "put through BtlEnemyStatsSet (0x8002A638), the copier: the stats (BtlStats) "
        "the battle starts the enemy with, each named as btl.h names it and noted "
        "with the code that reads it. The row's +0x19 (pad_19) is not copied; the "
        "stats' mp and status (+0x15) do not come from the row.")
    meta["battle_record_notes"] = enemy_templates.BATTLE_NOTES
    docs["enemy_templates"] = {
        "_meta": meta,
        "records": [enemy_templates.to_dict(r)
                    for r in enemy_templates.read_from_exe(image)]}

    meta = _meta(f"{RECORDS}.items", exe_name,
                 pointer_symbol=items.POINTER_SYMBOL,
                 table_base=hex(address(image, "g_BtlItemTable", items.BASE_ADDR)),
                 stride=items.STRIDE,
                 count=items.COUNT)
    meta["count_basis"] = ("ChrItemUseGet (0x80058088) answers -2 for an item number "
                           "of 0 or above 0xB6")
    meta["field_notes"] = items.NOTES
    docs["items"] = {
        "_meta": meta,
        "records": [items.to_dict(r) for r in items.read_from_exe(image)]}

    spell_rows = spells.read_from_exe(image)
    meta = _meta(f"{RECORDS}.spells", exe_name,
                 index_global=spells.INDEX_GLOBAL,
                 table_base=hex(address(image, "g_BtlSpellRowsByNumber", spells.BASE_ADDR)),
                 stride=spells.STRIDE,
                 count=spells.COUNT)
    meta["field_notes"] = spells.NOTES
    meta["unread_offsets"] = [hex(o) for o in spells.UNREAD_OFFSETS]
    docs["spells"] = {"_meta": meta,
                      "records": [spells.to_dict(r) for r in spell_rows]}

    meta = _meta(f"{RECORDS}.attack_classes", exe_name,
                 table_base=hex(address(image, "g_BtlAttackRows", attack_classes.BASE_ADDR)),
                 stride=attack_classes.STRIDE, count=attack_classes.COUNT)
    meta["field_notes"] = attack_classes.NOTES
    meta["unread_offsets"] = [hex(o) for o in attack_classes.UNREAD_OFFSETS]
    meta["param_globals"] = attack_classes.PARAM_GLOBALS
    docs["attack_classes"] = {
        "_meta": meta,
        "records": [attack_classes.to_dict(r)
                    for r in attack_classes.read_from_exe(image)]}

    dx, dy = battle_constants.read_direction_tables(image)
    heal = spell_rows[SPELL_33_ROW]
    docs["battle_runtime"] = {
        "_meta": _meta(f"{RECORDS}.battle_constants", exe_name,
                       note="the field's facing step tables g_MapFacingDxs "
                            "(0x80012C1C) / g_MapFacingDys (0x80012C24) that "
                            "MapSpotMove (0x80066848) reads (not the battle's), "
                            "the RNG's functions and spell 33's row"),
        "dir_dx": dx,
        "dir_dy": dy,
        "rng": {"seed_function": battle_constants.RNG_SEED_FUNC,
                "note": "the game seeds its own generator; there is no table"},
        "spell_33": {"row": SPELL_33_ROW, **heal.values,
                         "raw": heal.raw.hex()},
    }

    buf = resources[party_init.RESOURCE].read(archive)
    item_lookup = party_init.exe_items(image)
    members = party_init.party(buf, item_lookup)
    raw = party_init.level1_records(party_init.parse(buf), item_lookup)
    docs["party"] = {
        "_meta": {
            "source": {"kind": "lunadata", "producer": f"{FORMATS}.party_init",
                       "archive": "LUNADATA.FIL", "resource": party_init.RESOURCE,
                       "items": "EXE item table "
                                f"{address(image, 'g_BtlItemTable', items.BASE_ADDR):#x} "
                                "(records.items)",
                       "levels": "EXE level-up tables "
                                 f"{address(image, 'g_ChrLevelGainTable', level_up.GAINS_ADDR):#x}"
                                 " + spell rows "
                                 f"{address(image, 'g_BtlSpellRows', level_up.SPELL_ROWS_ADDR):#x}"
                                 " (records.level_up)"},
            "chain": "ChrRecordsReset (0x80063B30) (load 0xE7, memmove 12 x 0x40, equip via "
                     "ChrWornItemSet (0x80057FFC) -> ChrWornItemValuesAdd (0x800587D0) -> ChrWornItemStatAdd (0x80058910)) then "
                     "BtlPartyStatsSet (0x8002A138) (battle record + weapon-kind anim picks); "
                     "levels: ScriptCommandChrLevelItemSet (0x8005D2F0) -> ChrLevelAdd (0x8002844C) -> ChrLevelUp (0x80028554)",
            "notes": {"battle_record": "CharStats as BtlPartyStatsSet (0x8002A138) writes it at "
                                       "battle entry; bytes it does not write are 0",
                      "spells": "spell numbers (the spells table's rows) in the "
                                "slot ChrLevelUp (0x80028554)'s jtbl_800118DC gives each id",
                      "by_level": "columns, index i = level first + i: the battle "
                                  "record at each level as ScriptCommandChrLevelItemSet (0x8005D2F0) sets it — "
                                  "ChrLevelAdd (0x8002844C) raises the level-1 record "
                                  "(ChrLevelUp (0x80028554) per level), HP / MP refilled — "
                                  "with the starting equipment kept",
                      "place_preset": "the character's ChrPlacePresetRecord (chr.h) as a new game "
                                      "starts: ChrRecordsReset (0x80063B30) copies the 8 bytes at 0x342 "
                                      "on to *g_ChrPlacePresetRecords (0x800B8C74) + id * 8. Before a "
                                      "fight MapBtlRun (0x8007AE58) copies place_x (less the battle's "
                                      "x shift) and place_y to g_BtlPartyPlaceXCells (0x800B8E88) / "
                                      "g_BtlPartyPlaceYCells (0x800B8E90), and BtlPartyLoad (0x8002B114) "
                                      "puts the member at x = cell * 8, y = cell * 8; the presets "
                                      "are three (kind, number) pairs"}},
        "characters": [
            {"char_id": m.char_id,
             "level1": {k: (list(v) if isinstance(v, tuple) else v)
                        for k, v in vars(m.level1).items()},
             "starting_equipment": list(m.starting_equipment),
             "battle_record": m.battle.fields(),
             "by_level": party_init.by_level(
                 raw[m.char_id], m.char_id, item_lookup,
                 lambda r, lv, cid=m.char_id: level_up.set_level(r, cid, lv, image),
                 last=level_up.LEVEL_CAP),
             "place_preset": vars(party_init.place_preset(m.place_preset))}
            for m in members],
    }
    return docs

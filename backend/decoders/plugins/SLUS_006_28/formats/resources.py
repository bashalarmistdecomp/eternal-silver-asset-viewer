"""What each LUNADATA resource is, by number.

The game reads LUNADATA.FIL only by resource number (resource_table), and
the resources lie in regions by what reads them: the maps, the scripts, the
portraits, the sound banks, ... This module is that map, as written in
docs/spec/file-sector-map/overview.md §"The resources, by number" and
docs/spec/overview.md §"The resource sector table": number ranges, what the
resources are, the function that reads them, and whether that reader runs
them as a command list (resource_command_run (0x800202FC), formats.
command_list) or takes them as they lie. It holds no bytes of the game; the
sectors and the contents come from the user's disc at run time.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The numbers the C computes resources from.
PORTRAIT_FILE_BASE = 0xA2       # FaceDataLoad (0x8001B1C0): resource = file + 0xA2
SCENE_PORTRAIT_BASE = 0xBA      # FaceSlot6Load (0x8001B50C): resource = block + 0xBA
BROMIDE_BASE = 0x24A            # PictureShow(k) (0x80024A7C): resource = 0x24A + k
DISC_CHANGE = 0x257             # overlay_disc_wait (0x80023184), GameRun (0x800559F4)
LAST = 0x257                    # resources 1 to 599; pair 0x258 is empty


@dataclass(frozen=True)
class Region:
    """A run of resources read the same way."""
    first: int
    last: int
    key: str            # a short name for the region
    what: str           # what the resources are
    reader: str         # the code that reads them, as the register names it
    commands: bool      # True: the reader runs them through resource_command_run

    def __contains__(self, n: int) -> bool:
        return self.first <= n <= self.last


REGIONS: tuple[Region, ...] = (
    Region(1, 1, "system",
           "SYSTEM.DAT: the string table, the glyph atlas, three UI palettes",
           "main (0x80013D2C) -> resource_load_run(1) (0x800202CC)", True),
    Region(2, 2, "common-sheet",
           "STFIELD.DAT: the common sprite sheet (palette row 507, three sprite "
           "data blocks, a 4-bit page)",
           "sprite_reset (0x80018DBC)", False),
    Region(3, 3, "title",
           "OPEN1.BIN: the title screen (cards, pages, the sky and the planets)",
           "StartResourceLoad (0x8004409C)", True),
    Region(4, 100, "maps", "a map: one of the 97, a command list each",
           "MapResourceLoad (0x80020D70), by g_MapResourcePairs (0x800AF364)", True),
    Region(101, 162, "scripts", "a script: one of the 62",
           "ScriptResourceLoad (0x80020D20), by g_ScriptResourcePairs (0x800AF268)", False),
    Region(163, 186, "portrait-files", "a portrait file: a FACE block of five faces",
           "FaceDataLoad (0x8001B1C0)", False),
    Region(187, 228, "scene-portraits", "a scene portrait block: a FACE block of up to ten faces",
           "FaceSlot6Load (0x8001B50C)", False),
    Region(229, 230, "sprite-palettes", "a field sprite palette (rows 504 and 505)",
           "sprite_init (0x80018BFC)", False),
    Region(231, 231, "party-records", "the party's starting records",
           "ChrRecordsReset (0x80063B30)", False),
    Region(232, 232, "sound-common", "the common sound bank: the sound effects",
           "sound_common_load (0x80023E00) -> sound_bank_load (0x80024138)", True),
    Region(233, 293, "sound-music", "a music bank",
           "sound_music_load (0x80023E9C) -> sound_bank_load (0x80024138)", True),
    Region(294, 357, "sound-area", "an area's sound bank",
           "sound_area_load (0x80023F78) -> sound_bank_load (0x80024138), "
           "by g_SoundAreaBankPairs (0x800AF694)", True),
    Region(358, 358, "sound-battle", "the battle's sound bank",
           "sound_bank_load (0x80024138), bank slot 1 in battle; "
           "sound_btl_seek (0x80024044) seeks it", True),
    Region(359, 406, "battle-sets", "a monster set: one of the 48",
           "BtlDataLoad (0x80018694), by g_BtlDataResources (0x800A7E18)", False),
    Region(407, 407, "battle-party", "the battle's party bundle",
           "BtlPartyDataLoad (0x80018A78)", False),
    Region(408, 471, "effects", "a spell or item effect",
           "BtlEffectLoad (0x800897DC), by g_BtlEffectResourceNumbers (0x800B5E0C)", False),
    Region(472, 487, "effect-layers", "an effect's background layer",
           "tile_resource_load (0x8001DAE4), by g_TileResourceRows (0x800AE128)", True),
    Region(488, 488, "party-sheets", "the party's field sprite sheets",
           "MapPartySpriteDataLoad (0x80063D48)", False),
    Region(489, 585, "object-sets", "a map object set: one of the 97",
           "MapObjectsDataLoad (0x80065418), by g_MapObjectsDataResourceNumbers (0x800B4E2C)",
           False),
    Region(586, 598, "bromides", "a bromide: two pictures",
           "PictureShow (0x80024A7C)", True),
    Region(599, 599, "disc-change",
           "the disc-change screens and the two pictures after the game's end",
           "overlay_disc_wait (0x80023184) -> cd_change_wait (0x80024D2C); "
           "GameRun (0x800559F4)", True),
)


def region(n: int) -> Region | None:
    """The region resource `n` lies in; None outside 1..599."""
    for r in REGIONS:
        if n in r:
            return r
    return None


def is_command_list(n: int) -> bool:
    """Does the code that reads resource `n` walk it with resource_command_run?"""
    r = region(n)
    return bool(r and r.commands)


def number_in_region(n: int) -> str | None:
    """The number the code reads resource `n` by, where the C states it:
    'portrait file 3', 'scene block 12', 'bromide 4'; None elsewhere."""
    r = region(n)
    if r is None:
        return None
    if r.key == "portrait-files":
        return f"portrait file {n - PORTRAIT_FILE_BASE}"
    if r.key == "scene-portraits":
        return f"scene block {n - SCENE_PORTRAIT_BASE}"
    if r.key == "bromides":
        return f"bromide {n - BROMIDE_BASE}"
    return None

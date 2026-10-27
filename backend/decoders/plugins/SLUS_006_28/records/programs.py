"""The programs these readers read, and where each keeps its tables.

Two programs are one game here: SLUS_006.28, and the Japanese original
SLPS_013.97, a 1998 GCC 2.7.2 build of the same source. Their code is laid
out alike, function for function, but their data sits elsewhere. A reader
names the table it reads by the US register's name and passes its US
address; `address` gives the address the table has in the program the
image is.

Every Japanese address below was found by the code that reads it: the
Japanese function that does what the US reader does (the same calls, in
the same order, at the same place in the code) forms that address, and
each row names that function as `Name (US address; SLPS_013.97 address)`.
Most tables also hold the same bytes in both programs; the rows say where
they do not. A table not found that way has no row: a reader that needs it
raises `Unmapped`, and the tab says so.

A program is told from its image by its build stamp, g_BuildStamp
(0x80011000), the first bytes of its data; MENU.BIN begins with the same
text (overlay_stamp_check (0x800232B0) compares the two). STAMPS keeps a
digest of each stamp, not its text. An image whose stamp is neither is no
program these readers know: `program_of` answers None, and `address` and
`has` raise UnknownProgram, since reading it as the US program would give
plausible numbers instead of an error. (The tests' made-up images carry no
stamp; the tests' conftest reads that one as the US program.)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

US = "SLUS_006.28"
JP = "SLPS_013.97"
PROGRAMS = (US, JP)

#: Where the image the readers take begins: g_BuildStamp (0x80011000).
EXE_BASE = 0x80011000
#: Bytes enough for any stamp and its 0.
STAMP_MAX = 0x40

#: sha1 of each program's build stamp, its text up to the 0.
STAMPS = {
    "e51e5e436bb4f043fd31c817b578744e3994d1bc": US,
    "a1ac9aa3386797a23fb08dff55886d0debf63d58": JP,
}


class Unmapped(LookupError):
    """A table not located in the program the image is."""


class UnknownProgram(Unmapped):
    """An image whose build stamp is no program's in STAMPS: where its
    tables are is not known at all."""


@dataclass(frozen=True)
class Table:
    addr: int
    proof: str          # the function that forms the address, in that program
    note: str = ""


def _jp(addr: int, proof: str, note: str = "") -> Table:
    return Table(addr, proof, note)


#: SLPS_013.97's tables, by the US register's name.
JP_TABLES: dict[str, Table] = {
    # resources and maps
    "g_ResourceSectorPairs": _jp(
        0x800ACC90, "resource_load (0x80020230; SLPS_013.97 0x80021A08), "
        "resource_seek (0x80020290; SLPS_013.97 0x80021A60)",
        "601 pairs, as in the US program; resources are numbered as there, "
        "the sectors are this disc's"),
    "g_ScriptResourcePairs": _jp(
        0x800AD5F4, "ScriptResourceLoad (0x80020D20; SLPS_013.97 0x80022598)"),
    "g_MapResourcePairs": _jp(
        0x800AD6F0, "MapResourceFind (0x80020CD0; SLPS_013.97 0x80022548), "
        "MapNumberFind (0x80020CF8; SLPS_013.97 0x80022570)"),
    "g_MapTblNumbers": _jp(
        0x800B2804, "MapTblGet (0x80068618; SLPS_013.97 0x8006BB94)"),
    "g_MapTbls": _jp(
        0x800B28A4, "MapTblGet (0x80068618; SLPS_013.97 0x8006BB94)"),
    "g_MapObjectsDataResourceNumbers": _jp(
        0x800B2498, "MapObjectsDataLoad (0x80065418; SLPS_013.97 0x80068918)"),
    "g_MapTwinSpriteDataNumbers": _jp(
        0x8001341C, "MapPartySpriteDataLoad (0x80063D48; SLPS_013.97 0x8006720C), "
        "MapObjectInit (0x800656CC; SLPS_013.97 0x80068BD0)",
        "the code forms the address less 1 and adds the number"),
    "g_MoveSpeedPixels": _jp(
        0x80013428, "MoveCommandMoveBy (0x8006312C; SLPS_013.97 0x800665C8), "
        "StepCommandMoveBy (0x8006382C; SLPS_013.97 0x80066CDC)"),
    "g_MoveSpeedIntervals": _jp(
        0x80013430, "MoveCommandMoveBy (0x8006312C; SLPS_013.97 0x800665C8), "
        "StepCommandMoveBy (0x8006382C; SLPS_013.97 0x80066CDC)"),
    "g_TileAnimationSets": _jp(
        0x800AECA0, "tile_animation_set (0x800265BC; SLPS_013.97 0x80029DA8)"),
    "g_TileAnimationRows": _jp(
        0x800AECE8, "tile_animation_set (0x800265BC; SLPS_013.97 0x80029DA8)"),
    "g_PaletteAnimationSets": _jp(
        0x800AE880, "palette_animation_set (0x800262FC; SLPS_013.97 0x80029AE0)"),
    "g_PaletteAnimationRows": _jp(
        0x800AE8D0, "palette_animation_set (0x800262FC; SLPS_013.97 0x80029AE0)"),
    "g_PaletteAnimationCopyRows": _jp(
        0x800AEE68, "palette_animation_copy_set (0x8002628C; SLPS_013.97 0x80029A34)"),
    "g_MapFacingDxs": _jp(
        0x80013438, "MapSpotMove (0x80066848; SLPS_013.97 0x80069D50)"),
    "g_MapFacingDys": _jp(
        0x80013440, "MapSpotMove (0x80066848; SLPS_013.97 0x80069D50)"),
    # the program's own text
    "g_BuildStamp": _jp(
        0x80011000, "build_stamp_compare (0x80013D08; SLPS_013.97 0x800148CC)"),
    "g_OverlayFileName": _jp(
        0x80011DEC, "overlay_load (0x80023240; SLPS_013.97 0x80025B7C), "
        "overlay_disc_wait (0x80023184; SLPS_013.97 0x80025ABC)"),
    "g_CardSavePlaceNames": _jp(
        0x800A7058, "card_save_title_set (0x8001BF50; SLPS_013.97 0x8001DC0C)",
        "the names it points at are two-byte Shift-JIS, which the function "
        "copies two bytes at a time into the memory-card title"),
    "D_800B857C": _jp(
        0x800B5C0C, "debug_sprite_page_show (0x80019044; SLPS_013.97 0x8001A54C)"),
    "D_800B8588": _jp(
        0x800B5C18, "sprite_draw (0x8001A528; SLPS_013.97 0x8001BA18)"),
    "D_800B8594": _jp(
        0x800B5C24, "IconCellSet (0x8001AF04; SLPS_013.97 0x8001C188)",
        "its assertion's line is 0x131"),
    "D_800B85A0": _jp(
        0x800B5CF0, "FaceSlotGet (0x8001B200; SLPS_013.97 0x8001CC00)",
        "its assertion's line is 0x9D"),
    "g_FileHostPathFormat": _jp(
        0x800B5DC0, "file_load (0x80021034; SLPS_013.97 0x80022D1C)"),
    "g_SimConsoleFileName": _jp(
        0x800B5DEC, "sim_console_write (0x80021740; SLPS_013.97 0x800237B8)"),
    "g_Lbits": _jp(
        0x800B5DF4, "inflate_block_dynamic (0x80021DD8; SLPS_013.97 0x80023E88)"),
    "g_FontStringCodes": _jp(
        0x800B18B4, "font_string_put (0x80026F78; SLPS_013.97 0x8002A788), "
        "MessageCodesConv (0x8005AC44; SLPS_013.97 0x8005DE5C)",
        "one word differs from the US table"),
    "g_FontPatterns9908": _jp(
        0x800AEE90, "font_pattern_get (0x80026B1C; SLPS_013.97 0x8002A3A0)"),
    # the event scripts
    "g_ScriptCommandFunctions": _jp(
        0x800B1738, "ScriptLabelRun (0x80059FDC; SLPS_013.97 0x8005D3E8)",
        "0x5F handlers, ids 0 to 0x5E: the US program's 0x5F and 0x60 are not there"),
    "g_ScriptMapBtlRows": _jp(
        0x800B1A60, "ScriptCommandMapBtlRun (0x8005DFF0; SLPS_013.97 0x8006137C)"),
    # battle
    "g_BtlDataResources": _jp(
        0x800A6840, "BtlDataLoad (0x80018694; SLPS_013.97 0x80019B98)"),
    "g_BtlEnemyRows": _jp(
        0x800A71A8, "BtlEnemyStatsSet (0x8002A638; SLPS_013.97 0x8002DEDC)",
        "the same extent as the US table; many rows hold other values"),
    "g_BtlItemTable": _jp(
        0x800A84A8, "func_80026AB0 (0x80026AB0; SLPS_013.97 0x8002A2DC), "
        "BtlActionStatus40Adjust (0x8002E9CC; SLPS_013.97 0x80032288)"),
    "g_BtlSpellRowsByNumber": _jp(
        0x800A9168, "BtlActionSpellRun (0x8002E718; SLPS_013.97 0x80031FD4)"),
    "g_BtlSpellRows": _jp(
        0x800A9174, "ChrLevelUp (0x80028554; SLPS_013.97 0x8002BD80), "
        "BtlMenuSpellDisp (0x80046258; SLPS_013.97 0x8004957C)",
        "one byte differs from the US table"),
    "g_BtlEnemyGroups": _jp(
        0x800A93B4, "BtlEnemyLoad (0x8002B3AC; SLPS_013.97 0x8002EC54)"),
    "g_BtlNumberRows": _jp(
        0x800AABB2, "BtlEnemyLoad (0x8002B3AC; SLPS_013.97 0x8002EC54)"),
    "g_BtlEnemySetIds": _jp(
        0x800AADB0, "BtlEnemyLoad (0x8002B3AC; SLPS_013.97 0x8002EC54)"),
    "g_BtlAttackRows": _jp(
        0x800AB080, "BtlActionRowRun (0x80031ABC; SLPS_013.97 0x800353A8), "
        "BtlEnemyKind7Pick (0x8004CF48; SLPS_013.97 0x80050368)"),
    "g_BtlEffectRows": _jp(
        0x800AAE7C, "BtlEffectLoad (0x800897DC; SLPS_013.97 0x8008AF48)",
        "the same bytes as the US table"),
    "g_ChrLevelGainTable": _jp(
        0x800AB478, "ChrLevelGainGet (0x80028520; SLPS_013.97 0x8002BD4C), "
        "ChrLevelUp (0x80028554; SLPS_013.97 0x8002BD80)"),
    # sound
    "g_MusicBankNumbers": _jp(
        0x80013150, "MusicPlay (0x80054F2C; SLPS_013.97 0x800583FC), "
        "MusicLoadStart (0x80055118; SLPS_013.97 0x800585EC)",
        "the code forms the address less 1 and adds the number"),
    "g_SoundMusicIndexSkips": _jp(
        0x800ADAC4, "sound_music_index_get (0x80023E20; SLPS_013.97 0x80026870)"),
    "g_SoundAreaBankPairs": _jp(
        0x800AD9B8, "sound_area_load (0x80023F78; SLPS_013.97 0x800269F8), "
        "sound_area_seek (0x80023FE0; SLPS_013.97 0x80026A64)",
        "the same bytes as the US table"),
    "g_SoundMapAreas": _jp(
        0x800ADACC, "sound_area_get (0x80024784; SLPS_013.97 0x800273C0)",
        "the same bytes as the US table"),
    "_spu_rev_startaddr": _jp(
        0x800B564C, "_SpuInit (0x8009DCF8; SLPS_013.97 0x800A0838), "
        "SpuSetReverbModeParam (0x8009F618; SLPS_013.97 0x800A20F8)"),
    "_spu_rev_param": _jp(
        0x800B569C, "SpuSetReverbModeParam (0x8009F618; SLPS_013.97 0x800A20F8)"),
    # the voices
    "g_XaVoices": _jp(
        0x800ACA32, "xa_voice_get (0x800238BC; SLPS_013.97 0x80026338)",
        "105 entries, as in the US program; the places are this disc's"),
    "g_XaChannelEnds": _jp(
        0x800ACB04, "xa_voice_get (0x800238BC; SLPS_013.97 0x80026338)",
        "the function takes 2 off every end and reads no D_800AF62C"),
    # the bromides
    "g_PictureVoices": _jp(
        0x800AE378, "PictureXaPlay (0x800247AC; SLPS_013.97 0x80028804)"),
    # MENU.BIN, the movie player
    "D_8019769C": _jp(
        0x80197748, "movie_play (0x80196B54; SLPS_013.97 MENU.BIN 0x80196BFC)",
        "29 of its 55 end frames differ from the US table"),
}

#: The other program's tables, by program.
TABLES: dict[str, dict[str, Table]] = {JP: JP_TABLES}


@lru_cache(maxsize=16)
def stamp_digest(head: bytes) -> str:
    """sha1 of a stamp: `head`'s bytes up to the first 0."""
    return hashlib.sha1(bytes(head[:STAMP_MAX]).split(b"\0", 1)[0]).hexdigest()


def _head(image) -> bytes:
    if hasattr(image, "read_bytes"):            # exe_loader.LoadedBinary
        try:
            return bytes(image.read_bytes(EXE_BASE, STAMP_MAX))
        except (ValueError, IndexError):
            return b""
    return bytes(image[:STAMP_MAX])


def program_of(image) -> str | None:
    """The program `image` is: the program's image from 0x80011000 (bytes),
    a loaded binary, or MENU.BIN's bytes. None when the stamp is not known."""
    return STAMPS.get(stamp_digest(_head(image)))


def _known(image, name: str) -> str:
    program = program_of(image)
    if program is None:
        raise UnknownProgram(f"{name}: the image's build stamp is not one of "
                             f"{', '.join(PROGRAMS)}, so where its tables are is not known")
    return program


def address(image, name: str, us_addr: int) -> int:
    """Where table `name` (at `us_addr` in the US program) is in `image`'s
    program. Raises Unmapped when that program's table was not found, and
    UnknownProgram when the program is none of PROGRAMS."""
    program = _known(image, name)
    if program == US:
        return us_addr
    row = TABLES.get(program, {}).get(name)
    if row is None:
        raise Unmapped(f"{name} ({us_addr:#010x}) is not located in {program}")
    return row.addr


def has(image, name: str) -> bool:
    """True when `image`'s program has table `name` located. Raises
    UnknownProgram when the program is none of PROGRAMS."""
    program = _known(image, name)
    return program == US or name in TABLES.get(program, {})

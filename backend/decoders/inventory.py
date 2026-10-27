"""What the decoders parse, and out of which raw file.

**Read this before you write code that parses game bytes.** If a format is
already decoded here, call the decoder; if it is not, add a module and
register it here, rather than decoding inline in a tab, so the next reader
finds it.

    python3 -m decoders.inventory              # the whole index
    python3 -m decoders.inventory sprite       # search: module/summary/api
    python3 -m decoders.inventory --check      # drift check (also a test)

(run from backend/, with the repo's venv)

Each entry states what the decoder READS, which source kinds its output
may claim (the bytes of a LUNADATA resource, a disc file, static data in
the EXE, or what ported game code computes), its entry points, where the
format is written up, its tests, and — for one game's decoders — the
functions in that game's program whose reading PROVED the format. The
viewer shows those last two under "proven by" next to what it decoded.

`spec` paths are pages of the SSSC decompilation's documentation
(`SPEC_REPO`, docs/spec/...), where each format is written up.

**Adding a module?** Add its entry here in the same commit: `--check`
(and the test suite) fail on any module without one.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
#: backend/decoders -> the repository root
ROOT_DIR = PKG_DIR.parents[1]

#: Where the `spec` pages are: the public SSSC decompilation.
SPEC_REPO = "eternal-silver-sssc-decomp"

# -- source kinds: what an output's bytes are ----------------------------
KIND_ARCHIVE = "lunadata"          # a LUNADATA.FIL resource / TOC entry
KIND_DISC_FILE = "disc-file"       # some other file on the disc image
KIND_EXE = "exe-image"             # static data in the program file (the EXE)
KIND_TRANSCRIBED = "transcribed"   # computed by ported game code
SOURCE_KINDS = frozenset({KIND_ARCHIVE, KIND_DISC_FILE, KIND_EXE, KIND_TRANSCRIBED})
#: A codec's output is whatever kind its input was.
ANY_SHIPPABLE = SOURCE_KINDS

# Packages whose modules must all be inventoried, as paths under decoders/.
# Anything else (plumbing like config.py and _env.py) is exempt by not being
# here. psx/* is PlayStation knowledge; plugins/<serial>/* is one program's.
COVERED_PACKAGES = ("psx/formats", "psx/disc", "psx/analysis", "psx/gamedb",
                    "plugins/SLUS_006_28/formats",
                    "plugins/SLUS_006_28/records")


@dataclass(frozen=True)
class Decoder:
    """One inventoried module: what it reads and what it may produce."""

    module: str                  # dotted path, e.g. "decoders.psx.formats.tim"
    summary: str                 # one line, the searchable description
    reads: str                   # the raw input it consumes
    produces: frozenset          # source kinds its output may claim
    api: tuple                   # entry points worth knowing about
    spec: str = ""               # a page under SPEC_REPO, "" if none
    note: str = ""               # trap, caveat, or scope limit
    tests: str = ""              # repo-relative test module, "" if none
    #: Functions in the PROGRAM whose reading established this format —
    #: the code that PROVES it, as opposed to `spec`, which is where the
    #: conclusion was written down. Only a per-program plugin decoder may
    #: name any: a `psx/` decoder reads a Sony format and is proven by the
    #: format, not by one game's code.
    proven_by: tuple = ()

    @property
    def serial(self) -> str:
        """The PROGRAM this decoder belongs to, or "" for a generic one."""
        parts = self.module.split(".")
        if len(parts) > 2 and parts[1] == "plugins":
            return unmangle(parts[2])
        return ""

    @property
    def file(self) -> Path:
        return (PKG_DIR.parent / Path(*self.module.split("."))).with_suffix(".py")

    @property
    def test_file(self) -> Path | None:
        return (ROOT_DIR / self.tests) if self.tests else None

    def to_dict(self) -> dict:
        return {"module": self.module, "summary": self.summary,
                "reads": self.reads, "produces": sorted(self.produces),
                "api": list(self.api), "spec": self.spec, "note": self.note,
                "tests": self.tests, "proven_by": list(self.proven_by)}


def unmangle(pkg: str) -> str:
    """`SLUS_006_28` -> `SLUS_006.28` — the inverse of `plugins.mangle`.

    A package name cannot hold a `.`, so the directory carries the mangled
    serial and this puts it back. Only the LAST underscore is a dot; the
    first separates the letters from the number.
    """
    head, _, tail = pkg.rpartition("_")
    return f"{head}.{tail}" if head else pkg


def _d(module, summary, reads, produces, api, spec="", note="", tests="",
       proven_by=()):
    return Decoder(module, summary, reads, frozenset(produces), tuple(api),
                   spec, note, tests, tuple(proven_by))


# ======================================================================
# formats/ — the file and container decoders
# ======================================================================
FORMATS = [
    _d("decoders.plugins.SLUS_006_28.formats.lunadata",
       "The LUNADATA.FIL archive's own table of contents: 46 named entries, "
       "and the FACE blocks found by their magic word.",
       "LUNADATA.FIL",
       [KIND_ARCHIVE],
       ["LunaDataArchive", "ArchiveEntry"],
       "docs/spec/overview.md",
       "The program never reads the table of contents: it reads resources "
       "by number (resource_table). The names are kept for the resources "
       "they start at.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_lunadata.py"),

    _d("decoders.plugins.SLUS_006_28.formats.resource_table",
       "The EXE's index into LUNADATA.FIL: g_ResourceSectorPairs "
       "(0x800AE904), 601 [first sector, sectors] pairs, resources 1 to "
       "599 back to back.",
       "the EXE + LUNADATA.FIL",
       [KIND_EXE, KIND_ARCHIVE],
       ["load_resource_table", "Resource"],
       "docs/spec/file-sector-map/overview.md",
       "THE answer to 'which resource is at index N'. The table ends at "
       "g_ScriptResourcePairs (0x800AF268); pair 0 (the table of contents' "
       "span) and pair 0x258 (empty) are left out. The address resolves "
       "through decoders.psx.analysis.symbols.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_resource_table.py",
       proven_by=("resource_load (0x80020230)", "resource_load_run (0x800202CC)",
                  "resource_seek (0x80020290)")),

    _d("decoders.plugins.SLUS_006_28.formats.resources",
       "What each LUNADATA resource is, by number: the regions 1 to 599 "
       "(maps, scripts, portraits, sound banks, battle sets, effects, object "
       "sets, bromides, ...), the code that reads each and whether it runs "
       "a command list.",
       "nothing: number ranges and text from the specification",
       [KIND_ARCHIVE],
       ["Region", "REGIONS", "region", "is_command_list", "number_in_region",
        "PORTRAIT_FILE_BASE", "SCENE_PORTRAIT_BASE", "BROMIDE_BASE",
        "DISC_CHANGE", "LAST"],
       "docs/spec/file-sector-map/overview.md",
       "Knowledge, not bytes: what a resource holds is read from the user's "
       "disc (resource_table, command_list). The archive's TOC names 46 of "
       "the 599; the game reads none of them by name.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_resources.py",
       proven_by=("resource_load (0x80020230)", "MapResourceLoad (0x80020D70)",
                  "ScriptResourceLoad (0x80020D20)", "FaceDataLoad (0x8001B1C0)",
                  "FaceSlot6Load (0x8001B50C)", "sound_bank_load (0x80024138)",
                  "BtlDataLoad (0x80018694)", "BtlEffectLoad (0x800897DC)",
                  "tile_resource_load (0x8001DAE4)", "MapObjectsDataLoad (0x80065418)",
                  "PictureShow (0x80024A7C)", "overlay_disc_wait (0x80023184)")),

    _d("decoders.plugins.SLUS_006_28.formats.disc_files",
       "What each file on a game disc is (the spec's file tables) and the "
       "build stamp overlay_stamp_check (0x800232B0) compares: "
       "g_BuildStamp (0x80011000) against the text MENU.BIN begins with.",
       "file names; the EXE image and MENU.BIN's first bytes",
       [KIND_EXE],
       ["FileRole", "role", "movie_number", "MOVIE_ROLE", "c_string",
        "program_stamp", "overlay_file_name", "StampCheck", "stamp_check", "show",
        "OVERLAY_BASE", "STAMP_MAX"],
       "docs/spec/overview.md",
       "Knowledge as text, keyed by the file names the spec gives; the "
       "stamps are read from the user's disc. On a mismatch overlay_load "
       "calls an empty assert_fail and uses the overlay anyway, while "
       "overlay_disc_wait asks for the disc again.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_disc_files.py",
       proven_by=("overlay_load (0x80023240)", "overlay_stamp_check (0x800232B0)",
                  "build_stamp_compare_copy (0x80013DE4)",
                  "build_stamp_compare (0x80013D08)",
                  "overlay_disc_wait (0x80023184)", "MoviePlay (0x800232D4)",
                  "GameRun (0x800559F4)", "VoiceSet (0x80055470)")),

    _d("decoders.plugins.SLUS_006_28.formats.command_list",
       "The resource command list (resource_command_run, 0x800202FC): the container most "
       "LUNADATA resources are — {u32 word, u32 size, payload} entries, "
       "dispatched by the word's low byte.",
       "any general resource read via resource_table",
       [KIND_ARCHIVE],
       ["commands", "effective", "pictures", "describe", "summary", "Command",
        "CommandType", "TYPES", "STRINGS", "TIM", "TEXTURE_PAGE", "PALETTE",
        "MAP_LAYOUT", "MAP_ATTRIBUTES", "SECOND_LAYER", "MAP_ENTER_TABLES",
        "PALETTE_ROW", "VAB_HEAD", "VAB_BODY", "SEQUENCE", "TILE_ANIMATION",
        "SOUND_IDS", "TILE_PATTERN"],
       "docs/spec/overview.md",
       "Every type the switch dispatches (1-7, 9, 12-18) is named in TYPES "
       "with its handler; describe() says what an entry is by its type and "
       "sub-number. A fixed-destination type's LAST entry is the one in "
       "effect. The contents of 9, 16 and 17 are not decoded here.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_command_list.py",
       proven_by=("resource_command_run (0x800202FC)", "resource_load_run (0x800202CC)",
                  "resource_tim_add (0x800208A0)")),

    _d("decoders.plugins.SLUS_006_28.formats.event_script",
       "The map event-script bytecode: label table, command lengths for "
       "all 97 commands, a linear sweep and the BATTLE (0x2B) commands.",
       "an event-script resource in LUNADATA.FIL (g_ScriptResourcePairs (0x800AF268) -> "
       "records.areas byte 8), g_FontStringWords (0x800B386C) and g_ScriptMapBtlRows (0x800B366C) in the EXE image",
       [KIND_ARCHIVE, KIND_EXE],
       ["labels", "sweep", "script_code", "command_count", "label_boundaries", "battles",
        "flag_uses", "movie_plays", "objects_changed", "labels_reaching", "command_labels", "pair_flag",
        "chest_pair_flag", "party_flag", "FlagUse", "FLAG_COMMANDS",
        "scene_changes", "encounter_row", "encounter_rows", "script_resources",
        "actor_spawns", "script_switches", "party_kinds_set", "map_scripts",
        "text_end", "spells_given", "Command", "Gap", "EncounterRow", "ActorSpawn"],
       "docs/spec/code/subsystems/npc-scripting.md",
       "Every label starts a command, so a linear sweep from the lowest "
       "label sees every reachable command; all 62 scripts tile with every "
       "label on a command boundary. Script 200 (the world map's select "
       "menu) has 0xFFFF filler between entries. `scene_changes` lists the "
       "scene entries a script carries inline (0x26 with index 0, and "
       "0x5D): destination map c[6], object set c[0x10] — the one way a "
       "map is entered with a set no scene table names (one retail case: "
       "set 60 on map 30). `actor_spawns` reads the actors command 0x34 "
       "makes of its own (sprite data, kind, place, mode); `map_scripts` "
       "the scripts that can run on a map, by the commands that hand over.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_event_script.py",
       proven_by=("ScriptLabelRun (0x80059FDC)", "ScriptCommandLabelJump (0x8005BF5C)", "ScriptListCount (0x8005B5D8)",
                  "ScriptCommandMapBtlRun (0x8005DFF0)", "ScriptCommandMessageDisp (0x8005AB1C)", "font_string_walk (0x8005A884)",
                  "ScriptCommandMapChange (0x8005DB3C)", "ScriptCommandMapScriptChange (0x8005F068)",
                  "ScriptCommandMoveChrRowActorSet (0x80061EAC)", "ScriptCommandScriptChange (0x8005BFCC)",
                  "ScriptCommandMapPartyKindSet (0x8005E890)")),

    _d("decoders.plugins.SLUS_006_28.formats.script_voices",
       "Where the event scripts play their voices (0x52 keeps one, 0x53 "
       "starts it) and which messages the window shows while one plays: "
       "the message up as it starts, and those that come up before anything "
       "can have ended it or waited for the player.",
       "event-script resources (event_script.script_code) and the string "
       "table system_strings reads",
       [KIND_ARCHIVE],
       ["script_voices", "plays", "voice_sets", "text_end", "Play", "Kept", "ScriptVoices",
        "TextEnd", "READS_DISC", "WAITS_FOR_PLAYER", "CLEARS_WINDOW"],
       "docs/spec/code/subsystems/npc-scripting.md",
       "No table ties a voice to a message: this follows a label's commands "
       "every way its tests go, calls and returns as ScriptLabelRun runs "
       "them, and keeps what the window shows. A voice ends at 0x54, the "
       "next 0x52, a disc read (READS_DISC: cd_sector_load and pc_load stop "
       "it) or the label's end; a message after the player was waited for "
       "is not counted, since the voice may be over by then.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_script_voices.py",
       proven_by=("ScriptCommandVoiceSet (0x8005E9FC)", "ScriptCommandVoiceStart (0x8005EA44)",
                  "ScriptCommandVoiceEndWait (0x8005EA8C)", "ScriptVoiceStep (0x8005A328)",
                  "ScriptFrameStep (0x8005A1F0)", "ScriptLabelRun (0x80059FDC)",
                  "ScriptCommandMessageDisp (0x8005AB1C)", "MessageControlRun (0x8005AF20)",
                  "MessageClose (0x8005A72C)", "ScriptCommandMessageTimedSet (0x8005EB04)",
                  "cd_sector_load (0x80020E88)", "pc_load (0x80021584)")),

    _d("decoders.plugins.SLUS_006_28.formats.world_map",
       "Assembled playable areas (world / area maps): a map resource's "
       "tile layer as bg_first_draw (0x80014058) draws it — texture pages, the CLUT rows "
       "the game MAKES of its palette (tile rows, the walk-behind overlay "
       "copy's rows, the second layer's row) and the type-5 layout — and "
       "its second layer as bg_second_draw (0x800148E0) reads it, all from its command "
       "list.",
       "a map resource (records.areas.map_resource -> resource_table)",
       [KIND_ARCHIVE],
       ["layout", "block_tiles", "tile_plane", "pages",
        "clut_rows", "decode_tile", "Tile", "attributes", "attribute_block",
        "attribute_plane", "second_layer", "palettes",
        "tile_clut_words", "overlay_clut_words", "layer2_clut_words",
        "fix_tile_palette", "overlay_keep_from", "words_rgba", "tile_depth",
        "render_tiles", "tile_texels", "layer2_cells", "layer2_is_empty",
        "decode_layer2_cell", "Layer2Cell", "layer2_row_draws", "Layer2Draw",
        "layer2_sheet", "layer2_texel", "render_second_layer",
        "second_layer_indexes", "layer2_image", "layer2_cluts",
        "LAYER2_MODES", "TILE_CLUT_VRAM_ROWS", "LAYER2_CLUT_VRAM_ROW"],
       "docs/spec/graphics.md",
       "Tileset != world map: the tileset is the 256x256 atlas, the world "
       "map is the placement data that assembles it. Layout = 256 offsets "
       "(16x16 blocks of 8x8 tiles, 2048 px square), blocks per "
       "bg_block_load (0x80014F3C) (zero / fill / LZSS / raw). All 97 maps share the "
       "format; the old 'section 5' byte scan rendered 25, in part. Type 6 "
       "is the attribute plane (collision and map-cell events, read by the "
       "scripting probes), not graphics: `attribute_plane` expands it to "
       "256 x 256 cell words of 8 x 8 px (16 x 16 blocks of 16 x 16 cells; "
       "raw at or above data_end). Type 7 is the second tile layer's cell "
       "map (`second_layer`: 0x4000 bytes, 128 rows of 64 s16), returned as "
       "stored — `render_tiles` draws layer 0 only; `layer2_row_draws` / "
       "`render_second_layer` are bg_second_draw (0x800148E0)'s reading of it (pairs, "
       "wide cells of 16 / 32 px, page 3 as 256 x 128 FOUR-bit texels, "
       "CLUT row 508). THE CLUT ROWS ARE NOT THE STORED PALETTE: "
       "palette_zero_fix (0x80020830) makes colour 0 of each row the transparent word and "
       "every other stored 0 an opaque black, and 0x001F is plain red. "
       "Rows 510 / 511 "
       "(`overlay_clut_words`) colour the overlay copy of a bit-13 tile: "
       "the roof an actor walks behind. A palette of 256 colours (maps 9 "
       "and 43) gives one row; the second is not read. What shows through "
       "a tile's hole is the second layer in its mode 0, else the frame's "
       "black clear (rendering.md, 'The field's draw rule').",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_world_map.py",
       proven_by=("bg_block_load (0x80014F3C)", "bg_first_draw (0x80014058)", "lz_unpack (0x80022BF8)",
                  "resource_tpage_load (0x8002097C)", "resource_palette_load (0x80020A08)", "resource_bg_set (0x80020B34)",
                  "bg_attribute_block_load (0x800154F8)", "resource_bg_attribute_set (0x80020B60)", "bg_attribute_data_reset (0x8001543C)",
                  "MapAttributeFreeCheck (0x800692D4)", "resource_bg_second_set (0x80020BD8)",
                  "bg_second_draw (0x800148E0)", "palette_zero_fix (0x80020830)", "palette_rows_set (0x8002061C)",
                  "palette_rows_load (0x80020588)", "palette_bg_second_row_set (0x80020670)", "palette_bg_cover_rows_set (0x800206D4)",
                  "MapLoad (0x80068A10)", "tpage_small_image_load (0x8002053C)")),

    _d("decoders.plugins.SLUS_006_28.formats.system_dat",
       "SYSTEM.DAT (resource 1) as the game loads it — the glyph atlas TIM "
       "under its four text sub-palettes, the palette rows 502, 503 and "
       "507, and the menu icons — and OPEN1.BIN's title-screen layers.",
       "SYSTEM.DAT / OPEN1.BIN out of LUNADATA.FIL",
       [KIND_ARCHIVE],
       ["parse_system_dat", "parse_open1_bin", "ParsedAsset", "block_places",
        "palette_rows", "bit15_set", "colours", "glyph_atlas",
        "glyph_atlas_layers", "sub_palette", "icon_offsets", "icon_pixels",
        "icon_image", "ICONS", "ICON_SIDE", "ICON_ROW", "ICON_COLOUR",
        "ICON_DIMMED"],
       "docs/spec/assets/battle-ui.md",
       "colours() is the GPU's rule, not parse_ps1_palette's: only the word 0 "
       "is not drawn. A stored 0 at any colour but 0 is drawn black once "
       "palette_bit15_set has given it bit 15. The type-1 block's +0x599C "
       "(palette-animation colours) is named, not decoded. The icon table "
       "is read up to where the first icon's pixels begin (nothing in the "
       "code bounds an icon number). OPEN1.BIN is still read by deflate-stream search, not by "
       "its commands.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_system_dat.py",
       proven_by=("resource_command_run (0x800202FC)",
                  "resource_tim_add (0x800208A0)", "tim_image_load (0x8002073C)",
                  "ankprint_glyph_draw (0x80025B90)",
                  "resource_palette_row_load (0x80020ACC)",
                  "palette_bit15_set (0x800207E8)",
                  "palette_glyph_zero_set (0x8002087C)",
                  "palette_rows_set (0x8002061C)",
                  "palette_rows_load (0x80020588)",
                  "IconInit (0x8001ABCC)", "IconImageLoad (0x8001ADEC)",
                  "IconCellDraw (0x8001AD60)", "IconCellSet (0x8001AF04)",
                  "lz_unpack (0x80022BF8)", "MenuCursorTextDisp (0x8006C8F0)",
                  "MenuCommandsDisp (0x8006C178)",
                  "MenuIconBytesDisp (0x8006C21C)")),

    _d("decoders.plugins.SLUS_006_28.formats.stfield",
       "STFIELD.DAT (resource 2) as sprite_reset reads it: row 507's "
       "palette, three sprite data (g_SpriteData0..2, their texel records "
       "pointed at page 10) and the 256 x 232 4-bit sheet of page 10; "
       "every use of a bank the C makes, with its sub-palette.",
       "STFIELD.DAT out of LUNADATA.FIL (resource 2)",
       [KIND_ARCHIVE],
       ["parse", "Stfield", "patch_pages", "sheet_image", "USES", "DIGITS",
        "sub_palette_of", "row_of", "bank_sub_palettes", "BANK_NAMES"],
       "docs/spec/assets/battle-ui.md",
       "Not a command list. The head's words 2, 4 and 6 are not read. "
       "Lines of page 10 past the unpacked image are not resource bytes.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_stfield.py",
       proven_by=("sprite_reset (0x80018DBC)", "sprite_draw (0x8001A528)",
                  "BtlRecordSpriteDataSet (0x80089A3C)", "BtlMenuInit (0x800441B4)",
                  "BtlAmountShowStart (0x80088EA8)",
                  "BtlShowRecordTravelRun (0x800859A8)",
                  "BtlShowPlacesPlay (0x8007F2D8)",
                  "MenuUseShowPlacesPlay (0x8007EFC0)", "ShopOpen (0x800506EC)",
                  "ShopObjectInit (0x80054948)", "MenuRecordsInit (0x8006AD38)",
                  "MessageRecordsInit (0x8005A580)",
                  "MapObjectsDataLoad (0x80065418)", "MapObjectInit (0x800656CC)",
                  "MapRecordInit (0x80065940)", "BtlAmountRecordsInit (0x8004A8A0)",
                  "BtlAmountRecordStart (0x8004AB40)")),

    _d("decoders.plugins.SLUS_006_28.formats.sprite_pages",
       "Sprite data: the block layout field and battle sprites share "
       "(animations, steps, poses, slices, texel records), the composer that "
       "draws a pose as sprite_draw (0x8001A528) does, and the field's "
       "palette rows 504 and 505.",
       "sprite data blocks from map_object_sets, party_field_sheets and "
       "battle_gfx; resources 0xE5 and 0xE6 in LUNADATA.FIL",
       [KIND_ARCHIVE],
       ["parse_actor_block", "compose_pose", "pose_extent", "list_poses",
        "pose_tpages", "pose_sheet", "clut_fixup", "sprite_init_palette",
        "clut_id", "palette_row", "SPRITE_INIT_PALETTES", "SpriteBlockData",
        "Pose", "Slice", "Animation", "PoseSheet"],
       "docs/spec/assets/sprites.md",
       "A pose is a STACK OF SLICES drawn back to front, not a rectangle — "
       "compose_pose does that assembly, transcribed from sprite_draw "
       "(0x8001A528) / sprite_piece_draw (0x80019DBC) / sprite_quad_draw "
       "(0x800174F0). Frame +0x00 is a FLAGS word (0x10/0x20 = mirror the "
       "slice, 0x7000 = slice kind). A block carries no palette: sprite_draw "
       "takes row 0x1F8 | ((draw word >> 8) & 3). On the field rows 504 and "
       "505 are resources 0xE5 and 0xE6 after sprite_init (0x80018BFC)'s "
       "fix-up; the row a record takes is map_object_sets.record_draw.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_sprite_pages.py",
       proven_by=("sprite_draw (0x8001A528)", "sprite_piece_draw (0x80019DBC)",
                  "sprite_mirror_draw (0x80016F44)", "sprite_quad_draw (0x800174F0)",
                  "sprite_piece_edges_get (0x80019BEC)", "sprite_init (0x80018BFC)",
                  "BtlAnimationStep (0x800272A8)", "MapAnimationStart (0x80066468)",
                  "MapPartyAnimationStep (0x80065CF8)",
                  "MapObjectsAnimationStep (0x80065FD8)")),

    _d("decoders.plugins.SLUS_006_28.formats.map_object_sets",
       "Map object sets: the resource g_MapObjectsDataResourceNumbers "
       "(0x800B4E2C) names for a set — its definition block, sprite data "
       "list and pages — and the palette row each object is drawn with.",
       "object-set resources and map resources in LUNADATA.FIL, via "
       "resource_table; tables in the EXE",
       [KIND_ARCHIVE, KIND_EXE],
       ["set_resources", "twin_numbers", "set_header", "sprite_data_rows",
        "sprite_data", "definition_block", "set_pages", "parse_object_set",
        "record_draw", "object_draws", "sprite_data_draws", "enter_rows",
        "map_palette", "palette_bit15_set", "undrawn_slices", "ObjectSet",
        "SetHeader", "SpriteDataRow", "Draw", "ObjectDraw", "EnterRow"],
       "docs/spec/assets/sprites.md",
       "Of a definition only bytes 0, 1 and 3 are read here (kind, sprite "
       "data, mode); where an object stands and what it starts on are "
       "field_objects'. A set is named by the maps whose enter rows name it. "
       "Row 506 is the entered map's own palette; kind 7 (the chest) draws "
       "resource 2's sprite data with row 507, which is not read here.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_map_object_sets.py",
       proven_by=("MapObjectsDataLoad (0x80065418)", "sprite_page_list_load (0x800182B8)",
                  "MapObjectsInit (0x800655C8)", "MapObjectInit (0x800656CC)",
                  "MapRecordInit (0x80065940)", "sprite_draw (0x8001A528)",
                  "MapChange (0x8005922C)", "resource_map_enter_table_set (0x80020B8C)",
                  "resource_palette_load (0x80020A08)", "palette_bit15_set (0x800207E8)",
                  "palette_rows_set (0x8002061C)", "palette_update (0x80020134)")),

    _d("decoders.plugins.SLUS_006_28.formats.party_field_sheets",
       "The party's field sheets (resource 0x1E8): a directory of sprite "
       "data and pictures, loaded by party id — own sheet, party-kind-0 "
       "sheet and twin — and the palette rows they are drawn with.",
       "resource 0x1E8 in LUNADATA.FIL, via resource_table; "
       "g_MapTwinSpriteDataNumbers in the EXE",
       [KIND_ARCHIVE, KIND_EXE],
       ["parse_directory", "row_count", "sprite_data_row", "load_sheet",
        "twin_numbers", "twin_number", "member_kind", "member_sheets",
        "party_uses", "DirectoryRow", "FieldSheet", "MemberSheets", "PartyUse"],
       "docs/spec/assets/sprites.md",
       "The directory's row count is read from its layout (the code never "
       "bounds a row). What the twin shows, and who id 0xCE is, the code "
       "does not say.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_party_field_sheets.py",
       proven_by=("MapPartySpriteDataLoad (0x80063D48)",
                  "MapPartySpriteDataReload (0x800642A4)",
                  "MapPartyRecordInit (0x800649DC)", "sprite_page_image_add (0x8001808C)",
                  "sprite_page4_image_load (0x80017EB0)",
                  "MapRecordSpriteDataSet (0x800645A8)", "MapRecordInit (0x80065940)",
                  "sprite_init (0x80018BFC)")),

    _d("decoders.plugins.SLUS_006_28.formats.field_objects",
       "Map objects on their map: the entries into a map (its enter table's "
       "rows and the scripts' map changes), the rows an object set's "
       "definitions make, where each stands and faces, the class it stands "
       "in, the animation it starts on, the party on an entry's spot, and "
       "the animation tick.",
       "map resources and object-set definition blocks in LUNADATA.FIL, via "
       "resource_table; the field's movement tables in the EXE",
       [KIND_ARCHIVE, KIND_EXE, KIND_TRANSCRIBED],
       ["field_tables", "definition", "made_definitions", "enter_row",
        "table_rows", "table_entries", "script_entry", "free_check", "class_get",
        "anim_table", "anim_start", "anim_set", "pose_set", "pose_set_id", "anim_tick",
        "twin_sync", "move_set", "place_objects", "story_flag", "chest_flag",
        "chest_contents", "chest_lock_flag", "chest_amounts",
        "party_box", "party_lead", "FieldTables", "Box", "Definition", "MapEntry",
        "ChestContents", "Attributes", "AnimTable", "AnimState", "MapObject",
        "PartyLead"],
       "docs/spec/code/subsystems/field-frame.md",
       "Every definition is made as if no event flag were set: an object a "
       "flag leaves out is made, and a chest is closed. The class probes and "
       "the animation setters and tick are transcribed from the C.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_field_objects.py",
       proven_by=("MapChange (0x8005922C)", "ScriptCommandMapChange (0x8005DB3C)",
                  "ScriptCommandMapScriptChange (0x8005F068)",
                  "MapObjectsInit (0x800655C8)", "MapObjectInit (0x800656CC)",
                  "MapRecordInit (0x80065940)", "MapObjectMoveSet (0x80065A2C)",
                  "MapAttributeClassGet (0x8006960C)",
                  "MapAttributeFreeCheck (0x800692D4)",
                  "MapAnimationPoseSet (0x8006633C)", "MapAnimationSet (0x800663EC)",
                  "MapAnimationStart (0x80066468)",
                  "MapObjectsAnimationStep (0x80065FD8)",
                  "MapPartyAnimationStep (0x80065CF8)",
                  "MapPartySpotSet (0x80064B8C)", "MapPartyRecordInit (0x800649DC)",
                  "MapPartyRingFill (0x80067064)", "MapPartyRingFollow (0x800671C4)",
                  "MapPartyBoxSet (0x8006497C)", "MapObjectKind7Run (0x80067F84)")),

    _d("decoders.plugins.SLUS_006_28.formats.field_picture",
       "A field map drawn whole with what stands on it: the tiles, the "
       "second layer where the game shows it behind them, the sprites in the "
       "field's depth and queue order, and the roof tiles drawn again over "
       "what stands under them.",
       "map resources in LUNADATA.FIL (world_map); sprites from field_objects",
       [KIND_ARCHIVE, KIND_TRANSCRIBED],
       ["body_entry", "queue_of", "cover_cells", "ground", "roof_cells",
        "roof_layers", "tile_image", "tile_patches", "compose", "Sprite", "Ground",
        "TilePatch"],
       "docs/spec/code/subsystems/rendering.md",
       "A whole map has no one scroll, so a body's depth key is taken unheld "
       "(0x2DF - ground y): two sprites one screen can show are ordered as "
       "the game orders them. The second layer is drawn only in mode 0 with "
       "the camera's own scroll; any other is named in the notes.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_field_picture.py",
       proven_by=("sprite_draw (0x8001A528)", "sprite_list_draw (0x8001A798)",
                  "bg_cover_box_set (0x80013EF0)", "bg_first_draw (0x80014058)",
                  "MapSecondViewGoalGet (0x80069130)", "MapEffectSet (0x80068AC0)",
                  "layer_col_apply (0x8001E10C)", "sprite_init (0x80018BFC)",
                  "tile_animation_load (0x80026814)",
                  "tile_image_run_load (0x800267AC)", "tile_image_load (0x80026754)")),

    _d("decoders.plugins.SLUS_006_28.formats.palette_animation",
       "A map's palette animation: the slots its set starts, each copying "
       "frames of a strip into the tile palette's second row or turning its "
       "colours, stepped in order every field frame, and the CLUTs of that "
       "row copied to the second layer's row 508.",
       "the program's set, seed and copy tables (records.programs); the "
       "strip in SYSTEM.DAT's type-1 block (system_dat.block_places)",
       [KIND_EXE, KIND_ARCHIVE, KIND_TRANSCRIBED],
       ["animations", "copy_range", "with_strips", "step", "second_row",
        "PaletteAnimation"],
       "docs/spec/code/subsystems/field-frame.md",
       "Only row 501 changes: the tiles drawn through row 500 and the roofs' "
       "copies (rows 510 / 511) keep the colours the map loads with. A strip's "
       "word 0 is copied as it is and makes a hole in the tiles.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_palette_animation.py",
       proven_by=("palette_animation_set (0x800262FC)",
                  "palette_animation_copy_set (0x8002628C)",
                  "palette_animation_step (0x800263F4)", "palette_update (0x80020134)",
                  "palette_bg_second_row_set (0x80020670)", "GameStart (0x80055B60)",
                  "MapLoad (0x80068A10)")),

    _d("decoders.plugins.SLUS_006_28.formats.map_reach",
       "What a player can see of a map: the lead walked from every way in by "
       "the field's own box test and step cells, and the camera that follows "
       "him, cut to each way in's limits.",
       "map resources in LUNADATA.FIL (world_map): the attribute plane and the "
       "type-9 payload's place rows; the map script's 0x27 moves and labels "
       "(event_script); the entries into the map (field_objects)",
       [KIND_ARCHIVE, KIND_TRANSCRIBED],
       ["party_box", "Start", "limits_px", "place_row", "script_place",
        "payload_places", "free_mask", "event_ids", "label_act", "view", "walk",
        "reach", "seen_mask", "Reach"],
       "docs/spec/code/subsystems/field-frame.md",
       "A scene's own camera moves and a script's moves other than 0x27 are "
       "not followed; a label's story-bit tests are taken both ways, and the "
       "bg changes are walked all in or all out.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_map_reach.py",
       proven_by=("MapAttributeFreeCheck (0x800692D4)", "MapAttributeFind (0x80069A20)",
                  "MapAttributeRun (0x800590C0)", "MapPartyBoxSet (0x8006497C)",
                  "MapViewGoalGet (0x80069080)", "MapPartyPlace (0x80059730)",
                  "MapChange (0x8005922C)", "ScriptCommandMapPartyPlace (0x8005DCBC)",
                  "MapAttributeKind4Run (0x80059C48)", "MapPartyRingRewind (0x80066F54)",
                  "MapSpotMoveTry (0x8006661C)")),

    _d("decoders.plugins.SLUS_006_28.formats.bg_change",
       "A map's bg changes: the rectangles of tiles and attributes it copies "
       "over its own to open a door or leave a place changed for good, the "
       "story bit that keeps each, and the attribute cells that start them.",
       "map resources in LUNADATA.FIL (world_map): the type-9 payload from "
       "+0xA00",
       [KIND_ARCHIVE],
       ["changes", "map_changes", "trigger_cells", "copy", "apply", "BgChange"],
       "docs/spec/code/subsystems/field-frame.md",
       "A row with a story bit is copied again, from its last source, every "
       "time the map loads with the bit set; a row without one is played once "
       "per visit and the map reloads closed.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_bg_change.py",
       proven_by=("resource_map_enter_table_set (0x80020B8C)",
                  "MapBgChangeStart (0x80059900)", "MapBgChangeStep (0x80059A18)",
                  "MapBgChangeCopy (0x80059B0C)",
                  "MapBgChangeStoryBitsCopy (0x80059B6C)",
                  "bg_both_copy (0x800153A0)", "bg_copy (0x80015224)",
                  "bg_attribute_copy (0x800157DC)", "MapAttributeFind (0x80069A20)",
                  "MapAttributeRun (0x800590C0)")),

    _d("decoders.plugins.SLUS_006_28.formats.field_motion",
       "The field's tick for a map's objects and the party standing on its "
       "spot: the think pass and the thinks it calls (wander, step lists, "
       "turns, an enemy's looks), the animation tick, the random draws and "
       "the tile animation.",
       "map resources and object-set definition blocks in LUNADATA.FIL "
       "(field_objects); the field's tables and the tile animation sets in "
       "the EXE",
       [KIND_ARCHIVE, KIND_EXE, KIND_TRANSCRIBED],
       ["Rng", "Field", "Row", "Lead", "Track", "TileAnimation", "tile_animations",
        "tile_place", "field_rows", "facing_toward", "box_touch", "spot_move",
        "side_align_count", "value_div", "wander_step", "turn_step",
        "step_command_run", "look_step", "THINKS", "THINK_NAMES", "LOOKS"],
       "docs/spec/code/subsystems/field-frame.md",
       "The party never moves, sees or is touched: MapObjectPartySeenCheck "
       "answers \"not seen\" and MapObjectTouchFind is not run. Every row "
       "thinks as if the camera were on it, and each takes as its view "
       "limits the first given rectangle it stands in.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_field_motion.py",
       proven_by=("MapFrameUpdate (0x80055840)", "MapObjectsStep (0x800563D4)",
                  "MapObjectsThink (0x8006736C)", "MapObjectWanderStep (0x8006758C)",
                  "StepCommandRun (0x80067768)", "StepWalkStep (0x800677D4)",
                  "MapObjectTurnStep (0x800678F4)",
                  "MapObjectPartyLookStep (0x80077F1C)",
                  "MapObjectOverlapFind (0x80067AC4)", "MapBoxTouchGet (0x80067BFC)",
                  "MapSpotMoveTry (0x8006661C)", "MapSpotSideMoveTry (0x800668A8)",
                  "MapSpotSideAlignCount (0x80066E64)", "MapSpotMove (0x80066848)",
                  "MapFacingTowardGet (0x8005FBBC)",
                  "MapObjectFacingTurnSet (0x80078D00)",
                  "MapObjectFacingTurnStep (0x80078D5C)",
                  "MapObjectRandomWalkStart (0x80078B88)",
                  "MapObjectFacingWalk (0x8007868C)", "MapObjectTowardWalk (0x800782B8)",
                  "MapObjectOpenFacingFind (0x800787F0)",
                  "MapObjectSideFacingGet (0x80078A44)",
                  "MapObjectRandomSpotPlace (0x8007816C)",
                  "rng_range_draw (0x800780DC)", "value_div (0x80077EE8)",
                  "rng_seed (0x8001C5F8)", "rng_refill (0x8001C548)",
                  "rng_next (0x8001C6B0)", "rng_draw (0x8001C770)",
                  "system_init (0x8001EEB8)", "tile_animation_set (0x800265BC)",
                  "tile_animation_step (0x80026690)")),

    _d("decoders.plugins.SLUS_006_28.formats.battle_gfx",
       "Battle graphics bundles: an encounter's graphics set (arena, enemy "
       "type blocks, two CLUTs, up to 5 pages) and the party set (resource "
       "0x197, one block + page per character id).",
       "graphics-set resources g_BtlDataResources[set] (0x800A7E18) and resource 0x197 in "
       "LUNADATA.FIL, via resource_table",
       [KIND_ARCHIVE],
       ["parse_set_bundle", "parse_party_bundle", "parse_party_entry",
        "party_clut", "party_entry_count", "render_page", "compose_arena",
        "SetBundle", "PartyBundle", "PartyEntry", "BattlePage",
        "ARENA_SPRITES", "PARTY_RESOURCE", "ENEMY_ANIMS", "PARTY_ANIMS",
        "COMPANION_ANIMS", "party_places", "PartyPlace"],
       "docs/spec/code/subsystems/battle.md",
       "Containers only — the actor blocks inside are sprite_pages' layout, "
       "so poses compose with sprite_pages.compose_pose. Pages decode "
       "byte-exact to the battle VRAM capture (all rows), CLUT A/B/party to "
       "rows 500/505/504. The type COUNT comes from the set's EXE type list "
       "(records.encounters), not the header. Party descriptors are returned "
       "page-relative (the loader patches them to its VRAM placement). "
       "party_places stands the party as MapBtlRun (0x8007AE58) and BtlPartyLoad "
       "(0x8002B114) do, from the members' place cells.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_battle_gfx.py",
       proven_by=("BtlDataLoad (0x80018694)", "BtlEnemyLoad (0x8002B3AC)", "BtlPartyDataLoad (0x80018A78)",
                  "BtlPartyLoad (0x8002B114)", "BtlPartyImageLoad (0x800187D8)", "BtlFrameDraw (0x80018564)")),

    _d("decoders.plugins.SLUS_006_28.formats.party_init",
       "The new-game party table (LUNADATA resource 0xE7): every character's "
       "level-1 persistent record and starting equipment, and the battle "
       "record BtlPartyStatsSet (0x8002A138) derives from them — the party's real stats.",
       "resource 0xE7 in LUNADATA.FIL via resource_table, plus the EXE item "
       "table (records.items) as an ItemLookup",
       [KIND_ARCHIVE],
       ["parse", "equip", "level1_records", "persistent", "battle_record",
        "by_level", "party", "exe_items", "PartyInit", "PersistentRecord",
        "BattleRecord", "PartyMemberData", "RESOURCE", "SELECTORS",
        "LEVEL_FIELDS", "PlacePreset", "place_preset"],
       "docs/spec/code/subsystems/battle.md",
       "Party stats were never STORED: ChrRecordsReset (0x80063B30) memmoves 12 x 0x40 "
       "persistent records out of 0xE7 and equips each id's six starting "
       "items (ChrWornItemSet (0x80057FFC) -> ChrWornItemValuesAdd (0x800587D0) -> ChrWornItemStatAdd (0x80058910), item bonuses "
       "by selector), and BtlPartyStatsSet (0x8002A138) derives the battle record from that "
       "at battle entry — why every whole-record search failed. Ids 1/6/7 "
       "match the battle savestate byte for byte except +0x2E..+0x31, the "
       "items the character carries (ChrRecord +0x24..+0x29, chr.h), which "
       "change in play. Also yields the weapon-kind anim picks, the spell list, "
       "each id's place record (ChrPlacePresetRecord, chr.h: battle place and "
       "presets) and (by_level, with records.level_up) the record at every level.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_party_init.py",
       proven_by=("ChrRecordsReset (0x80063B30)", "FIL_0230", "ChrWornItemSet (0x80057FFC)", "ChrWornItemValuesAdd (0x800587D0)",
                  "ChrWornItemStatAdd (0x80058910)", "BtlPartyStatsSet (0x8002A138)")),

    _d("decoders.plugins.SLUS_006_28.formats.system_strings",
       "The game's string table (LUNADATA resource 1): every character, "
       "enemy, item, spell and enemy-special name, the descriptions, battle "
       "and menu labels, locations, scene/music titles and system messages.",
       "resource 1 in LUNADATA.FIL via resource_table (its type-1 command, "
       "inflate16), plus the EXE's dictionary of words g_FontStringWords (0x800B386C) and code "
       "table g_FontStringCodes (0x800B34C0), passed in",
       [KIND_ARCHIVE],
       ["block", "table_size", "string_offset", "decode",
        "strings", "category", "string_id", "GameStrings",
        "categories_json", "Words", "words_of", "exe_char_table",
        "DecodedString", "Category", "CATEGORIES", "BY_CATEGORY",
        "RESOURCE", "codes", "string_codes", "string_codes_json",
        "char_table_words", "CHAR_TABLE_ADDR", "CHAR_TABLE_ENTRIES",
        "control_markup", "exe_words", "WORD_COUNT", "walk", "splice_id",
        "RUN_CODES", "RUN_ENDS", "WORD_ENDS", "char_text", "control_text",
        "characters_of", "Characters",
        "spaced", "MOVE"],
       "docs/spec/text.md",
       "Never plain text on the disc: inflate16-packed, and decoded by "
       "font_string_walk (0x8005A884) — a 0x0E run is ASCII - 0x1F with bytes >= "
       "0x5C as dictionary words, then 16-bit codes (0xF0-0xF6 splice "
       "another string). Ids: character = id, enemy = id + 0x80, item = id "
       "| 0x100, spell = row + 0x1B6, enemy special = class | 0x300, "
       "location = id + 0x400, movie = theater entry + 0x500, BGM = n + "
       "0x546, menu label = command number + 0x100 and a description = the "
       "name's number + 0x200 (each from its caller); only the bromide "
       "titles by layout. Byte-checked against RAM. GameStrings is how "
       "every consumer names things. `walk` is the one transcription of "
       "font_string_walk; `decode` is the string for a person (splices "
       "from the string table, passed in for an event script's message): "
       "plain text (line breaks, a pen move as one space between words: "
       "it moves the pen in pixels, and the font is proportional) and a "
       "markup that names every control as a message window reads it "
       "(MOVE, FACE_LEFT/RIGHT, STYLE, WAIT, PROMPT, PAGE, CLOSE); `codes` "
       "is the walk's codes as they come, in order — for a caller with a control handler of its "
       "own (the field's message window shows a string by id that way). No "
       "string of the table uses a dictionary word.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_system_strings.py",
       proven_by=("main (0x80013D2C)", "resource_load_run (0x800202CC)", "resource_command_run (0x800202FC)",
                  "resource_command01_set (0x80020480)", "main_buffer_init (0x80013E04)", "font_string_put (0x80026F78)",
                  "font_string_walk (0x8005A884)", "font_string_word_get (0x80059F4C)", "BtlActionStringDisp (0x8004987C)",
                  "BtlLevelUpGainsDisp (0x8004C324)", "BtlMenuFirstOpen (0x80044780)",
                  "MenuCursorTextDisp (0x8006C8F0)", "BtlMenuItemDisp (0x80046BB4)", "BtlMenuSpellDisp (0x80046258)",
                  "font_control_run (0x8002710C)", "MessageControlRun (0x8005AF20)", "font_pen_move (0x800270CC)")),

    _d("decoders.plugins.SLUS_006_28.formats.jp_characters",
       "SLPS_013.97's glyph codes as Unicode characters, for reading its "
       "text: our transcription of the program's own glyphs (0x9908-0x99F8 "
       "and the 0x84xx list), plain Shift-JIS for the codes the kanji ROM "
       "draws.",
       "nothing: the table is ours, made by matching each glyph's picture "
       "and checked by eye",
       [KIND_TRANSCRIBED],
       ["CHARACTERS", "OWN_RANGES", "own", "character"],
       "",
       "Two glyphs with no confident match are None and show as "
       "{GLYPH:xxxx}. The 0x99xx capitals and digits are read as full-width "
       "forms, the list's letters as ASCII.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_jp_characters.py",
       proven_by=("font_pattern_get (0x80026B1C)",)),

    _d("decoders.plugins.SLUS_006_28.formats.message_window",
       "The field message window: each event-script message walked through "
       "the window's handlers into its text buffer, the stops the player "
       "waits at, who speaks (the faces up), and the window drawn as the "
       "game draws it — shade, outlined text, faces and arrow.",
       "the event scripts (LUNADATA.FIL resources) and resource 1's string "
       "table, the EXE's dictionary, code table and glyph patterns, palette "
       "rows 503 and 507 (system_dat), passed in",
       [KIND_ARCHIVE, KIND_EXE, KIND_TRANSCRIBED],
       ["Window", "Font", "Screen", "Said", "Message", "outline",
        "glyph_width", "script_messages", "answer_strings", "draw",
        "row_image", "row_places", "cell_runs", "Layout", "US_LAYOUT",
        "JP_LAYOUT", "layout_of", "ROM_STAND_IN", "RomFont", "PATTERNS_20",
        "PATTERNS_9908", "ROW_BYTES", "CELL_BYTES", "PAGE_BYTES", "TOP",
        "HEIGHT", "WIDTH", "ANSWER"],
       "docs/spec/text.md",
       "A message is read in the order of its script's code, the window "
       "fresh at each label (ScriptLabelRun) and carried over otherwise: "
       "the code's flow is not followed. Faces are named by their file "
       "(FaceListByteLoad loads file id for character id). Glyphs outside "
       "the program's tables come from the BIOS's kanji ROM (Krom2RawAdd), "
       "which is the console's and is not read: they are drawn by their "
       "characters with what the caller gives (rom_font; the viewer gives an "
       "installed Japanese font), else as a box. "
       "The face pages start at page 0 at a label; the order within one "
       "ordering-table slot is not read. SLPS_013.97's window is laid out "
       "by its own numbers (JP_LAYOUT: MessageRowDisp's columns and 12, 13 "
       "or 17 cells, CellFacePlacesSet's face cells, MessageArrowStep's y), "
       "read from its machine code against the US C.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_message_window.py",
       proven_by=("ScriptCommandMessageDisp (0x8005AB1C)", "font_string_walk (0x8005A884)",
                  "MessageStringCodePut (0x8005A834)", "MessageControlRun (0x8005AF20)",
                  "font_code_put (0x80026D64)", "font_pattern_get (0x80026B1C)",
                  "font_pattern_outline (0x80026B98)", "font_pen_move (0x800270CC)",
                  "font_target_set (0x800270AC)", "font_col_set (0x800270BC)",
                  "MessageFaceSet (0x8005B36C)", "CellFacePlacesSet (0x80057608)",
                  "FaceCellSet (0x8001B3DC)", "MessageClose (0x8005A72C)",
                  "MessageLinesClear (0x8005BC74)", "ScriptLabelRun (0x80059FDC)",
                  "MessageRowDisp (0x8005B4A0)", "CellTextDisp (0x800572E0)",
                  "font_cell_run_set (0x80016230)", "font_place_split (0x80016204)",
                  "font_cell_set (0x800161CC)", "font_cell_draw (0x80016134)",
                  "MessageArrowStep (0x8005A678)", "MessageStringDisp (0x8005AB98)",
                  "FaceCellDraw (0x8001B4B0)", "MessageShadeDraw (0x80015E88)",
                  "MessageOpen (0x8005A6D0)", "MessageArrowDraw (0x80015F0C)",
                  "ScriptAnswerRun (0x8005C198)", "ScriptStringEndFind (0x8005C144)",
                  "FaceListByteLoad (0x80076094)", "GsClearOt (0x8008FB98)")),

    _d("decoders.plugins.SLUS_006_28.formats.face_blocks",
       "Portraits by face number: the face data (FACE blocks) as face.c "
       "reads them — files of five faces (1..120) and 42 scene blocks of "
       "ten, each picture 64x64 at 8 bits.",
       "LUNADATA resources 0xA3..0xE4, via resource_table",
       [KIND_ARCHIVE],
       ["parse", "FaceBlock", "is_valid", "checksum", "face_file",
        "file_resource", "scene_resource", "face_source", "face_pixels",
        "member_face", "own_file", "image", "FILES", "FACES", "CLUT_ROW"],
       "docs/spec/assets/sprites.md",
       "Texels, not colours: the palette is row 503 (system_dat.palette_rows). "
       "A scene block's pictures are copies of the faces it lists; a face "
       "is named by character only as a member's face, (id - 1) * 5 + 1.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_face_blocks.py",
       proven_by=("FaceCellSet (0x8001B3DC)", "FaceSlotGet (0x8001B200)",
                  "FaceDataLoad (0x8001B1C0)", "FaceImageLoad (0x8001B310)",
                  "FaceDataCheck (0x8001B54C)", "FaceSlot6Find (0x8001B5C4)",
                  "FaceSlot6Load (0x8001B50C)", "FaceCellDraw (0x8001B4B0)",
                  "ShopFaceSet (0x80054C0C)", "BtlMenuActingFaceSet (0x80049D60)",
                  "FaceListByteLoad (0x80076094)", "FaceListPartySet (0x80075EFC)")),

    _d("decoders.psx.formats.tim",
       "Standard PS1 TIM images: the header, CLUT and pixel blocks. SSSC "
       "keeps 41 in its command lists (formats.resource_pictures); The "
       "Making of Lunar carries 73 raw in its EXE.",
       "raw TIM bytes from any container — a type-2 command's packed "
       "payload (SSSC), uncompressed banks in an EXE image (SLUS_009.21)",
       [KIND_ARCHIVE, KIND_EXE],
       ["parse_tim", "tims_in_stream", "TimImage"],
       "docs/spec/sprites.md",
       "TIMs carry their own CLUT, unlike sprite_pages; clut_words keeps "
       "the stored 16-bit colours for code that draws through VRAM.",
       tests="backend/decoders/psx/formats/tests/test_tim.py"),

    _d("decoders.plugins.SLUS_006_28.formats.resource_pictures",
       "The game's 41 pictures: the TIMs of command 2 in LUNADATA's command "
       "lists, each with its resource, picture number and the code that "
       "shows it, drawn through the colours that code draws it with.",
       "the command-list resources of LUNADATA.FIL (formats.resources)",
       [KIND_ARCHIVE],
       ["Picture", "Role", "pictures", "role", "image", "GLYPH_ATLAS_RESOURCE",
        "TITLE_RESOURCE", "TITLE_PAGES", "GLYPH_CLUT", "BROMIDE_CLUT",
        "SCREEN_PICTURE_H", "ShowFrame", "fade_strength", "bromide_show",
        "bromide_image", "BROMIDE_SHOWN", "BROMIDE_FADE", "BROMIDE_VOICE_WAIT",
        "SCREEN_W", "SCREEN_H", "BROMIDE_PAGE_X"],
       "docs/spec/sprites.md",
       "Resource 1: the glyph atlas. Resource 3: five cards (only picture 0 "
       "is shown) and three title pages. Bromides 586-598: top and bottom, "
       "shown as one column of video memory the screen pans down and back "
       "up (bromide_image, bromide_show). Resource 599: pictures 0-3 the "
       "disc-change screens, 4 while _SECOND.XA plays after the game's end, "
       "5 for ever after.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_resource_pictures.py",
       proven_by=("resource_tim_add (0x800208A0)", "resource_tim_unpack (0x80020918)",
                  "resource_tim_load (0x80020950)", "PictureShow (0x80024A7C)",
                  "PictureStep (0x800249B0)", "PictureDraw (0x80024950)",
                  "PictureBandDraw (0x8002484C)", "screen_fade_step (0x8001C0F0)",
                  "StartPictureShow (0x8001607C)", "cd_change_wait (0x80024D2C)",
                  "GameRun (0x800559F4)", "ankprint_cell_draw (0x80025C20)")),

    _d("decoders.psx.formats.str_stream",
       "STR streaming movie CONTAINER — sector headers, frame reassembly, "
       "MDEC frame attributes. SLUS_009.21's _B000.STR is 320x240, "
       "10-ish sectors per frame, ~529 MB (the documentary itself).",
       "raw .STR sectors (2048 B each: 32-byte header + 2016-byte payload) "
       "from any disc",
       [KIND_DISC_FILE],
       ["parse_sector_header", "iter_sectors", "iter_str_sectors",
        "iter_frames", "probe", "looks_like_str_sector",
        "StrSectorHeader", "StrFrame"],
       "docs/spec/video.md",
       "CONTAINER only — hand its StrFrame.bitstream to formats.mdec for "
       "pixels. Two measured departures from Sony's File Formats text: "
       "StFRAME_SIZE is BYTES not long words, and a .STR legitimately "
       "contains interleaved XA sectors with no STR header.",
       tests="backend/decoders/psx/formats/tests/test_str_stream.py"),

    _d("decoders.psx.formats.mdec",
       "PS1 MDEC video codec — the compressed bitstream inside an STR "
       "frame to 8-bit RGB pixels. v2 streams (every one measured here); "
       "v3's differential DC is refused rather than guessed.",
       "a reassembled STR frame from str_stream (header + bitstream)",
       [KIND_DISC_FILE],
       ["parse_frame_header", "decode_frame", "check_frame", "idct_8x8",
        "FrameHeader", "DecodedFrame", "MdecError",
        "AC_VLC", "QUANT_TABLE", "ZIGZAG"],
       "docs/spec/formats/mdec.md",
       "TRAPS: the bitstream is little-endian 16-bit words read MSB-first "
       "(reading bytes in file order desyncs after a while), and "
       "macroblocks are ordered down COLUMNS, not across rows. "
       "check_frame() validates a decode against the file itself — block "
       "count from the geometry, the header's code bound, and the "
       "bitstream tail — so correctness is falsifiable without a "
       "reference decoder or an emulator capture.",
       tests="backend/decoders/psx/formats/tests/test_mdec.py"),

    _d("decoders.psx.formats.xa_adpcm",
       "CD-XA ADPCM — the audio interleaved into an STR movie (and .XA "
       "files). Every Lunar stream measured is mono 37800 Hz 4-bit.",
       "RAW 2352-byte sectors from a DISC IMAGE (not extracted files)",
       [KIND_DISC_FILE],
       ["parse_subheader", "iter_xa_sectors", "decode_sector",
        "decode_stream", "new_states", "samples_per_sector", "to_wav",
        "wav_header", "Subheader", "XaFormat", "XaError"],
       "docs/spec/formats/xa-adpcm.md",
       "TRAP: audio does NOT survive file extraction. A Form 2 sector "
       "carries 2324 bytes and an ISO extractor keeps 2048, so an "
       "extracted .STR has every audio sector truncated and its subheader "
       "— the sample rate, channels and bit depth — gone. Read the disc "
       "image. The sound-group parameter layout was settled by "
       "measurement, not by a published description: blocks 0-3 read bytes "
       "0..3 (copied to 4..7), blocks 4-7 read bytes 8..11.",
       tests="backend/decoders/psx/formats/tests/test_xa_adpcm.py"),

    _d("decoders.plugins.SLUS_006_28.formats.script_text",
       "The program's own text (the Program text tab): the dictionary of "
       "512 words packed strings put in, the memory-card short location "
       "names, and the developers' texts the register names (a debug "
       "viewer's caption, two assertions' source files, the host-mode path "
       "format and console).",
       "the EXE image: g_FontStringWords (0x800B386C), g_CardSavePlaceNames (0x800A8618) and "
       "the texts it points at, and the texts of DEVELOPER_TEXTS (0x800B857C-0x800B86FF)",
       [KIND_EXE],
       ["dictionary_block", "read_location_names", "exe_text_blocks",
        "text_runs", "TextBlock", "TextEntry", "NamedText", "DEVELOPER_TEXTS"],
       "docs/spec/text.md",
       "Decodes no packed text: the string table and the event scripts' "
       "messages are formats.system_strings' (font_string_walk (0x8005A884)). The "
       "dictionary is read as font_string_word_get (0x80059F4C) reads it, word n past n "
       "0 bytes, for the 512 words the register states.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_script_text.py",
       proven_by=("font_string_word_get (0x80059F4C)", "font_string_walk (0x8005A884)",
                  "card_save_title_set (0x8001BF50)")),

    _d("decoders.plugins.SLUS_006_28.formats.sound_banks",
       "The VAB+SEQ region: 127 banks at resource indices 232-358.",
       "LUNADATA.FIL sectors 4568-12670",
       [KIND_ARCHIVE],
       ["load_bank", "parse_bank", "find_banks", "walk_chunks", "SoundBank",
        "Chunk"],
       "docs/spec/sound.md",
       "This is the music, NOT the .PCM files (which extract as all zeros "
       "— MODE2 reservations). Engine cmds 13/14/15 = VAB head/body/SEQ. "
       "A bank is music or sound effects by the bank slot the code loads "
       "it into.",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_sound_banks.py",
       proven_by=("BtlShowSoundSet (0x80089EF8)", "SoundPlay (0x800555F0)", "SsSeqOpen (0x80095B38)",
                  "sound_seq_play (0x80023B24)", "sound_effect_play (0x80024514)",
                  "sound_music_load (0x80023E9C)", "sound_area_load (0x80023F78)")),

    _d("decoders.plugins.SLUS_006_28.formats.xa_voices",
       "The voices: the 103 spoken lines in _AUDIO.XA, each one's channel "
       "and sectors from g_XaVoices as xa_voice_get finds them, decoded "
       "from the disc image's raw sectors.",
       "g_XaVoices (0x800ADFF2), g_XaChannelEnds (0x800AE0C4) and D_800AF62C "
       "(0x800AF62C) in the EXE image (records.programs for SLPS_013.97); "
       "_AUDIO.XA's RAW sectors from a DISC IMAGE",
       [KIND_EXE, KIND_DISC_FILE],
       ["Voice", "table", "channel_ends", "end_less", "voice", "voices", "proof",
        "decode", "wav", "FILE_NAME", "FIRST", "LAST", "CHANNELS", "UNIT",
        "SECTORS_PER_SECOND"],
       "docs/spec/sound.md",
       "Units of 16 file sectors, one of each channel: a voice lasts "
       "(end - start) / 150 s. The drive plays only file 1 and the voice's "
       "channel, so `decode` keeps those sectors and carries the filter "
       "state across them. SLPS_013.97's xa_voice_get (0x80026338) takes 2 "
       "off every end and reads no D_800AF62C. Extracted files have lost "
       "the audio (xa_adpcm).",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/"
             "test_xa_voices.py",
       proven_by=("xa_voice_get (0x800238BC)", "VoiceSet (0x80055470)",
                  "VoiceStart (0x800554C4)", "VoiceStep (0x80055524)",
                  "xa_play_start (0x800235C0)", "xa_end_set (0x80023630)",
                  "xa_read_start (0x80023674)", "xa_end_check (0x80023820)",
                  "PictureXaPlay (0x800247AC)")),

    _d("decoders.psx.formats.vab",
       "PS1 VAB sample banks and SPU-ADPCM waveform decoding. SSSC ships "
       "VABs inside LUNADATA; The Making of Lunar has no VAB at all — a bare "
       "two-waveform ADPCM bank sits raw in its EXE and is SpuWrite'd at boot.",
       "VAB chunks out of sound_banks, or bare SPU-ADPCM block runs from an "
       "EXE image (SLUS_009.21's bank at 0x8010BDF0)",
       [KIND_ARCHIVE, KIND_EXE],
       ["parse_vab", "decode_adpcm", "decode_adsr", "note_pitch",
        "pitch_from_note", "tone_sample_rate", "pcm_to_wav", "Vab", "Vag",
        "Program", "Tone"],
       "docs/spec/sound.md",
       "TRAP: the ADPCM terminator block must NOT be decoded — 704 samples "
       "end 00 07 77 77 and decoding it is a full-scale click.",
       tests="backend/decoders/psx/formats/tests/test_vab.py"),

    _d("decoders.psx.formats.seq",
       "PS1 SEQ music sequences and conversion to standard MIDI.",
       "SEQ chunks out of sound_banks",
       [KIND_ARCHIVE],
       ["parse_seq", "seq_to_midi", "note_spans", "tempo_map",
        "controller_name", "Seq", "SeqEvent", "NoteSpan"],
       "docs/spec/sound.md",
       "TRAP: SEQ meta events carry NO length byte — parsing them the MIDI "
       "way silently loses the rest of the sequence.",
       tests="backend/decoders/psx/formats/tests/test_seq.py"),

    _d("decoders.psx.formats.seq_synth",
       "libsnd playing a SEQ through its own VAB, rendered to PCM.",
       "a parsed Seq + its Vab",
       [KIND_ARCHIVE],
       ["render", "walk", "spu_writes", "spu_volume", "bend_pitch",
        "Player", "tail_frames", "RenderStats", "SpuWrite",
        "NTSC_FIELD_HZ", "FIDELITY", "fidelity_lines"],
       "docs/spec/code/libsnd-map.md",
       "Transcribes libsnd's score reader and voice manager on its own "
       "clock: once a sound tick _SsSeqPlay reads the events due (tenths of "
       "a tick, whole-number tempo), and _SsVmFlush sends the changes to "
       "the SPU at the next tick. NRPN loops play as _SsContNrpn2 does, 24 "
       "voices allocated and stolen as _SsVmAlloc picks, every tone in "
       "range keyed, the squared volume law. Player plays it a piece at a "
       "time holding only the moment's state, an endless loop for ever "
       "until set_looping(False); render() is a Player of N passes read to "
       "the end (RenderStats.loop is the last pass), the same samples "
       "however it is read. walk() reads the score without rendering; "
       "spu_writes() lists the register writes. FIDELITY states what is "
       "approximated; the asset viewer prints it beside every sequence.",
       tests="backend/decoders/psx/formats/tests/test_seq_synth.py"),

    _d("decoders.psx.formats.spu_voice",
       "The SPU's voices offline: ADSR envelope, sample playback, mixing.",
       "decoded VAG samples + register values from a driver",
       [KIND_ARCHIVE],
       ["Envelope", "Play", "Mixer", "envelope", "ENV_MAX", "VOICES"],
       "docs/spec/sound.md",
       "psx-spx's envelope (15-bit level, rate counter from the key-on), "
       "steps of one sample run in closed form and exponential stretches "
       "from a byte-bounded cache, both proven equal to stepping one sample "
       "at a time. A one-shot's end silences the voice and zeroes ENVX. "
       "Interpolation is linear. The Mixer is a window moving along the "
       "output, so a score of any length mixes in a few chunks' memory.",
       tests="backend/decoders/psx/formats/tests/test_spu_voice.py"),

    _d("decoders.psx.formats.spu_reverb",
       "libspu's reverb preset records and the SPU reverb network.",
       "libspu's _spu_rev_param / _spu_rev_startaddr tables in an EXE image "
       "(addresses supplied by a program's records package)",
       [KIND_EXE],
       ["parse_preset", "parse_libspu_tables", "process", "Reverb",
        "process_reference", "ReverbPreset", "ReverbSetting", "REGISTERS",
        "MODE_NAMES"],
       "docs/spec/sound.md",
       "Record = u32 mask + the 32 registers SPU +0x1C0..+0x1FE (0x44 "
       "stride); mBASE per mode in 8-byte units. The network is psx-spx's "
       "formula; every read is a fixed delay of one write target, so it runs "
       "as numpy delay lines in blocks (1.3s per 3-minute track), proven "
       "equal to the per-sample ring-buffer reference. Reverb runs it as a "
       "stream, the delay lines carried between pieces: the same output as "
       "process() over the whole.",
       tests="backend/decoders/psx/formats/tests/test_spu_reverb.py"),

    _d("decoders.psx.formats.deflate",
       "Locate raw deflate streams in an arbitrary blob.",
       "any binary input",
       ANY_SHIPPABLE,
       ["find_deflate_streams", "DeflateStream"],
       "docs/spec/formats/compression.md",
       "Codec primitive: the kind of what comes out is the kind of what "
       "went in.",
       tests="backend/decoders/psx/formats/tests/test_deflate.py"),

    _d("decoders.plugins.SLUS_006_28.formats.lzss",
       "LZSS decompressor, including the PS1 executable's own packing.",
       "any binary input / the packed EXE",
       ANY_SHIPPABLE,
       ["decompress", "decompress_exe"],
       "docs/spec/formats/compression.md",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/test_lzss.py"),

    _d("decoders.plugins.SLUS_006_28.formats.inflate16",
       "PS1 16-bit-word inflate variant.",
       "any binary input",
       ANY_SHIPPABLE,
       ["decompress"],
       "docs/spec/formats/compression.md",
       tests="backend/decoders/plugins/SLUS_006_28/formats/tests/test_inflate16.py"),

    _d("decoders.psx.formats.display",
       "PS1 GPU display modes: the mode PutDispEnv sets for a display's "
       "width and height, and the shape of a pixel in it (NTSC: 8:7 in the "
       "256 mode).",
       "a display environment's width and height (numbers, not bytes)",
       [KIND_TRANSCRIBED],
       ["mode_for", "DisplayMode", "TICKS_PER_PIXEL"],
       "docs/spec/video.md",
       "The mode thresholds are libgpu PutDispEnv's (0x8008C434): 280, 352, "
       "400 and 560 wide; over 256 lines is interlaced.",
       tests="backend/decoders/psx/formats/tests/test_display.py"),

    _d("decoders.psx.formats.palette",
       "PS1 16-bit ABGR1555 palette decoding.",
       "CLUT bytes from any source",
       ANY_SHIPPABLE,
       ["parse_ps1_palette"],
       "docs/spec/formats/palettes.md",
       tests="backend/decoders/psx/formats/tests/test_palette.py"),

    _d("decoders.psx.formats.renderer",
       "8-bit indexed pixel layers -> PIL images, with compositing.",
       "decoded pixels + a palette",
       ANY_SHIPPABLE,
       ["render_indexed_layer", "composite_layers"],
       "docs/spec/graphics.md",
       "composite_layers is ALPHA compositing: every layer must be RGBA and "
       "one size, and it names the offending layer when one is not "
       "(PIL's own message identifies neither).",
       tests="backend/decoders/psx/formats/tests/test_renderer.py"),
]

# ======================================================================
# records/ — in-memory / EXE-resident record layouts
# ======================================================================
RECORDS = [
    _d("decoders.plugins.SLUS_006_28.records.enemy_templates",
       "The enemies' rows (BtlEnemyRow), 0x26 bytes each, g_BtlEnemyRows (0x800A8768): "
       "127 rows, the register's extent.",
       "the EXE",
       [KIND_EXE],
       ["read_from_exe", "parse_table", "parse_record", "to_dict",
        "EnemyTemplate", "build_charstats", "battle_record", "template_index",
        "COPIER_MAP", "BATTLE_FIELDS"],
       "docs/spec/battle-data.md",
       "The layout is read off the copier, BtlEnemyStatsSet (0x8002A638): "
       "stride 0x26 from its own arithmetic, ids 1-based, and every field "
       "mapped to its place in the stats (BtlStats). Fields carry btl.h's names; "
       "battle_record is the stats the copier writes, each noted with the code "
       "that reads it (BtlHitAmountSet (0x80030070), BtlTargetTraitCheck (0x80037648), "
       "BtlActionRowRun (0x80031ABC), BtlStat0EHitAmountSet (0x80035EF8), BtlTurnOrderMake (0x8002F4B0), BtlEnemyActionPick (0x8004CAB8), "
       "BtlWinRewardSum (0x80028D78), BtlWinItemsGive (0x80028A54) and others).",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_enemy_templates.py",
       proven_by=("BtlEnemyStatsSet (0x8002A638)", "BtlHitAmountSet (0x80030070)", "BtlTargetTraitCheck (0x80037648)",
                  "BtlActionRowRun (0x80031ABC)", "BtlStat0EHitAmountSet (0x80035EF8)", "BtlTurnOrderMake (0x8002F4B0)",
                  "BtlEnemyActionPick (0x8004CAB8)", "BtlWinRewardSum (0x80028D78)", "BtlWinItemsGive (0x80028A54)")),

    _d("decoders.plugins.SLUS_006_28.records.encounters",
       "Encounter tables: encounter id -> {graphics set, formation}; per-set "
       "enemy type lists and LUNADATA resource; 0x18-byte formations "
       "(enemy ids + anchor positions).",
       "the EXE",
       [KIND_EXE],
       ["encounter", "all_encounters", "type_list", "type_slot",
        "set_resource", "formation", "max_enemy_id", "tables_json",
        "Encounter", "Formation", "FormationSlot"],
       "docs/spec/code/subsystems/battle.md",
       "Read off BtlEnemyLoad (0x8002B3AC): positions are the actor ANCHOR (x*8, y*8 "
       "clamped 0x70..0xB0, mirrored at x >= 0xC0), and an enemy id matching "
       "none of the first THREE type-list entries draws from block 3. The "
       "encounter and type-list symbols sit one entry before their data "
       "(1-based tables, base folded); extents are layout readings. "
       "tables_json also carries the event script's BATTLE rows g_ScriptMapBtlRows (0x800B366C) "
       "(`script_rows`: encounter, MapBtlRun (0x8007AE58)'s arg1 = the party's x shift, "
       "the row's party list), read by formats.event_script.encounter_rows.",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_encounters.py",
       proven_by=("BtlEnemyLoad (0x8002B3AC)", "BtlDataLoad (0x80018694)", "ScriptCommandMapBtlRun (0x8005DFF0)")),

    _d("decoders.plugins.SLUS_006_28.records.items",
       "The item rows (BtlItemRow), 0x12 bytes each, items 1..0xB6, g_BtlItemTable (0x800A9A68).",
       "the EXE",
       [KIND_EXE],
       ["read_from_exe", "parse_table", "parse_record", "to_dict",
        "ItemRecord", "COUNT"],
       "docs/spec/battle-data.md",
       "0xB6 (182) rows: ChrItemUseGet (0x80058088) answers -2 for an item number "
       "of 0 or above 0xB6, and the table ends where the spell rows begin.",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_items.py",
       proven_by=("BtlPartyStatsSet (0x8002A138)", "ChrItemUseGet (0x80058088)")),

    _d("decoders.plugins.SLUS_006_28.records.spells",
       "The spell rows (BtlSpellRow), 0x0C bytes each; row n is spell n.",
       "the EXE",
       [KIND_EXE],
       ["read_from_exe", "parse_table", "parse_record", "to_dict",
        "SpellRecord", "COUNT"],
       "docs/spec/battle-data.md",
       "Read from g_BtlSpellRowsByNumber (0x800AA728), one row before g_BtlSpellRows "
       "(0x800AA734), as the battle reads spell n: 0x33 rows, row 0 and the "
       "table's 0x32 spells. +0x06 is the show number, not the spell's.",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_spells.py",
       proven_by=("BtlHitAmountSet (0x80030070)", "BtlActionRowRun (0x80031ABC)", "BtlActionSpellRun (0x8002E718)",
                  "ChrLevelUp (0x80028554)")),

    _d("decoders.plugins.SLUS_006_28.records.attack_classes",
       "Enemy attack / special class records (g_BtlAttackRows, 0x800AC640), 8 bytes each, "
       "indexed by class: target mode, effect id and the effect parameters "
       "BtlActionRowRun (0x80031ABC) loads for an enemy's class attack (+0x1C, kind 2) or "
       "special (+0x1D, kind 7).",
       "the EXE",
       [KIND_EXE],
       ["read_from_exe", "parse_table", "parse_record", "to_dict",
        "AttackClass", "COUNT", "TARGET_ANY_ACTIVE", "TARGET_STATUS_FREE"],
       "docs/spec/code/subsystems/battle.md",
       "127 rows, ending where the level-up table g_ChrLevelGainTable (0x800ACA38) begins; a "
       "class's name is string class | 0x300. Every reader is accounted for "
       "(structs.py --all): BtlActionRowRun (0x80031ABC) (+1..+6), BtlActionTargetAdjust (0x8002ED34) and "
       "BtlEnemyKind7Pick (0x8004CF48) (+0, the target mode). Row 0 is all zero and NOT a "
       "checked sentinel — class 0 under kind 7 would call "
       "scene_state_table[-1].",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_attack_classes.py",
       proven_by=("BtlActionRowRun (0x80031ABC)", "BtlActionTargetAdjust (0x8002ED34)", "BtlEnemyKind7Pick (0x8004CF48)",
                  "BtlEnemyActionAdjust (0x80029510)")),

    _d("decoders.plugins.SLUS_006_28.records.shops",
       "The shops' stock (g_ShopStockRows, 0x800A8468): 0x28 rows of six item "
       "numbers; shop n, the number ScriptCommandShopRun (0x8005E384) hands "
       "ShopRun (0x80050694), is row n - 1.",
       "the EXE",
       [KIND_EXE],
       ["read_from_exe", "Shop", "COUNT", "CLOSED", "FREE", "HIDDEN_WHILE_CARRIED"],
       "docs/spec/code/subsystems/menu-ui.md",
       "ShopListSet (0x80051768) copies the row ShopStockGet (0x8001BF1C) answers "
       "(row 0x27 for 0x28 and up) into the list, 0 an empty place. Shop 8 never "
       "opens (ShopRun) and its row is zeros; shop 0x22 takes no money; item 0xB5 "
       "is left out while the party carries one.",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/test_shops.py",
       proven_by=("ShopRun (0x80050694)", "ShopStockGet (0x8001BF1C)",
                  "ShopListSet (0x80051768)", "ScriptCommandShopRun (0x8005E384)")),

    _d("decoders.plugins.SLUS_006_28.records.level_up",
       "The party's level-up: the EXE's per-character gain and EXP tables "
       "and the spell rows, applied to a persistent party record the way "
       "ChrLevelUp (0x80028554) / ChrLevelAdd (0x8002844C) / ScriptCommandChrLevelItemSet (0x8005D2F0) do.",
       "the EXE (g_ChrLevelGainTable (0x800ACA38) tables, spell rows "
       "g_BtlSpellRows (0x800AA734))",
       [KIND_EXE],
       ["level_up", "raise_levels", "set_level", "gain", "exp_next",
        "spell_slot", "Gains", "GAINS_ADDR", "LEVEL_CAP"],
       "docs/spec/code/subsystems/battle.md",
       "Every level past the first is computable: gains by OLD level, EXP to "
       "the next from a shared big-endian table, one spell per level from "
       "the rows whose +0x07 is the id (+0x00 the level), slotted by "
       "jtbl_800118DC. Cross-checked against 0xE7's level-1 spell slots and "
       "EXP totals. Not an artifact producer: party_init.by_level takes "
       "set_level as a callable, like its item table.",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_level_up.py",
       proven_by=("ChrLevelUp (0x80028554)", "ChrLevelGainGet (0x80028520)", "ChrLevelGainAdd (0x800289E0)",
                  "ChrLevelAdd (0x8002844C)", "ScriptCommandChrLevelItemSet (0x8005D2F0)", "BtlWinRun (0x80028140)")),

    _d("decoders.plugins.SLUS_006_28.records.music",
       "BGM numbers: what MusicPlay (0x80054F2C) plays for music number n — a "
       "sequence bank (g_MusicBankNumbers (0x800127B8) + g_SoundMusicIndexSkips (0x800AF7A0) through sound_music_load (0x80023E9C)) or "
       "CD audio track 2 (n = 0x3C).",
       "the EXE (g_MusicBankNumbers (0x800127B8), g_SoundMusicIndexSkips (0x800AF7A0))",
       [KIND_EXE],
       ["bgm", "bank_resource", "jukebox", "Bgm", "TITLE_BASE", "CD_NUMBER"],
       "docs/spec/sound.md",
       "Title of BGM n is string 0x546 + n (the jukebox, MenuUseMusicListDisp (0x800774EC)). "
       "The BGM number -> bank map is what the audio engine plays.",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_music.py",
       proven_by=("MusicPlay (0x80054F2C)", "MusicLoadStart (0x80055118)", "sound_music_load (0x80023E9C)",
                  "sound_music_index_get (0x80023E20)", "cd_track_play (0x8001B684)", "MenuUseMusicPick (0x800772E0)")),

    _d("decoders.plugins.SLUS_006_28.records.sound_effects",
       "Sound effects: what SoundPlay (0x800555F0) plays for a sound number on "
       "a map or in battle — a sequence of the common bank, of the battle's, "
       "or of the map's own area bank (g_SoundMapAreas (0x800AF7A8), "
       "g_SoundAreaBankPairs (0x800AF694), the bank's command 17 for "
       "g_SoundIds (0x800E4CD8)) — and the calls whose number the code writes.",
       "the EXE (g_SoundMapAreas, g_SoundAreaBankPairs) + an area bank's command 17",
       [KIND_EXE, KIND_TRANSCRIBED],
       ["tables", "Tables", "sound_ids", "play", "Played", "CALLS", "Call"],
       "docs/spec/sound.md",
       "Numbers 1 to 24 are one sound everywhere; 0x1F to 0x82 the battle's; "
       "from 0x83 each area bank's own, so the same number is another sound "
       "in another place.",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_sound_effects.py",
       proven_by=("SoundPlay (0x800555F0)", "sound_effect_play (0x80024514)",
                  "sound_area_get (0x80024784)", "sound_pair_find (0x80023E5C)",
                  "sound_area_load (0x80023F78)", "sound_id_table_set (0x800244E4)",
                  "SoundMapSet (0x800555CC)")),

    _d("decoders.plugins.SLUS_006_28.records.movie_display",
       "How SSSC shows a movie: its player sets the display to the frame's "
       "own width, so a 224 x 192 movie plays in the 256-wide mode (pixels "
       "8:7, a 4:3 picture).",
       "a movie frame's width and height (from the STR sector header)",
       [KIND_TRANSCRIBED],
       ["movie_mode", "PLAYER"],
       "docs/spec/video.md",
       "The display width is rect.w * 2 / 3 with rect.w = width * 3 / 2: "
       "the frame's width.",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_movie_display.py",
       proven_by=("movie_frames_play (0x80196414)",
                  "movie_frame_next (0x80196954)",
                  "PutDispEnv (0x8008C434)")),

    _d("decoders.plugins.SLUS_006_28.records.areas",
       "Map areas: the location, party kind and music MapSet (0x80068780) sets for "
       "each map (area records g_MapTbls (0x800B5238) via g_MapTblNumbers (0x800B5198)), and the resource "
       "holding each map (g_MapResourcePairs (0x800AF364), resource_pair_find (0x80020C58)).",
       "the EXE (g_MapTblNumbers (0x800B5198), g_MapTbls (0x800B5238), g_MapResourcePairs (0x800AF364))",
       [KIND_EXE],
       ["area", "area_record_index", "map_resources", "map_resource", "maps",
        "Area", "LOCATION_STRING_BASE"],
       "docs/spec/text.md",
       "A map's name is string 0x400 + its area record's byte 6, its music "
       "the BGM number in byte 0xF; the game's map table lists 97 maps, 13 "
       "of which an archive-entry scan misses. Header byte 19 repeats the "
       "map id.",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_areas.py",
       proven_by=("MapSet (0x80068780)", "MapTblGet (0x80068618)", "resource_pair_find (0x80020C58)",
                  "MapResourceFind (0x80020CD0)", "MapSeek (0x8006891C)")),

    _d("decoders.plugins.SLUS_006_28.records.events",
       "Play events: what MoviePlay(n) (0x800232D4) shows — a movie (_B%03d.STR, "
       "disc 1/2) or bromide k (resource 0x24A + k, and its voice) — the "
       "theater's entry -> event rule, and MENU.BIN's movie end-frame table.",
       "constants transcribed from MoviePlay (0x800232D4) / MenuUseMoviePick (0x800775D4) / "
       "PictureShow (0x80024A7C); MENU.BIN (the overlay) for end_frames",
       [KIND_EXE],
       ["event", "theater_event", "movie_number", "bromide_for_resource",
        "resource_role", "end_frames", "picture_voices", "Event",
        "BROMIDE_RESOURCE_BASE", "DISC_PROMPT_RESOURCE"],
       "docs/spec/video.md",
       "Theater entry i plays _B{i-1:03d}.STR; event 0x37 + k is bromide k. "
       "end_frames' zero entries are exactly the movies on neither disc.",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_events.py",
       proven_by=("MoviePlay (0x800232D4)", "MenuUseMoviePick (0x800775D4)", "MenuUseMoviePlay (0x800778C8)",
                  "PictureShow (0x80024A7C)", "PictureXaPlay (0x800247AC)", "BIN")),

    _d("decoders.plugins.SLUS_006_28.records.battle_voices",
       "The voices the battles play: the voice in each effect's row of "
       "g_BtlEffectRows (0x800AC43C) that a show keeps and starts, the set "
       "battles' voices and the revive's, and who casts what: the spells a "
       "character keeps or picks, the attacks a monster's planner gives it.",
       "the EXE (g_BtlEffectRows (0x800AC43C))",
       [KIND_EXE],
       ["effect_rows", "show_voices", "EffectRow", "OTHER_VOICE_IDS",
        "SET_BATTLE_VOICES", "REVIVE_VOICE", "REVIVER_ID", "other_voice",
        "level_spells", "script_spell_ok", "planned_attacks", "PICKED_SPELLS",
        "PLANNED", "SERIES"],
       "docs/spec/sound.md",
       "Row n is effect n: flags, tile row, voice, other voice. A show of 1 to "
       "0x5A whose row names a voice raises the voice byte.",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_battle_voices.py",
       proven_by=("BtlShowOpen (0x8007B7C8)", "BtlEffectLoad (0x800897DC)",
                  "BtlShowActingPlay (0x8008A95C)", "BtlShowVoiceStep (0x80089D78)",
                  "BtlActingShowRun (0x8003A158)", "BtlSlot5Revive (0x80028E5C)",
                  "BtlSlot5ReviveTry (0x80027B6C)", "ChrLevelUp (0x80028554)",
                  "ScriptCommandChrSpellSet (0x8005EE30)",
                  "BtlActingSpellPick (0x800393F0)",
                  "BtlEnemyActionSpecialSet (0x800417E4)",
                  "BtlActionSeriesRun (0x8002DD88)")),

    _d("decoders.plugins.SLUS_006_28.records.spu_reverb",
       "libspu's reverb presets in this EXE, and the reverb the game sets.",
       "the EXE (or the disc EXE via exe_loader)",
       [KIND_EXE],
       ["read_from_exe", "game_setting", "PARAM_ADDR", "STARTADDR_ADDR",
        "GAME_MODE", "GAME_VLOUT", "GAME_VROUT"],
       "docs/spec/sound.md",
       "Tables at D_800B8170 / D_800B8140 (SpuSetReverbModeType (0x800A0E68) = libspu "
       "SpuSetReverbModeType, relocations aligned). The game runs STUDIO_C "
       "at depth 0x2800 / 0x2800, in phase: sound_init (0x80023D54) re-calls "
       "SpuSetReverbModeDepth at 0x80023DDC after sound_reverb_set (0x800241F4)'s 0x3000 / "
       "0xB000 (kept as FUNC_800241F4_*).",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_spu_reverb.py",
       proven_by=("sound_init (0x80023D54)", "sound_reverb_set (0x800241F4)", "SpuSetReverbModeType (0x800A0E68)",
                  "SpuSetReverbModeDepth (0x800A1038)", "_spu_setReverbAttr (0x8009FAF8)")),

    _d("decoders.plugins.SLUS_006_28.records.sound_setting",
       "How the game plays a score: the levels, tick and reverb its code "
       "sets, as seq_synth.render arguments.",
       "the EXE (for the reverb preset)",
       [KIND_EXE],
       ["game_setting", "SoundSetting", "SCORE_VOLUME", "MASTER_VOLUME",
        "VBLANK_MINUS", "TICK_HZ"],
       "docs/spec/sound.md",
       "Score volume 0x50 / 0x50 at the full music level, main volume "
       "0x3F80, one tick per vertical blank of a 240-line non-interlaced "
       "NTSC screen (59.817 Hz), stereo, STUDIO_C reverb "
       "(records.spu_reverb). Music-level fades are not modelled.",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_sound_setting.py",
       proven_by=("sound_seq_play (0x80023B24)",
                  "sound_music_volume_set (0x80023C4C)",
                  "sound_music_level_reset (0x800245D0)",
                  "sound_init (0x80023D54)", "SsSetTickMode (0x800995E8)",
                  "SsStart2 (0x80098388)", "screen_mode_set (0x8001F0C8)",
                  "SoundMonoSet (0x800550D4)")),

    _d("decoders.plugins.SLUS_006_28.records.battle_constants",
       "EXE-static constants the Data tables tab shows: the field's facing "
       "step tables (MapSpotMove (0x80066848), not the battle's) and the RNG's "
       "function names.",
       "the EXE",
       [KIND_EXE],
       ["read_direction_tables"],
       "docs/spec/code/subsystems/npc-scripting.md",
       proven_by=("MapSpotMove (0x80066848)",)),

    _d("decoders.plugins.SLUS_006_28.records.programs",
       "Which program an image is (SLUS_006.28 or the Japanese original "
       "SLPS_013.97, by its build stamp), and where each table the readers "
       "read lies in the Japanese program.",
       "the EXE's build stamp (g_BuildStamp (0x80011000)) or MENU.BIN's",
       [KIND_EXE],
       ["program_of", "address", "has", "Unmapped", "JP_TABLES", "STAMPS"],
       "",
       "Every Japanese address is formed by the Japanese function that does "
       "what the US reader does, named in its row; a table with no row is "
       "not read on the Japanese disc.",
       tests="backend/decoders/plugins/SLUS_006_28/records/tests/"
             "test_programs.py",
       proven_by=("build_stamp_compare (0x80013D08)",
                  "overlay_stamp_check (0x800232B0)")),

]

# ======================================================================
# disc/ — getting bytes off the disc image
# ======================================================================
DISC = [
    _d("decoders.psx.disc.extractor",
       "Orchestrates disc image extraction into <library>/<program>/raw/.",
       "a BIN/CUE disc image",
       [KIND_DISC_FILE],
       ["DiscExtractor", "ExtractResult"],
       "docs/spec/overview.md",
       tests="backend/decoders/psx/disc/tests/test_extractor.py"),

    _d("decoders.psx.disc.iso_reader",
       "Pure-Python ISO 9660 Level 1 reader for PS1 disc images, plus "
       "lazy by-slice access to an image and a root-directory file lookup.",
       "a BIN/CUE disc image",
       [KIND_DISC_FILE],
       ["ISO9660Reader", "DirectoryEntry", "DiscImage", "find_file",
        "file_path"],
       "docs/spec/overview.md",
       "DiscImage reads by seek rather than loading the whole image; "
       "find_file returns an entry's LBA, which is what lets a caller read "
       "RAW 2352-byte sectors (the only place XA audio survives). A file "
       "is written only in the folder it is extracted to (file_path).",
       tests="backend/decoders/psx/disc/tests/test_iso_reader.py"),

    _d("decoders.psx.disc.cd_audio",
       "Red Book CD audio tracks 2-3, read straight from the BIN.",
       "a BIN/CUE disc image",
       [KIND_DISC_FILE],
       ["load_tracks", "msf_to_sectors", "pcm_to_wav", "CdTrack"],
       "docs/spec/sound.md",
       "TRAP: read from INDEX 01, not byte 0 — there is a 150-sector "
       "pregap. Distinct from the sequenced SPU audio in sound_banks; "
       "never conflate the two music systems.",
       tests="backend/decoders/psx/disc/tests/test_cd_audio.py"),

    _d("decoders.psx.disc.cue_parser",
       "Parse .cue sheets for track layout.",
       "a .cue sheet",
       [KIND_DISC_FILE],
       ["parse_cue", "CueSheet", "CueTrack"],
       tests="backend/decoders/psx/disc/tests/test_cue_parser.py"),

    _d("decoders.psx.disc.checksum",
       "SHA-256 of a disc image, for identification.",
       "a BIN/CUE disc image",
       [KIND_DISC_FILE],
       ["sha256_file"]),
]

# ======================================================================
# analysis/ — reading the executable itself
# ======================================================================
ANALYSIS = [
    _d("decoders.psx.analysis.exe_loader",
       "PS-X EXE container header + the SLUS_006.28 outer-LZSS unwrap (a "
       "declared seam: it belongs in that plugin).",
       "the packed EXE",
       [KIND_EXE],
       ["load_exe", "find_exe", "LoadedBinary"],
       "docs/spec/code-decompilation.md",
       "The unpacked image is mapped with its header just below the body "
       "(0x80010800).",
       tests="backend/decoders/psx/analysis/tests/test_exe_loader.py"),

    _d("decoders.psx.analysis.symbols",
       "Resolve EXE addresses BY NAME: the data tables the decoders read.",
       "its own table (DATA_TABLES)",
       [KIND_EXE],
       ["lookup", "resolve", "DATA_TABLES", "Symbol"],
       "docs/spec/code/README.md",
       "Use this instead of hardcoding an address, so each one is spelled "
       "once."),

]

# ======================================================================
# gamedb/ — which disc is this
# ======================================================================
GAMEDB = [
    _d("decoders.psx.gamedb.database",
       "Resolve an installed/extracted game by disc id or checksum.",
       "<library>/<program>/raw/ + <library>/discs/",
       [KIND_DISC_FILE],
       ["GameDatabase", "resolve_disc_source", "read_meta", "InstalledGame"]),

    _d("decoders.psx.gamedb.known_games",
       "Static table of known PS1 disc images, the programs they boot, and "
       "the games (library slots) those programs belong to.",
       "(static table)",
       [KIND_DISC_FILE],
       ["GameInfo", "Game", "GAMES", "game_programs", "game_of",
        "version_group", "disc_tag"]),
]


INVENTORY: tuple = tuple(FORMATS + RECORDS + DISC + ANALYSIS + GAMEDB)

BY_MODULE = {d.module: d for d in INVENTORY}

GROUPS = (
    ("formats", "file and container decoders", FORMATS),
    ("records", "EXE-resident record layouts", RECORDS),
    ("disc", "getting bytes off the disc image", DISC),
    ("analysis", "reading the executable itself", ANALYSIS),
    ("gamedb", "which disc is this", GAMEDB),
)


# ----------------------------------------------------------------------
# lookup
# ----------------------------------------------------------------------
def get(module: str) -> Decoder | None:
    """The entry for a dotted module path, or None."""
    return BY_MODULE.get(module)


def find(query: str) -> list:
    """Decoders matching `query` across module, summary, reads, api, note.

    Deliberately generous: someone who searches for "sprite" or "resource"
    or "palette" should LAND on the existing decoder.
    """
    terms = query.lower().split()
    if not terms:
        return list(INVENTORY)
    out = []
    for d in INVENTORY:
        hay = " ".join((d.module, d.summary, d.reads, d.note,
                        " ".join(d.api))).lower()
        # all terms, in any order: "sector table" must find resource_table
        if all(t in hay for t in terms):
            out.append(d)
    return out


# ----------------------------------------------------------------------
# drift check
# ----------------------------------------------------------------------
def _public_names(path: Path) -> set:
    """Top-level public names in a module, without importing it."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target,
                                                            ast.Name):
            names.add(node.target.id)
    return {n for n in names if not n.startswith("_")}


def check_drift() -> list:
    """-> list of human-readable problems; empty means the index is true."""
    problems = []

    # 1. every module in a covered package is inventoried
    for pkg in COVERED_PACKAGES:
        pkg_dir = PKG_DIR.joinpath(*pkg.split("/"))
        if not pkg_dir.is_dir():
            problems.append(f"covered package missing from tree: {pkg}/")
            continue
        dotted = pkg.replace("/", ".")
        for py in sorted(pkg_dir.glob("*.py")):
            if py.stem.startswith("_"):
                continue
            mod = f"decoders.{dotted}.{py.stem}"
            if mod not in BY_MODULE:
                problems.append(f"{mod} has no inventory entry — add one to "
                                f"backend/decoders/inventory.py")

    for d in INVENTORY:
        # 2. every entry points at a real module, with real API names
        if not d.file.is_file():
            problems.append(f"{d.module}: entry names a module that does not "
                            f"exist ({d.file})")
            continue
        missing = [n for n in d.api if n not in _public_names(d.file)]
        if missing:
            problems.append(f"{d.module}: entry lists API name(s) the module "
                            f"no longer defines: {', '.join(missing)}")
        # 3. kinds are from the closed vocabulary
        bad = sorted(d.produces - SOURCE_KINDS)
        if bad:
            problems.append(f"{d.module}: unknown produces kind(s): {', '.join(bad)}")
        if not d.produces:
            problems.append(f"{d.module}: produces nothing — state at least one kind")
        # 4. a declared test module exists
        if d.tests and not d.test_file.is_file():
            problems.append(f"{d.module}: entry names a test module that does "
                            f"not exist ({d.tests})")
        # 5. only one program's decoders name that program's functions
        if d.proven_by and not d.serial:
            problems.append(f"{d.module}: names proven_by functions but is not "
                            f"a per-program decoder")
    return problems


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def _fmt(d: Decoder, verbose: bool = True) -> str:
    lines = [f"  {d.module}",
             f"      {d.summary}",
             f"      reads:    {d.reads}"]
    if verbose:
        lines.append(f"      produces: {', '.join(sorted(d.produces))}")
        lines.append(f"      api:      {', '.join(d.api)}")
        if d.spec:
            lines.append(f"      spec:     {SPEC_REPO}: {d.spec}")
        if d.note:
            lines.append(f"      note:     {d.note}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="What the decoders parse, and out of which raw file.")
    ap.add_argument("query", nargs="?", default="",
                    help="search module/summary/reads/api (e.g. 'sprite')")
    ap.add_argument("--check", action="store_true",
                    help="fail if the index has drifted from the tree")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    ap.add_argument("--short", action="store_true", help="one line per entry")
    args = ap.parse_args(argv)

    if args.check:
        problems = check_drift()
        for problem in problems:
            print(f"  - {problem}")
        if problems:
            print(f"FAIL: {len(problems)} problem(s) — the index no longer "
                  f"describes the tree.")
            return 1
        print(f"OK: {len(INVENTORY)} decoders inventoried.")
        return 0

    hits = find(args.query)
    if args.json:
        print(json.dumps([d.to_dict() for d in hits], indent=2))
        return 0
    if args.query:
        if not hits:
            print(f"no decoder matches {args.query!r}.")
            return 1
        print(f"{len(hits)} decoder(s) matching {args.query!r}:\n")
        for d in hits:
            print(_fmt(d, verbose=not args.short))
            print()
        return 0
    for name, blurb, group in GROUPS:
        print(f"--- {name}/  ({blurb}) " + "-" * (44 - len(name) - len(blurb)))
        for d in group:
            print(_fmt(d, verbose=not args.short))
            print()
    print(f"{len(INVENTORY)} decoders.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

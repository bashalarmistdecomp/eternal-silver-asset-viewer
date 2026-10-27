"""The resource command list — the container most LUNADATA resources are.

`resource_load_run(n) (0x800202CC)` reads resource n into the buffer at
0x80156000 and hands it to `resource_command_run (0x800202FC)`, which first
empties the list of kept pictures (`resource_tim_reset (0x80020C4C)`) and
then walks it:

    entry = {u32 word, u32 size, `size` bytes of payload}
    type  = word & 0xFF            -> the switch below
    sub   = (word >> 8) & 0xFF     what some handlers read
    next  = 8 + (size >> 2) * 4    bytes on (an unaligned size truncates)
    a zero word ends the list

    type  handler                                   what it does with the payload
    1     resource_command01_set (0x80020480)       unpacks it (inflate_buffer (0x80021D6C)) into
                                                    g_ResourceCommand01Buffer (0x800B8868): the string
                                                    table, the palette animations' colours, the icons
    2     resource_tim_add (0x800208A0)             a packed TIM: sub 0 is unpacked and sent to VRAM
                                                    at once (tim_image_load (0x8002073C)); any other
                                                    sub is kept as the next picture, 0, 1, ... in order
                                                    (g_ResourceTims (0x800E0C10)), for
                                                    resource_tim_unpack (0x80020918) /
                                                    resource_tim_load (0x80020950)
    3     resource_tpage_load (0x8002097C)          a texture page, unpacked and sent: sub 0..2 a
                                                    256 x 256 8-bit page to tpage 0x19 / 0x1B / 0x1D,
                                                    3..0x7F a 128 x 128 one to tpage 0x1F, 0x80..0x82
                                                    the tile layer's pages (tile_tpage_get (0x8001DC94))
    4     resource_palette_load (0x80020A08)        palettes, unpacked: sub 0 the tile palette (CLUT
                                                    rows 500 / 501, 508, 510 / 511); 1..0x7F one row
                                                    to 506; 0x80 one row to 501; above, nowhere
    5     resource_bg_set (0x80020B34)              copied to g_BgDataBuffer (0x800B882C): the tile layout
    6     resource_bg_attribute_set (0x80020B60)    copied to g_BgAttributeDataBuffer (0x800B8834): the
                                                    attribute plane
    7     resource_bg_second_set (0x80020BD8)       unpacked to g_BgSecondBuffer (0x800B887C): the second
                                                    tile layer
    9     resource_map_enter_table_set (0x80020B8C) copied to MapEnterTableAddress() (0x80055E6C),
                                                    0x801E6B00, when g_MapResourceSw (0x800B86D8) is set:
                                                    the map's enter, move and door tables — 128
                                                    MapEnterRow rows MapChange (0x8005922C) reads, the
                                                    same-map moves of MapPartyPlace (0x80059730), the
                                                    bg changes (g_MapBgChangeTable (0x800B8CFC))
    12    resource_palette_row_load (0x80020ACC)    one palette row, unpacked and sent to row 500 + sub
    13    sound_vab_head_open (0x80024314)          a VAB header, opened with SsVabOpenHead
    14    sound_vab_body_transfer (0x800243D0)      a VAB body, sent to SPU RAM
    15    sound_seq_add (0x80024464)                one SEQ sequence
    16    resource_tile_animation_set (0x80020BFC)  unpacked to 0x801C1B00: the images of the map's
                                                    tile animation
    17    sound_id_table_set (0x800244E4)           sixteen 16-bit numbers to g_SoundIds (0x800E4CD8):
                                                    the sound ids the area bank's sequences answer to
    18    resource_tile_pattern_set (0x80020C24)    kept where it lies: its address goes to
                                                    g_TilePatterns[sub] (0x800E0A00) (tile_pattern_set
                                                    (0x8001DB38))
    any other type is stepped over.

The contents of types 9, 16 and 17 are not decoded here.
docs/spec/overview.md §"The command list format", graphics.md, sound.md.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

STRINGS = 1             # resource_command01_set (0x80020480)
TIM = 2                 # resource_tim_add (0x800208A0)
TEXTURE_PAGE = 3        # resource_tpage_load (0x8002097C)
PALETTE = 4             # resource_palette_load (0x80020A08)
MAP_LAYOUT = 5          # resource_bg_set (0x80020B34) -> g_BgDataBuffer (0x800B882C)
MAP_ATTRIBUTES = 6      # resource_bg_attribute_set (0x80020B60) -> g_BgAttributeDataBuffer (0x800B8834)
SECOND_LAYER = 7        # resource_bg_second_set (0x80020BD8) -> g_BgSecondBuffer (0x800B887C)
MAP_ENTER_TABLES = 9    # resource_map_enter_table_set (0x80020B8C) -> 0x801E6B00
PALETTE_ROW = 12        # resource_palette_row_load (0x80020ACC)
VAB_HEAD = 13           # sound_vab_head_open (0x80024314)
VAB_BODY = 14           # sound_vab_body_transfer (0x800243D0)
SEQUENCE = 15           # sound_seq_add (0x80024464)
TILE_ANIMATION = 16     # resource_tile_animation_set (0x80020BFC) -> 0x801C1B00
SOUND_IDS = 17          # sound_id_table_set (0x800244E4) -> g_SoundIds (0x800E4CD8)
TILE_PATTERN = 18       # resource_tile_pattern_set (0x80020C24) -> g_TilePatterns (0x800E0A00)

#: resource_palette_row_load / palette_rows_set (0x8002061C): sub n goes to VRAM row 500 + n.
PALETTE_ROW_BASE = 500


@dataclass(frozen=True)
class CommandType:
    """One case of resource_command_run (0x800202FC)'s switch."""
    number: int
    name: str           # a short name for a list
    handler: str        # the function the case calls, as the register names it


#: Every type resource_command_run (0x800202FC) dispatches; any other is stepped over.
TYPES: dict[int, CommandType] = {t.number: t for t in (
    CommandType(STRINGS, "strings and UI data", "resource_command01_set (0x80020480)"),
    CommandType(TIM, "TIM picture", "resource_tim_add (0x800208A0)"),
    CommandType(TEXTURE_PAGE, "texture page", "resource_tpage_load (0x8002097C)"),
    CommandType(PALETTE, "palette", "resource_palette_load (0x80020A08)"),
    CommandType(MAP_LAYOUT, "tile layout", "resource_bg_set (0x80020B34)"),
    CommandType(MAP_ATTRIBUTES, "attribute plane", "resource_bg_attribute_set (0x80020B60)"),
    CommandType(SECOND_LAYER, "second tile layer", "resource_bg_second_set (0x80020BD8)"),
    CommandType(MAP_ENTER_TABLES, "enter, move and door tables",
                "resource_map_enter_table_set (0x80020B8C)"),
    CommandType(PALETTE_ROW, "palette row", "resource_palette_row_load (0x80020ACC)"),
    CommandType(VAB_HEAD, "VAB header", "sound_vab_head_open (0x80024314)"),
    CommandType(VAB_BODY, "VAB body", "sound_vab_body_transfer (0x800243D0)"),
    CommandType(SEQUENCE, "SEQ sequence", "sound_seq_add (0x80024464)"),
    CommandType(TILE_ANIMATION, "tile-animation images", "resource_tile_animation_set (0x80020BFC)"),
    CommandType(SOUND_IDS, "sound ids", "sound_id_table_set (0x800244E4)"),
    CommandType(TILE_PATTERN, "tile pattern", "resource_tile_pattern_set (0x80020C24)"),
)}


@dataclass(frozen=True)
class Command:
    offset: int         # where the entry starts in the resource
    type: int           # the word's low byte — resource_command_run (0x800202FC)'s switch
    word: int           # the whole word: some handlers read word >> 8
    payload: bytes

    @property
    def arg(self) -> int:
        """`(word >> 8) & 0xFF` — the sub-number the handlers read."""
        return (self.word >> 8) & 0xFF


def commands(buf: bytes) -> list[Command]:
    """resource_command_run (0x800202FC)'s walk over a loaded resource."""
    out, o = [], 0
    while o + 8 <= len(buf):
        word, size = struct.unpack_from("<II", buf, o)
        if word == 0:
            break
        out.append(Command(o, word & 0xFF, word, bytes(buf[o + 8:o + 8 + size])))
        o += 8 + (size >> 2) * 4
    return out


def effective(buf: bytes, command_type: int) -> Command | None:
    """The entry of a type whose payload is in effect once the walk is done:
    resource_command_run (0x800202FC) dispatches every entry, and a fixed-destination handler
    (types 1, 5, 6, 7, 9, 16, 17) overwrites what an earlier one wrote — so the
    last one wins. None when the resource has no entry of that type."""
    found = [c for c in commands(buf) if c.type == command_type]
    return found[-1] if found else None


def pictures(cmds: list[Command]) -> list[tuple[Command, int | None]]:
    """Every type-2 entry with the number resource_tim_add (0x800208A0) gives it:
    None for sub 0 (sent to VRAM at once), else the picture's place among
    the kept ones — 0, 1, ... in list order, whatever the sub's value."""
    out, kept = [], 0
    for c in cmds:
        if c.type != TIM:
            continue
        if c.arg == 0:
            out.append((c, None))
        else:
            out.append((c, kept))
            kept += 1
    return out


def describe(c: Command, picture: int | None = None) -> str:
    """What the handler does with this entry, by its type and sub-number.
    `picture` is a type-2 entry's kept number (`pictures`)."""
    t, sub = c.type, c.arg
    if t == STRINGS:
        return ("the string table, the palette animations' colours and the icons, "
                "unpacked into g_ResourceCommand01Buffer (0x800B8868)")
    if t == TIM:
        if sub == 0:
            return "a TIM picture, unpacked and sent to VRAM at once"
        return ("a TIM picture, kept" + (f" as picture {picture}" if picture is not None else "")
                + " for resource_tim_load (0x80020950)")
    if t == TEXTURE_PAGE:
        if sub < 3:
            return f"texture page {sub}: 256 x 256 8-bit, to tpage {0x19 + 2 * sub:#04x}"
        if sub < 0x80:
            return "a 128 x 128 texture page, to tpage 0x1f"
        if sub < 0x83:
            return f"the tile layer's page {sub - 0x80} (tile_tpage_get (0x8001DC94))"
        return "a texture page sent nowhere"
    if t == PALETTE:
        if sub == 0:
            return "the tile palette: CLUT rows 500 and 501, 508, 510 and 511"
        if sub < 0x80:
            return "one palette row, to CLUT row 506"
        if sub == 0x80:
            return "one palette row, to CLUT row 501"
        return "a palette sent nowhere"
    if t == MAP_LAYOUT:
        return "the tile layout, copied to g_BgDataBuffer (0x800B882C)"
    if t == MAP_ATTRIBUTES:
        return "the attribute plane, copied to g_BgAttributeDataBuffer (0x800B8834)"
    if t == SECOND_LAYER:
        return "the second tile layer, unpacked to g_BgSecondBuffer (0x800B887C)"
    if t == MAP_ENTER_TABLES:
        return ("the map's enter, move and door tables (MapEnterRow rows for "
                "MapChange (0x8005922C), the moves of MapPartyPlace (0x80059730), "
                "the bg changes), copied to 0x801E6B00")
    if t == PALETTE_ROW:
        return f"one palette row, to CLUT row {PALETTE_ROW_BASE + sub}"
    if t == VAB_HEAD:
        return "a VAB header, opened with SsVabOpenHead"
    if t == VAB_BODY:
        return "a VAB body, sent to SPU RAM"
    if t == SEQUENCE:
        return "one SEQ sequence"
    if t == TILE_ANIMATION:
        return "the images of the map's tile animation, unpacked to 0x801C1B00"
    if t == SOUND_IDS:
        return ("the sixteen sound ids the area bank's sequences answer to, "
                "copied to g_SoundIds (0x800E4CD8)")
    if t == TILE_PATTERN:
        return f"tile pattern {sub}: its address kept in g_TilePatterns (0x800E0A00)"
    return "no handler: stepped over"


def summary(cmds: list[Command]) -> str:
    """The list in a line: each type once, in first-seen order, with a count
    when it repeats — '9 · 3×4 · 4×2 · 5 · 6 · 7 · 16'."""
    counts: dict[int, int] = {}
    for c in cmds:
        counts[c.type] = counts.get(c.type, 0) + 1
    return " · ".join(f"{t}×{n}" if n > 1 else f"{t}" for t, n in counts.items())

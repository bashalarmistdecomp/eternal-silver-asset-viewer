"""World (area) maps — a map resource assembled the way the field renderer
draws it. Tileset != world map: the tilesets are the texture pages, the
world map is the tile layout that places them.

Every one of the game's 97 maps is the same command list (formats.
command_list; text.md §"Locations" for how a map id finds its resource):

    type 3 (resource_tpage_load, 0x8002097C)   inflate16 texture pages; (word >> 8) = page:
                             0..2 -> 256x256 8-bit (LoadImage 0x80 x 0x100,
                             tpages 0x19 / 0x1B / 0x1D), 3 -> 0x40 x 0x80
                             VRAM words (tpage_small_image_load (0x8002053C), tpage 0x1F): 16384
                             bytes, which the second layer reads as 256 x
                             128 FOUR-bit texels (`layer2_sheet`)
    type 4 (resource_palette_load, 0x80020A08)   inflate16 palettes; (word >> 8) == 0 is the
                             1024-byte one the tile CLUT rows are MADE FROM
                             (VRAM rows 500 / 501, g_BgCluts (0x800A7DB4)) —
                             made, not copied: see "The CLUT rows" below
    type 5 (resource_bg_set, 0x80020B34)   raw copy into g_BgDataBuffer (0x800B882C) — the TILE LAYOUT
    type 6 (resource_bg_attribute_set, 0x80020B60)   raw copy into g_BgAttributeDataBuffer (0x800B8834) — the ATTRIBUTE plane
                             (below), not graphics

The layout, as bg_block_load (0x80014F3C) reads it for bg_first_draw (0x80014058):

    u16 offset[256]              block (bx, by) at index bx + by * 16 — a
                                 16 x 16 grid of 8 x 8-tile blocks, so the
                                 map plane is 128 x 128 tiles (2048 px square)
    u16 fill_end  (+0x200)       g_BgBlockFillLimit (0x800B88C0)
    u16 data_end  (+0x202)       g_BgBlockPlainLimit (0x800B88C4)
    then fill tiles and LZSS strips

    offset == 0          the block is 64 x tile 0
    offset <  fill_end   the block is 64 x the u16 at layout[offset & ~1]
    offset <  data_end   lz_unpack(layout + offset) (0x80022BF8): 64 tiles,
                         ending at the stream's own end marker
    otherwise            64 raw u16s at layout + offset (an odd offset
                         first runs hex_dump(layout, 0x210) (0x80021510) — no map
                         uses this branch: `block_tiles` refuses it)

A tile (x, y) is block tile (x & 7) + (y & 7) * 8, drawn 16 x 16 by
bg_first_draw's decode (`decode_tile`, rendering.md); bg_first_draw has no
tile-0 skip. The type-6 plane uses the same block rules on a finer grid
(bg_attribute_block_load (0x800154F8): 16 x 16 blocks of 16 x 16 cells), but its readers
are the field's code — the movement probe MapAttributeFreeCheck (0x800692D4)
and MapAttributeFind (0x80069A20) — so it is walkability / trigger data,
not a picture. What shows through layer 0's transparent
pixels is the second layer when it is drawn BEHIND the tiles (its mode 0),
else the frame's clear, which is black (rendering.md §"The field's draw
rule"); `render_tiles` leaves those pixels transparent.

THE CLUT ROWS. resource_palette_load does not upload the stored
palette: it runs palette_zero_fix(buf, 0x200, 0xFF) (0x80020830) over it first —
colour 0 of each 256-colour row becomes the word 0, the ONE word the
GPU does not draw, and every OTHER colour stored as 0 becomes 1, an opaque
black. 0x001F is an ordinary red: there is no colour key. From that buffer
it uploads five rows, by `LoadImage` at y = row + 0x1F4 (palette_rows_load, 0x80020588):

    500, 501   the two halves (palette_rows_set(0, 2, buf) (0x8002061C))     `tile_clut_words`
    508        the second half with bit 15 set on every
               colour and colour 0 of every 16 made 0
               (palette_bg_second_row_set(8, 1, buf) (0x80020670))                    `layer2_clut_words`
    510, 511   the two halves with the first g_PaletteBgCoverCount (0x800B86D4)
               colours of every 16 made 0 (palette_bg_cover_rows_set (0x800206D4),
               to the RECT g_PaletteBgCoverRectangles[0] (0x800AF4EC))                     `overlay_clut_words`

Rows 510 / 511 colour the OVERLAY COPY of a tile whose word has bit 13
(bg_first_draw): the same texels drawn a second time, in
front of an actor that stands over the cell — the roof the party walks
behind. g_PaletteBgCoverCount is 10, or 8 when g_MapPartyKind is 0 (MapLoad, 0x80068A10):
`overlay_keep_from`.

A palette that stores fewer than 0x200 colours (2 of the 97 maps: 9 and 43,
256 colours each) leaves the second half of the game's buffer as the command
before it left it (both handlers inflate into g_LoadBuffer (0x800B8884)). That is not read
here: such a palette gives ONE row, and the functions that need the second
half refuse it.

`attribute_plane` expands the type-6 plane the same way
bg_attribute_block_load fills its cache: 256 offsets, fill_end / data_end at
+0x200 / +0x202 (bg_attribute_data_reset (0x8001543C) copies them to g_BgAttributeBlockFillLimit (0x800B88D8) / g_BgAttributeBlockPlainLimit (0x800B88DC)),
block (bx, by) at bx + by * 16, 256 cells a block, cell (x & 0xF) + (y &
0xF) * 16 (the probe's own index, MapAttributeFreeCheck (0x800692D4)). The
cell bits are in graphics.md §"The attribute plane (type 6)".

`second_layer` returns the type-7 cell map (resource_bg_second_set (0x80020BD8): inflate16 into
g_BgSecondBuffer (0x800B887C), always 0x4000 bytes — 128 rows of 64 s16 cells of 8 x 8 px,
drawn by bg_second_draw (0x800148E0)). It is returned as stored; `render_tiles` does not
draw it. What bg_second_draw makes of it is here:
`layer2_cells` / `decode_layer2_cell` (the cell word), `layer2_row_draws`
(its walk of a row in PAIRS: a pair whose first cell has 0x200 is one sprite
16 px wide, or 32 when the next cell is not 0), `layer2_sheet` (page 3 as
4-bit texels), `layer2_clut_words` (row 508) and `render_second_layer` (the
whole 512 x 1024 plane). The layer's place among the others (behind the
tiles, or in front of everything, opaque or blended) and its scroll are
decided by the map's area record, not by the resource: rendering.md.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from PIL import Image

from . import command_list, inflate16
from .lzss import decompress as lzss_decompress

GRID = 16                   # blocks per row and per column
BLOCK = 8                   # tiles per block side (bg_block_load (0x80014F3C): x >> 3)
TILES = GRID * BLOCK        # 128 tiles per side
TILE_PX = 16
OFFSET_TABLE = 0x200        # 256 u16 offsets
FILL_END_AT, DATA_END_AT = 0x200, 0x202

#: type-3 page index -> (width, height) of its 8-bit page (tpage_image_load (0x800204F0) /
#: tpage_small_image_load (0x8002053C)'s LoadImage rectangles, in pixels).
PAGE_SIZE = {0: (256, 256), 1: (256, 256), 2: (256, 256), 3: (128, 128)}
TILE_CLUT_PALETTE = 0       # the type-4 entry whose rows are the tile CLUTs
CLUT_COLOURS = 256          # one 512-byte VRAM row
CLUT_ROWS = 2               # g_BgCluts = {0x7D00, 0x7D40}

# Tile-value fields, from bg_first_draw (0x80014058) / gpu_primitive_builder (rendering.md).
TILE_U_MASK = 0x000F        # U = (tile & 0xF) * 16
TILE_V_MASK = 0x00F0        # V = tile & 0xF0
TILE_TPAGE_SHIFT, TILE_TPAGE_MASK = 8, 0x3      # g_BgTPages[] (0x800A7D98)
TILE_CLUT_SHIFT, TILE_CLUT_MASK = 12, 0x1       # g_BgCluts[] (0x800A7DB4)
TILE_HFLIP, TILE_VFLIP = 0x4000, 0x8000

# The attribute plane (type 6) — bg_attribute_block_load (0x800154F8).
ATTR_GRID = 16              # blocks per row and per column (bx = x >> 4)
ATTR_BLOCK = 16             # cells per block side
ATTR_CELLS = ATTR_GRID * ATTR_BLOCK     # 256 cells per side
ATTR_CELL_PX = 8            # the probes shift pixels right by 3
# The second tile layer (type 7) — resource_bg_second_set (0x80020BD8) / bg_second_draw (0x800148E0).
SECOND_LAYER = 7            # the command type (command_list.SECOND_LAYER)
LAYER2_COLS, LAYER2_ROWS = 64, 128      # `col & 0x3F`, `row & 0x7F`
LAYER2_BYTES = 2 * LAYER2_COLS * LAYER2_ROWS    # 0x4000
LAYER2_CELL_PX = 8
LAYER2_EMPTY = -1           # the cell that draws nothing (bg_second_draw, 0x800148E0)
LAYER2_PAGE = 3             # the type-3 page its texels are on (tpage 0x1F)
LAYER2_SHEET_W, LAYER2_SHEET_H = 256, 128   # that page's 0x40 x 0x80 words as 4-bit texels
LAYER2_WIDE = 0x200
LAYER2_HFLIP, LAYER2_VFLIP = 0x400, 0x800
LAYER2_CLUTS = 16           # CLUT word 0x7F00 + n: row 508, x = 16 n
#: layer_mix_mode_get (0x8001DFE8)'s answer -> (first ordering-table entry, semi-transparent,
#: blend mode); a cell's entry is first + its depth offset 0..63. The table
#: is drawn from entry 0x3FF down: 0x3C0.. is BEHIND the tiles (0x300..),
#: 0x100.. in front of them and of the actors (0x1FF..0x2FF).
LAYER2_MODES = {0: (0x3C0, False, 0), 3: (0x100, False, 0),
                1: (0x100, True, 0), 5: (0x100, True, 1)}

# bg_first_draw (0x80014058)
TILE_OVERLAY = 0x2000       # bit 13: the tile is queued a second time
TILE_DEPTH_BASE = 0x300     # entry = base + ((word >> 2) & 0xFF)

# The CLUT rows — resource_palette_load (0x80020A08) and its four callees.
PALETTE_COLOURS = 0x200     # palette_zero_fix(buf, 0x200, 0xFF) (0x80020830): two rows of 256
TRANSPARENT = 0x0000        # the one colour word the GPU does not draw
STP = 0x8000                # bit 15: blended when the packet is semi-transparent
CLUT_VRAM_ROW = 0x1F4       # palette_rows_load (0x80020588): LoadImage at y = row + 0x1F4
TILE_CLUT_VRAM_ROWS = (CLUT_VRAM_ROW + 0, CLUT_VRAM_ROW + 1)    # palette_rows_set(0, 2, buf) (0x8002061C)
LAYER2_CLUT_VRAM_ROW = CLUT_VRAM_ROW + 8                        # palette_bg_second_row_set(8, 1, buf) (0x80020670)
OVERLAY_KEEP_FROM = 0xA     # MapLoad (0x80068A10): palette_bg_cover_count_set(0xA) (0x80020DB4) ...
OVERLAY_KEEP_FROM_KIND0 = 8     # ... or (8) when g_MapPartyKind (the area record's byte 0) is 0

Color = tuple[int, int, int, int]


@dataclass(frozen=True)
class Tile:
    u: int
    v: int
    page: int
    clut: int
    hflip: bool
    vflip: bool


def decode_tile(value: int) -> Tile:
    """bg_first_draw (0x80014058)'s decode of a 16-bit tile value. (It also derives a
    draw depth, ((tile >> 2) & 0xFF) + 0x300 — not a CLUT.)"""
    return Tile(u=(value & TILE_U_MASK) * TILE_PX, v=value & TILE_V_MASK,
                page=(value >> TILE_TPAGE_SHIFT) & TILE_TPAGE_MASK,
                clut=(value >> TILE_CLUT_SHIFT) & TILE_CLUT_MASK,
                hflip=bool(value & TILE_HFLIP), vflip=bool(value & TILE_VFLIP))


def layout(raw_map: bytes) -> bytes | None:
    """The layer-0 layout resource_bg_set (0x80020B34) copies into g_BgDataBuffer (0x800B882C)."""
    cmd = command_list.effective(raw_map, command_list.MAP_LAYOUT)
    return cmd.payload if cmd else None


def block_tiles(lay: bytes, bx: int, by: int) -> list[int]:
    """bg_block_load (0x80014F3C)'s fill of one 8 x 8 block: 64 tile values."""
    off = struct.unpack_from("<H", lay, 2 * (bx + by * GRID))[0]
    if off == 0:
        return [0] * (BLOCK * BLOCK)
    fill_end, data_end = struct.unpack_from("<HH", lay, FILL_END_AT)
    if off < fill_end:
        tile = struct.unpack_from("<H", lay, off & ~1)[0]
        return [tile] * (BLOCK * BLOCK)
    if off < data_end:
        out = lzss_decompress(lay[off:])
    else:
        if off & 1:
            raise ValueError(f"block ({bx},{by}): odd raw offset {off:#x} needs "
                             f"hex_dump (0x80021510), which is not read")
        out = lay[off:off + 2 * BLOCK * BLOCK]
    out = out[:2 * BLOCK * BLOCK].ljust(2 * BLOCK * BLOCK, b"\0")
    return list(struct.unpack(f"<{BLOCK * BLOCK}H", out))


def tile_plane(lay: bytes) -> list[list[int]]:
    """The whole layer-0 plane: plane[y][x], 128 x 128 tile values."""
    plane = [[0] * TILES for _ in range(TILES)]
    for by in range(GRID):
        for bx in range(GRID):
            tiles = block_tiles(lay, bx, by)
            for ty in range(BLOCK):
                row = plane[by * BLOCK + ty]
                row[bx * BLOCK:(bx + 1) * BLOCK] = tiles[ty * BLOCK:(ty + 1) * BLOCK]
    return plane


def attributes(raw_map: bytes) -> bytes | None:
    """The type-6 payload resource_bg_attribute_set (0x80020B60) copies into g_BgAttributeDataBuffer (0x800B8834), or None
    when the resource has none (bg_attribute_data_init (0x80015498) then builds an empty plane:
    every offset 0, so every cell reads 0)."""
    cmd = command_list.effective(raw_map, command_list.MAP_ATTRIBUTES)
    return cmd.payload if cmd else None


def attribute_block(att: bytes, bx: int, by: int) -> list[int]:
    """bg_attribute_block_load (0x800154F8)'s fill of one 16 x 16-cell block: 256 cell
    words. The order of its tests is the code's: 0, below fill_end, AT OR
    ABOVE data_end (raw), otherwise an LZSS strip."""
    n = ATTR_BLOCK * ATTR_BLOCK
    off = struct.unpack_from("<H", att, 2 * (bx + by * ATTR_GRID))[0]
    if off == 0:
        return [0] * n
    fill_end, data_end = struct.unpack_from("<HH", att, FILL_END_AT)
    if off < fill_end:
        cell = struct.unpack_from("<H", att, off & ~1)[0]
        return [cell] * n
    if off >= data_end:
        if off & 1:
            raise ValueError(f"attribute block ({bx},{by}): odd raw offset "
                             f"{off:#x} needs hex_dump (0x80021510), which is not read")
        out = att[off:off + 2 * n]
    else:
        out = lzss_decompress(att[off:])
    out = out[:2 * n].ljust(2 * n, b"\0")
    return list(struct.unpack(f"<{n}H", out))


def attribute_plane(att: bytes | None) -> list[list[int]]:
    """The whole attribute plane: plane[y][x], 256 x 256 cell words, one
    per 8 x 8 pixels. `None` (no type-6 command) is the empty plane."""
    plane = [[0] * ATTR_CELLS for _ in range(ATTR_CELLS)]
    if att is None:
        return plane
    for by in range(ATTR_GRID):
        for bx in range(ATTR_GRID):
            cells = attribute_block(att, bx, by)
            for cy in range(ATTR_BLOCK):
                row = plane[by * ATTR_BLOCK + cy]
                row[bx * ATTR_BLOCK:(bx + 1) * ATTR_BLOCK] = \
                    cells[cy * ATTR_BLOCK:(cy + 1) * ATTR_BLOCK]
    return plane


def second_layer(raw_map: bytes) -> bytes | None:
    """The type-7 cell map as resource_bg_second_set (0x80020BD8) inflates it: 0x4000 bytes, 128
    rows of 64 little-endian s16 cells. None when the resource has no
    type-7 command; ValueError when it inflates to another size (no map
    does — graphics.md)."""
    cmd = command_list.effective(raw_map, SECOND_LAYER)
    if cmd is None:
        return None
    out = inflate16.decompress(cmd.payload)
    if len(out) != LAYER2_BYTES:
        raise ValueError(f"second layer inflates to {len(out):#x} bytes, "
                         f"not {LAYER2_BYTES:#x}")
    return out


def palettes(raw_map: bytes) -> dict[int, bytes]:
    """Every type-4 palette resource_palette_load (0x80020A08) uploads, inflated: arg -> the
    15-bit colour words as stored. Entry 0 is the 1024-byte one whose two
    halves are the tile CLUT rows (`clut_rows`)."""
    return {c.arg: inflate16.decompress(c.payload)
            for c in command_list.commands(raw_map)
            if c.type == command_list.PALETTE}


def pages(raw_map: bytes) -> dict[int, bytes]:
    """The texture pages resource_tpage_load (0x8002097C) uploads: page index -> 8-bit pixels."""
    out = {}
    for c in command_list.commands(raw_map):
        if c.type == command_list.TEXTURE_PAGE and c.arg in PAGE_SIZE:
            w, h = PAGE_SIZE[c.arg]
            out[c.arg] = inflate16.decompress(c.payload)[:w * h]
    return out


def clut_rows(raw_map: bytes) -> list[list[Color]]:
    """The tile CLUT rows as the game uploads them (VRAM rows 500 / 501),
    as RGBA: `tile_clut_words` through `words_rgba`. Colour 0 of a row is
    the hole and nothing else is. Two rows — ONE when the palette stores
    only 256 colours (module docstring) — and none without a palette 0."""
    pal = palettes(raw_map).get(TILE_CLUT_PALETTE)
    if pal is None:
        return []
    return [words_rgba(row) for row in tile_clut_words(pal)]


# ---- the CLUT rows the game makes of palette 0 (resource_palette_load, 0x80020A08) ---------------

def tile_depth(value: int) -> int:
    """bg_first_draw (0x80014058)'s ordering-table entry for a tile word.
    The table is drawn from entry 0x3FF down, so a higher entry is behind."""
    return ((value >> 2) & 0xFF) + TILE_DEPTH_BASE


def overlay_keep_from(party_kind: int) -> int:
    """g_PaletteBgCoverCount (0x800B86D4) as MapLoad (0x80068A10) sets it before a map is loaded: how many
    leading colours of every 16 the overlay copy's rows lose."""
    return OVERLAY_KEEP_FROM_KIND0 if party_kind == 0 else OVERLAY_KEEP_FROM


def fix_tile_palette(pal: bytes) -> list[int]:
    """palette_zero_fix(buf, 0x200, 0xFF) (0x80020830) over the inflated type-4 entry 0, as
    colour words: colour 0 of each 256-colour row becomes 0; any other
    colour that is 0 becomes 1. The game runs it over 0x200 words of its
    buffer; this returns the ones the palette STORES (at most 0x200) — the
    rest of a short palette's buffer is not read here."""
    n = min(len(pal) // 2, PALETTE_COLOURS)
    out = list(struct.unpack_from(f"<{n}H", pal))
    for i in range(n):
        if not i & 0xFF:
            out[i] = TRANSPARENT
        elif out[i] == 0:
            out[i] = 1
    return out


def _rows(words: list[int]) -> list[list[int]]:
    """The whole 256-colour rows of a word list."""
    return [words[r * CLUT_COLOURS:(r + 1) * CLUT_COLOURS]
            for r in range(len(words) // CLUT_COLOURS)]


def tile_clut_words(pal: bytes) -> list[list[int]]:
    """VRAM rows 500 / 501 as the game uploads them: the tile CLUT for a
    word with bit 12 clear / set (g_BgCluts[0] (0x800A7DB4) / [2]). One row only when
    the palette stores fewer than 0x200 colours."""
    return _rows(fix_tile_palette(pal))


def overlay_clut_words(pal: bytes, keep_from: int = OVERLAY_KEEP_FROM) -> list[list[int]]:
    """VRAM rows 510 / 511 (palette_bg_cover_rows_set, 0x800206D4): the tile rows with every colour
    whose index & 0xF is below `keep_from` made 0. The overlay copy of a
    bit-13 tile is drawn through these (g_BgCluts[1] (0x800A7DB4) / [3]), so it shows
    only the texels with an index nibble of `keep_from` or more. As many
    rows as `tile_clut_words` gives."""
    words = [TRANSPARENT if (i & 0xF) < keep_from else c
             for i, c in enumerate(fix_tile_palette(pal))]
    return _rows(words)


def layer2_clut_words(pal: bytes) -> list[list[int]]:
    """VRAM row 508 (palette_bg_second_row_set, 0x80020670), as the second layer's sixteen 16-colour
    CLUTs: the tile palette's SECOND row with bit 15 set on every colour and
    colour 0 of each CLUT made 0. ValueError for a palette that stores no
    second row."""
    rows = tile_clut_words(pal)
    if len(rows) < 2:
        raise ValueError(f"tile palette holds {len(pal) // 2} colours, not "
                         f"{PALETTE_COLOURS}: its second row is whatever the "
                         f"inflate buffer held before, which is not read")
    return layer2_cluts(rows[1])


def layer2_cluts(row: list[int]) -> list[list[int]]:
    """Row 508's sixteen CLUTs made from the tile palette's second row as
    colour words: bit 15 set on every colour, colour 0 of each CLUT 0
    (palette_bg_second_row_set (0x80020670) at the load; palette_update
    (0x80020134) for a palette animation's copied CLUTs)."""
    out = [TRANSPARENT if not i & 0xF else c | STP for i, c in enumerate(row)]
    return [out[n * 16:(n + 1) * 16] for n in range(LAYER2_CLUTS)]


def words_rgba(words: list[int]) -> list[Color]:
    """Colour words as RGBA the way the GPU treats them: the word 0 is not
    drawn, every other word is (bit 15 only matters to a semi-transparent
    packet). 5 bits a channel, scaled as parse_ps1_palette scales them."""
    return [((c & 0x1F) << 3, ((c >> 5) & 0x1F) << 3, ((c >> 10) & 0x1F) << 3,
             0 if c == TRANSPARENT else 255) for c in words]


def render_tiles(plane: list[list[int]], pages: dict[int, bytes], rows: list[list[int]],
                 only_overlay: bool = False) -> Image.Image:
    """The tile plane through CLUT rows given as colour WORDS (`rows[bit 12]`):
    `tile_clut_words` for the tile layer, `overlay_clut_words` with
    `only_overlay` for the overlay copies of the bit-13 tiles (what would be
    drawn again in front of an actor standing over every one of them).
    2048 x 2048 RGBA; the word 0 is not drawn. Pages are 256 x 256 8-bit
    (page 3 is the second layer's sheet: no retail map has a tile on it,
    and one that had would be skipped here); a tile whose row the palette
    does not store is skipped too."""
    size = len(plane) * TILE_PX
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    rgba = [words_rgba(r) for r in rows]
    for ty, line in enumerate(plane):
        for tx, value in enumerate(line):
            if only_overlay and not value & TILE_OVERLAY:
                continue
            page = pages.get((value >> TILE_TPAGE_SHIFT) & TILE_TPAGE_MASK)
            row = (value >> TILE_CLUT_SHIFT) & TILE_CLUT_MASK
            if page is None or len(page) < 0x10000 or row >= len(rgba):
                continue
            u, v = (value & TILE_U_MASK) * TILE_PX, value & TILE_V_MASK
            clut = rgba[row]
            hflip, vflip = bool(value & TILE_HFLIP), bool(value & TILE_VFLIP)
            for j in range(TILE_PX):
                src = (v + (TILE_PX - 1 - j if vflip else j)) * 256 + u
                for i in range(TILE_PX):
                    colour = clut[page[src + (TILE_PX - 1 - i if hflip else i)]]
                    if colour[3]:
                        px[tx * TILE_PX + i, ty * TILE_PX + j] = colour
    return img


def tile_texels(plane: list[list[int]], pages: dict[int, bytes],
                x: int, y: int, w: int, h: int) -> list[list[int]]:
    """The 8-bit texel INDICES the tile plane reads for the w x h pixel
    window whose top-left is map pixel (x, y): texels[j][i] is the index
    `render_tiles` colours pixel (x + i, y + j) from -- the same page, u, v
    and mirrors -- before its CLUT row (the tile word's bit 12) turns it into
    a colour. -1 where `render_tiles` draws nothing for want of a page (a
    tile on a page the map does not store, or on page 3). The window must lie
    inside the plane."""
    size = len(plane) * TILE_PX
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > size or y + h > size:
        raise ValueError(f"window ({x}, {y}) {w} x {h} is not inside the {size}-px plane")
    out = [[-1] * w for _ in range(h)]
    for j in range(h):
        py = y + j
        for i in range(w):
            px = x + i
            value = plane[py // TILE_PX][px // TILE_PX]
            page = pages.get((value >> TILE_TPAGE_SHIFT) & TILE_TPAGE_MASK)
            if page is None or len(page) < 0x10000:
                continue
            u, v = (value & TILE_U_MASK) * TILE_PX, value & TILE_V_MASK
            ti, tj = px % TILE_PX, py % TILE_PX
            if value & TILE_HFLIP:
                ti = TILE_PX - 1 - ti
            if value & TILE_VFLIP:
                tj = TILE_PX - 1 - tj
            out[j][i] = page[(v + tj) * 256 + u + ti]
    return out


# ---- the second layer as bg_second_draw (0x800148E0) reads it -------------------------------

@dataclass(frozen=True)
class Layer2Cell:
    """One cell word of the second layer, as bg_second_draw (0x800148E0) reads it."""
    u: int          # texel, (word & 0x1F) * 8
    v: int          # texel, (word & 0x1E0) >> 2
    clut: int       # (word & 0xF000) >> 12: CLUT word 0x7F00 + clut
    depth: int      # (word & 0x1FF) >> 3: added to the mode's first entry
    wide: bool      # 0x200 — only read at the head of a cell pair
    hflip: bool     # 0x400 — not read on a wide cell
    vflip: bool     # 0x800


def decode_layer2_cell(value: int) -> Layer2Cell | None:
    """A cell word; None for -1, the empty cell. (A word of 0 is a cell.)"""
    if value == LAYER2_EMPTY:
        return None
    return Layer2Cell(u=(value & 0x1F) << 3, v=(value & 0x1E0) >> 2,
                      clut=(value & 0xF000) >> 12, depth=(value & 0x1FF) >> 3,
                      wide=bool(value & LAYER2_WIDE),
                      hflip=bool(value & LAYER2_HFLIP), vflip=bool(value & LAYER2_VFLIP))


def layer2_cells(data: bytes) -> list[list[int]]:
    """`second_layer`'s 0x4000 bytes as cells[row][col]: 128 rows of 64
    signed words."""
    flat = struct.unpack(f"<{LAYER2_COLS * LAYER2_ROWS}h", data)
    return [list(flat[r * LAYER2_COLS:(r + 1) * LAYER2_COLS]) for r in range(LAYER2_ROWS)]


def layer2_is_empty(data: bytes | None) -> bool:
    """No cell draws: the resource has no type-7 command, or every cell is -1."""
    return data is None or all(c == LAYER2_EMPTY for row in layer2_cells(data) for c in row)


def layer2_sheet(page3: bytes) -> bytes:
    """Texture page 3 as the second layer reads it: 256 x 128 FOUR-bit
    texels, one byte each here. The page is 0x40 x 0x80 VRAM words; a word
    holds four texels, lowest nibble first — so byte k of a line holds
    texels 2k (low nibble) and 2k + 1."""
    need = LAYER2_SHEET_W * LAYER2_SHEET_H // 2
    if len(page3) < need:
        raise ValueError(f"page 3 holds {len(page3)} bytes, not {need}")
    out = bytearray(LAYER2_SHEET_W * LAYER2_SHEET_H)
    for k in range(need):
        out[2 * k] = page3[k] & 0xF
        out[2 * k + 1] = page3[k] >> 4
    return bytes(out)


@dataclass(frozen=True)
class Layer2Draw:
    """One packet of a layer row: where on the row, how wide, which cell."""
    col: int        # the column it starts at
    cells: int      # how many columns it takes: 1, 2 or 4
    cell: Layer2Cell


def layer2_row_draws(row: list[int], first: int = 0) -> list[Layer2Draw]:
    """bg_second_draw (0x800148E0)'s walk of one row, in PAIRS, over
    the 64 columns from column `first` (even: the game's first column is
    (x >> 4) * 2), wrapping. A pair whose first cell has 0x200 is one sprite
    16 px wide, or 32 when the cell after it is not 0 (it is compared with
    0, not with -1) — and the walk skips the 2 or 4 columns it covers.
    Otherwise the pair's two cells are 8 x 8 each. `col` is not wrapped: a
    32-px cell at column 62 runs to column 66.

    In the retail maps a 32-px cell is always `head, 1, head + 16 px, 0`
    (44,873 of them, none at column 62): its second pair is itself the
    16-px sprite of its right half, so the picture is the same wherever the
    walk starts."""
    if first & 1:
        raise ValueError(f"the walk starts on a pair: column {first} is odd")
    out = []
    col = first
    end = first + LAYER2_COLS
    while col < end:
        t = row[col % LAYER2_COLS]
        if t != LAYER2_EMPTY and t & LAYER2_WIDE:
            n = 4 if row[(col + 1) % LAYER2_COLS] != 0 else 2
            out.append(Layer2Draw(col, n, decode_layer2_cell(t)))
            col += n
            continue
        for k in range(2):
            t = row[(col + k) % LAYER2_COLS]
            if t != LAYER2_EMPTY:
                out.append(Layer2Draw(col + k, 1, decode_layer2_cell(t)))
        col += 2
    return out


def layer2_texel(sheet: bytes, cell: Layer2Cell, i: int, j: int, cells: int = 1) -> int:
    """The 4-bit texel a packet shows at pixel (i, j) of itself. A mirrored
    8 x 8 cell is taken as the exact mirror (the quad's corner texels run
    cell + 7 back to cell - 1); a wide cell's mirror bits are not read; a
    packet's texels past u = 255 wrap inside the page. (How the console
    steps across a quad, and that a sprite's u wraps, are the hardware's —
    not in the C.)"""
    mirror_x = cell.hflip and cells == 1
    mirror_y = cell.vflip and cells == 1
    tv = cell.v + (LAYER2_CELL_PX - 1 - j if mirror_y else j)
    tu = (cell.u + (LAYER2_CELL_PX - 1 - i if mirror_x else i)) & 0xFF
    return sheet[tv * LAYER2_SHEET_W + tu]


def second_layer_indexes(cells_data: bytes, page3: bytes) -> bytes:
    """The second layer's whole plane, 512 x 1024, as row-508 colour
    indexes: 16 * CLUT + texel where a packet draws a texel other than 0,
    0 where none does (colour 0 of every CLUT of row 508 is 0, the hole:
    `layer2_clut_words`). Every row walked from column 0
    (`layer2_row_draws`), texels by `layer2_texel`, a later packet drawn
    over an earlier one."""
    sheet = layer2_sheet(page3)
    w = LAYER2_COLS * LAYER2_CELL_PX
    out = bytearray(w * LAYER2_ROWS * LAYER2_CELL_PX)
    for r, row in enumerate(layer2_cells(cells_data)):
        for d in layer2_row_draws(row):
            base = d.cell.clut * 16
            for j in range(LAYER2_CELL_PX):
                at = (r * LAYER2_CELL_PX + j) * w
                for i in range(d.cells * LAYER2_CELL_PX):
                    t = layer2_texel(sheet, d.cell, i, j, d.cells)
                    if t:
                        out[at + (d.col * LAYER2_CELL_PX + i) % w] = base | t
    return bytes(out)


def layer2_image(indexes: bytes, cluts: list[list[int]]) -> Image.Image:
    """`second_layer_indexes` through row 508's sixteen CLUTs as colour
    words (`layer2_clut_words`): 512 x 1024 RGBA, transparent where no
    cell draws."""
    table = [bytes(c) for clut in cluts for c in words_rgba(clut)]
    w, h = LAYER2_COLS * LAYER2_CELL_PX, LAYER2_ROWS * LAYER2_CELL_PX
    return Image.frombytes("RGBA", (w, h), b"".join(table[v] for v in indexes))


def render_second_layer(cells_data: bytes, page3: bytes, pal: bytes) -> Image.Image:
    """The second layer's whole plane, 512 x 1024 RGBA, transparent where no
    cell draws: `second_layer_indexes` through `layer2_clut_words`."""
    return layer2_image(second_layer_indexes(cells_data, page3), layer2_clut_words(pal))

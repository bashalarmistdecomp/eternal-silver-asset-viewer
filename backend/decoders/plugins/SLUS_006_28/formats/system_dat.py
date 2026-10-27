"""SYSTEM.DAT (LUNADATA resource 1) as the game loads it, and OPEN1.BIN.

SYSTEM.DAT is a resource command list (formats.command_list): main
(0x80013D2C) loads it at boot with resource_load_run(1) (0x800202CC), and
resource_command_run (0x800202FC) runs its commands:

    type 1   resource_command01_set (0x80020480) unpacks it into the block at
             g_ResourceCommand01Buffer (0x800B8868), which other code reads
             at fixed places:
               +0x0000  the string table (formats.system_strings)
               +0x599C  the palette animations' colours: GameStart
                        (0x80055B60) sets g_PaletteAnimationCols (0x800B8B04)
                        here, and palette_animation_step (0x800263F4) copies
                        a mode-1 animation's frames from it
               +0x899C  the icons: main_buffer_init (0x80013E04) hands this
                        to IconInit (0x8001ABCC): 16-bit offsets, then one
                        lz_unpack (0x80022BF8) stream an icon, 24 x 24 at 8
                        bits, drawn with palette row 502 (IconCellDraw
                        (0x8001AD60)) — `icon_offsets`, `icon_pixels`,
                        `icon_image`
    type 2   resource_tim_add (0x800208A0): with word >> 8 == 0, unpacked and
             sent at once by tim_image_load (0x8002073C): a TIM, the glyph
             atlas (`glyph_atlas`). ankprint_glyph_draw (0x80025B90) draws it
             with palette 0x7EC0 + 11 + (cell >> 14): row 507, sub-palettes
             11 to 14.
    type 12  resource_palette_row_load (0x80020ACC): one palette row each
             (`palette_rows`).

SLPS_013.97's block holds the same parts at other places: its GameStart
(SLPS_013.97 0x80058EC4) points g_PaletteAnimationCols at +0x3BF4 and its
main_buffer_init (SLPS_013.97 0x800149C4) hands IconInit (0x8001ABCC;
SLPS_013.97 0x8001BE30) +0x6BF4 (`block_places`).

OPEN1.BIN (resource 3) is read below by deflate-stream search, not by its
commands.
"""

import struct
from dataclasses import dataclass, field, replace

from PIL import Image

from decoders.plugins.SLUS_006_28.formats import command_list
from decoders.plugins.SLUS_006_28.formats.inflate16 import decompress as inflate16
from decoders.plugins.SLUS_006_28.records import programs
from decoders.psx.formats.deflate import find_deflate_streams
from decoders.psx.formats.palette import Color, parse_ps1_palette


@dataclass
class ParsedAsset:
    """A decoded asset file with renderable layers and metadata."""
    name: str
    layers: list[Image.Image] = field(default_factory=list)
    info: str = ""
    #: what each layer is, when the decoder knows ("" each otherwise)
    labels: list[str] = field(default_factory=list)


#: SYSTEM.DAT is LUNADATA resource 1 (main: resource_load_run(1)).
RESOURCE = 1
#: resource_command_run's case 12 -> resource_palette_row_load
PALETTE_ROW = 12
#: palette_rows_set (0x8002061C) -> palette_rows_load (0x80020588): the row
#: goes to (0, 0x1F4 + n) of video memory, n = the command word's second byte
ROW_BASE = 0x1F4
#: for n == 7 resource_palette_row_load also has palette_glyph_zero_set
#: (0x8002087C) make these colours 0
GLYPH_ROW = 7
GLYPH_ZEROED = (0xB0, 0xC0, 0xD0, 0xE0)
#: FaceCellDraw (0x8001B4B0) draws a portrait with palette 0x7DC0: row 503
FACE_ROW = 503
#: resource_tim_add sends a TIM at once when the word's second byte is 0
TIM_NOW = 0
#: ankprint_glyph_draw: palette 0x7EC0 + (((cell >> 14) + 0xB) & 0xF)
TEXT_ROW = 507
GLYPH_SUB_PALETTES = (11, 12, 13, 14)
#: the type-1 block's places (main_buffer_init, GameStart)
PALETTE_ANIMATION_COLOURS = 0x599C
ICONS = 0x899C
#: ... and SLPS_013.97's (module docstring)
JP_PALETTE_ANIMATION_COLOURS = 0x3BF4
JP_ICONS = 0x6BF4


def block_places(image) -> tuple[int, int]:
    """(the palette animations' colours, the icons): the type-1 block's
    places in `image`'s program."""
    if programs.program_of(image) == programs.JP:
        return JP_PALETTE_ANIMATION_COLOURS, JP_ICONS
    return PALETTE_ANIMATION_COLOURS, ICONS

#: IconCellDraw (0x8001AD60): a 24 x 24 sprite, palette 0x7D80 (row 502),
#: colour 0x808080, or 0x404040 for a dimmed cell (IconCellSet's flag)
ICON_SIDE = 24
ICON_ROW = 502
ICON_COLOUR = 0x80
ICON_DIMMED = 0x40


def bit15_set(words, mask: int = 0xFF) -> list[int]:
    """palette_bit15_set (0x800207E8)(cols, n, mask): a colour whose position
    has none of `mask`'s bits becomes 0, every other gets bit 15. Every call
    passes 0xFF: colour 0 becomes 0 and the other 255 keep their value with
    bit 15 set, a stored 0 becoming 0x8000."""
    return [0 if not (i & mask) else w | 0x8000 for i, w in enumerate(words)]


def palette_rows(res1: bytes) -> dict[int, tuple[int, ...]]:
    """{video-memory row: its 256 colour words} for each command 12 of a
    resource, as resource_palette_row_load leaves the row: the payload
    unpacked (inflate16), bit15_set(colours, 0xFF), and for n = 7 the four
    GLYPH_ZEROED colours made 0. A later command for the same row replaces
    the earlier one, as the second upload does."""
    rows: dict[int, tuple[int, ...]] = {}
    for cmd in command_list.commands(res1):
        if cmd.type != PALETTE_ROW:
            continue
        raw = inflate16(cmd.payload)
        if len(raw) < 0x200:
            raise ValueError(f"command {cmd.word:#x} unpacks to {len(raw)} bytes; "
                             f"the row takes 0x200")
        words = bit15_set(struct.unpack_from("<256H", raw))
        if cmd.arg == GLYPH_ROW:
            for i in GLYPH_ZEROED:
                words[i] = 0
        rows[ROW_BASE + cmd.arg] = tuple(words)
    return rows


def colours(words) -> list[Color]:
    """RGBA for colour words as the GPU draws a texel with them: the word 0
    is not drawn (alpha 0); any other word is, 0x8000 as black (bit 15 only
    picks blending in a semi-transparent draw). Each five-bit channel is
    shifted up by 3, as `parse_ps1_palette` does."""
    return [((w & 0x1F) << 3, ((w >> 5) & 0x1F) << 3, ((w >> 10) & 0x1F) << 3,
             0 if w == 0 else 255) for w in words]


def glyph_atlas(res1: bytes):
    """The TIM of the type-2 command resource_tim_add sends at once: the
    glyph atlas, as `psx.formats.tim.TimImage`. Raises ValueError when the
    resource has no such command or it is not a TIM."""
    from decoders.psx.formats.tim import parse_tim

    for cmd in command_list.commands(res1):
        if cmd.type == command_list.TIM and cmd.arg == TIM_NOW:
            tim = parse_tim(inflate16(cmd.payload))
            if tim is None:
                raise ValueError(f"command {cmd.word:#x} does not unpack to a TIM")
            return tim
    raise ValueError("no type-2 command sent at once: not resource 1")


def sub_palette(row, k: int) -> list[Color]:
    """Sub-palette k (colours 16k .. 16k + 15) of a row's words, as colours."""
    return colours(row[16 * k:16 * (k + 1)])


def glyph_atlas_layers(res1: bytes) -> list[tuple[str, Image.Image]]:
    """[(label, image)]: the atlas under each of row 507's sub-palettes 11
    to 14, the colours ankprint_glyph_draw picks by the cell's top bits."""
    tim = glyph_atlas(res1)
    row = palette_rows(res1)[TEXT_ROW]
    return [(f"sub-palette {k}", replace(tim, cluts=[sub_palette(row, k)]).to_image(0))
            for k in GLYPH_SUB_PALETTES]


def icon_offsets(blk: bytes, icons: int = ICONS) -> list[int]:
    """The icons' offset table at the type-1 block's +0x899C, one u16 per
    icon number, each counted from +0x899C (IconInit (0x8001ABCC) stores the
    one address as both g_IconOffsets and g_IconBase). Nothing in the code
    bounds an icon number; the table is read up to where the first icon's
    pixels begin (a layout reading). `icons` is the program's place for
    them (`block_places`)."""
    out: list[int] = []
    first = len(blk) - icons
    while 2 * len(out) < first:
        off = struct.unpack_from("<H", blk, icons + 2 * len(out))[0]
        out.append(off)
        if off:
            first = min(first, off)
    return out


def icon_pixels(blk: bytes, offsets: list[int], icon: int, icons: int = ICONS) -> bytes:
    """Icon `icon`'s 24 x 24 texels as IconImageLoad (0x8001ADEC) sends them:
    lz_unpack (0x80022BF8, formats.lzss) of the stream at g_IconBase + its
    offset into g_IconImageBuffer (0x800E03C8), of which LoadImage takes
    24 x 24 bytes (g_IconImageRectangle (0x800B858C): 12 x 24 words)."""
    from .lzss import decompress

    out = decompress(blk[icons + offsets[icon]:])
    if len(out) < ICON_SIDE * ICON_SIDE:
        raise ValueError(f"icon {icon} unpacks to {len(out)} bytes, short of 24 x 24")
    return out[:ICON_SIDE * ICON_SIDE]


def icon_image(texels: bytes, colours: list[Color], level: int = ICON_COLOUR) -> Image.Image:
    """An icon as IconCellDraw (0x8001AD60) draws it: each texel through row
    502, the word 0 not drawn, each five-bit channel times level / 0x80 (the
    sprite's colour: 0x80 as stored, 0x40 dimmed)."""
    def scale(c: int) -> int:
        return min(31, (c >> 3) * level >> 7) << 3

    if len(texels) == ICON_SIDE * ICON_SIDE:
        try:
            drawn = {t: bytes((scale(r), scale(g), scale(b), a))
                     for t in set(texels) for r, g, b, a in (colours[t],)}
        except ValueError:
            pass                            # a channel out of a byte: set one by one
        else:
            return Image.frombytes("RGBA", (ICON_SIDE, ICON_SIDE),
                                   b"".join(map(drawn.__getitem__, texels)))
    im = Image.new("RGBA", (ICON_SIDE, ICON_SIDE), (0, 0, 0, 0))
    px = im.load()
    for i, t in enumerate(texels):
        r, g, b, a = colours[t]
        px[i % ICON_SIDE, i // ICON_SIDE] = (scale(r), scale(g), scale(b), a)
    return im


def parse_system_dat(raw: bytes, name: str = "SYSTEM.DAT",
                     places: tuple[int, int] = (PALETTE_ANIMATION_COLOURS, ICONS)) -> ParsedAsset:
    """SYSTEM.DAT's one picture, the glyph atlas, under the four text
    sub-palettes, and what its commands are. `places` are the type-1
    block's (`block_places`)."""
    try:
        cmds = command_list.commands(raw)
        tim = glyph_atlas(raw)
        layers = glyph_atlas_layers(raw)
    except (ValueError, KeyError, struct.error) as e:
        return ParsedAsset(name=name, info=f"{name}\nnot read as resource 1: {e}")
    rows = sorted(palette_rows(raw))
    info = [name,
            f"Size: {len(raw):,} bytes; resource {RESOURCE}, "
            f"{len(cmds)} commands: " + ", ".join(f"{c.word:#x}" for c in cmds),
            "",
            f"Glyph atlas: the type-2 TIM, {tim.width} x {tim.height} at "
            f"{4 if tim.mode == 0 else 8} bits, video memory ({tim.vram_x}, {tim.vram_y}).",
            "ankprint_glyph_draw (0x80025B90) draws it with row 507, sub-palette",
            "11 + (cell >> 14); the layers are those four, as resource 1's",
            "command 0x70C loads the row.",
            "",
            "Palette rows (type 12): " + ", ".join(str(r) for r in rows) +
            ": 502 the icons, 503 the portraits, 507 the text.",
            "",
            "The type-1 block (resource_command01_set (0x80020480)):",
            "  +0x0000  the string table (the Strings tab)",
            f"  +0x{places[0]:04X}  the palette animations' colours: GameStart (0x80055B60)",
            "           points g_PaletteAnimationCols (0x800B8B04) here;",
            "           palette_animation_step (0x800263F4) copies from it",
            f"  +0x{places[1]:04X}  the icons: IconInit (0x8001ABCC), 24 x 24 at 8 bits,",
            "           palette row 502 (IconCellDraw (0x8001AD60)): the icons items"]
    return ParsedAsset(name=name, layers=[im for _l, im in layers],
                       labels=[label for label, _im in layers], info="\n".join(info))


def parse_open1_bin(raw: bytes, name: str = "OPEN1.BIN") -> ParsedAsset:
    """Parse OPEN1.BIN — title screen / logo layers.

    Structure:
      - 65536-byte layers (256x256 indexed) before data_offset
      - 1024-byte palette
      - Additional streams after data_offset (72K+ each — larger images)
    """
    if len(raw) < 8:
        return ParsedAsset(name=name, info="Too small to parse")

    streams = find_deflate_streams(raw, 8)

    layers_65k = [s.data for s in streams if s.decompressed_size == 65536]
    palettes = [s.data for s in streams
                if s.decompressed_size in (512, 1024)]
    big_streams = [s for s in streams
                   if s.decompressed_size > 1024
                   and s.decompressed_size != 65536]

    palette = parse_ps1_palette(palettes[0]) if palettes else []

    layers = []
    # Standard 256x256 layers
    for data in layers_65k:
        img = _render_indexed(data, palette, 256, 256)
        layers.append(img)

    # Larger images (title artwork, etc.)
    for s in big_streams:
        img = _render_indexed_auto(s.data, palette)
        if img:
            layers.append(img)

    info = (
        f"{name}\n"
        f"Size: {len(raw):,} bytes\n"
        f"Streams: {len(streams)}\n"
        f"Layers (256x256): {len(layers_65k)}\n"
        f"Large images: {len(big_streams)}\n"
        f"Palettes: {len(palettes)}\n"
        f"Total renderable: {len(layers)}"
    )
    return ParsedAsset(name=name, layers=layers, info=info)


def _render_indexed(data: bytes, palette: list, w: int, h: int) -> Image.Image:
    """Render 8-bit indexed pixel data to RGBA."""
    from decoders.psx.formats.renderer import render_indexed_layer
    return render_indexed_layer(data, palette, w, h)


def _render_indexed_auto(data: bytes, palette: list) -> Image.Image | None:
    """Render indexed data, auto-detecting dimensions (width=256)."""
    size = len(data)
    if size < 256:
        return None
    w = 256
    h = size // w
    if h < 1:
        return None
    return _render_indexed(data, palette, w, h)

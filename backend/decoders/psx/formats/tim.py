"""PS1 TIM image decoding.

TIM is the standard PlayStation texture container: a header describing pixel
depth and VRAM placement, an optional CLUT block, then the pixel block. A
game keeps its TIMs wherever it likes — SSSC packs each into a command of a
LUNADATA resource (decoders.plugins.SLUS_006_28.formats.resource_pictures),
The Making of Lunar keeps them plain in its EXE.

The layout below is the one SSSC's own parser walks
(`tim_image_load (0x8002073C)` -> `GsGetTimInfo (0x8008FC48)` -> `LoadImage`); see docs/spec/sprites.md.

    u32 magic = 0x00000010
    u32 flags       bits 0-2 = pixel mode, bit 3 = has CLUT
    [if has CLUT]
        u32 length (includes this 12-byte header)
        u16 clut_x, clut_y      VRAM position
        u16 clut_w, clut_h      colours per CLUT, number of CLUTs
        u16 colours[clut_w * clut_h]
    u32 length (includes this 12-byte header)
    u16 pix_x, pix_y            VRAM position
    u16 pix_w, pix_h            width in 16-bit VRAM words, height in rows

`pix_w` counts VRAM halfwords, so the real pixel width is `pix_w * 4` at 4bpp
and `pix_w * 2` at 8bpp.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Iterator

from PIL import Image

from decoders.psx.formats.palette import Color, parse_ps1_palette

TIM_MAGIC = 0x00000010

MODE_4BIT = 0
MODE_8BIT = 1
MODE_16BIT = 2
MODE_24BIT = 3

MODE_NAMES = {
    MODE_4BIT: "4-bit CLUT",
    MODE_8BIT: "8-bit CLUT",
    MODE_16BIT: "16-bit direct",
    MODE_24BIT: "24-bit direct",
}

# byte -> its two 4-bit pixels, low nibble first (PS1 packs left pixel low)
_NIBBLES = [bytes((b & 0xF, b >> 4)) for b in range(256)]

# The 8-byte header and a pixel block's 12-byte header: anything shorter
# cannot be a TIM.
_MIN_TIM = 20


@dataclass
class TimImage:
    """A decoded TIM. Pixels stay packed until `to_image()` is called."""

    mode: int
    width: int
    height: int
    vram_x: int = 0
    vram_y: int = 0
    clut_x: int = 0
    clut_y: int = 0
    cluts: list[list[Color]] = field(default_factory=list)
    pixels: bytes = b""
    byte_size: int = 0          # bytes consumed by the whole TIM
    #: The CLUT rows as stored: 16-bit colour words, one list per row.
    clut_words: list[list[int]] = field(default_factory=list)

    @property
    def mode_name(self) -> str:
        return MODE_NAMES.get(self.mode, f"mode {self.mode}")

    @property
    def clut_count(self) -> int:
        return len(self.cluts)

    def to_image(self, clut_index: int = 0) -> Image.Image:
        """Render to RGBA. `clut_index` picks among multi-CLUT TIMs."""
        w, h = self.width, self.height
        if w <= 0 or h <= 0:
            return Image.new("RGBA", (1, 1), (0, 0, 0, 0))

        if self.mode == MODE_16BIT:
            return self._render_direct16(w, h)
        if self.mode == MODE_24BIT:
            return self._render_direct24(w, h)

        if self.mode == MODE_4BIT:
            indices = b"".join(_NIBBLES[b] for b in self.pixels)
        else:
            indices = self.pixels

        need = w * h
        if len(indices) < need:
            indices = indices + bytes(need - len(indices))

        palette = self.cluts[clut_index] if clut_index < len(self.cluts) else []
        return _paletted_to_rgba(indices[:need], w, h, palette)

    def _render_direct16(self, w: int, h: int) -> Image.Image:
        # PS1 stores 16-bit pixels as little-endian ABGR1555: bit 15 is stp,
        # 14-10 blue, 9-5 green, 4-0 RED (docs/spec/formats/palettes.md, and
        # `parse_ps1_palette` below reads it the same way). Pillow's "BGR;15"
        # raw mode unpacks the halfword fast but puts the LOW five bits in
        # its first band, i.e. it hands back (B, G, R) under an "RGB" label —
        # so the bands must be swapped back or red and blue come out
        # exchanged. The stp bit is dropped (treated as opaque).
        # Pillow also upscales 5 bits to 8 by REPLICATION (31 -> 255) where
        # this tree's convention is a plain shift (31 -> 248, "multiply by
        # 8" — docs/spec/formats/palettes.md, and `parse_ps1_palette`).
        # Masking off the replicated low bits converts one law to the other
        # exactly: (v5<<3 | v5>>2) & 0xF8 == v5<<3.
        need = w * h * 2
        data = self.pixels[:need].ljust(need, b"\x00")
        packed = Image.frombytes("RGB", (w, h), data, "raw", "BGR;15")
        blue, green, red = packed.split()
        merged = Image.merge("RGB", (red, green, blue))
        return merged.point(lambda v: v & 0xF8).convert("RGBA")

    def _render_direct24(self, w: int, h: int) -> Image.Image:
        # Three bytes a pixel, R G B, in rows of `pix_w` halfwords: a row
        # whose width is odd ends on a padding byte.
        stride = (w * 3 + 1) // 2 * 2
        need = stride * h
        data = self.pixels[:need].ljust(need, b"\x00")
        return Image.frombytes("RGB", (w, h), data, "raw", "RGB",
                               stride).convert("RGBA")


def _paletted_to_rgba(indices: bytes, w: int, h: int,
                      palette: list[Color]) -> Image.Image:
    """Map index bytes through a CLUT, honouring per-colour alpha."""
    img = Image.frombytes("P", (w, h), indices)

    flat: list[int] = []
    alpha_lut: list[int] = []
    for i in range(256):
        r, g, b, a = palette[i] if i < len(palette) else (0, 0, 0, 0)
        flat.extend((r, g, b))
        alpha_lut.append(a)
    img.putpalette(flat)

    alpha = img.point(alpha_lut, mode="L")
    rgba = img.convert("RGB").convert("RGBA")
    rgba.putalpha(alpha)
    return rgba


def parse_tim(data: bytes, offset: int = 0) -> TimImage | None:
    """Parse a TIM at `offset`. Returns None if it is not a valid TIM."""
    if len(data) - offset < _MIN_TIM:
        return None
    try:
        magic, flags = struct.unpack_from("<II", data, offset)
    except struct.error:
        return None
    if magic != TIM_MAGIC:
        return None

    mode = flags & 0x7
    if mode > MODE_24BIT:
        return None

    pos = offset + 8
    cluts: list[list[Color]] = []
    clut_words: list[list[int]] = []
    clut_x = clut_y = 0

    if flags & 0x8:
        try:
            length, clut_x, clut_y, clut_w, clut_h = struct.unpack_from(
                "<IHHHH", data, pos)
        except struct.error:
            return None
        if length < 12 or pos + length > len(data):
            return None
        body = data[pos + 12:pos + length]
        stride = clut_w * 2
        if stride:
            for i in range(clut_h):
                chunk = body[i * stride:(i + 1) * stride]
                if len(chunk) < stride:
                    break
                cluts.append(parse_ps1_palette(chunk))
                clut_words.append(list(struct.unpack(f"<{clut_w}H", chunk)))
        pos += length

    try:
        length, pix_x, pix_y, pix_w, pix_h = struct.unpack_from("<IHHHH", data, pos)
    except struct.error:
        return None
    if length < 12 or pos + length > len(data):
        return None

    if mode == MODE_4BIT:
        width = pix_w * 4
    elif mode == MODE_8BIT:
        width = pix_w * 2
    elif mode == MODE_24BIT:
        width = pix_w * 2 // 3          # three bytes a pixel
    else:
        width = pix_w

    # Guard against a coincidental 0x10 magic in unrelated data: a real TIM is
    # destined for VRAM, which is 1024x512 16-bit words.
    if not (0 < pix_w <= 1024 and 0 < pix_h <= 512):
        return None
    if pix_x > 1024 or pix_y > 512:
        return None

    return TimImage(
        mode=mode,
        width=width,
        height=pix_h,
        vram_x=pix_x,
        vram_y=pix_y,
        clut_x=clut_x,
        clut_y=clut_y,
        cluts=cluts,
        pixels=data[pos + 12:pos + length],
        byte_size=(pos + length) - offset,
        clut_words=clut_words,
    )


def tims_in_stream(data: bytes) -> Iterator[tuple[int, TimImage]]:
    """Yield every TIM inside one decompressed stream, as `(offset, tim)`.

    A stream is often a *bundle* of TIMs laid end to end, so parsing only
    offset 0 misses most of them. After each successful parse the walk
    continues at the end of that image; where that does not land on another
    TIM it falls back to a 4-byte-aligned search for the next magic.
    """
    pos, end = 0, len(data)
    while pos + _MIN_TIM <= end:
        tim = parse_tim(data, pos)
        if tim is not None and tim.byte_size >= _MIN_TIM:
            yield pos, tim
            pos += tim.byte_size
            pos += (-pos) % 4          # bundles keep entries word-aligned
            continue

        # Not a TIM here: hunt for the next word-aligned magic.
        pos += (-pos) % 4
        nxt = data.find(b"\x10\x00\x00\x00", pos + 4)
        if nxt < 0:
            return
        pos = nxt - (nxt % 4)
        if nxt % 4:
            pos = nxt + (4 - nxt % 4)

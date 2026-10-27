"""PS1 16-bit ABGR 1555 palette decoding."""

import struct

Color = tuple[int, int, int, int]  # RGBA


def parse_ps1_palette(pal_data: bytes) -> list[Color]:
    """Decode PS1 16-bit palette data into RGBA tuples.

    PS1 16-bit format (little-endian):
        Bit 15:    Semi-transparency flag
        Bits 14-10: Blue  (5 bits)
        Bits 9-5:   Green (5 bits)
        Bits 4-0:   Red   (5 bits)

    Only the word 0x0000 is transparent: the GPU skips that texel and draws
    every other one (docs/spec/formats/palettes.md). 0x001F is plain red.
    """
    colors: list[Color] = []
    for i in range(0, len(pal_data) - 1, 2):
        c = struct.unpack_from("<H", pal_data, i)[0]
        r = (c & 0x1F) << 3
        g = ((c >> 5) & 0x1F) << 3
        b = ((c >> 10) & 0x1F) << 3
        a = 0 if c == 0x0000 else 255
        colors.append((r, g, b, a))
    return colors

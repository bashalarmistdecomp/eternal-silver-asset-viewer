"""STFIELD.DAT, LUNADATA resource 2: the common sprite sheet, as
sprite_reset (0x80018DBC) reads it.

It is not a command list. sprite_reset(y) reads resource 2 with
resource_load (0x80020230) and takes its first eight 16-bit words as
places, each counted in 4 bytes from the resource's start:

    word 0         a palette of 0x100 colours. Colour 0 of each of the 16
                   sub-palettes is made 0 (clut[i * 16] = 0); LoadClut
                   (0x8008E808) sends it to (0, 0x1FB), row 507, and the 256
                   colours are copied to row 7 of the palette buffer
                   (0x801D6980). No bit 15 is set.
    words 1, 3, 5  three packed sprite data (SpriteDataHead,
                   include/sprite.h), unpacked by inflate_buffer (0x80021D6C)
                   to the three addresses of g_SpriteDataAddresses
                   (0x80011054): g_SpriteData0 (0x800DE088), g_SpriteData1
                   (0x800DDFB0) and g_SpriteData2 (0x800DF370). In each, the
                   texel records from head word 4 to word 5 ((end - first) / 3
                   records of 12 bytes) get page 10 at +2.
    word 7         a packed 4-bit image, unpacked into the load buffer; its
                   lines from y on (0x80 bytes, 256 texels a line) go with
                   LoadImage to (0x3C0, y), 0x40 words wide and 0x100 - y
                   lines high: sprite page 10 (g_SpritePageCorners
                   (0x800A7F88) row 10 is (0x3C0, 0)). Lines past the
                   unpacked image are whatever the buffer held, not resource
                   bytes.
    words 2, 4, 6  not read.

Callers: main (0x80013D2C) and sprite_init (0x80018BFC) with y = 0,
MenuNoWalkRun (0x80075BD8) with y = 0x40.

A record drawn from a bank takes its palette from its draw word (+0xE):
sprite_draw (0x8001A528) uses GetClut(word & 0xFF, 0x1F8 | ((word >> 8) & 3)),
so every word in `USES` is row 507, sub-palette (word & 0xFF) >> 4. `USES`
lists each binding of a bank the C makes, and `DIGITS` the amount digits
BtlAmountRecordsInit (0x8004A8A0) cuts from the sheet's first line.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from decoders.plugins.SLUS_006_28.formats.inflate16 import decompress as inflate16

#: sprite_reset: resource_load(2, ...)
RESOURCE = 2
#: LoadClut(..., 0, 0x1FB)
PALETTE_ROW = 0x1FB
#: the head words: palette, the three banks, the image
PALETTE_WORD = 0
BANK_WORDS = (1, 3, 5)
IMAGE_WORD = 7
HEAD_WORDS = 8
#: SpriteDataHead word 4 / word 5: the texel records; 12 bytes a record
TEXEL_RECORDS = 4
TEXEL_RECORDS_END = 5
TEXEL_RECORD_BYTES = 12
#: the page sprite_reset writes into every texel record (+2)
PAGE = 10
#: the image: 0x40 words (256 4-bit texels) a line, 0x80 bytes
SHEET_WIDTH = 256
LINE_BYTES = 0x80
#: g_SpriteDataAddresses' three blocks, in order
BANK_NAMES = ("g_SpriteData0", "g_SpriteData1", "g_SpriteData2")

#: Every binding of a resource-2 bank in the C: (bank, draw word, what,
#: where). Sub-palette (word & 0xFF) >> 4 of row 507.
USES = (
    (0, 0x760, "the battle menu's marks: records 1 to 3, animations 2, 0xA, 0xB",
     "BtlMenuInit (0x800441B4)"),
    (0, 0x760, "the shop's pointer and cursors, the list's up and down marks: "
               "animations 12, 8, 10, 4, 5",
     "ShopOpen (0x800506EC) -> ShopObjectInit (0x80054948)"),
    (0, 0x7F0, "the shop's Buy and Sell plates: animations 0, 1",
     "ShopOpen -> ShopObjectInit"),
    (0, 0x6360, "the field menu's cursors and list marks: animations 0xA, 8, 9, 4, 5",
     "MenuRecordsInit (0x8006AD38)"),
    (0, 0x6350, "two still pictures of the field menu: animation 0xE's first step",
     "MenuRecordsInit"),
    (0, 0x6360, "the message's arrow: animation 5", "MessageRecordsInit (0x8005A580)"),
    (0, 0x780, "the show places' sparkle: animations 6, 7 (BtlShow30Run, BtlShow31Run)",
     "BtlShowPlacesPlay (0x8007F2D8), MenuUseShowPlacesPlay (0x8007EFC0)"),
    (0, 0x790, "the show places' sparkle: animations 6, 7 (BtlShow32Run, BtlShow33Run)",
     "BtlShowPlacesPlay, MenuUseShowPlacesPlay"),
    (1, 0x2370, "the map's kind-7 objects (sprite data entry 0)",
     "MapObjectsDataLoad (0x80065418), MapObjectInit (0x800656CC), "
     "MapRecordInit (0x80065940)"),
    (2, 0x730, "the battle menu's target mark: record 0, animation 6", "BtlMenuInit"),
    (2, 0x700, "a hit's impact: animation 0", "BtlAmountShowStart (0x80088EA8)"),
    (2, 0x710, "a strong hit's impact: animation 1", "BtlAmountShowStart"),
    (2, 0x720, "amount kind 6 (the barrier): animation 5", "BtlAmountShowStart"),
    (2, 0x7C0, "amount kind 8 (attack up, ATC): animation 7", "BtlAmountShowStart"),
    (2, 0x7B0, "amount kind 9 (defence up, DEF): animation 8", "BtlAmountShowStart"),
    (2, 0x7F0, "BtlShow3ARun's travelling record: animation 2",
     "BtlShowRecordTravelRun (0x800859A8)"),
    (2, 0x790, "BtlShow3BRun's and BtlShow3CRun's: animations 3, 4",
     "BtlShowRecordTravelRun"),
)

#: The amount digits: 8 x 8 pictures at u = 8 * i on the sheet's line 0,
#: page 10 (BtlAmountRecordsInit), drawn with 0x4300 | (style & 0xF0)
#: (BtlAmountRecordStart (0x8004AB40)): (style, sub-palette, what).
DIGITS = (
    (0xE0, 14, "a hit"),
    (0xB0, 11, "weak"),
    (0xC4, 12, "resisted"),
    (0xD0, 13, "a heal"),
    (0xC0, 12, "attack up"),
    (0xB4, 11, "defence up"),
)


def sub_palette_of(word: int) -> int:
    """sprite_draw's GetClut x: the sub-palette (word & 0xFF) >> 4 of the
    row 504 + ((word >> 8) & 3)."""
    return (word & 0xFF) >> 4


def row_of(word: int) -> int:
    """sprite_draw's GetClut y: 0x1F8 | ((word >> 8) & 3)."""
    return 0x1F8 | ((word >> 8) & 3)


@dataclass(frozen=True)
class Stfield:
    """Resource 2 as sprite_reset leaves it."""
    head: tuple                     # the eight 16-bit places
    palette: tuple                  # 256 colour words, colour 16k made 0
    banks: tuple                    # three unpacked sprite data, pages patched
    image: bytes                    # the unpacked 4-bit image, whole lines

    @property
    def lines(self) -> int:
        return len(self.image) // LINE_BYTES


def patch_pages(block: bytes, page: int = PAGE) -> bytes:
    """sprite_reset's patch: from head word 4 on, (word 5 - word 4) / 3
    texel records of 12 bytes get `page` at +2."""
    if len(block) < 12:
        raise ValueError("sprite data shorter than its head")
    first, end = struct.unpack_from("<2H", block, 2 * TEXEL_RECORDS)
    count = ((end - first) & 0xFFFFFFFF) // 3
    out = bytearray(block)
    q = first * 4
    for _ in range(count):
        if q + 4 > len(out):
            raise ValueError(f"texel record at {q:#x} past the {len(out):#x}-byte data")
        struct.pack_into("<H", out, q + 2, page)
        q += TEXEL_RECORD_BYTES
    return bytes(out)


def parse(res2: bytes) -> Stfield:
    """Open resource 2 as sprite_reset does (the module docstring)."""
    if len(res2) < 2 * HEAD_WORDS:
        raise ValueError("resource 2 shorter than its head")
    head = struct.unpack_from(f"<{HEAD_WORDS}H", res2, 0)

    def place(word: int) -> int:
        at = head[word] * 4
        if not 0 < at < len(res2):
            raise ValueError(f"word {word}: place {at:#x} outside the resource")
        return at

    at = place(PALETTE_WORD)
    if at + 0x200 > len(res2):
        raise ValueError("the palette runs past the resource")
    palette = list(struct.unpack_from("<256H", res2, at))
    for i in range(16):
        palette[i * 16] = 0
    banks = tuple(patch_pages(inflate16(res2[place(w):])) for w in BANK_WORDS)
    image = inflate16(res2[place(IMAGE_WORD):])
    image = image[:len(image) // LINE_BYTES * LINE_BYTES]
    return Stfield(head, tuple(palette), banks, image)


def sheet_image(st: Stfield, sub: int):
    """The image as an RGBA PIL image under sub-palette `sub` of the
    palette (system_dat.colours: only the word 0 is not drawn). Texels are
    4 bits, the low nibble first."""
    from PIL import Image

    from decoders.plugins.SLUS_006_28.formats.system_dat import colours

    texels = bytearray(len(st.image) * 2)
    texels[0::2] = bytes(b & 0xF for b in st.image)
    texels[1::2] = bytes(b >> 4 for b in st.image)
    pic = Image.frombytes("P", (SHEET_WIDTH, st.lines), bytes(texels))
    pal = colours(st.palette[16 * sub:16 * (sub + 1)]) + [(0, 0, 0, 0)] * 240
    pic.putpalette(b"".join(bytes(c) for c in pal), rawmode="RGBA")
    return pic.convert("RGBA")


def bank_sub_palettes(bank: int) -> list[int]:
    """The sub-palettes `USES` draws bank `bank` with, in first-use order."""
    return list(dict.fromkeys(sub_palette_of(w) for b, w, _what, _where in USES
                              if b == bank))

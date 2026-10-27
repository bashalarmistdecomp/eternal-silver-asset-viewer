"""Battle graphics bundles: the encounter's graphics SET and the PARTY set.

Both are LUNADATA resources loaded at battle entry, and every offset below is
read off the code that loads them (docs/spec/code/subsystems/battle.md
§"Battle graphics"). The actor blocks inside both use the anim/step/pose/
frame/descriptor layout `sprite_pages` already decodes, so composing a pose
is `sprite_pages.compose_pose` — this module only opens the containers.

SET BUNDLE — `BtlDataLoad(set) (0x80018694)` loads resource `g_BtlDataResources[set] (0x800A7E18)`
(`records.encounters.set_resource`):

    +0x00  4 x {u16 size_words, u16 offset_words}   enemy TYPE blocks.
           BtlEnemyLoad (0x8002B3AC) inflates the first n — n = the set's type-list
           length (records.encounters.type_list) — with inflate_buffer (0x80021D6C)
           (inflate16) into a size*4 byte allocation each.
    +0x10  u16 word offset of CLUT A -> LoadClut(buf + off*4, 0, 500)
    +0x12  u16 word offset of CLUT B -> LoadClut(buf + off*4, 0, 505)
    +0x14  5 x {u16 code, u16 offset_words}: texture pages, stop at code 0.
           Page i is inflated and LoadImage'd to g_SpritePageCorners[i] (0x800A7F88) — VRAM
           (320,0) (448,0) (576,0) (704,0) (832,0) — as 0x80 halfwords
           (256 8bpp pixels) x (code >> 8) * 4 lines.
    g_BtlPage4ImageRows (0x800B8900) = (page 4 code >> 8) * 4 — lines of slot 4 the set takes,
           which the party loader (BtlPartyImageLoad, 0x800187D8) then keeps clear of.

  Who uses what: the ARENA is page 0 (256 x 240) at screen (0,0) plus page
  1's left 80 columns at (256,0), CLUT A, drawn every frame by BtlFrameDraw (0x80018564)
  as two SPRTs behind everything (OT 0x300). Enemy actors draw with
  actor +0x0E = 0x2100, i.e. CLUT row 504 | 1 = 505 = CLUT B
  (`sprite_pages.clut_id`); their descriptors name page slots directly.

PARTY BUNDLE — resource 0x197, `BtlPartyDataLoad (0x80018A78)` then `BtlPartyLoad (0x8002B114)`:

    +0x00  u16 hdr. The party CLUT is at byte (hdr & 0xFFFC); the u16 at
           (hdr & 0xFFFE) is zeroed first (palette entry 0 = transparent),
           then LoadClut(..., 0, 504).
    +0x02  per character id 1.. : {u16 block_words, u16 block_bytes,
           u16 page_words, u16 page_code}. BtlPartyLoad inflates the block
           at buf + block_words*4 into a block_bytes allocation;
           BtlPartyImageLoad inflates the page at buf + page_words*4 and
           LoadImage's it 256 px x (page_code >> 8) lines into the first
           free 8-line run of VRAM column (832,0) / (320,256) / (448,256)
           — then PATCHES the block's descriptors to match (page slot =
           4 + column, v += 8 * run start). The descriptors stored on disc
           are page-relative (slot 0, v from the page's top), which is
           what this module returns, so each character composes against
           its own page alone.

  Party actors draw with actor +0x0E = 0x2000 -> CLUT row 504.

The character ids are g_BtlSlotIds[slot] (0x800E48E0); which id is which hero is not in
the code (the persistent party record holds them). The `battle` savestate
locates characters 1, 6, 7 and 12 in slots 0, 1, 2 and 5
(slot 5 is BtlPartyLoad's special case: anchor (0xA0, 0x68), anim 5).
That is an oracle LOCATING an index, not a source for any byte here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from decoders.plugins.SLUS_006_28.formats.inflate16 import decompress as inflate16
from decoders.plugins.SLUS_006_28.formats.sprite_pages import (
    SpriteBlockData, parse_actor_block)

PAGE_WIDTH = 256                 # 0x80 halfwords of 8bpp pixels
CLUT_BYTES = 512                 # 256 x u16
SET_TYPE_PAIRS = 4
SET_CLUT_A = 0x10
SET_CLUT_B = 0x12
SET_PAGES = 0x14
SET_PAGE_COUNT = 5

#: VRAM CLUT rows the loaders upload to (BtlDataLoad (0x80018694), BtlPartyDataLoad (0x80018A78)).
CLUT_ROW_ARENA = 500
CLUT_ROW_ENEMY = 505
CLUT_ROW_PARTY = 504

#: BtlPartyDataLoad (0x80018A78)'s literal.
PARTY_RESOURCE = 0x197
PARTY_ENTRY = 8

#: BtlFrameDraw (0x80018564): the arena is two SPRTs — (screen x, y, u, v, w, h, page).
ARENA_SPRITES = ((0, 0, 0, 0, 256, 240, 0), (256, 0, 0, 0, 80, 240, 1))
#: The visible area those land in (GsInitGraph 320x240, clip 320x224 —
#: screen_mode_set (0x8001F0C8) / packet_draw_area_add (0x80015E24)).
SCREEN_W, SCREEN_H = 320, 224

#: What the battle code plays each anim id FOR: {id: (label, who plays it)},
#: from the census of the 92 BtlAnimationSet (0x80027208) call sites (battle.md §"Battle
#: animation ids"). The anim TABLES are per block, but the CODE picks the
#: id, so these hold for every enemy / party block. The bit tests are code;
#: the status NAMES in parentheses are inferred from what the readers do.
#: Ids absent here are played only by id- or encounter-keyed scripts (enemy
#: 6, 9-15) or come from runtime tables (the party's idle/walk/attack ids,
#: g_BtlPartyStandAnimations (0x800B8BEC) / BF4 / BB8 per weapon kind) — unnamed, not guessed.
ENEMY_ANIMS = {
    0: ("idle", "BtlEnemyLoad (0x8002B3AC), BtlActingRestAnimationSet (0x80037890)"),
    1: ("move", "BtlWalkPathFollow (0x8002CA78)"),
    2: ("attack", "BtlAttackAnimationRun (0x800315A8)"),
    3: ("rest: status & 0x04 (paralysis)", "BtlSlotStatusAnimationSet (0x8003801C)"),
    4: ("rest: status & 0x08 (sleep)", "BtlSlotStatusAnimationSet (0x8003801C)"),
    5: ("rest: status & 0x30 (stone)", "BtlSlotStatusAnimationSet (0x8003801C)"),
    7: ("special, queued", "BtlSlotActionAnimationSet (0x80037E64)"),
    8: ("special, effect 95/97", "BtlShow97Run (0x8003A3BC), BtlShow99Run (0x8003A6FC)"),
    0x10: ("rest: status & 0x80 (silence)", "BtlSlotStatusAnimationSet (0x8003801C)"),
    0x11: ("rest: status & 0x40 (confusion)", "BtlSlotStatusAnimationSet (0x8003801C)"),
}
PARTY_ANIMS = {
    0x0F: ("victory", "BtlWinMessageDisp (0x8004BB68)"),
    0x11: ("evade", "BtlAttackMissShow (0x80031378), BtlPartyHitAnimationSet (0x80030E78)"),
    0x12: ("hit", "BtlAttackHitShow (0x800314B8), BtlPartyHitAnimationSet (0x80030E78)"),
    0x13: ("defend", "BtlActingRestAnimationSet (0x80037890)"),
    0x14: ("rest: status & 0x01 (poison)", "BtlSlotStatusAnimationSet (0x8003801C)"),
    0x15: ("rest: status & 0x04 (paralysis)", "BtlSlotStatusAnimationSet (0x8003801C)"),
    0x16: ("rest: status & 0x08 (sleep)", "BtlSlotStatusAnimationSet (0x8003801C)"),
    0x17: ("rest: status & 0x10 (stone, setting in)", "BtlSlotStatusAnimationSet (0x8003801C)"),
    0x18: ("rest: status & 0x20 (stone, setting in)", "BtlSlotStatusAnimationSet (0x8003801C)"),
    0x19: ("rest: status == 0x30 (stone)", "BtlSlotStatusAnimationSet (0x8003801C)"),
    0x1A: ("rest: status & 0x40 (confusion)", "BtlSlotStatusAnimationSet (0x8003801C)"),
    0x1B: ("rest: status & 0x80 (silence)", "BtlSlotStatusAnimationSet (0x8003801C)"),
    0x1C: ("KO", "BtlFallRun (0x800385B4)"),
    0x1D: ("confused, no action", "BtlActionKindRun (0x8002E12C)"),
    0x1E: ("magic queued", "BtlSlotSpellAnimationGet (0x80037F84)"),
    0x1F: ("magic queued", "BtlSlotSpellAnimationGet (0x80037F84)"),
}
#: Slot 5 — the companion — is BtlPartyLoad (0x8002B114)'s special case and keeps its
#: own ids: anim 5 at setup, 0-3 from the random idle machine (BtlSlot5RoamStep
#: (0x80038EE8), gated by g_BtlSlot5Roaming (0x800B8B26)), 7 to revive a KO'd member
#: (BtlSlot5ReviveTry, 0x80027B6C). They apply only to the block actually in slot 5.
COMPANION_ANIMS = {
    0: ("companion: random idle", "BtlSlot5RoamStep (0x80038EE8)"),
    1: ("companion: random idle", "BtlSlot5RoamStep (0x80038EE8)"),
    2: ("companion: random idle", "BtlSlot5RoamStep (0x80038EE8)"),
    3: ("companion: random idle", "BtlSlot5RoamStep (0x80038EE8)"),
    5: ("companion: setup", "BtlPartyLoad (0x8002B114)"),
    7: ("companion: revive", "BtlSlot5ReviveTry (0x80027B6C)"),
}


@dataclass(frozen=True)
class BattlePage:
    """One 8bpp texture page, 256 pixels wide."""
    index: int
    lines: int
    pixels: bytes

    @property
    def width(self) -> int:
        return PAGE_WIDTH


@dataclass
class SetBundle:
    """A decoded graphics-set resource."""
    type_blocks: list[bytes]
    clut_a: bytes
    clut_b: bytes
    pages: list[BattlePage]
    reserved_lines: int                 # g_BtlPage4ImageRows (0x800B8900)
    header: tuple[int, ...] = ()

    def actor(self, slot: int) -> SpriteBlockData | None:
        return parse_actor_block(self.type_blocks[slot])


@dataclass(frozen=True)
class PartyEntry:
    """One character's battle graphics inside the party bundle."""
    char_id: int
    block: bytes
    page: BattlePage

    def actor(self) -> SpriteBlockData | None:
        return parse_actor_block(self.block)


@dataclass
class PartyBundle:
    clut: bytes
    members: dict[int, PartyEntry] = field(default_factory=dict)


def _inflate_exact(buf: bytes, off: int, size: int, what: str) -> bytes:
    if not 0 <= off < len(buf):
        raise ValueError(f"{what}: offset {off:#x} outside the {len(buf):#x}-byte resource")
    out = inflate16(buf[off:])
    if len(out) < size:
        raise ValueError(f"{what}: inflated {len(out)} bytes, the loader expects {size}")
    return out[:size]


def parse_set_bundle(buf: bytes, n_types: int) -> SetBundle:
    """Open a graphics-set resource as BtlDataLoad (0x80018694) + BtlEnemyLoad (0x8002B3AC) do.

    `n_types` is how many type blocks the engine inflates: the length of the
    set's type list, which lives in the EXE (records.encounters.type_list),
    not in this resource — the unused header pairs are not guaranteed to be
    zero."""
    if len(buf) < SET_PAGES + 4 * SET_PAGE_COUNT:
        raise ValueError("graphics-set resource shorter than its header")
    if not 0 <= n_types <= SET_TYPE_PAIRS:
        raise ValueError(f"a set has at most {SET_TYPE_PAIRS} types, got {n_types}")
    hdr = struct.unpack_from("<20H", buf, 0)
    blocks = []
    for t in range(n_types):
        size_w, off_w = hdr[2 * t], hdr[2 * t + 1]
        blocks.append(_inflate_exact(buf, off_w * 4, size_w * 4, f"type {t}"))
    ca, cb = hdr[SET_CLUT_A // 2] * 4, hdr[SET_CLUT_B // 2] * 4
    pages = []
    for i in range(SET_PAGE_COUNT):
        code, off_w = hdr[SET_PAGES // 2 + 2 * i], hdr[SET_PAGES // 2 + 2 * i + 1]
        if code == 0:
            break
        lines = (code >> 8) * 4
        pages.append(BattlePage(index=i, lines=lines,
                                pixels=_inflate_exact(buf, off_w * 4, PAGE_WIDTH * lines,
                                                      f"page {i}")))
    reserved = (hdr[(SET_PAGES + 16) // 2] >> 8) * 4
    return SetBundle(type_blocks=blocks,
                     clut_a=bytes(buf[ca:ca + CLUT_BYTES]),
                     clut_b=bytes(buf[cb:cb + CLUT_BYTES]),
                     pages=pages, reserved_lines=reserved, header=hdr)


def party_clut(buf: bytes) -> bytes:
    """BtlPartyDataLoad (0x80018A78)'s palette: entry (hdr&0xFFFE) zeroed, 512 bytes at hdr&0xFFFC."""
    hdr = struct.unpack_from("<H", buf, 0)[0]
    out = bytearray(buf)
    z = hdr & 0xFFFE
    out[z:z + 2] = b"\0\0"
    base = hdr & 0xFFFC
    return bytes(out[base:base + CLUT_BYTES])


def party_entry_count(buf: bytes) -> int:
    """How many character entries sit before the palette.

    The code never bounds the id (it is a byte from g_BtlSlotIds (0x800E48E0)); the table
    simply runs up to the CLUT, so the count is a LAYOUT reading."""
    hdr = struct.unpack_from("<H", buf, 0)[0]
    return max(0, ((hdr & 0xFFFC) - 2) // PARTY_ENTRY)


def parse_party_entry(buf: bytes, char_id: int) -> PartyEntry:
    """One character's block + page, as BtlPartyLoad (0x8002B114) / BtlPartyImageLoad (0x800187D8) load them."""
    if char_id < 1:
        raise ValueError("character ids are 1-based; 0 is an empty slot")
    blk_w, blk_bytes, page_w, page_code = struct.unpack_from(
        "<4H", buf, 2 + (char_id - 1) * PARTY_ENTRY)
    lines = page_code >> 8
    block = _inflate_exact(buf, blk_w * 4, blk_bytes, f"char {char_id} block")
    page = BattlePage(index=0, lines=lines,
                      pixels=_inflate_exact(buf, page_w * 4, PAGE_WIDTH * lines,
                                            f"char {char_id} page"))
    return PartyEntry(char_id=char_id, block=block, page=page)


def parse_party_bundle(buf: bytes) -> PartyBundle:
    members = {}
    for cid in range(1, party_entry_count(buf) + 1):
        members[cid] = parse_party_entry(buf, cid)
    return PartyBundle(clut=party_clut(buf), members=members)


#: BtlPartyLoad (0x8002B114) stands slots 0..4 on their place cells and
#: slot 5 at (0xA0, 0x68) with anim 5.
PARTY_PLACED_SLOTS = 5
PLACE_CELL = 8
SLOT5_X, SLOT5_Y, SLOT5_ANIM = 0xA0, 0x68, 5
#: Every party record faces 0x2020 (bit 13: mirrored); a slot 0..4 whose x
#: cell is below 0x10 faces 0x20.
FACE_UNMIRRORED_BELOW = 0x10
#: MapBtlRun (0x8007AE58) copies a slot's place only for an id below 0x1F.
PLACE_ID_LIMIT = 0x1F


@dataclass(frozen=True)
class PartyPlace:
    """One party record as BtlPartyLoad (0x8002B114) puts it."""
    slot: int
    char_id: int
    x: int                          # record +0x06, the anchor x in pixels
    y: int                          # record +0x0A (and the depth, +0x08)
    mirrored: bool                  # record +0x0C bit 13
    cells: tuple[int, int] | None   # the place cells it stands on; None for slot 5


def party_places(slot_ids, places: dict[int, tuple[int, int]],
                 x_shift: int = 0) -> list[PartyPlace]:
    """Where the party stands as a battle opens.

    `slot_ids` is g_BtlSlotIds (0x800E48E0) slots 0..5; `places` maps a
    character id to (place_x, place_y), the first two bytes of its
    ChrPlacePresetRecord (chr.h).

    MapBtlRun (0x8007AE58), for slots 0..4 up to the first empty one and ids
    below 0x1F: g_BtlPartyPlaceXCells (0x800B8E88)[slot] = place_x - x_shift
    (a byte) and g_BtlPartyPlaceYCells (0x800B8E90)[slot] = place_y.
    BtlPartyLoad (0x8002B114), for each slot 0..5 with an id: facing 0x2020;
    slots 0..4 at x = x cell * 8, y = y cell * 8, facing 0x20 when the x cell
    is below 0x10; slot 5 at (0xA0, 0x68). A slot whose cells MapBtlRun did
    not copy (or whose id `places` lacks) keeps an earlier battle's cells and
    is left out here.
    """
    cells = {}
    for slot in range(PARTY_PLACED_SLOTS):
        cid = slot_ids[slot]
        if cid == 0:
            break
        if cid < PLACE_ID_LIMIT and cid in places:
            px, py = places[cid]
            cells[slot] = ((px - x_shift) & 0xFF, py & 0xFF)
    out = []
    for slot, cid in enumerate(slot_ids[:PARTY_PLACED_SLOTS + 1]):
        if cid == 0:
            continue
        if slot == PARTY_PLACED_SLOTS:
            out.append(PartyPlace(slot, cid, SLOT5_X, SLOT5_Y, True, None))
        elif slot in cells:
            cx, cy = cells[slot]
            out.append(PartyPlace(slot, cid, cx * PLACE_CELL, cy * PLACE_CELL,
                                  cx >= FACE_UNMIRRORED_BELOW, (cx, cy)))
    return out


def render_page(page: BattlePage, clut: bytes):
    """-> RGBA PIL image of a page under one CLUT.

    Colours and transparency are `parse_ps1_palette`'s (0x0000 transparent);
    the indexed pixels go through PIL's palette mode rather than a per-pixel
    loop, which is the same mapping ~100x faster."""
    from PIL import Image
    from decoders.psx.formats.palette import parse_ps1_palette

    colors = parse_ps1_palette(clut)
    colors += [(0, 0, 0, 0)] * (256 - len(colors))
    img = Image.frombytes("P", (PAGE_WIDTH, page.lines), page.pixels)
    img.putpalette(b"".join(bytes(c) for c in colors), rawmode="RGBA")
    return img.convert("RGBA")


def compose_arena(bundle: SetBundle):
    """-> the 320x224 arena exactly as BtlFrameDraw (0x80018564) draws it (neutral
    brightness 0x80, no wave), from pages 0 and 1 under CLUT A."""
    from PIL import Image

    img = Image.new("RGBA", (SCREEN_W, SCREEN_H), (0, 0, 0, 255))
    rendered = {p.index: render_page(p, bundle.clut_a) for p in bundle.pages[:2]}
    for x, y, u, v, w, h, page in ARENA_SPRITES:
        src = rendered.get(page)
        if src is None:
            continue
        crop = src.crop((u, v, u + w, min(v + h, src.height)))
        img.paste(crop, (x, y), crop)
    return img

"""A field map drawn whole with what stands on it, by the field frame's
draw rules (docs/spec/code/subsystems/rendering.md §"The field's draw
rule"; docs/spec/sprites.md §"The sprite list and `sprite_draw`").

THE ORDER -- the ordering table is drawn from entry 0x3FF down, and at
one entry the packet queued first lies on top:

    0x3C0..   the second layer in its mode 0 (behind the tiles)
    0x300..   the tiles (bg_first_draw (0x80014058))
    0x200..   the sprites of class 0x2000 and 0x4000: sprite_draw
              (0x8001A528) gives the key 0xFF - (ground y - scroll y +
              0x20), held to 0..0xFF, so lower on the map is in front;
              sprite list entries 0x46..0x6D (the twins) take 0xFF, behind
              every body. sprite_list_draw (0x8001A798) queues entries
              0x46..0x6D, then 0..0x45 (the party 0..5, the map objects
              from 0x10), so of two sprites at one entry the earlier lies
              on top.

A whole map has no one scroll, so `body_entry` takes the key unheld
(0x2DF - ground y): any two sprites one screen can show are ordered as the
game orders them.

THE ROOFS -- a tile whose word has bit 13 is drawn a second time, through
palette rows 510 / 511 (`world_map.overlay_clut_words`), at the entry
g_BgCoverGrid holds for its screen cell. That grid starts each frame at
0x1000 (no copy) and every piece of a sprite of class 0x2000 lowers the
cells its rectangle reaches, x >> 4 to (x + w) >> 4 and the same in y,
both ends counted (bg_cover_box_set (0x80013EF0)), to its own entry less
one. So the copy lies just in front of the frontmost such sprite over the
cell, and only there; a sprite of class 0x4000 raises none and lies over
it when it is in front. The copy is queued after the sprites.

THE SECOND LAYER -- drawn here only in mode 0 (area record +0xB bit 0x40:
behind the tiles) with scroll 1 (+0xB & 3: the camera's own, one for one,
MapSecondViewGoalGet (0x80069130)), where a map pixel (x, y) shows layer
pixel (x mod 512, y mod 1024). Mode 0 also sets g_BgMode = 1, which makes
the tile layer semi-transparent (MapEffectSet (0x80068AC0),
layer_col_apply (0x8001E10C)): a tile texel whose colour has bit 15 is
drawn half and half over what lies behind it.

A SPRITE'S COLOURS -- a draw word with 0x400, or an attribute word with
0x8000, is semi-transparent: half and half (the sprite pages' texture
page words are GetTPage(.., 0, ..) in sprite_init (0x80018BFC)). The
attribute's 0x8000 also picks colour table entry 2 of g_SpriteCols, 0: the
sprite is drawn black, so it darkens what lies behind it by half
(MapRecordInit's mode 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageOps

from decoders.plugins.SLUS_006_28.formats import world_map as wm

BODY_ENTRY_TOP = 0x2DF          # 0x200 + 0xFF - 0x20: sprite_draw's entry at ground y 0
TWIN_ENTRY = 1 << 20            # behind every body, wherever it stands
COVER_NONE = 1 << 24
CLASS_UNDER = 0x2000            # raises the roofs' copies
LAYER2_SCROLL_CAMERA = 1        # MapSecondViewGoalGet: scroll 1 = the camera
EFFECT_LAYER2_BEHIND = 0x40     # MapEffectSet: mode 0 and g_BgMode = 1
LAYER2_W = wm.LAYER2_COLS * wm.LAYER2_CELL_PX
LAYER2_H = wm.LAYER2_ROWS * wm.LAYER2_CELL_PX
PLANE = wm.TILES * wm.TILE_PX


def body_entry(depth: int) -> int:
    """sprite_draw's ordering-table entry for a body standing at ground y
    `depth`, the key unheld (module docstring)."""
    return BODY_ENTRY_TOP - depth


@dataclass
class Sprite:
    """One sprite list entry as sprite_draw draws it."""
    image: Image.Image          # the pose, RGBA, as compose_pose draws it
    left: int                   # the image's top-left on the map
    top: int
    depth: int                  # ground y
    pieces: list = field(default_factory=list)  # (x, y, w, h) on the map, each piece
    twin: bool = False          # entries 0x46..0x6D
    queue: int = 0              # its place in sprite_list_draw's walk
    klass: int = CLASS_UNDER    # draw word & 0x6000
    semi: bool = False
    black: bool = False

    @property
    def entry(self) -> int:
        return TWIN_ENTRY if self.twin else body_entry(self.depth)


def queue_of(slot: int) -> int:
    """sprite_list_draw's walk: entries 0x46..0x6D, then 0..0x45, then the rest."""
    if 0x46 <= slot <= 0x6D:
        return slot - 0x46
    if slot < 0x46:
        return 0x28 + slot
    return 0x100 + slot


def cover_cells(sprites: list[Sprite]) -> dict[tuple[int, int], int]:
    """g_BgCoverGrid as the sprite pass leaves it, by 16-px map cell: the
    entry a roof copy takes there (absent: no copy)."""
    out: dict[tuple[int, int], int] = {}
    for s in sprites:
        if s.klass != CLASS_UNDER:
            continue
        depth = s.entry - 1
        for x, y, w, h in s.pieces:
            for cy in range(y >> 4, ((y + h) >> 4) + 1):
                for cx in range(x >> 4, ((x + w) >> 4) + 1):
                    if depth < out.get((cx, cy), COVER_NONE):
                        out[(cx, cy)] = depth
    return out


@dataclass
class Ground:
    """A map's tiles ready to draw: its background (the second layer and
    the tile layer), and what its roof copies are drawn from."""
    image: Image.Image          # 2048 x 2048 RGBA
    plane: list[list[int]]      # tile words
    sheets: dict                # (page, row) -> the page through overlay row `row`
    stp_sheets: dict            # the same, only the texels drawn half and half
    layer2: bool                # the second layer is drawn
    notes: list[str]
    pages: dict = field(default_factory=dict)   # page -> 8-bit texels, as loaded
    rows: list = field(default_factory=list)    # the tile CLUT rows' colour words
    under: Image.Image | None = None            # the second layer alone, when drawn
    #: ... as row-508 colour indexes, 512 x 1024 (world_map.second_layer_indexes)
    layer2_indexes: bytes | None = None


def _blend_over(base: Image.Image, top: Image.Image, at: tuple[int, int]) -> None:
    """Half and half of `top`'s drawn texels over `base`, in place."""
    box = (at[0], at[1], at[0] + top.width, at[1] + top.height)
    under = base.crop(box)
    mixed = Image.blend(under, top, 0.5)
    base.paste(mixed, at, top)


def _word_rows(rows: list[list[int]], keep_stp: bool | None) -> list[list[wm.Color]]:
    """Colour words as RGBA; `keep_stp` True keeps only the words with bit
    15, False only those without, None all."""
    out = []
    for row in rows:
        if keep_stp is not None:
            row = [w if bool(w & wm.STP) == keep_stp else wm.TRANSPARENT for w in row]
        out.append(wm.words_rgba(row))
    return out


def _sheets(pages: dict[int, bytes], rows: list[list[wm.Color]]) -> dict:
    from decoders.psx.formats.renderer import render_indexed_layer
    return {(p, ci): render_indexed_layer(data, rows[ci], *wm.PAGE_SIZE[p])
            for p, data in pages.items() if p in wm.PAGE_SIZE for ci in range(len(rows))}


def tile_image(value: int, sheets: dict) -> Image.Image | None:
    """One 16 x 16 tile as bg_first_draw draws it, from rendered pages."""
    t = wm.decode_tile(value)
    sheet = sheets.get((t.page, t.clut))
    if sheet is None or t.u + wm.TILE_PX > sheet.width or t.v + wm.TILE_PX > sheet.height:
        return None
    tile = sheet.crop((t.u, t.v, t.u + wm.TILE_PX, t.v + wm.TILE_PX))
    if t.hflip:
        tile = ImageOps.mirror(tile)
    if t.vflip:
        tile = ImageOps.flip(tile)
    return tile


def _plane_image(plane: list[list[int]], sheets: dict) -> Image.Image:
    img = Image.new("RGBA", (PLANE, PLANE), (0, 0, 0, 0))
    for y, row in enumerate(plane):
        for x, value in enumerate(row):
            tile = tile_image(value, sheets)
            if tile is not None:
                img.paste(tile, (x * wm.TILE_PX, y * wm.TILE_PX), tile)
    return img


def ground(map_raw: bytes, effect: int, party_kind: int) -> Ground | None:
    """The map's tiles as the field draws them under its sprites (module
    docstring); None for a resource with no layout or no tile palette."""
    lay = wm.layout(map_raw)
    pal = wm.palettes(map_raw).get(wm.TILE_CLUT_PALETTE)
    pages = wm.pages(map_raw)
    if lay is None or pal is None or not pages:
        return None
    plane = wm.tile_plane(lay)
    rows = wm.tile_clut_words(pal)
    notes: list[str] = []
    behind = bool(effect & EFFECT_LAYER2_BEHIND)
    cells = wm.second_layer(map_raw)
    layer2 = False
    under = None
    indexes = None
    img = Image.new("RGBA", (PLANE, PLANE), (0, 0, 0, 0))
    if not wm.layer2_is_empty(cells):
        scroll = effect & 3
        if behind and scroll == LAYER2_SCROLL_CAMERA and len(rows) > 1 and wm.LAYER2_PAGE in pages:
            indexes = wm.second_layer_indexes(cells, pages[wm.LAYER2_PAGE])
            plane2 = wm.layer2_image(indexes, wm.layer2_clut_words(pal))
            img = Image.new("RGBA", (PLANE, PLANE), (0, 0, 0, 255))
            for y in range(0, PLANE, LAYER2_H):
                for x in range(0, PLANE, LAYER2_W):
                    img.paste(plane2, (x, y), plane2)
            layer2 = True
            under = img.copy()
        elif behind:
            notes.append(f"the second layer (mode 0) is not drawn: its scroll is {scroll}, "
                         f"which moves it apart from the map as the camera moves; the "
                         f"tiles' bit-15 texels are drawn whole, not half over it")
        else:
            notes.append("the second layer is not drawn: its mode puts it in front of "
                         "everything (rendering.md §\"The second layer\")")
    blend = behind and layer2
    if blend:
        # g_BgMode 1: bit-15 texels are half and half over the layer behind.
        opaque = _plane_image(plane, _sheets(pages, _word_rows(rows, False)))
        stp = _plane_image(plane, _sheets(pages, _word_rows(rows, True)))
        img.paste(opaque, (0, 0), opaque)
        _blend_over(img, stp, (0, 0))
    else:
        tiles = _plane_image(plane, _sheets(pages, _word_rows(rows, None)))
        img.paste(tiles, (0, 0), tiles)
    cover = wm.overlay_clut_words(pal, wm.overlay_keep_from(party_kind))
    return Ground(image=img, plane=plane,
                  sheets=_sheets(pages, _word_rows(cover, False if blend else None)),
                  stp_sheets=_sheets(pages, _word_rows(cover, True)) if blend else {},
                  layer2=layer2, notes=notes, pages=pages, rows=rows, under=under,
                  layer2_indexes=indexes)


def roof_layers(g: Ground) -> tuple[Image.Image, Image.Image | None]:
    """Every roof cell's copy drawn where it lies, through the cover rows:
    what `compose` draws at a covered roof cell, for a player that sorts
    the copies itself. The second picture holds the texels drawn half and
    half (None when the tiles draw none)."""
    roofs = roof_cells(g.plane)
    opaque = Image.new("RGBA", (PLANE, PLANE), (0, 0, 0, 0))
    stp = Image.new("RGBA", (PLANE, PLANE), (0, 0, 0, 0)) if g.stp_sheets else None
    for cx, cy in roofs:
        value = g.plane[cy][cx]
        at = (cx * wm.TILE_PX, cy * wm.TILE_PX)
        tile = tile_image(value, g.sheets)
        if tile is not None:
            opaque.paste(tile, at, tile)
        if stp is not None:
            t2 = tile_image(value, g.stp_sheets)
            if t2 is not None:
                stp.paste(t2, at, t2)
    return opaque, stp


@dataclass
class TilePatch:
    """The cells one tile animation record changes and how each of its
    frames draws them. Frame k's picture holds patch j at
    ((j % PATCH_COLUMNS) * 16, (j // PATCH_COLUMNS) * 16); a cell is
    (x, y, j), its top-left on the map in pixels. Before the record's
    first step the pages hold their own texels: the ground as drawn."""
    delay: int
    frames: int
    cells: list
    pictures: list


PATCH_COLUMNS = 32


def _cell_box(cx: int, cy: int) -> tuple[int, int, int, int]:
    return (cx * wm.TILE_PX, cy * wm.TILE_PX, (cx + 1) * wm.TILE_PX, (cy + 1) * wm.TILE_PX)


def _patched_pages(g: Ground, places: dict, images: bytes, first: int) -> dict:
    """The pages `places` names with tiles first + j of `images` put in."""
    from decoders.plugins.SLUS_006_28.formats import field_motion as fmo
    side = fmo.TILE_SIDE
    out = {}
    for (page, u, v), j in places.items():
        buf = bytearray(out.get(page, g.pages[page]))
        at = (first + j) * fmo.FIELD_TILE_AT
        texels = images[at:at + fmo.FIELD_TILE_AT]
        if len(texels) == fmo.FIELD_TILE_AT:
            w = wm.PAGE_SIZE[page][0]
            for line in range(side):
                o = (v + line) * w + u
                buf[o:o + side] = texels[line * side:(line + 1) * side]
        out[page] = bytes(buf)
    return out


def tile_patches(g: Ground, anims: list, images: bytes) -> list[TilePatch]:
    """What tile_animation_load (0x80026814) sends after each step of
    tile_animation_step (0x80026690), as cells of the ground: at frame k a
    record puts tiles source + k * count + j of `images` (the map's
    type-16 command inflated, 0x100 bytes a 16 x 16 8-bit tile) on page
    tile `tile + j` (tile_image_run_load (0x800267AC),
    field_motion.tile_place), and every map cell whose tile reads one of
    those changes with it."""
    from decoders.plugins.SLUS_006_28.formats import field_motion as fmo
    blend = g.under is not None
    out = []
    for r in anims:
        places = {}
        for j in range(r.count):
            page, u, v = fmo.tile_place(r.tile + j)
            if page in g.pages and page in wm.PAGE_SIZE:
                places[(page, u, v)] = j
        keys: dict = {}
        cells = []
        first_box = {}
        for cy, row in enumerate(g.plane):
            for cx, value in enumerate(row):
                t = wm.decode_tile(value)
                if (t.page, t.u, t.v) not in places:
                    continue
                box = _cell_box(cx, cy)
                # one patch per tile word and what lies under it
                key = (value, g.under.crop(box).tobytes() if blend else None)
                j = keys.setdefault(key, len(keys))
                first_box.setdefault(j, (value, box))
                cells.append((box[0], box[1], j))
        if not cells or r.frames == 0:
            continue
        n = len(keys)
        size = (min(n, PATCH_COLUMNS) * wm.TILE_PX, -(-n // PATCH_COLUMNS) * wm.TILE_PX)
        pictures = []
        for k in range(r.frames):
            pages = _patched_pages(g, places, images, r.source + k * r.count)
            if blend:
                opaque = _sheets(pages, _word_rows(g.rows, False))
                stp = _sheets(pages, _word_rows(g.rows, True))
            else:
                opaque, stp = _sheets(pages, _word_rows(g.rows, None)), None
            pic = Image.new("RGBA", size, (0, 0, 0, 0))
            for j, (value, box) in first_box.items():
                cell = (g.under.crop(box) if blend
                        else Image.new("RGBA", (wm.TILE_PX, wm.TILE_PX), (0, 0, 0, 0)))
                tile = tile_image(value, opaque)
                if tile is not None:
                    cell.paste(tile, (0, 0), tile)
                if stp is not None:
                    t2 = tile_image(value, stp)
                    if t2 is not None and t2.getbbox():
                        _blend_over(cell, t2, (0, 0))
                pic.paste(cell, ((j % PATCH_COLUMNS) * wm.TILE_PX, (j // PATCH_COLUMNS) * wm.TILE_PX))
            pictures.append(pic)
        out.append(TilePatch(delay=r.delay, frames=r.frames, cells=cells, pictures=pictures))
    return out


def roof_cells(plane: list[list[int]]) -> set[tuple[int, int]]:
    """The cells whose tile is queued a second time (bit 13)."""
    return {(x, y) for y, row in enumerate(plane) for x, v in enumerate(row)
            if v & wm.TILE_OVERLAY}


def _paste_sprite(img: Image.Image, s: Sprite) -> None:
    at = (s.left, s.top)
    if not (s.semi or s.black):
        img.paste(s.image, at, s.image)
        return
    src = s.image
    if s.black:
        src = Image.new("RGBA", s.image.size, (0, 0, 0, 255))
        src.putalpha(s.image.getchannel("A"))
    if s.semi:
        box = (at[0], at[1], at[0] + src.width, at[1] + src.height)
        mixed = Image.blend(img.crop(box), src, 0.5)
        img.paste(mixed, at, s.image)
    else:
        img.paste(src, at, s.image)


def compose(g: Ground, sprites: list[Sprite]) -> Image.Image:
    """The map with `sprites` drawn on it, the roof copies over them."""
    img = g.image.copy()
    roofs = roof_cells(g.plane)
    cover = cover_cells(sprites)
    items: list[tuple[int, int, object]] = [(s.entry, s.queue, s) for s in sprites]
    last = max((s.queue for s in sprites), default=0) + 1
    for (cx, cy), depth in cover.items():
        if (cx, cy) in roofs and 0 <= cy < len(g.plane) and 0 <= cx < len(g.plane[cy]):
            items.append((depth, last, (cx, cy)))
    items.sort(key=lambda t: (t[0], t[1]), reverse=True)
    for _entry, _queue, it in items:
        if isinstance(it, Sprite):
            _paste_sprite(img, it)
            continue
        cx, cy = it
        value = g.plane[cy][cx]
        at = (cx * wm.TILE_PX, cy * wm.TILE_PX)
        tile = tile_image(value, g.sheets)
        if tile is not None:
            img.paste(tile, at, tile)
        if g.stp_sheets:
            stp = tile_image(value, g.stp_sheets)
            if stp is not None and stp.getbbox():
                _blend_over(img, stp, at)
    return img


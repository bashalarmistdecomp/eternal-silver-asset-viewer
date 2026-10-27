"""The game's pictures: the TIMs of command 2 in LUNADATA's command lists.

A picture is a type-2 command (formats.command_list): resource_tim_add
(0x800208A0) unpacks a sub-number 0 TIM and sends it to VRAM at once
(tim_image_load (0x8002073C)), and keeps any other as picture 0, 1, ... in
list order (g_ResourceTims (0x800E0C10)) for resource_tim_unpack
(0x80020918) / resource_tim_load (0x80020950). Walking command 2 of every
resource the code runs as a command list (formats.resources) finds the
game's 41 TIMs on the disc: resource 1 (the glyph atlas), resource 3 (five
cards and the three title pages), two in each bromide (586 to 598) and six
in resource 599. docs/spec/sprites.md §"Pictures: the TIMs".

What each one is comes from the code that shows it:

    1      sent at once     the glyph atlas, drawn through CLUT 0x7ECE (row 507,
                            colours 224-239) by ankprint_cell_draw (0x80025C20)
    3      sent at once     the title's pages, by VRAM x: 384 the logo, 768
                            PRESS START, 896 the menu (StartScreenDraw (0x80043848))
    3      picture 0        the card StartPictureLoadShow (0x800435A4) shows before
                            the title (StartPictureShow (0x8001607C))
    3      pictures 1-4     cards no code shows: only picture 0 is ever loaded
    586+k  pictures 0, 1    bromide k: PictureShow(k) (0x80024A7C) loads both, one
                            under the other, and pans down them (PictureDraw
                            (0x80024950)); picture 1 has no CLUT and is drawn
                            through 0x7F40 (row 509), picture 0's
                            (PictureBandDraw (0x8002484C))
    599    pictures 0-3     the disc-change screens: overlay_disc_wait (0x80023184)
                            asks cd_change_wait (0x80024D2C) for picture 0 when
                            the movie wanted is below 0x24 (disc 1), 1 from it
                            (disc 2), and 2 or 3 once a disc has failed its check
    599    pictures 4, 5    GameRun (0x800559F4) after the game's end: picture 4
                            while _SECOND.XA's nine channels play, then picture 5
                            for ever; screen_picture_put (0x80024C04) shows the
                            top 320 x 224 of each

SLPS_013.97 differs in two places: its StartPictureLoadShow (SLPS_013.97
0x80046994) shows resource 3's pictures 0 to 4 in turn before the title, a
press ending the run, and its StartScreenDraw (SLPS_013.97 0x80046BC8)
draws the title from other places, not read here, so its pages are not
named. Its resource 599 has pictures 0-3 only.

The colours a picture is drawn with are those in VRAM when it is drawn:
its own CLUT for a kept picture with one; for a sub-number 0 TIM, its CLUT
row as the whole list leaves it (the logo page's row 504 is the PRESS
START page's, which loads after it); for a TIM with no CLUT, the row the
code names, as the list and the earlier pictures left it. A CLUT word of 0
is not drawn (world_map.words_rgba).

A bromide is shown as one picture (`bromide_image`, `bromide_show`):
resource_tim_load puts its two pictures in video memory at their own
places, x 320, the second at row 240 over the first's last rows, and
PictureDraw draws the 224 rows from a row y of that column across the
screen's 320 columns, three sprites a band (PictureBandDraw): rows y to
0xFF of texture page 5, then the first y - 0x20 rows of page 0x15. Each
frame PictureStep (0x800249B0) moves y round a circle from 0: down to 254
and back up over PictureShow's 0x2D0 frames, the screen fading in from
black over the first 0x20 and out over 0x20 more (screen_fade_step
(0x8001C0F0)).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cache

from PIL import Image

from decoders.psx.formats.tim import MODE_4BIT, MODE_8BIT, TimImage, parse_tim

from . import command_list as cl
from . import inflate16
from ..records import programs
from .resources import BROMIDE_BASE, DISC_CHANGE
from .world_map import words_rgba

GLYPH_ATLAS_RESOURCE = 1
TITLE_RESOURCE = 3
#: StartScreenDraw (0x80043848): the title's 8-bit pages, by VRAM x.
TITLE_PAGES = {384: "the logo", 768: "PRESS START", 896: "the menu"}
GLYPH_CLUT = 0x7ECE         # ankprint_cell_draw (0x80025C20): row 507, x 224
BROMIDE_CLUT = 0x7F40       # PictureBandDraw (0x8002484C): row 509, x 0
SCREEN_PICTURE_H = 224      # screen_picture_put (0x80024C04): 320 x 224


@dataclass(frozen=True)
class Picture:
    """One type-2 command of a resource, and the TIM in it."""
    resource: int
    offset: int                 # where the command starts in the resource
    sub: int                    # its sub-number
    picture: int | None         # the kept picture's number; None = sent at once
    width: int
    height: int
    mode: int
    vram_x: int
    vram_y: int
    has_clut: bool

    @property
    def sent_at_once(self) -> bool:
        return self.picture is None


@dataclass(frozen=True)
class Role:
    """What the code does with a picture."""
    what: str                   # "bromide 3, top", "the glyph atlas"
    shown_by: str               # the code that loads or shows it
    draw_clut: int | None = None    # the CLUT word the code draws it through, when not its own


def _tim(c: cl.Command) -> TimImage | None:
    return parse_tim(inflate16.decompress(c.payload))


def pictures(buf: bytes, resource: int) -> list[Picture]:
    """Every type-2 command of a resource's list, its TIM unpacked."""
    out = []
    for c, number in cl.pictures(cl.commands(buf)):
        t = _tim(c)
        if t is None:
            continue
        out.append(Picture(resource, c.offset, c.arg, number, t.width, t.height,
                           t.mode, t.vram_x, t.vram_y, bool(t.clut_words)))
    return out


#: SLPS_013.97's StartPictureLoadShow: pictures 0 to 4 (`n < 5`).
JP_CARDS = 5


def role(p: Picture, program: str = programs.US) -> Role:
    """What `program`'s code does with picture `p` (module docstring)."""
    r, n = p.resource, p.picture
    jp = program == programs.JP
    if r == GLYPH_ATLAS_RESOURCE and n is None:
        return Role("the glyph atlas",
                    "main (0x80013D2C) -> resource_load_run(1) (0x800202CC), sent at once",
                    GLYPH_CLUT)
    if r == TITLE_RESOURCE and jp:
        if n is None:
            return Role("a title page",
                        "StartResourceLoad (0x8004409C), sent at once; SLPS_013.97's "
                        "StartScreenDraw (SLPS_013.97 0x80046BC8) draws it, not read here")
        if n < JP_CARDS:
            return Role(f"card {n + 1} of {JP_CARDS} shown before the title",
                        "SLPS_013.97's StartPictureLoadShow (SLPS_013.97 0x80046994) "
                        "-> StartPictureShow (0x8001607C; SLPS_013.97 0x80017344), "
                        "pictures 0 to 4 in turn until a press")
    if r == TITLE_RESOURCE:
        if n is None:
            page = TITLE_PAGES.get(p.vram_x)
            return Role(f"title page: {page}" if page else "a title page",
                        "StartResourceLoad (0x8004409C), sent at once; drawn by "
                        "StartScreenDraw (0x80043848)")
        if n == 0:
            return Role("card shown before the title",
                        "StartPictureLoadShow (0x800435A4) -> StartPictureShow (0x8001607C)")
        return Role("card no code shows",
                    "kept by StartResourceLoad (0x8004409C); StartPictureLoadShow "
                    "(0x800435A4) loads picture 0 only")
    k = r - BROMIDE_BASE
    if 0 <= k < 13 and n in (0, 1):
        return Role(f"bromide {k}, " + ("top" if n == 0 else "bottom"),
                    f"PictureShow({k}) (0x80024A7C) -> resource_tim_load({n}) (0x80020950); "
                    "PictureDraw (0x80024950) pans down the two",
                    None if p.has_clut else BROMIDE_CLUT)
    if r == DISC_CHANGE and n is not None:
        if n < 4:
            disc = 1 + (n & 1)
            again = ", once a disc has failed its check" if n & 2 else ""
            return Role(f"disc-change screen: a movie on disc {disc}{again}",
                        "overlay_disc_wait (0x80023184) -> cd_change_wait (0x80024D2C) "
                        "-> screen_picture_put (0x80024C04)")
        if n == 4:
            return Role("after the game's end, while _SECOND.XA plays",
                        "GameRun (0x800559F4): resource_tim_unpack(4) (0x80020918) "
                        "-> screen_picture_put (0x80024C04)")
        if n == 5:
            return Role("after the game's end, for ever",
                        "GameRun (0x800559F4): resource_tim_unpack(5) (0x80020918) "
                        "-> screen_picture_put (0x80024C04)")
    return Role("a picture", "resource_tim_add (0x800208A0)")


# ---- colours ----------------------------------------------------------------

def _palette_row(c: cl.Command) -> list[int]:
    """resource_palette_row_load (0x80020ACC)'s row: palette_bit15_set (0x800207E8)
    makes colour 0 the word 0 and sets bit 15 on the others; for row 7,
    palette_glyph_zero_set (0x8002087C) makes colours 0xB0, 0xC0, 0xD0, 0xE0
    0 too."""
    raw = inflate16.decompress(c.payload)[:512]
    words = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw) - 1, 2)]
    words = [0 if i == 0 else w | 0x8000 for i, w in enumerate(words)]
    if c.arg == 7:
        for i in (0xB0, 0xC0, 0xD0, 0xE0):
            if i < len(words):
                words[i] = 0
    return words


class _Cluts:
    """The CLUT rows of VRAM, as uploads leave them."""

    def __init__(self):
        self.rows: dict[int, dict[int, int]] = {}

    def put(self, x: int, y: int, words: list[int]):
        row = self.rows.setdefault(y, {})
        for i, w in enumerate(words):
            row[x + i] = w

    def put_tim(self, t: TimImage):
        for j, words in enumerate(t.clut_words):
            self.put(t.clut_x, t.clut_y + j, words)

    def get(self, x: int, y: int, n: int) -> list[int] | None:
        row = self.rows.get(y, {})
        words = [row.get(x + i) for i in range(n)]
        return None if any(w is None for w in words) else words

    def copy(self) -> "_Cluts":
        other = _Cluts()
        other.rows = {y: dict(r) for y, r in self.rows.items()}
        return other


def image(buf: bytes, p: Picture) -> tuple[Image.Image, str]:
    """Picture `p` of resource bytes `buf`, drawn through the colours the
    code draws it with, and a line saying which those are."""
    cmds = cl.commands(buf)
    after_list = _Cluts()
    tims: dict[int, TimImage] = {}
    for c in cmds:
        if c.type == cl.TIM and c.arg == 0:
            t = _tim(c)
            if t is not None:
                after_list.put_tim(t)
                tims[c.offset] = t
        elif c.type == cl.PALETTE_ROW:
            after_list.put(0, cl.PALETTE_ROW_BASE + c.arg, _palette_row(c))
    kept = [(c, n) for c, n in cl.pictures(cmds) if n is not None]
    for c, _n in kept:
        tims.setdefault(c.offset, _tim(c))
    t = tims[p.offset]
    colours = 16 if t.mode == MODE_4BIT else 256
    r = role(p)

    if r.draw_clut is not None:
        vram = after_list.copy()
        for c, n in kept:
            if p.picture is not None and n < p.picture:
                vram.put_tim(tims[c.offset])
        x, y = (r.draw_clut & 0x3F) * 16, r.draw_clut >> 6
        words = vram.get(x, y, colours)
        note = f"CLUT {r.draw_clut:#06x} (row {y}, colours {x} to {x + colours - 1}), as the code draws it"
    elif p.sent_at_once and t.clut_words:
        words = after_list.get(t.clut_x, t.clut_y, colours)
        own = t.clut_words[0][:colours]
        note = (f"CLUT row {t.clut_y}" + ("" if words == own else
                ", as a later TIM of the list leaves it (its own copy differs)"))
    else:
        words = t.clut_words[0][:colours] if t.clut_words else None
        note = f"its own CLUT (row {t.clut_y})" if words else "no CLUT: index values as grey"

    if words is None:
        ramp = [(v * 255 // (colours - 1),) * 3 + (255,) for v in range(colours)]
        return replace(t, cluts=[ramp]).to_image(0), "no CLUT the code draws it with: index values as grey"
    return replace(t, cluts=[words_rgba(words)]).to_image(0), note


# ---- a bromide's show ---------------------------------------------------------

#: PictureShow (0x80024A7C): PictureStep once a frame, 0x2D0 frames after
#: screen_fade_start(0x20, 2) and 0x20 after screen_fade_start(0x20, 3);
#: then the screen is off (SetDispMask(0)) until the voice has ended, 0x80
#: frames at most.
BROMIDE_SHOWN = 0x2D0
BROMIDE_FADE = 0x20
BROMIDE_VOICE_WAIT = 0x80
#: PictureDraw (0x80024950) draws 224 rows of 320 columns from texture
#: page 5, 8-bit, at video memory x 5 * 64, and under them page 0x15 (y 256).
SCREEN_W = 320
SCREEN_H = 224
BROMIDE_PAGE_X = 5 * 64
#: PictureStep (0x800249B0): the pan's pair (a, b) starts at (0, 0x8000),
#: each adds the other over 120 a frame (b takes it off); the row is
#: 0x7C - (b >> 8), held between 0 and 0xFF.
PAN_START = 0x8000
PAN_TURN = 120
PAN_MIDDLE = 0x7C
PAN_LAST = 0xFF
#: screen_fade_start's modes: bit 0 grows the fade, bit 1 takes the colour
#: away (the screen goes toward black) rather than adding it.
FADE_IN = 2
FADE_OUT = 3


@dataclass(frozen=True)
class ShowFrame:
    """One frame of a bromide on the screen."""
    row: int        # the row of the picture the screen begins at (g_PicturePanRow)
    dark: int       # what the fade takes off each colour, 0 to 0xFF (0xFF: black)


def _c_div(a: int, b: int) -> int:
    """The C's signed division, toward 0."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def fade_strength(mode: int, left: int, length: int) -> int:
    """screen_fade_step (0x8001C0F0)'s colour with `left` of the fade's
    `length` frames left: 0xFF * k / length, k = left when bit 0 of the
    mode is clear (the fade dies away) and length - left - 1 when it is set
    (it grows; its last frame is the whole 0xFF), held between 0 and 0xFF.
    None left draws nothing: 0."""
    if left <= 0:
        return 0
    grows = bool(mode & 1)
    if grows and left == 1:
        return 0xFF
    k = length - left - 1 if grows else left
    return min(max(_c_div(0xFF * k, max(length, 1)), 0), 0xFF)


@cache
def bromide_show() -> tuple[ShowFrame, ...]:
    """The frames a bromide is on the screen, as PictureShow (0x80024A7C)
    runs them. Each turns the pan, PictureStep (0x800249B0): a = a + b / 120
    and b = b - (the old a) / 120 in the C's division, from (0, 0x8000);
    the row is 0x7C - (b >> 8), held between 0 and 0xFF. The fade comes in
    from black over the first BROMIDE_FADE of the BROMIDE_SHOWN frames and
    goes out over BROMIDE_FADE more (screen_fade_step (0x8001C0F0) with
    modes 2 and 3, which take its colour off the screen's)."""
    a, b = 0, PAN_START
    out = []
    for f in range(BROMIDE_SHOWN + BROMIDE_FADE):
        a, b = a + _c_div(b, PAN_TURN), b - _c_div(a, PAN_TURN)
        row = min(max(PAN_MIDDLE - (b >> 8), 0), PAN_LAST)
        if f < BROMIDE_FADE:
            dark = fade_strength(FADE_IN, BROMIDE_FADE - f, BROMIDE_FADE)
        elif f >= BROMIDE_SHOWN:
            dark = fade_strength(FADE_OUT, BROMIDE_FADE - (f - BROMIDE_SHOWN), BROMIDE_FADE)
        else:
            dark = 0
        out.append(ShowFrame(row, dark))
    return tuple(out)


#: Texels a 16-bit word of video memory holds, by TIM mode.
_TEXELS = {MODE_4BIT: 4, MODE_8BIT: 2}


def bromide_image(buf: bytes, resource: int) -> tuple[Image.Image, list[tuple[Picture, str]]]:
    """Bromide resource `buf` as the screen shows it: the column of video
    memory PictureDraw (0x80024950) reads, SCREEN_W texels from x
    BROMIDE_PAGE_X, holding kept pictures 0 and 1 each at its own place,
    the second over the first where they meet (PictureShow loads 0, then 1,
    with resource_tim_load (0x80020950)), from row 0 to the last row the pan
    puts on the screen. With it, each picture and the line `image` says its
    colours with."""
    shown = sorted((p for p in pictures(buf, resource) if p.picture in (0, 1)),
                   key=lambda p: p.picture)
    rows = max(f.row for f in bromide_show()) + SCREEN_H
    out = Image.new("RGBA", (SCREEN_W, rows))
    found = []
    for p in shown:
        img, colours = image(buf, p)
        out.paste(img, ((p.vram_x - BROMIDE_PAGE_X) * _TEXELS.get(p.mode, 1), p.vram_y))
        found.append((p, colours))
    return out, found

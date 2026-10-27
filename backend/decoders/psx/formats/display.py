"""The PS1 GPU's display modes, and the shape of a pixel in each.

The GPU scans each TV line at a fixed rate and lasts one pixel a whole
number of ticks of its dot clock; the horizontal mode (256, 320, 368, 512 or
640 wide) picks that number, so the mode fixes how wide a pixel is on the
TV. libgpu's PutDispEnv picks the mode from the display environment's width
(disp.w): up to 280 is the 256 mode, up to 352 the 320, up to 400 the 368,
up to 560 the 512, anything wider the 640; a height over 256 lines (NTSC)
is the interlaced 480-line mode.

Pixel shapes here are NTSC's (every Lunar disc is NTSC). In the 256 mode a
pixel lasts 10 ticks, which against the rate for square pixels on a 4:3
picture makes it 8:7 wide; the other modes last 8, 7, 5 and 4 ticks, so
their pixels are narrower in that proportion. An interlaced line is half as
tall, so its pixel is twice as wide for its height.

Nothing here reads bytes: a program's display environment says which mode
it uses, and this says what that mode looks like.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

#: Ticks of the dot clock one pixel lasts, by the mode's width.
TICKS_PER_PIXEL = {256: 10, 320: 8, 368: 7, 512: 5, 640: 4}

#: The 256 mode's pixel on an NTSC 4:3 picture, progressive lines.
_PIXEL_256 = Fraction(8, 7)

#: Lines above which PutDispEnv sets the interlaced mode (NTSC).
PROGRESSIVE_LINES = 256


@dataclass(frozen=True)
class DisplayMode:
    #: The mode's width: 256, 320, 368, 512 or 640.
    width: int
    interlaced: bool

    @property
    def pixel_aspect(self) -> Fraction:
        """A pixel's width over its height on the TV."""
        aspect = _PIXEL_256 * Fraction(TICKS_PER_PIXEL[self.width], 10)
        return aspect * 2 if self.interlaced else aspect


def mode_for(disp_w: int, disp_h: int) -> DisplayMode:
    """The mode PutDispEnv sets for a display `disp_w` x `disp_h` pixels."""
    if disp_w <= 280:
        width = 256
    elif disp_w <= 352:
        width = 320
    elif disp_w <= 400:
        width = 368
    elif disp_w <= 560:
        width = 512
    else:
        width = 640
    return DisplayMode(width, disp_h > PROGRESSIVE_LINES)

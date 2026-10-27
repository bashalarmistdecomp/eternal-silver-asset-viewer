"""How SSSC shows a movie: the display mode its player puts each frame on.

movie_frames_play (0x80196414, the MENU overlay) shows each decoded frame
on a 24-bit display built from the frame's rectangle: movie_frame_next
(0x80196954) sets the rectangle's width to the frame's width * 3 / 2 (24-bit
pixels counted in 16-bit VRAM words) and its height to the frame's height,
and the loop sets disp.w = width * 2 / 3 back, the frame's own width, before
PutDispEnv (0x8008C434). So the display mode follows the frame: SSSC's
224 x 192 movies play in the 256-wide mode, whose pixels are 8:7, and fill a
4:3 picture (224 * 8 / 7 = 256 by 192). The loop's screen.w = 0xE0 narrows
the range of the line shown, not the pixel.
"""

from __future__ import annotations

from decoders.psx.formats.display import DisplayMode, mode_for

#: The routine whose display this follows, for the viewer's notes.
PLAYER = "movie_frames_play (0x80196414)"


def movie_mode(width: int, height: int) -> DisplayMode:
    """The display mode a `width` x `height` movie frame plays in."""
    return mode_for(width, height)

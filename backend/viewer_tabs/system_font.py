"""An installed Japanese font, to draw what the console's kanji ROM draws.

SLPS_013.97 draws every glyph code outside its own tables from the BIOS's
kanji ROM through Krom2RawAdd (formats.message_window). The ROM is part of
the console, not the disc, and is not read here. Such a code is drawn
instead from its Shift-JIS character (formats.jp_characters) with a
Japanese font installed on this machine, in the cell the game reads: a
16 x 16 one-bit pattern of which font_pattern_outline (0x80026B98) takes
the first 15 rows. The glyph is drawn 15 pixels to the em, a full-width
kanji centred in the top-left 15 x 15, and not smoothed (FreeType's
one-bit rendering, which takes a font's own small bitmaps where it has
them). A character the font has no glyph for gets no pattern.

The font is looked for once, at first use:

    fontconfig   where fc-list is installed: the faces it lists for
                 :lang=ja, a face named for Japanese first (Noto Sans CJK
                 JP before KR in the same file, which fc-match :lang=ja may
                 give), a sans face before a serif one, then the face
                 fc-match :lang=ja gives, then a regular weight
    Windows      MS Gothic, Yu Gothic, Meiryo, MS Mincho in the system's
                 Fonts folder
    macOS        Hiragino Kaku Gothic, Osaka, Hiragino Mincho

None when none is found; the caller keeps its stand-in box.
"""

from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from decoders._env import system_env

#: The em in pixels, and the cell: 16 x 16, the outline reads 15 rows.
EM = 15
CELL = 16
PATTERN_BYTES = 32
#: A full-width kanji, to place the em by: its ink is centred in EM x EM.
SQUARE = "国"
#: A code point no font has, to know a font's missing-glyph box by.
NO_GLYPH = "\U0010FFFD"

_JAPANESE = re.compile(r"\bJP\b|Japan|IPA|Takao|Gothic|Mincho|Meiryo|Hiragino|"
                       r"Osaka|Sazanami|Kochi|\bVL\b|Ume|ゴシック|明朝")
_SERIF = re.compile(r"Serif|Mincho|明朝")
_REGULAR = {"regular", "book", "normal", "medium", "w3", "w4"}


def _windows_paths() -> list[tuple[str, int]]:
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    return [(str(fonts / name), 0) for name in
            ("msgothic.ttc", "YuGothR.ttc", "YuGothM.ttc", "meiryo.ttc", "msmincho.ttc")]


_MAC_PATHS = [("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 0),
              ("/System/Library/Fonts/ヒラギノ角ゴ ProN W3.otf", 0),
              ("/Library/Fonts/Osaka.ttf", 0),
              ("/System/Library/Fonts/ヒラギノ明朝 ProN.ttc", 0)]


@dataclass(frozen=True)
class Face:
    """A face fontconfig lists: its file, its index there, its names."""
    path: str
    index: int
    family: str
    style: str


def rank(faces: list[Face], matched: tuple[str, int] | None) -> list[Face]:
    """`faces` in the order they are tried (module docstring); `matched` is
    fc-match's (file, index)."""
    def key(f: Face):
        style = f.style.split(",")[0].strip().lower()
        return (not _JAPANESE.search(f.family), bool(_SERIF.search(f.family)),
                matched is None or f.path != matched[0],
                (f.path, f.index) != matched, style not in _REGULAR, f.path, f.index)
    return sorted(faces, key=key)


def _run(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace",
                              timeout=10, check=True, env=system_env()).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _fontconfig() -> list[tuple[str, int]]:
    if not shutil.which("fc-list"):
        return []
    faces = []
    for line in _run("fc-list", "-f", "%{file}\t%{index}\t%{family}\t%{style}\n",
                     ":lang=ja").splitlines():
        parts = line.split("\t")
        if len(parts) == 4 and parts[1].isdigit():
            faces.append(Face(parts[0], int(parts[1]), parts[2], parts[3]))
    matched = None
    got = _run("fc-match", "-f", "%{file}\t%{index}", ":lang=ja").split("\t")
    if len(got) == 2 and got[1].isdigit():
        matched = (got[0], int(got[1]))
    return [(f.path, f.index) for f in rank(faces, matched)]


class SystemFont:
    """One installed face, drawing characters into the game's cell."""

    def __init__(self, path: str, index: int = 0):
        self.path = path
        self.index = index
        self._font = ImageFont.truetype(path, EM, index=index)
        family, style = self._font.getname()
        self.name = f"{family} {style}".strip() if style and style != "Regular" else family
        self.file = Path(path).name
        left, top, right, bottom = self._font.getbbox(SQUARE, anchor="ls")
        self._origin = (round((EM - (right - left)) / 2 - left),
                        round((EM - (bottom - top)) / 2 - top))
        self._missing = self._draw(NO_GLYPH)

    def _draw(self, ch: str) -> bytes:
        im = Image.new("1", (CELL, CELL), 0)
        draw = ImageDraw.Draw(im)
        draw.fontmode = "1"
        draw.text(self._origin, ch, font=self._font, fill=1, anchor="ls")
        return im.tobytes()        # one bit a pixel, the leftmost the high bit

    def pattern(self, ch: str) -> bytes | None:
        """`ch` as a 16 x 16 pattern, two bytes a row, high byte first: as
        font_pattern_get gives a glyph. None for a character the face has
        no glyph for."""
        if len(ch) != 1:
            return None
        got = self._draw(ch)
        return None if got == self._missing and ch != NO_GLYPH else got

    def __str__(self) -> str:
        return f"{self.name} ({self.file})"


def _load(candidates) -> SystemFont | None:
    for path, index in candidates:
        if not Path(path).is_file():
            continue
        try:
            font = SystemFont(path, index)
        except OSError:
            continue
        if font.pattern(SQUARE):
            return font
    return None


@functools.lru_cache(maxsize=1)
def find() -> SystemFont | None:
    """The Japanese font this machine has (module docstring), or None."""
    return _load(_fontconfig() + _windows_paths() + _MAC_PATHS)


def kanji_lines(font: SystemFont | None, glyphs: int | None = None, boxed: int = 0,
                tinted: bool = False) -> list[str]:
    """A selection's info on its kanji: `glyphs` of the kanji ROM's (a
    count, or None for "the kanji"), `boxed` of them drawn as a box."""
    what = "The kanji are" if glyphs is None else f"{glyphs} glyphs are"
    text = (f"{what} the console's: it draws them from its BIOS's kanji ROM "
            "(Krom2RawAdd), which is not read. ")
    if font is None:
        text += "No Japanese font was found on this machine, so each is a box."
    else:
        text += f"They are drawn here with {font}, a font of this machine, not the game's."
        if tinted:
            text += " The second layer tints them."
        if boxed:
            text += f" {boxed} have no glyph in it: a box."
    return textwrap.wrap(text, 70)

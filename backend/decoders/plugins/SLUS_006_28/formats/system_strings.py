"""The game's string table — every name, label and system message the menus
and the battle UI print — LUNADATA resource 1, and the text code that reads it.

Every step is a function that was read (docs/spec/text.md §"The string
table"):

    main (0x80013D2C) — first thing at boot:
        resource_load_run(1) (0x800202CC)                    # FIL_0230(1, g_ResourceReadBuffer (0x800B8828) = 0x80156000)
                                            # then resource_command_run (0x800202FC) walks the buffer
    main_buffer_init (0x80013E04) — g_ResourceCommand01Buffer (0x800B8868) = alloc_top(0x15828), the block
    resource_command_run (io) — a command list: u32 word (type = low byte), u32 size,
        `size` bytes of payload; the next entry is 8 + (size & ~3) bytes on;
        a zero word ends it. Type 1 -> resource_command01_set (0x80020480):
            inflate_buffer(payload, g_ResourceCommand01Buffer) (0x80021D6C)      # inflate16
    func_80026AB0 — g_FontStringTable (0x800B8B70) = g_ResourceCommand01Buffer
    font_string_put (0x80026F78) — string `id`:
            off = ((u16 *)g_FontStringTable)[id]; 0 = none
            font_string_walk (0x8005A884)(g_FontStringTable + off, font_string_code_put (0x80026F30), font_string_control_run (0x80026F54))

font_string_walk (matching C) — `walk` below, the one transcription of it:

    until the byte 0xFF:
      0x0E: text until a 0x00 —
            b < 0x5C   the character b + 0x1F, except the controls of
                       jtbl_80012A84, which emit codes: '%' 0xFF00,
                       '*' 0xFF00 0xFF01, '@' 0xFF02, '^' 0xFF01,
                       '\\' 0xFF03, '$' 0xFF00 0xFF03 and the end of the
                       message
            b >= 0x5C  a dictionary word (font_string_word_get (0x80059F4C), `Words`:
                       word n of g_FontStringWords (0x800B386C)): n = b - 0x5C,
                       or the next byte + 0xA1 after 0xFD, + 0x19E after
                       0xFE — its bytes are ASCII with jtbl_80012994's
                       controls (the same set; '\\' there also ends it)
      else: a 16-bit code — g_FontStringCodes[b] (0x800B34C0) for b < 0xD6, else (b << 8 |
            next byte). Above 0xEFFF it is a control; below, a font glyph
            (0xD640..0xEFFF less 0x5500).

What a control DOES is the control handler's business, and there are two
(docs/spec/text.md §"The controls — what each path does"): the label path's
font_control_run (0x8002710C) and a message window's MessageControlRun (0x8005AF20) (the
battle popup's BtlMessageControlRun (0x8004C5E4) is its twin). The markup names each
control by what the message window does with it:

    0xF0nn-0xF6nn  {STR:0x...}   splice string (code & 0xFFF) in
    0xF8nn  {WAIT:nn frames}     wait nn frames (the label path: nothing)
    0xF9nn  {MOVE:nnpx}          font_pen_move(nn) (0x800270CC): the pen moves nn PIXELS
    0xFAnn  {FACE_LEFT:0xnn}     face nn in the left portrait place
    0xFBnn  {FACE_RIGHT:0xnn}    face nn in the right place (the label path:
                                 nothing for either); 0xFA00 / 0xFB00 take
                                 the shown faces down: {FACES_OFF}
    0xFCnn  {STYLE:nn}           font_col_set((nn & 3) << 2) (0x800270BC): the glyph style
                                 (the label path sets 0xF0 for every nn)
    0xFF00  {PROMPT}             wait for the button, or a timeout
    0xFF01  {PAGE}               a new page: the three rows are cleared
    0xFF02  a line break         the next row (the third starts a new page)
    0xFF03  {CLOSE}              close the window

So '%' is the prompt, '@' the line break, '^' a new page and '*' prompt-
then-new-page; '$' is prompt-then-close and ends the walk.

The plain text keeps what a reader needs: the row and page breaks as line
breaks, and a pen move as ONE space between two pieces of text (none at
either end of a line). The font is proportional — font_code_put (0x80026D64) gives each
glyph its own width, a blank one 5 pixels — so a move of nn pixels is no
number of characters; the markup keeps the exact move.

The id space (`CATEGORIES`) is fixed by the callers: BtlLevelUpGainsDisp (0x8004C324) prints a
character as `id | 0xF000`, BtlMenuFirstOpen (0x80044780) an enemy as `id + 0x80`,
BtlActionStringDisp (0x8004987C) an item as `id | 0x100`, a spell as `row + 0x1B6` and an
enemy special as `class | 0x300`, BtlWinItemMessageDisp (0x8004BF8C) a drop as `item | 0xF100`,
MenuCardListDisp (0x800734F0) a location as `id + 0x400`, the theater (MenuUseMovieListDisp, 0x80077838) a
movie as `entry + 0x500` and the jukebox (MenuUseMusicListDisp, 0x800774EC) a BGM as
`n + 0x546`. A menu's icon or command number n (an item id, a spell + 0xB6,
a command byte) names string n + 0x100 and its description n + 0x200:
MenuCursorTextDisp (0x8006C8F0) writes both, as BtlMenuItemDisp (0x80046BB4) and BtlMenuSpellDisp (0x80046258)
do in battle. Only the bromide titles are placed by the table's own layout,
and say so. `GameStrings` is how every consumer names things: one place
applies these rules.

This module reads LUNADATA bytes; the dictionary of words is the EXE's and
is passed in (`Words`, the one reader of it), as party_init takes its item
table.

SLPS_013.97, the Japanese program, has no dictionary and no runs: its
font_string_put (SLPS_013.97 0x8002A788) and its message command
(ScriptCommandMessageDisp, SLPS_013.97 0x8005DC7C) read every byte as the
walk's "else" branch reads it, 0x0E included. `walk` reads that way when
it is given no dictionary (`words_of` answers None for that program). Its
g_FontStringCodes lies elsewhere (`exe_char_table` asks records.programs).
Its codes are kana and kanji, not ASCII: a reading for a person takes
them through `characters_of` (formats.jp_characters).

ONE WALK, THREE READINGS. `walk` hands the codes to two callbacks, as the
C does. `decode` is the string for a person: text and markup, splices
expanded from the string table (passed in for a message that lives
elsewhere, as the event scripts' do). `codes` is the 16-bit codes as they
come, nothing expanded or named — for a caller that runs a control handler
of its own: the field's message window shows a string by id (a splice
0xF6nn in a message, the item notice's `item | 0x100`) by feeding that
string's codes to MessageStringCodePut (0x8005A834) / MessageStringControlRun
(0x8005A864). `string_codes` is every string that way, with the bytes read;
event_script.text_end is the walk's stop position alone.
"""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass
from typing import Callable, NamedTuple

from . import command_list, inflate16
from ..records import programs

#: main (0x80013D2C): resource_load_run(1) (0x800202CC).
RESOURCE = 1
#: main_buffer_init (0x80013E04): g_ResourceCommand01Buffer (0x800B8868) = alloc_top(0x15828) — the block's capacity.
BLOCK_CAPACITY = 0x15828
#: resource_command_run (0x800202FC)'s case 1 -> resource_command01_set (0x80020480) (inflate16 into g_ResourceCommand01Buffer (0x800B8868)).
CMD_STRINGS = command_list.STRINGS
#: g_FontStringWords (0x800B386C): font_string_word_get (0x80059F4C)'s dictionary base.
WORDS_ADDR = 0x800B386C
#: g_FontStringWords (0x800B386C) holds 512 words, ending at 0x800B45F0 (the register;
#: docs/spec/text.md §"The dictionary"). A run can number up to 0x29D; past
#: word 511 font_string_word_get would read on into the next table.
WORD_COUNT = 512
#: g_FontStringCodes (0x800B34C0): font_string_walk (0x8005A884) indexes it with a byte below 0xD6,
#: so it has 0xD6 words.
CHAR_TABLE_ADDR = 0x800B34C0
CHAR_TABLE_ENTRIES = 0xD6
EXE_BASE = 0x80011000

#: font_string_walk (0x8005A884)'s six control characters (a run's b + 0x1F, or a word's
#: byte) and the codes each hands the control handler; '$' also ends the
#: walk, and so does a backslash inside a word.
RUN_CONTROLS = {"%": (0xFF00,), "*": (0xFF00, 0xFF01), "@": (0xFF02,),
                "^": (0xFF01,), "\\": (0xFF03,), "$": (0xFF00, 0xFF03)}
#: MessageControlRun (0x8005AF20)'s 0xFFnn controls: (text, markup). A row break and a new
#: page read as a line break; the prompt and the close print nothing.
_FF_CONTROLS = {0xFF00: ("", "{PROMPT}"), 0xFF01: ("\n", "{PAGE}"),
                0xFF02: ("\n", "\n"), 0xFF03: ("", "{CLOSE}")}
#: Stands for a pen move in the text until the string is whole (`spaced`).
MOVE = "\ue000"
_MOVES = re.compile(f"[ {MOVE}]*{MOVE}[ {MOVE}]*")


def control_markup(code: int) -> str:
    """A control code (above 0xEFFF, not a splice) as the markup names it:
    what MessageControlRun (0x8005AF20) does with it (the module docstring's table). A
    code no handler acts on keeps its hex."""
    hi, nn = code & 0xFF00, code & 0xFF
    if code in _FF_CONTROLS:
        return _FF_CONTROLS[code][1]
    if hi == 0xF800:
        return f"{{WAIT:{nn} frames}}"
    if hi == 0xF900:
        return f"{{MOVE:{nn}px}}"
    if hi in (0xFA00, 0xFB00):
        # MessageFaceSet (0x8005B36C): face 0 takes every shown face down
        if nn == 0:
            return "{FACES_OFF}"
        return f"{{FACE_{'LEFT' if hi == 0xFA00 else 'RIGHT'}:{nn:#04x}}}"
    if hi == 0xFC00:
        return f"{{STYLE:{nn}}}"
    return f"{{{code:04X}}}"


def spaced(text: str) -> str:
    """The plain text's pen moves: one space between two pieces of text (a
    move and the spaces beside it count once), none at either end of a line."""
    return "\n".join(_MOVES.sub(MOVE, row).strip(MOVE).replace(MOVE, " ")
                     for row in text.split("\n"))


#: What a program's glyph codes stand for: code -> character, or None
#: (`characters_of`).
Characters = Callable[[int], "str | None"]


def char_text(code: int, characters: Characters | None = None) -> tuple[str, str]:
    """A character code (emit_char's) as (text, markup): printable ASCII as
    itself, then the character `characters` gives it (the program's,
    `characters_of`), else Shift-JIS's ideographic space 0x8140 as a space
    and any other glyph as {GLYPH:xxxx}."""
    if 0x20 <= code <= 0x7E:
        return chr(code), chr(code)
    ch = characters(code) if characters else None
    if ch is not None:
        return ch, ch
    mark = f"{{GLYPH:{code:04X}}}"
    return (" " if code == 0x8140 else mark), mark


def control_text(code: int) -> str:
    """A control code (not a splice) in the plain text: a line break for a
    row or page break, `MOVE` for a pen move (`spaced` makes it one space),
    else nothing."""
    return MOVE if (code & 0xFF00) == 0xF900 else _FF_CONTROLS.get(code, ("",))[0]


class Category(NamedTuple):
    """A range of string ids: string id = base + index. `proof` names the
    code that builds the id; None = placed by the table's layout only."""
    name: str
    first: int
    last: int
    base: int
    proof: str | None


CATEGORIES = [
    Category("character", 0x001, 0x00C, 0x000, "BtlLevelUpGainsDisp (0x8004C324): char id | 0xF000 (id 0xB as 0xF001)"),
    Category("enemy", 0x081, 0x0FF, 0x080, "BtlMenuFirstOpen (0x80044780): enemy id + 0x80"),
    Category("item", 0x101, 0x1B6, 0x100, "BtlActionStringDisp (0x8004987C) kind 4: item | 0x100; BtlWinItemMessageDisp (0x8004BF8C): drop | 0xF100"),
    Category("spell", 0x1B7, 0x1E6, 0x1B6, "BtlActionStringDisp (0x8004987C) kind 3: the spell's number + 0x1B6"),
    Category("menu", 0x1E7, 0x1FF, 0x100, "MenuCursorTextDisp (0x8006C8F0): a menu command byte + 0x100; "
             "BtlMenuFirstOpen (0x80044780): an icon number + 0x100"),
    Category("description", 0x201, 0x2FF, 0x200, "MenuCursorTextDisp (0x8006C8F0), BtlMenuItemDisp (0x80046BB4), "
             "BtlMenuSpellDisp (0x80046258): an icon or command number + 0x200, under its name (+ 0x100)"),
    Category("enemy_special", 0x301, 0x37F, 0x300, "BtlActionStringDisp (0x8004987C) kind 7: attack class | 0x300"),
    Category("location", 0x401, 0x4FF, 0x400, "MenuCardListDisp (0x800734F0): g_MapPlaceName (0x800B8CD8) + 0x400; travel menu: id + 0x400"),
    Category("movie", 0x501, 0x537, 0x500, "MenuUseMovieListDisp (0x80077838): theater entry i + 0x500 (entry i plays _B{i-1:03d}.STR)"),
    Category("bromide", 0x538, 0x544, 0x538, None),
    Category("bgm", 0x547, 0x58A, 0x546, "MenuUseMusicListDisp (0x800774EC): BGM number n + 0x546 (the jukebox)"),
    Category("system", 0x601, 0x6FF, 0x600, "direct ids, e.g. MenuChrRecordOpen (0x800704F4): 0x616-0x618"),
]
BY_CATEGORY = {c.name: c for c in CATEGORIES}

#: A name's description is the string 0x100 past it: for one icon or
#: command number n the code writes the name n + 0x100 and the description
#: n + 0x200 (MenuCursorTextDisp (0x8006C8F0), BtlMenuItemDisp (0x80046BB4), BtlMenuSpellDisp (0x80046258)).
DESCRIPTION_OFFSET = 0x100
#: The categories whose ids are such a number + 0x100.
DESCRIBED = ("item", "spell", "menu")

#: A word by number — font_string_word_get (0x80059F4C) over the EXE's
#: dictionary (`Words`).
WordLookup = Callable[[int], bytes]


def block(buf: bytes, inflate: Callable[[bytes], bytes] = inflate16.decompress) -> bytes:
    """The string block resource_command01_set (0x80020480) inflates out of resource 1."""
    cmd = command_list.effective(buf, CMD_STRINGS)
    if cmd is None:
        raise ValueError("no type-1 command: not the string resource")
    out = inflate(cmd.payload)
    if len(out) > BLOCK_CAPACITY:
        raise ValueError(f"{len(out):#x} bytes overflow main_buffer_init (0x80013E04)'s {BLOCK_CAPACITY:#x}")
    return out


def table_size(blk: bytes) -> int:
    """How many u16 offsets the table holds: slots run until the lowest
    offset any earlier slot points at — the first string's bytes."""
    end, i = len(blk), 0
    while 2 * i + 2 <= min(end, len(blk)):
        off = struct.unpack_from("<H", blk, 2 * i)[0]
        if off:
            end = min(end, off)
        i += 1
    return min(i, end // 2)


def string_offset(blk: bytes, sid: int) -> int:
    """font_string_put (0x80026F78)'s lookup: 0 = no string (or an id past the block)."""
    if 2 * sid + 2 > len(blk):
        return 0
    return struct.unpack_from("<H", blk, 2 * sid)[0]


@dataclass(frozen=True)
class DecodedString:
    text: str          # for a reader: line breaks, a space for a pen move, splices expanded
    markup: str        # every control named ({TOKENS}), splices as {STR:0x...}
    words: int         # dictionary words used


#: font_string_walk (0x8005A884)'s switch on a run's character (b + 0x1F)
#: or a word's byte: the codes it hands emit_ctl. Any other goes to
#: emit_char as it is.
RUN_CODES = {0x25: (0xFF00,), 0x40: (0xFF02,), 0x5C: (0xFF03,),
             0x24: (0xFF00, 0xFF03), 0x2A: (0xFF00, 0xFF01), 0x5E: (0xFF01,)}
#: The characters that end the walk: '$' anywhere, a backslash in a word.
RUN_ENDS = (0x24,)
WORD_ENDS = (0x24, 0x5C)

Emit = Callable[[int], None]


def walk(buf: bytes, p: int, words: WordLookup | None, char_table: Callable[[int], int],
         emit_char: Emit, emit_ctl: Emit) -> int:
    """font_string_walk (0x8005A884) over `buf` from `p`, as its C reads:
    the codes go to the two callbacks in order, and the answer is the index
    it returns — the 0xFF it stopped on, or the run byte that ended the
    message (the '$', or the last byte of the word number whose text ended
    it). The walk itself expands nothing: a splice (0xF0nn-0xF6nn) is a
    code for emit_ctl, as it is for the game's handlers.

    `words` is font_string_word_get (0x80059F4C) (`Words`), or None for
    a program with no dictionary, whose walk has no 0x0E runs (module
    docstring); `char_table` g_FontStringCodes (0x800B34C0)
    (`exe_char_table`). A stream with no end inside `buf` is refused: the
    original reads on."""
    size = len(buf)

    def past() -> ValueError:
        return ValueError("font_string_walk (0x8005A884): ran past the end of the buffer (no 0xFF)")

    while True:
        if p >= size:
            raise past()
        c = buf[p]
        if c == 0xFF:
            return p
        if c == 0x0E and words is not None:
            p += 1
            while True:
                if p >= size:
                    raise past()
                c = buf[p]
                if c == 0:
                    break
                p += 1
                if c < 0x5C:
                    code = c + 0x1F
                    ctl = RUN_CODES.get(code)
                    if ctl is None:
                        emit_char(code)
                        continue
                    for x in ctl:
                        emit_ctl(x)
                    if code in RUN_ENDS:
                        return p - 1
                    continue
                if c == 0xFD or c == 0xFE:
                    if p >= size:
                        raise past()
                    n = buf[p] + (0xA1 if c == 0xFD else 0x19E)
                    p += 1
                else:
                    n = c - 0x5C
                for f in words(n):
                    ctl = RUN_CODES.get(f)
                    if ctl is None:
                        emit_char(f)
                        continue
                    for x in ctl:
                        emit_ctl(x)
                    if f in WORD_ENDS:
                        return p - 1
        else:
            if c < 0xD6:
                code = char_table(c) & 0xFFFF
            else:
                if p + 1 >= size:
                    raise past()
                code = ((c << 8) | buf[p + 1]) & 0xFFFF
                p += 1
            if code > 0xEFFF:
                emit_ctl(code)
            else:
                emit_char(code - 0x5500 if code > 0xD63F else code)
        p += 1


def walk_end(buf: bytes, p: int, words: WordLookup | None) -> int:
    """`walk`'s answer with the codes handed to no one: the same steps over
    the same bytes, the same refusal of a stream with no end inside `buf`,
    without a call for each code (event_script.text_end steps over every
    message of a script this way)."""
    size = len(buf)

    def past() -> ValueError:
        return ValueError("font_string_walk (0x8005A884): ran past the end of the buffer (no 0xFF)")

    while True:
        if p >= size:
            raise past()
        c = buf[p]
        if c == 0xFF:
            return p
        if c == 0x0E and words is not None:
            p += 1
            while True:
                if p >= size:
                    raise past()
                c = buf[p]
                if c == 0:
                    break
                p += 1
                if c < 0x5C:
                    if c + 0x1F in RUN_ENDS:
                        return p - 1
                    continue
                if c == 0xFD or c == 0xFE:
                    if p >= size:
                        raise past()
                    n = buf[p] + (0xA1 if c == 0xFD else 0x19E)
                    p += 1
                else:
                    n = c - 0x5C
                for f in words(n):
                    if f in WORD_ENDS:
                        return p - 1
        elif c >= 0xD6:
            if p + 1 >= size:
                raise past()
            p += 1
        p += 1


def splice_id(code: int) -> int | None:
    """The string a splice control names: 0xF0nn-0xF6nn -> code & 0xFFF
    (MessageControlRun (0x8005AF20) walks g_FontStringTable + that slot's
    offset; font_control_run (0x8002710C) the same through font_string_put
    (0x80026F78)). None for any other code."""
    return code & 0xFFF if 0xF000 <= (code & 0xFF00) <= 0xF600 else None


def decode(blk: bytes, off: int, words: WordLookup | None,
           char_table: Callable[[int], int] = lambda b: 0xF000 | b,
           table: bytes | None = None,
           characters: Characters | None = None) -> DecodedString:
    """`walk` over the string at `off`, for a person. A splice
    (0xF0nn-0xF6nn) is expanded from `table`, the string table (the block
    itself when None), as both handlers do; a slot whose offset is 0 is
    shown as nothing. Every other control is read as a message window reads
    it (module docstring), so a multi-row message keeps its line breaks.
    `char_table` is g_FontStringCodes (0x800B34C0) (only used outside 0x0E
    runs); `characters` what the program's codes stand for (`char_text`)."""
    table = blk if table is None else table
    text: list[str] = []
    mark: list[str] = []
    used = 0

    def counted(n: int) -> bytes:
        nonlocal used
        used += 1
        return words(n)

    def emit_char(code: int) -> None:
        t, m = char_text(code, characters)
        text.append(t)
        mark.append(m)

    def emit_ctl(code: int, depth: int = 0) -> None:
        sid = splice_id(code)
        if sid is None:
            text.append(control_text(code))
            mark.append(control_markup(code))
            return
        mark.append(f"{{STR:{sid:#05x}}}")
        inner = string_offset(table, sid)
        if inner and depth < 4:
            keep = len(mark)
            try:
                walk(table, inner, words, char_table, emit_char,
                     lambda c: emit_ctl(c, depth + 1))
            except ValueError:
                pass                    # the spliced text as far as the table goes
            del mark[keep:]

    walk(blk, off, None if words is None else counted, char_table, emit_char, emit_ctl)
    return DecodedString(spaced("".join(text)), "".join(mark), used)


def strings(blk: bytes, words: WordLookup | None,
            char_table: Callable[[int], int] = lambda b: 0xF000 | b,
            characters: Characters | None = None) -> dict[int, DecodedString]:
    """Every id that has a string."""
    out = {}
    for sid in range(table_size(blk)):
        off = string_offset(blk, sid)
        if off:
            out[sid] = decode(blk, off, words, char_table, characters=characters)
    return out


def codes(blk: bytes, off: int, words: WordLookup | None,
          char_table: Callable[[int], int]) -> tuple[list[int], int]:
    """`walk` with no handler: the 16-bit codes it hands its two callbacks,
    in order, nothing expanded or named, and the index it returns.

    This is what a caller that feeds the codes to a handler of its own
    needs — the field's message window prints a string by id through
    MessageStringCodePut (0x8005A834) / MessageStringControlRun (0x8005A864),
    and a splice (0xF0nn..0xF6nn) hands the spliced string's codes to the
    same two. `decode` reads the same bytes for a person.

    Which callback a code went to is its value: a run's six control
    characters and a word's become 0xFF00..0xFF03 (emit_ctl), any other
    run or word byte is its own value (emit_char); outside a run a code
    above 0xEFFF goes to emit_ctl and any other to emit_char, 0xD640..0xEFFF
    less 0x5500.
    """
    out: list[int] = []
    end = walk(blk, off, words, char_table, out.append, out.append)
    return out, end


def string_codes(blk: bytes, words: WordLookup | None,
                 char_table: Callable[[int], int]) -> dict[int, tuple[bytes, list[int]]]:
    """Every id that has a string -> (the bytes font_string_walk (0x8005A884) read,
    up to and with the byte it stopped on; the codes it emitted for them)."""
    out = {}
    for sid in range(table_size(blk)):
        off = string_offset(blk, sid)
        if off:
            emitted, end = codes(blk, off, words, char_table)
            out[sid] = (bytes(blk[off:end + 1]), emitted)
    return out


def char_table_words(image: bytes, addr: int | None = None,
                     image_base: int = EXE_BASE) -> list[int]:
    """g_FontStringCodes (0x800B34C0) as its 0xD6 words: the code of a byte below 0xD6 that
    stands outside a run (font_string_walk, 0x8005A884), and the table MessageCodesConv (0x8005AC44)
    searches entries 1..7 of the other way."""
    if addr is None:
        addr = programs.address(image, "g_FontStringCodes", CHAR_TABLE_ADDR)
    table = exe_char_table(image, addr, image_base)
    if addr - image_base < 0 or len(image) < addr - image_base + 2 * CHAR_TABLE_ENTRIES:
        raise ValueError(f"image of {len(image):#x} bytes does not cover "
                         f"{addr:#x} .. +{2 * CHAR_TABLE_ENTRIES:#x}")
    return [table(b) for b in range(CHAR_TABLE_ENTRIES)]


def string_codes_json(table: dict[int, tuple[bytes, list[int]]], char_table: list[int]) -> dict:
    """The code streams as string_codes.json carries them — the exporter's
    body: g_FontStringCodes (0x800B34C0), and for every string its bytes (hex) and its codes."""
    return {
        "char_table": list(char_table),
        "strings": [{"id": sid, "bytes": raw.hex(), "codes": emitted}
                    for sid, (raw, emitted) in sorted(table.items())],
    }


def category(sid: int) -> tuple[str, int] | None:
    """(category name, index within it) for a string id."""
    for c in CATEGORIES:
        if c.first <= sid <= c.last:
            return c.name, sid - c.base
    return None


def string_id(category_name: str, index: int) -> int | None:
    """The string id the code builds for `index` in a category, or None
    when it falls outside the category's range."""
    c = BY_CATEGORY[category_name]
    sid = c.base + index
    return sid if c.first <= sid <= c.last else None


_GLYPHS_AND_SPACE = re.compile(r"\{GLYPH:[0-9A-F]{4}\}|\s")


def _placeholder(text: str) -> bool:
    """A slot holding only font-glyph codes (the blank 0x99F0 entries)."""
    return not _GLYPHS_AND_SPACE.sub("", text)


class GameStrings:
    """The string table with the categories' id rules applied — the one way
    to name a game thing. Built from a decode (`decode_block`) or from the
    exported strings.json (`from_json`); both yield the same texts."""

    def __init__(self, texts: dict[int, str], markup: dict[int, str] | None = None):
        self._texts = dict(texts)
        self._markup = dict(markup or {})
        #: id -> whether its slot is a placeholder (`text`), as asked
        self._blank: dict[int, bool] = {}

    @classmethod
    def decode_block(cls, blk: bytes, words: WordLookup | None,
                     char_table: Callable[[int], int] = lambda b: 0xF000 | b,
                     characters: Characters | None = None) -> "GameStrings":
        table = strings(blk, words, char_table, characters)
        return cls({sid: d.text for sid, d in table.items()},
                   {sid: d.markup for sid, d in table.items() if d.markup != d.text})

    @classmethod
    def from_json(cls, doc: dict) -> "GameStrings":
        rows = doc.get("strings", [])
        return cls({s["id"]: s["text"] for s in rows},
                   {s["id"]: s["markup"] for s in rows if "markup" in s})

    def __len__(self) -> int:
        return len(self._texts)

    def items(self):
        """(id, text) for every slot, blank ones included, by id."""
        return sorted(self._texts.items())

    def entries(self):
        """(id, text, markup) for every slot — markup equals text when the
        string has no controls."""
        return [(sid, t, self._markup.get(sid, t)) for sid, t in self.items()]

    def text(self, sid: int | None) -> str | None:
        """String `sid` as displayed; None for a missing or blank slot."""
        t = self._texts.get(sid) if sid is not None else None
        if t is None:
            return None
        blank = self._blank.get(sid)
        if blank is None:
            blank = self._blank[sid] = _placeholder(t)
        return None if blank else t

    def name(self, category_name: str, index: int) -> str | None:
        """The `index`-th name of a category (string id = base + index)."""
        return self.text(string_id(category_name, index))

    def description(self, category_name: str, index: int) -> str | None:
        """The description of an item, a spell or a menu label: its name's
        string + 0x100 (`DESCRIPTION_OFFSET`); None for another category."""
        sid = string_id(category_name, index) if category_name in DESCRIBED else None
        return self.text(sid + DESCRIPTION_OFFSET) if sid is not None else None

    def to_json(self) -> dict:
        """The categories and texts, as strings.json carries them (no markup)
        — what an app's labels are built from."""
        return {"categories": categories_json(),
                "strings": [{"id": sid, "text": t} for sid, t in self.items()]}


def categories_json() -> list[dict]:
    return [c._asdict() for c in CATEGORIES]


class Words:
    """g_FontStringWords (0x800B386C) as font_string_word_get (0x80059F4C)
    reads it, the one reader of the dictionary:

        p = g_FontStringWords;
        while (word_number > 0) { if (*p++ == 0) word_number--; }
        return p;

    Word n starts past n 0 bytes counted from the base, and the walk
    (font_string_walk, 0x8005A884) reads it up to the next 0 byte. A Words
    is a `WordLookup`: words(n) is word n's bytes. Each word's start is
    stepped to once and kept, so word n + 1 is counted on from word n."""

    def __init__(self, image: bytes, addr: int | None = None,
                 image_base: int = EXE_BASE):
        if addr is None:                # raises Unmapped for a program with none
            addr = programs.address(image, "g_FontStringWords", WORDS_ADDR)
        self._image = image
        self._image_base = image_base
        self._starts = [addr - image_base]
        self._words: dict[int, bytes] = {}

    def offset(self, n: int) -> int:
        """Where word n starts in the image: past n 0 bytes from the base."""
        while len(self._starts) <= n:
            self._starts.append(self._image.index(0, self._starts[-1]) + 1)
        return self._starts[n]

    def address(self, n: int) -> int:
        return self.offset(n) + self._image_base

    @property
    def key(self) -> tuple:
        """What the words are read from, as bytes: two readers with the same
        key read the same words (event_script.script_code keeps a script's
        sweep by it)."""
        got = self.__dict__.get("_key")
        if got is None:
            got = self._key = (hashlib.sha1(self._image).digest(), self._starts[0],
                               self._image_base)
        return got

    def __call__(self, n: int) -> bytes:
        if n not in self._words:
            p = self.offset(n)
            self._words[n] = bytes(self._image[p:self._image.index(0, p)])
        return self._words[n]


def words_of(image: bytes) -> Words | None:
    """The dictionary of `image`'s program, or None for a program with none
    (SLPS_013.97), whose walk then has no runs."""
    return Words(image) if programs.has(image, "g_FontStringWords") else None


def characters_of(image: bytes) -> Characters | None:
    """What `image`'s program's glyph codes stand for, for a reading by a
    person: SLPS_013.97's (formats.jp_characters); None for SLUS_006.28,
    whose text is ASCII and whose own glyphs are kept as {GLYPH:xxxx}."""
    if programs.program_of(image) != programs.JP:
        return None
    from . import jp_characters
    return jp_characters.character


def exe_words(image: bytes, addr: int | None = None,
              image_base: int = EXE_BASE) -> list[tuple[int, bytes]]:
    """The dictionary's WORD_COUNT words as `Words` reads them: (address,
    word) for n = 0 .. 511."""
    words = Words(image, addr, image_base)
    return [(words.address(n), words(n)) for n in range(WORD_COUNT)]


def exe_char_table(image: bytes, addr: int | None = None,
                   image_base: int = EXE_BASE) -> Callable[[int], int]:
    """g_FontStringCodes (0x800B34C0) — the byte -> 16-bit code table font_string_walk (0x8005A884) reads and MessageCodesConv (0x8005AC44) searches.
    `addr` defaults to where `image`'s program keeps it."""
    if addr is None:
        addr = programs.address(image, "g_FontStringCodes", CHAR_TABLE_ADDR)
    return lambda b: struct.unpack_from("<H", image, addr - image_base + 2 * b)[0]

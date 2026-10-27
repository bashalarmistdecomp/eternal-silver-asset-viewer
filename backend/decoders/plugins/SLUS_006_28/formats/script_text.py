"""The executable's own text, as the Program text tab shows it.

What the program keeps as text in its image:

* the dictionary of words, g_FontStringWords (0x800B386C): 512 words, each ended by a 0
  byte, read as font_string_word_get (0x80059F4C) reads them (`system_strings.exe_words`).
  Word n is what a packed string's run byte 0x5C + n (or 0xFD / 0xFE and a
  byte) puts in (docs/spec/text.md §"The dictionary");
* the memory-card short names of the locations, g_CardSavePlaceNames (0x800A8618)
  (`read_location_names`): 84 pointers to 83 texts, 67 of them at
  0x800110F4-0x800114E5 and 16 at 0x800B85C4-0x800B8638 (the block's note
  gives the runs it finds);
* the developers' texts the register names, each with the code that reads
  it (`DEVELOPER_TEXTS`): a debug viewer's caption, a copied and unused
  '000', the source-file names two assertions give, and the host-mode path
  format and console name.

SLPS_013.97 keeps the same kinds of text but no dictionary (its walk has
no runs to put words in), and its short location names are two-byte
Shift-JIS, the memory card's own encoding for a title, which its
card_save_title_set (SLPS_013.97 0x8001DC0C) copies two bytes at a time.

The game's packed text is not here: the string table (LUNADATA resource 1)
and the messages of the event scripts (command 0x02, ScriptCommandMessageDisp (0x8005AB1C))
are walked by font_string_walk (0x8005A884), which formats.system_strings transcribes, and
their controls are named there as MessageControlRun (0x8005AF20) acts on them.
"""

import struct
from dataclasses import dataclass, field

from . import system_strings
from ..records import programs


@dataclass
class TextEntry:
    """One string of a block, as the tab prints it."""

    text: str
    address: int = 0


@dataclass
class TextBlock:
    """A region of the executable's text."""

    label: str
    address: int = 0
    """RAM address of the region's first string."""
    entries: list[TextEntry] = field(default_factory=list)
    note: str = ""
    """What reads the region, for the tab's header."""


def dictionary_block(image: bytes) -> TextBlock:
    """The dictionary's 512 words, numbered as a packed string numbers them."""
    if not programs.has(image, "g_FontStringWords"):
        return TextBlock(
            label="Dictionary of words — g_FontStringWords",
            note=(f"{programs.program_of(image)} has no dictionary: its "
                  "font_string_put (0x80026F78; SLPS_013.97 0x8002A788) and message walk "
                  "read every byte as a character code, with no 0x0E runs."))
    words = system_strings.exe_words(image)
    end = words[-1][0] + len(words[-1][1]) + 1
    block = TextBlock(
        label="Dictionary of words — g_FontStringWords",
        address=system_strings.WORDS_ADDR,
        note=(f"{len(words)} words, 0x{system_strings.WORDS_ADDR:08X}-0x{end:08X}; word n as "
              "font_string_word_get (0x80059F4C) finds it, past n 0 bytes. A packed string's "
              "run byte 0x5C + n puts word n in (0xFD b: word b + 0xA1, "
              "0xFE b: word b + 0x19E)."))
    for n, (addr, word) in enumerate(words):
        block.entries.append(TextEntry(f'{n:3d}  "{word.decode("ascii", errors="replace")}"', addr))
    return block


#: card_save_title_set (0x8001BF50) indexes the short-name table by location id - 0x51.
SHORT_NAME_FIRST_LOCATION = 0x51


def _ascii_at(binary, ptr: int, limit: int = 40) -> str | None:
    """The NUL-terminated ASCII string at `ptr`, or None when `ptr` is not
    inside the image or does not point at printable text."""
    if not (binary.text_start <= ptr < binary.code_end):
        return None
    raw = binary.read_bytes(ptr, limit).split(b"\x00")[0]
    if not raw or any(c < 0x20 or c > 0x7E for c in raw):
        return None
    return raw.decode("ascii")


def _card_text_at(binary, ptr: int, limit: int = 40) -> str | None:
    """SLPS_013.97's short name at `ptr`: two-byte Shift-JIS up to its 0,
    or None when it is not that."""
    if not (binary.text_start <= ptr < binary.code_end):
        return None
    raw = binary.read_bytes(ptr, limit).split(b"\x00")[0]
    try:
        return raw.decode("shift_jis") if raw else None
    except UnicodeDecodeError:
        return None


def read_location_names(binary) -> dict[int, str]:
    """The memory-card short location names, by location id.

    g_CardSavePlaceNames (0x800A8618) holds 84 pointers indexed by location
    id - 0x51; its one reader, card_save_title_set (0x8001BF50), puts one in
    the memory-card title (beside the save's number, play time and level) in
    the save path (card_save_header_set, 0x800253C8). These are
    short forms of the names; the names the game displays are the string
    table's, location id + 0x400 (formats.system_strings). A slot that does
    not point at an ASCII string inside the image is left out.
    """
    from decoders.psx.analysis.symbols import lookup

    table = lookup("g_CardSavePlaceNames")
    if table is None:
        return {}
    base = programs.address(binary, table.name, table.addr)
    text_at = (_card_text_at if programs.program_of(binary) == programs.JP
               else _ascii_at)
    names: dict[int, str] = {}
    for i in range(table.size // 4):
        try:
            ptr = binary.read_u32(base + i * 4)
        except (IndexError, ValueError, struct.error):
            break
        name = text_at(binary, ptr)
        if name:
            names[SHORT_NAME_FIRST_LOCATION + i] = name
    return names


@dataclass(frozen=True)
class NamedText:
    """A text the register names, and the code that reads it."""

    addr: int
    name: str
    reader: str


#: The developers' texts among the data from 0x800B857C to 0x800B8700, by
#: the register. The other texts there, 0x800B85C4-0x800B8638, are place
#: names g_CardSavePlaceNames (0x800A8618) points at (the block above).
DEVELOPER_TEXTS = (
    NamedText(0x800B857C, "D_800B857C",
              "debug_sprite_page_show (0x80019044), the developers' viewer of the "
              "sprite pages: its caption, with the page and the palette row "
              "written in (debug_digits_put, 0x80018FA4)"),
    NamedText(0x800B8588, "D_800B8588",
              "sprite_draw (0x8001A528): copied to its stack and not read again"),
    NamedText(0x800B8594, "D_800B8594",
              "IconCellSet (0x8001AF04): the source file it hands assert_fail "
              "(0x8001B050) with line 0x132"),
    NamedText(0x800B85A0, "D_800B85A0",
              "FaceSlotGet (0x8001B200): the source file it hands assert_fail "
              "(0x8001B050) with line 0x9E"),
    NamedText(0x800B86E4, "g_FileHostPathFormat",
              "file_load (0x80021034): the format of a file's path on the host "
              "(host mode only)"),
    NamedText(0x800B86F8, "g_SimConsoleFileName",
              "sim_console_write (0x80021740): the host console it opens and "
              "writes to"),
)


def text_runs(texts: list[tuple[int, str]]) -> list[tuple[int, int, int]]:
    """(first address, last address, count) of each run of texts lying back
    to back: a text starts within 4 bytes of the 0 that ends the one before
    (the gap is padding to a word). A text is measured in the bytes it was
    read from: Shift-JIS, which is ASCII's one byte a letter and two for a
    Japanese character."""
    runs: list[list[int]] = []
    for addr, text in sorted(set(texts)):
        end = addr + len(text.encode("shift_jis", "replace"))   # the text's 0
        if runs and addr - runs[-1][1] <= 4:
            runs[-1][1] = max(runs[-1][1], end)
            runs[-1][2] += 1
        else:
            runs.append([addr, end, 1])
    return [tuple(r) for r in runs]


def exe_text_blocks(binary) -> list[TextBlock]:
    """The executable's text regions, for the Program text tab."""
    from decoders.psx.analysis.symbols import lookup

    blocks = [dictionary_block(binary.code)]

    # the location-name table, read through its pointers so the entries
    # keep their table index
    names = read_location_names(binary)
    if names:
        table = lookup("g_CardSavePlaceNames")
        base = programs.address(binary, table.name, table.addr)
        rows = [(loc, binary.read_u32(base + 4 * (loc - SHORT_NAME_FIRST_LOCATION)), name)
                for loc, name in sorted(names.items())]
        where = ", ".join(f"0x{a:08X}-0x{e:08X} ({n})"
                          for a, e, n in text_runs([(ptr, name) for _l, ptr, name in rows]))
        block = TextBlock(
            label="Location short names (memory-card titles, by location id)",
            address=base,
            note=("card_save_title_set (0x8001BF50): pointer location id - 0x51; "
                  f"the texts at {where}"))
        for loc, ptr, name in rows:
            block.entries.append(TextEntry(f"[{loc:#04x}] {name}", ptr))
        blocks.append(block)

    block = TextBlock(label="Developers' texts (named by the register)",
                      address=programs.address(binary, DEVELOPER_TEXTS[0].name,
                                               DEVELOPER_TEXTS[0].addr),
                      note="each with the code that reads it")
    jp = programs.program_of(binary) == programs.JP
    for t in DEVELOPER_TEXTS:
        if not programs.has(binary, t.name):
            continue
        addr = programs.address(binary, t.name, t.addr)
        # the Japanese row names the function there, and what differs
        reader = (programs.JP_TABLES[t.name].proof
                  + (f"; {programs.JP_TABLES[t.name].note}"
                     if programs.JP_TABLES[t.name].note else "")) if jp else t.reader
        text = _ascii_at(binary, addr)
        if text is not None:
            block.entries.append(TextEntry(f'0x{addr:08X}  {t.name}  "{text}"\n'
                                           f"            {reader}", addr))
    if block.entries:
        blocks.append(block)

    return blocks

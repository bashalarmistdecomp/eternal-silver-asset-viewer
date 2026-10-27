"""The message window on made-up glyphs and messages — no game data.

What this CAN catch: font_pattern_outline's outline, font_code_put's width
and nibble order, font_pen_move's cell steps, MessageControlRun's rows,
pages, prompt and close, MessageFaceSet's places, the stops a message
leaves, and where `draw` puts the shade, the text, a face and the arrow.

What it CANNOT catch: whether the program's patterns are where
PATTERNS_20 / PATTERNS_9908 say, or what row 507 holds. Only re-reading
font_pattern_get (0x80026B1C) and font_cell_draw (0x80016134) does that.
"""

import struct

from PIL import Image

from decoders.plugins.SLUS_006_28.formats import message_window as mw
from decoders.plugins.SLUS_006_28.formats import system_strings as ss

BAR = bytes([0x80, 0x00] * 15 + [0, 0])        # column 0 of rows 0..14
DOT = bytes([0x80, 0x00] + [0] * 30)           # one pixel, row 0 column 0


def font(**glyphs: bytes) -> mw.Font:
    """A program image holding only the made-up glyphs, by character."""
    image = bytearray(mw.PATTERNS_20 - ss.EXE_BASE + mw.PATTERNS_20_COUNT * 32)
    for ch, pattern in glyphs.items():
        at = mw.PATTERNS_20 - ss.EXE_BASE + (ord(ch) - 0x20) * 32
        image[at:at + 32] = pattern
    return mw.Font(bytes(image))


def nibble(buf: bytes, x: int, y: int, row: int = 0) -> int:
    b = buf[row * mw.ROW_BYTES + (x // 16) * mw.CELL_BYTES + y * 8 + (x % 16) // 2]
    return b >> 4 if x & 1 else b & 0xF


def run(text: bytes) -> bytes:
    """A message: a 0x0E run of `text` (ASCII), then the end."""
    return b"\0\0" + bytes([0x0E, *(c - 0x1F for c in text), 0x00, 0xFF])


def no_words(n: int) -> bytes:
    return b""


GREYS = [(n, n, n, 255) for n in range(256)]


def message(win: mw.Window, raw: bytes, table: bytes = bytes(4)) -> mw.Message:
    return win.message(raw, 0, no_words, lambda b: 0xF000 | b, table)


def test_the_outline_is_left_right_above_and_below_never_diagonal():
    rows = mw.outline(DOT)
    assert rows[1][0] == 1
    assert rows[0][0] == 3 and rows[2][0] == 3 and rows[1][1] == 3
    assert rows[0][1] == 0 and rows[2][1] == 0
    assert len(rows) == 17


def test_a_glyph_is_as_wide_as_its_rightmost_column_and_a_blank_is_5():
    assert mw.glyph_width(mw.outline(DOT)) == 2
    assert mw.glyph_width(mw.outline(bytes(32))) == mw.BLANK_WIDTH


def test_code_put_ors_columns_in_and_steps_the_pen():
    win = mw.Window(font(A=BAR))
    win.code_put(0x41)
    assert win.pen == 2
    assert nibble(win.buf, 0, 1) == 1 and nibble(win.buf, 1, 1) == 3
    assert nibble(win.buf, 0, 0) == 3
    win.colbits = 4
    win.code_put(0x41)
    assert nibble(win.buf, 2, 1) == 1 | 4


def test_the_pen_moves_a_cell_on_every_16_pixels():
    win = mw.Window(font())
    win.pen_move(20)
    assert (win.target, win.pen) == (mw.CELL_BYTES, 4)


def test_a_message_stops_at_each_prompt_and_a_page_clears_the_rows():
    win = mw.Window(font(A=BAR, B=BAR))
    m = message(win, run(b"A@B%^A$"))
    assert [s.why for s in m.screens] == ["prompt", "prompt"]
    first = m.screens[0]
    assert nibble(first.rows, 0, 1, row=0) == 1 and nibble(first.rows, 0, 1, row=1) == 1
    assert first.text == "A\nB"
    assert nibble(m.screens[1].rows, 0, 1, row=1) == 0
    assert win.places == 0 and not win.buf.strip(b"\0")


def test_a_fourth_row_turns_the_page_without_a_wait():
    m = message(mw.Window(font(A=BAR)), run(b"A@A@A@A%"))
    assert [s.why for s in m.screens] == ["page", "prompt"]
    assert m.screens[1].text == "A"


def test_a_message_that_does_not_close_leaves_the_window_open():
    win = mw.Window(font(A=BAR))
    m = message(win, run(b"AA"))
    assert [s.why for s in m.screens] == ["open"]
    m2 = message(win, run(b"A%"))
    assert m2.screens[0].text == "AAA"


def test_faces_place_the_speaker_and_a_new_place_clears_only_itself():
    win = mw.Window(font(A=BAR))
    raw = b"\0\0" + bytes([0xFA, 0x07, 0x0E, 0x22, 0x00, 0xFB, 0x0C, 0x0E, 0x22, 0x06, 0x00, 0xFF])
    m = message(win, raw)
    assert [s.faces for s in m.said] == [((0x10, 7),), ((0x20, 12),)]
    shot = m.screens[0]
    assert shot.places == 0x20
    assert shot.faces == {0x10: 7, 0x20: 12}


def test_a_splice_comes_from_the_table_passed_in():
    table = struct.pack("<HH", 0, 4) + bytes([0x0E, 0x22, 0x00, 0xFF])
    raw = b"\0\0" + bytes([0xF0, 0x01, 0x0E, 0x06, 0x00, 0xFF])
    m = message(mw.Window(font(A=BAR)), raw, table)
    assert m.said[0].text == "A" and m.screens[0].why == "prompt"


def test_draw_puts_shade_text_face_and_arrow_where_the_game_does():
    win = mw.Window(font(A=BAR))
    m = message(win, b"\0\0" + bytes([0xFA, 0x03, 0x0E, 0x22, 0x06, 0x00, 0xFF]))
    colours = [(0, 0, 0, 0)] * 0xE0 + [(n * 16, 200, 100, 255) for n in range(16)] + [(0, 0, 0, 0)] * 0x10
    colours[0xE0] = (0, 0, 0, 0)
    face = Image.new("RGBA", (64, 64), (1, 2, 3, 255))
    im = mw.draw(m.screens[0], colours, lambda f: face if f == 3 else None)
    assert im.size == (mw.WIDTH, mw.HEIGHT)
    assert im.getpixel((300, 152 - mw.TOP)) == (0, 0, 0, mw.SHADE_ALPHA)
    assert im.getpixel((300, 151 - mw.TOP))[3] == 0
    x0 = 0xA * 8                            # place 0x10: text from column 0xA
    assert im.getpixel((x0, 160 + 1 - mw.TOP)) == colours[0xE1]
    assert im.getpixel((8, 0)) == (1, 2, 3, 255)
    assert im.getpixel((0x128 + 4, mw.US_LAYOUT.arrow_y + 1 - mw.TOP)) == mw.ARROW_COLOUR


def test_a_rows_last_cells_move_down_a_grid_row_past_column_40():
    screen = mw.Screen(bytes(mw.PAGE_BYTES), 0x10, {}, "open", "")
    rows = bytearray(screen.rows)
    rows[16 * mw.CELL_BYTES] = 0x01        # row 0, cell 16, pixel (0, 0)
    screen.rows = bytes(rows)
    colours = [(9, 9, 9, 255)] * 256
    colours[0xE0] = (0, 0, 0, 0)
    im = mw.draw(screen, colours, lambda f: None)
    assert im.getpixel((2 * 8, (mw.TEXT_ROW + 1) * 8 - mw.TOP)) == (9, 9, 9, 255)


def test_answer_strings_follow_the_command_and_the_first_end():
    buf = bytes([7, 0, 5, 0, 1, 0]) + b"ab\xff" + b"c\xff"
    assert mw.answer_strings(buf, 0) == (6, 9)


def test_a_kanji_rom_glyph_is_counted_and_stood_in_for_and_the_wide_space_is_blank():
    win = mw.Window(font())
    raw = b"\0\0" + bytes([0xE3, 0x67, 0xD6, 0x40, 0xFF])     # 0x8E67, 0x8140
    m = message(win, raw)
    assert m.rom_glyphs == 1
    moved = win.target // mw.CELL_BYTES * mw.CELL + win.pen
    assert moved == mw.glyph_width(mw.outline(mw.ROM_STAND_IN)) + mw.BLANK_WIDTH


def test_a_kanji_rom_glyph_is_drawn_by_the_font_it_is_given_by_its_character():
    f = font()
    f.characters = {0x8E67: "x", 0x8E68: "y"}.get              # made up
    f.rom_font = {"x": BAR}.get                                 # draws x only
    assert f.outline(0x8E67) == mw.outline(BAR) and not f.boxed(0x8E67)
    assert f.outline(0x8E68) == mw.outline(mw.ROM_STAND_IN) and f.boxed(0x8E68)
    assert f.outline(0x8140) == mw.outline(bytes(32)) and not f.boxed(0x8140)
    raw = b"\0\0" + bytes([0xE3, 0x67, 0xE3, 0x68, 0xE3, 0x67, 0xFF])
    m = message(mw.Window(f), raw)
    assert (m.rom_glyphs, m.rom_boxed) == (3, 1)


def test_the_font_drawn_glyphs_alone_are_tinted():
    f = font(A=DOT)
    f.characters = {0x8E67: "x"}.get
    f.rom_font = {"x": DOT}.get
    plain = mw.string_image(f, [ord("A"), 0x8E67], GREYS)
    tinted = mw.string_image(f, [ord("A"), 0x8E67], GREYS, (255, 0, 0))
    grey = mw.TEXT_CLUT_FIRST + 1
    assert plain.getpixel((2, 1)) == (grey, grey, grey, 255)
    assert tinted.getpixel((0, 1)) == plain.getpixel((0, 1))         # A: the game's
    assert tinted.getpixel((2, 1)) == ((grey + 255) // 2, grey // 2, grey // 2, 255)
    assert tinted.getpixel((3, 0)) == plain.getpixel((3, 0))         # no pixel: as is


def test_the_japanese_font_its_listed_codes_and_its_wider_blank(jp_image):
    from decoders.plugins.SLUS_006_28.records import programs
    p9908 = programs.JP_TABLES["g_FontPatterns9908"].addr
    img = jp_image(mw.JP_LIST_ADDR - ss.EXE_BASE + 0x100)
    at = p9908 - ss.EXE_BASE + 2 * 32                       # code 0x990A
    img[at:at + 32] = DOT
    listed = mw.JP_LIST_ADDR - ss.EXE_BASE
    img[listed:listed + 3] = bytes([0x47, 0x45, 0])         # 0x8447, 0x8445
    second = p9908 - ss.EXE_BASE + (mw.PATTERNS_9908_COUNT + 1) * 32
    img[second:second + 32] = BAR
    f = mw.Font(bytes(img))
    assert f.pattern(0x990A) == DOT
    assert f.pattern(0x8445) == BAR                         # the list's second
    assert f.pattern(0x8446) == bytes(32)                   # not listed: blank
    assert not f.from_rom(0x8446)
    assert f.pattern(0x41) is None and f.from_rom(0x41)     # no 0x20 table there
    assert f.blank_width == mw.JP_BLANK_WIDTH == 10
    assert len(f.columns(0x8446)) == 10


def test_the_japanese_window_says_its_codes_as_characters(jp_image):
    from decoders.plugins.SLUS_006_28.formats import jp_characters as jc
    f = mw.Font(bytes(jp_image(mw.JP_LIST_ADDR - ss.EXE_BASE + 0x100)))
    assert f.characters is jc.character
    f.characters = {0x9A01: "x", 0x8140: "\u3000"}.get       # made up
    raw = b"\0\0" + bytes([0xEF, 0x01, 0xD6, 0x40, 0xEF, 0x02, 0xFF])
    m = mw.Window(f, draw=False).message(raw, 0, None, lambda b: 0xF000 | b, bytes(4))
    assert m.said[0].text == "x\u3000{GLYPH:9A02}"



def test_a_string_is_drawn_glyph_by_glyph_with_moves_and_rows():
    f = font(A=DOT, B=BAR)
    im = mw.string_image(f, [ord("A"), 0xF903, ord("B"), mw.ROW_BREAK, ord("A")], GREYS)
    assert im.size == (2 + 3 + 2, 32)               # A, a 3-pixel move, B; two rows
    assert im.getpixel((0, 1))[0] == mw.TEXT_CLUT_FIRST + 1      # A's pixel
    assert im.getpixel((5, 1))[0] == mw.TEXT_CLUT_FIRST + 1      # B's bar, after the move
    assert im.getpixel((0, 17))[0] == mw.TEXT_CLUT_FIRST + 1     # A on the second row
    styled = mw.string_image(f, [0xFC01, ord("A")], GREYS)
    assert styled.getpixel((0, 1))[0] == mw.TEXT_CLUT_FIRST + (1 | 4)
    assert mw.string_image(f, [0xFF00, 0xF123], GREYS) is None


def lit(row: int, cell: int) -> mw.Screen:
    """A screen whose text row `row` has one pixel set, (0, 0) of `cell`."""
    rows = bytearray(mw.PAGE_BYTES)
    rows[row * mw.ROW_BYTES + cell * mw.CELL_BYTES] = 0x01
    return mw.Screen(bytes(rows), 0, {}, "prompt", "")


def drawn_at(screen: mw.Screen, layout: mw.Layout) -> list[tuple[int, int]]:
    colours = [(0, 0, 0, 0)] * 256
    colours[mw.TEXT_CLUT_FIRST + 1] = (9, 9, 9, 255)
    im = mw.draw(screen, colours, lambda f: None, arrow=False, layout=layout)
    return [(x, y + mw.TOP) for y in range(mw.HEIGHT) for x in range(mw.WIDTH)
            if im.getpixel((x, y)) == (9, 9, 9, 255)]


def test_the_japanese_layout_is_the_program_s(jp_image):
    assert mw.layout_of(bytes(jp_image(0x100))) is mw.JP_LAYOUT
    assert mw.layout_of(bytes(0x100)) is mw.US_LAYOUT


def test_a_japanese_row_with_a_face_shows_its_first_13_cells_from_column_0xb():
    sc = lit(1, 12)
    sc.places = 0x10
    assert drawn_at(sc, mw.JP_LAYOUT) == [(0xB * 8 + 12 * 16, (mw.TEXT_ROW + 2) * 8)]
    sc = lit(1, 13)
    sc.places = 0x10
    assert drawn_at(sc, mw.JP_LAYOUT) == []                 # held, not shown
    assert drawn_at(sc, mw.US_LAYOUT) != []
    sc = lit(0, 12)
    sc.places = 1
    assert drawn_at(sc, mw.JP_LAYOUT) == []                 # place 1: 12 cells
    sc = lit(0, 11)
    sc.places = 1
    assert drawn_at(sc, mw.JP_LAYOUT) == [(0xD * 8 + 11 * 16, mw.TEXT_ROW * 8)]


def test_a_japanese_row_with_no_face_splits_at_its_line_s_end():
    # row 2 starts at block 2: 14 cells, then the rest 28 grid columns on
    assert drawn_at(lit(2, 14), mw.JP_LAYOUT) == [((3 + 28) * 8, (mw.TEXT_ROW + 4) * 8)]
    assert drawn_at(lit(2, 13), mw.JP_LAYOUT) == [(3 * 8 + 13 * 16, (mw.TEXT_ROW + 4) * 8)]
    assert drawn_at(lit(0, 16), mw.JP_LAYOUT) == [((3 + 32) * 8, mw.TEXT_ROW * 8)]


def test_cell_runs_split_as_font_cell_run_set_does():
    assert mw.cell_runs(2, 0x14, 13, 17) == [(2, 0x14, 0, 13)]
    assert mw.cell_runs(0xA, 0x14, 17, 0) == [(0xA, 0x14, 0, 16), (2, 0x15, 16, 1)]
    assert mw.cell_runs(3, 0x16, 17, 17) == [(3, 0x16, 0, 15), (33, 0x16, 15, 2)]
    assert mw.cell_runs(3, 0x16, 15, 17) == [(3, 0x16, 0, 15)]     # no empty rest


def test_the_japanese_face_and_arrow_sit_where_that_program_puts_them():
    sc = mw.Screen(bytes(mw.PAGE_BYTES), 0x20, {0x20: 5}, "prompt", "")
    face = Image.new("RGBA", (64, 64), (1, 2, 3, 255))
    im = mw.draw(sc, [(0, 0, 0, 0)] * 256, lambda f: face, layout=mw.JP_LAYOUT)
    assert im.getpixel((0x1E * 8, 0x12 * 8 - mw.TOP)) == (1, 2, 3, 255)
    assert im.getpixel((0x1E * 8 - 1, 0x12 * 8 - mw.TOP)) != (1, 2, 3, 255)
    assert im.getpixel((0xE8 + 4, 0xC8 + 1 - mw.TOP)) == mw.ARROW_COLOUR

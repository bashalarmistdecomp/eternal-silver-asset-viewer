"""Tier 1 for the event-script walker — synthetic bytes, no game data.

What this CAN catch: the label table's extent, each command-length rule the
module transcribes (fixed lengths, the alignment-dependent ones, the byte /
pair / word lists, the select menu's two FF strings, the text handler's
early end at '$'), the BATTLE and spell-giving operand layouts, the sweep's stop reasons and
the gap classification, and the shop a command 0x2E opens.

What it CANNOT catch: that a length is the handler's — only re-reading the
handler does that. See decoders/testing.py.
"""

import struct

import pytest

from decoders.plugins.SLUS_006_28.formats import event_script as es
from decoders.plugins.SLUS_006_28.formats import system_strings as ss


def u16(*w):
    return b"".join(struct.pack("<H", x) for x in w)


def script(code: bytes, label_offsets=(None,)) -> bytes:
    """A resource: label table (label n at index n), code after it."""
    n = len(label_offsets)
    table = bytearray(2 * (n + 1))
    base = len(table)
    for i, off in enumerate(label_offsets, start=0):
        if off is not None:
            struct.pack_into("<H", table, 2 * i, (base + off) // 2)
    return bytes(table) + code


# the dictionary: word 0 "ab", word 1 a backslash, word 2 "$"
WORDS = ss.Words(bytes(ss.WORDS_ADDR - es.EXE_BASE) + b"ab\x00\x5c\x00$\x00" + bytes(0x100))


def test_labels_stop_where_the_first_label_code_begins():
    buf = script(u16(0x03, 0) + u16(0x05), [None, 0, 4])
    assert es.labels(buf) == {1: 8, 2: 12}
    assert es.labels(bytes(8)) == {}


def test_fixed_length_commands():
    buf = script(u16(0x2B, 1, 0x0301, 0xFF05) + u16(0x1F, 0) + u16(0x5E), [None, 0])
    cmds, gaps = es.script_code(buf, WORDS)
    assert [(c.id, c.end - c.offset) for c in cmds[:3]] == [(0x2B, 8), (0x1F, 4), (0x5E, 2)]


def test_battle_operands():
    code = struct.pack("<HHBBBB", es.BATTLE, 0x1FF, 3, 2, 1, 0xFF) + u16(0x5E)
    buf = script(code, [None, 0])
    cmds, _ = es.script_code(buf, WORDS)
    b = es.battles(buf, cmds)
    assert b == [{"offset": 6, "label": 0x1FF, "row": 3, "restore": 2, "music": 1, "bgm": 0xFF}]


def test_a_spell_given_is_the_id_then_the_spell():
    code = struct.pack("<HBB", es.SPELL_SET, 0x0B, 7) + struct.pack("<HBB", es.SPELL_SET, 2, 9) + u16(0x5E)
    buf = script(code, [None, 0])
    cmds, _ = es.script_code(buf, WORDS)
    assert es.spells_given(buf, cmds) == [(0x0B, 7), (2, 9)]


def test_a_shop_is_the_byte_after_the_command_word():
    code = struct.pack("<HBB", es.SHOP_RUN, 5, 0) + struct.pack("<HBB", es.SHOP_RUN, 0x22, 0) + u16(0x5E)
    buf = script(code, [None, 0])
    cmds, _ = es.script_code(buf, WORDS)
    assert es.shop_runs(buf, cmds) == [(6, 5), (10, 0x22)]


def test_encounter_row_is_operand_minus_one_times_eight():
    img = bytearray(es.ENCOUNTER_ROWS_ADDR - es.EXE_BASE + 40)
    img[es.ENCOUNTER_ROWS_ADDR - es.EXE_BASE + 8] = 77
    assert es.encounter_row(bytes(img), 2) == 77
    with pytest.raises(ValueError):
        es.encounter_row(bytes(img), 0)


def test_encounter_rows_decode_all_eight_bytes():
    # ScriptCommandMapBtlRun (0x8005DFF0): [0] encounter, [1] MapBtlRun
    # (0x8007AE58)'s arg1, [2..7] the party list to its first 0 (six at
    # most); rows naming encounter 0 are empty
    img = bytearray(ss.WORDS_ADDR - es.EXE_BASE)
    base = es.ENCOUNTER_ROWS_ADDR - es.EXE_BASE
    img[base: base + 8] = bytes([0xD1, 0x06, 0, 9, 9, 9, 9, 9])          # row 1: field party
    img[base + 16: base + 24] = bytes([0xC5, 0, 0x0A, 0x08, 1, 3, 6, 2])  # row 3: six ids
    img[base + 63 * 8] = 0x29                                           # row 64: the last
    assert es.ENCOUNTER_ROW_COUNT == 64
    rows = es.encounter_rows(bytes(img))
    assert rows == [es.EncounterRow(row=1, encounter=0xD1, x_shift=6, party=()),
                    es.EncounterRow(row=3, encounter=0xC5, x_shift=0, party=(0x0A, 0x08, 1, 3, 6, 2)),
                    es.EncounterRow(row=64, encounter=0x29, x_shift=0, party=())]
    assert [es.encounter_row(bytes(img), r.row) for r in rows] == [0xD1, 0xC5, 0x29]



def test_a_rows_own_list_fills_the_slots_as_ScriptCommandMapBtlRun_does():
    # id 0xC to slot 5, every other id in order from slot 0
    row = es.EncounterRow(row=2, encounter=0xE2, x_shift=10, party=(1, 0xC, 6, 7))
    assert row.slot_ids() == (1, 6, 7, 0, 0, 0xC)
    assert es.EncounterRow(row=1, encounter=0xE2, x_shift=10, party=()).slot_ids() is None
    five = es.EncounterRow(row=3, encounter=0xF4, x_shift=0, party=(11, 0xC, 3, 5, 2, 4))
    assert five.slot_ids() == (11, 3, 5, 2, 4, 0xC)


def test_byte_list_ends_after_the_zero_byte_rounded_even():
    # 0x0E: [cmd] bytes... 0 ; zero at odd offset -> next even, at even -> +2
    buf = bytes(8) + u16(0x0E) + bytes([5, 6, 0]) + bytes(5)
    assert es._list1(buf, 10, 1) == 14          # zero at 12 (even): +2
    buf2 = bytes(8) + u16(0x0E) + bytes([5, 0]) + bytes(5)
    assert es._list1(buf2, 10, 1) == 12         # zero at 11 (odd): +1


def test_pair_list_and_word_list():
    buf = bytes(4) + bytes([1, 2, 3, 4, 0, 9]) + bytes(4)
    assert es._list1(buf, 4, 2) == 10
    assert es._list2(u16(7, 8, 0, 9), 0) == 6


def test_unterminated_lists_are_walk_errors():
    with pytest.raises(es.WalkError):
        es._list1(bytes([1, 1, 1]), 0, 1)
    with pytest.raises(es.WalkError):
        es._list2(u16(1, 2), 0)


def test_conditional_command_has_label_then_list():
    buf = script(u16(0x0B, 0x42, 0x10, 0x11, 0) + u16(0x5E), [None, 0])
    cmds, _ = es.script_code(buf, WORDS)
    assert [(c.id, c.end - c.offset) for c in cmds[:2]] == [(0x0B, 10), (0x5E, 2)]


def test_four_aligned_operand_depends_on_the_address():
    # ScriptCommandMoneyAdd (0x8005CF6C): end = align4(c + 2) + 4
    assert es._a4(b"", 0, b"") == 8
    assert es._a4(b"", 2, b"") == 12
    assert es._a4(b"", 4, b"") == 12


def test_spawn_length_depends_on_the_slot():
    assert es._spawn(u16(0x34) + bytes([3, 0]), 0, b"") == 4
    assert es._spawn(u16(0x34) + bytes([0xB, 0]), 0, b"") == 0x10


def test_entity_walk_steps_by_opcode_and_ends_at_f9():
    code = u16(0x38) + bytes([2]) + bytes([0xF0, 1,  0xF3, 1, 2, 3, 4,  0xF8, 1, 2, 3,  0xF9, 0])
    assert es._entity(code, 0, b"") == len(code) - 1 + 1  # F9 at 12 (even) -> +2 = 14
    with pytest.raises(es.WalkError):
        es._entity(u16(0x38) + bytes([2, 0xFA]), 0, b"")


def test_scene_inline_and_jump_lengths():
    assert es._scene_inline(u16(0x27) + bytes([1, 0]), 0, b"") == 4
    assert es._scene_inline(u16(0x27) + bytes([0, 0]), 0, b"") == 0xE
    assert es._scene_jump(u16(0x26, 7) + bytes([1, 0, 0, 0]), 0, b"") == 8
    assert es._scene_jump(u16(0x26, 7) + bytes([0, 0, 0, 0]), 0, b"") == 0x12


def test_select_scans_two_ff_strings_and_evens():
    # [07][label][u8 pad] then "a\xff" "bc\xff" -> end rounded even
    buf = u16(0x07, 5, 0) + b"a\xff" + b"bc\xff" + bytes(4)
    assert es._select(buf, 0, b"") == 12
    with pytest.raises(es.WalkError):
        es._select(u16(0x07, 5, 0) + b"a\xff" + b"bc", 0, b"")


def test_text_ends_early_at_dollar_and_at_ff():
    # run 0E, chars 'A'-0x1F..., '$' is byte 5 (0x24 - 0x1F)
    run = bytes([0x0E, 0x22, 0x23, 0x05, 0x00, 0xFF])
    assert es.text_end(run, 0, WORDS) == 3        # stopped on the '$' byte
    assert es.text_end(bytes([0x30, 0x31, 0xFF]), 0, WORDS) == 2
    assert es.text_end(bytes([0xD6, 0x01, 0xFF]), 0, WORDS) == 2   # two-byte code
    # text command: next = end + 1 rounded to even
    assert es._text(u16(0x02) + run, 0, WORDS) == 6


def test_text_fragment_with_backslash_ends_the_message():
    # fragment 0 is "ab", 1 is "\", 2 is "$"; index byte 0x5C + n
    buf = bytes([0x0E, 0x5C + 0, 0x5C + 1, 0x00, 0xFF])
    assert es.text_end(buf, 0, WORDS) == 2        # p - 1 after reading the index byte
    buf = bytes([0x0E, 0x5C + 2, 0x00, 0xFF])
    assert es.text_end(buf, 0, WORDS) == 1


def test_sweep_stops_at_error_ids_and_reports_why():
    buf = u16(0x05, 0x01)
    cmds, why = es.sweep(buf, 0, WORDS)
    assert [c.id for c in cmds] == [5] and "0x1" in why
    assert es.sweep(u16(0x5E), 0, WORDS)[1] is None


def test_gaps_are_classified():
    # label 1 -> cmd, then 0xFFFF filler, label 2 -> cmd, then zero tail
    code = u16(0x5E) + u16(0xFFFF, 0xFFFF) + u16(0x5E) + bytes(4)
    buf = script(code, [None, 0, 6])
    cmds, gaps = es.script_code(buf, WORDS)
    assert [(g.kind, g.end - g.start) for g in gaps] == [("filler", 4), ("end", 4)]
    assert es.label_boundaries(buf, cmds) == {}
    # a stop on an error id with real bytes between it and the next label is "dead"
    code = u16(0x5E) + u16(0x01, 0x03, 0x07) + u16(0x5E)
    buf = script(code, [None, 0, 8])
    _c, gaps = es.script_code(buf, WORDS)
    assert gaps[0].kind == "dead"


def test_wrong_length_shows_as_label_off_boundary():
    code = u16(0x1F, 0) + u16(0x5E) + u16(0x5E)
    buf = script(code, [None, 0, 6])        # label 2 lands inside the 4-byte command + 2
    cmds, _ = es.script_code(buf, WORDS)
    assert es.label_boundaries(buf, cmds) == {}
    buf = script(code, [None, 0, 2])        # inside the 0x1F command
    cmds, _ = es.script_code(buf, WORDS)
    assert es.label_boundaries(buf, cmds) != {}


def test_script_resources_first_match_and_terminator():
    img = bytearray(es.SCRIPT_TABLE_ADDR - es.EXE_BASE + 16)
    o = es.SCRIPT_TABLE_ADDR - es.EXE_BASE
    for i, (a, b) in enumerate([(0, 101), (1, 102), (0, 999), (7, 0)]):
        struct.pack_into("<hh", img, o + 4 * i, a, b)
    assert es.script_resources(bytes(img)) == {0: 101, 1: 102}


def test_a_label_past_the_last_command_is_an_end_sentinel_not_an_error():
    code = u16(0x5E) + bytes(4)
    buf = script(code, [None, 0, 2])        # label 2 -> first word after the code
    cmds, _ = es.script_code(buf, WORDS)
    assert es.label_boundaries(buf, cmds) == {}


def test_scene_changes_read_the_inline_entrys_map_and_object_set():
    # ScriptCommandMapChange (0x8005DB3C) (0x26): e.b[0] = c[6], e.b[1] = c[0x10] when c[4] == 0;
    # ScriptCommandMapScriptChange (0x8005F068) (0x5D): the same two bytes, always inline
    inline = u16(0x26, 7) + bytes([0, 1, 30, 2, 0, 0, 0, 0, 0, 0, 0, 0, 60, 9])
    by_index = u16(0x26, 7) + bytes([5, 0, 0, 0])
    change = u16(0x5D, 3) + bytes([8, 0, 0x45, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x46, 1])
    code = inline + by_index + change + u16(0x5E)
    buf = script(code, [None, 0])
    cmds, _ = es.script_code(buf, WORDS)
    base = cmds[0].offset
    assert es.scene_changes(buf, cmds) == [
        {"offset": base, "id": 0x26, "entry": 0, "map": 30, "object_set": 60},
        {"offset": base + 0x12, "id": 0x26, "entry": 5, "map": None, "object_set": None},
        {"offset": base + 0x1A, "id": 0x5D, "entry": 0, "map": 0x45, "object_set": 0x46},
    ]


def test_actor_spawns_read_the_own_actor_commands_bytes():
    # ScriptCommandMoveChrRowActorSet (0x80061EAC): slot c[2]; from 0xB the
    # 16-byte form: sprite data c[3], kind c[4], x c[5], y c[6], height c[7],
    # facing c[8], layer c[9], mode c[0xA]; below 0xB a 4-byte bind
    own = u16(0x34) + bytes([0xC, 0x40, 3, 10, 20, 8, 5, 0x80, 1]) + bytes(5)
    bind = u16(0x34) + bytes([2, 7])
    buf = script(own + bind + u16(0x5E), [None, 0])
    cmds, _ = es.script_code(buf, WORDS)
    assert [(c.id, c.end - c.offset) for c in cmds] == [(0x34, 16), (0x34, 4), (0x5E, 2)]
    assert es.actor_spawns(buf, cmds) == [es.ActorSpawn(
        offset=cmds[0].offset, slot=0xC, sprite_data=0x40, kind=3, x=10, y=20,
        height=8, facing=5, layer=0x80, mode=1)]


def test_script_switches_and_the_party_kinds_a_script_sets():
    # 0x42: ScriptChange(c[4]) on the same map; 0x5D: ScriptChange(c[4])
    # after MapChange to map c[6]; 0x48: g_MapPartyKind = c[2], 3 is not a kind
    jump = u16(0x42, 1) + bytes([9, 0])
    change = u16(0x5D, 1) + bytes([0x11, 0, 0x22]) + bytes(11)
    kinds = u16(0x48) + bytes([0, 0]) + u16(0x48) + bytes([3, 0]) + u16(0x48) + bytes([2, 0])
    buf = script(jump + change + kinds + u16(0x5E), [None, 0])
    cmds, _ = es.script_code(buf, WORDS)
    assert es.script_switches(buf, cmds) == [(9, None), (0x11, 0x22)]
    assert es.party_kinds_set(buf, cmds) == {0, 2}


def test_map_scripts_follow_the_hand_overs():
    entered = {1: 10, 2: 20}
    switches = {10: [(11, None)], 11: [(12, None), (30, 3)], 20: [], 30: [(10, None)]}
    assert es.map_scripts(entered, switches) == {
        1: {10, 11, 12}, 2: {20}, 3: {30, 10, 11, 12}}


def test_the_japanese_program_has_handlers_0_to_0x5e(jp_image):
    assert es.command_count(bytes(jp_image(0x100))) == es.JP_CMD_COUNT == 0x5F
    assert es.command_count(bytes(0x100)) == es.CMD_COUNT
    buf = u16(0x5E, 0x5F, 0)               # 0x5F takes 4 bytes in the US program
    assert es.sweep(buf, 0, WORDS)[1] is None
    cmds, why = es.sweep(buf, 0, None, es.JP_CMD_COUNT)
    assert [c.id for c in cmds] == [0x5E] and "0x5f" in why


# -- walk_label ----------------------------------------------------------------

TEXT_CMD = u16(0x02) + bytes([0x30, 0x31, 0xFF, 0x00])     # a text command, 6 bytes


def _walk(code: bytes, labels: list, label: int, script_id: int | None = None):
    buf = script(code, labels)
    cmds, gaps = es.script_code(buf, WORDS)
    base = 2 * (len(labels) + 1)
    w = es.walk_label(buf, {c.offset: c for c in cmds}, label, script_id)
    rel = lambda offs: [o - base for o in offs]
    return w, rel


def test_walk_follows_tests_calls_and_jumps_falling_through_first():
    code = (u16(0x0B, 2, 5, 0)          # 0: story flag 5 set -> label 2
            + TEXT_CMD                  # 8: text A
            + u16(0x04, 3)              # 14: call label 3, then on
            + u16(0x05)                 # 18: return: the way ends
            + TEXT_CMD                  # 20 (label 2): text B
            + u16(0x03, 4)              # 26: jump to label 4
            + TEXT_CMD                  # 30 (label 3): text C
            + u16(0x05)                 # 36
            + u16(0x42, 7, 9)           # 38 (label 4): script 9 from its label 7
            + TEXT_CMD + u16(0x05))     # 44 (label 5): nothing reaches it
    w, rel = _walk(code, [None, 0, 20, 30, 38, 44], 1)
    assert rel(w.reached) == [0, 8, 14, 18, 30, 36, 20, 26, 38]
    assert rel(w.texts) == [8, 30, 20]
    assert w.handed_over == [(9, 7)] and w.lost == []


def test_walk_takes_every_label_a_pick_can_draw_and_a_won_battle():
    code = (u16(0x08, 2, 3, 0)          # 0: pick label 2, label 3, or on
            + u16(0x05)                 # 8
            + struct.pack("<HHBBBB", es.BATTLE, 3, 1, 0, 0, 0xFF)   # 10 (label 2): won -> 3
            + TEXT_CMD + u16(0x05)      # 18: lost or fled: on
            + TEXT_CMD + u16(0x05))     # 26 (label 3)
    w, rel = _walk(code, [None, 0, 10, 26], 1)
    assert rel(w.texts) == [18, 26]
    assert sorted(rel(w.reached)) == [0, 8, 10, 18, 24, 26, 32]


def test_walk_a_question_branches_but_pages_do_not():
    question = u16(0x07, 2) + bytes([0, 0]) + b"\xff\xff"   # label 2, cursor 0, two empty answers
    code = question + u16(0x05) + TEXT_CMD + u16(0x05)
    asked, rel = _walk(code, [None, 0, 10], 1)
    paged, _ = _walk(code, [None, 0, 10], 1, script_id=0xC8)
    assert rel(asked.texts) == [10] and paged.texts == []


def test_walk_reports_labels_it_cannot_follow():
    w, _rel = _walk(u16(0x03, 9) + u16(0x05), [None, 0], 1)
    assert w.lost == [9] and len(w.reached) == 1
    assert es.walk_label(script(u16(0x05), [None, 0]), {}, 4).lost == [4]


def test_the_music_and_the_sounds_a_script_plays():
    code = (struct.pack("<HBB", es.MUSIC_PLAY, 12, 3) + struct.pack("<HBB", es.MUSIC_PLAY, 0, 0)
            + struct.pack("<HH", es.SOUND_PLAY, 0x103) + struct.pack("<HH", es.SOUND_PLAY, 0)
            + u16(0x5E))
    buf = script(code, [None, 0])
    cmds, _ = es.script_code(buf, WORDS)
    assert es.music_plays(buf, cmds) == [(6, 12, 3), (10, 0, 0)]
    assert es.sound_plays(buf, cmds) == [(14, 0x103), (18, 0)]


def test_the_labels_whose_run_reaches_a_command():
    # label 1 plays a sound and ends; label 2 jumps to label 1; label 3 ends
    code = (struct.pack("<HH", es.SOUND_PLAY, 0x0B) + u16(0x5E)
            + u16(0x03, 1) + u16(0x5E))
    buf = script(code, [None, 0, 6, 10])
    cmds, _ = es.script_code(buf, WORDS)
    at = {c.offset for c in cmds if c.id == es.SOUND_PLAY}
    assert es.labels_reaching(buf, {c.offset: c for c in cmds}, at) == {min(at): [1, 2]}
    assert es.labels_reaching(buf, {c.offset: c for c in cmds}, ()) == {}


def test_a_script_swept_again_is_kept_by_its_bytes_and_dictionary():
    """script_code keeps a sweep by the script's bytes, the dictionary it
    reads and the command count: the same three give the same commands
    (lists of their own), another dictionary sweeps again."""
    words_ab = WORDS
    # the same layout, but word 2 is "a" and so does not end the text
    words_a = ss.Words(bytes(ss.WORDS_ADDR - es.EXE_BASE) + b"ab\x00\x5c\x00a\x00" + bytes(0x100))
    assert words_ab.key != words_a.key
    text = u16(es.TEXT) + bytes([0x0E, 0x5E]) + bytes([0x22, 0x00, 0xFF])
    buf = script(text + bytes(1) + u16(0x5E), [None, 0])
    first, _ = es.script_code(buf, words_ab)
    first.clear()
    again, _ = es.script_code(buf, words_ab)
    assert again and again == es._script_code(buf, words_ab, es.CMD_COUNT)[0]
    other, _ = es.script_code(buf, words_a)
    assert other == es._script_code(buf, words_a, es.CMD_COUNT)[0]
    assert other != again
    # a dictionary reader with no key is swept every time, as it was
    assert es.script_code(buf, words_ab.__call__)[0] == again

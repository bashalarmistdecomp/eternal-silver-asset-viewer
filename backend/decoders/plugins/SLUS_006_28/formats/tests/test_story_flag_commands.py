"""Tier 1 for the script commands that touch the story flags
(event_script.flag_uses, movie_plays, objects_changed, labels_reaching,
command_labels) —
made-up scripts, no game data.

What this CAN catch: a command's operands turned into the wrong flag
number (the words, the 0x580 and 0x480 bytes, the map and definition
pairs, the chest pairs either side of map 0x65, the party ids and their
folds), a check's label read from the wrong place, a 0x23 with a map
object's id counted, the scripts' numbers for an object, a chest or a tile
change disagreeing with the numbers field_objects and bg_change read for
the same thing, a command not credited to every scene whose run reaches it
(a shared label's to the scenes that call it), or a dead one credited,
and a command put in the wrong piece (the label whose code holds it).

What it CANNOT catch: that the handlers add these numbers (the C:
ScriptCommandStoryBitsSet (0x8005C504) to ScriptCommandStoryBitPairs2620Set
(0x8005CECC), ScriptCommandPartyJoin (0x8005D60C), ScriptCommandPartyLeave
(0x8005D70C), ScriptCommandStoryBitsItemsReset (0x8005EF58)).
"""

import struct

from decoders.plugins.SLUS_006_28.formats import bg_change as bc
from decoders.plugins.SLUS_006_28.formats import event_script as es
from decoders.plugins.SLUS_006_28.formats import field_objects as fo
from decoders.plugins.SLUS_006_28.formats.tests.test_event_script import WORDS, script, u16


def _uses(code: bytes, label_offsets=(None, 0)):
    buf = script(code, label_offsets)
    cmds, _gaps = es.script_code(buf, WORDS)
    return buf, cmds, es.flag_uses(buf, cmds)


def test_each_form_turns_its_operands_into_flag_numbers():
    code = (u16(0x09, 0x100, 0x101, 0)                    # words
            + u16(0x0E) + bytes([0x21, 0x22, 0, 0])         # 0x580 + byte
            + u16(0x18) + bytes([0x03, 0])                  # 0x480 + byte
            + u16(0x13) + bytes([0x66, 2, 0x20, 7, 0, 0])   # (map, definition)
            + u16(0x1A) + bytes([0x20, 4, 0x70, 1, 0, 0])   # chest (map, definition)
            + u16(0x5C) + u16(0x5E))
    _buf, _cmds, uses = _uses(code)
    assert [(u.id, u.does, u.flags) for u in uses] == [
        (0x09, es.SET, (0x100, 0x101)),
        (0x0E, es.SET, (0x5A1, 0x5A2)),
        (0x18, es.SET, (0x483,)),
        (0x13, es.SET, ((0x66 << 7) + 2 - 0x2C00, (0x20 * 0x80 + 7 - 0x2C00) & 0xFFFF)),
        (0x1A, es.SET, (4 + 0x2620 + (0x20 - 0x15) * 32, 1 + 0x2620 + (0x70 - 0x35) * 32)),
        (0x5C, es.RESET, (es.END_FLAG,))]
    assert uses[3].written == ((0x66, 2), (0x20, 7))


def test_a_check_keeps_its_label_before_its_list():
    code = (u16(0x0B, 0x42, 0x10, 0x11, 0) + u16(0x0C, 0x43, 0x12, 0)
            + u16(0x11, 0x44) + bytes([5, 0]) + u16(0x17, 0x45) + bytes([0x65, 1, 0, 0])
            + u16(0x5E))
    _buf, _cmds, uses = _uses(code)
    assert [(u.does, u.label, u.flags) for u in uses] == [
        (es.ALL, 0x42, (0x10, 0x11)), (es.NONE, 0x43, (0x12,)),
        (es.NONE, 0x44, (0x585,)), (es.ANY, 0x45, (0x65 * 0x80 + 1 - 0x2C00,))]


def test_party_ids_fold_as_the_handlers_fold_them():
    assert es.party_flag(2) == 0x2BC + 2
    assert es.party_flag(0x12) == 0x2BC + 3           # 0x10..0x1E: less 0xF
    assert es.party_flag(0x1F) == es.party_flag(0x40) == 0x2BC + 0xD
    code = (struct.pack("<HBB", 0x23, 0, 0x12) + struct.pack("<HBB", 0x23, 1, 4)
            + struct.pack("<HBBH", 0x24, 0x20, 0, 0) + u16(0x5E))
    _buf, _cmds, uses = _uses(code)
    # the second join takes its id from a map object: not in the script
    assert [(u.id, u.does, u.flags, u.written) for u in uses] == [
        (0x23, es.SET, (0x2BC + 3,), (0x12,)), (0x24, es.CLEAR, (0x2BC + 0xD,), (0x20,))]


def test_the_scripts_numbers_are_the_ones_the_maps_read():
    def made(index, kind, story=1, facing=4):
        raw = bytearray(fo.DEFINITION_SIZE)
        raw[0], raw[2], raw[6] = kind - 1, story, facing
        block = bytearray(fo.STEP_LISTS_AT)
        block[index * fo.DEFINITION_SIZE:(index + 1) * fo.DEFINITION_SIZE] = raw
        return fo.definition(bytes(block), index)
    for m in (0x20, 0x58, 0x64, 0x65, 0x66, 0x90):
        assert es.pair_flag(m, 9) == fo.story_flag(made(9, 5), m)
        assert es.chest_pair_flag(m, 3) == fo.chest_flag(made(3, 7), m)
    assert es.ENTITY_BASE + 0x21 == fo.story_flag(made(1, 2, story=0x21), 0x30)
    assert es.TILE_CHANGE_BASE == bc.BIT_BASE


def test_movies_and_objects_read_their_byte_lists():
    code = (struct.pack("<HBBH", 0x2D, 7, 0, 0) + u16(0x25) + bytes([3, 4, 0, 0])
            + u16(0x41) + bytes([5, 0]) + u16(0x5E))
    buf = script(code, (None, 0))
    cmds, _ = es.script_code(buf, WORDS)
    assert es.movie_plays(buf, cmds) == [(6, 7)]
    assert es.objects_changed(buf, cmds) == [(12, 0x25, (3, 4)), (18, 0x41, (5,))]


def test_a_command_is_credited_to_every_scene_that_reaches_it():
    # labels 1 and 2 start together and call label 3, then end; the 0x0A
    # after their end can never run; label 3 sets 0x200 and returns
    code = (u16(0x09, 0x100, 0) + u16(0x04, 3) + u16(0x5E)    # 0..11
            + u16(0x0A, 0x100, 0)                              # 12..17, dead
            + u16(0x09, 0x200, 0) + u16(0x05))                 # 18.., label 3
    buf = script(code, (None, 0, 0, 18))
    cmds, _ = es.script_code(buf, WORDS)
    base = len(buf) - len(code)
    at = [u.offset for u in es.flag_uses(buf, cmds)]
    credit = es.labels_reaching(buf, {c.offset: c for c in cmds}, at)
    assert credit[base] == [1, 2]
    assert base + 12 not in credit
    # the scene you watch: label 3's flag is set by the scenes that call it too
    assert credit[base + 18] == [1, 2, 3]


def test_a_command_is_held_in_the_labels_whose_code_holds_it():
    # labels 1 and 2 start together; label 3 after a 0x5E; the 0x0A between
    # the 0x5E and label 3 can never run
    code = (u16(0x09, 0x100, 0) + u16(0x5E)          # 0..7
            + u16(0x0A, 0x100, 0)                    # 8..13, dead
            + u16(0x09, 0x200, 0) + u16(0x5E))       # 14.., label 3
    buf = script(code, (None, 0, 0, 14))
    cmds, _ = es.script_code(buf, WORDS)
    held = es.command_labels(buf, cmds)
    base = len(buf) - len(code)
    assert held[base] == (1, 2) and held[base + 6] == (1, 2)
    assert base + 8 not in held
    assert held[base + 14] == (3,)

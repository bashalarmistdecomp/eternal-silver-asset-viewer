"""Tier 1 for the resource command list — synthetic bytes, no game data.

What this CAN catch: resource_command_run (0x800202FC)'s walk — type = the word's low byte,
the 8 + (size >> 2) * 4 stride (an unaligned size truncates), the zero
terminator, the (word >> 8) sub-index — which entry of a repeated
fixed-destination type is in effect (the last), resource_tim_add
(0x800208A0)'s numbering of kept pictures, and that every type the switch
dispatches has a name.

What it CANNOT catch: what each type's handler does with its payload;
only re-reading resource_command_run's callees does that. See
decoders/testing.py.
"""

import struct

from decoders.plugins.SLUS_006_28.formats import command_list as cl


def _list(*entries: tuple[int, bytes]) -> bytes:
    out = bytearray()
    for word, payload in entries:
        out += struct.pack("<II", word, len(payload)) + payload
    return bytes(out + struct.pack("<I", 0))


def test_walk_types_words_and_payloads():
    cmds = cl.commands(_list((0x102, b"abcdefgh"), (0x001, b"PAYL")))
    assert [(c.type, c.word, c.arg, c.payload) for c in cmds] == \
        [(2, 0x102, 1, b"abcdefgh"), (1, 1, 0, b"PAYL")]


def test_unaligned_size_truncates_the_stride():
    odd = struct.pack("<II", 0x102, 5) + b"abcd" + struct.pack("<II", 1, 0) + struct.pack("<I", 0)
    assert [c.type for c in cl.commands(odd)] == [2, 1]


def test_the_last_entry_of_a_type_is_in_effect():
    buf = _list((5, b"one!"), (6, b"lay1"), (5, b"two!"))
    assert cl.effective(buf, cl.MAP_LAYOUT).payload == b"two!"
    assert cl.effective(buf, 7) is None


def test_kept_pictures_are_numbered_in_list_order():
    # resource_tim_add (0x800208A0): sub 0 is sent at once; every other sub is
    # kept as the next picture, whatever its value.
    cmds = cl.commands(_list((0x502, b"aaaa"), (0x002, b"bbbb"), (0x5, b"lay!"),
                             (0x102, b"cccc"), (0x002, b"dddd")))
    assert [(c.payload, n) for c, n in cl.pictures(cmds)] == \
        [(b"aaaa", 0), (b"bbbb", None), (b"cccc", 1), (b"dddd", None)]


def test_every_dispatched_type_is_named():
    for t in (1, 2, 3, 4, 5, 6, 7, 9, 12, 13, 14, 15, 16, 17, 18):
        assert cl.TYPES[t].number == t and cl.TYPES[t].handler
        c = cl.Command(0, t, t, b"")
        assert "stepped over" not in cl.describe(c)
    assert set(cl.TYPES) == {1, 2, 3, 4, 5, 6, 7, 9, 12, 13, 14, 15, 16, 17, 18}
    assert cl.describe(cl.Command(0, 8, 8, b"")) == "no handler: stepped over"


def test_describe_reads_the_sub_number():
    assert "tpage 0x1b" in cl.describe(cl.Command(0, 3, 0x103, b""))
    assert "128 x 128" in cl.describe(cl.Command(0, 3, 0x303, b""))
    assert "row 506" in cl.describe(cl.Command(0, 4, 0x104, b""))
    assert "row 501" in cl.describe(cl.Command(0, 4, 0x8004, b""))
    assert "row 507" in cl.describe(cl.Command(0, 12, 0x70C, b""))
    assert "picture 3" in cl.describe(cl.Command(0, 2, 0x102, b""), picture=3)


def test_summary_counts_each_type_once_in_order():
    cmds = cl.commands(_list((9, b"x" * 4), (3, b"p" * 4), (0x103, b"p" * 4),
                             (4, b"c" * 4), (5, b"l" * 4), (16, b"a" * 4)))
    assert cl.summary(cmds) == "9 · 3×2 · 4 · 5 · 16"

"""Tier 1 for the enemies' rows — synthetic bytes, no game data.

What this CAN catch: a field that moves, a width that changes, and — the
reason the file exists — a copier-map row that stops agreeing with the
FIELDS table. The map was transcribed by hand from `BtlEnemyStatsSet (0x8002A638)`'s store
displacements, so the failure mode to guard is a typo in a hex offset, not
a decode bug.

What it CANNOT catch: whether the transcription matches the FUNCTION. Only
re-reading the asm does that. See decoders/testing.py.
"""

import struct

import pytest

from decoders.plugins.SLUS_006_28.records import enemy_templates as et


def _template(**over) -> bytes:
    """A template whose every byte is its own offset, so a mis-mapped field
    shows up as the WRONG OFFSET rather than as a plausible number."""
    buf = bytearray(range(et.STRIDE))
    for off, val in over.items():
        buf[int(off)] = val
    return bytes(buf)


def _row(**values) -> bytes:
    """A made-up template: each named FIELDS field set, the rest 0."""
    at = {name: (off, kind) for off, kind, name, _note in et.FIELDS}
    buf = bytearray(et.STRIDE)
    for name, v in values.items():
        off, kind = at[name]
        struct.pack_into({"u8": "<B", "u16": "<H"}[kind], buf, off, v)
    return bytes(buf)


def test_stride_and_layout_agree():
    assert et.STRIDE == 0x26
    # Every field lies inside the record, and none overlaps its neighbour.
    end = 0
    for off, kind, name, note in sorted(et.FIELDS):
        width = {"u8": 1, "u16": 2, "u32": 4}[kind]
        assert off >= end, f"{name} at {off:#x} overlaps the field before it"
        assert off + width <= et.STRIDE, f"{name} runs past the record"
        assert note, f"{name} has no note — the evidence is the point"
        end = off + width


def test_the_extent_is_the_registers():
    """0x12EE bytes up to g_BtlItemRowsByNumber: 127 whole rows, 0x14 over."""
    assert et.SIZE == 0x12EE
    assert (et.COUNT, et.TAIL) == (127, 0x14)
    assert et.COUNT * et.STRIDE + et.TAIL == et.SIZE
    assert et.BASE_ADDR + et.SIZE == 0x800A9A56


def test_read_from_exe_reads_every_whole_row():
    """A made-up image that ends after the last whole row: the tail is not
    needed, and every row is read, numbered from 0."""
    off = et.BASE_ADDR - et.EXE_BASE
    image = bytearray(off + et.COUNT * et.STRIDE)
    image[off + (et.COUNT - 1) * et.STRIDE + 1] = 9      # the last row's level
    rows = et.read_from_exe(bytes(image))
    assert len(rows) == et.COUNT
    assert rows[-1].index == et.COUNT - 1 and rows[-1].values["level"] == 9
    with pytest.raises(ValueError):
        et.read_from_exe(bytes(image[:-1]))


def test_every_byte_is_accounted_for():
    """The copier reads all 38 bytes but one, and FIELDS must say so."""
    covered = set()
    for off, kind, _name, _note in et.FIELDS:
        covered.update(range(off, off + {"u8": 1, "u16": 2, "u32": 4}[kind]))
    assert covered == set(range(et.STRIDE))

    read_by_copier = set()
    for src, width, _dst in et.COPIER_MAP:
        read_by_copier.update(range(src, src + width))
    assert set(range(et.STRIDE)) - read_by_copier == {0x19}


def test_copier_map_matches_the_field_table():
    by_off = {off: kind for off, kind, _n, _t in et.FIELDS}
    for src, width, dst in et.COPIER_MAP:
        assert src in by_off, f"copier reads +{src:#x}, FIELDS has no field there"
        assert {"u8": 1, "u16": 2}[by_off[src]] == width, (
            f"+{src:#x}: FIELDS says {by_off[src]}, the copier loads {width}B")
        assert 0 <= dst < et.CHARSTATS_STRIDE


def test_build_charstats_places_each_field():
    rec = et.build_charstats(_template())
    assert len(rec) == et.CHARSTATS_STRIDE
    for src, width, dst in et.COPIER_MAP:
        assert rec[dst:dst + width] == bytes(range(src, src + width)), (
            f"row +{src:#x} did not land at stats +{dst:#x}")


def test_hp_is_written_twice():
    """A fresh enemy starts at full HP because the copier stores hp at both
    +0x00 (current) and +0x02 (max) — not because anything else fills it."""
    rec = et.build_charstats(_template(**{"2": 0x2A, "3": 0x00}))
    assert rec[0x00:0x02] == rec[0x02:0x04] == b"\x2a\x00"


def test_untouched_destinations_stay_zero():
    """+0x15 is the runtime status mask and the copier never writes it."""
    rec = et.build_charstats(_template())
    written = {d for src, w, dst in et.COPIER_MAP for d in range(dst, dst + w)}
    assert 0x15 not in written
    assert rec[0x15] == 0


def test_ids_are_one_based():
    assert et.template_index(1) == 0
    assert et.template_index(7) == 6
    with pytest.raises(ValueError):
        et.template_index(0)          # 0 terminates the encounter list


def test_parse_reads_the_named_fields():
    row = _row(hp=0x1D2, stat_08=48, stat_0a=17, level=9, least_amount=3)
    rec = et.parse_record(row, 0)
    assert rec.values["hp"] == 0x1D2
    assert rec.values["stat_08"] == 48
    assert rec.values["stat_0a"] == 17
    assert rec.values["level"] == 9
    assert rec.values["least_amount"] == 3
    assert not rec.is_empty


def test_a_row_field_is_named_as_the_stats_field_it_lands_in():
    """btl.h gives a BtlEnemyRow field the name of the BtlStats field the
    copier puts it in; hp is the one stored twice (hp and hp_max)."""
    row_names = {off: name for off, _k, name, _n in et.FIELDS}
    stats_names = {off: name for off, _k, name, _n in et.BATTLE_FIELDS}
    for src, _width, dst in et.COPIER_MAP:
        if (src, dst) == (0x02, 0x02):
            assert stats_names[dst] == "hp_max"
            continue
        assert row_names[src] == stats_names[dst], (src, dst)


def test_every_stats_field_the_copier_writes_is_named():
    written = {dst for _s, _w, dst in et.COPIER_MAP}
    assert written == {off for off, *_ in et.BATTLE_FIELDS}


def test_empty_record_is_flagged():
    assert et.parse_record(bytes(et.STRIDE), 3).is_empty


def test_short_buffers_raise():
    with pytest.raises(ValueError):
        et.parse_record(bytes(et.STRIDE - 1), 0)
    with pytest.raises(ValueError):
        et.build_charstats(bytes(et.STRIDE - 1))


def test_battle_fields_lie_inside_what_the_copier_writes():
    """A BATTLE_FIELDS row naming an offset the copier never writes would
    read a zero and call it a measurement."""
    written = {d for _s, w, dst in et.COPIER_MAP for d in range(dst, dst + w)}
    for off, kind, name, note in et.BATTLE_FIELDS:
        width = {"u8": 1, "u16": 2}[kind]
        assert set(range(off, off + width)) <= written, (
            f"{name} at +{off:#x}: the copier does not write it")
        assert note, f"{name} has no note — the proving consumer is the point"


def test_battle_record_reads_through_the_copier():
    """Each named field comes from its template source via COPIER_MAP, so a
    template whose bytes are their own offsets yields the SOURCE offsets."""
    br = et.battle_record(_template())
    assert br["hp"] == br["hp_max"] == 0x0302          # row +0x02, twice
    assert br["stat_08"] == 0x0504                     # +0x04
    assert br["stat_0a"] == 0x0706                     # +0x06
    assert br["stat_0c"] == 0x0908                     # +0x08 -> +0x0C
    assert br["action_pick"] == 0x00                   # +0x00 -> +0x1A
    assert br["stat_0e"] == 0x0B0A                     # +0x0A -> +0x0E
    assert br["stat_10"] == 0x0D0C                     # +0x0C -> +0x10
    assert br["attack_count"] == 0x10                  # +0x10 -> +0x12
    assert br["level"] == 0x01                         # +0x01 -> +0x14
    assert br["least_amount"] == 0x0F                  # +0x0F -> +0x16
    assert br["trait"] == 0x11                         # +0x11 -> +0x1B
    assert br["walk_reach"] == 0x0E                    # +0x0E -> +0x13
    assert br["attack_show"] == 0x16                   # +0x16 -> +0x17
    assert br["walk_speed"] == 0x15                    # +0x15 -> +0x18
    assert br["attack_sound"] == 0x17                  # +0x17 -> +0x19
    assert br["attack_number"] == 0x12                 # +0x12 -> +0x1C
    assert br["kind7_number"] == 0x13                  # +0x13 -> +0x1D
    assert br["walk_sound"] == 0x14                    # +0x14 -> +0x1E
    assert br["action_sound"] == 0x18                  # +0x18 -> +0x1F
    assert br["win_item_1"] == 0x1E                    # +0x1E -> +0x20
    assert br["win_rate_1"] == 0x1F                    # +0x1F -> +0x21
    assert br["win_item_2"] == 0x20                    # +0x20 -> +0x22
    assert br["win_rate_2"] == 0x21                    # +0x21 -> +0x23
    assert br["experience"] == 0x1B1A                  # +0x1A -> +0x24
    assert br["money"] == 0x1D1C                       # +0x1C -> +0x26
    assert br["weak_mask"] == 0x2322                   # +0x22 -> +0x28
    assert br["resist_mask"] == 0x2524                 # +0x24 -> +0x2A


def test_battle_record_of_a_made_up_enemy():
    """The masks are the u16 words BtlTargetTraitCheck (0x80037648) reads: a
    resist mask whose LOW byte is 0 (0x2100) still resists, which a
    one-byte reader would miss."""
    row = _row(action_pick=7, level=4, stat_0c=30, stat_0e=12, stat_10=9,
               attack_count=2, least_amount=3, weak_mask=0x00C0, resist_mask=0x2100)
    br = et.battle_record(row)
    assert (br["level"], br["attack_count"], br["least_amount"]) == (4, 2, 3)
    assert (br["stat_0e"], br["stat_10"]) == (12, 9)
    # BtlTurnOrderMake (0x8002F4B0)'s key and BtlEnemyActionPick (0x8004CAB8)'s switch
    assert (br["stat_0c"], br["action_pick"]) == (30, 7)
    assert br["weak_mask"] == 0x00C0
    assert br["resist_mask"] == 0x2100
    assert br["trait"] == 0

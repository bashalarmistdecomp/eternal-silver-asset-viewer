"""SPU-ADPCM decoding — and the terminator-block trap.

The trap (docs/spec/sound.md): 704 of Lunar's 1,029 samples are followed by
the encoder's canonical one-shot end marker

    00 07 77 77 77 77 77 77 77 77 77 77 77 77 77 77

which decodes to a burst at ±28672 — a full-scale click. Hardware never
plays it; the block exists only so the SPU's repeat address has somewhere
silent to point. Decoding must therefore stop **after the block that sets
loop-end**, which in the real layout is the block *before* the terminator.

The flag census in the spec is what pins the layout: flags `1` (end, no
repeat) occurs 704 times and flags `7` (the terminator) also 704 times, so
a one-shot sample ends `… | 1 | 7` and the 7-block is never reached.

The pitch arithmetic is libsnd's `SsPitchFromNote`; its ratio tables are
checked against a program's EXE by the SLUS_006_28 plugin's
formats/tests/test_libsnd_on_disc.py when the disc is in the library.
"""

import struct

import pytest

from decoders.psx.formats import vab


def _block(flags, nibbles=0x00, shift=0, filt=0):
    """One 16-byte SPU-ADPCM block: shift/filter byte, flag byte, 14 data."""
    return bytes([(filt << 4) | shift, flags]) + bytes([nibbles]) * 14


def test_terminator_block_is_not_decoded():
    """THE trap. A one-shot sample: data, end-marker block, terminator."""
    sample = _block(0, 0x11) + _block(vab.LOOP_END, 0x11) + _block(0x07, 0x77)
    samples, loop = vab.decode_adpcm(sample)

    # Two blocks decoded, not three: 2 * 28 samples.
    assert len(samples) == 56
    assert loop is None
    # And crucially, no full-scale click.
    assert max(abs(s) for s in samples) < 28672


def test_the_terminator_really_would_click():
    """The other half of the trap — proof the guard is load-bearing.

    If the terminator were decoded, this is what would land at the end of
    every one-shot sample.
    """
    burst, _ = vab.decode_adpcm(_block(0x07, 0x77))
    assert len(burst) == 28
    assert max(abs(s) for s in burst) == 28672


def test_loop_start_alone_does_not_make_a_sample_loop():
    """Judging by LOOP_START would call all 1,029 samples looping."""
    sample = (_block(vab.LOOP_START, 0x11) + _block(vab.LOOP_END, 0x11)
              + _block(0x07, 0x77))
    _, loop = vab.decode_adpcm(sample)
    assert loop is None, "the TERMINATING block's flags decide, not loop-start"


def test_a_real_loop_reports_its_start():
    # flags 6 = loop start inside a loop region, 3 = end + repeat.
    sample = (_block(0, 0x11)
              + _block(vab.LOOP_START | vab.LOOP_REPEAT, 0x11)
              + _block(vab.LOOP_END | vab.LOOP_REPEAT, 0x11))
    samples, loop = vab.decode_adpcm(sample)
    assert len(samples) == 84
    assert loop == 28, "loop start is a SAMPLE index, not a block index"


def test_one_shot_flag_combination_is_not_a_loop():
    # ONE_SHOT is END|REPEAT|START together — the repeat address points back
    # at the terminating block itself, which is silence.
    assert vab.ONE_SHOT == 0x07
    _, loop = vab.decode_adpcm(_block(vab.ONE_SHOT, 0x11))
    assert loop is None


def test_empty_and_partial_blocks():
    assert vab.decode_adpcm(b"") == ([], None)
    # A trailing fragment shorter than a block is ignored, not read past.
    assert vab.decode_adpcm(_block(vab.LOOP_END) + b"\x00" * 5)[0] != []


def test_out_of_range_shift_and_filter_are_clamped():
    """Malformed blocks must decode the way the hardware sees them."""
    samples, _ = vab.decode_adpcm(_block(vab.LOOP_END, 0x11, shift=15, filt=7))
    assert len(samples) == 28
    assert all(-32768 <= s <= 32767 for s in samples)


def test_output_stays_in_16_bit_range():
    loud = _block(vab.LOOP_END, 0x88, shift=0, filt=0)
    assert all(-32768 <= s <= 32767 for s in vab.decode_adpcm(loud)[0])


def test_pitch_from_note_centre_octaves_and_clamp():
    p = vab.pitch_from_note
    assert p(60, 0, 60, 0) == 0x1000
    assert p(72, 0, 60, 0) == 0x2000
    assert p(48, 0, 60, 0) == 0x800
    assert p(36, 0, 60, 0) == 0x400
    # From two octaves above the centre, libsnd's maximum, whatever the note.
    assert p(83, 0, 60, 0) < vab.PITCH_MAX
    assert p(84, 0, 60, 0) == vab.PITCH_MAX
    assert p(96, 0, 60, 0) == vab.PITCH_MAX


def test_pitch_fine_parts_carry_and_borrow():
    p = vab.pitch_from_note
    assert p(60, 128, 60, 0) == p(61, 0, 60, 0)
    assert p(60, 100, 60, 28) == p(61, 0, 60, 0)
    assert p(60, -1, 60, 0) == p(59, 127, 60, 0)
    # fine steps are 1/128 semitone: a whole semitone of them is one note
    assert p(59, 127, 60, 0) < p(60, 0, 60, 0)


def test_pitch_rounds_the_octave_shift():
    # semitone 7 of the octave below the centre: (ratio + 2) >> 2
    raw = (vab.SEMITONE_RATIOS[7] * vab.FINE_RATIOS[0]) >> 16
    assert vab.pitch_from_note(67, 0, 60, 0) == (raw + 2) >> 2


def test_ratio_tables():
    assert len(vab.SEMITONE_RATIOS) == 12 and len(vab.FINE_RATIOS) == 128
    assert vab.SEMITONE_RATIOS[0] == vab.FINE_RATIOS[0] == 0x8000
    assert vab.SEMITONE_RATIOS[6] == 46340          # floor(0x8000 * 2**.5)
    assert vab.tone_sample_rate(0) == vab.SPU_BASE_RATE


def test_adsr_fields_sit_where_the_spu_reads_them():
    a = vab.decode_adsr(0x8000 | (0x55 << 8) | (0xA << 4) | 0x3,
                        0x8000 | 0x4000 | (0x2B << 6) | 0x20 | 0x11)
    assert (a["attack_mode"], a["attack_rate"], a["decay_rate"], a["sustain_level"]) == \
        ("exp", 0x55, 0xA, 0x3)
    assert (a["sustain_mode"], a["sustain_dir"], a["sustain_rate"]) == ("exp", "dec", 0x2B)
    assert (a["release_mode"], a["release_rate"]) == ("exp", 0x11)
    # bit 13 is no field: alone it changes nothing
    assert vab.decode_adsr(0, 0x2000) == vab.decode_adsr(0, 0)
    b = vab.decode_adsr(0, 0x4000)
    assert (b["sustain_dir"], b["sustain_mode"]) == ("dec", "lin")


def test_pcm_to_wav_is_a_riff_container():
    wav = vab.pcm_to_wav([0, 1000, -1000, 0], vab.SPU_BASE_RATE)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"


# -- the header, as _SsVabOpenHeadWithMode (0x8009D7F8) opens it -------------

def _vh(version, sizes, ps=1, form=b"p", slots=None, vs=None):
    """A VH with one program of one tone; `sizes` = the VAG size table's
    first entries (in the version's units)."""
    slots = slots or vab.program_slots(form[0], version)
    head = (form + b"BAV" + struct.pack("<iiI", version, 0, 0)
            + struct.pack("<HHHH", 0, ps, 1, len(sizes) - 1 if vs is None else vs)
            + bytes([127, 64, 0, 0]) + bytes(4))
    progs = bytes([1, 127, 0, 0, 64, 0]) + bytes(10) + bytes(16 * (slots - 1))
    tones = bytes(512 * ps)
    table = struct.pack(f"<{len(sizes)}H", *sizes) + bytes(2 * (256 - len(sizes)))
    return head + progs + tones + table


def test_program_slots_and_size_units_follow_the_version():
    assert (vab.program_slots(ord("p"), 7), vab.vag_size_unit(7)) == (128, 8)
    assert (vab.program_slots(ord("p"), 4), vab.vag_size_unit(4)) == (64, 4)
    assert vab.program_slots(ord("q"), 7) == 64     # another form: 64

    body = bytes(range(64)) * 2
    new = vab.parse_vab(_vh(7, [0, 2, 3]), body)
    old = vab.parse_vab(_vh(4, [0, 4, 6]), body)    # the same bytes in 4s
    assert len(new.programs) == 128 and len(old.programs) == 64
    assert old.vh_size == 32 + 64 * 16 + 512 + 512
    for v in (new, old):
        assert [(g.index, g.offset, g.size) for g in v.vags] == [(1, 0, 16), (2, 16, 24)]
        assert v.vags[1].data == body[16:40]


def test_vag_offsets_count_entry_zero_and_stop_at_vs():
    body = bytes(range(80))
    v = vab.parse_vab(_vh(7, [1, 2, 3, 5], vs=2), body)
    # entry 0's eight bytes come first in the body; entry 3 is past vs
    assert [(g.index, g.offset, g.size) for g in v.vags] == [(1, 8, 16), (2, 24, 24)]


def test_more_programs_than_slots_is_refused():
    with pytest.raises(ValueError):
        vab.parse_vab(_vh(4, [0, 2], ps=65, slots=64))

"""The sequence renderer against libsnd's reader and voice manager.

Every input is built here by hand: a VAB with a square-wave sample and the
programs a test needs, and a SEQ of a few events. The tick runs at exactly
60 Hz here, so at 44.1 kHz a tick is 735 samples, and at the default 480
ticks a quarter and 120 bpm libsnd steps 160 tenths of a delta tick (16
ticks) per sound tick. What a tick reads reaches the SPU at the next tick's
flush: at sample (tick + 1) * 735.

At pitch 0x1000 the square wave is read one sample per output sample with
no fraction, so a rendered sample is exactly `((wave * envelope) >> 15) *
volume >> 14`, then the main volume, and the volume law can be checked to
the bit.
"""

import struct
from array import array
from dataclasses import replace

import pytest

from decoders.psx.formats import seq_synth, spu_voice, vab
from decoders.psx.formats.seq import SEQ_MAGIC, parse_seq
from decoders.testing import be32, u16, u32

# -- a bank ------------------------------------------------------------------

#: Two ADPCM blocks, filter 0, shift 0: 14 samples of +0x7000 then 14 of
#: -0x7000, twice — a square wave of period 28 that loops from sample 0.
HIGH, LOW = 0x7000, -0x7000


def _block(flags):
    return bytes([0x00, flags]) + b"\x77" * 7 + b"\x99" * 7


SQUARE = _block(vab.LOOP_START | vab.LOOP_REPEAT) \
    + _block(vab.LOOP_END | vab.LOOP_REPEAT)

#: Attack at once, then hold full level: AR 0 linear; DR 0, SL 15; sustain
#: increasing (so it stays at 0x7FFF); release linear at the fastest rate.
ADSR1, ADSR2 = 0x000F, 0x0000


def _tone(center=60, lo=0, hi=127, vol=127, pan=64, shift=0, pbmin=0,
          pbmax=0, adsr1=ADSR1, adsr2=ADSR2, mode=0, vag_no=1, prior=0):
    return (bytes([prior, mode, vol, pan, center, shift, lo, hi, 0, 0, 0, 0,
                   pbmin, pbmax, 0, 0])
            + u16(adsr1, adsr2) + struct.pack("<hh", 0, vag_no) + bytes(8))


def _bank(programs, mvol=127):
    """A VAB: `programs` maps program number -> (mvol, mpan, [tone bytes])."""
    used = sorted(programs)
    head = (b"pBAV" + u32(7, 0, 0) + u16(0, len(used), 0, 1)
            + bytes([mvol, 64, 0, 0]) + u32(0))
    progs = b""
    for p in range(vab.PROGRAM_SLOTS):
        if p in programs:
            pvol, mpan, tones = programs[p]
            progs += bytes([len(tones), pvol, 0, 0, mpan, 0]) + bytes(10)
        else:
            progs += bytes(16)
    tones = b""
    for p in used:
        slot = b"".join(programs[p][2])
        tones += slot + bytes(512 - len(slot))
    sizes = u16(0, len(SQUARE) // 8) + bytes(2 * 254)
    return vab.parse_vab(head + progs + tones + sizes, SQUARE)


def _varlen(n):
    out = [n & 0x7F]
    while n > 0x7F:
        n >>= 7
        out.insert(0, (n & 0x7F) | 0x80)
    return bytes(out)


def _seq(*events, resolution=480, tempo=500_000, end=True):
    """Events as (delta ticks, bytes...), each written as its delta time
    and then its bytes, as libsnd reads them."""
    body = b""
    for delta, *msg in events:
        body += _varlen(delta) + bytes(msg)
    return parse_seq(SEQ_MAGIC + be32(1) + struct.pack(">H", resolution)
                     + tempo.to_bytes(3, "big") + bytes([4, 2])
                     + body + (b"\x00\xFF\x2F\x00" if end else b""))


TICK = 735                      # samples a 60 Hz tick at 44.1 kHz
KW = dict(tick_hz=60)


def _at(tick):
    """The sample where what `tick` read reaches the SPU."""
    return (tick + 1) * TICK


def _render(seq, bank, **kw):
    pcm, stats = seq_synth.render(seq, bank, tail_seconds=0.0, **KW, **kw)
    out = array("h")
    out.frombytes(pcm)
    return out[0::2], out[1::2], stats


def _writes(seq, bank, kind=None, **kw):
    log, stats = seq_synth.spu_writes(seq, bank, **KW, **kw)
    return [w for w in log if kind is None or w.kind == kind], stats


def _crossings(wave, start, end):
    return sum(1 for i in range(start, end - 1)
               if (wave[i] < 0) != (wave[i + 1] < 0))


QUARTER = 44100 // 4            # 240 delta ticks: 15 sound ticks


def _held(ch=0, note=60, vel=127, *, pre=(), mid=()):
    """A note held half a second (480 ticks), with events before and under
    it."""
    rest = 480 - sum(d for d, *_ in mid)
    return _seq(*pre, (0, 0x90 | ch, note, vel), *mid,
                (rest, 0x90 | ch, note, 0))


def _expected(k, vol, start=_at(0)):
    """A voice keyed at `start`, at pitch 0x1000 and full envelope, output
    sample k, after the default main volume."""
    t = k - start
    wave = HIGH if (t % 28) < 14 else LOW
    env = spu_voice.envelope(ADSR1, ADSR2, 1 << 30, t + 1)[t]
    return ((((wave * env) >> 15) * vol >> 14) * seq_synth.MASTER_VOLUME) \
        >> 14


ONE = {0: (127, 64, [_tone()])}

# -- the tick ------------------------------------------------------------------


def test_events_due_in_a_tick_reach_the_spu_together_at_the_next():
    # 16 delta ticks is one sound tick; 8 + 8 fill the first tick exactly
    seq = _seq((0, 0x90, 60, 100), (8, 0x90, 62, 100), (8, 0x90, 64, 100),
               (16, 0x90, 65, 100), (16, 0x90, 60, 0), (0, 0x90, 62, 0),
               (0, 0x90, 64, 0), (0, 0x90, 65, 0))
    ons, _ = _writes(seq, _bank(ONE), "on")
    # the reader stops a burst when the delta time read reaches the step,
    # so the note at 16 waits for the next tick
    assert [w.at for w in ons] == [_at(0), _at(0), _at(1), _at(2)]


def test_a_tempo_is_whole_beats_rounded_at_open_and_truncated_after():
    # 615000 us is 97.56 bpm: the header rounds it to 98, a tempo event
    # truncates it to 97. At 480 ticks a quarter that is a step of 131 or
    # 129 tenths; a note 4800 ticks on is read when no more than one step
    # is left.
    opened = _seq((0, 0x90, 60, 100), (4800, 0x90, 62, 100),
                  (16, 0x90, 60, 0), (0, 0x90, 62, 0), tempo=615_000)
    met = _seq((0, 0xFF, 0x51, 0x09, 0x62, 0x58), (0, 0x90, 60, 100),
               (4800, 0x90, 62, 100), (16, 0x90, 60, 0), (0, 0x90, 62, 0))
    bank = _bank(ONE)
    for seq, step in ((opened, 131), (met, 129)):
        ons, _ = _writes(seq, bank, "on")
        tick = -(-48000 // step) - 1
        assert [w.at for w in ons] == [_at(0), _at(tick)]


def test_the_score_starts_one_tick_in_and_a_quarter_is_fifteen_ticks():
    stats = seq_synth.walk(_held(), _bank(ONE), **KW)
    # the note off at 480 ticks (4800 tenths) is read on tick 29
    assert stats.ticks == 30 and stats.seconds == pytest.approx(_at(29) / 44100)


# -- voices --------------------------------------------------------------------

def test_a_key_on_and_off_in_one_tick_never_sound():
    seq = _seq((0, 0x90, 60, 100), (4, 0x90, 60, 0), (60, 0x90, 64, 1),
               (16, 0x90, 64, 0))
    ons, _ = _writes(seq, _bank(ONE), "on")
    assert [w.at for w in ons] == [_at(3)]          # only note 64
    left, _, _ = _render(seq, _bank(ONE))
    assert not any(left[:_at(3)])


def test_the_twenty_fifth_voice_steals_the_oldest():
    notes = [(0, 0x90, 30 + n, 100) for n in range(25)]
    offs = [(16 if n == 0 else 0, 0x90, 30 + n, 0) for n in range(25)]
    ons, stats = _writes(_seq(*notes, *offs), _bank(ONE), "on")
    # all 25 key-ons are in one tick: the 25th takes voice 0 back before
    # the flush, so the SPU sees 24 key-ons, voice 0 with note 54's pitch
    assert len(ons) == 24 and stats.stolen == 1 and stats.lost == 0
    first = next(w for w in ons if w.voice == 0)
    assert first.pitch == vab.note_pitch(54, 60, 0)


def test_a_tone_of_higher_priority_is_never_stolen():
    bank = _bank({0: (127, 64, [_tone(prior=5)]),
                  1: (127, 64, [_tone(prior=1)])})
    notes = [(0, 0x90, 30 + n, 100) for n in range(24)]
    seq = _seq((0, 0xC1, 1), *notes, (16, 0x91, 60, 100),
               (16, 0x91, 60, 0))
    ons, stats = _writes(seq, bank, "on")
    assert len(ons) == 24 and stats.lost == 1


def test_a_voice_keyed_in_the_last_tick_reads_silent_and_goes_first():
    # The flush reads every voice's envelope before it keys anything on, so
    # a voice keyed in the tick before reads 0 and is the cheapest victim.
    first = [(0, 0x90, 30 + n, 100) for n in range(23)]
    seq = _seq(*first, (80, 0x90, 70, 100), (16, 0x90, 72, 100),
               (16, 0x90, 70, 0))
    ons, stats = _writes(seq, _bank(ONE), "on")
    late = next(w for w in ons if w.pitch == vab.note_pitch(70, 60, 0))
    last = ons[-1]
    assert last.pitch == vab.note_pitch(72, 60, 0)
    assert last.voice == late.voice and stats.stolen == 1


def test_a_released_voice_is_reused_once_silent():
    # released on tick 1 at the fastest rate, the voice reads silent at the
    # flush after (tick 2's), and the note read on tick 3 finds it idle
    seq = _seq((0, 0x90, 60, 100), (16, 0x90, 60, 0), (48, 0x90, 62, 100),
               (16, 0x90, 62, 0))
    ons, stats = _writes(seq, _bank(ONE), "on")
    assert [w.voice for w in ons] == [0, 0] and stats.stolen == 0


# -- loops ---------------------------------------------------------------------

def _looped(count=127, after=96):
    """A loop around one half-second note; the loop end carries a delta
    time of `after` ticks before the end of the track."""
    return _seq((0, 0xB0, 99, 20), (0, 0xB0, 6, count), (0, 0x90, 60, 100),
                (480, 0x90, 60, 0), (0, 0xB0, 99, 30), (after, 0xFF, 0x2F, 0),
                end=False)


def test_an_endless_loop_plays_the_asked_passes_then_goes_on():
    for passes in (1, 2, 3):
        stats = seq_synth.walk(_looped(), _bank(ONE), passes=passes, **KW)
        assert stats.notes == passes and stats.passes == passes
    stats = seq_synth.walk(_looped(), _bank(ONE), passes=2, **KW)
    # a pass is the 480-tick body, 30 sound ticks: the jump drops the loop
    # end's own delta time
    start, end = stats.loop
    assert end - start == 30 * TICK
    # going on past the last pass, that delta time is played: 96 ticks,
    # six sound ticks to the end of the track
    assert stats.seconds * 44100 == pytest.approx(end + 6 * TICK)


def test_the_last_pass_loops_into_itself():
    _, _, stats = _render(_looped(), _bank(ONE), passes=2)
    ons, _ = _writes(_looped(), _bank(ONE), "on", passes=2)
    start, end = stats.loop
    assert [w.at for w in ons] == [_at(0), start]
    assert end == start + 30 * TICK


def _jumps_back(marks):
    return [(a, b) for a, b in zip(marks, marks[1:])
            if a[0] == b[0] and b[1] < a[1]]


def test_a_counted_loop_plays_its_count():
    stats = seq_synth.walk(_looped(count=3), _bank(ONE), passes=2, **KW)
    assert stats.notes == 3 and stats.loop is None and stats.passes == 0
    # the time map goes back to the loop start at each of the two jumps
    assert [(a[1], b[1]) for a, b in _jumps_back(stats.marks)] == \
        [(480, 0)] * 2


def test_the_time_map_jumps_back_at_each_pass():
    stats = seq_synth.walk(_looped(), _bank(ONE), passes=3, **KW)
    start, _ = stats.loop
    assert [a[0] for a, _ in _jumps_back(stats.marks)] == \
        [start - 30 * TICK, start]
    assert stats.marks[0] == (_at(0), 0)
    assert stats.marks[-1] == (stats.seconds * 44100, 480 + 96)


def test_the_end_of_the_track_keys_every_voice_off():
    seq = _seq((0, 0x90, 60, 100), (0, 0x90, 64, 100), (480, 0xB0, 7, 127))
    offs, _ = _writes(seq, _bank(ONE), "off")
    assert sorted(w.voice for w in offs) == [0, 1]


# -- the reader ----------------------------------------------------------------

def test_a_note_off_status_only_sets_the_channel():
    # 81 3E 64 reads as a note-on of key 62 on channel 1 under the running
    # 0x90: libsnd's reader has no case for 0x80
    bank = _bank({0: (127, 64, [_tone()]), 1: (127, 64, [_tone(center=48)])})
    seq = _seq((0, 0x90, 60, 100), (240, 0x81, 62, 100), (240, 0x90, 60, 0),
               (0, 0x91, 62, 0))
    ons, stats = _writes(seq, bank, "on")
    assert stats.notes == 2
    assert ons[1].pitch == vab.note_pitch(62, 48, 0)


def test_walk_counts_what_render_keys():
    bank = _bank({0: (127, 64, [_tone(lo=0, hi=70), _tone(lo=50, hi=127)])})
    seq = _seq((0, 0x90, 60, 100), (0, 0x90, 20, 100), (0, 0x90, 90, 100),
               (240, 0x90, 60, 0), (0, 0x90, 20, 0), (0, 0x90, 90, 0))
    walked = seq_synth.walk(seq, bank, **KW)
    _, _, rendered = _render(seq, bank)
    for name in ("notes", "voices", "layered", "dropped"):
        assert getattr(walked, name) == getattr(rendered, name)
    assert (walked.notes, walked.voices, walked.layered) == (3, 4, 1)


# -- pitch -------------------------------------------------------------------

def test_key_on_clamps_the_fine_tune_and_bends_do_not():
    assert vab.note_pitch(60, 60, 200) == vab.pitch_from_note(60, 0, 60, 127)
    tone = vab.Tone(0, 0, 0, 0, 127, 64, 60, 200, 0, 127, 0, 0, 0, 0,
                    0, 0, ADSR1, ADSR2, 0, 1)
    bent = seq_synth.bend_pitch(tone, 60, 64)
    assert bent == vab.pitch_from_note(60, 0, 60, 200)
    assert bent != vab.note_pitch(60, 60, 200)


def test_a_note_two_octaves_up_plays_at_the_maximum():
    ons, _ = _writes(_held(note=90), _bank(ONE), "on")
    assert ons[0].pitch == vab.PITCH_MAX


# -- tone selection ----------------------------------------------------------

def test_every_tone_in_range_sounds():
    bank = _bank({0: (127, 64, [_tone(lo=0, hi=70), _tone(lo=50, hi=127),
                                _tone(lo=80, hi=90)])})
    ons, stats = _writes(_held(note=60), bank, "on")
    assert len(ons) == 2
    assert (stats.notes, stats.voices, stats.layered) == (1, 2, 1)


def test_a_note_no_range_holds_is_silent():
    bank = _bank({0: (127, 64, [_tone(lo=0, hi=40)])})
    left, right, stats = _render(_held(note=60), bank)
    assert stats.dropped == 1 and stats.voices == 0
    assert not any(left) and not any(right)


def test_only_the_programs_declared_tones_are_searched():
    # The second slot's range holds the note, but ProgAtr.tones says 1.
    bank = _bank({0: (127, 64, [_tone(lo=0, hi=40), _tone()])})
    bank.programs[0] = replace(bank.programs[0], tones=1)
    ons, stats = _writes(_held(note=60), bank, "on")
    assert not ons and stats.dropped == 1


def test_channels_start_on_their_own_program():
    bank = _bank({0: (127, 64, [_tone(center=60)]),
                  3: (127, 64, [_tone(center=48)])})
    ons, _ = _writes(_held(ch=3), bank, "on")
    assert ons[0].pitch == 0x2000              # program 3's tone, not 0's


def test_programs_map_to_their_slot_among_used_programs():
    bank = _bank({2: (127, 64, [_tone(center=60)]),
                  7: (127, 64, [_tone(center=72)])})
    ons, _ = _writes(_held(pre=[(0, 0xC0, 7)]), bank, "on")
    assert ons[0].pitch == 0x800               # program 7 = tone block 1


# -- key-off -----------------------------------------------------------------

def test_a_struck_held_note_keeps_sounding_until_its_note_off():
    seq = _seq((0, 0x90, 60, 100), (64, 0x90, 60, 100), (64, 0x90, 60, 0))
    log, _ = _writes(seq, _bank(ONE))
    ons = [w for w in log if w.kind == "on"]
    offs = [w for w in log if w.kind == "off"]
    assert [w.voice for w in ons] == [0, 1]
    # both voices are released by the one note off, in one flush
    assert sorted(w.voice for w in offs) == [0, 1]
    assert offs[0].at == offs[1].at == _at(7)


def test_note_off_goes_by_program_not_channel():
    # channel 1 on program 0 releases channel 0's note 60
    seq = _seq((0, 0xC1, 0), (0, 0x90, 60, 100), (240, 0x91, 60, 0),
               (240, 0x90, 60, 0))
    offs, _ = _writes(seq, _bank(ONE), "off")
    assert offs[0].at == _at(14) == QUARTER


# -- pitch bend --------------------------------------------------------------

def test_bend_math_follows_the_tones_range():
    t = _bank({0: (127, 64, [_tone(pbmin=2, pbmax=12)])}).tones[0]
    p = vab.pitch_from_note
    assert seq_synth.bend_pitch(t, 60, 127) == p(72, 0, 60, 0)   # +63/63
    assert seq_synth.bend_pitch(t, 60, 96) == p(66, 12, 60, 0)   # 32*12/63
    # down: note + bend*pbmin/64 - 1, fine + 127
    assert seq_synth.bend_pitch(t, 60, 0) == p(57, 127, 60, 0)
    flat = _bank(ONE).tones[0]
    assert seq_synth.bend_pitch(flat, 60, 127) == p(60, 0, 60, 0)
    assert seq_synth.bend_pitch(flat, 60, 0) == p(59, 127, 60, 0)


def test_a_bend_moves_the_note_already_sounding():
    bank = _bank({0: (127, 64, [_tone(pbmax=12)])})
    # bend up an octave a quarter second into a half-second note
    seq = _held(mid=[(240, 0xE0, 0, 127)])
    left, _, _ = _render(seq, bank)
    # struck on tick 0, bent on tick 14, released on tick 29
    span = _at(14) - _at(0) - 2000
    before = _crossings(left, _at(0) + 1000, _at(14) - 1000)
    after = _crossings(left, _at(14) + 1000, _at(14) + 1000 + span)
    assert before / span == pytest.approx(2 / 28, rel=0.02)
    assert after == pytest.approx(2 * before, rel=0.02)


def test_a_note_struck_under_a_bend_starts_unbent():
    bank = _bank({0: (127, 64, [_tone(pbmax=12)])})
    log, _ = _writes(_held(pre=[(0, 0xE0, 0, 127)]), bank)
    assert {w.pitch for w in log if w.kind in ("on", "set")} == {0x1000}


def test_a_bend_reaches_every_channel_on_the_program():
    bank = _bank({0: (127, 64, [_tone(pbmax=12)])})
    seq = _seq((0, 0xC1, 0), (0, 0x90, 60, 100), (0, 0x91, 64, 100),
               (64, 0xE0, 0, 127), (64, 0x90, 60, 0), (0, 0x91, 64, 0))
    sets, _ = _writes(seq, bank, "set")
    bent = {w.voice: w.pitch for w in sets if w.at == _at(3)}
    assert bent == {0: vab.pitch_from_note(72, 0, 60, 0),
                    1: vab.pitch_from_note(76, 0, 60, 0)}


def test_rpn_zero_sets_the_bend_range():
    seq = _held(pre=[(0, 0xB0, 101, 0), (0, 0xB0, 100, 0), (0, 0xB0, 6, 12)],
                mid=[(64, 0xE0, 0, 127)])
    sets, _ = _writes(seq, _bank(ONE), "set")
    assert sets[-1].pitch == vab.pitch_from_note(72, 0, 60, 0)


# -- volume ------------------------------------------------------------------

def test_volume_law_full_scale_and_squared():
    full = seq_synth.spu_volume(127, 127, 127, 127, (127, 127), (64,) * 3)
    assert full == (0x3FFF, 0x3FFF)
    half = seq_synth.spu_volume(64, 127, 127, 127, (127, 127), (64,) * 3)
    linear = 64 * 129                          # 127 * 129 == 0x3FFF
    assert half == (linear * linear // 16383,) * 2
    # a score volume scales before the square
    s = seq_synth.spu_volume(127, 127, 127, 127, (0x50, 0x50), (64,) * 3)
    v = 0x3FFF * 0x50 // 127
    assert s == (v * v // 16383,) * 2


def test_volume_law_pans_scale_one_side_each():
    v = seq_synth.spu_volume
    assert v(127, 127, 127, 127, (127, 127), (64, 64, 0)) == (0x3FFF, 0)
    assert v(127, 127, 127, 127, (127, 127), (64, 64, 127)) == (0, 0x3FFF)
    r = 0x3FFF * 32 // 63
    assert v(127, 127, 127, 127, (127, 127), (32, 64, 64)) == \
        (0x3FFF, r * r // 16383)
    # the three pans compound
    r2 = r * 32 // 63
    assert v(127, 127, 127, 127, (127, 127), (32, 32, 64))[1] == \
        r2 * r2 // 16383
    # mono: both sides take the louder before the square
    assert v(127, 127, 127, 127, (127, 127), (64, 64, 0), mono=True) == \
        (0x3FFF, 0x3FFF)


def test_rendered_samples_follow_the_volume_law():
    left, right, _ = _render(_held(vel=100), _bank(ONE))
    vol = seq_synth.spu_volume(100, 127, 127, 127, (127, 127), (64,) * 3)[0]
    assert not any(left[:_at(0)])
    for k in (5, 100, 1003, 9000):
        k += _at(0)
        assert left[k] == right[k] == _expected(k, vol)


def test_the_main_volume_scales_the_mix():
    seq = _held(vel=100)
    full, _, _ = _render(seq, _bank(ONE), master_volume=0x4000)
    half, _, _ = _render(seq, _bank(ONE), master_volume=0x2000)
    k = _at(0) + 1003
    assert half[k] == full[k] >> 1 and full[k]


def test_cc7_relevels_a_sounding_note():
    seq = _held(mid=[(240, 0xB0, 7, 64)])
    left, _, _ = _render(seq, _bank(ONE), score_volume=(127, 127))
    full = seq_synth.spu_volume(127, 127, 127, 127, (127, 127), (64,) * 3)[0]
    after = seq_synth.spu_volume(127 * 64 // 127, 127, 127, 127, (127, 127),
                                 (64,) * 3)[0]
    change = _at(14)                           # 240 ticks in
    assert left[change - 7] == _expected(change - 7, full)
    assert left[change + 7] == _expected(change + 7, after)


def test_cc10_pans_a_sounding_note_and_cc11_sets_the_program_volume():
    seq = _seq((0, 0xC1, 0), (0, 0x90, 60, 127), (64, 0xB0, 10, 0),
               (64, 0xB0, 11, 64), (0, 0x91, 64, 127), (64, 0x90, 60, 0),
               (0, 0x91, 64, 0))
    log, _ = _writes(seq, _bank(ONE))
    pan = next(w for w in log if w.kind == "set" and w.at == _at(3))
    # pan 0 counts as 1
    assert pan.vol == seq_synth.spu_volume(127, 127, 127, 127, (127, 127),
                                           (64, 64, 1))
    # CC11 is the program's volume: a later note on another channel has it
    second = [w for w in log if w.kind == "on"][1]
    assert second.vol == seq_synth.spu_volume(127, 127, 64, 127, (127, 127),
                                              (64, 64, 64))


def test_the_damper_slows_the_release_of_notes_struck_under_it():
    bank = _bank({0: (127, 64, [_tone(adsr2=0x0005)])})
    seq = _held(pre=[(0, 0xB0, 64, 127)])
    ons, _ = _writes(seq, bank, "on")
    assert ons[0].adsr == (ADSR1, 0x0007)
    ons, _ = _writes(_held(pre=[(0, 0xB0, 64, 0)]), bank, "on")
    assert ons[0].adsr == (ADSR1, 0x0005)


# -- length --------------------------------------------------------------------

def test_a_long_note_is_not_cut():
    # 120 ticks of 1/6 s: a note held 20 seconds
    seq = _seq((0, 0x90, 60, 127), (120, 0x90, 60, 0),
               resolution=12, tempo=2_000_000)
    left, _, stats = _render(seq, _bank(ONE), rate=4410)
    assert stats.seconds == pytest.approx(20.0, abs=2 / 60)
    assert any(left[15 * 4410:15 * 4410 + 100])


def test_pure_python_mixer_matches_numpy(monkeypatch):
    if spu_voice.np is None:
        pytest.skip("numpy not installed")
    bank = _bank({0: (127, 64, [_tone(pbmin=2, pbmax=7, lo=0, hi=70),
                                _tone(lo=60, hi=127, pan=20)])})
    seq = _seq((0, 0x90, 60, 110), (30, 0xE0, 0, 100), (30, 0xB0, 7, 90),
               (0, 0x90, 67, 80), (30, 0xB0, 10, 30), (30, 0xE0, 0, 10),
               (60, 0x90, 60, 0), (30, 0x90, 67, 0))
    fast, _ = seq_synth.render(seq, bank, **KW)
    monkeypatch.setattr(spu_voice, "np", None)
    monkeypatch.setattr(seq_synth, "np", None)
    slow, _ = seq_synth.render(seq, bank, **KW)
    assert slow == fast


# -- playing live --------------------------------------------------------------

def _song():
    """An intro note, an endless loop of two notes (one sent to the reverb,
    ringing past the loop end), and an ending note."""
    return _seq((0, 0x90, 48, 100), (240, 0x90, 48, 0),
                (0, 0xB0, 99, 20), (0, 0xB0, 6, 127),
                (0, 0x90, 60, 100), (120, 0x91, 67, 90), (120, 0x90, 60, 0),
                (240, 0xB0, 99, 30), (0, 0x91, 67, 0),
                (0, 0x90, 72, 100), (240, 0x90, 72, 0))


def _song_bank():
    from decoders.psx.formats.tests.test_spu_reverb import _preset
    bank = _bank({0: (127, 64, [_tone(adsr2=0x0008)]),
                  1: (127, 40, [_tone(adsr2=0x0004, mode=seq_synth.TONE_REVERB,
                                      pan=90)])})
    from decoders.psx.formats.spu_reverb import ReverbSetting
    return bank, ReverbSetting(_preset(), 0x3000, 0x2800)


def _player(passes=None, reverb=True):
    bank, setting = _song_bank()
    return seq_synth.Player(_song(), bank, passes=passes,
                            reverb=setting if reverb else None, **KW)


def _read_all(player, sizes):
    out, i = [], 0
    while chunk := player.read(sizes[i % len(sizes)]):
        out.append(chunk)
        i += 1
    return b"".join(out)


def test_played_in_pieces_it_is_the_render_sample_for_sample():
    pytest.importorskip("numpy")
    bank, setting = _song_bank()
    for reverb in (setting, None):
        whole, stats = seq_synth.render(_song(), bank, passes=3,
                                        reverb=reverb, **KW)
        for sizes in ([1], [735], [999, 17, 44100], [1 << 20]):
            if sizes == [1] and reverb is None:
                continue                    # slow, and the reverb case has it
            played = _read_all(_player(3, reverb is not None),
                               sizes if sizes != [1] else [1, 5000])
            assert played == whole
    assert stats.passes == 3 and stats.reverb_notes


def test_an_endless_loop_never_ends_while_it_loops():
    player = _player()
    second = 44100
    for _ in range(12):
        assert len(player.read(second)) == 4 * second
    # a pass is 480 delta ticks: 30 sound ticks, half a second
    assert not player.ended and len(player.reader.jumps) >= 22
    assert player.reader.went_on is None


def test_with_the_loop_off_the_score_ends_after_the_current_pass():
    pytest.importorskip("numpy")
    bank, setting = _song_bank()
    player = _player()
    _, second_end = seq_synth.walk(_song(), bank, passes=2, **KW).loop
    played = player.read(second_end + 5000)                 # into pass 3
    assert len(player.reader.jumps) == 2
    player.set_looping(False)
    played += _read_all(player, [4410])
    # what was played is the score with its loop played three times
    whole, _ = seq_synth.render(_song(), bank, passes=3, reverb=setting, **KW)
    assert played == whole and player.ended
    assert player.reader.went_on == player.reader.jumps[-1]


def test_switching_the_loop_back_on_keeps_it_looping():
    player = _player()
    player.read(int(1.5 * 30 * TICK))
    player.set_looping(False)
    player.set_looping(True)
    player.read(10 * 30 * TICK)
    assert not player.ended and player.reader.went_on is None


def test_the_loop_switch_holds_from_the_tick_heard_at_a_frame():
    """Thrown off for output frame F on, the switch decides the first loop
    end heard at F or after; the ones heard before it jump back."""
    player = _player()
    for frame in (0, 1, TICK - 1, TICK, TICK + 1, 12345):
        tick = player.tick_for(frame)
        assert player.at(tick) >= frame
        assert tick == 0 or player.at(tick - 1) < frame
    frame = 3 * 30 * TICK + 100                     # in the fourth pass
    player.read(frame - 30 * TICK)                  # a pass short of it
    player.set_looping(False, frame)
    _read_all(player, [4410])
    r = player.reader
    assert player.ended and r.went_on == r.jumps[-1]
    assert player.at(r.went_on) >= frame
    assert all(player.at(j) < frame for j in r.jumps[:-1])


def test_a_seek_replays_without_output_and_goes_on_as_straight_play():
    target = 4 * 30 * TICK + 4321                           # in pass 4
    straight = _player().read(target + 44100)[4 * target:]
    sought = _player()
    assert sought.skip(target) == target
    assert sought.read(44100) == straight
    # and from a copy of the state taken on the way
    on = _player()
    on.read(30 * TICK)
    copy = on.snapshot()
    copy.skip(target - 30 * TICK)
    assert copy.read(44100) == straight


def test_the_first_pass_and_the_jumps_are_where_the_reader_met_them():
    stats = seq_synth.walk(_song(), _song_bank()[0], passes=2, **KW)
    # the loop body begins with the intro note's off, 240 ticks in: read on
    # tick 14 (the loop start marker carries no delta of its own)
    assert stats.first_pass == _at(14)
    # the first pass ends 30 sound ticks on, the second 30 after that
    start, end = stats.loop
    assert start == _at(44) and end == _at(74)


def test_a_score_of_noise_tones_says_so_once():
    bank = _bank({0: (127, 64, [_tone(vag_no=seq_synth.NOISE_VAG)])})
    seq = _seq(*[(d, 0x90, 60 + k, 100) for k, d in enumerate((0, 30, 30, 30))],
               (30, 0x90, 60, 0))
    _left, _right, stats = _render(seq, bank)
    assert stats.warnings.count(seq_synth.NOISE_WARNING) == 1

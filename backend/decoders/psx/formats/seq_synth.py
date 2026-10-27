"""Render a SEQ sequence to audio using its own VAB bank.

This is libsnd (PSY-Q 4.5, the matched C in the decomp's `libsnd_*.c`)
playing a score on an offline SPU (`spu_voice`). It runs on libsnd's own
clock: once a sound tick the score reader takes the events that are due,
its handlers drive the voice manager, and the voice manager's flush at the
start of the next tick sends what changed to the SPU. The result is the
music played with its own instruments, at its own timing: no soundfont, no
substitution, no MIDI clock.

What is transcribed from libsnd:

* **The tick** — `_SsSeqPlay` (0x80098998): delta times are counted in
  tenths of a tick (`_SsReadDeltaValue` (0x80097B98)); each sound tick
  takes `tick_step` tenths, which `_SsInitSoundSeq` (0x80097C48) and
  `_SsGetMetaEvent` (0x80097878) derive from the resolution, the tempo in
  whole beats per minute (rounded at open, truncated at a tempo event) and
  VBLANK_MINUS (60). Events whose time has come are read in a burst, and
  what they change reaches the SPU at the next tick's `_SsVmFlush`
  (0x8009A258).
* **The reader** — `_SsGetSeqData` (0x80098CD8) and the handlers: see
  `seq.parse_seq` for the byte rules. Controllers 6, 7, 10, 11, 64, 98, 99,
  100, 101 and 121 are played; a program change sets the channel's program.
* **Loops** — the NRPN loop: CC99 20 marks the loop start (after its delta
  time), the next CC6 is the count, CC99 30 is the loop end
  (`_SsContNrpn2` (0x80096698), `_SsContDataEntry` (0x80095E48)). A count
  of 127 or more loops for ever: the jump drops the loop end's delta time.
  The end of the track keys every voice off (`_SsSeqGetEof` (0x80098A94),
  `_SsVmSeqKeyOff` (0x8009CE38)); scores are played once
  (`SsSeqPlay(seq, 1, 1)`).
* **Playing** — `Player` runs all of that a piece at a time, holding only
  the state of the moment, so an endless loop plays for ever as the game
  plays it; `render` is a `Player` read to the end.
* **Voices** — `_SsVmKeyOn` (0x8009AA78) keys EVERY tone of the program
  whose key range holds the note (`_SsVmSelectToneAndVag` (0x8009CEE8)),
  each on the voice `_SsVmAlloc` (0x8009B228) picks among the 24: an idle
  one, or the one of lowest priority, then lowest envelope level (as the
  last flush read it), then greatest age. `_SsVmKeyOff` (0x8009AF94)
  releases every voice of the score still on record with that program and
  note. `_SsVmFlush` frees a voice whose envelope read silent in its
  history ring's slots 0-14, cancels a key-on whose voice was keyed off in
  the same tick, then writes registers, key-offs and key-ons.
* **Pitch** — `SsPitchFromNote` (0x8009B71C) via `vab.note_pitch`; bends
  re-pitch the program's voices by each tone's own range (`_SsVmPitchBend`
  (0x8009C574), `_SsVmPBVoice` (0x8009C388)).
* **Volume and pan** — `_SsVmKeyOnNow` (0x8009BEB8) at key-on and
  `_SsVmSetVol` (0x8009CFB8) when CC7, CC10 or CC11 changes: velocity x
  channel volume, x the bank, program and tone volumes, x the score volume,
  three pans, squared / 0x3FFF.

What is the SPU's is in `spu_voice`. What is approximated is in FIDELITY,
which the asset viewer prints beside every rendered sequence.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field, replace
from fractions import Fraction

from decoders.psx.formats.seq import IGNORED_STATUSES, META_END, Seq
from decoders.psx.formats.spu_voice import (
    VOICES, Mixer, Play, np,
)
from decoders.psx.formats.vab import (
    SPU_BASE_RATE, Vab, _cdiv, _cmod, note_pitch, pitch_from_note,
)

__all__ = ["render", "walk", "spu_writes", "spu_volume", "bend_pitch",
           "Player", "tail_frames", "RenderStats", "SpuWrite",
           "NTSC_FIELD_HZ", "FIDELITY", "fidelity_lines"]

#: (aspect, exact?, what) — the fidelity statement, in one place so the
#: module docstring and anything that SHOWS the renderer's output cannot
#: drift apart. The asset viewer prints this next to every rendered
#: sequence: someone listening deserves to know which parts of what they
#: hear are the game's and which are ours, and an approximation is only
#: honest while it is visible.
FIDELITY = (
    ("timing", True,
     "libsnd's _SsSeqPlay (0x80098998): the score is read once a sound "
     "tick, delta times counted in tenths against VBLANK_MINUS 60, the tempo "
     "in whole beats per minute (rounded at open, truncated at a tempo "
     "event); a tick's changes reach the SPU at the next tick's _SsVmFlush "
     "(0x8009A258)"),
    ("loop points", True,
     "the NRPN loop (CC99 20, a CC6 count, CC99 30) as _SsContNrpn2 "
     "(0x80096698) plays it; the end of the track keys every voice off"),
    ("voices", True,
     "24 voices; _SsVmAlloc (0x8009B228) takes an idle voice or steals by "
     "priority, envelope level and age, by the levels the flush reads each "
     "tick; a voice silent in 15 readings is freed; a key-on and key-off of "
     "one voice in one tick cancel as the flush orders them"),
    ("tone selection", True,
     "libsnd's _SsVmSelectToneAndVag (0x8009CEE8): every tone of the "
     "program whose key range holds the note sounds; a note no range holds "
     "is silent"),
    ("pitch", True,
     "libsnd's SsPitchFromNote (0x8009B71C): 12 semitone x 128 fine ratio "
     "tables, the octave shift with rounding, 0x3FFF from two octaves above "
     "the centre"),
    ("pitch bend", True,
     "libsnd's _SsVmPitchBend (0x8009C574): re-pitches the program's voices "
     "by each tone's own bend range; a struck note starts unbent; RPN 0 "
     "sets the range"),
    ("volume and pan", True,
     "libsnd's _SsVmKeyOnNow (0x8009BEB8) and _SsVmSetVol (0x8009CFB8): "
     "velocity x channel x bank, program, tone and score volumes, three "
     "linear pans / 63, squared / 0x3FFF; CC7, CC10 and CC11 re-level "
     "sounding voices; the damper (CC64) slows releases"),
    ("ADSR", True,
     "the SPU envelope: 15-bit level, rate counter from the key-on, linear "
     "and exponential modes, the >=0x6000 attack slowdown"),
    ("sample loops", True,
     "real loop points sustain; one-shots play once, as the flags say"),
    ("main volume", True,
     "the SPU main volume the program sets, over the whole mix"),
    ("tick rate", False,
     "one tick per vertical blank at the NTSC field rate of a "
     "non-interlaced screen, 53.693175 MHz / 3413 / 263 = 59.817 Hz (the "
     "GPU's video clock); an interlaced screen ticks at 59.94 Hz"),
    ("endless loops", True,
     "played live, a loop end jumps back for ever as the game's does, and "
     "the voices ring on through the jump; with the loop switched off the "
     "score goes on to its ending at the next loop end. An export renders "
     "a chosen number of passes, then the ending"),
    ("tick phase", False,
     "where the flush's 16-slot silence history stands when the score "
     "starts is not known; it is taken as slot 0"),
    ("not played", False,
     "CC0 (bank change), CC91 (reverb depth), CC121's reverb off, NRPN "
     "tone attributes, noise tones (VAG 0xFF), and the sound effects that "
     "share the voices in the game"),
    ("reverb", False,
     "the SPU reverb network over the program's own preset and depth (read "
     "from its EXE and code by its records package; the setting used is "
     "shown with the render), fed by voices whose tone's VagAtr.mode has "
     "bit 2; float math and linear 22.05 kHz resampling, not 16-bit fixed "
     "point and the 39-tap FIR — and only when a reverb setting is given"),
    ("mixing", False,
     "voices summed at their SPU volumes and clipped once at 16 bits, then "
     "the main volume"),
    ("interpolation", False, "linear, not the SPU's 4-tap Gaussian"),
)


def fidelity_lines() -> list[str]:
    """The fidelity statement as display lines: exact first, then ours."""
    out = []
    for group, label in ((True, "the game's own"), (False, "ours")):
        rows = [(a, w) for a, ex, w in FIDELITY if ex is group]
        if not rows:
            continue
        out.append(f"{label}:")
        width = max(len(a) for a, _ in rows)
        for aspect, what in rows:
            out.append(f"  {aspect.ljust(width)}  {what}")
    return out


#: libsnd's score volume when nothing sets it (`SsSetTableSize` (0x800993C8)
#: and `SsSeqClose` (0x800958D4) reset both sides to 127). A program that
#: calls `SsSeqSetVol` (0x800997C8) passes its own to `render`.
SCORE_VOLUME = (127, 127)

#: The SPU main volume `_SsInit` (0x800959D8) writes; a program that sets
#: its own passes it to `render`.
MASTER_VOLUME = 0x3FFF

#: libsnd's VBLANK_MINUS: the ticks a second the tempo arithmetic assumes
#: (`_SsInit` (0x800959D8); `SsSetTickMode` (0x800995E8) keeps 60 for an
#: NTSC vertical-blank tick).
VBLANK_MINUS = 60

#: The rate the tick actually runs at on an NTSC console with a
#: non-interlaced screen: one field of 263 lines of 3413 clocks of the
#: GPU's 53.693175 MHz video clock.
NTSC_FIELD_HZ = Fraction(53_693_175, 3413 * 263)

#: Channel state at the start of a score (`_SsInitSoundSeq` (0x80097C48)).
CHANNEL_VOLUME = 0x7F
CHANNEL_PAN = 0x40

#: Low byte of a VAG number that libsnd keys as the noise generator.
NOISE_VAG = 0xFF
#: What a score that keys one says, once.
NOISE_WARNING = "noise tones are not played"

#: `_SsVmInit` (0x8009A728): programs a VAB can address.
MAX_PROGRAMS = 128

#: A score that reads this many events in one tick never moves on (an
#: endless loop around nothing would hang libsnd); stop it.
READS_PER_TICK = 1 << 16

#: An hour of ticks: a score still playing then is stopped.
MAX_TICKS = 60 * 60 * 60

#: Extra tail while reverb is on, so the decay is not cut at the end.
REVERB_TAIL_SECONDS = 2.0

#: VagAtr.mode bit that routes a tone into the reverb (LIBREF: "4: reverb").
TONE_REVERB = 0x04


# ---------------------------------------------------------------------------
# libsnd's arithmetic
# ---------------------------------------------------------------------------

def spu_volume(note_vol: int, bank_vol: int, prog_vol: int, tone_vol: int,
               score_volume: tuple[int, int], pans,
               mono: bool = False) -> tuple[int, int]:
    """The SPU voice volume pair libsnd writes (0..0x3FFF each).

    `_SsVmKeyOnNow` (0x8009BEB8) and `_SsVmSetVol` (0x8009CFB8) share it:
    `note_vol` (velocity x channel volume / 127) x the bank's master volume
    x 0x3FFF / 16129, x the program's and the tone's volume / 16129, split
    by the score's left and right volume / 127; then each pan in `pans`
    (tone, program, channel) scales the right side by pan / 63 below 64 and
    the left by (127 - pan) / 63 from 64; in mono both sides take the
    louder; and each side is squared / 16383.
    """
    vl = note_vol * (bank_vol * 0x3FFF) // 16129
    vl = vl * prog_vol * tone_vol // 16129
    vr = vl * score_volume[1] // 127
    vl = vl * score_volume[0] // 127
    for pan in pans:
        if pan < 64:
            vr = vr * pan // 63
        else:
            vl = vl * (127 - pan) // 63
    if mono:
        vl = vr = max(vl, vr)
    return vl * vl // 16383, vr * vr // 16383


def bend_pitch(tone, note: int, value: int) -> int:
    """The pitch `_SsVmPBVoice` (0x8009C388) gives a sounding voice for a
    bend's high byte (`value`, 64 = centre): the bend scaled by the tone's
    range into whole notes and 1/128ths, then `note2pitch2` (0x8009B6B4) —
    which, unlike a key-on, passes the tone's fine tune through unclamped."""
    bend = value - 64
    if bend > 0:
        note += bend * tone.pbmax // 63
        fine = (bend * tone.pbmax % 63) * 2
    elif bend < 0:
        note = note + _cdiv(bend * tone.pbmin, 64) - 1
        fine = _cmod(bend * tone.pbmin, 64) * 2 + 127
    else:
        fine = 0
    return pitch_from_note(note, fine, tone.center, tone.shift)


def _bpm(us: int, rounded: bool) -> int:
    """Whole beats per minute from microseconds per quarter: rounded to
    nearest at open (`_SsInitSoundSeq`), truncated at a tempo event
    (`_SsGetMetaEvent`)."""
    bpm = 60_000_000 // us
    if rounded and us // 2 < 60_000_000 % us:
        bpm += 1
    return bpm


# ---------------------------------------------------------------------------
# What a render reports
# ---------------------------------------------------------------------------

@dataclass
class RenderStats:
    notes: int = 0              # note-ons that keyed at least one tone
    voices: int = 0             # tones keyed (a layered note keys several)
    layered: int = 0            # note-ons that keyed more than one tone
    dropped: int = 0            # note-ons no tone's key range holds
    stolen: int = 0             # key-ons that took a voice still sounding
    lost: int = 0               # tones that found no voice
    voices_max: int = 0         # most voices sounding at one tick
    peak: int = 0
    clipped: int = 0
    seconds: float = 0.0        # until the last tick the score played
    end: int = 0                # output sample of the last tick's flush
    ticks: int = 0              # sound ticks the score played
    tick_hz: float = 0.0
    passes: int = 0             # passes of an endless loop played
    #: (start, end) output samples of the last pass of an endless loop:
    #: playing them over and over continues the music as the game does
    loop: tuple[int, int] | None = None
    #: output sample where the endless loop's first pass begins (the
    #: intro is what comes before it)
    first_pass: int | None = None
    #: (output sample, score tick) where the time map bends: the start,
    #: tempo changes, loop jumps (two marks at one sample) and the end
    marks: list[tuple[int, int]] = field(default_factory=list)
    reverb_notes: int = 0       # key-ons routed to the reverb
    reverb: str = ""            # the setting used, "" when off
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The score: libsnd's reader
# ---------------------------------------------------------------------------

class _Reader:
    """One score as libsnd plays it: `_SsSeqPlay` (0x80098998) once per
    `tick()`, and the handlers, which drive `vm` (libsnd's voice manager's
    entry points). `passes`: how many times an endless loop is played
    before the score goes on past its end; None, for ever. It may change
    while the score plays: a loop end jumps back while fewer than `passes`
    loop ends have been met."""

    def __init__(self, seq: Seq, vm, passes: int | None,
                 vblank_minus: int = VBLANK_MINUS):
        self.events = seq.events
        self.vm = vm
        self.passes = math.inf if passes is None else max(1, passes)
        self.vblank = vblank_minus
        self.resolution = seq.resolution
        self.programs = list(range(16))
        self.vol = [CHANNEL_VOLUME] * 16
        self.pan = [CHANNEL_PAN] * 16
        self.channel = 0
        self.rpn_lsb = self.rpn_msb = self.rpn_count = 0
        self.nrpn_lsb = self.nrpn_msb = self.nrpn_count = 0
        self.loop_armed = self.loop_on = self.loop_count = 0
        self.read = self.loop_pos = 0
        self.playing = True
        self.now = 0                    # the tick being read
        self.jumps: list[int] = []      # ticks an endless loop ended in
        self.went_on: int | None = None         # ... the one gone on past
        self.loop_reached: int | None = None    # tick a loop's body began
        self.first_pass: int | None = None      # ... the endless loop's
        self.marks: list[tuple[int, int]] = [(0, 0)]
        self.warnings: set[str] = set()
        # the delta time before the first event, read with the header
        self.delta_value = (self.events[0].tick * 10 if self.events else 0)
        if not seq.tempo or not seq.resolution:
            self.warnings.add("the header's tempo or resolution is 0")
            self.playing = False
            self.tick_step = self.tick_wait = 1
            return
        self._set_step(_bpm(seq.tempo, rounded=True))

    def _set_step(self, bpm: int) -> None:
        n = self.resolution * bpm * 10
        v = self.vblank * 60
        if n == 0:
            self.warnings.add("a tempo of 0 stops the score")
            self.playing = False
            self.tick_step = self.tick_wait = 1
        elif n < v:
            self.tick_step = self.tick_wait = self.vblank * 600 // (n // 10)
        else:
            self.tick_wait = -1
            self.tick_step = n // v + (v // 2 < n % v)

    # -- _SsSeqPlay ---------------------------------------------------------

    def tick(self) -> None:
        if not self.playing:
            return
        if self.delta_value - self.tick_step > 0:
            if self.tick_wait > 0:
                self.tick_wait -= 1
            elif self.tick_wait == 0:
                self.tick_wait = self.tick_step
                self.delta_value -= 1
            else:
                self.delta_value -= self.tick_step
        else:
            delta = self.delta_value
            reads = 0
            while True:
                while True:
                    self._get()
                    reads += 1
                    if self.delta_value != 0 or reads > READS_PER_TICK:
                        break
                delta += self.delta_value
                if delta >= self.tick_step or reads > READS_PER_TICK:
                    break
            if reads > READS_PER_TICK:
                self.warnings.add("the score reads on without time passing; "
                                  "stopped")
                self.playing = False
                self.vm.seq_key_off()
            self.delta_value = delta - self.tick_step
        self.now += 1

    # -- _SsGetSeqData ------------------------------------------------------

    def _get(self) -> None:
        if self.loop_reached is None:
            self.loop_reached = self.now
        if self.read >= len(self.events):
            self._end()                 # the data ends without an end mark
            return
        ev = self.events[self.read]
        self.read += 1
        status = ev.status
        if status < 0x80:               # a data byte with no running status
            return
        if status != 0xFF:
            self.channel = status & 0x0F
        kind = status & 0xF0
        if kind in IGNORED_STATUSES:
            return
        delta = ev.delta * 10 if ev.delta else 0
        if status == 0xFF:
            if ev.data[:1] == bytes([META_END]):
                self._end()
                return
            if ev.tempo:                # _SsGetMetaEvent
                self._set_step(_bpm(ev.tempo, rounded=False))
                self.marks.append((self.now, ev.tick))
            else:
                self.warnings.add("a tempo of 0 stops the score")
                self.playing = False
            self.delta_value = delta
            return
        ch = self.channel
        prog = self.programs[ch]
        data = ev.data
        if kind == 0x90:
            self.delta_value = delta
            if len(data) < 2:
                return
            if data[1]:
                self.vm.key_on(ch, prog, data[0], data[1], self.vol[ch],
                               self.pan[ch])
            else:
                self.vm.key_off(prog, data[0])
        elif kind == 0xB0:
            if len(data) < 2:
                self.delta_value = delta
                return
            self._control(ch, prog, data[0], data[1], delta)
        elif kind == 0xC0:
            if data:
                self.programs[ch] = data[0]
            self.delta_value = delta
        elif kind == 0xE0:
            if len(data) >= 2:
                self.vm.pitch_bend(prog, data[1])
            self.delta_value = delta

    def _end(self) -> None:
        """`_SsSeqGetEof` (0x80098A94) for a score played once: it is over,
        and every voice it holds is keyed off."""
        self.playing = False
        self.loop_pos = 0
        self.vm.seq_key_off()
        self.delta_value = self.tick_step
        self.marks.append((self.now, self.events[self.read - 1].tick
                           if self.read else 0))

    def _set_vol(self, prog: int, vol: int, pan: int) -> None:
        # _SsVmSetVol lifts a channel volume of 0 to 1 when it re-levels a
        # voice
        if self.vm.set_vol(prog, vol, pan) and self.vol[self.channel] == 0:
            self.vol[self.channel] = 1

    def _control(self, ch: int, prog: int, cc: int, value: int,
                 delta: int) -> None:
        self.delta_value = delta
        if cc == 0:                     # bank change: another VAB
            self.warnings.add("CC0 (bank change) is not played")
        elif cc == 6:                   # _SsContDataEntry (0x80095E48)
            if self.loop_armed == 1 and self.loop_on == 0:
                self.loop_count = value
                self.loop_armed, self.loop_on = 0, 1
            elif self.rpn_count == 2:
                if self.rpn_msb == 0 and self.rpn_lsb == 0:
                    self.vm.bend_range(prog, value & 0x7F)
                self.rpn_count = 0
            elif self.nrpn_count == 2:
                self.warnings.add("NRPN tone attributes are not played")
                self.nrpn_count = 0
        elif cc == 7:                   # _SsContMainVol (0x800961C8)
            self._set_vol(prog, value, self.pan[ch])
            self.vol[ch] = value
        elif cc == 10:                  # _SsContPanpot (0x80096298)
            self._set_vol(prog, self.vol[ch], value)
            self.pan[ch] = value
        elif cc == 11:                  # _SsContExpression (0x80096368)
            self.vm.set_prog_vol(prog, value)
            self._set_vol(prog, self.vol[ch], self.pan[ch])
        elif cc == 64:                  # _SsContDamper (0x80096458)
            self.vm.damper(value >= 0x40)
        elif cc == 91:                  # _SsContExternal (0x80096508)
            self.warnings.add("CC91 (reverb depth) is not played")
        elif cc == 98:                  # _SsContNrpn1 (0x80096598)
            if self.nrpn_msb not in (20, 30, 40):
                self.nrpn_lsb = value
                self.loop_armed = 0
                self.nrpn_count += 1
        elif cc == 99:                  # _SsContNrpn2 (0x80096698)
            self.nrpn_msb = value
            if value == 20:
                self.loop_armed = 1
                self.loop_pos = self.read
                self.loop_reached = None
            elif value == 30:
                self._loop_end()
            else:
                self.nrpn_count += 1
        elif cc == 100:                 # _SsContRpn1 (0x800967D8)
            self.rpn_lsb = value
            self.rpn_count += 1
        elif cc == 101:                 # _SsContRpn2 (0x80096848)
            self.rpn_msb = value
            self.rpn_count += 1
        elif cc == 121:                 # _SsContResetAll (0x800968B8)
            self.warnings.add("CC121's reverb off is not played")
            self.vm.damper(False)
            self.programs[ch] = ch
            self.rpn_lsb = self.rpn_msb = 0
            self.vol[ch] = CHANNEL_VOLUME
            self.pan[ch] = CHANNEL_PAN

    def _loop_end(self) -> None:
        here = self.events[self.read - 1].tick
        start = (self.events[self.loop_pos].tick
                 if self.loop_pos < len(self.events) else here)
        if self.loop_count == 0:
            self.loop_on = 0
        elif self.loop_count < 0x7F:
            self.loop_count -= 1
            if self.loop_count:
                self.read = self.loop_pos
                self.marks += [(self.now, here), (self.now, start)]
            else:
                self.loop_on = 0
        else:
            # endless: the jump drops this event's delta time; after the
            # asked passes the score goes on instead
            if self.first_pass is None:
                self.first_pass = self.loop_reached
            self.jumps.append(self.now)
            if len(self.jumps) < self.passes:
                self.delta_value = 0
                self.read = self.loop_pos
                self.marks += [(self.now, here), (self.now, start)]
            else:
                self.loop_on = 0
                self.marks.append((self.now, here))
                if self.went_on is None:
                    self.went_on = self.now


# ---------------------------------------------------------------------------
# Tone selection, shared by the counting walk and the voice manager
# ---------------------------------------------------------------------------

class _Bank:
    """A VAB's tables as libsnd keeps them in RAM: program volumes (CC11
    writes them) and bend ranges (RPN 0 writes them) change while a score
    plays."""

    def __init__(self, vab: Vab):
        self.vab = vab
        self.prog_vol = [p.mvol for p in vab.programs]
        self.prog_pan = [p.mpan for p in vab.programs]
        self.prog_tones = [p.tones for p in vab.programs]
        self.slot = []                  # ProgAtr.reserved1
        used = 0
        for p in vab.programs:
            self.slot.append(used)
            used += p.tones != 0
        self.tones = list(vab.tones)

    def select(self, prog: int, note: int) -> list:
        """(index, tone) of each tone `_SsVmSelectToneAndVag` (0x8009CEE8)
        keys; [] when `_SsVmKeyOn` (0x8009AA78) refuses the program."""
        if not 0 <= prog < min(MAX_PROGRAMS, len(self.slot)):
            return []
        fake = self.slot[prog]
        if fake >= self.vab.ps:
            return []
        base = fake * 16
        out = []
        for i in range(self.prog_tones[prog]):
            if base + i >= len(self.tones):
                break
            t = self.tones[base + i]
            if t.min_note <= note <= t.max_note:
                out.append((i, t))
        return out

    def bend_range(self, prog: int, value: int) -> None:
        """RPN 0 through `_SsContDataEntry`: every tone of the program
        bends `value` semitones each way."""
        if not 0 <= prog < len(self.slot):
            return
        base = self.slot[prog] * 16
        for i in range(self.prog_tones[prog]):
            if base + i < len(self.tones):
                self.tones[base + i] = replace(self.tones[base + i],
                                               pbmin=value, pbmax=value)


class _Counter:
    """A voice manager that only counts what a key-on would key."""

    def __init__(self, bank: _Bank, stats: RenderStats):
        self.bank, self.stats = bank, stats

    def key_on(self, ch, prog, note, vel, chvol, pan) -> None:
        tones = self.bank.select(prog, note)
        _count(self.stats, tones)

    def set_vol(self, prog, vol, pan) -> int:
        return 0

    def set_prog_vol(self, prog, value) -> None:
        if 0 <= prog < len(self.bank.prog_vol):
            self.bank.prog_vol[prog] = value

    def bend_range(self, prog, value) -> None:
        self.bank.bend_range(prog, value)

    def key_off(self, prog, note) -> None:
        pass

    def pitch_bend(self, prog, value) -> None:
        pass

    def seq_key_off(self) -> None:
        pass

    def damper(self, on) -> None:
        pass


def _count(stats: RenderStats, tones: list) -> None:
    if not tones:
        stats.dropped += 1
        return
    stats.notes += 1
    stats.voices += len(tones)
    stats.layered += len(tones) > 1


# ---------------------------------------------------------------------------
# The voice manager
# ---------------------------------------------------------------------------

class _Rec:
    """libsnd's record of one voice (`_svm_voice`)."""

    __slots__ = ("key_stat", "envx", "age", "prior", "ours", "prog", "pg",
                 "vol", "channel", "pan", "note", "tone", "vag")

    def __init__(self):
        # as _SsVmInit (0x8009A728) leaves it
        self.key_stat, self.envx, self.age, self.prior = 0, 0, 24, 0
        self.ours = False               # seq_sep: no score yet
        self.prog = self.pg = self.vol = self.channel = self.note = 0
        self.pan, self.tone, self.vag = 0x40, 0xFF, 0xFF


class _Regs:
    """One SPU voice's registers, as libsnd last wrote them."""

    __slots__ = ("vol", "pitch", "vag", "adsr", "rev", "dirty")

    def __init__(self):
        self.vol, self.pitch, self.vag = (0, 0), 0x1000, 0
        self.adsr = (0x80FF, 0x4000)
        self.rev = False
        self.dirty = 0


class _VoiceManager:
    """libsnd's voice manager for one score, writing to the SPU voices."""

    def __init__(self, bank: _Bank, spu: "_Spu", score_volume, mono: bool,
                 stats: RenderStats):
        self.bank, self.spu, self.stats = bank, spu, stats
        self.score_volume = tuple(min(127, v) for v in score_volume)
        self.mono = mono
        self.recs = [_Rec() for _ in range(VOICES)]
        self.regs = [_Regs() for _ in range(VOICES)]
        self.okon = self.okof = self.orev = 0
        self.damper_add = 0
        self.hist = [0] * 16
        self.hist_ptr = 0

    # -- _SsVmKeyOn and what it calls ----------------------------------------

    def key_on(self, ch, prog, note, vel, chvol, pan) -> None:
        tones = self.bank.select(prog, note)
        _count(self.stats, tones)
        note_vol = vel * chvol // 127
        for index, tone in tones:
            v = self._alloc(tone.prior)
            if v >= VOICES:
                self.stats.lost += 1
                continue
            rec = self.recs[v]
            if rec.key_stat or rec.envx:
                self.stats.stolen += 1
            rec.key_stat, rec.age, rec.ours = 1, 0, True
            rec.prog, rec.pg = self.bank.slot[prog], prog
            rec.vol, rec.channel, rec.pan = vel, ch, pan
            rec.tone, rec.note, rec.prior = index, note, tone.prior
            rec.vag = tone.vag & 0xFF
            self._do_allocate(v, tone)
            if rec.vag == NOISE_VAG:
                if NOISE_WARNING not in self.stats.warnings:     # once a score
                    self.stats.warnings.append(NOISE_WARNING)
                continue
            # _SsVmKeyOnNow (0x8009BEB8)
            regs = self.regs[v]
            regs.vol = spu_volume(
                note_vol, self.bank.vab.mvol, self.bank.prog_vol[prog],
                tone.vol, self.score_volume,
                (tone.pan, self.bank.prog_pan[prog], pan), self.mono)
            regs.pitch = note_pitch(note, tone.center, tone.shift)
            regs.dirty |= 7
            bit = 1 << v
            if tone.mode & TONE_REVERB:
                self.orev |= bit
                self.stats.reverb_notes += 1
            else:
                self.orev &= ~bit
            self.okon |= bit
            self.okof &= ~self.okon

    def _alloc(self, want: int) -> int:
        """`_SsVmAlloc` (0x8009B228) for a tone of priority `want`."""
        recs = self.recs
        chosen = None
        prior = want
        best, count, minkey, age = VOICES, 0, 0xFFFF, 0
        for i, r in enumerate(recs):
            if r.key_stat == 0 and r.envx == 0:
                chosen = i
                break
            if r.prior < prior:
                prior, best, minkey, age, count = r.prior, i, r.envx, r.age, 1
            elif r.prior == prior:
                count += 1
                if r.envx < minkey:
                    age, minkey, best = r.age, r.envx, i
                elif r.envx == minkey and age < r.age:
                    age, best = r.age, i
        if chosen is None:
            chosen = best if count else VOICES
        if chosen < VOICES:
            for r in recs:
                r.age += 1
            recs[chosen].age = 0
            recs[chosen].prior = want
        return chosen

    def _do_allocate(self, v: int, tone) -> None:
        """`_SsVmDoAllocate` (0x8009B498): the sample and the envelope, the
        release slowed by the damper."""
        self.recs[v].envx = 0x7FFF
        bit = ~(1 << v)
        self.hist = [h & bit for h in self.hist]
        regs = self.regs[v]
        regs.vag = tone.vag & 0xFF
        rr = min(0x1F, (tone.adsr2 & 0x1F) + self.damper_add)
        regs.adsr = (tone.adsr1, (tone.adsr2 & 0xFFE0) | rr)
        regs.dirty |= 0x38

    def key_off(self, prog, note) -> None:
        """`_SsVmKeyOff` (0x8009AF94): every voice still on record."""
        for v, r in enumerate(self.recs):
            if r.ours and r.note == note and r.pg == prog:
                self._key_off_now(v)

    def _key_off_now(self, v: int) -> None:
        """`_SsVmKeyOffNow` (0x8009BDF8)."""
        r = self.recs[v]
        r.key_stat, r.vag = 0, 0
        self.okof |= 1 << v
        self.okon &= ~self.okof

    def seq_key_off(self) -> None:
        """`_SsVmSeqKeyOff` (0x8009CE38)."""
        for v, r in enumerate(self.recs):
            if r.ours:
                self._key_off_now(v)

    def set_vol(self, prog, vol, pan) -> int:
        """`_SsVmSetVol` (0x8009CFB8): re-level the program's voices."""
        vol, pan = max(1, vol), max(1, pan)
        bank = self.bank
        count = 0
        for v, r in enumerate(self.recs):
            if not (r.ours and r.pg == prog):
                continue
            tone = bank.tones[r.prog * 16 + r.tone]
            regs = self.regs[v]
            regs.vol = spu_volume(
                r.vol * vol // 127, bank.vab.mvol, bank.prog_vol[prog],
                tone.vol, self.score_volume,
                (tone.pan, bank.prog_pan[r.pg], pan), self.mono)
            regs.dirty |= 3
            count += 1
        return count

    def set_prog_vol(self, prog, value) -> None:
        """`_SsVmSetProgVol` (0x8009C658)."""
        if 0 <= prog < min(MAX_PROGRAMS, len(self.bank.prog_vol)):
            self.bank.prog_vol[prog] = value

    def pitch_bend(self, prog, value) -> None:
        """`_SsVmPitchBend` (0x8009C574)."""
        for v, r in enumerate(self.recs):
            if r.ours and r.pg == prog:
                tone = self.bank.tones[r.prog * 16 + r.tone]
                self.regs[v].pitch = bend_pitch(tone, r.note, value)
                self.regs[v].dirty |= 4

    def bend_range(self, prog, value) -> None:
        self.bank.bend_range(prog, value)

    def damper(self, on: bool) -> None:
        """`_SsVmDamperOn` / `_SsVmDamperOff` (0x8009A248 / 0x8009A238)."""
        self.damper_add = 2 if on else 0

    # -- _SsVmFlush ---------------------------------------------------------

    def flush(self, t: int) -> None:
        """`_SsVmFlush` (0x8009A258) at output sample `t`."""
        spu, recs = self.spu, self.recs
        self.hist_ptr = (self.hist_ptr + 1) & 15
        silent = 0
        sounding = 0
        for v in range(VOICES):
            level = spu.envx(v, t)
            recs[v].envx = level
            if level == 0:
                silent |= 1 << v
            else:
                sounding += 1
        self.hist[self.hist_ptr] = silent
        self.stats.voices_max = max(self.stats.voices_max, sounding)
        freed = 0xFFFFFFFF
        for h in self.hist[:15]:
            freed &= h
        for v in range(VOICES):
            if freed & (1 << v):
                recs[v].key_stat = 0
        self.okon &= ~self.okof
        for v in range(VOICES):
            regs = self.regs[v]
            regs.rev = bool(self.orev >> v & 1)
            if regs.dirty:
                spu.write(v, t, regs)
                regs.dirty = 0
            else:
                spu.route(v, regs.rev)
        for v in range(VOICES):
            if self.okof >> v & 1:
                spu.key_off(v, t)
        for v in range(VOICES):
            if self.okon >> v & 1:
                spu.key_on(v, t, self.regs[v])
        self.okon = self.okof = 0


# ---------------------------------------------------------------------------
# The SPU voices
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpuWrite:
    """What libsnd's flush sent one SPU voice: a key-on ("on", with the
    registers it starts with), a key-off ("off"), or new registers for a
    voice already sounding ("set")."""
    at: int                     # output sample
    voice: int
    kind: str
    pitch: int = 0
    vol: tuple[int, int] = (0, 0)
    vag: int = 0
    adsr: tuple[int, int] = (0, 0)
    reverb: bool = False


class _Spu:
    """The 24 voices: what is sounding on each, for the voice manager to
    write to and read back."""

    def __init__(self, vab: Vab, mixer: Mixer, rate: int, log=None):
        self.vab, self.mixer, self.log = vab, mixer, log
        self.unit = SPU_BASE_RATE / rate * 16       # pitch -> 16.16 step
        self.plays: list[Play | None] = [None] * VOICES
        self.samples: dict[int, tuple] = {}
        self.done: list[Play] = []

    def _sample(self, vag_no: int) -> tuple:
        if vag_no not in self.samples:
            vag = next((v for v in self.vab.vags if v.index == vag_no), None)
            pcm, loop = vag.decode() if vag else ([], None)
            # One guard sample so the interpolator's `src[idx + 1]` is always
            # in range, including on the sample that wraps to the loop point.
            if pcm:
                pcm = pcm + [pcm[loop] if loop is not None else pcm[-1]]
            n = len(pcm) - 1 if pcm else 0
            self.samples[vag_no] = (
                (np.array(pcm, dtype=np.int64) if np is not None and pcm
                 else pcm), n,
                loop if loop is not None and loop < n else None)
        return self.samples[vag_no]

    def _step(self, pitch: int) -> int:
        return int(pitch * self.unit)

    def envx(self, v: int, t: int) -> int:
        play = self.plays[v]
        if play is None:
            return 0
        play.advance(t)
        if play.ended is not None:
            self.plays[v] = None
            return 0
        return play.level

    def _note(self, t: int, v: int, kind: str, regs: _Regs | None = None):
        if self.log is not None:
            if regs is None:
                self.log.append(SpuWrite(t, v, kind))
            else:
                self.log.append(SpuWrite(t, v, kind, regs.pitch, regs.vol,
                                         regs.vag, regs.adsr, regs.rev))

    def write(self, v: int, t: int, regs: _Regs) -> None:
        self._note(t, v, "set", regs)
        play = self.plays[v]
        if play is not None:
            play.advance(t)
            play.set(self._step(regs.pitch), regs.vol, regs.rev)
            if regs.dirty & 0x10:
                play.env.set_adsr(*regs.adsr)

    def route(self, v: int, rev: bool) -> None:
        play = self.plays[v]
        if play is not None and play.rev != rev:
            play.set(play.step, play.vol, rev)

    def key_off(self, v: int, t: int) -> None:
        self._note(t, v, "off")
        play = self.plays[v]
        if play is not None:
            play.env.key_off()

    def key_on(self, v: int, t: int, regs: _Regs) -> None:
        self._note(t, v, "on", regs)
        old = self.plays[v]
        if old is not None:
            old.advance(t)
            old.cut()
        self.plays[v] = Play(self.mixer, t, self._sample(regs.vag),
                             regs.adsr, self._step(regs.pitch), regs.vol,
                             regs.rev)

    def finish(self, t: int) -> None:
        for v, play in enumerate(self.plays):
            if play is not None:
                play.advance(t)
                play.flush()
                self.plays[v] = None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def walk(seq: Seq, vab: Vab, passes: int = 1, rate: int = SPU_BASE_RATE,
         tick_hz=NTSC_FIELD_HZ, vblank_minus: int = VBLANK_MINUS
         ) -> RenderStats:
    """Play the score's events through libsnd's reader without voices:
    what its key-ons would key, its length, its loop and its time map (in
    output samples at `rate`)."""
    stats = RenderStats()
    reader = _Reader(seq, _Counter(_Bank(vab), stats), passes, vblank_minus)
    _run(reader, lambda j: None)
    _timing(stats, reader, rate, tick_hz)
    stats.end = _sample_at(max(0, reader.now - 1), rate, tick_hz)
    stats.seconds = stats.end / rate
    return stats


def _sample_at(j: int, rate: int, tick_hz) -> int:
    """The output sample at which what tick `j` read reaches the SPU: the
    next tick's flush, counting from the tick `SsSeqPlay` starts on."""
    return int((j + 1) * rate / Fraction(tick_hz))


def spu_writes(seq: Seq, vab: Vab, passes: int = 1,
               rate: int = SPU_BASE_RATE,
               score_volume: tuple[int, int] = SCORE_VOLUME,
               tick_hz=NTSC_FIELD_HZ, vblank_minus: int = VBLANK_MINUS,
               mono: bool = False) -> tuple[list[SpuWrite], RenderStats]:
    """Everything libsnd sends the SPU voices while it plays the score, in
    order (`set` entries for a voice keyed on in the same flush come
    first), without mixing any audio."""
    stats, log = RenderStats(), []
    spu = _Spu(vab, Mixer(False, limit=0), rate, log)
    vm = _VoiceManager(_Bank(vab), spu, score_volume, mono, stats)
    reader = _Reader(seq, vm, passes, vblank_minus)
    _run(reader, lambda j: vm.flush(_sample_at(j, rate, tick_hz)))
    _timing(stats, reader, rate, tick_hz)
    return log, stats


def _run(reader: _Reader, after_tick) -> None:
    while reader.playing and reader.now < MAX_TICKS:
        j = reader.now
        reader.tick()
        after_tick(j)
    if reader.playing:
        reader.warnings.add("still playing after an hour; stopped")
        reader.playing = False
        reader.vm.seq_key_off()
        after_tick(reader.now)


def _timing(stats: RenderStats, reader: _Reader, rate: int, tick_hz) -> None:
    def at(j):
        return _sample_at(j, rate, tick_hz)
    stats.ticks = reader.now
    stats.tick_hz = float(tick_hz)
    stats.passes = len(reader.jumps)
    if len(reader.jumps) >= 2:
        stats.loop = (at(reader.jumps[-2]), at(reader.jumps[-1]))
    stats.marks = [(at(j), tick) for j, tick in reader.marks]
    if reader.first_pass is not None:
        stats.first_pass = at(reader.first_pass)
    stats.warnings += sorted(reader.warnings)


def tail_frames(rate: int, tail_seconds: float = 1.5, reverb=None) -> int:
    """Output samples after the score's last tick: the voices' releases,
    and with reverb its decay too."""
    if reverb is not None and np is not None:
        tail_seconds += REVERB_TAIL_SECONDS
    return int(tail_seconds * rate)


#: Output frames `render` reads at a time; the mix is also taken from the
#: mixer at least this often, which bounds the memory a long read holds.
RENDER_CHUNK = 1 << 16


class Player:
    """The score played as libsnd plays it, a piece at a time.

    `read(frames)` hands over the next output frames as interleaved 16-bit
    stereo. It runs libsnd's ticks only as far as those frames need, and
    holds only the state of the moment: the reader, the voices, the stretch
    of the mix not yet handed over and the reverb's delay lines. Whatever
    the pieces asked for, the frames are the same: a sample is handed over
    only once every voice has been mixed past it and the reverb has run
    past it, and the reverb runs on blocks of its own (`spu_reverb.Reverb`).
    `render` is a Player read to the end.

    `passes`: how many times an endless loop plays before the score goes on
    to its ending. None plays it for ever, as the game does, until
    `set_looping(False)`: the score then goes on at the next loop end. An
    hour's limit applies only to a counted number of passes.
    """

    def __init__(self, seq: Seq, vab: Vab, rate: int = SPU_BASE_RATE,
                 tail_seconds: float = 1.5, reverb=None,
                 score_volume: tuple[int, int] = SCORE_VOLUME,
                 master_volume: int = MASTER_VOLUME,
                 passes: int | None = None, tick_hz=NTSC_FIELD_HZ,
                 vblank_minus: int = VBLANK_MINUS, mono: bool = False):
        self.rate = rate
        self.tick_hz = tick_hz
        self.master_volume = master_volume
        self.stats = RenderStats()
        if reverb is not None and np is None:
            self.stats.warnings.append("reverb skipped: needs numpy")
            reverb = None
        self.setting = reverb
        self.tail = tail_frames(rate, tail_seconds, reverb)
        self.mixer = Mixer(reverb is not None)
        self.spu = _Spu(vab, self.mixer, rate)
        self.vm = _VoiceManager(_Bank(vab), self.spu, score_volume, mono,
                                self.stats)
        self.reader = _Reader(seq, self.vm, passes, vblank_minus)
        self.max_ticks = None if passes is None else MAX_TICKS
        self.reverb = None
        if reverb is not None:
            from decoders.psx.formats.spu_reverb import Reverb
            self.reverb = Reverb(reverb, rate)
        self.flushed = 0            # output sample of the latest flush
        self.settled = 0            # mixed and taken from the mixer to here
        self.total: int | None = None   # the output's length, once known
        self.pos = 0                # frames handed over
        self._dry: list = []        # the mix from `pos` on, in pieces
        self._looping_from = None   # (tick, on): the loop switch, waiting
        self._finished = False

    # -- where things are -------------------------------------------------

    def at(self, tick: int) -> int:
        """The output sample at which what `tick` read reaches the SPU."""
        return _sample_at(tick, self.rate, self.tick_hz)

    def tick_for(self, frame: int) -> int:
        """The first tick whose reading is heard at output `frame` or
        later."""
        return max(0, math.ceil(Fraction(frame) * Fraction(self.tick_hz)
                                / self.rate) - 1)

    @property
    def ended(self) -> bool:
        """Every frame has been handed over."""
        return self.total is not None and self.pos >= self.total

    @property
    def looping(self) -> bool:
        return self.reader.passes == math.inf

    def set_looping(self, on: bool, frame: int | None = None) -> None:
        """Repeat the endless loop for ever, or go on to the score's ending
        at the next loop end: from the next tick on, or from the tick that
        is heard at output `frame` (a loop end the reader has already met
        stays as it went)."""
        tick = self.reader.now if frame is None else self.tick_for(frame)
        if tick > self.reader.now:
            self._looping_from = (tick, on)
            return
        self._looping_from = None
        r = self.reader
        r.passes = math.inf if on else len(r.jumps) + 1

    def set_passes(self, passes: int | None) -> None:
        """Play an endless loop `passes` times in all (None: for ever) from
        the next tick on, whatever the loop switch was waiting to do."""
        self._looping_from = None
        self.reader.passes = math.inf if passes is None else passes

    # -- playing ----------------------------------------------------------

    def _tick(self) -> None:
        """`_SsSeqPlay` for one sound tick, and the flush that sends it."""
        reader = self.reader
        if not reader.playing:          # a header that stops it at once
            self._end(self.at(max(0, reader.now - 1)))
            return
        j = reader.now
        if self._looping_from is not None and j >= self._looping_from[0]:
            self.set_looping(self._looping_from[1])
        reader.tick()
        self.flushed = self.at(j)
        self.vm.flush(self.flushed)
        if not reader.playing:
            self._end(self.at(max(0, reader.now - 1)))
        elif self.max_ticks is not None and reader.now >= self.max_ticks:
            reader.warnings.add("still playing after an hour; stopped")
            reader.playing = False
            reader.vm.seq_key_off()
            self.vm.flush(self.at(reader.now))
            self._end(self.at(reader.now - 1))

    def _end(self, end: int) -> None:
        """The score is over: its voices ring out for the tail."""
        self.stats.end = end
        self.total = end + self.tail + 1
        self.spu.finish(self.total)
        self.flushed = self.total

    def _settle(self) -> None:
        """Mix every voice up to the latest flush and take that from the
        mixer: it is final."""
        for play in self.spu.plays:
            if play is not None:
                play.flush()
        left, right, rev_l, rev_r = self.mixer.take(self.flushed)
        if self.reverb is not None:
            self.reverb.push(rev_l, rev_r)
            if self.total is not None:
                self.reverb.close()
            # a voice sent to the reverb is heard dry as well
            left, right = left + rev_l, right + rev_r
        if len(left):
            self._dry.append((left, right))
        self.settled = self.flushed

    def _final(self) -> int:
        """Output frames that can be handed over."""
        if self.reverb is None:
            return self.settled
        return min(self.settled, self.reverb.ready)

    def _fill(self, want: int) -> None:
        while self._final() < want and not (
                self.total is not None and self.settled == self.total):
            need = want if self.reverb is None else self.reverb.input_for(want)
            need = min(max(need, self.flushed + 1),
                       self.flushed + RENDER_CHUNK)
            while self.total is None and self.flushed < need:
                self._tick()
            self._settle()

    def _take(self, frames: int):
        want = self.pos + max(0, frames)
        self._fill(want)
        n = max(0, min(want, self._final()) - self.pos)
        parts_l, parts_r, got = [], [], 0
        while got < n:
            left, right = self._dry[0]
            k = min(len(left), n - got)
            parts_l.append(left[:k])
            parts_r.append(right[:k])
            if k < len(left):
                self._dry[0] = (left[k:], right[k:])
            else:
                self._dry.pop(0)
            got += k
        left, right = _join(parts_l), _join(parts_r)
        if self.reverb is not None:
            wet_l, wet_r = self.reverb.pull(n)
            left = left + np.rint(wet_l).astype(np.int32)
            right = right + np.rint(wet_r).astype(np.int32)
        self.pos += n
        return left, right

    def read(self, frames: int) -> bytes:
        """The next `frames` output frames, interleaved 16-bit stereo; fewer
        only at the end, and b"" once it is over."""
        left, right = self._take(frames)
        if not len(left):
            return b""
        out, peak, clipped = _master(left, right, self.master_volume)
        self.stats.peak = max(self.stats.peak, peak)
        self.stats.clipped += clipped
        return out

    def skip(self, frames: int) -> int:
        """Play `frames` frames without handing them over (they still count
        in everything but the peak and clipping); -> frames skipped."""
        before = self.pos
        end = self.pos + max(0, frames)
        while self.pos < end and not self.ended:
            if not len(self._take(min(RENDER_CHUNK, end - self.pos))[0]):
                break
        return self.pos - before

    def snapshot(self) -> "Player":
        """A copy of the whole state, taken between reads: reading on from
        the copy gives exactly what reading on from here gives. The score,
        the bank and the decoded samples are shared, never changed."""
        memo = {id(x): x for x in (self.reader.events, self.spu.vab,
                                   self.vm.bank.vab, self.spu.samples,
                                   self.setting)}
        for tone in self.vm.bank.tones:
            memo[id(tone)] = tone
        for sample in self.spu.samples.values():
            memo[id(sample)] = sample
            memo[id(sample[0])] = sample[0]
        if self.reverb is not None:
            net = self.reverb.net
            for name in ("p", "res", "kern", "pows", "v_in", "combs", "apf"):
                if hasattr(net, name):
                    memo[id(getattr(net, name))] = getattr(net, name)
        return copy.deepcopy(self, memo)

    def result(self) -> RenderStats:
        """What the performance played, once it is over."""
        stats = self.stats
        if self._finished:
            return stats
        self._finished = True
        _timing(stats, self.reader, self.rate, self.tick_hz)
        stats.seconds = stats.end / self.rate
        if self.setting is not None:
            dl, dr = self.setting.depth
            stats.reverb = (f"{self.setting.preset.name} depth "
                            f"{dl:+.3f}/{dr:+.3f}, {stats.reverb_notes} of "
                            f"{stats.voices} key-ons sent")
        if stats.clipped:
            stats.warnings.append(f"{stats.clipped:,} samples clipped")
        if stats.dropped:
            stats.warnings.append(
                f"{stats.dropped} note(s) fall in no tone's key range and "
                f"sound nothing, as in libsnd")
        if stats.lost:
            stats.warnings.append(
                f"{stats.lost} tone(s) found no free voice and did not "
                f"sound, as in libsnd")
        return stats


def render(seq: Seq, vab: Vab, rate: int = SPU_BASE_RATE,
           tail_seconds: float = 1.5, progress=None, reverb=None,
           score_volume: tuple[int, int] = SCORE_VOLUME,
           master_volume: int = MASTER_VOLUME, passes: int = 2,
           tick_hz=NTSC_FIELD_HZ, vblank_minus: int = VBLANK_MINUS,
           mono: bool = False) -> tuple[bytes, RenderStats]:
    """Render a sequence to interleaved 16-bit stereo PCM: a `Player` of
    `passes` read to the end.

    `reverb`: a `spu_reverb.ReverbSetting` (the program's preset + depth),
    or None for a dry render (reverb needs numpy). `score_volume`: the
    (left, right) a program sets with `SsSeqSetVol`, 0..127.
    `master_volume`: the SPU main volume (0..0x3FFF). `passes`: how many
    times an endless loop plays before the score goes on to its end;
    `stats.loop` is then the last pass. `tick_hz`: the sound tick's real
    rate; `vblank_minus`: the rate libsnd's tempo arithmetic assumes.
    `progress(tick, ticks)` is called as it goes."""
    passes = max(1, passes)
    player = Player(seq, vab, rate, tail_seconds, reverb, score_volume,
                    master_volume, passes, tick_hz, vblank_minus, mono)
    ticks = None
    if progress:
        probe = _Reader(seq, _Counter(_Bank(vab), RenderStats()), passes,
                        vblank_minus)
        _run(probe, lambda j: None)
        ticks = probe.now
    parts = []
    while chunk := player.read(RENDER_CHUNK):
        parts.append(chunk)
        if progress:
            progress(player.reader.now, ticks)
    return b"".join(parts), player.result()


def _join(parts):
    if np is not None:
        return (np.concatenate(parts) if parts
                else np.zeros(0, dtype=np.int32))
    from array import array
    out = array("i")
    for part in parts:
        out += part
    return out


def _master(left, right, master_volume: int) -> tuple[bytes, int, int]:
    """Clip the mix to 16 bits, apply the main volume, interleave ->
    (PCM, peak, samples clipped)."""
    total = len(left)
    if np is not None:
        clipped = int(
            np.count_nonzero((left > 32767) | (left < -32768))
            + np.count_nonzero((right > 32767) | (right < -32768)))
        inter = np.empty(total * 2, dtype=np.int64)
        inter[0::2] = np.clip(left, -32768, 32767)
        inter[1::2] = np.clip(right, -32768, 32767)
        inter = (inter * master_volume) >> 14
        peak = int(np.abs(inter).max(initial=0))
        return np.clip(inter, -32768, 32767).astype(np.int16).tobytes(), \
            peak, clipped
    from array import array
    clipped = sum(1 for v in left if v > 32767 or v < -32768) \
        + sum(1 for v in right if v > 32767 or v < -32768)
    buf = array("h", bytes(4 * total))

    def level(v):
        v = -32768 if v < -32768 else (32767 if v > 32767 else v)
        v = (v * master_volume) >> 14
        return -32768 if v < -32768 else (32767 if v > 32767 else v)

    buf[0::2] = array("h", [level(v) for v in left])
    buf[1::2] = array("h", [level(v) for v in right])
    return buf.tobytes(), max((abs(v) for v in buf), default=0), clipped

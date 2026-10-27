"""PS1 VAB sample banks and SPU-ADPCM waveform decoding.

VAB is Sony's standard instrument-bank container for `libsnd`: a *header*
part (VH) describing programs and tones, and a *body* part (VB) holding the
raw SPU-ADPCM waveforms the tones point at. Lunar ships 127 of them inside
LUNADATA.FIL — see `decoders.plugins.SLUS_006_28.formats.sound_banks` for how they are found and
`docs/spec/sound.md` for the whole picture.

The struct layout here is taken from Sony's `libsnd.h`, the PsyQ SDK's
header (`VabHdr`, `ProgAtr`, `VagAtr`), which is the authority on field
widths — not from any third-party ripper. Two fields
are commonly got wrong by tools that guess: `VagAtr.prog` and `VagAtr.vag`
are **signed shorts**, and the eight bytes after them are `reserved[4]`, not
a tone name.

    VabHdr    32 bytes
    ProgAtr   16 bytes x 128 or 64 (the slots, whatever `ps` says)
    VagAtr    32 bytes x 16 x ps  (16 tone slots per *declared* program)
    u16       x 256               VAG sizes, in 8- or 4-byte units

How libsnd reads it is `_SsVabOpenHeadWithMode` (0x8009D7F8, SSSC's copy of
libsnd), and `parse_vab` follows it: a 'pBAV' header of version 5 or later
has 128 program slots and counts VAG sizes in 8-byte units; an older or
other form has 64 slots and 4-byte units; a header declaring more programs
than its slots is refused. The VB is the VAGs of size-table entries 0 to
`vs` back to back, entry 0 first — so VAG *n* starts after entries 0..n-1
— and is sent to SPU RAM whole.

The waveform codec is the SPU's 16-byte-block ADPCM: a shift/filter byte, a
flag byte, then 28 samples packed two per byte. The predictor coefficients
are hardware constants; the only free choice is how the coefficient sum is
rounded, and implementations disagree on the last bit (ffmpeg truncates
toward zero, PSY-Z rounds each term separately, this rounds the sum to
nearest as psx-spx describes). Measured across all 1,029 of Lunar's samples
the three differ by 28 RMS — 61 dB below full scale, and neither clips
measurably more than the others — so the choice is inaudible and none of
them can be called bit-exact without hardware to compare against.
"""

from __future__ import annotations

import io
import struct
import wave
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# SPU-ADPCM
# ---------------------------------------------------------------------------

# Second-order predictor coefficients, scaled by 1/64. The SPU defines five;
# a block naming a higher filter is treated as filter 0 (as the hardware does).
_FILTER_POS = (0, 60, 115, 98, 122)
_FILTER_NEG = (0, 0, -52, -55, -60)

ADPCM_BLOCK = 16            # bytes per encoded block
ADPCM_SAMPLES = 28          # samples produced per block

# Block flag bits (byte 1 of each block).
LOOP_END = 1                # last block of the sample
LOOP_REPEAT = 2             # on end, jump to the loop start (else release)
LOOP_START = 4              # this block is the loop point

# All three bits together is the encoder's idiom for "one-shot": the repeat
# address points back at this terminating block, which is silence. Lunar uses
# it on 704 of its 1029 samples; the other 325 end with END|REPEAT and really
# do loop. Reading LOOP_START alone would call every sample a looping one.
ONE_SHOT = LOOP_END | LOOP_REPEAT | LOOP_START

#: The SPU plays a sample at 44100 Hz when its pitch register reads 0x1000.
SPU_BASE_RATE = 44100
SPU_UNITY_PITCH = 0x1000

# PSY-Q 4.5 libsnd's pitch tables, as `SsPitchFromNote` (0x8009B71C) reads
# them: 12 semitone ratios `0x8000 * 2**(k/12)` (D_800B7A10) and 128
# fine-tune ratios `0x8000 * 2**(k/1536)`, 1/128 of a semitone apart
# (D_800B7A28), both 0.15 fixed point and rounded down. They are generated
# rather than transcribed; the SLUS_006_28 plugin's
# formats/tests/test_libsnd_on_disc.py checks every entry against the tables
# in that program's EXE when the disc is in the library.
SEMITONE_RATIOS = tuple(int(0x8000 * 2 ** (k / 12)) for k in range(12))
FINE_RATIOS = tuple(int(0x8000 * 2 ** (k / 1536)) for k in range(128))

#: The SPU pitch libsnd puts on every note two octaves or more above its
#: tone's centre.
PITCH_MAX = 0x3FFF


def _clamp16(v: int) -> int:
    return -32768 if v < -32768 else (32767 if v > 32767 else v)


def decode_adpcm(data: bytes) -> tuple[list[int], int | None]:
    """Decode SPU-ADPCM to signed 16-bit PCM.

    Returns `(samples, loop_start)` where `loop_start` is the sample index the
    SPU would jump back to, or None when the sample is one-shot — judged from
    the *terminating* block's flags, not from LOOP_START alone (see ONE_SHOT).

    Decoding stops after the block that sets LOOP_END, which is where the SPU
    stops or jumps. That matters: 704 of Lunar's 1,029 samples are followed by
    the encoder's canonical end marker `00 07 77 77 …`, and decoding it emits
    a burst at ±28672 — a full-scale click on the end of every one-shot
    sample. The block is never heard on hardware and must not be decoded.
    """
    out: list[int] = []
    loop_start: int | None = None
    end_flags = 0
    hist1 = hist2 = 0

    for pos in range(0, len(data) - ADPCM_BLOCK + 1, ADPCM_BLOCK):
        header = data[pos]
        shift = header & 0x0F
        filt = header >> 4
        flags = data[pos + 1]

        # Out-of-range values are what the hardware sees on malformed blocks.
        if shift > 12:
            shift = 9
        if filt >= len(_FILTER_POS):
            filt = 0
        f_pos, f_neg = _FILTER_POS[filt], _FILTER_NEG[filt]

        if flags & LOOP_START and loop_start is None:
            loop_start = len(out)
        if flags & LOOP_END:
            end_flags = flags

        for i in range(ADPCM_SAMPLES):
            byte = data[pos + 2 + (i >> 1)]
            nibble = (byte & 0x0F) if not (i & 1) else (byte >> 4)
            # Sign-extend the nibble into the top of a 16-bit word, then scale.
            sample = (nibble << 12) & 0xFFFF
            if sample & 0x8000:
                sample -= 0x10000
            sample >>= shift
            sample += (hist1 * f_pos + hist2 * f_neg + 32) >> 6
            sample = _clamp16(sample)
            out.append(sample)
            hist2, hist1 = hist1, sample

        if flags & LOOP_END:
            break

    if end_flags == ONE_SHOT or not end_flags & LOOP_REPEAT:
        loop_start = None
    return out, loop_start


def pcm_to_wav(samples: list[int], rate: int) -> bytes:
    """Wrap 16-bit mono PCM in a RIFF/WAVE container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


def _cdiv(a: int, b: int) -> int:
    """C's integer division: the quotient rounded toward zero."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _cmod(a: int, b: int) -> int:
    """C's remainder: the sign of the dividend."""
    return a - b * _cdiv(a, b)


def pitch_from_note(note: int, fine: int, center: int, shift: int) -> int:
    """libsnd's `SsPitchFromNote` (0x8009B71C): the SPU pitch register value
    (0x1000 plays a sample at 44100 Hz) for `note` plus `fine` 1/128ths of a
    semitone, on a tone recorded at `center` with fine tune `shift`.

    The fine parts add up and carry into the note; the note's distance from
    the centre splits into an octave and a semitone; the pitch is the product
    of the two ratio tables, 0x4000 at unity, shifted right by the octave
    with rounding. From two octaves above the centre it is PITCH_MAX.
    """
    f = fine + shift
    n = note + _cdiv(f, 128) - center
    f = _cmod(f, 128)
    if f < 0:
        f += 128
        n -= 1
    octave = _cdiv(n, 12) - 2
    semi = _cmod(n, 12)
    if semi < 0:
        semi += 12
        octave -= 1
    pitch = (SEMITONE_RATIOS[semi] * FINE_RATIOS[f]) >> 16
    if octave >= 0:
        return PITCH_MAX
    return (pitch + (1 << (-octave - 1))) >> -octave


def note_pitch(note: int, center: int, shift: int) -> int:
    """SPU pitch of a note at key-on, as libsnd's `note2pitch` (0x8009B668)
    asks `SsPitchFromNote` (0x8009B71C) for it: no fine part, a fine tune
    above 127 taken as 127."""
    return pitch_from_note(note, 0, center, min(shift, 0x7F))


def tone_sample_rate(shift: int) -> int:
    """Playback rate of a tone struck on its own centre note."""
    return round(SPU_BASE_RATE * note_pitch(0, 0, shift) / SPU_UNITY_PITCH)


# ---------------------------------------------------------------------------
# VAB structures
# ---------------------------------------------------------------------------

VAB_MAGIC = b"pBAV"         # 'VABp' as a little-endian long
VAB_FORM = b"BAV"           # the form's top three bytes, which libsnd checks
VAB_HEADER_SIZE = 32
PROGRAM_SLOTS = 128         # a 'p' form of version 5 or later
PROGRAM_SLOTS_OLD = 64      # anything else
PROGRAM_SIZE = 16
TONE_SLOTS = 16
TONE_SIZE = 32
VAG_TABLE_SLOTS = 256


def program_slots(form: int, version: int) -> int:
    """`_SsVabOpenHeadWithMode` (0x8009D7F8): the ProgAtr slots a header
    has, by its form's low byte and its version."""
    return PROGRAM_SLOTS if form == ord("p") and version >= 5 \
        else PROGRAM_SLOTS_OLD


def vag_size_unit(version: int) -> int:
    """Bytes per unit of the VAG size table: 8 from version 5, 4 before."""
    return 8 if version >= 5 else 4


@dataclass(frozen=True)
class Program:
    """One `ProgAtr` slot — a bank of up to 16 tones addressed by MIDI program."""

    index: int
    tones: int
    mvol: int
    prior: int
    mode: int
    mpan: int
    attr: int

    @property
    def used(self) -> bool:
        return self.tones > 0


@dataclass(frozen=True)
class Tone:
    """One `VagAtr` slot — a waveform plus how to play it across a key range."""

    program: int
    index: int
    prior: int
    mode: int
    vol: int
    pan: int
    center: int
    shift: int
    min_note: int
    max_note: int
    vib_w: int
    vib_t: int
    por_w: int
    por_t: int
    pbmin: int
    pbmax: int
    adsr1: int
    adsr2: int
    prog: int
    vag: int

    @property
    def sample_rate(self) -> int:
        return tone_sample_rate(self.shift)


@dataclass
class Vag:
    """One waveform in the body, and the slice of the VB that holds it."""

    index: int
    offset: int             # byte offset within the VB
    size: int               # bytes of ADPCM
    data: bytes = b""

    @property
    def frames(self) -> int:
        return (self.size // ADPCM_BLOCK) * ADPCM_SAMPLES

    def decode(self) -> tuple[list[int], int | None]:
        return decode_adpcm(self.data)


@dataclass
class Vab:
    """A parsed VAB: header, program/tone tables, and the waveforms."""

    version: int
    vab_id: int
    fsize: int
    ps: int                 # declared program count
    ts: int                 # declared tone count
    vs: int                 # declared VAG count
    mvol: int
    pan: int
    attr1: int
    attr2: int
    vh_size: int
    programs: list[Program] = field(default_factory=list)
    tones: list[Tone] = field(default_factory=list)
    vags: list[Vag] = field(default_factory=list)

    @property
    def used_programs(self) -> list[Program]:
        return [p for p in self.programs if p.used]

    def tones_of(self, program: int) -> list[Tone]:
        return [t for t in self.tones if t.program == program]

    def tones_using(self, vag_index: int) -> list[Tone]:
        """Every tone that references VAG *n* (1-based, as stored)."""
        return [t for t in self.tones if t.vag == vag_index]

    def vag_rate(self, vag_index: int) -> int:
        """Best-known natural rate for a waveform, via the tones that use it.

        A VAG carries no rate of its own — pitch is a property of the tone
        that plays it. When several tones share one waveform they normally
        agree; if they do not, the first is used and the caller can show the
        rest from `tones_using`.
        """
        users = self.tones_using(vag_index)
        return users[0].sample_rate if users else SPU_BASE_RATE


def vh_size(ps: int, slots: int = PROGRAM_SLOTS) -> int:
    """Bytes of VH for a bank declaring `ps` programs in `slots` slots."""
    return (VAB_HEADER_SIZE
            + slots * PROGRAM_SIZE
            + ps * TONE_SLOTS * TONE_SIZE
            + VAG_TABLE_SLOTS * 2)


def parse_vab(vh: bytes, vb: bytes = b"") -> Vab:
    """Parse a VH (and optionally attach the matching VB body)."""
    if len(vh) < VAB_HEADER_SIZE or vh[1:4] != VAB_FORM:
        raise ValueError("not a VAB header (missing 'pBAV' magic)")

    _form, ver, vab_id, fsize = struct.unpack_from("<iiiI", vh, 0)
    _res0, ps, ts, vs = struct.unpack_from("<HHHH", vh, 16)
    mvol, pan, attr1, attr2 = vh[24:28]

    slots = program_slots(vh[0], ver)
    if ps > slots:
        raise ValueError(f"VH declares {ps} programs in {slots} slots")
    expected = vh_size(ps, slots)
    if len(vh) < expected:
        raise ValueError(f"VH truncated: {len(vh)} bytes, need {expected}")

    programs = []
    for i in range(slots):
        off = VAB_HEADER_SIZE + i * PROGRAM_SIZE
        tones, pvol, prior, mode, mpan, _r0 = vh[off:off + 6]
        (attr,) = struct.unpack_from("<h", vh, off + 6)
        programs.append(Program(index=i, tones=tones, mvol=pvol, prior=prior,
                                mode=mode, mpan=mpan, attr=attr))

    tone_base = VAB_HEADER_SIZE + slots * PROGRAM_SIZE
    tones_out = []
    for p in range(ps):
        for t in range(TONE_SLOTS):
            off = tone_base + (p * TONE_SLOTS + t) * TONE_SIZE
            b = vh[off:off + TONE_SIZE]
            adsr1, adsr2 = struct.unpack_from("<HH", b, 16)
            prog, vag = struct.unpack_from("<hh", b, 20)
            tones_out.append(Tone(
                program=p, index=t,
                prior=b[0], mode=b[1], vol=b[2], pan=b[3],
                center=b[4], shift=b[5], min_note=b[6], max_note=b[7],
                vib_w=b[8], vib_t=b[9], por_w=b[10], por_t=b[11],
                pbmin=b[12], pbmax=b[13],
                adsr1=adsr1, adsr2=adsr2, prog=prog, vag=vag,
            ))

    size_base = tone_base + ps * TONE_SLOTS * TONE_SIZE
    sizes = struct.unpack_from(f"<{VAG_TABLE_SLOTS}H", vh, size_base)
    unit = vag_size_unit(ver)

    # entries 0..vs (vs read as a byte, as libsnd keeps it), in VB order
    vags, cursor = [], 0
    for i in range((vs & 0xFF) + 1):
        size = sizes[i] * unit
        if i and size:
            vags.append(Vag(index=i, offset=cursor, size=size,
                            data=vb[cursor:cursor + size]))
        cursor += size

    return Vab(version=ver, vab_id=vab_id, fsize=fsize, ps=ps, ts=ts, vs=vs,
               mvol=mvol, pan=pan, attr1=attr1, attr2=attr2,
               vh_size=expected, programs=programs, tones=tones_out, vags=vags)


# ---------------------------------------------------------------------------
# ADSR — the envelope word pair, decoded for display
# ---------------------------------------------------------------------------

def decode_adsr(adsr1: int, adsr2: int) -> dict:
    """Unpack the two SPU ADSR registers into their named fields.

    Layout is the SPU's, as written by `SsUtSetVagAtr`/`SpuSetVoiceADSR`:
    adsr1 = SL(0-3) DL(4-7) AT(8-14) AM(15); adsr2 = RR(0-4) RM(5) SR(6-12)
    SD(14) SM(15), as libsnd's `_SsUtResolveADSR` and the renderer
    (seq_synth) read them; bit 13 is not used.
    """
    return {
        "sustain_level": adsr1 & 0x0F,
        "decay_rate": (adsr1 >> 4) & 0x0F,
        "attack_rate": (adsr1 >> 8) & 0x7F,
        "attack_mode": "exp" if adsr1 & 0x8000 else "lin",
        "release_rate": adsr2 & 0x1F,
        "release_mode": "exp" if adsr2 & 0x20 else "lin",
        "sustain_rate": (adsr2 >> 6) & 0x7F,
        "sustain_dir": "dec" if adsr2 & 0x4000 else "inc",
        "sustain_mode": "exp" if adsr2 & 0x8000 else "lin",
    }

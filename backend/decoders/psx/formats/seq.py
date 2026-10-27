"""PS1 SEQ music sequences, and their conversion to standard MIDI.

SEQ is what `libsnd` plays: a fifteen-byte header followed by a MIDI event
stream — variable-length delta times, running status, the usual channel
voice messages. It is close enough to a format-0 MIDI track that converting
one is a re-wrap rather than a translation.

    'pQES'          4 bytes, 'SEQp' as a little-endian long
    version         u32 big-endian
    resolution      u16 big-endian, ticks per quarter note
    tempo           u24 big-endian, microseconds per quarter note
    rhythm          2 bytes
    events          MIDI stream, terminated by FF 2F 00

Every multi-byte field is **big-endian**, unlike the VAB header beside it —
the sequence data was authored on MIDI tooling and kept its byte order.

Meta events are the one place SEQ departs from MIDI: they carry **no length
byte**. `FF 51` is followed by three raw tempo bytes, not by `03` and then
the tempo. Reading them the MIDI way desynchronises the stream — a length of
0x0d gets taken from the first tempo byte and the rest of the sequence is
lost. Across Lunar's 412 sequences exactly two meta types occur, `FF 2F 00`
(end of track, once per sequence) and `FF 51 tt tt tt` (set tempo, 103
times), and with this rule all 412 parse to a clean end.

`parse_seq` reads the stream byte for byte as libsnd's reader does
(`_SsGetSeqData` (0x80098CD8) and the handlers it calls), so what it lists
is what the library plays, also where that is not what MIDI would mean:

* the delta time before the first event is read with the header
  (`_SsInitSoundSeq` (0x80097C48)); every other delta is read by the handler
  of the event before it, and a delta has no length limit
  (`_SsReadDeltaValue` (0x80097B98));
* the reader knows the statuses 0x90, 0xB0, 0xC0, 0xE0 and 0xF0-0xFF. A
  status byte 0x80, 0xA0 or 0xD0 only sets the channel: no data byte and no
  delta is read for it, so the bytes after it are read under the running
  status of the event before (a MIDI note-off `8n kk vv` plays as a note-on
  of key kk at velocity vv on channel n);
* a pitch bend keeps only its second data byte;
* every meta type but the end of track (0x2F) is read as a tempo: three
  bytes, then a delta (`_SsGetMetaEvent` (0x80097878)).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

SEQ_MAGIC = b"pQES"
SEQ_HEADER_SIZE = 15

META_END = 0x2F
META_TEMPO = 0x51

#: Statuses `_SsGetSeqData` (0x80098CD8) has no case for: the status byte
#: sets the channel and nothing else is read.
IGNORED_STATUSES = (0x80, 0xA0, 0xD0)

_MESSAGE_NAMES = {
    0x80: "note off", 0x90: "note on", 0xA0: "aftertouch",
    0xB0: "control", 0xC0: "program", 0xD0: "channel pressure",
    0xE0: "pitch bend",
}

# Controllers Lunar's sequences actually use. 98/99 are MIDI's NRPN selects,
# which libsnd repurposes for its own sequence controls (loop points among
# them) — hence the neutral naming for those two.
CONTROLLER_NAMES = {
    0: "bank select", 1: "modulation", 6: "data entry", 7: "volume",
    10: "pan", 11: "expression", 38: "data entry lo", 64: "sustain",
    91: "reverb depth", 98: "NRPN lo", 99: "NRPN hi",
    120: "all sound off", 121: "reset controllers", 123: "all notes off",
}


def controller_name(number: int) -> str:
    return CONTROLLER_NAMES.get(number, f"cc{number}")


@dataclass(frozen=True)
class SeqEvent:
    """One event as libsnd's reader takes it. `tick` is its place in delta
    ticks from the start; `delta` is the delta time the reader takes after
    it (in ticks), or None when it takes none (the end of track, and the
    statuses the reader has no case for)."""

    tick: int
    status: int
    data: bytes
    delta: int | None = None

    @property
    def channel(self) -> int:
        return self.status & 0x0F

    @property
    def kind(self) -> int:
        return self.status & 0xF0

    @property
    def name(self) -> str:
        if self.status == 0xFF:
            return f"meta {self.data[0]:#04x}" if self.data else "meta"
        if self.kind in IGNORED_STATUSES:
            return f"{_MESSAGE_NAMES[self.kind]} (not read)"
        return _MESSAGE_NAMES.get(self.kind, f"status {self.status:#04x}")

    @property
    def tempo(self) -> int | None:
        """Microseconds per quarter note, for a meta event libsnd reads as
        a tempo (every type but the end of track)."""
        if self.status == 0xFF and len(self.data) >= 4 \
                and self.data[0] != META_END:
            return int.from_bytes(self.data[1:4], "big")
        return None

    @property
    def is_note_on(self) -> bool:
        return self.kind == 0x90 and len(self.data) > 1 and self.data[1] > 0


@dataclass
class Seq:
    """A parsed sequence."""

    version: int
    resolution: int         # ticks per quarter note
    tempo: int              # microseconds per quarter note
    rhythm: tuple[int, int]
    events: list[SeqEvent] = field(default_factory=list)
    size: int = 0           # bytes of the whole SEQ chunk
    truncated: bool = False  # the stream ran out before an end-of-track

    @property
    def bpm(self) -> float:
        return 60_000_000 / self.tempo if self.tempo else 0.0

    @property
    def ticks(self) -> int:
        return self.events[-1].tick if self.events else 0

    @property
    def seconds(self) -> float:
        """Length at the header tempo. Sequences that change tempo mid-stream
        are re-timed here event by event, so this stays honest for them too."""
        if not self.resolution:
            return 0.0
        total, tempo, prev = 0.0, self.tempo, 0
        for ev in self.events:
            total += (ev.tick - prev) * tempo / self.resolution / 1_000_000
            prev = ev.tick
            if ev.tempo:
                tempo = ev.tempo
        return total

    @property
    def channels(self) -> list[int]:
        return sorted({e.channel for e in self.events
                       if e.kind in (0x90, 0xB0, 0xC0, 0xE0)})

    @property
    def programs(self) -> list[int]:
        return sorted({e.data[0] for e in self.events
                       if e.kind == 0xC0 and e.data})

    @property
    def notes(self) -> int:
        return sum(1 for e in self.events if e.is_note_on)


def _read_delta(data: bytes, pos: int) -> tuple[int | None, int]:
    """A delta time as `_SsReadDeltaValue` (0x80097B98) reads it: 7 bits a
    byte while bit 7 is set, with no limit on the length. (None, pos) when
    the data ends first."""
    value = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, pos
    return None, pos


def parse_seq(data: bytes) -> Seq:
    """Parse a SEQ chunk (starting at its 'pQES' magic) the way libsnd's
    reader walks it (the module docstring has the rules)."""
    if len(data) < SEQ_HEADER_SIZE or data[:4] != SEQ_MAGIC:
        raise ValueError("not a SEQ (missing 'pQES' magic)")

    (version,) = struct.unpack_from(">I", data, 4)
    (resolution,) = struct.unpack_from(">H", data, 8)
    tempo = int.from_bytes(data[10:13], "big")
    rhythm = (data[13], data[14])

    events: list[SeqEvent] = []
    tick, pos = _read_delta(data, SEQ_HEADER_SIZE)
    running = channel = 0
    truncated = True

    def take(n: int) -> bytes | None:
        nonlocal pos
        if pos + n > len(data):
            return None
        pos += n
        return data[pos - n:pos]

    while tick is not None and pos < len(data):
        byte = data[pos]
        pos += 1
        if byte & 0x80:
            channel = byte & 0x0F
            kind = byte & 0xF0
            if kind in IGNORED_STATUSES:
                events.append(SeqEvent(tick, byte, b""))
                continue
            running = kind = 0xFF if kind == 0xF0 else kind
            first = take(1)             # a bend's is the low byte, dropped
            if first is None:
                break
        else:
            if running == 0:            # a data byte the reader skips
                events.append(SeqEvent(tick, channel, bytes([byte])))
                continue
            kind, first = running, bytes([byte])

        if kind == 0xFF:                # meta: fixed width, no length byte
            meta_type = first[0]
            if meta_type == META_END:
                events.append(SeqEvent(tick, 0xFF, bytes([META_END])))
                truncated = False
                break
            payload = take(3)
            if payload is None:
                break
            body = bytes([meta_type]) + payload
            status = 0xFF
        else:
            status = kind | channel
            # a note's key and velocity, a controller's number and value, a
            # bend's low and high byte; a program change is one byte
            rest = b"" if kind == 0xC0 else take(1)
            if rest is None:
                break
            body = first + rest
        delta, pos = _read_delta(data, pos)
        events.append(SeqEvent(tick, status, body, delta))
        if delta is None:               # the data ends before the delta
            break
        tick += delta

    return Seq(version=version, resolution=resolution, tempo=tempo,
               rhythm=rhythm, events=events, size=len(data),
               truncated=truncated)


# ---------------------------------------------------------------------------
# MIDI export
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NoteSpan:
    """A note-on paired with the note-off that ends it."""

    tick: int
    duration: int               # ticks
    channel: int
    note: int
    velocity: int

    @property
    def end(self) -> int:
        return self.tick + self.duration


def note_spans(seq: Seq) -> list[NoteSpan]:
    """Pair note-ons with their note-offs.

    A note-on with velocity 0 is a note-off — Lunar's sequences use that form
    almost exclusively, running-status note-ons being cheaper than switching
    to 0x80. A retrigger closes the previous span rather than nesting, and
    anything still held when the sequence ends is closed there.
    """
    open_notes: dict[tuple[int, int], tuple[int, int]] = {}
    out: list[NoteSpan] = []
    last_tick = 0

    for ev in seq.events:
        last_tick = ev.tick
        if ev.status >= 0xF0 or len(ev.data) < 2:
            continue
        kind = ev.kind
        if kind not in (0x80, 0x90):
            continue
        key = (ev.channel, ev.data[0])
        if kind == 0x90 and ev.data[1] > 0:
            if key in open_notes:
                start, vel = open_notes.pop(key)
                out.append(NoteSpan(start, max(1, ev.tick - start),
                                    ev.channel, ev.data[0], vel))
            open_notes[key] = (ev.tick, ev.data[1])
        elif key in open_notes:
            start, vel = open_notes.pop(key)
            out.append(NoteSpan(start, max(1, ev.tick - start),
                                ev.channel, ev.data[0], vel))

    for (channel, note), (start, vel) in open_notes.items():
        out.append(NoteSpan(start, max(1, last_tick - start), channel, note,
                            vel))

    out.sort(key=lambda n: (n.tick, n.channel, n.note))
    return out


def tempo_map(seq: Seq) -> list[tuple[int, int]]:
    """[(tick, microseconds per quarter)] including the header tempo at 0."""
    out = [(0, seq.tempo)]
    for ev in seq.events:
        if ev.tempo:
            out.append((ev.tick, ev.tempo))
    return out


def _varlen(value: int) -> bytes:
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(out)


def seq_to_midi(seq: Seq) -> bytes:
    """Re-wrap a sequence as a format-0 standard MIDI file.

    The header tempo becomes a leading Set Tempo meta event, since SEQ keeps
    it in the header where MIDI keeps it in the stream. Meta events regain
    the length byte SEQ omits, and running status is expanded, so the result
    needs no special reader. Delta times are rebuilt from absolute ticks, so
    an event the reader skips writes nothing, not even its delta; a data byte
    keeps its low seven bits, as a MIDI data byte has no more.
    """
    track = bytearray()
    track += _varlen(0) + b"\xFF\x51\x03" + seq.tempo.to_bytes(3, "big")

    prev = 0
    saw_end = False
    for ev in seq.events:
        if ev.status == 0xFF:
            if ev.data[0] == META_END:
                body = b"\xFF\x2F\x00"
                saw_end = True
            else:                       # libsnd reads it as a tempo
                body = b"\xFF\x51\x03" + ev.data[1:4]
        elif ev.kind in (0x90, 0xB0, 0xC0, 0xE0):
            body = bytes([ev.status]) + bytes(b & 0x7F for b in ev.data)
        else:
            continue                    # a status or byte the reader skips
        track += _varlen(ev.tick - prev) + body
        prev = ev.tick
    if not saw_end:
        track += _varlen(0) + b"\xFF\x2F\x00"

    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, seq.resolution or 480)
    return header + b"MTrk" + struct.pack(">I", len(track)) + bytes(track)

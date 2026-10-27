"""SEQ sequence parsing — and the meta-event trap.

The trap (docs/spec/sound.md): SEQ meta events are **fixed width and carry
no length byte**. Reading them the MIDI way — status, type, *length*,
payload — desynchronises the stream and silently loses the rest of the
sequence. `test_meta_events_have_no_length_byte` pins both halves: the
correct encoding parses whole, and the MIDI-shaped one does not.
"""

import struct

from decoders.psx.formats import seq
from decoders.testing import be32


def _header(resolution=120, tempo=500_000, rhythm=(4, 2)):
    return (seq.SEQ_MAGIC + be32(1) + struct.pack(">H", resolution)
            + tempo.to_bytes(3, "big") + bytes(rhythm))


NOTE_ON = bytes([0x90, 60, 100])
NOTE_OFF = bytes([0x90, 60, 0])         # a note-on at velocity 0
END = b"\xFF\x2F\x00"


def test_header_fields():
    s = seq.parse_seq(_header(resolution=480, tempo=400_000) + b"\x00" + END)
    assert s.resolution == 480
    assert s.tempo == 400_000
    assert s.rhythm == (4, 2)
    assert not s.truncated


def test_rejects_missing_magic():
    try:
        seq.parse_seq(b"SEQp" + bytes(20))
    except ValueError:
        return
    raise AssertionError("a chunk without 'pQES' must not parse as a SEQ")


def test_meta_events_have_no_length_byte():
    """THE trap. Both directions asserted."""
    tempo_meta = b"\xFF\x51" + (400_000).to_bytes(3, "big")
    body = (b"\x00" + NOTE_ON + b"\x60" + NOTE_OFF
            + b"\x00" + tempo_meta + b"\x00" + END)
    good = seq.parse_seq(_header() + body)
    assert len(good.events) == 4
    assert not good.truncated, "a well-formed sequence must reach its End meta"
    assert [e.name for e in good.events] == [
        "note on", "note on", "meta 0x51", "meta 0x2f"]

    # The tempo payload is the three bytes straight after the meta type,
    # with no length byte between them.
    assert good.events[2].data[1:] == (400_000).to_bytes(3, "big")

    # The same sequence written the MIDI way, with a 0x03 length byte after
    # the meta type. Note what the damage looks like: the stream can
    # RESYNCHRONISE by luck and still yield four events — so an event count
    # is not enough to catch this. What is corrupted is the payload, and
    # through it the tempo.
    midi_shaped = (b"\x00" + NOTE_ON + b"\x60" + NOTE_OFF
                   + b"\x00" + b"\xFF\x51\x03" + (400_000).to_bytes(3, "big")
                   + b"\x00" + END)
    bad = seq.parse_seq(_header() + midi_shaped)
    assert bad.events[2].data[1:] != (400_000).to_bytes(3, "big")
    assert seq.tempo_map(bad) != seq.tempo_map(good)


def test_every_meta_but_the_end_is_read_as_a_tempo():
    # _SsGetMetaEvent takes three bytes and a delta whatever the type is
    body = b"\x00" + b"\xFF\x7A\x07\xA1\x20" + b"\x10" + NOTE_ON + b"\x00" + END
    s = seq.parse_seq(_header() + body)
    assert s.events[0].tempo == 0x07A120
    assert s.events[1].tick == 0x10 and s.events[1].is_note_on
    assert not s.truncated
    assert seq.tempo_map(s) == [(0, 500_000), (0, 0x07A120)]


def test_a_status_the_reader_has_no_case_for_only_sets_the_channel():
    # 0x81: channel 1, nothing read; the key and velocity after it are read
    # under the running status, a note-on — of velocity 0x40, so it sounds
    body = (b"\x00" + NOTE_ON + b"\x60" + bytes([0x81, 62, 0x40])
            + b"\x20" + bytes([64, 0]) + b"\x00" + END)
    s = seq.parse_seq(_header() + body)
    off, struck, after = s.events[1:4]
    assert (off.name, off.data, off.delta) == ("note off (not read)", b"", None)
    assert (struck.status, struck.data, struck.tick) == (0x91, bytes([62, 0x40]), 0x60)
    assert struck.is_note_on
    assert (after.status, after.tick) == (0x91, 0x80)
    assert s.notes == 2


def test_each_delta_is_read_after_its_event():
    body = (b"\x05" + bytes([0xC0, 3]) + b"\x07" + NOTE_ON + b"\x00"
            + bytes([0xB0, 7, 100]) + b"\x09" + END)
    s = seq.parse_seq(_header() + body)
    assert [(e.tick, e.delta) for e in s.events] == [
        (5, 7), (12, 0), (12, 9), (21, None)]


def test_a_bend_keeps_its_second_byte_in_either_form():
    body = (b"\x00" + bytes([0xE2, 0x11, 0x50]) + b"\x00" + bytes([0x22, 0x60])
            + b"\x00" + END)
    s = seq.parse_seq(_header() + body)
    assert [(e.status, e.data) for e in s.events[:2]] == [
        (0xE2, bytes([0x11, 0x50])), (0xE2, bytes([0x22, 0x60]))]


def test_running_status():
    # A data byte with the top bit clear reuses the previous status.
    body = (b"\x00" + NOTE_ON + b"\x10" + bytes([62, 100])
            + b"\x10" + bytes([64, 100]) + b"\x00" + END)
    s = seq.parse_seq(_header() + body)
    assert s.notes == 3
    assert all(e.status == 0x90 for e in s.events if e.is_note_on)


def test_variable_length_delta():
    # 0x81 0x00 is the two-byte encoding of 128.
    body = b"\x81\x00" + NOTE_ON + b"\x00" + END
    s = seq.parse_seq(_header() + body)
    assert s.events[0].tick == 128


def test_a_delta_has_no_length_limit():
    # five bytes: libsnd reads on while bit 7 is set
    body = b"\x00" + NOTE_ON + b"\x81\x80\x80\x80\x00" + END
    s = seq.parse_seq(_header() + body)
    assert s.events[0].delta == 1 << 28 and not s.truncated


def test_truncated_stream_is_flagged_not_raised():
    s = seq.parse_seq(_header() + b"\x00" + NOTE_ON)   # no End meta
    assert s.truncated
    assert s.notes == 1


def test_bpm_from_header_tempo():
    assert seq.parse_seq(_header(tempo=500_000) + b"\x00" + END).bpm == 120.0


def test_channels_and_programs():
    body = (b"\x00" + bytes([0xC1, 7])          # program change, ch 1
            + b"\x00" + bytes([0x92, 60, 90])   # note on, ch 2
            + b"\x00" + END)
    s = seq.parse_seq(_header() + body)
    assert s.channels == [1, 2]
    assert s.programs == [7]


def test_note_spans_pair_on_with_off():
    body = (b"\x00" + NOTE_ON + b"\x60" + NOTE_OFF + b"\x00" + END)
    (span,) = seq.note_spans(seq.parse_seq(_header() + body))
    assert (span.tick, span.duration, span.end) == (0, 96, 96)
    assert (span.channel, span.note, span.velocity) == (0, 60, 100)


def test_zero_velocity_note_on_is_a_note_off():
    body = (b"\x00" + NOTE_ON + b"\x60" + bytes([0x90, 60, 0])
            + b"\x00" + END)
    (span,) = seq.note_spans(seq.parse_seq(_header() + body))
    assert span.end == 96


def _midi_events(midi: bytes) -> list[tuple[int, bytes]]:
    """A format-0 file's (delta, event) pairs, read strictly: every event
    has its own status byte and data bytes below 0x80."""
    track = midi[midi.index(b"MTrk") + 8:]
    sizes = {0x90: 2, 0xB0: 2, 0xC0: 1, 0xE0: 2}
    out, p = [], 0
    while p < len(track):
        delta = 0
        while True:
            c = track[p]
            p += 1
            delta = delta << 7 | c & 0x7F
            if not c & 0x80:
                break
        status = track[p]
        assert status & 0x80, f"no status at {p}"
        n = 3 + track[p + 2] if status == 0xFF else 1 + sizes[status & 0xF0]
        event = track[p:p + n]
        if status != 0xFF:
            assert all(b < 0x80 for b in event[1:]), event.hex()
        out.append((delta, event))
        p += n
    return out


def test_midi_export_writes_nothing_for_an_event_the_reader_skips():
    # a note on, then (10 ticks on) a 0x80 status libsnd does not read
    body = bytes([0x00, 0x90, 0x3C, 0x64, 0x0A, 0x80, 0x3C, 0x00, 0x00]) + END
    parsed = seq.parse_seq(_header() + body)
    events = _midi_events(seq.seq_to_midi(parsed))
    assert all(e[0] != 0x80 for _d, e in events)
    assert sum(d for d, _e in events) == parsed.events[-1].tick


def test_midi_export_adds_the_length_bytes_back():
    """SEQ has no meta length byte; Standard MIDI Files require one."""
    body = b"\x00" + NOTE_ON + b"\x60" + NOTE_OFF + b"\x00" + END
    midi = seq.seq_to_midi(seq.parse_seq(_header() + body))
    assert midi[:4] == b"MThd"
    assert b"MTrk" in midi
    assert midi.rstrip().endswith(b"\xFF\x2F\x00")

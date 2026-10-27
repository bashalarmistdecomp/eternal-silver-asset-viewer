"""Arrangement view — a read-only DAW timeline for a SEQ sequence.

One lane per MIDI channel, notes as bars along a shared bar-numbered
ruler, the way a sequencer's arrangement page shows a song. It answers the
questions the raw event list cannot at a glance: how many parts are playing,
where each one enters and drops out, which are sustained pads and which are
staccato, and where the song's sections are.

Nothing here edits anything. The Sequences view keeps the byte-level event
dump; this is the same data as a timeline. The app draws it
(stage/ArrangementView, from viewer_server.present._arrangement): in
ticks, not pixels, so it can zoom, with a playhead that follows
`tempo_ticks` through the score's tempo changes and loops.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from decoders.psx.formats.seq import Seq, note_spans


@dataclass
class Arrangement:
    """A sequence's notes by lane, and the clock the playhead follows."""

    lanes: list[int] = field(default_factory=list)      # channel per lane
    total_seconds: float = 0.0
    resolution: int = 0
    ticks: int = 0
    #: (channel, tick, duration, note, velocity) per note.
    notes: list[tuple[int, int, int, int, int]] = field(default_factory=list)
    #: channel -> the lane's instrument label.
    lane_labels: dict[int, str] = field(default_factory=dict)
    #: (seconds, tick) breakpoints; tempo is constant between them.
    tempo_ticks: list[tuple[float, int]] = field(default_factory=list)


def arrangement(seq: Seq, program_names: dict[int, str] | None,
                tempo_ticks: list[tuple[float, int]], seconds: float) -> Arrangement:
    """The sequence's notes, a lane for each channel that plays one (or for
    each it names, when none does), timed by `tempo_ticks` over `seconds`."""
    notes = note_spans(seq)
    channels = sorted({n.channel for n in notes}) or seq.channels or [0]
    return Arrangement(lanes=channels, total_seconds=seconds,
                       resolution=seq.resolution, ticks=seq.ticks,
                       notes=[(n.channel, n.tick, n.duration, n.note,
                               n.velocity) for n in notes],
                       lane_labels=dict(program_names or {}),
                       tempo_ticks=tempo_ticks)

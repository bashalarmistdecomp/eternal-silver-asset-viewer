"""A score the app plays live: what Music and Sound banks hand the server to play.

The game keeps no recording of its music. libsnd reads the score once a
sound tick, sends what changed to the SPU, and jumps back at an endless
loop's end, for ever. The app plays a sequence the same way:
`viewer_server.music` runs the score's `seq_synth.Player` a little ahead
of what the app has played, so nothing waits for a whole render and an
endless loop never runs out.

This says what to play and how its time is laid out. Positions are shown
on the score's MAP: the score with its endless loop played `passes` times
and then its ending, which is what the overview draws and what an export
writes by default. Playing does the server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ScoreSource:
    label: str
    #: passes -> a fresh `seq_synth.Player` of the score at the game's
    #: setting; None plays an endless loop for ever
    player: Callable[[int | None], Any]
    #: how many times the map plays an endless loop
    passes: int
    rate: int
    #: output frames of the map, the voices' last release included
    frames: int
    #: the map's output frame where the endless loop's first pass begins,
    #: and its last pass (start, end); None for a score without one
    first_pass: int | None
    loop: tuple[int, int] | None
    #: the whole map's `RenderStats` -> {"text": ..., "info": ...}: the
    #: selection's text and info with what only a full pass measures
    describe: Callable[[Any], dict]

    @property
    def seconds(self) -> float:
        return self.frames / self.rate

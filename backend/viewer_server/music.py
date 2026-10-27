"""Music for the desktop app: a score played live, in chunks the app pulls.

The game keeps no recording of its music: libsnd reads the score once a
sound tick and jumps back at each loop end, for ever. A selected sequence
is played the same way. A MusicStream runs the score's `seq_synth.Player`
as far as the app asks, a few seconds ahead of what it hears, and holds
only the player's state: playback starts at once, and an endless loop
never runs out.

Two clocks:

* stream frames — output samples since the score's start, as this
  stream has played it; with the loop on they grow for ever;
* the MAP — the score with its endless loop played `passes` times, then
  its ending (`ScoreSource`). The transport shows the map: the passes the
  map holds where they lie in it, every later pass in its last pass, and
  the ending after that. Each chunk carries the marks that turn its stream
  frames into map frames and say which part is playing.

A seek replays the score from the start without output up to the asked
place (`Player.skip`), from the latest copy of a player's state taken on
the way (`Player.snapshot`) whose loop ends went as the place needs, so
what follows is exactly what straight play gives there. The OVERVIEW plays
the map once in the background: it draws the waveform, measures what only
a whole pass can (the peak, the most voices at once), and leaves copies of
its state along the map for seeks. It yields to the stream whenever the
stream renders.

Rendering holds the stream's lock, never the session's.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from viewer_server.present import WAVEFORM_COLUMNS as COLUMNS
from viewer_tabs.score import ScoreSource
from viewer_tabs.waveform import StreamEnvelope

#: Frames the overview plays at a time: it yields to the stream between
#: them, so a chunk the app asks for waits a few milliseconds at most.
OVERVIEW_CHUNK = 1 << 14
#: The overview leaves a copy of its state this often along the map, and
#: no more than MAX_COPIES of them (each is about 0.3 MB).
COPY_SECONDS = 10.0
MAX_COPIES = 48
#: The stream keeps a copy of its own state about once a second it plays,
#: the last ROLLING of them: enough to go back over what the app holds
#: ahead when the loop switch changes.
ROLL_SECONDS = 1.0
ROLLING = 8
#: The most frames one request may ask for: about 3 s.
MAX_FRAMES = 1 << 17


class Stale(Exception):
    """A chunk asked for where the stream no longer is (it was moved)."""


@dataclass
class _Copy:
    """A copy of a player's state: where it is and which loop ends it has
    met (`jumps` jumped back, and whether it went on past one)."""
    frame: int
    jumps: int
    went_on: bool
    player: Any

    @classmethod
    def of(cls, player, copy: bool = True) -> "_Copy":
        r = player.reader
        went = r.went_on is not None
        return cls(player.pos, len(r.jumps) - went, went,
                   player.snapshot() if copy else player)

    def fits(self, frame: int, ending: int | None) -> bool:
        """Whether playing on from here reaches `frame` as straight play
        does: a place every loop end jumps back to (`ending` None) or the
        ending the score goes on to at loop end number `ending`. A loop end
        the reader met at or past `frame` must still be open to the switch,
        so a copy that met one there does not fit a place in the loop."""
        if self.frame > frame:
            return False
        if ending is not None:
            return (self.jumps == ending - 1 if self.went_on
                    else self.jumps < ending)
        if self.went_on:
            return False
        tick = self.player.tick_for(frame)
        return not any(j >= tick for j in self.player.reader.jumps)


class Overview(threading.Thread):
    """The map played once in the background."""

    def __init__(self, source: ScoreSource, idle: threading.Event):
        super().__init__(daemon=True, name=f"overview {source.label}")
        self.source = source
        self.idle = idle
        self.stopped = threading.Event()
        self.cond = threading.Condition()
        self.envelope = StreamEnvelope(source.frames, 2, COLUMNS)
        self.copies: list[_Copy] = []
        self.every = max(int(COPY_SECONDS * source.rate),
                         source.frames // MAX_COPIES)
        self.done = False
        self.described: dict | None = None
        self.error: str | None = None

    def run(self) -> None:
        try:
            player = self.source.player(self.source.passes)
            due = self.every
            while not self.stopped.is_set():
                self.idle.wait()                # the live stream goes first
                if self.stopped.is_set():
                    return
                if player.pos >= due and not player.ended:
                    copy = _Copy.of(player)
                    with self.cond:
                        self.copies.append(copy)
                    due += self.every
                pcm = player.read(OVERVIEW_CHUNK)
                if not pcm:
                    break
                with self.cond:
                    self.envelope.add(pcm)
                    self.cond.notify_all()
            if self.stopped.is_set():
                return
            described = self.source.describe(player.result())
            with self.cond:
                self.envelope.close()
                self.described = described
                self.done = True
                self.cond.notify_all()
        except Exception as exc:                # shown, never raised
            with self.cond:
                self.error = f"{type(exc).__name__}: {exc}"
                self.done = True
                self.cond.notify_all()

    def stop(self) -> None:
        self.stopped.set()

    def state(self, have: int, wait: float = 0.0) -> dict:
        """The columns from `have` on, waiting up to `wait` seconds for new
        ones; once done, what the selection shows with the whole pass."""
        with self.cond:
            if wait and not self.done and len(self.envelope.lo) <= have:
                self.cond.wait(wait)
            out = {"columns": self.envelope.columns, "from": have,
                   "lo": self.envelope.lo[have:],
                   "hi": self.envelope.hi[have:], "done": self.done}
            if self.described:
                out.update(self.described)
            if self.error:
                out["error"] = self.error
            return out

    def fitting(self, frame: int, ending: int | None) -> _Copy | None:
        with self.cond:
            fit = [c for c in self.copies if c.fits(frame, ending)]
        return max(fit, key=lambda c: c.frame, default=None)


class MusicStream:
    """One score playing live, pulled a chunk at a time."""

    def __init__(self, source: ScoreSource):
        self.source = source
        self.lock = threading.Lock()
        self.idle = threading.Event()
        self.idle.set()
        self.player = source.player(None)
        self.looping = True
        self.rolling: list[_Copy] = []
        self.overview = Overview(source, self.idle)
        self.overview.start()

    def describe(self) -> dict:
        s = self.source
        return {"rate": s.rate, "channels": 2, "frames": s.frames,
                "passes": s.passes, "firstPass": s.first_pass,
                "loop": list(s.loop) if s.loop else None}

    @contextmanager
    def _busy(self):
        with self.lock:
            self.idle.clear()
            try:
                yield
            finally:
                self.idle.set()

    # -- playing ----------------------------------------------------------

    def pcm(self, start: int, frames: int) -> tuple[bytes, dict]:
        """Frames [start, start + frames) as interleaved 16-bit stereo, and
        where they are: `start` must be where the stream is."""
        frames = max(1, min(MAX_FRAMES, frames))
        with self._busy():
            p = self.player
            if start != p.pos:
                raise Stale(f"the music is at frame {p.pos}, not {start}")
            if not self.rolling or \
                    p.pos - self.rolling[-1].frame >= ROLL_SECONDS * p.rate:
                self.rolling = (self.rolling + [_Copy.of(p)])[-ROLLING:]
            data = p.read(frames)
            n = len(data) // 4
            return data, {"from": start, "frames": n, "done": p.ended,
                          "marks": self._marks(start, start + n)}

    def seek(self, seconds: float, looping: bool) -> dict:
        """Move to a place on the map. A place in the endless loop is its
        first pass there (the loop switch then holds from it); a place in
        the map's ending is the ending, reached as the map reaches it."""
        s = self.source
        frame = max(0, min(int(round(seconds * s.rate)), s.frames - 1))
        ending = s.passes if s.loop and frame >= s.loop[1] else None
        with self._busy():
            self.looping = looping
            self._go(frame, ending, looping)
            return {"from": frame, "marks": self._marks(frame, frame)}

    def set_loop(self, on: bool, frame: int) -> dict:
        """The loop switch, from stream `frame` on (at or after what the
        app has played). A loop end met in what the app holds from there
        that went the other way is played again: {"from": frame}, the app
        drops what it holds from there. Otherwise {"from": None}."""
        with self._busy():
            self.looping = on
            p = self.player
            frame = max(0, min(frame, p.pos))
            tick = p.tick_for(frame)
            r = p.reader
            if r.went_on is not None and r.went_on < tick:
                return {"from": None}           # the ending plays there
            if not any(j >= tick for j in r.jumps):
                p.set_looping(on, frame)
                return {"from": None}
            self._go(frame, None, on)
            return {"from": frame, "marks": self._marks(frame, frame)}

    def _go(self, frame: int, ending: int | None, looping: bool) -> None:
        """Put the player at stream `frame`, replaying from the latest copy
        that fits."""
        here = _Copy.of(self.player, copy=False)
        fit = [c for c in [here, *self.rolling,
                           self.overview.fitting(frame, ending)]
               if c is not None and c.fits(frame, ending)]
        best = max(fit, key=lambda c: (c.frame, c is here), default=None)
        if best is None:
            player = self.source.player(None)
        elif best is here:
            player = self.player
        else:
            player = best.player.snapshot()     # the copy stays as it was
        player.max_ticks = None                 # live: no hour's limit
        player.set_passes(None if ending is None else ending)
        if ending is None:
            player.set_looping(looping, frame)
        player.skip(frame - player.pos)
        self.player = player

    def _marks(self, lo: int, hi: int) -> list:
        """[stream frame, map frame, map limit, part, pass] where the map
        position starts counting from — the one in force at `lo` and any in
        (lo, hi]. Part is "intro", "loop" or "ending" ("" for a score
        without an endless loop); a map position never passes its limit."""
        s, p = self.source, self.player
        if s.loop is None or s.first_pass is None:
            return [[0, 0, s.frames, "", 0]]
        last_start, last_end = s.loop
        marks = [[0, 0, s.first_pass, "intro", 0],
                 [s.first_pass, s.first_pass, last_start, "loop", 1]]
        r = p.reader
        for n, tick in enumerate(r.jumps, start=2):
            at = p.at(tick)
            if tick == r.went_on:
                marks.append([at, last_end, s.frames, "ending", 0])
                break
            if n < s.passes:
                marks.append([at, at, last_start, "loop", n])
            else:
                marks.append([at, last_start, last_end, "loop", n])
        start = max((m for m in marks if m[0] <= lo), key=lambda m: m[0])
        return [start] + [m for m in marks if lo < m[0] <= hi]

    def overview_state(self, have: int, wait: float) -> dict:
        return self.overview.state(have, wait)

    def close(self) -> None:
        self.overview.stop()
        self.idle.set()

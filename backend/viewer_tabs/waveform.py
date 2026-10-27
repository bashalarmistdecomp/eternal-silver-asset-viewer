"""Waveforms for the sound tabs (Music, Sound banks, CD tracks), as the
min/max columns the app draws.

A sample is easier to recognise by shape than by name, and the loop point is
the one piece of ADPCM metadata that changes how a sample is meant to be
heard — so the app draws both. Long samples are reduced by min/max per column
rather than by picking every Nth frame, which keeps transients visible
instead of aliasing them away.
"""

from __future__ import annotations

try:
    import numpy as np
except ImportError:                                   # pragma: no cover
    np = None


def pcm_envelope(pcm: bytes, channels: int, width: int):
    """(min, max) per column for interleaved 16-bit PCM.

    A CD track is six million frames; reducing that with a Python loop takes
    seconds, so this uses numpy when it is available and falls back to a
    strided sample otherwise — the fallback is a rougher picture, not a
    wrong one.
    """
    frames = len(pcm) // (2 * channels)
    if frames <= 0:
        return [], []
    if np is not None:
        data = np.frombuffer(pcm, dtype=np.int16)
        if channels > 1:                     # mono-ise for the picture
            data = data[:frames * channels].reshape(-1, channels).mean(axis=1)
        cols = min(width, frames)
        edges = np.linspace(0, len(data), cols + 1).astype(int)
        lo = np.minimum.reduceat(data, edges[:-1])
        hi = np.maximum.reduceat(data, edges[:-1])
        return lo.tolist(), hi.tolist()

    import struct
    step = max(1, frames // (width * 4))
    vals = [struct.unpack_from("<h", pcm, i * 2 * channels)[0]
            for i in range(0, frames, step)]
    per = max(1, len(vals) / width)
    lo, hi = [], []
    for x in range(min(width, len(vals))):
        chunk = vals[int(x * per):max(int((x + 1) * per), int(x * per) + 1)]
        lo.append(min(chunk))
        hi.append(max(chunk))
    return lo, hi


class StreamEnvelope:
    """`pcm_envelope` of PCM that arrives a piece at a time, its length
    known before it does: `add` each piece, and `lo` / `hi` fill in column
    by column, the columns `pcm_envelope` gives for the whole."""

    def __init__(self, frames: int, channels: int, width: int):
        self.channels = channels
        self.columns = min(width, frames) if frames > 0 else 0
        n = self.columns
        self.edges = [frames * i // n if n else 0 for i in range(n + 1)]
        if np is not None and n:
            self.edges = np.linspace(0, frames, n + 1).astype(int).tolist()
        self.lo: list = []
        self.hi: list = []
        self.at = 0                     # frames added
        self._open = None               # (lo, hi) of the column being filled

    def add(self, pcm: bytes) -> None:
        frames = len(pcm) // (2 * self.channels)
        if not frames or len(self.lo) >= self.columns:
            return
        if np is not None:
            data = np.frombuffer(pcm[:frames * 2 * self.channels],
                                 dtype=np.int16)
            if self.channels > 1:
                data = data.reshape(-1, self.channels).mean(axis=1)
        else:
            import struct
            raw = struct.unpack(f"<{frames * self.channels}h",
                                pcm[:frames * 2 * self.channels])
            data = [sum(raw[i:i + self.channels]) / self.channels
                    for i in range(0, len(raw), self.channels)]
        i = 0
        while i < frames and len(self.lo) < self.columns:
            col = len(self.lo)
            last = col == self.columns - 1
            end = self.edges[col + 1]
            take = frames - i if last else min(frames - i, end - self.at)
            piece = data[i:i + take]
            lo, hi = ((piece.min(), piece.max()) if np is not None
                      else (min(piece), max(piece)))
            if self._open is not None:
                lo, hi = min(lo, self._open[0]), max(hi, self._open[1])
            self.at += take
            i += take
            if not last and self.at >= end:
                self.lo.append(float(lo) if np is not None else lo)
                self.hi.append(float(hi) if np is not None else hi)
                self._open = None
            else:
                self._open = (lo, hi)

    def close(self) -> None:
        """The PCM has ended: the last column is complete."""
        if self._open is not None and len(self.lo) < self.columns:
            lo, hi = self._open
            self.lo.append(float(lo))
            self.hi.append(float(hi))
            self._open = None


def sample_envelope(samples, width: int):
    """(min, max) per column for a decoded mono sample (a list of ints).

    The same reduction as `pcm_envelope`, for the int lists `Vag.decode()`
    returns. The desktop app draws the shape itself from these columns
    instead of receiving a pre-rendered bitmap of it.
    """
    if not samples:
        return [], []
    if np is not None:
        return pcm_envelope(np.asarray(samples, dtype=np.int16).tobytes(),
                            1, width)
    import struct
    return pcm_envelope(struct.pack(f"<{len(samples)}h", *samples), 1, width)


def wav_envelope(wav: bytes, width: int):
    """(min, max, seconds) for a 16-bit PCM RIFF/WAVE blob, or None.

    Read from the blob's own fmt/data chunks — the same walk as
    `audio.wav_duration` — so any decoded .wav can be drawn without
    knowing which decoder wrote it.
    """
    import struct
    if len(wav) < 44 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        return None
    pos, channels, rate, bits = 12, 0, 0, 0
    while pos + 8 <= len(wav):
        cid = wav[pos:pos + 4]
        (size,) = struct.unpack_from("<I", wav, pos + 4)
        body = pos + 8
        if cid == b"fmt " and size >= 16:
            _fmt, channels, rate, _bps, _block, bits = struct.unpack_from(
                "<HHIIHH", wav, body)
        elif cid == b"data":
            if bits != 16 or not channels or not rate:
                return None
            pcm = wav[body:body + size]
            lo, hi = pcm_envelope(pcm, channels, width)
            return lo, hi, len(pcm) / (2 * channels * rate)
        pos = body + size + (size & 1)
    return None

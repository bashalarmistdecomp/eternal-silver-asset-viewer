"""Red Book CD audio tracks — the disc's own audio, read from the BIN.

These are the tracks you would hear putting the disc in a CD player: raw
16-bit stereo 44.1 kHz PCM at 2352 bytes per sector, no encoding at all.
They are a **different thing** from the game's in-game music, which is
sequenced on the SPU from the VAB banks in LUNADATA.FIL
(`decoders.plugins.SLUS_006_28.formats.sound_banks`, `docs/spec/sound.md`). Lunar uses both: the
CD tracks are streamed straight to the audio mixer, the VAB banks are played
by the sound driver a note at a time.

Track layout comes from the cue sheet. A track's `INDEX 00` is its pregap and
`INDEX 01` is where the audio actually starts — for split-BIN rips like
Lunar's the pregap is two seconds of silence at the head of each track file,
so reading from byte zero gives a silent lead-in that is not part of the
music.
"""

from __future__ import annotations

import io
import re
import wave
from dataclasses import dataclass
from pathlib import Path

CD_SECTOR = 2352          # bytes per Red Book sector
CD_RATE = 44100
CD_CHANNELS = 2
CD_FRAMES_PER_SECTOR = CD_SECTOR // 4     # 588 stereo frames


def msf_to_sectors(msf: str) -> int:
    """`MM:SS:FF` (75 frames to the second) -> absolute sector."""
    m = re.match(r"(\d+):(\d+):(\d+)$", msf.strip())
    if not m:
        return 0
    minutes, seconds, frames = (int(g) for g in m.groups())
    return (minutes * 60 + seconds) * 75 + frames


@dataclass
class CdTrack:
    """One audio track, resolved to a byte range in a BIN file."""

    number: int
    path: Path
    start: int            # byte offset of INDEX 01
    size: int             # bytes of audio from `start` to the end of the track
    pregap_sectors: int

    @property
    def frames(self) -> int:
        return self.size // 4

    @property
    def seconds(self) -> float:
        return self.frames / CD_RATE

    @property
    def sectors(self) -> int:
        return self.size // CD_SECTOR

    def read(self, start_frame: int = 0, frames: int | None = None) -> bytes:
        """Raw interleaved 16-bit stereo PCM."""
        offset = self.start + start_frame * 4
        want = self.size - start_frame * 4 if frames is None else frames * 4
        want = max(0, min(want, self.size - start_frame * 4))
        with open(self.path, "rb") as f:
            f.seek(offset)
            return f.read(want)

    def to_wav(self, start_frame: int = 0, frames: int | None = None) -> bytes:
        return pcm_to_wav(self.read(start_frame, frames))


def pcm_to_wav(pcm: bytes, rate: int = CD_RATE,
               channels: int = CD_CHANNELS) -> bytes:
    """Wrap raw interleaved 16-bit PCM in a RIFF/WAVE container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def load_tracks(cue_path: Path | str) -> list[CdTrack]:
    """Resolve every AUDIO track in a cue sheet to a readable byte range.

    Handles the split-BIN layout (one file per track, which is what Lunar's
    rip uses) and the single-BIN layout, where consecutive tracks share a
    file and a track ends where the next one begins.
    """
    from decoders.psx.disc.cue_parser import parse_cue

    sheet = parse_cue(cue_path)
    out: list[CdTrack] = []

    for i, track in enumerate(sheet.tracks):
        if track.is_data or track.file_path is None:
            continue
        path = Path(track.file_path)
        if not path.exists():
            continue

        index1 = msf_to_sectors(track.indices.get(1, "00:00:00"))
        # No INDEX 00: no pregap in the file (a PREGAP line's is not stored)
        index0 = msf_to_sectors(track.indices[0]) if 0 in track.indices else index1
        file_size = path.stat().st_size

        # Same file as the previous track means the cue's MSF values are
        # absolute within that file; a fresh file restarts them at zero.
        shares_file = any(Path(t.file_path or "") == path
                          for t in sheet.tracks[:i])
        start_sector = index1 if not shares_file else index1

        # The track runs to the start of the next one in the same file, or
        # to the end of the file.
        end = file_size
        for later in sheet.tracks[i + 1:]:
            if later.file_path and Path(later.file_path) == path:
                nxt = msf_to_sectors(later.indices.get(0)
                                     or later.indices.get(1, "00:00:00"))
                end = min(end, nxt * CD_SECTOR)
                break

        start = start_sector * CD_SECTOR
        if start >= file_size:
            start = 0
        out.append(CdTrack(number=track.number, path=path, start=start,
                           size=max(0, end - start),
                           pregap_sectors=max(0, index1 - index0)))
    return out

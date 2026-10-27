"""Parse .cue sheet files to extract track information.

A sheet whose every track lies in ONE file that is not there, beside
exactly one .bin, means that .bin: the image was renamed after its sheet
was written (a common state for older single-BIN dumps). The track keeps
the sheet's name in `filename`; `file_path` is the file on disk.

A sheet is read as UTF-8, a byte-order mark before it dropped (a Windows
editor writes one), else in the system's own code page, as older Windows
tools wrote it. A FILE line's name may be quoted or, without a space in
it, not.
"""

from dataclasses import dataclass, field
from pathlib import Path
import locale
import re


@dataclass
class CueTrack:
    number: int
    track_type: str  # "MODE2/2352", "AUDIO", etc.
    filename: str
    file_path: Path = None
    indices: dict[int, str] = field(default_factory=dict)

    @property
    def is_data(self) -> bool:
        return "MODE" in self.track_type


@dataclass
class CueSheet:
    tracks: list[CueTrack]
    source_path: Path

    @property
    def data_track(self) -> CueTrack | None:
        for t in self.tracks:
            if t.is_data:
                return t
        return None

    @property
    def audio_tracks(self) -> list[CueTrack]:
        return [t for t in self.tracks if not t.is_data]


def _text(raw: bytes) -> str:
    """A sheet's text: UTF-8 (a byte-order mark dropped), else the system's
    code page, else Latin-1, which reads any bytes."""
    for encoding in ("utf-8-sig", locale.getencoding()):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1")


def parse_cue(cue_path: Path) -> CueSheet:
    """Parse a .cue file and resolve bin file paths relative to the cue directory."""
    cue_path = Path(cue_path).resolve()
    cue_dir = cue_path.parent
    text = _text(cue_path.read_bytes())

    tracks: list[CueTrack] = []
    current_file = None
    current_track = None

    for line in text.splitlines():
        line = line.strip()

        file_match = re.match(r'FILE\s+(?:"([^"]+)"|(\S+))\s+(\w+)', line)
        if file_match:
            current_file = file_match.group(1) or file_match.group(2)
            continue

        track_match = re.match(r'TRACK\s+(\d+)\s+(.+)', line)
        if track_match:
            current_track = CueTrack(
                number=int(track_match.group(1)),
                track_type=track_match.group(2).strip(),
                filename=current_file,
                file_path=cue_dir / current_file if current_file else None,
            )
            tracks.append(current_track)
            continue

        index_match = re.match(r'INDEX\s+(\d+)\s+(\S+)', line)
        if index_match and current_track:
            current_track.indices[int(index_match.group(1))] = index_match.group(2)

    _resolve_renamed(tracks, cue_dir)
    return CueSheet(tracks=tracks, source_path=cue_path)


def _resolve_renamed(tracks: list[CueTrack], cue_dir: Path) -> None:
    named = {t.filename for t in tracks if t.filename}
    if len(named) != 1 or any(t.file_path and t.file_path.exists() for t in tracks):
        return
    bins = [p for p in cue_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".bin"]
    if len(bins) != 1:
        return
    for t in tracks:
        t.file_path = bins[0]

"""Where a movie's sectors are: what the Video tab hands the app to play.

A movie on a PS1 disc is one sector stream carrying both tracks, laid out
so a double-speed drive delivers them in real time. That is why the sector
index is a clock (sector N plays at N/150 s) and why real playback reads
the DISC IMAGE: an ISO extractor keeps 2048 bytes of each sector, but the
audio sectors carry 2324 and their subheader says how to decode them, so
an extracted `.STR` has no usable audio in it. Video-only playback from
the extracted file is the fallback when no image is on hand.

Decoding is `viewer_server.video`'s job; this only says what to read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Sectors a double-speed drive delivers per second.
SECTORS_PER_SECOND = 150


def raw_track(source: Path | None) -> tuple[Path | None, str]:
    """The data track's raw 2352-byte sectors for the image a dump came from
    (`DiscContext.source`): a cue sheet's data track, or a bare .bin, which
    is one. (None, why) when there is none: an .iso keeps 2048 bytes of each
    sector, as an extracted file does, and a cue sheet's track can be gone."""
    suffix = source.suffix.lower() if source is not None else ""
    if suffix == ".iso":
        return None, f"{source.name} keeps only 2048 bytes of each sector"
    if suffix == ".bin":
        return source, ""
    if suffix != ".cue":
        return None, "the disc image this dump came from is not on hand"
    from decoders.psx.disc.cue_parser import parse_cue
    try:
        data = parse_cue(source).data_track
    except (OSError, ValueError) as ex:
        return None, f"the cue sheet could not be read: {ex}"
    track = Path(data.file_path) if data is not None and data.file_path else None
    if track is None or not track.exists():
        return None, f"the image's data track is missing ({source.name})"
    return track, ""


@dataclass(frozen=True)
class MovieSource:
    label: str
    #: The data track's raw image, or None when only the extracted file is.
    image_path: Path | None
    #: The movie's first sector in the image.
    lba: int
    sectors: int
    #: The extracted .STR, read when there is no image (video only).
    fallback: Path | None = None
    #: A pixel's width over its height as the game shows the movie on a TV
    #: (decoders.psx.formats.display), or None when the program's player
    #: is not known: the app then shows the pixels square.
    pixel_aspect: tuple[int, int] | None = None
    #: Where that shape comes from, for the app to show.
    shape_note: str = ""

    @property
    def duration(self) -> float:
        return self.sectors / SECTORS_PER_SECOND

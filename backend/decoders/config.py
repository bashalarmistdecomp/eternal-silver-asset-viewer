"""Where the library is, and the PlayStation's sector sizes.

The library is one folder, chosen by whoever runs the viewer (the app's
setup screen, `server.py --library`, or ASSET_VIEWER_LIBRARY). Everything
the viewer reads or writes is under it:

    <library>/discs/                  disc images (optional: an image can be
                                      extracted from anywhere)
    <library>/<program>/raw/<disc>/   one extracted disc
    <library>/<program>/exports/      what the viewer's Export writes
    <library>/<program>/index/<disc>.zip
                                      what the viewer keeps of one disc's
                                      reading (viewer_server.index)

Every root is keyed by the PROGRAM a disc boots, never by the disc: both
discs of a two-disc game boot one byte-identical executable, so they share
one root and its exports. This module is the only place these paths are
spelled.
"""

import os
import sys
from pathlib import Path

#: The variable naming the library. server.py sets it from --library before
#: this module is imported, because every path below is resolved once.
LIBRARY_ENV = "ASSET_VIEWER_LIBRARY"


def _default_library() -> Path:
    """The library when none is named: the user's data folder."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "eternal-silver-asset-viewer" / "library"


LIBRARY: Path = (Path(os.environ[LIBRARY_ENV]).expanduser().resolve()
                 if os.environ.get(LIBRARY_ENV) else _default_library())

#: Disc images, under human filenames. Identity comes from the image's
#: checksum (gamedb), not from its name.
DISCS_DIR: Path = LIBRARY / "discs"

#: Where an extraction is written before it is moved into its program's
#: root: each in a folder of its own named after this one (".extracting-
#: <random>", extractor._staging). Inside the library, so the move stays
#: on one filesystem.
EXTRACTING_DIR: Path = LIBRARY / ".extracting"

SECTOR_SIZE: int = 2048
RAW_SECTOR_SIZE: int = 2352
MODE2_DATA_OFFSET: int = 24


def _folder(name: str) -> str:
    """`name`, which must name one folder: not empty, "." or "..", and no
    path of its own (a separator, a drive). ValueError otherwise: a
    program or disc comes from a dump's meta.json when gamedb does not
    know it, and nothing is written outside the library for one."""
    if name in ("", ".", "..") or Path(name).name != name:
        raise ValueError(f"{name!r} is not the name of a folder of the library")
    return name


def game_dir(program: str) -> Path:
    """<library>/<program> — the root for one program's discs."""
    return LIBRARY / _folder(program)


def raw_dir(program: str, disc: str | None = None) -> Path:
    """<library>/<program>/raw/<disc> — one extracted disc.

    `disc` is the member disc's own serial, defaulting to `program` (the
    single-disc case)."""
    return game_dir(program) / "raw" / _folder(disc or program)


def exports_dir(program: str) -> Path:
    """<library>/<program>/exports — what the viewer's Export writes."""
    return game_dir(program) / "exports"


def index_file(raw: Path) -> Path:
    """<library>/<program>/index/<disc>.zip — the index of the disc
    extracted at `raw` (<library>/<program>/raw/<disc>)."""
    raw = Path(raw)
    return raw.parent.parent / "index" / f"{raw.name}.zip"

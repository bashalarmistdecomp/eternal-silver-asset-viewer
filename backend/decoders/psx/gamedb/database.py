"""Game database lookup logic."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from decoders import config
from decoders.config import DISCS_DIR
from decoders.psx.gamedb.known_games import (
    GameInfo, KNOWN_CHECKSUMS, DISC_ID_LOOKUP,
    disc_display, disc_position, program_of,
)

DISC_SUFFIXES = (".cue", ".iso", ".bin", ".cdr", ".img")

#: A disc id a dump's meta.json may give: a serial ("SLUS_006.28") or a
#: volume id, letters, digits, "_" and ".", never only dots. For a disc
#: gamedb does not know it becomes the program, and so a folder of the
#: library, and the library may be someone else's.
PLAIN_ID = re.compile(r"[A-Z0-9][A-Z0-9_.]*")


@dataclass
class InstalledGame:
    """One extracted disc dump, identified against gamedb.

    `path` is the member disc directory (<library>/<program>/raw/<disc>) — what
    callers open files from. Everything below `source` is IDENTITY, and it
    is resolved live against gamedb rather than trusted from the meta.json
    written at extraction time: a catalogue row can be corrected after a
    dump lands (SLUS_009.21 was), and a stale copy on disk would go on
    displaying the superseded answer forever.
    """

    disc_id: str
    title: str
    region: str
    path: Path
    has_lunadata: bool
    source: Path | None = None   # disc image, re-resolved if the repo moved

    #: The program this disc BOOTS — the game root its bytes live under.
    program: str = ""
    #: Position in the program's disc set (1 of 1 for a single-disc program).
    disc_number: int = 1
    disc_count: int = 1
    #: "game" | "bonus" | "demo" — a bonus disc boots its own program.
    role: str = "game"
    volume_id: str = ""
    #: sha256 of the data track, as recorded at extraction.
    checksum: str = ""
    #: HOW the identity above was reached. "checksum" is the only exact
    #: answer (KNOWN_CHECKSUMS is the proof); "serial" trusts the
    #: BOOT line in the dump; "unrecognized" means gamedb cannot place it
    #: and every field above it is the dump's own claim about itself.
    identified_by: str = "unrecognized"
    #: Ready-made human label — see known_games.disc_display.
    label: str = ""


def resolve_disc_source(source: str | Path | None,
                        disc_dir: Path | None = None) -> Path | None:
    """Locate the disc image a game was extracted from.

    `meta.json` records an absolute path at extraction time, so moving the
    image (or the library) leaves that path dangling. Rather than treating
    the game as unusable, fall back to matching the recorded filename
    underneath the library's `discs/`.

    Returns None when nothing plausible is found — callers should then ask the
    user rather than guessing between unrelated disc images.
    """
    if source:
        recorded = Path(source)
        if recorded.exists():
            return recorded
    else:
        recorded = None

    root = disc_dir or DISCS_DIR
    if not root.is_dir():
        return None

    candidates = [p for p in root.rglob("*")
                  if p.is_file() and p.suffix.lower() in DISC_SUFFIXES]
    if not candidates:
        return None

    if recorded is not None:
        # Same filename somewhere under discs/ — the image simply moved.
        for p in candidates:
            if p.name == recorded.name:
                return p
        # Same disc, different container (.cue vs .bin vs .iso).
        for p in candidates:
            if p.stem == recorded.stem:
                return p
        # A name was recorded and nothing matches it. Do not substitute some
        # other image lying in discs/ — it could be a different disc.
        return None

    # Nothing recorded to match: only answer when there is no ambiguity.
    cues = [p for p in candidates if p.suffix.lower() == ".cue"]
    if len(cues) == 1:
        return cues[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


def read_meta(game_dir: Path) -> dict:
    """Read a game's meta.json, or {} if missing/corrupt (or not an
    object)."""
    meta_path = game_dir / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _text(meta: dict, key: str, default: str = "") -> str:
    """meta.json's `key`, where it is a string."""
    value = meta.get(key)
    return value if isinstance(value, str) else default


class GameDatabase:

    def lookup_by_checksum(self, sha256: str) -> GameInfo | None:
        return KNOWN_CHECKSUMS.get(sha256)

    def lookup_by_disc_id(self, disc_id: str) -> GameInfo | None:
        return DISC_ID_LOOKUP.get(disc_id)

    def get_installed_games(self) -> list[InstalledGame]:
        """Every extracted disc dump, across every game root.

        Raw extraction is strictly per-disc and nests two deep now —
        `<library>/<program>/raw/<member-disc>/` — so a 2-disc release is two
        entries under one game root. `path` stays the member dir, which is
        what callers open LUNADATA.FIL from.
        """
        if not config.LIBRARY.exists():
            return []

        games = []
        for game_root in sorted(config.LIBRARY.iterdir()):
            raw = game_root / "raw"
            if not raw.is_dir():
                continue
            for d in sorted(raw.iterdir()):
                if not d.is_dir() or not (d / "meta.json").exists():
                    continue
                meta = read_meta(d)
                if not meta:
                    continue

                games.append(self.identify(d, meta))

        return games

    def identify(self, disc_dir: Path, meta: dict | None = None) -> InstalledGame:
        """Resolve one extracted dump to an identity.

        The chain is the same one the extraction identifies a disc image
        by (extractor.DiscExtractor; extractor.disc_identity reads its
        serial): the image CHECKSUM is the only exact answer, the serial
        in the dump's own SYSTEM.CNF is the fallback, and a disc gamedb
        cannot place is reported as unrecognized rather than quietly given
        a neighbour's title. A disc id that is not PLAIN_ID is not taken:
        the dump's folder names it instead.
        """
        meta = read_meta(disc_dir) if meta is None else meta
        disc_id = _text(meta, "disc_id")
        if not PLAIN_ID.fullmatch(disc_id):
            disc_id = disc_dir.name
        checksum = _text(meta, "checksum")

        info = KNOWN_CHECKSUMS.get(checksum) if checksum else None
        identified_by = "checksum" if info else ""
        if info is None:
            info = DISC_ID_LOOKUP.get(disc_id)
            identified_by = "serial" if info else "unrecognized"

        # A checksum row and a serial row can disagree only if the tables
        # drift; known_games.check_consistency() is what catches that, and
        # the checksum wins here because it is the measured one.
        if info is not None:
            disc_id = info.disc_id
            number, count = disc_position(disc_id)
            label = disc_display(disc_id)
        else:
            number, count = 1, 1
            label = f"(unidentified disc) ({disc_id})"

        return InstalledGame(
            disc_id=disc_id,
            title=info.title if info else _text(meta, "title", disc_dir.name),
            region=info.region if info else _text(meta, "region", "Unknown"),
            path=disc_dir,
            has_lunadata=(disc_dir / "LUNADATA.FIL").exists(),
            source=resolve_disc_source(_text(meta, "source") or None),
            program=program_of(disc_id),
            disc_number=number,
            disc_count=count,
            role=info.role if info else "game",
            volume_id=(info.disc_label if info else "") or _text(meta, "volume_id"),
            checksum=checksum,
            identified_by=identified_by,
            label=label,
        )

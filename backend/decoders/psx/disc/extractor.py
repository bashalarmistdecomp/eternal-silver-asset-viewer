"""Orchestrates disc image extraction into the data directory."""

import json
import os
import re
import secrets
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from decoders import config
from decoders.config import raw_dir
from decoders.psx.disc.cue_parser import parse_cue
from decoders.psx.disc.checksum import sha256_file
from decoders.psx.disc.iso_reader import DiscImage, ISO9660Reader
from decoders.psx.gamedb.database import GameDatabase
from decoders.psx.gamedb.known_games import program_meta, program_of

#: The most a SYSTEM.CNF, or a root directory, is read of when a disc is
#: identified (`disc_identity`): a disc's are a sector or two.
_IDENTITY_LIMIT = 64 << 10
#: A staging folder (`_staging`) untouched for this long was left by a
#: backend that stopped mid-extraction: no live one goes this long
#: without writing a file.
STAGING_STALE = 3600.0


def boot_serial(text: str) -> str | None:
    """The program SYSTEM.CNF's BOOT line starts ("SLUS_006.28"): the
    disc's serial."""
    match = re.search(r"BOOT\s*=\s*cdrom:\\?([^;\s]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def disc_identity(disc_path: Path) -> tuple[str | None, str]:
    """(serial, volume id) of the disc image at `disc_path` (a cue sheet,
    or an .iso or .bin), read from its volume descriptor and SYSTEM.CNF
    alone, as `extract` reads them, without reading the image whole. The
    serial is None for a disc with no SYSTEM.CNF or no BOOT line in it.
    ValueError for a file that holds no ISO 9660 volume, OSError for an
    image that is not there."""
    disc_path = Path(disc_path)
    if disc_path.suffix.lower() == ".cue":
        data = parse_cue(disc_path).data_track
        if data is None:
            raise ValueError("its cue sheet names no data track")
        if not data.file_path or not data.file_path.exists():
            raise FileNotFoundError(f"its data track is missing: "
                                    f"{data.file_path.name if data.file_path else '?'}")
        image_path, modes = data.file_path, (True,)
    else:
        image_path, modes = disc_path, (False, True)
    with DiscImage(image_path) as image:
        for raw_mode2 in modes:
            iso = ISO9660Reader(image, raw_mode2=raw_mode2)
            try:
                pvd = iso.read_pvd()
            except ValueError:
                continue
            root = iso.read_directory(pvd["root_lba"], min(pvd["root_size"], _IDENTITY_LIMIT))
            cnf = next((e for e in root if not e.is_directory
                        and e.name.upper() == "SYSTEM.CNF" and e.size <= _IDENTITY_LIMIT), None)
            serial = (boot_serial(iso.extract_file(cnf).decode("ascii", errors="replace"))
                      if cnf is not None else None)
            return serial, pvd["volume_id"]
    raise ValueError("not a disc image: it holds no ISO 9660 volume")


def data_track_range(cue) -> tuple[int, int | None]:
    """The bytes of the data track's file that are the data track. gamedb's
    checksums are of the data track alone (a split-BIN rip's Track 1
    file); a single-BIN image holds the audio tracks after it, so the data
    track ends where the next track in its file begins (its INDEX 00, else
    its INDEX 01: a PREGAP line's silence is not in the file)."""
    from decoders.psx.disc.cd_audio import CD_SECTOR, msf_to_sectors
    data = cue.data_track
    start = msf_to_sectors(data.indices.get(0) or data.indices.get(1, "00:00:00"))
    after = cue.tracks[cue.tracks.index(data) + 1:]
    for t in after:
        if t.file_path == data.file_path:
            end = msf_to_sectors(t.indices.get(0) or t.indices.get(1, "00:00:00"))
            return start * CD_SECTOR, end * CD_SECTOR
    return start * CD_SECTOR, None


def _staging() -> Path:
    """A new staging folder of this extraction's own, in the library (the
    final rename stays on one filesystem): <library>/.extracting-<random>.
    Two backends on one library (two windows of the app) each stage apart.
    Folders a stopped backend left (STAGING_STALE) are removed first."""
    base = config.EXTRACTING_DIR
    base.parent.mkdir(parents=True, exist_ok=True)
    for old in base.parent.glob(f"{base.name}*"):
        try:
            touched = max([old.stat().st_mtime]
                          + [e.stat().st_mtime for e in os.scandir(old)])
        except OSError:
            continue
        if time.time() - touched > STAGING_STALE:
            shutil.rmtree(old, ignore_errors=True)
    staging = base.with_name(f"{base.name}-{secrets.token_hex(6)}")
    staging.mkdir()
    return staging


def _rename(src: Path, dst: Path, tries: int = 8) -> None:
    """`src` renamed to `dst`, tried again while Windows says a file in it
    is held open (the indexer, a virus scanner reading a new file)."""
    for attempt in range(tries):
        try:
            src.rename(dst)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.25 * (attempt + 1))


def _remove(folder: Path, tries: int = 8) -> None:
    """`folder` deleted, tried again while a file in it is held open; one
    still held is left to a later extraction's sweep (`_staging`)."""
    for attempt in range(tries):
        try:
            shutil.rmtree(folder)
            return
        except FileNotFoundError:
            return
        except OSError as ex:
            if attempt == tries - 1:
                print(f"{folder} was left to be removed later: {ex}", file=sys.stderr)
                return
            time.sleep(0.25 * (attempt + 1))


@dataclass
class ExtractResult:
    disc_id: str
    title: str
    region: str
    output_dir: Path
    files_extracted: list[str]
    #: gamedb knew the disc by its image's checksum, the one exact answer;
    #: False when it went by the serial its SYSTEM.CNF boots alone
    #: (`identified_by`), or knew it not at all
    recognized: bool
    #: "checksum" | "serial" | "unrecognized" (gamedb.InstalledGame's)
    identified_by: str = "checksum"


class DiscExtractor:
    """Extracts a PS1 disc image into the data directory."""

    def __init__(self, progress_cb=None):
        self._progress = progress_cb or (lambda *a: None)
        self._db = GameDatabase()

    def extract(self, disc_path: Path,
                allow_unknown: bool = False) -> ExtractResult:
        """Auto-detect format and extract.

        `allow_unknown=False` (the default) refuses to mint a NEW game root
        for a disc gamedb cannot place — an unknown serial landing silently
        would put bytes under an unadjudicated identity. Add the measured
        row to gamedb first (the SLUS_009.21 lesson: read SYSTEM.CNF, then
        record), or pass allow_unknown=True deliberately.

        A disc image cut short or damaged, or a file of it that cannot be
        written, fails the extraction (iso_reader.ISO9660Reader.extract_all):
        a dump with files missing is never added."""
        disc_path = Path(disc_path).resolve()
        self._allow_unknown = allow_unknown
        suffix = disc_path.suffix.lower()

        if suffix == ".cue":
            return self._extract_cue(disc_path)
        elif suffix in (".iso", ".bin"):
            return self._extract_iso(disc_path)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

    def _extract_cue(self, cue_path: Path) -> ExtractResult:
        self._progress("Parsing cue sheet...", 0, 0)
        cue = parse_cue(cue_path)
        data_track = cue.data_track
        if not data_track:
            raise ValueError("No data track found in cue sheet")

        bin_path = data_track.file_path
        if not bin_path or not bin_path.exists():
            raise FileNotFoundError(f"Data track bin not found: {bin_path}")

        self._progress("Checksumming disc image...", 0, 0)
        checksum = sha256_file(bin_path, *data_track_range(cue))

        self._progress("Reading disc image...", 0, 0)
        raw_data = bin_path.read_bytes()

        # tracks after the data track: a file of its directory may lie in
        # them (ISO9660Reader), past the end of what the data's file holds
        after = cue.tracks[cue.tracks.index(data_track) + 1:]
        iso = ISO9660Reader(raw_data, raw_mode2=True, other_tracks=bool(after))
        return self._do_extract(iso, checksum, cue_path)

    def _extract_iso(self, iso_path: Path) -> ExtractResult:
        self._progress("Checksumming disc image...", 0, 0)
        checksum = sha256_file(iso_path)

        self._progress("Reading disc image...", 0, 0)
        raw_data = iso_path.read_bytes()

        # Try plain ISO first, fall back to MODE2
        try:
            iso = ISO9660Reader(raw_data, raw_mode2=False)
            iso.read_pvd()
        except ValueError:
            iso = ISO9660Reader(raw_data, raw_mode2=True)

        return self._do_extract(iso, checksum, iso_path)

    def _do_extract(self, iso: ISO9660Reader, checksum: str,
                    source_path: Path) -> ExtractResult:
        pvd = iso.read_pvd()
        self._progress(f"Volume: {pvd['volume_id']}", 0, 0)

        # Extract to a temp name first, rename once we know the disc ID.
        # The serial comes out of SYSTEM.CNF *inside* the dump, so it is not
        # known yet: stage in a folder of this extraction's own, in the
        # library, and remove it whatever goes wrong.
        tmp_dir = _staging()
        try:
            return self._place(iso, pvd, checksum, source_path, tmp_dir)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _place(self, iso: ISO9660Reader, pvd: dict, checksum: str,
               source_path: Path, tmp_dir: Path) -> ExtractResult:
        files = iso.extract_all(tmp_dir, progress_cb=self._on_file_progress)

        # Parse disc ID from SYSTEM.CNF
        disc_id = self._read_disc_id(tmp_dir)
        if not disc_id:
            disc_id = pvd["volume_id"].replace(" ", "_")[:20] or "UNKNOWN"

        # Look up game info
        game_info = self._db.lookup_by_checksum(checksum)
        identified_by = "checksum"
        if not game_info:
            game_info = self._db.lookup_by_disc_id(disc_id)
            identified_by = "serial" if game_info else "unrecognized"

        title = game_info.title if game_info else pvd["volume_id"]
        region = game_info.region if game_info else "Unknown"

        if game_info is None and not getattr(self, "_allow_unknown", False):
            raise ValueError(f"a disc the viewer does not know ({disc_id}), "
                             f"so it was not added")

        # Write metadata, in the staging folder: a dump is never without it.
        meta = {
            "disc_id": disc_id,
            "title": title,
            "region": region,
            "volume_id": pvd["volume_id"],
            "checksum": checksum,
            "source": str(source_path),
            "extract_date": datetime.now().isoformat(),
            "files": files,
        }
        (tmp_dir / "meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

        # Move to final directory: <library>/<program>/raw/<this disc>. The
        # outer key answers WHICH PROGRAM, the inner WHICH DISC it shipped
        # on; program_of() resolves a later disc of a multi-disc title to
        # the program's root, and is the identity for a single-disc title.
        # A dump there already is renamed aside first and deleted last, so
        # one whose file is held open (Windows) stays whole, not half gone.
        final_dir = raw_dir(program_of(disc_id), disc_id)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        aside = None
        if final_dir.exists():
            aside = tmp_dir.with_name(f"{tmp_dir.name}-replaced")
            try:
                _rename(final_dir, aside)
            except PermissionError as ex:
                raise PermissionError(
                    f"the disc's folder {final_dir} could not be replaced "
                    f"({ex.strerror or ex}): if another window of the app or a "
                    f"virus scan holds a file of it, close it and try again") from None
            try:
                os.utime(aside)             # not a stale one to sweep (_staging)
            except OSError:
                pass
        try:
            _rename(tmp_dir, final_dir)
        except OSError:
            if aside is not None:
                _rename(aside, final_dir)   # the old dump, back as it was
            raise
        if aside is not None:
            _remove(aside)

        # Self-description at the game root: the tree must read without
        # gamedb in hand.
        program = program_of(disc_id)
        game_root = final_dir.parent.parent
        (game_root / "program.json").write_text(
            json.dumps(program_meta(program), indent=2) + "\n",
            encoding="utf-8",
        )

        return ExtractResult(
            disc_id=disc_id,
            title=title,
            region=region,
            output_dir=final_dir,
            files_extracted=files,
            recognized=identified_by == "checksum",
            identified_by=identified_by,
        )

    def _on_file_progress(self, filename, done, total):
        self._progress(f"Extracting {filename}...", done, total)

    @staticmethod
    def _read_disc_id(directory: Path) -> str | None:
        cnf = directory / "SYSTEM.CNF"
        if not cnf.exists():
            return None
        return boot_serial(cnf.read_text(encoding="ascii", errors="replace"))

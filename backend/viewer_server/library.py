"""The library: one slot per game, holding every disc of every version.

A game (gamedb's GAMES) is its own program and every program related to
it: Lunar 1's slot holds both US discs, the Japanese discs, the demo and
the making-of disc. A slot lists each disc gamedb knows of, whether it is
extracted, waiting in `<library>/discs/`, or not added yet, and opens as
one game (viewer_server.session).

On disk nothing changes: `<library>/<program>/raw/<disc>/` still keys by
the PROGRAM a disc boots. Identity comes from gamedb through
`InstalledGame`; when it is not a checksum match the disc says so.

Discs that belong to no game are listed apart, by program, and images in
`discs/` that nothing names yet are listed for extraction.

Discs are added by the batch (`scan`, `reextract_rows`): a list of the
images to extract, each a row the app shows, which an import job
(viewer_server.routes) extracts one after another.
"""

from __future__ import annotations

import os
from pathlib import Path

from decoders import config
from decoders._env import system_env
from decoders.psx.gamedb.database import GameDatabase, InstalledGame, read_meta
from decoders.psx.gamedb.known_games import (
    DISC_ID_LOOKUP, GAMES, disc_display, disc_tag, discs_of, game_of,
    game_programs, program_of,
)

#: Shown only when identity is NOT exact (mirrors LibraryView.IDENTITY_WARN).
IDENTITY_WARN = {
    "serial": ("identified by SYSTEM.CNF only", "warn"),
    "unrecognized": ("not in gamedb", "danger"),
}

DISC_SUFFIXES = (".cue", ".iso", ".bin")
#: How far under a folder its disc images are looked for (`images_in`): a
#: folder of a game's, a folder of each disc's in it, and one more.
SCAN_DEPTH = 3


def folder() -> dict:
    """Where this backend reads from — what the app's library screen shows."""
    return {
        "path": str(config.LIBRARY),
        "discs": str(config.DISCS_DIR) if config.DISCS_DIR.is_dir() else None,
        "exists": config.LIBRARY.is_dir(),
    }


def game_key(game: InstalledGame) -> str:
    """A stable id for one dump: its path under the library, e.g.
    SLUS_006.28/raw/SLUS_008.99 — unique by construction."""
    try:
        return game.path.relative_to(config.LIBRARY).as_posix()
    except ValueError:
        return game.path.as_posix()


def find_game(key: str) -> InstalledGame | None:
    for game in GameDatabase().get_installed_games():
        if game_key(game) == key:
            return game
    return None


def _heading(game: InstalledGame) -> str:
    if game.role == "bonus":
        return "Bonus disc"
    if game.role == "demo":
        return "Demo disc"
    if game.disc_count > 1:
        return f"Disc {game.disc_number} of {game.disc_count}"
    return "Disc 1"


def _disc_row(game: InstalledGame) -> dict:
    files, total = 0, 0
    readable = True
    try:
        for p in game.path.iterdir():
            if p.is_file() and p.name != "meta.json" and not p.name.startswith("."):
                files += 1
                total += p.stat().st_size
    except OSError:
        readable = False
    warn = IDENTITY_WARN.get(game.identified_by)
    return {
        "key": game_key(game),
        "discId": game.disc_id,
        "label": game.label,
        "heading": _heading(game),
        "region": game.region,
        "volumeId": game.volume_id,
        "role": game.role,
        "files": files,
        "bytes": total,
        "readable": readable,
        "source": str(game.source) if game.source else None,
        "identifiedBy": game.identified_by,
        "warning": {"text": warn[0], "tone": warn[1]} if warn else None,
        "hasLunadata": game.has_lunadata,
    }


def _image_for(path: Path) -> Path:
    """The file to extract `path` from: the cue sheet whose tracks lie in
    it when there is one (renamed images included, cue_parser), because
    the track layout (CD-DA, where the data track ends) lives there, not in
    the data track. A sheet's suffix is matched in any case (LUNAR.CUE)."""
    from decoders.psx.disc.cue_parser import parse_cue
    if path.suffix.lower() == ".cue" or not path.parent.is_dir():
        return path
    for cue in sorted(p for p in path.parent.iterdir() if p.suffix.lower() == ".cue"):
        try:
            tracks = parse_cue(cue).tracks
        except OSError:
            continue
        if any(t.file_path and t.file_path.resolve() == path.resolve()
               for t in tracks):
            return cue
    return path


def _pool(installed: list[InstalledGame]) -> list[dict]:
    """Disc images in <library>/discs/ with no dump yet, each listed by its
    file name: it is identified when it is extracted."""
    sources = {g.source.resolve() for g in installed if g.source}
    out, listed = [], set()
    if config.DISCS_DIR.is_dir():
        for p in sorted(config.DISCS_DIR.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in DISC_SUFFIXES:
                continue
            if _image_for(p) != p:
                continue        # a track: its cue sheet is listed instead
            if p.resolve() in listed or p.resolve() in sources:
                continue        # listed already, or extracted
            listed.add(p.resolve())
            out.append({"serial": "", "title": p.stem, "label": "",
                        "path": str(p), "sha256": "", "bytes": p.stat().st_size})
    out.sort(key=lambda r: (r["title"], r["serial"]))
    return out


def _slot_disc(serial: str, present: InstalledGame | None,
               pool: dict | None) -> dict:
    """One disc of a slot: extracted, waiting in discs/, or not added. An
    extracted one says how far its index is (viewer_server.index): ready,
    being made, or not yet."""
    from viewer_server.index import INDEXER
    return {
        "serial": serial,
        "tag": disc_tag(serial),
        "label": present.label if present else disc_display(serial),
        "state": ("present" if present else "in-folder" if pool else "missing"),
        "disc": ({**_disc_row(present), "index": INDEXER.status(present)}
                 if present else None),
        "pool": pool,
    }


def _slot(key: str, title: str, programs: tuple[str, ...],
          installed: list[InstalledGame], pool: dict[str, dict]) -> dict:
    present = {g.disc_id: g for g in installed if g.program in programs}
    serials: list[str] = []
    for program in programs:
        for serial in discs_of(program):
            if serial not in serials:
                serials.append(serial)
    # A disc gamedb files under the program but does not list (it should
    # not happen; check_consistency guards it) still shows.
    serials += [s for s in present if s not in serials]
    rank = {p: i for i, p in enumerate(programs)}

    def order(serial: str):
        g = present.get(serial)
        program = g.program if g else _program_of(serial, programs)
        info = DISC_ID_LOOKUP.get(serial)
        return (rank.get(program, len(rank)), info.disc_number if info else 1)

    serials.sort(key=order)
    return {
        "key": key,
        "title": title,
        "programs": list(programs),
        "discs": [_slot_disc(s, present.get(s), pool.get(s)) for s in serials],
        "present": len(present),
        "partial": partial(key),
    }


def partial(key: str) -> bool:
    """Whether a slot is a game the viewer does not read in full yet: no tab
    serves its own program by name (a provider's `programs`), so it opens
    with only the tabs any PlayStation disc has. Lunar 2 today. A disc of
    no game ("program:<serial>") is never partial: nothing more is promised
    for it."""
    from viewer_tabs.tab_providers import PROVIDER_CLASSES
    game = next((g for g in GAMES if g.key == key), None)
    return game is not None and not any(
        game.program in getattr(cls, "programs", ()) for cls in PROVIDER_CLASSES)


def _program_of(serial: str, programs: tuple[str, ...]) -> str:
    for program in programs:
        if serial in discs_of(program):
            return program
    return serial


def library() -> dict:
    installed = GameDatabase().get_installed_games()
    pool_rows = _pool(installed)
    pool = {r["serial"]: r for r in pool_rows if r["serial"]}
    slots = [_slot(g.key, g.title, game_programs(g), installed, pool)
             for g in GAMES]

    # Discs of no game: each program its own slot, holding what is here.
    others: dict[str, list[str]] = {}
    for g in installed:
        if game_of(g.program) is None:
            others.setdefault(g.program, [])
    for serial in pool:
        if game_of(program_of(serial)) is None:
            others.setdefault(program_of(serial), [])
    other_slots = []
    for program in sorted(others):
        info = DISC_ID_LOOKUP.get(program)
        slot = _slot(f"program:{program}", info.title if info else program,
                     (program,), installed, pool)
        slot["discs"] = [d for d in slot["discs"] if d["state"] != "missing"]
        other_slots.append(slot)
    return {"folder": folder(), "games": slots, "others": other_slots,
            "unsorted": [r for r in pool_rows if not r["serial"]]}


def game_members(key: str) -> tuple[str, list[InstalledGame]]:
    """A slot's title and its extracted discs, in the slot's order: the
    game's own discs, then its versions', the demo's, the bonus discs'."""
    if key.startswith("program:"):
        programs = (key.removeprefix("program:"),)
        info = DISC_ID_LOOKUP.get(programs[0])
        title = info.title if info else programs[0]
    else:
        game = next((g for g in GAMES if g.key == key), None)
        if game is None:
            raise KeyError(f"no game {key!r}")
        programs, title = game_programs(game), game.title
    rank = {p: i for i, p in enumerate(programs)}
    members = [g for g in GameDatabase().get_installed_games()
               if g.program in rank]
    members.sort(key=lambda g: (rank[g.program], g.disc_number))
    return title, members


def _slot_of(serial: str) -> tuple[str, str]:
    """(key, title) of the slot a disc joins: its game's, or its program's
    own where it belongs to no game."""
    program = program_of(serial)
    owner = game_of(program)
    if owner is not None:
        return owner.key, owner.title
    info = DISC_ID_LOOKUP.get(program)
    return f"program:{program}", info.title if info else program


def extract(job, disc_path: str) -> dict:
    """Extract one disc image into <library>/<program>/raw/<disc>/ (a job body)."""
    from decoders.psx.disc.extractor import DiscExtractor

    path = Path(disc_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"not found: {path}")
    if path.suffix.lower() not in DISC_SUFFIXES:
        raise ValueError(f"not a disc image (.cue, .iso or .bin): {path.name}")
    config.LIBRARY.mkdir(parents=True, exist_ok=True)

    def on_progress(message, current, total):
        job.progress(message, current, total)

    result = DiscExtractor(progress_cb=on_progress).extract(_image_for(path))
    key = None
    for game in GameDatabase().get_installed_games():
        if game.disc_id == result.disc_id:
            key = game_key(game)
            break
    slot, title = _slot_of(result.disc_id)
    return {"key": key, "discId": result.disc_id,
            "dir": str(result.output_dir),
            "recognized": result.recognized,
            "files": len(result.files_extracted),
            "tag": disc_tag(result.disc_id),
            # The slot it joined, to say so and to open.
            "game": slot,
            "gameTitle": title}


# ---------------------------------------------------------------------------
# Adding discs: the batch
# ---------------------------------------------------------------------------
#
# A batch is the images an import job extracts, in order: the ones found in
# a folder (`scan`), or a game's discs extracted again (`reextract_rows`).
# Each is a row the app shows while the job runs:
#
#   path, file   the image (its cue sheet where it has one), its file name
#   serial       the program its SYSTEM.CNF boots, "" where none is read
#   tag, label   the disc as the library names it (disc_tag, disc_display)
#   game, gameTitle   the slot it joins
#   state        waiting | extracting | added | failed | skipped
#   why          in words, why it was skipped or failed
#   key          the dump it replaces (game_key), and once added the one
#                it became


def _batch_row(path: Path, serial: str | None, state: str, why: str = "",
               key: str | None = None) -> dict:
    known = bool(serial) and serial in DISC_ID_LOOKUP
    slot, title = _slot_of(serial) if known else (None, "")
    return {"path": str(path), "file": path.name, "serial": serial or "",
            "tag": disc_tag(serial) if known else "",
            "label": disc_display(serial) if known else (serial or path.name),
            "game": slot, "gameTitle": title,
            "state": state, "why": why, "key": key}


def _in_a_dump(folder: Path) -> bool:
    """`folder` is the library's own (a dump, an index, the exports): its
    files are a disc's files, not disc images. The library's discs/ is
    not."""
    try:
        here = folder.resolve()
    except OSError:
        return False
    return (here.is_relative_to(config.LIBRARY.resolve())
            and not here.is_relative_to(config.DISCS_DIR.resolve()))


def images_in(path: Path | str) -> list[Path]:
    """The disc images at `path`: an image itself (its cue sheet where it
    has one), or every image in a folder and its subfolders, SCAN_DEPTH
    deep: cue sheets, and the .iso and .bin files no cue sheet beside them
    names. Hidden folders, links to folders and the library's own dumps
    are not looked in."""
    path = Path(path).expanduser()
    if path.is_file():
        if path.suffix.lower() not in DISC_SUFFIXES:
            raise ValueError(f"not a disc image (.cue, .iso or .bin): {path.name}")
        return [_image_for(path)]
    if not path.is_dir():
        raise FileNotFoundError(f"not found: {path}")
    out = []
    for here, dirs, files in os.walk(path):
        here = Path(here)
        deep = len(here.relative_to(path).parts) < SCAN_DEPTH
        dirs[:] = sorted(d for d in dirs if deep and not d.startswith(".")
                         and not _in_a_dump(here / d))
        for name in sorted(files):
            p = here / name
            if p.suffix.lower() in DISC_SUFFIXES and _image_for(p) == p:
                out.append(p)
    return out


def scan(path: Path | str) -> list[dict]:
    """The batch of the disc images at `path` (`images_in`), each read for
    the serial its SYSTEM.CNF boots (extractor.disc_identity): waiting to
    be extracted, or skipped, and why: already in the library, a second
    copy of a disc found (its cue sheet is the one extracted: the track
    layout is there), a disc gamedb does not know (extraction refuses
    one), or not a disc image the viewer reads. An image that fails to be
    read, however, is skipped alone: the rest go on."""
    from decoders.psx.disc.extractor import disc_identity
    have = {g.disc_id for g in GameDatabase().get_installed_games()}
    read: list[tuple[Path, str | None, str]] = []
    for p in images_in(path):
        try:
            serial, _volume = disc_identity(p)
            why = "" if serial else "no SYSTEM.CNF names its program: not a game disc"
        except (FileNotFoundError, ValueError) as ex:
            serial, why = None, str(ex)
        except OSError as ex:
            serial, why = None, f"it could not be read ({ex.strerror or ex})"
        except Exception as ex:             # one damaged image is its own row's
            serial, why = None, f"it could not be read ({type(ex).__name__}: {ex})"
        read.append((p, serial, why))
    first: dict[str, Path] = {}
    for p, serial, why in sorted(read, key=lambda r: (r[0].suffix.lower() != ".cue", str(r[0]))):
        if serial and not why:
            first.setdefault(serial, p)
    rows = []
    for p, serial, why in read:
        if why:
            rows.append(_batch_row(p, serial, "skipped", why))
        elif serial not in DISC_ID_LOOKUP:
            rows.append(_batch_row(p, serial, "skipped", f"a disc the viewer does not know ({serial})"))
        elif serial in have:
            rows.append(_batch_row(p, serial, "skipped", "already in the library"))
        elif first[serial] != p:
            rows.append(_batch_row(p, serial, "skipped",
                                   f"another copy of this disc: {first[serial].name} is added"))
        else:
            rows.append(_batch_row(p, serial, "waiting"))
    return rows


def reextract_rows(games: list[InstalledGame], image: Path | str | None = None) -> list[dict]:
    """The batch that extracts `games`' dumps again, each from the image it
    came from (or, for one game, from `image`: one the user found for
    it, which must hold the same disc); skipped where the image is no
    longer there."""
    from decoders.psx.disc.extractor import disc_identity
    rows = []
    for g in games:
        key = game_key(g)
        if image is not None:
            found = images_in(image)
            if len(found) != 1:
                raise ValueError("choose the disc's image itself, not a folder")
            serial, _volume = disc_identity(found[0])
            if serial != g.disc_id:
                raise ValueError(f"{found[0].name} holds {serial or 'no game'}, "
                                 f"not {g.disc_id}")
            rows.append(_batch_row(found[0], g.disc_id, "waiting", key=key))
        elif g.source is not None and g.source.exists():
            rows.append(_batch_row(g.source, g.disc_id, "waiting", key=key))
        else:
            recorded = read_meta(g.path).get("source")
            recorded = recorded if isinstance(recorded, str) else None
            rows.append(_batch_row(Path(recorded) if recorded else g.path, g.disc_id, "skipped",
                                   f"its image is no longer at {recorded}" if recorded
                                   else "where its image is was not kept", key=key))
    return rows


def reveal(path: str) -> None:
    """Show a file in the system file manager. Only inside the library."""
    import subprocess
    import sys

    target = Path(path).resolve()
    if not target.is_relative_to(config.LIBRARY.resolve()):
        raise PermissionError("only paths inside the library can be revealed")
    folder = target if target.is_dir() else target.parent
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target)] if target.is_file()
                         else ["open", str(folder)])
    elif os.name == "nt":
        # one string: as a list, a path with a space quotes the whole
        # "/select,…" and Explorer opens its default folder instead
        subprocess.Popen(f'explorer /select,"{target}"' if target.is_file()
                         else ["explorer", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)], env=system_env(),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

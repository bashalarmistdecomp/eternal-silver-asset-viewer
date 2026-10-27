"""Adding discs (viewer_server.library's batch, Backend.extract): made-up
disc images in a made-up library, their serials gamedb's own, no game data.

What this CAN catch: a folder's disc image missed (in a subfolder, a cue
sheet over its raw track, a bare .iso), or one taken from where nothing is
looked for (a hidden folder, too deep, the library's own dumps); a disc
already in the library, a second copy of one (its cue sheet is the one
kept), a disc gamedb does not know or a file that is no disc image
extracted instead of skipped and said why; a game's disc made again from
another disc's image, or one whose image moved not skipped; a batch that
stops at a disc that fails, extracts what it skips, indexes what it did
not add, or leaves a replaced dump open; the indexer's queue not showing
the discs that wait their turn.

What it CANNOT catch: the extraction itself (test_iso_reader.py, and the
discs the library holds).
"""

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from decoders import config
from decoders.psx.gamedb import database
from decoders.psx.gamedb.database import GameDatabase
from decoders.psx.gamedb.known_games import DISC_ID_LOOKUP, program_of
from decoders.testing import iso_image, raw_sectors
from viewer_server import index as library_index
from viewer_server import library
from viewer_server.index import Indexer
from viewer_server.routes import Backend

#: two discs gamedb knows, and one it does not
ONE, TWO = sorted(DISC_ID_LOOKUP)[:2]
UNKNOWN = "SLUS_999.99"


def _cnf(serial: str) -> bytes:
    return f"BOOT = cdrom:\\{serial};1\r\n".encode()


def _iso(path: Path, serial: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(iso_image({b"SYSTEM.CNF;1": _cnf(serial)}))
    return path


def _cue(folder: Path, name: str, serial: str) -> Path:
    """A cue sheet over a raw track, as a rip's folder holds them."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.bin").write_bytes(raw_sectors(iso_image({b"SYSTEM.CNF;1": _cnf(serial)})))
    cue = folder / f"{name}.cue"
    cue.write_text(f'FILE "{name}.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    return cue


@pytest.fixture
def lib(monkeypatch, tmp_path):
    root = tmp_path / "library"
    monkeypatch.setattr(config, "LIBRARY", root)
    monkeypatch.setattr(config, "DISCS_DIR", root / "discs")
    monkeypatch.setattr(database, "DISCS_DIR", root / "discs")
    assert UNKNOWN not in DISC_ID_LOOKUP
    return root


def _installed(lib: Path, serial: str, source: Path | None = None) -> Path:
    """A dump in the library, as an extraction leaves it."""
    dump = lib / program_of(serial) / "raw" / serial
    dump.mkdir(parents=True)
    (dump / "meta.json").write_text(json.dumps({"disc_id": serial, "source": str(source or "")}))
    return dump


def _states(rows) -> dict[str, tuple[str, str]]:
    return {r["file"]: (r["state"], r["why"]) for r in rows}


def test_a_folder_s_discs_are_found_and_the_rest_skipped_and_why(lib, tmp_path):
    rips = tmp_path / "rips"
    _cue(rips / "disc one", "One", ONE)
    _iso(rips / "Two.iso", TWO)
    _iso(rips / "copies" / "A copy.iso", ONE)       # met before the cue sheet, not kept
    _iso(rips / "Other.iso", UNKNOWN)
    (rips / "firmware.bin").write_bytes(bytes(600_000))
    _iso(rips / ".hidden" / "Hidden.iso", TWO)
    _iso(rips / "a" / "b" / "c" / "Three deep.iso", TWO)
    _iso(rips / "a" / "b" / "c" / "d" / "Four deep.iso", TWO)
    got = _states(library.scan(rips))
    assert set(got) == {"One.cue", "Two.iso", "A copy.iso", "Other.iso", "firmware.bin",
                        "Three deep.iso"}
    assert got["One.cue"] == got["Two.iso"] == ("waiting", "")
    assert got["A copy.iso"] == ("skipped", "another copy of this disc: One.cue is added")
    assert got["Three deep.iso"][1] == "another copy of this disc: Two.iso is added"
    assert got["Other.iso"] == ("skipped", f"a disc the viewer does not know ({UNKNOWN})")
    assert got["firmware.bin"] == ("skipped", "not a disc image: it holds no ISO 9660 volume")


def test_one_damaged_image_is_skipped_and_the_rest_go_on(lib, tmp_path, monkeypatch):
    from decoders.config import SECTOR_SIZE
    from decoders.psx.disc import extractor
    from decoders.testing import ISO_ROOT_LBA
    rips = tmp_path / "rips"
    _iso(rips / "Good.iso", ONE)
    damaged = bytearray(iso_image({b"SYSTEM.CNF;1": _cnf(TWO)}))
    damaged[ISO_ROOT_LBA * SECTOR_SIZE] = 20         # the root's first record: 20 bytes
    (rips / "Damaged.iso").write_bytes(damaged)
    got = _states(library.scan(rips))
    assert got["Good.iso"] == ("waiting", "")
    assert got["Damaged.iso"][0] == "skipped" and "damaged record" in got["Damaged.iso"][1]
    # and a failure no reader foresaw is that image's alone too
    identity = extractor.disc_identity

    def fails_on_good(p):
        if Path(p).name == "Good.iso":
            raise IndexError("made-up failure")
        return identity(p)

    monkeypatch.setattr(extractor, "disc_identity", fails_on_good)
    _iso(rips / "Two.iso", TWO)
    got = _states(library.scan(rips))
    assert got["Good.iso"] == ("skipped", "it could not be read (IndexError: made-up failure)")
    assert got["Two.iso"] == ("waiting", "")


@pytest.mark.parametrize("disc_id", ["../../outside", "..", "/abs", "C:\\x", "a/b", ["SLUS_000.00"]])
def test_a_dump_s_meta_json_cannot_name_a_folder_outside_the_library(lib, disc_id):
    dump = lib / "ANY" / "raw" / "ANY"
    dump.mkdir(parents=True)
    (dump / "meta.json").write_text(json.dumps({"disc_id": disc_id, "checksum": [1], "source": 2}))
    game, = GameDatabase().get_installed_games()
    assert (game.disc_id, game.program) == ("ANY", "ANY")
    exports = config.exports_dir(game.program)
    assert exports.resolve().is_relative_to(lib.resolve())


@pytest.mark.parametrize("name", ["", ".", "..", "../outside", "a/b", "/abs"])
def test_no_folder_of_the_library_is_named_out_of_it(lib, name):
    with pytest.raises(ValueError):
        config.exports_dir(name)
    with pytest.raises(ValueError):
        config.raw_dir("SLUS_000.00", name or "..")


def test_a_meta_json_that_is_not_an_object_is_no_dump(lib):
    dump = lib / "ANY" / "raw" / "ANY"
    dump.mkdir(parents=True)
    (dump / "meta.json").write_text("[1, 2]")
    assert GameDatabase().get_installed_games() == []
    (dump / "meta.json").write_bytes(b"\xff\xfe not text")
    assert GameDatabase().get_installed_games() == []


def test_images_in_the_discs_folder_are_listed_by_their_names(lib):
    _iso(lib / "discs" / "Two.iso", TWO)
    (lib / "discs" / "manifest.json").write_text("[1, 2]")      # read by nothing
    assert [(r["title"], r["serial"]) for r in library.library()["unsorted"]] == [("Two", "")]


def test_a_disc_the_library_holds_is_skipped(lib, tmp_path):
    _installed(lib, ONE)
    rows = library.scan(_iso(tmp_path / "rips" / "One.iso", ONE).parent)
    assert _states(rows) == {"One.iso": ("skipped", "already in the library")}
    assert rows[0]["tag"] and rows[0]["gameTitle"]


def test_an_image_is_added_by_its_cue_sheet(lib, tmp_path):
    cue = _cue(tmp_path / "rip", "One", ONE)
    assert library.images_in(cue.with_suffix(".bin")) == [cue]
    assert [r["path"] for r in library.scan(cue.with_suffix(".bin"))] == [str(cue)]


def test_the_library_s_own_dumps_are_not_looked_in(lib):
    dump = _installed(lib, ONE)
    (dump / "DATA.BIN").write_bytes(bytes(600_000))          # a disc's file, not an image
    _iso(lib / "discs" / "Two.iso", TWO)
    assert _states(library.scan(lib)) == {"Two.iso": ("waiting", "")}


def test_a_game_s_discs_are_made_again_from_their_own_images(lib, tmp_path):
    one = _iso(tmp_path / "rips" / "One.iso", ONE)
    _installed(lib, ONE, one)
    _installed(lib, TWO, tmp_path / "moved" / "Two.iso")
    games = GameDatabase().get_installed_games()
    rows = {r["serial"]: r for r in library.reextract_rows(games)}
    assert (rows[ONE]["state"], rows[ONE]["path"]) == ("waiting", str(one))
    assert rows[ONE]["key"] == library.game_key(next(g for g in games if g.disc_id == ONE))
    assert rows[TWO]["state"] == "skipped"
    assert rows[TWO]["why"] == f"its image is no longer at {tmp_path / 'moved' / 'Two.iso'}"


def test_a_dump_whose_meta_json_names_no_image_is_skipped_and_why(lib):
    dump = _installed(lib, ONE)
    (dump / "meta.json").write_text(json.dumps({"disc_id": ONE, "source": ["not", "a path"]}))
    row, = library.reextract_rows(GameDatabase().get_installed_games())
    assert (row["state"], row["why"]) == ("skipped", "where its image is was not kept")


def test_a_disc_found_again_must_be_the_same_disc(lib, tmp_path):
    _installed(lib, ONE)
    game = GameDatabase().get_installed_games()[0]
    other = _iso(tmp_path / "Two.iso", TWO)
    with pytest.raises(ValueError, match=f"holds {TWO}, not {ONE}"):
        library.reextract_rows([game], other)
    same = _iso(tmp_path / "One.iso", ONE)
    assert [r["state"] for r in library.reextract_rows([game], same)] == ["waiting"]


def _wait(job):
    for _ in range(500):
        if job.state != "running":
            return
        threading.Event().wait(0.01)
    raise AssertionError("the job did not end")


def test_a_batch_extracts_in_turn_goes_on_past_a_failure_and_indexes_what_it_added(monkeypatch, tmp_path):
    def row(file, state="waiting", key=None):
        return {"path": str(tmp_path / file), "file": file, "serial": "", "tag": "", "label": file,
                "game": None, "gameTitle": "", "state": state, "why": "", "key": key}

    rows = [row("a.cue"), row("b.cue"), row("c.iso", "skipped"), row("d.cue", key="old/d")]
    extracted, forgotten, indexed, replacing = [], [], [], []

    def extract(job, path):
        extracted.append(Path(path).name)
        replacing.append(library_index.INDEXER._replaced(tmp_path / "dumps" / "old" / "d"))
        if path.endswith("b.cue"):
            raise ValueError("made-up failure")
        name = Path(path).stem
        return {"key": f"new/{name}", "discId": name, "dir": str(tmp_path / "dumps" / name),
                "recognized": True, "files": 3, "tag": name.upper(), "game": "made-up",
                "gameTitle": "Made Up"}

    monkeypatch.setattr(library, "extract", extract)
    monkeypatch.setattr(library, "find_game", lambda key: SimpleNamespace(path=tmp_path / "dumps" / key))
    monkeypatch.setattr(library_index.INDEXER, "build_each", lambda games, progress: indexed.extend(games))
    backend = Backend("t", "test")
    monkeypatch.setattr(backend, "forget", lambda dump: forgotten.append(Path(dump).relative_to(tmp_path).as_posix()))
    job = backend.extract(lambda: rows)
    _wait(job)
    assert job.state == "done" and job.describe()["stage"] == "index"
    assert extracted == ["a.cue", "b.cue", "d.cue"]
    got = job.result["discs"]
    assert [d["state"] for d in got] == ["added", "failed", "skipped", "added"]
    assert got[1]["why"] == "made-up failure"
    assert (got[0]["key"], got[0]["tag"], got[0]["files"]) == ("new/a", "A", 3)
    # the dump re-extracted is let go of before, and each dump written after
    assert forgotten == ["dumps/a", "dumps/old/d", "dumps/d"]
    # and is not indexed while it is replaced, nor kept from it after
    assert replacing == [False, False, True]
    assert not library_index.INDEXER._replacing
    assert [g.path.name for g in indexed] == ["a", "d"]


def test_a_batch_with_nothing_to_extract_indexes_nothing(monkeypatch):
    monkeypatch.setattr(library_index.INDEXER, "build_each",
                        lambda games, progress: pytest.fail("nothing was added"))
    job = Backend("t", "test").extract(lambda: [])
    _wait(job)
    assert (job.state, job.result, job.describe()["stage"]) == ("done", {"discs": []}, "")


def test_the_discs_a_batch_indexes_wait_their_turn_in_the_queue(tmp_path):
    indexer, seen = Indexer(), []
    games = [SimpleNamespace(path=tmp_path / n) for n in ("a", "b", "c")]

    def build(game, progress=None):
        seen.append(sorted(p.name for p in indexer._queued))
        indexer._queued.remove(Path(game.path))
        if game.path.name == "a":
            indexer._queued.remove(tmp_path / "b")          # made meanwhile, by another job

    indexer.build = build
    indexer.build_each(games)
    assert seen == [["a", "b", "c"], ["c"]]
    assert indexer._queued == []


def test_a_game_no_tab_serves_says_it_is_not_fully_supported(lib):
    slots = {s["key"]: s for s in library.library()["games"]}
    assert slots["lunar-1"]["partial"] is False
    assert slots["lunar-2"]["partial"] is True
    # a disc of no game promises nothing more; neither does an unknown key
    assert library.partial("program:SLUS_900.55") is False
    assert library.partial("made-up") is False

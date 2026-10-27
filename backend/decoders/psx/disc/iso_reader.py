"""Pure-Python ISO 9660 Level 1 reader for PS1 disc images."""

import struct
from dataclasses import dataclass
from pathlib import Path

from decoders.config import SECTOR_SIZE, RAW_SECTOR_SIZE, MODE2_DATA_OFFSET


@dataclass
class DirectoryEntry:
    name: str
    lba: int
    size: int
    is_directory: bool


class DiscImage:
    """A disc image read LAZILY, by slice, from an open file.

    `ISO9660Reader` takes anything that answers `len()` and slicing, and
    the extractor hands it `Path.read_bytes()` — fine for a one-shot
    extraction, ruinous for anything that wants a few sectors out of a
    700 MB image (a movie's directory entry, a seek during playback).
    This is the same interface backed by seeks.

    Use as a context manager, or call `close()`.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._size = self.path.stat().st_size
        self._fh = self.path.open("rb")

    def __len__(self) -> int:
        return self._size

    def __getitem__(self, item) -> bytes:
        if not isinstance(item, slice):
            raise TypeError("DiscImage supports slicing only")
        start = 0 if item.start is None else max(0, item.start)
        stop = self._size if item.stop is None else min(self._size, item.stop)
        if stop <= start:
            return b""
        self._fh.seek(start)
        return self._fh.read(stop - start)

    def sectors(self, lba: int, count: int) -> bytes:
        """`count` RAW 2352-byte sectors starting at `lba`.

        Raw, not user data: Form 2 sectors carry 2324 bytes and their
        subheader is what says so, both of which an ISO-level read throws
        away. Anything reading XA audio needs this.
        """
        return self[lba * RAW_SECTOR_SIZE:(lba + count) * RAW_SECTOR_SIZE]

    def close(self):
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def find_file(image: "DiscImage", name: str) -> DirectoryEntry | None:
    """Locate one file in the image's root directory, by name.

    Returns the entry — crucially its LBA, which is what lets a caller read
    the file's RAW sectors rather than the extracted user-data copy.
    """
    iso = ISO9660Reader(image, raw_mode2=True)
    pvd = iso.read_pvd()
    wanted = name.upper().split(";")[0]
    for entry in iso.read_directory(pvd["root_lba"], pvd["root_size"]):
        if not entry.is_directory and entry.name.upper() == wanted:
            return entry
    return None


#: Characters no file name of the root directory may hold: path separators
#: (either system's), a drive's colon and the control characters.
_NOT_IN_A_NAME = frozenset("/\\:") | frozenset(map(chr, range(0x20)))


def file_path(out_dir: Path, name: str) -> Path:
    """Where the root directory's file `name` is written: in `out_dir`,
    and nowhere else. A name is the image's own bytes, so one holding a
    separator, a drive, ".." or nothing at all is refused (ValueError),
    and so is any path that does not resolve to a file directly in
    `out_dir`. ISO 9660 names are letters, digits, "_" and one ".", so no
    disc that keeps to the standard is refused."""
    if not name or ".." in name or not _NOT_IN_A_NAME.isdisjoint(name):
        raise ValueError(f"the disc names a file {name!r}, which is not a "
                         f"file name: nothing was extracted")
    path = out_dir / name
    if path.resolve().parent != out_dir.resolve():
        raise ValueError(f"the disc's file {name!r} would be written outside "
                         f"{out_dir}: nothing was extracted")
    return path


#: The most a directory is read of. A CD's directories are a sector or a
#: few; this is some 20,000 files. A larger size is a damaged record's,
#: and would have the reader build that much out of the image.
MAX_DIRECTORY = 1 << 20
#: A directory record's fixed part, before its name (ISO 9660 9.1).
_RECORD_HEAD = 33
#: The most sectors a CD holds (99 minutes at 75 a second): a volume
#: descriptor counting more is a damaged one's.
CD_SECTORS = 99 * 60 * 75


def _named(names: list[str], most: int = 5) -> str:
    """"A, B and C", the first `most` of them, then how many more."""
    shown = names[:most] + ([f"{len(names) - most} more"] if len(names) > most else [])
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


class ISO9660Reader:
    """Reads an ISO 9660 filesystem from raw MODE2/2352 sector data or plain ISO.

    Every size and place it reads is the image's own bytes, so none is
    trusted: a sector past the image's end, a file that runs past it, a
    directory record shorter than its fixed part or a directory larger
    than MAX_DIRECTORY is a ValueError, never zeros or a guess.

    But for one case: `other_tracks`, the disc has tracks after this one
    that `data` does not hold, or not all of (a cue sheet's CD audio, in
    files of their own, or after the data in its file but for a PREGAP
    line's silence). A file running past the data's end, but within the
    volume (its descriptor's sector count, which counts those tracks, and
    no more than a CD holds), then lies partly or wholly in them, as
    Lunar's .PCM files do, and `extract_all` writes its sectors in the data
    followed by zeros: there is nothing an ISO-level read could take from a
    CD audio sector. (So an image of several tracks whose file is cut short
    is not seen to be; its checksum then matches no disc gamedb knows.)"""

    def __init__(self, data: bytes | memoryview, raw_mode2: bool = False,
                 other_tracks: bool = False):
        self._data = data
        self._other_tracks = other_tracks
        self._raw = raw_mode2
        self._sector_size = RAW_SECTOR_SIZE if raw_mode2 else SECTOR_SIZE

    def _read_sector(self, lba: int) -> bytes:
        offset = lba * self._sector_size
        if lba < 0 or offset + self._sector_size > len(self._data):
            raise ValueError(f"sector {lba} lies past the end of the image")
        raw = self._data[offset:offset + self._sector_size]
        if self._raw:
            return raw[MODE2_DATA_OFFSET:MODE2_DATA_OFFSET + SECTOR_SIZE]
        return raw[:SECTOR_SIZE]

    def _read_sectors(self, lba: int, count: int) -> bytes:
        out = bytearray()
        for i in range(count):
            out.extend(self._read_sector(lba + i))
        return bytes(out)

    def within(self, entry: DirectoryEntry) -> bool:
        """Whether every sector of `entry` lies in the image (an empty
        file has none, wherever its record says it starts)."""
        sectors = (entry.size + SECTOR_SIZE - 1) // SECTOR_SIZE
        return sectors == 0 or (entry.lba + sectors) * self._sector_size <= len(self._data)

    def in_other_tracks(self, entry: DirectoryEntry, volume_space: int) -> bool:
        """Whether `entry` runs on into the tracks after this one
        (`other_tracks`): past the data's end, within the volume's
        `volume_space` sectors (read_pvd) and what a CD holds."""
        sectors = (entry.size + SECTOR_SIZE - 1) // SECTOR_SIZE
        return (self._other_tracks and not self.within(entry)
                and entry.lba + sectors <= min(volume_space, CD_SECTORS))

    def _completed(self, entry: DirectoryEntry) -> bytes:
        """A file running on into the other tracks (`in_other_tracks`): its
        sectors in the data, then zeros."""
        held = max(0, min((entry.size + SECTOR_SIZE - 1) // SECTOR_SIZE,
                          len(self._data) // self._sector_size - entry.lba))
        data = self._read_sectors(entry.lba, held)
        return data[:entry.size] + bytes(max(0, entry.size - len(data)))

    def read_pvd(self) -> dict:
        """Read Primary Volume Descriptor at sector 16."""
        if 17 * self._sector_size > len(self._data):
            raise ValueError("Not a valid ISO 9660 image (too short for one)")
        pvd = self._read_sector(16)
        if pvd[1:6] != b"CD001":
            raise ValueError("Not a valid ISO 9660 image (no CD001 magic)")

        root_record = pvd[156:190]
        root_lba = struct.unpack_from("<I", root_record, 2)[0]
        root_size = struct.unpack_from("<I", root_record, 10)[0]

        return {
            "system_id": pvd[8:40].decode("ascii", errors="replace").strip(),
            "volume_id": pvd[40:72].decode("ascii", errors="replace").strip(),
            "root_lba": root_lba,
            "root_size": root_size,
            # the volume's sectors, the disc's other tracks counted in
            "volume_space": struct.unpack_from("<I", pvd, 80)[0],
        }

    def read_directory(self, lba: int, size: int) -> list[DirectoryEntry]:
        """Read a directory at the given LBA. ValueError for one larger
        than MAX_DIRECTORY, past the image's end, or holding a record that
        is shorter than its own fields or runs past the directory's end."""
        if size > MAX_DIRECTORY:
            raise ValueError(f"the image's directory at sector {lba} is "
                             f"{size} bytes long: a damaged image")
        num_sectors = (size + SECTOR_SIZE - 1) // SECTOR_SIZE
        dir_data = self._read_sectors(lba, num_sectors)

        entries = []
        pos = 0
        while pos < len(dir_data):
            rec_len = dir_data[pos]
            if rec_len == 0:
                pos = ((pos // SECTOR_SIZE) + 1) * SECTOR_SIZE
                continue
            if (rec_len < _RECORD_HEAD or pos + rec_len > len(dir_data)
                    or _RECORD_HEAD + dir_data[pos + 32] > rec_len):
                raise ValueError(f"the image's directory at sector {lba} holds "
                                 f"a damaged record: a damaged image")

            entry = dir_data[pos:pos + rec_len]
            name_len = entry[32]
            raw_name = entry[33:33 + name_len]
            flags = entry[25]
            entry_lba = struct.unpack_from("<I", entry, 2)[0]
            entry_size = struct.unpack_from("<I", entry, 10)[0]

            name = raw_name.decode("ascii", errors="replace")
            name = name.split(";")[0]  # strip version number

            if name not in ("", "\x00", "\x01"):
                entries.append(DirectoryEntry(
                    name=name,
                    lba=entry_lba,
                    size=entry_size,
                    is_directory=bool(flags & 0x02),
                ))

            pos += rec_len

        return entries

    def extract_file(self, entry: DirectoryEntry) -> bytes:
        """Extract file data for a directory entry. ValueError when it runs
        past the image's end (`within`), before anything is read."""
        if not self.within(entry):
            raise ValueError(f"{entry.name} runs past the end of the image")
        num_sectors = (entry.size + SECTOR_SIZE - 1) // SECTOR_SIZE
        data = self._read_sectors(entry.lba, num_sectors)
        return data[:entry.size]

    def extract_all(self, out_dir: Path, progress_cb=None) -> list[str]:
        """Extract all files from the root directory to out_dir.

        Returns list of extracted filenames.
        progress_cb is called with (filename, files done, total files)
        before each file.

        Raises ValueError, before anything is written, when a file's name
        could put it anywhere but in out_dir itself (`file_path`): the
        names are the image's own bytes, and this runs before the disc is
        recognised. So does a file that runs past the image's end (a cut
        short or damaged image), naming every such file. A file that cannot
        be written does not stop the others; OSError afterwards names them
        all. Either way the disc's files are not all there, and what was
        written is the caller's to remove.
        """
        pvd = self.read_pvd()
        root_entries = self.read_directory(pvd["root_lba"], pvd["root_size"])
        files = [(entry, file_path(out_dir, entry.name))
                 for entry in root_entries if not entry.is_directory]
        space = pvd["volume_space"]
        past = [entry.name for entry, _path in files
                if not self.within(entry) and not self.in_other_tracks(entry, space)]
        if past:
            raise ValueError(f"the disc image is cut short or damaged: {_named(past)} "
                             f"{'runs' if len(past) == 1 else 'run'} past its end, "
                             f"so nothing was extracted")

        out_dir.mkdir(parents=True, exist_ok=True)
        extracted, failed = [], []

        for n, (entry, out_path) in enumerate(files):
            if progress_cb:
                progress_cb(entry.name, n, len(files))
            try:
                out_path.write_bytes(self._completed(entry) if self.in_other_tracks(entry, space)
                                     else self.extract_file(entry))
            except OSError as ex:
                failed.append(f"{entry.name} ({ex.strerror or ex})")
                continue
            extracted.append(entry.name)

        if failed:
            raise OSError(f"{_named(failed)} could not be written, so the disc's "
                          f"files are not all there")
        return extracted

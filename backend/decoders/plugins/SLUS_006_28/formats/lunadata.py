"""The LUNADATA.FIL archive's own table of contents.

The program never reads it: it reads a resource by number, from the sector
pairs in the executable (formats.resource_table). The table of contents
names 46 files, SYSTEM.DAT, STFIELD.DAT, OPEN1.BIN and 43 of the 97 maps
(docs/spec/overview.md §"Its table of contents"). Its entries are kept
here as names for the resources they start at.
"""

import struct
from dataclasses import dataclass
from pathlib import Path

SECTOR = 2048


@dataclass
class ArchiveEntry:
    name: str
    sector: int
    size: int
    #: TOC bytes 28-31. NOT a checksum: it is the packed file's Unix
    #: modification time (seconds since 1970 UTC), in the retail and demo
    #: (SLUS_900.55) archives alike (docs/spec/overview.md). The field
    #: keeps its old name for its callers; read `mtime`.
    checksum: int

    @property
    def mtime(self) -> int:
        """Unix modification time of the packed file."""
        return self.checksum


class LunaDataArchive:
    """Reader for LUNADATA.FIL's table of contents."""

    def __init__(self, filepath: Path):
        self._path = Path(filepath)
        self.entries: list[ArchiveEntry] = []
        self._parse_toc()

    def _parse_toc(self):
        with open(self._path, "rb") as f:
            header = f.read(32)
            num_entries = struct.unpack_from("<I", header, 0)[0]

            for _ in range(num_entries):
                entry = f.read(32)
                name = entry[:20].split(b"\x00")[0].decode("ascii", errors="replace")
                sector, size, checksum = struct.unpack_from("<III", entry, 20)
                self.entries.append(ArchiveEntry(name, sector, size, checksum))

    @property
    def toc_entries(self) -> list[ArchiveEntry]:
        """The 46 entries of the table of contents."""
        return list(self.entries)

    def extract(self, entry: ArchiveEntry) -> bytes:
        """Read an entry's bytes from the archive."""
        with open(self._path, "rb") as f:
            f.seek(entry.sector * SECTOR)
            return f.read(entry.size)

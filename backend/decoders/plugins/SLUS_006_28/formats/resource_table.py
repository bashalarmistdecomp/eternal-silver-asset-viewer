"""The resource table — the EXE's index into LUNADATA.FIL.

The game never reads the archive's own table of contents. It reads a
resource by number: resource_load(n, destination) (0x80020230) takes pair n
of g_ResourceSectorPairs (0x800AE904), `[first_sector:u16, sectors:u16]`,
and reads `sectors << 11` bytes from `first_sector << 11`.

The table holds 601 pairs, resources 0 to 0x258: 0x964 bytes up to the next
symbol, g_ScriptResourcePairs (0x800AF268). Pair 0 is (0, 599), the span of
the table of contents; from resource 1 on each pair starts where the one
before ends, so every sector from 16 to the archive's last belongs to
exactly one of resources 1 to 599; pair 0x258 is (the archive's length in
sectors, 0). Nothing in the code tests a number against that size: a number
past it would read the script pairs that follow as sectors.
docs/spec/file-sector-map/overview.md §"The resource table".

The address and the count come from `decoders.psx.analysis.symbols`; in
SLPS_013.97 the table lies elsewhere (records.programs) and holds as many
pairs, resources numbered as here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from decoders.psx.analysis.symbols import lookup
from decoders.config import SECTOR_SIZE

from ..records.programs import address


@dataclass(frozen=True)
class Resource:
    """One pair of the table: resource `index` and its sectors."""
    index: int
    start_sector: int
    size_sectors: int
    table: str = ""

    @property
    def offset(self) -> int:
        return self.start_sector * SECTOR_SIZE

    @property
    def size(self) -> int:
        return self.size_sectors * SECTOR_SIZE

    def read(self, archive_path: Path | str) -> bytes:
        with open(archive_path, "rb") as f:
            f.seek(self.offset)
            return f.read(self.size)


def load_resource_table(binary, table: str = "g_ResourceSectorPairs",
                        count: int | None = None) -> list[Resource]:
    """The resources of a sector table read out of a loaded EXE.

    `count` defaults to the table's own (601 pairs). A pair with a start or
    a length of 0 is left out: pair 0, the table of contents' span, and the
    empty pair 0x258 — neither is a resource the game reads.
    """
    sym = lookup(table)
    if sym is None:
        raise KeyError(f"unknown sector table {table!r}")
    if count is None:
        if not sym.size:
            raise ValueError(f"{table} has no recorded size: pass count")
        count = sym.size // 4

    base = address(binary, table, sym.addr)
    out: list[Resource] = []
    for i in range(count):
        try:
            raw = binary.read_bytes(base + i * 4, 4)
        except (IndexError, ValueError):
            break
        if len(raw) < 4:
            break
        start, size = struct.unpack("<HH", raw)
        if start == 0 or size == 0:
            continue
        out.append(Resource(index=i, start_sector=start,
                            size_sectors=size, table=table))
    return out

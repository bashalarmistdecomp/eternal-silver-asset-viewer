"""Tier 1 for LUNADATA.FIL's table of contents — built bytes, no game data.

What this CAN catch: the 32-byte entry layout (name, first sector, size,
modification time) and reading an entry's bytes.

What it CANNOT catch: what the program reads (it never reads this table:
formats.resource_table). See decoders/testing.py.
"""

import struct

from decoders.plugins.SLUS_006_28.formats.lunadata import SECTOR, LunaDataArchive


def _archive(tmp_path):
    head = struct.pack("<I", 1).ljust(32, b"\0")
    entry = b"SYSTEM.DAT".ljust(20, b"\0") + struct.pack("<III", 1, 100, 0x36F2E000)
    data = bytearray((head + entry).ljust(SECTOR, b"\0"))
    data += b"x" * SECTOR                                   # sector 1: the entry
    path = tmp_path / "LUNADATA.FIL"
    path.write_bytes(bytes(data))
    return LunaDataArchive(path)


def test_the_table_of_contents(tmp_path):
    arc = _archive(tmp_path)
    [e] = arc.toc_entries
    assert (e.name, e.sector, e.size, e.mtime) == ("SYSTEM.DAT", 1, 100, 0x36F2E000)
    assert arc.extract(e) == b"x" * 100
    assert arc.toc_entries == arc.entries

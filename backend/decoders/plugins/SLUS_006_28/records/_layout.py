"""Field-list parsing shared by the record modules.

A layout is a list of (offset, kind, name, note) tuples; kind is
"u8" / "u16" / "u32", optionally with an array suffix ("u8[6]").
All values little-endian, as on the PS1.
"""

import re
import struct

_KIND = re.compile(r"^(u8|u16|u32)(?:\[(\d+)\])?$")
_FMT = {"u8": "B", "u16": "H", "u32": "I"}


def parse_fields(buf: bytes, fields, base: int = 0) -> dict:
    """-> {name: int | list[int]} for every field in the layout."""
    out = {}
    for off, kind, name, _note in fields:
        m = _KIND.match(kind)
        if not m:
            raise ValueError(f"bad field kind {kind!r} for {name}")
        k, n = m.group(1), m.group(2)
        if n:
            out[name] = list(struct.unpack_from(
                f"<{int(n)}{_FMT[k]}", buf, base + off))
        else:
            out[name] = struct.unpack_from(f"<{_FMT[k]}", buf, base + off)[0]
    return out


def field_notes(fields) -> dict:
    """-> {name: note} — for embedding the evidence hints in exports."""
    return {name: note for _off, _kind, name, note in fields}

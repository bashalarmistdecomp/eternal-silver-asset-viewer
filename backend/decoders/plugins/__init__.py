"""Per-program plugin packages: decoders/plugins/<serial>/.

The core rule: **serial keys, not title slugs** — per-game code is keyed
by program serial, the same key the library's folders use. The generic
core lives in psx/ (PlayStation knowledge, no game knowledge); anything
one program group needs beyond that lives in its plugin.

A Python package name cannot contain '.', so a plugin DIRECTORY carries
the mangled serial (SLUS_006.28 -> SLUS_006_28, see `mangle`), each
plugin declares its real `SERIAL` in its __init__, and the plugins'
tests cross-check declaration, directory name, and gamedb.

COMPAT below is the compatibility list: which serial each plugin serves.
Resolution goes through gamedb's program_of first, so a DISC serial finds
the program's plugin (e.g. either SSSC disc resolves to SLUS_006.28 —
both discs boot the same program, cmp-proven).
"""

from __future__ import annotations

import importlib


def mangle(serial: str) -> str:
    """A program serial -> the plugin package directory name for it."""
    return serial.replace(".", "_")


#: The compatibility list: program serial -> plugin package under this
#: one. A plugin serves its own serial and may serve another program of
#: the same source (its plugin then says how it tells them apart). A
#: program with no entry has no plugin — its work uses psx/ alone, which
#: is not an error.
COMPAT: dict[str, str] = {
    "SLUS_006.28": "SLUS_006_28",
    # the Japanese original: the same source, its tables located by
    # SLUS_006_28.records.programs
    "SLPS_013.97": "SLUS_006_28",
}


def plugin_for(serial: str):
    """Import and return the plugin package serving `serial`, or None.

    Accepts a program serial or any disc serial gamedb can resolve to a
    program; returns None when no plugin exists for that program.
    """
    from decoders.psx.gamedb.known_games import program_of
    prog = program_of(serial)
    name = COMPAT.get(prog) or COMPAT.get(serial)
    if name is None:
        return None
    return importlib.import_module(f"{__name__}.{name}")

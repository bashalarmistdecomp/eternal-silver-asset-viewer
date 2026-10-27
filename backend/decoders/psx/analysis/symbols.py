"""Resolve EXE addresses by name instead of hardcoding them.

`DATA_TABLES` below holds the data tables the program reads that reverse
engineering has located and documented. Code that reads one should ask for
it by name rather than paste a literal address, so there is one place to
change.

    >>> from decoders.psx.analysis.symbols import resolve
    >>> hex(resolve("g_CardSavePlaceNames"))
    '0x800a8618'
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Symbol:
    """A named EXE address."""
    name: str
    addr: int
    kind: str = ""            # "func", "data", ... ("" when unstated)
    size: int | None = None
    source: str = ""          # "spec": located by reading the code
    note: str = ""


# ---------------------------------------------------------------------------
# The data tables, by name.
# ---------------------------------------------------------------------------

DATA_TABLES: dict[str, Symbol] = {
    s.name: s for s in (
        Symbol(
            name="g_CardSavePlaceNames", addr=0x800A8618, kind="data",
            size=84 * 4, source="spec",
            note="g_CardSavePlaceNames (0x800A8618): 84 pointers to the memory-card SHORT location "
                 "names, indexed by location id - 0x51 (ids 0x51-0xA4); read "
                 "only by card_save_title_set (0x8001BF50), the memory-card title of the save "
                 "path. The display names are the string table's "
                 "(location id + 0x400). docs/spec/text.md §Locations",
        ),
        Symbol(
            name="g_ResourceSectorPairs", addr=0x800AE904, kind="data",
            size=601 * 4, source="spec",
            note="601 x [first_sector:u16, sectors:u16] into LUNADATA.FIL, "
                 "resources 0 to 0x258: 0x964 bytes up to the next symbol, "
                 "g_ScriptResourcePairs (0x800AF268). resource_load "
                 "(0x80020230) reads pair n; nothing bounds n. Pair 0 is "
                 "(0, 599), the span of the archive's own table of contents; "
                 "from resource 1 on each pair starts where the one before "
                 "ends, and pair 0x258 is (18046, 0). "
                 "docs/spec/file-sector-map/overview.md §\"The resource table\"",
        ),
        Symbol(
            name="g_BuildStamp", addr=0x80011000, kind="data", source="spec",
            note="The program's build stamp: a text and its 0, the first "
                 "bytes of the program's data. build_stamp_compare "
                 "(0x80013D08) is strcmp of its argument with it; its one "
                 "use is overlay_stamp_check (0x800232B0), which passes the "
                 "overlay just read to 0x80196000. "
                 "docs/spec/code/subsystems/overlay.md §\"The build stamp\"",
        ),
        Symbol(
            name="g_OverlayFileName", addr=0x80011734, kind="data", source="spec",
            note="The overlay's file name and its 0: overlay_load "
                 "(0x80023240) reads that file whole to 0x80196000, "
                 "overlay_disc_wait (0x80023184) its first 0x800 bytes. "
                 "docs/spec/code/subsystems/overlay.md §\"Loading\"",
        ),
    )
}


def lookup(name: str) -> Symbol | None:
    """Find a symbol by name."""
    return DATA_TABLES.get(name)


def resolve(name: str) -> int:
    """Return a symbol's address, or raise KeyError if it is unknown."""
    sym = lookup(name)
    if sym is None:
        raise KeyError(f"unknown symbol {name!r} — add it to DATA_TABLES in {__name__}")
    return sym.addr


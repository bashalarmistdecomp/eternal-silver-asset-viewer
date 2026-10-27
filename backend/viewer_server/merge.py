"""One tab's items from several discs, as one list.

Each disc's provider lists its own items; this puts them together:

  * items with the same key in the same version group are ONE row (the
    Japanese _B001.STR is the US one's other version; the making-of disc's
    _B000.STR is a different movie, its program being its own group);
  * within a row, items whose contents match are ONE version, held by
    every disc that has it; items that differ are separate versions;
  * a disc whose whole tab is byte-identical to another's (both US discs'
    archive tabs) adds its tag to that disc's items without listing again;
  * rows keep each disc's order: a run of items only one disc has goes
    just before the next row that disc shares with an earlier one, after
    the earlier discs' own items there (a Japanese script's messages, keyed
    by their place in its own text, sit under that script, after the US
    ones, not at the end of the list).

A placeholder (an item with no data, "No CD audio on this disc") is kept
only when no disc has a real item.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from viewer_tabs.identity import Identity, same


@dataclass
class Entry:
    """One disc's item: `holders[0]` lists it, the rest hold the same bytes."""
    holders: tuple[int, ...]
    item: int
    label: str
    data: Any
    identity: Identity | None


@dataclass
class Version:
    entries: list[Entry]

    @property
    def first(self) -> Entry:
        return self.entries[0]

    @property
    def holders(self) -> list[int]:
        out: list[int] = []
        for e in self.entries:
            out += [h for h in e.holders if h not in out]
        return out


@dataclass
class Row:
    key: tuple
    versions: list[Version] = field(default_factory=list)
    #: Where the row sorts (see `_before`).
    order: tuple = ()

    @property
    def holders(self) -> list[int]:
        out: list[int] = []
        for v in self.versions:
            out += [h for h in v.holders if h not in out]
        return out


@dataclass
class Listing:
    """One disc's (or one set of identical discs') items for the tab."""
    holders: tuple[int, ...]
    group: str
    items: list[tuple[str, Any, Identity | None]]


def merge(listings: list[Listing]) -> list[Row]:
    rows: dict[tuple, Row] = {}
    placeholders: dict[tuple, Row] = {}
    for n, listing in enumerate(listings):
        before = set(rows)          # rows earlier listings added
        run: list[tuple[int, Row]] = []     # this listing's new rows so far
        for i, (label, data, ident) in enumerate(listing.items):
            entry = Entry(listing.holders, i, label, data, ident)
            if data is None:
                row = placeholders.setdefault((label,), Row((label,)))
                if row.versions:
                    row.versions[0].entries.append(entry)
                else:
                    row.versions.append(Version([entry]))
                continue
            key = (listing.group, ident.key if ident else label)
            row = rows.get(key)
            if row is None:
                row = rows[key] = Row(key)
                run.append((i, row))
            elif key in before and run:
                for j, new in run:
                    new.order = _before(row.order, n, j)
                run = []
            for version in row.versions:
                other = version.first.identity
                if ident is not None and other is not None and same(ident, other):
                    version.entries.append(entry)
                    break
            else:
                row.versions.append(Version([entry]))
        for j, new in run:              # after every row listed so far
            new.order = ((math.inf, 0), (n, j))
    return (sorted(rows.values(), key=lambda r: r.order)
            or list(placeholders.values()))


def _before(order: tuple, n: int, j: int) -> tuple:
    """A key for item `j` of listing `n` that sorts just before the row
    whose key is `order`, after every row that already sorts before it.

    A key is a path of (listing, item) steps; the last step's item is a
    whole number, so half a step less sorts after its predecessors and
    their own runs, and the listing's step keeps its run in order behind
    an earlier listing's run at the same place."""
    *head, (m, i) = order
    return (*head, (m, i - 0.5), (n, j))

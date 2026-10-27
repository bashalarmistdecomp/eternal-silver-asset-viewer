"""What makes two discs' items the same item, and the same content.

A game opens with every disc it has (viewer_server.session), so a tab lists
items from several discs at once. Two items with the same KEY are one item
(the Japanese _B001.STR is the US _B001.STR's version); they are one
VERSION when their contents match, which `size` tells cheaply when they
differ and `digest` tells for certain.

A provider says this per item with `item_identity(label, data, ctx)`. A tab
whose items have no identity (none has now) is compared whole instead:
discs whose files the tab requires (its `requires`, and the program) are
byte-identical show the tab's items once, tagged with each of them.

Digests are sha1s of file bytes, kept beside the dump in `.digests.json`
(by name, size and mtime) so a game reopens without hashing its movies
again. The dump's file list skips dot-files, so the cache is never shown
as a disc file.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

CACHE_NAME = ".digests.json"

_lock = threading.Lock()
_memory: dict[tuple[str, int, int], str] = {}


@dataclass(frozen=True)
class Identity:
    #: What makes two discs' items one item.
    key: str
    #: A cheap first test: items whose sizes differ differ.
    size: int | None = None
    #: The full test, computed only when the cheap one ties.
    digest: Callable[[], str] | None = None


def of_file(key: str, path: Path) -> Identity:
    """An item that is one file of the dump."""
    return Identity(key, path.stat().st_size, lambda: file_digest(path))


def of_bytes(key: str, data: bytes) -> Identity:
    return Identity(key, len(data), lambda: hashlib.sha1(data).hexdigest())


def of_parts(key: str, read: Callable[[], Iterable[bytes]]) -> Identity:
    """An item read from several byte strings: `of_bytes` over them, each
    with its length, read only when another disc's item of the same key is
    compared with it, and once."""
    digest: list[str] = []

    def once() -> str:
        if not digest:
            h = hashlib.sha1()
            for part in read():
                h.update(len(part).to_bytes(4, "little"))
                h.update(part)
            digest.append(h.hexdigest())
        return digest[0]

    return Identity(key, None, once)


def same(a: Identity, b: Identity) -> bool:
    """True when the two items' contents are known to match."""
    if a.size is not None and b.size is not None and a.size != b.size:
        return False
    if a.digest is None or b.digest is None:
        return False
    return a.digest() == b.digest()


def file_digest(path: Path) -> str:
    """sha1 of a file's bytes, cached in memory and beside the file."""
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    with _lock:
        hit = _memory.get(key)
    if hit:
        return hit
    cache_path = path.parent / CACHE_NAME
    cache = _read(cache_path)
    row = cache.get(path.name) or {}
    if row.get("size") == st.st_size and row.get("mtime") == st.st_mtime_ns:
        digest = row["sha1"]
    else:
        h = hashlib.sha1()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        digest = h.hexdigest()
        with _lock:
            cache = _read(cache_path)
            cache[path.name] = {"size": st.st_size, "mtime": st.st_mtime_ns,
                                "sha1": digest}
            _write(cache_path, cache)
    with _lock:
        _memory[key] = digest
    return digest


def tab_sources(provider, ctx) -> tuple | None:
    """What a tab without item identities reads on this disc, as digests:
    the files it requires (glob patterns allowed) and the program when it
    serves named programs. None when it declares neither, so it cannot be
    compared."""
    patterns = getattr(provider, "requires", ())
    programs = getattr(provider, "programs", ())
    if not patterns and not programs:
        return None
    names = sorted({n for p in patterns
                    for n in fnmatch.filter(ctx.files, p)})
    out = [(n, file_digest(ctx.path(n))) for n in names]
    if programs and ctx.exe_path.exists():
        out.append(("program", file_digest(ctx.exe_path)))
    return tuple(out)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _write(path: Path, cache: dict) -> None:
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        tmp.replace(path)
    except OSError:
        pass                    # a read-only dump just hashes again next time

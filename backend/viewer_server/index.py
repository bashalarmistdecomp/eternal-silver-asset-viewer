"""The library's index of a disc: what its tabs list and what links its
things, kept on disk, so a game opens without reading every disc again.

Opening a game used to read every disc of it whole: each tab's list made
on every disc, the discs' items compared by their bytes, and a disc's
links made from all its maps and scripts the first time a page of it was
shown. None of that changes until the disc or the viewer does, so it is
kept, one file per disc, in the library beside the disc's files:

    <library>/<program>/index/<disc>.zip      (decoders.config.index_file)

    stamp.json        what it was made from (`stamp_of`), written last
    tabs/<key>.json   a tab's list in each of its views: each item's row
                      and Fan row as the app shows them, and its identity
                      (viewer_tabs.identity) with its digest
    links.json        the disc's links (viewer_tabs.links.LinkIndex): its
    links.bin         things and their titles, its edges as numbers

Each row's data in a list read from here is a `Kept`: its row and Fan
row as the index holds them, and the provider's item itself where the
provider takes it unlisted (`selects_unlisted`: plain data, numbers and
strings in tuples, a script's resource and number). Any other item (a
map's records, a song's banks) is read again from its provider when it
is wanted, by its place in the provider's list, and the session checks it
is the item the index lists: the list label by label, and a selected
item by its identity, digest and all (GameSession._data).

**When it is made**: as the last step of extracting a disc (an extraction
job), and in the background when the backend starts, for every disc of
the library whose index is missing or stale (`Indexer.start`). Until a
disc's index is there, the game reads that disc as it always did.

**When it is stale**: its stamp is the viewer's code (the digest of the
backend's sources; in the frozen build, the build's own file) and the
disc's (every file of the dump, by size and modification time; the image
it came from; the Japanese font the machine draws kanji with). An index
whose stamp is not the disc's now is not read, and is made again.

**Safe to read**: the library is a folder its owner may copy or share,
so reading an index runs no code: JSON, and whole numbers in an array.
A file that cannot be read, or reads wrong, is not used. It is written
whole under a temporary name and renamed into place, so no reader sees
half of one; two backends on one library each write their own, and the
last rename wins. A lock file beside it says one is being made, and by
which process, so a second backend does not make it too; a lock whose
process is gone (the app closed mid-index: the backend exits at once) is
taken over, and a disc another backend held is made once it lets go.
"""

from __future__ import annotations

import array
import hashlib
import json
import os
import sys
import threading
import time
import traceback
import zipfile
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path

from decoders import config
from viewer_tabs import links as tab_links
from viewer_tabs.identity import Identity
from viewer_tabs.refs import Ref

#: What an index holds and how: an index of another format is not read.
FORMAT = 1
#: Set to 1 to neither read nor make an index: every list is read from the
#: discs, as before there was one.
OFF_ENV = "ASSET_VIEWER_NO_INDEX"
#: The most one part of an index file may unpack to; a larger one is not
#: one this viewer wrote, and is not read.
MAX_PART = 256 << 20
#: A backend making an index touches its lock after every tab; a lock left
#: older than this was left by one that stopped.
LOCK_STALE = 300.0
#: How often the background indexer looks again at a disc another backend
#: was making when it came to it (`Indexer._run`).
LOCK_POLL = 15.0
#: How long a dump about to be replaced waits for this process to stop
#: making its index (`Indexer.replacing`).
REPLACE_WAIT = 30.0


def enabled() -> bool:
    return os.environ.get(OFF_ENV) != "1"


# ---------------------------------------------------------------------------
# The stamp
# ---------------------------------------------------------------------------

_code: str | None = None


def code_stamp() -> str:
    """The digest of the code that reads the discs: every source file of
    the backend but its tests, and the Python running it. A frozen build
    (docs/development.md, "A release build") has no sources to read: its own file,
    by size and modification time, stands for them."""
    global _code
    if _code is None:
        h = hashlib.sha1()
        if getattr(sys, "frozen", False):
            st = Path(sys.executable).stat()
            h.update(f"frozen {st.st_size} {st.st_mtime_ns}".encode())
        else:
            root = Path(__file__).resolve().parent.parent
            for p in sorted(root.rglob("*.py")):
                rel = p.relative_to(root)
                if any(part in ("tests", "__pycache__") or part.startswith(".")
                       for part in rel.parts[:-1]):
                    continue
                h.update(rel.as_posix().encode() + b"\0")
                h.update(p.read_bytes())
        h.update(sys.version.encode())
        _code = h.hexdigest()
    return _code


def disc_stamp(ctx) -> dict:
    """What the disc's reading is made from: every file of the dump (by
    size and modification time), the disc image it came from (its tracks,
    the CD audio, are read from there) and the font kanji are drawn with
    (viewer_tabs.system_font)."""
    from viewer_tabs import system_font
    files = {}
    for p in sorted(Path(ctx.data_dir).iterdir()):
        if p.name.startswith(".") or not p.is_file():
            continue
        st = p.stat()
        files[p.name] = [st.st_size, st.st_mtime_ns]
    source = None
    try:
        if ctx.source is not None:
            st = Path(ctx.source).stat()
            source = [str(ctx.source), st.st_size, st.st_mtime_ns]
    except OSError:
        pass
    font = system_font.find()
    return {"files": files, "source": source,
            "font": [font.path, font.index] if font is not None else None}


def stamp_of(ctx) -> str:
    """The stamp an index of the disc must carry to be read: the code's
    and the disc's together, as one digest."""
    text = json.dumps({"format": FORMAT, "code": code_stamp(), "disc": disc_stamp(ctx)},
                      sort_keys=True)
    return hashlib.sha1(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

#: A Kept's item when the index does not hold it: it is read again.
AGAIN = object()


class Kept:
    """An item of a tab's list as the index holds it: its row and its Fan
    row as the app shows them, and the provider's item itself where the
    provider takes it unlisted (plain data), else AGAIN: it is read again
    from its provider when it is wanted (GameSession._data)."""

    __slots__ = ("row", "fan", "item")

    def __init__(self, row: dict, fan: dict | None, item=AGAIN):
        self.row = row
        self.fan = fan
        self.item = item


def _plain(x) -> bool:
    """Data an index holds as it is: numbers, strings and None, in tuples."""
    if x is None or type(x) in (int, str, bool):
        return True
    return type(x) is tuple and all(_plain(i) for i in x)


def _tuples(x):
    """Plain data as an index holds it (a tuple is a JSON list), back."""
    if type(x) is list:
        return tuple(_tuples(i) for i in x)
    if x is None or type(x) in (int, str, bool):
        return x
    raise ValueError("not plain data")


def _part(zf: zipfile.ZipFile, name: str) -> bytes:
    if zf.getinfo(name).file_size > MAX_PART:
        raise ValueError(f"{name}: larger than an index's part")
    return zf.read(name)


def _identity(ident) -> Identity | None:
    if ident is None:
        return None
    key, size, digest = ident
    if (type(key) is not str or not (size is None or type(size) is int)
            or not (digest is None or type(digest) is str)):
        raise ValueError("not an identity")
    return Identity(key, size, None if digest is None else (lambda: digest))


def _listed(entries) -> list[tuple[str, Kept | None, Identity | None]]:
    """A view's items as merge takes them: (label, data, identity), the
    data a Kept, or None where the provider's item was None."""
    out = []
    for row, fan, ident, *item in entries:
        label, empty = row["label"], row["empty"]
        if type(label) is not str or type(empty) is not bool or not (
                fan is None or isinstance(fan, dict)) or len(item) > 1:
            raise ValueError("not a row")
        kept = None if empty else Kept(row, fan, _tuples(item[0]) if item else AGAIN)
        out.append((label, kept, _identity(ident)))
    return out


class DiscIndex:
    """One disc's index as this process reads it: whether it is there and
    current (`ready`), a tab's list (`listed`), its links (`links`)."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.path = config.index_file(ctx.data_dir)
        self._lock = threading.Lock()
        self._stamp: str | None = None
        #: the file as last looked at (mtime, size, inode), and whether it was current
        self._seen: tuple | None = None
        self._ok = False
        #: tab key -> its views as read (view -> entries), None where unreadable
        self._tabs: dict[str, dict | None] = {}
        #: (tab key, view) -> its items, made from the entries once
        self._listed: dict[tuple[str, str], list | None] = {}

    def stamp(self) -> str:
        if self._stamp is None:
            self._stamp = stamp_of(self.ctx)
        return self._stamp

    def ready(self) -> bool:
        """The file is there, whole, and was made from this disc and this
        code. Looked at again only when the file changes."""
        if not enabled():
            return False
        try:
            st = self.path.stat()
        except OSError:
            with self._lock:
                self._seen, self._ok = None, False
            return False
        seen = (st.st_mtime_ns, st.st_size, st.st_ino)
        with self._lock:
            if seen != self._seen:
                self._seen, self._tabs, self._listed = seen, {}, {}
                self._ok = self._read_stamp() == self.stamp()
            return self._ok

    def _read_stamp(self) -> str | None:
        try:
            with zipfile.ZipFile(self.path) as zf:
                head = json.loads(_part(zf, "stamp.json"))
            return head["stamp"] if head.get("format") == FORMAT else None
        except Exception:
            return None

    def listed(self, key: str, view: str | None) -> list | None:
        """Tab `key`'s items in `view` as merge takes them, (label, Kept or
        None, identity) each; None when the index does not hold them."""
        if not self.ready():
            return None
        which = (key, "" if view is None else view)
        with self._lock:
            if which in self._listed:
                return self._listed[which]
            if key not in self._tabs:
                self._tabs[key] = self._read_tab(key)
            views = self._tabs[key]
            got = None
            if views is not None and which[1] in views:
                try:
                    got = _listed(views[which[1]])
                except Exception:
                    got = None                  # read from the disc instead
            self._listed[which] = got
            return got

    def _read_tab(self, key: str) -> dict | None:
        try:
            with zipfile.ZipFile(self.path) as zf:
                part = json.loads(_part(zf, f"tabs/{key}.json"))
            if part.get("stamp") != self.stamp() or not isinstance(part.get("views"), dict):
                return None
            return part["views"]
        except Exception:
            return None

    def links(self, model) -> tab_links.LinkIndex | None:
        """The disc's links as the index holds them, or None."""
        if not self.ready():
            return None
        try:
            with zipfile.ZipFile(self.path) as zf:
                head = json.loads(_part(zf, "links.json"))
                if head.get("stamp") != self.stamp():
                    return None
                raw = _part(zf, "links.bin")
            return _read_links(model, head, raw)
        except Exception:
            return None

    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0


_by_dir: dict[Path, DiscIndex] = {}
_by_dir_lock = threading.Lock()


def of_ctx(ctx) -> DiscIndex:
    """The process's reading of the disc's index (one per extracted disc,
    so a stamp is made once). `forget` drops it."""
    key = Path(ctx.data_dir)
    with _by_dir_lock:
        got = _by_dir.get(key)
        if got is None or got.ctx.game != ctx.game:
            got = _by_dir[key] = DiscIndex(ctx)
        return got


def forget(data_dir) -> None:
    """The disc at `data_dir` was replaced: its index is looked at afresh."""
    here = Path(data_dir).resolve()
    with _by_dir_lock:
        for key in [k for k in _by_dir if Path(k).resolve() == here]:
            del _by_dir[key]


def _load_links(model) -> tab_links.LinkIndex | None:
    """LinkIndex.loader: the disc's links from its index, when it has a
    current one."""
    if not enabled():
        return None
    try:
        ctx = model.ctx
        Path(ctx.data_dir)
    except Exception:
        return None
    return of_ctx(ctx).links(model)


tab_links.LinkIndex.loader = _load_links
# A disc's links are listed in the order their domains registered (the
# order LinkIndex reads them in), and a provider that imports one of them
# first changes that order. Registered here, as the backend starts and
# before any provider runs, they are in the one order every backend
# meets them in, so links read from an index are listed as a backend
# without one lists them.
tab_links._load_domains()


# ---------------------------------------------------------------------------
# The links, as numbers
# ---------------------------------------------------------------------------
#
# links.json: the things linked (`refs`, each its kind's number in `kinds`
# and its parts), every string once (`strings`), each thing's title (a
# string's number), the things listed last, the domains' errors, and how
# long each array of links.bin is. links.bin: little-endian 32-bit numbers,
#
#   edges       6 a link: from, to (things), rel, back, note, proof (strings)
#   out keys    the things with links out, in the order LinkIndex.out has them
#   out starts  where each one's links begin in `out list` (one more: the end)
#   out list    the links (edges' numbers), each thing's in its order
#   into keys, into starts, into list: the same for LinkIndex.into

_ARRAYS = ("edges", "out_keys", "out_starts", "out_list",
           "into_keys", "into_starts", "into_list")


def _int32() -> array.array:
    a = array.array("i")
    if a.itemsize != 4:
        raise RuntimeError("no 32-bit array on this machine")
    return a


def _links_part(model, stamp: str) -> tuple[bytes, bytes]:
    index = tab_links.LinkIndex.of(model)
    kinds: dict[str, int] = {}
    strings: dict[str, int] = {}
    refs: dict[Ref, int] = {}
    edges: dict[tab_links.Edge, int] = {}
    arrays = {name: _int32() for name in _ARRAYS}

    def text(s) -> int:
        if type(s) is not str:
            raise TypeError(f"not a string: {s!r}")
        return strings.setdefault(s, len(strings))

    def thing(r: Ref) -> int:
        if r not in refs:
            if type(r.kind) is not str or not all(type(i) is int for i in r.id):
                raise TypeError(f"not a reference: {r!r}")
            kinds.setdefault(r.kind, len(kinds))
            refs[r] = len(refs)
        return refs[r]

    def edge(e) -> int:
        if e not in edges:
            edges[e] = len(edges)
            arrays["edges"].extend((thing(e.frm), thing(e.to), text(e.rel), text(e.back),
                                    text(e.note), text(e.proof)))
        return edges[e]

    for way in ("out", "into"):
        keys, starts, listed = (arrays[f"{way}_{a}"] for a in ("keys", "starts", "list"))
        for r, es in getattr(index, way).items():
            keys.append(thing(r))
            starts.append(len(listed))
            listed.extend(edge(e) for e in es)
        starts.append(len(listed))
    titles = [text(tab_links.title_of(model, r)) for r in refs]
    head = {
        "stamp": stamp,
        "kinds": list(kinds),
        "strings": list(strings),
        "refs": [[kinds[r.kind], *r.id] for r in refs],
        "titles": titles,
        "last": [n for r, n in refs.items() if tab_links.is_last(model, r)],
        "errors": [str(e) for e in index.errors],
        "lengths": {name: len(a) for name, a in arrays.items()},
    }
    raw = b""
    for name in _ARRAYS:
        a = arrays[name]
        if sys.byteorder == "big":
            a.byteswap()
        raw += a.tobytes()
    return json.dumps(head, separators=(",", ":")).encode(), raw


class _Edges(Mapping):
    """LinkIndex.out or .into as the index holds it: each thing's links,
    made into Edges the first time they are asked for."""

    def __init__(self, at: dict[Ref, int], starts, listed, edge: Callable):
        self._at, self._starts, self._listed, self._edge = at, starts, listed, edge
        self._made: dict[Ref, list] = {}

    def __getitem__(self, r: Ref) -> list:
        got = self._made.get(r)
        if got is None:
            n = self._at[r]
            got = self._made[r] = [self._edge(e) for e in
                                   self._listed[self._starts[n]:self._starts[n + 1]]]
        return got

    def __contains__(self, r) -> bool:
        return r in self._at

    def __iter__(self):
        return iter(self._at)

    def __len__(self) -> int:
        return len(self._at)


def _read_links(model, head: dict, raw: bytes) -> tab_links.LinkIndex:
    lengths = head["lengths"]
    a = _int32()
    a.frombytes(raw)
    if sys.byteorder == "big":
        a.byteswap()
    if len(a) != sum(lengths[name] for name in _ARRAYS):
        raise ValueError("links.bin is not as long as links.json says")
    arrays, at = {}, 0
    for name in _ARRAYS:
        arrays[name] = a[at:at + lengths[name]]
        at += lengths[name]
    kinds, strings = head["kinds"], head["strings"]
    if not all(type(s) is str for s in kinds) or not all(type(s) is str for s in strings):
        raise ValueError("not strings")
    refs = []
    for row in head["refs"]:
        if not row or not all(type(i) is int for i in row) or not 0 <= row[0] < len(kinds):
            raise ValueError("not a reference")
        refs.append(Ref(kinds[row[0]], tuple(row[1:])))
    edges = arrays["edges"]
    n_edges = len(edges) // 6
    if len(edges) % 6:
        raise ValueError("a link of fewer than six numbers")

    def within(values, end: int):
        if len(values) and (min(values) < 0 or max(values) >= end):
            raise ValueError("a number out of range")

    for way in ("out", "into"):
        keys, starts, listed = (arrays[f"{way}_{x}"] for x in ("keys", "starts", "list"))
        within(keys, len(refs))
        within(listed, n_edges)
        if (len(starts) != len(keys) + 1 or (len(starts) and (starts[0] != 0 or starts[-1] != len(listed)))
                or any(x > y for x, y in zip(starts, starts[1:]))):
            raise ValueError("links out of order")
    within(edges[0::6], len(refs))
    within(edges[1::6], len(refs))
    for field in range(2, 6):
        within(edges[field::6], len(strings))
    titles = head["titles"]
    if len(titles) != len(refs) or not all(type(t) is int for t in titles):
        raise ValueError("not a title each")
    within(array.array("i", titles), len(strings))
    last = head["last"]
    if not all(type(n) is int for n in last):
        raise ValueError("not a thing")
    within(array.array("i", last), len(refs))
    errors = head["errors"]
    if not all(type(e) is str for e in errors):
        raise ValueError("not an error")

    def edge(n: int) -> tab_links.Edge:
        f = edges[6 * n:6 * n + 6]
        return tab_links.Edge(refs[f[0]], refs[f[1]], strings[f[2]], strings[f[3]],
                              strings[f[4]], strings[f[5]])

    index = tab_links.LinkIndex.__new__(tab_links.LinkIndex)
    index.model = model
    for way in ("out", "into"):
        keys = arrays[f"{way}_keys"]
        setattr(index, way, _Edges({refs[k]: n for n, k in enumerate(keys)},
                                   arrays[f"{way}_starts"], arrays[f"{way}_list"], edge))
    index.errors = list(errors)
    index.kept = tab_links.Kept({r: strings[t] for r, t in zip(refs, titles)},
                                {refs[n] for n in last})
    return index


# ---------------------------------------------------------------------------
# Making one
# ---------------------------------------------------------------------------

def _tab_part(prov, ctx, archive) -> dict:
    """A tab's list in each of its views, as `_listed` reads it: each item
    its row (viewer_server.present.item_rows), its Fan row and identity,
    and the item itself where the provider takes it unlisted."""
    from viewer_server.present import item_rows
    views = list(getattr(prov, "get_views", lambda: [])()) or [None]
    identify = getattr(prov, "item_identity", None)
    fan_row = getattr(prov, "fan_row", None)
    unlisted = getattr(prov, "selects_unlisted", False)
    out = {}
    for view in views:
        if view is not None:
            prov.view = view
        items = prov.get_items({}, archive, ctx, None)
        listed = []
        for (label, data), row in zip(items, item_rows(prov, items)):
            ident = fan = None
            if identify is not None and data is not None:
                i = identify(label, data, ctx)
                ident = [i.key, i.size, None if i.digest is None else i.digest()]
                _identity(ident)                # a key the index can hold
            if fan_row is not None and data is not None:
                try:
                    fan = fan_row(label, data, ctx)
                except Exception:
                    fan = None                  # the row as written, as the session does
            item = [data] if unlisted and data is not None and _plain(data) else []
            listed.append([row, fan, ident] + item)
        out["" if view is None else view] = listed
    return out


def build(ctx, progress: Callable | None = None,
          stop: Callable[[], bool] | None = None) -> bool:
    """Read the disc whole and write its index (a tab its provider cannot
    list is left out, and is read from the disc; so are the links when a
    domain of them failed). False, and nothing written, when the disc
    changed while it was read, or `stop()` said to stop (it is asked
    before each tab and before the index is written). An index that
    cannot be written raises (`_write`)."""
    from decoders.plugins.SLUS_006_28.formats.lunadata import LunaDataArchive
    from viewer_server.session import tab_key
    from viewer_tabs.model import GameModel
    from viewer_tabs.tab_providers import providers_for

    def say(message, current, total):
        if progress is not None:
            progress(message, current, total)

    stamp = stamp_of(ctx)
    path = config.index_file(ctx.data_dir)
    archive = LunaDataArchive(ctx.path("LUNADATA.FIL")) if ctx.has("LUNADATA.FIL") else None
    providers = providers_for(ctx)
    total = len(providers) + 1
    parts: dict[str, bytes] = {}
    for n, prov in enumerate(providers):
        if stop is not None and stop():
            return False
        say(f"Indexing… {prov.name}", n, total)
        key = tab_key(type(prov))
        try:
            part = {"stamp": stamp, "views": _tab_part(prov, ctx, archive)}
            parts[f"tabs/{key}.json"] = json.dumps(part, default=str,
                                                   separators=(",", ":")).encode()
        except Exception:
            traceback.print_exc()           # that tab is read from the disc
        _touch(path)
    say("Indexing… links", total - 1, total)
    try:
        model = GameModel.for_ctx(ctx)
        errors = tab_links.LinkIndex.of(model).errors
        if errors:
            # Not kept: a failure that may pass would be kept for good.
            # They are made again when first wanted.
            print(f"{ctx.data_dir}: the links are not indexed: " + "; ".join(errors),
                  file=sys.stderr)
        else:
            parts["links.json"], parts["links.bin"] = _links_part(model, stamp)
    except Exception:
        traceback.print_exc()               # the links are made when first wanted
    if (stop is not None and stop()) or stamp_of(ctx) != stamp:
        return False                        # the dump changed under the reading
    parts["stamp.json"] = json.dumps({"format": FORMAT, "stamp": stamp,
                                      "made": round(time.time())}).encode()
    _write(path, parts)
    say("Indexed", total, total)
    return True


def _write(path: Path, parts: dict[str, bytes], tries: int = 5) -> None:
    """The index, whole, under a temporary name, then renamed into place.
    The rename is tried again while Windows says a reader has the file
    open; PermissionError when it still does."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for name, data in parts.items():
                zf.writestr(name, data)
        for attempt in range(tries):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:         # Windows: a reader has it open
                if attempt == tries - 1:
                    raise
                time.sleep(0.2 * (attempt + 1))
    finally:
        tmp.unlink(missing_ok=True)


def _sweep(path: Path) -> None:
    """Remove what a backend that stopped while it wrote the index at
    `path` left of it (`_write`'s temporary files)."""
    for tmp in path.parent.glob(f".{path.name}.*.tmp"):
        try:
            if time.time() - tmp.stat().st_mtime > LOCK_STALE:
                tmp.unlink()
        except OSError:
            pass


def _lock_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.lock")


def _alive(pid: int) -> bool:
    """Whether process `pid` is running on this machine."""
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) would END the process on Windows: ask instead
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5             # ERROR_ACCESS_DENIED: it runs
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259                        # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                         # another user's: it runs
    return True


def _left(lock: Path) -> bool:
    """Whether the lock at `lock` was left by a backend that stopped: the
    process it names is not running, or is this one (which never takes a
    lock it holds: Indexer.build; so the pid is an old backend's, used
    again), or it went untouched for LOCK_STALE. OSError when there is
    no lock."""
    if time.time() - lock.stat().st_mtime >= LOCK_STALE:
        return True
    try:
        pid = int(lock.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False                        # being written just now
    return pid == os.getpid() or not _alive(pid)


def _take(path: Path) -> bool:
    """The lock that says a backend is making the index at `path`; False
    when another holds it (`_left` says it does not)."""
    lock = _lock_path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if not _left(lock):
                    return False
            except OSError:
                continue                    # let go of just now: try again
            lock.unlink(missing_ok=True)    # left by a backend that stopped
            continue
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    return False


def _touch(path: Path) -> None:
    try:
        os.utime(_lock_path(path))
    except OSError:
        pass


def _held_elsewhere(path: Path) -> bool:
    try:
        return not _left(_lock_path(path))
    except OSError:
        return False


# ---------------------------------------------------------------------------
# The indexer
# ---------------------------------------------------------------------------

class Indexer:
    """Makes the library's indexes, a disc at a time: on the thread that
    asks (`build`, the extraction job's last step), or on a thread of its
    own for every disc whose index is missing or stale (`start`, when the
    backend starts). `status` is what the library screen shows."""

    def __init__(self):
        self._lock = threading.Lock()
        #: a disc's folder -> its progress, while this process makes its index
        self._making: dict[Path, dict] = {}
        self._queued: list[Path] = []
        #: dumps being replaced (`replacing`), resolved: none is indexed
        self._replacing: set[Path] = set()
        self._thread: threading.Thread | None = None

    def _replaced(self, here: Path) -> bool:
        return Path(here).resolve() in self._replacing

    @contextmanager
    def replacing(self, dump):
        """While the dump at `dump` is extracted again: no index of it is
        made, one this process is making stops at its next tab, and this
        waits for it to (REPLACE_WAIT at most), so that no file of the dump
        is held open when it is renamed aside (Windows refuses that)."""
        here = Path(dump).resolve()
        with self._lock:
            self._replacing.add(here)
        try:
            deadline = time.monotonic() + REPLACE_WAIT
            while time.monotonic() < deadline:
                with self._lock:
                    if not any(p.resolve() == here for p in self._making):
                        break
                time.sleep(0.05)
            yield
        finally:
            with self._lock:
                self._replacing.discard(here)

    def status(self, game) -> dict:
        """{"state": ready | making | queued | missing | stale | off}, with
        the progress while it is made and the file's size once it is."""
        if not enabled():
            return {"state": "off"}
        here = Path(game.path)
        with self._lock:
            making = self._making.get(here)
            if making is not None:
                return {"state": "making", **making}
            if here in self._queued:
                return {"state": "queued"}
        from viewer_tabs.context import DiscContext
        index = of_ctx(DiscContext.for_game(game))
        if index.ready():
            return {"state": "ready", "bytes": index.size()}
        if _held_elsewhere(index.path):
            return {"state": "making", "message": "Indexing…", "current": 0, "total": 0}
        return {"state": "stale" if index.path.exists() else "missing"}

    def build(self, game, progress: Callable | None = None) -> bool:
        """Make the disc's index now, on this thread, unless it is current.
        False when it could not be made (another backend is making it, the
        dump is being replaced, or the disc changed while it was read)."""
        if not enabled():
            return False
        from viewer_tabs.context import DiscContext
        ctx = DiscContext.for_game(game)
        here = Path(game.path)
        with self._lock:
            if here in self._making or self._replaced(here):
                return False                # made already, or being replaced
            self._making[here] = {"message": "Indexing…", "current": 0, "total": 0}
            if here in self._queued:
                self._queued.remove(here)
        path = config.index_file(ctx.data_dir)

        def report(message, current, total):
            with self._lock:
                self._making[here] = {"message": message, "current": current, "total": total}
            if progress is not None:
                progress(message, current, total)

        try:
            forget(ctx.data_dir)
            if of_ctx(ctx).ready():
                return True
            if not _take(path):
                return False
            try:
                _sweep(path)
                return build(ctx, report, stop=lambda: self._replaced(here))
            finally:
                _lock_path(path).unlink(missing_ok=True)
        finally:
            with self._lock:
                self._making.pop(here, None)
            forget(ctx.data_dir)

    def build_each(self, games: list, progress: Callable | None = None) -> None:
        """Make the discs' indexes one after another, on this thread: each
        waits its turn in `status` (queued), and one made meanwhile, by
        another job, is left as it is."""
        here = [Path(g.path) for g in games]
        with self._lock:
            self._queued += [p for p in here if p not in self._queued]
        try:
            for game, path in zip(games, here):
                with self._lock:
                    if path not in self._queued:
                        continue            # made meanwhile, by another job
                try:
                    self.build(game, progress)
                except Exception:
                    traceback.print_exc()   # the disc is read from its files
        finally:
            with self._lock:
                self._queued = [p for p in self._queued if p not in here]

    def start(self, delay: float = 2.0) -> None:
        """Index every disc of the library whose index is missing or stale,
        one at a time on a thread of its own, the games' discs first in the
        order a game lists them."""
        if not enabled():
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, args=(delay,),
                                            daemon=True, name="indexer")
            self._thread.start()

    def _discs(self) -> list:
        from decoders.psx.gamedb.database import GameDatabase
        from decoders.psx.gamedb.known_games import GAMES
        from viewer_server.library import game_members
        order = []
        for g in GAMES:
            try:
                order += game_members(g.key)[1]
            except KeyError:
                continue
        seen = {Path(g.path) for g in order}
        return order + [g for g in GameDatabase().get_installed_games()
                        if Path(g.path) not in seen]

    def _run(self, delay: float) -> None:
        time.sleep(delay)                   # the app's first requests first
        from viewer_tabs.context import DiscContext

        def ready(g) -> bool:
            return of_ctx(DiscContext.for_game(g)).ready()

        def held(g) -> bool:
            return _held_elsewhere(config.index_file(g.path))

        waiting = [g for g in self._discs() if not ready(g)]
        while waiting:
            self.build_each(waiting)
            # A disc another backend was making when its turn came waits
            # until that one lets go of it, and is made here then unless
            # that one made it (it stopped first: the app was closed).
            waiting = [g for g in waiting if not ready(g) and held(g)]
            while waiting and all(held(g) and not ready(g) for g in waiting):
                time.sleep(LOCK_POLL)
            waiting = [g for g in waiting if not ready(g)]


INDEXER = Indexer()

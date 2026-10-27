"""The links between the game's things, and the card each thing shows.

docs/taxonomy.md is the reference: what each kind is called, how it is
numbered, and which links the code makes. This package holds them:

- an **edge** is one link the code makes from a thing to another: a map
  plays a song, a battle is started by a map monster. Every edge says which
  function makes it, and is kept both ways, so the card of a song lists the
  maps that play it as well as the bank it plays from.
- a **card** is what a thing shows when a link is followed: its title, a
  picture, its facts in plain words, its links grouped, and the extended
  info (the code's name, the number in hex, what proves it).

Each domain module (sound, world, battle …) registers what it knows with
the decorators below: `@edges` for a function yielding every edge of
the disc, `@card(kind)` for the card of one thing, `@title(kind)` for the
short title a link to it shows, and `@listed_last` for the things listed
after the others wherever links are (the debug room's). A kind with no
card yet still has a title (its written reference) and its links.

The index of every edge is built once per disc (`LinkIndex.of(model)`), on
first use; a domain that cannot be read says so in the index's `errors`
and the rest still link, as does what a domain read past (`@unread`: a
script, a map). Each error is printed to stderr as the index is built,
and every card says its links may be missing, in its extended info.

A domain that reads the program and LUNADATA.FIL alone registers its edges
`@edges(kept=True)`: they are made once for the discs that carry the same
two files (GameModel.twin) and kept there, so the second disc's index puts
them in without reading them again. Where the library keeps a disc's index
(viewer_server.index, through `LinkIndex.loader`) it is read from there
instead, with every thing's title and whether it is listed last (`kept`).
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable

from viewer_tabs.names import UnknownProgram
from viewer_tabs.refs import KINDS, Ref, number_hex, written, written_hex


@dataclass(frozen=True)
class Edge:
    """A link the code makes: `frm` -> `to`.

    `rel` heads the group the link shows in on `frm`'s card ("Music"),
    `back` the group on `to`'s card ("Played on"). `note` says how, in plain
    words; `proof` the function that makes it, as the register names it."""
    frm: Ref
    to: Ref
    rel: str
    back: str
    note: str = ""
    proof: str = ""


@dataclass
class CardBody:
    """What a domain says of one thing; the rest of the card (its number,
    its links, its home) is put round it here and by the session."""
    title: str
    subtitle: str = ""
    picture: object | None = None           # a PIL image, drawn with square pixels
    facts: list[tuple[str, str]] = field(default_factory=list)
    #: a paragraph or two in plain words, under the facts
    note: str = ""
    #: the extended info: facts for whoever wants how it is done
    extended: list[tuple[str, str]] = field(default_factory=list)
    #: the functions that prove what the card says
    proven: list[str] = field(default_factory=list)


_EDGES: list[Callable] = []
#: the edge functions registered `kept`: made once for twin discs
_KEPT: set[Callable] = set()
_CARDS: dict[str, Callable] = {}
_TITLES: dict[str, Callable] = {}
_LAST: list[Callable] = []
_UNREAD: list[Callable] = []
_ORDERS: dict[str, tuple[str, ...]] = {}
_ADVANCED: dict[str, frozenset[str]] = {}


def edges(fn: Callable | None = None, *, kept: bool = False):
    """Register `fn(model) -> Iterable[Edge]`: every edge of a domain.
    `kept`: what the function reads is the program's and LUNADATA.FIL's
    alone (the model's parts, what it keeps and its names), so its edges
    are made on the model's twin and kept there (`made`)."""
    def register(fn: Callable) -> Callable:
        _EDGES.append(fn)
        if kept:
            _KEPT.add(fn)
        return fn
    return register if fn is None else register(fn)


def unread(fn: Callable) -> Callable:
    """Register `fn(model) -> Iterable[str]`: what a domain read past and
    read the rest without (a script, a map), a sentence each. The index
    lists it with the domains that could not be read: the links it would
    have made are missing."""
    _UNREAD.append(fn)
    return fn


def made(model, fn: Callable, keep: bool = True) -> Iterable[Edge]:
    """The edges `fn` makes on `model`'s disc: a `kept` function's are made
    once for the discs whose model has one twin (GameModel.kept), unless
    `keep` is false."""
    if keep and fn in _KEPT:
        return model.kept(f"_edges {fn.__module__}.{fn.__qualname__}",
                          lambda twin: tuple(fn(twin)))
    return list(fn(model))


def card(kind: str):
    """Register `fn(model, ref) -> CardBody` for one kind."""
    if kind not in KINDS:
        raise KeyError(f"no kind {kind!r}")

    def wrap(fn):
        _CARDS[kind] = fn
        return fn
    return wrap


def title(kind: str):
    """Register `fn(model, ref) -> str | None`: a link's title for one kind."""
    if kind not in KINDS:
        raise KeyError(f"no kind {kind!r}")

    def wrap(fn):
        _TITLES[kind] = fn
        return fn
    return wrap


def listed_last(fn: Callable) -> Callable:
    """Register `fn(model, ref) -> bool`: is this thing listed after the
    others? The debug room's maps, scripts and objects are, wherever links
    name them (docs/taxonomy.md)."""
    _LAST.append(fn)
    return fn


def is_last(model, r: Ref) -> bool:
    """Whether `r` is listed after the others (`listed_last`)."""
    kept = _kept(model)
    if kept is not None and r in kept.titles:
        return r in kept.last
    _load_domains()
    for fn in _LAST:
        try:
            if fn(model, r):
                return True
        except Exception:
            continue
    return False


def group_order(kind: str, *titles: str) -> None:
    """Put the link groups titled `titles` first on a card of `kind`, in
    that order: a story flag's Set by, Cleared by, Checked by."""
    if kind not in KINDS:
        raise KeyError(f"no kind {kind!r}")
    _ORDERS[kind] = titles


def advanced_groups(kind: str, *titles: str) -> None:
    """Show the link groups titled `titles` on a card of `kind` with the
    extended info in Fan mode, and open in Advanced: the code's workings an
    engineer looks for, not what a player meets (a story flag's *Held in*
    and *Goes on at*). Each of their links is marked `advanced`, as a link
    to a kind whose home is only in Advanced mode is."""
    if kind not in KINDS:
        raise KeyError(f"no kind {kind!r}")
    _ADVANCED[kind] = frozenset(titles)


#: The domain modules, which register themselves on import.
DOMAINS = ("sound", "world", "battle", "media", "sprites", "story", "voices", "flags",
           "sound_effects")


_loaded = False


def _load_domains():
    global _loaded
    if _loaded:
        return
    import importlib
    for name in DOMAINS:
        importlib.import_module(f"viewer_tabs.links.{name}")
    _loaded = True


@dataclass
class Kept:
    """What an index read from the library holds besides its edges: every
    linked thing's title (`title_of`) and those listed last (`is_last`)."""
    titles: dict[Ref, str]
    last: set[Ref]


def _kept(model) -> Kept | None:
    index = getattr(model, "__dict__", {}).get("_link_index")
    return getattr(index, "kept", None)


class LinkIndex:
    """Every edge of one disc, both ways."""

    _lock = threading.Lock()
    #: `loader(model) -> LinkIndex | None`: the disc's index as the library
    #: keeps it, or None (viewer_server.index sets it).
    loader: Callable | None = None
    #: titles and things listed last, on an index the loader read
    kept: Kept | None = None

    def __init__(self, model, sources: Iterable[Callable] | None = None):
        """The index of every domain's edges, or of `sources`' alone: an
        index of chosen sources (a test's) makes all of them afresh."""
        self.model = model
        self.out: dict[Ref, list[Edge]] = {}
        self.into: dict[Ref, list[Edge]] = {}
        #: what a domain could not read, as a sentence each
        self.errors: list[str] = []
        # the code can make one link several ways (two entrances from one
        # map to another): it is kept once
        seen: set[Edge] = set()
        every = sources is None
        sources = list(_EDGES if every else sources)
        for fn in sources:
            try:
                found = made(model, fn, keep=every)
            except UnknownProgram:
                continue                    # the game's own links: none on this program
            except Exception as ex:          # one domain failing leaves the rest
                self.errors.append(f"{fn.__module__}.{fn.__name__}: {type(ex).__name__}: {ex}")
                continue
            for e in found:
                if e in seen:
                    continue
                seen.add(e)
                self.out.setdefault(e.frm, []).append(e)
                self.into.setdefault(e.to, []).append(e)
        # what the domains read past, each read now (it was kept as they read)
        domains = {fn.__module__ for fn in sources}
        for fn in _UNREAD:
            if fn.__module__ not in domains:
                continue
            try:
                self.errors += [f"{fn.__module__}: {s}" for s in fn(model)]
            except Exception:
                continue                    # its domain's own error says why
        for e in self.errors:
            print(f"links: could not read {e}", file=sys.stderr)

    @classmethod
    def of(cls, model) -> "LinkIndex":
        """The disc's index, the first time it is asked for read from the
        library's (`loader`) or else built. One built or read already is
        handed over without waiting on another disc's being built."""
        _load_domains()
        index = model.__dict__.get("_link_index")
        if index is not None:
            return index
        loaded = cls.loader(model) if cls.loader is not None else None
        if loaded is not None:
            return model.__dict__.setdefault("_link_index", loaded)
        with cls._lock:
            index = model.__dict__.get("_link_index")
            if index is None:
                index = model.__dict__["_link_index"] = cls(model)
            return index


#: the kinds whose title could not be read, each said once on stderr
_UNTITLED: set[str] = set()


def title_of(model, r: Ref) -> str:
    """A link's title: the domain's, else the written reference (and a
    title that could not be read is said on stderr, the first of a kind)."""
    kept = _kept(model)
    if kept is not None and r in kept.titles:
        return kept.titles[r]
    _load_domains()
    fn = _TITLES.get(r.kind)
    if fn is not None:
        try:
            t = fn(model, r)
        except Exception as ex:
            t = None
            if r.kind not in _UNTITLED:
                _UNTITLED.add(r.kind)
                print(f"links: {written(r)}'s title could not be read, its reference shown "
                      f"instead (said once for every {r.kind}): {type(ex).__name__}: {ex}",
                      file=sys.stderr)
        if t:
            return t
    return written(r)


def link_json(model, r: Ref, note: str = "") -> dict:
    """A link as the app shows it: the reference, its title and number.
    `advanced`: its kind's home is only in Advanced mode (a resource, a
    sound bank), so Fan mode shows it with the extended info."""
    return {"ref": r.json(), "title": title_of(model, r), "written": written(r),
            "hex": written_hex(r), "note": note, "advanced": KINDS[r.kind].advanced}


def groups(model, index: LinkIndex, r: Ref) -> list[dict]:
    """The card's links: what it points at, by `rel` ("dir": "out"), then
    what points at it, by `back` ("dir": "in"), each group in the order the
    edges came, the things listed last (`listed_last`) after the rest; the
    groups its kind puts first (`group_order`) first; the links of the
    groups its kind shows with the extended info (`advanced_groups`) marked
    `advanced`. A
    thing linked in one group several ways (a tile change sets its flag and
    is loaded changed while it is set) is listed once, with each way's note
    and proof."""
    listed: dict[tuple[str, str], list[Ref]] = {}
    #: (title, thing) -> the direction it is listed in, its notes and proofs
    seen: dict[tuple[str, Ref], tuple[str, list, list]] = {}
    for d, e in [("out", e) for e in index.out.get(r, [])] + \
                [("in", e) for e in index.into.get(r, [])]:
        title, other = (e.rel, e.to) if d == "out" else (e.back, e.frm)
        if (title, other) not in seen:
            seen[(title, other)] = (d, [], [])
            listed.setdefault((d, title), []).append(other)
        was, notes, proofs = seen[(title, other)]
        if was == d:
            notes += [e.note] if e.note and e.note not in notes else []
            proofs += [e.proof] if e.proof and e.proof not in proofs else []
    order = _ORDERS.get(r.kind, ())
    advanced = _ADVANCED.get(r.kind, frozenset())
    ranked = sorted(listed.items(), key=lambda g: order.index(g[0][1]) if g[0][1] in order
                    else len(order))
    out = []
    for (d, t), found in ranked:
        group = []
        for o in sorted(found, key=lambda o: is_last(model, o)):
            link = {**link_json(model, o, "; ".join(seen[(t, o)][1])),
                    "proof": "; ".join(seen[(t, o)][2])}
            if t in advanced:
                link["advanced"] = True
            group.append(link)
        out.append({"title": t, "dir": d, "links": group})
    return out


def card_body(model, r: Ref) -> tuple[CardBody, str]:
    """What the domain says of `r`, and why it could not say it ("" when
    it could): a body titled by the link's title then. A tab's page of a
    thing is laid out from this, as its card is."""
    _load_domains()
    fn = _CARDS.get(r.kind)
    if fn is not None:
        try:
            return fn(model, r), ""
        except Exception as ex:
            return (CardBody(title=title_of(model, r)),
                    f"Could not read {written(r)}: {type(ex).__name__}: {ex}")
    return CardBody(title=title_of(model, r)), ""


#: The parts of the disc the index could not read a card names; the rest
#: are counted.
UNREAD_SHOWN = 5


def unread_of(index: LinkIndex) -> list[tuple[str, str]]:
    """What a card says when its links may be missing: each part of the
    disc the index could not read (its domain) and why."""
    said = [("Links may be missing", e.removeprefix(f"{__name__}."))
            for e in index.errors[:UNREAD_SHOWN]]
    if len(index.errors) > UNREAD_SHOWN:
        said.append(("Links may be missing",
                     f"and {len(index.errors) - UNREAD_SHOWN} more parts not read"))
    return said


def extended_of(r: Ref, body: CardBody, index: LinkIndex | None = None
                ) -> list[tuple[str, str]]:
    """The extended info: the code's name and the number in hex, then the
    domain's own, then what of the disc `index` could not read."""
    kind = KINDS[r.kind]
    return [("The code's name", kind.code),
            ("Number", f"{written(r)} · {number_hex(r)}"), *body.extended,
            *(unread_of(index) if index is not None else ())]


def build_card(model, r: Ref, put_image: Callable | None = None) -> dict:
    """The card of `r`: the domain's body with its number, links and the
    code's name round it. `put_image(picture) -> blob id` stores a picture."""
    kind = KINDS[r.kind]
    body, error = card_body(model, r)
    index = LinkIndex.of(model)
    extended = extended_of(r, body, index)
    out = {
        "ref": r.json(),
        "kind": r.kind,
        "kindName": kind.title,
        "written": written(r),
        "hex": written_hex(r),
        "title": body.title,
        "subtitle": body.subtitle,
        "facts": [list(f) for f in body.facts],
        "note": body.note,
        "groups": groups(model, index, r),
        "extended": [list(f) for f in extended],
        "proven": list(body.proven),
        "error": error,
    }
    if body.picture is not None and put_image is not None:
        out["picture"] = {"blob": put_image(body.picture), "w": body.picture.width,
                          "h": body.picture.height}
    return out

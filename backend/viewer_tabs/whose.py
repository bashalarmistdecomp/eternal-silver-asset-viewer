"""Whose a portrait is: as far as the game says, and no further
(docs/taxonomy.md, "character" and "portrait").

**The characters are the party's numbers, 1 to 12.** The string table names
them; FaceListPartySet (0x80075EFC) keeps a face-list member's number below
0xD, and the scripts' portrait-list command (0x3E, ScriptCommandFaceListSet
(0x8005E610)) names the characters a scene needs by the same numbers.
Nothing in the code gives anyone else a number.

**Character n's portraits are file n's five.** FaceListByteLoad
(0x80076094) loads file n for character n (FaceLoad((n - 1) * 5 + 1), five
faces a file: FaceCellSet (0x8001B3DC)), and ShopFaceSet (0x80054C0C) and
BtlMenuActingFaceSet (0x80049D60) show face (n - 1) * 5 + 1.

**Files 13 to 24 are no one's.** A message names a portrait by its number
alone (0xFAnn / 0xFBnn, MessageFaceSet (0x8005B36C)). The portrait lists
(FaceSlot6Load (0x8001B50C)) bundle the faces a scene shows together;
g_FaceListEntryRows (0x800B2CDC) copies their lists, and of character n's
row (FaceListEntriesSet (0x800760D0)) the menus read only the first face,
(n - 1) * 5 + 1 (MenuIconBytesDisp (0x8006C21C)). Neither says whose the
other faces are. A face of these files is a speaker of its own,
`portrait n`.

**A copy is its character's.** A picture drawn as one of a character's own
but for at most `COPY_PIXELS` of its 4096 pixels (the eyes, the mouth) is
theirs: the same drawing, read from the bytes. On the discs read, the copies
differ in 17 to 27 pixels and every other picture of files 13 to 24 from
every character's in more than 1,400. A blank picture (every texel 0) is
no one's.
"""

from __future__ import annotations

from dataclasses import dataclass

from viewer_tabs.refs import Ref, ref

#: The characters: the party's numbers (FaceListPartySet keeps them below 0xD).
PARTY_LAST = 12
#: Five faces a file (FaceCellSet).
PER_FILE = 5
#: A picture this close to a character's own is a copy of it: 1 in 100 of
#: its 64 x 64 pixels.
COPY_PIXELS = 40
#: One picture's rows and their width (FaceImageLoad: 64 x 64 at 8 bits).
SIDE = 64

FACE_CELL_SET = "FaceCellSet (0x8001B3DC)"
BYTE_LOAD = "FaceListByteLoad (0x80076094)"
MESSAGE_FACE_SET = "MessageFaceSet (0x8005B36C)"


@dataclass(frozen=True)
class Whose:
    """Whose one portrait is."""
    #: the character it is, or None for one the game ties to no one
    character: int | None
    #: for a copy, the character's own portrait it repeats
    copy_of: int | None = None
    #: and how many of its pixels differ from that one
    differ: int = 0


def own_character(face: int) -> int | None:
    """The character whose file holds `face`: file (face - 1) / 5 + 1 when
    that is 1 to 12 (FaceListByteLoad), else None."""
    if face < 1:
        return None
    c = (face - 1) // PER_FILE + 1
    return c if c <= PARTY_LAST else None


def _rows(px: bytes) -> list[bytes]:
    return [bytes(px[i:i + SIDE]) for i in range(0, SIDE * SIDE, SIDE)]


def read(pictures: dict[int, bytes]) -> dict[int, Whose]:
    """face -> Whose, for every face of `pictures` (face -> its 64 x 64
    texels): file n's for character n up to 12, a copy of one of theirs
    for them, else no one."""
    out: dict[int, Whose] = {}
    originals = {f: _rows(px) for f, px in sorted(pictures.items())
                 if own_character(f) is not None and any(px)}
    # a copy differs in at most COPY_PIXELS pixels, so it shares at least
    # this many of its rows with its original
    least_rows = SIDE - COPY_PIXELS
    for f, px in sorted(pictures.items()):
        c = own_character(f)
        if c is not None:
            out[f] = Whose(c if any(px) else None)
            continue
        found = None
        if any(px):
            rows = _rows(px)
            for g, theirs in originals.items():
                if sum(a == b for a, b in zip(rows, theirs)) < least_rows:
                    continue
                differ = sum(x != y for a, b in zip(rows, theirs) if a != b
                             for x, y in zip(a, b))
                if differ <= COPY_PIXELS and (found is None or differ < found[1]):
                    found = (g, differ)
        out[f] = Whose(own_character(found[0]), found[0], found[1]) if found else Whose(None)
    return out


def of(model) -> dict[int, Whose]:
    """face -> Whose for the disc's portraits, kept for as long as the disc
    is open."""
    def build(model):
        from viewer_tabs.links import battle
        faces = battle._faces(model)
        return read({f: px for f, (_res, _pic, px) in faces.portraits.items()})
    return model.kept("_whose", build)


def character_of(model, face: int) -> int | None:
    """The character portrait `face` is, or None."""
    got = of(model).get(face)
    return got.character if got is not None else own_character(face)


def speaker(model, face: int) -> Ref:
    """Who a message showing `face` names: the character it is, else the
    portrait itself."""
    c = character_of(model, face)
    return ref("character", c) if c is not None else ref("portrait", face)


def portraits_of(model, c: int) -> list[int]:
    """Character c's portraits: their file's that draw anything, then the
    copies of them elsewhere."""
    found = of(model)
    own = [f for f in range((c - 1) * PER_FILE + 1, c * PER_FILE + 1)
           if found.get(f, Whose(None)).character == c]
    return own + [f for f, w in sorted(found.items())
                  if w.character == c and w.copy_of is not None]


def name(model, c: int) -> str | None:
    """Character c's name from the string table, or None."""
    names = model.names
    return names.character(c) if names is not None and 1 <= c <= PARTY_LAST else None


def word(model, r: Ref) -> str:
    """A speaker in words: a character by name, else "character n"; a
    portrait no one is, "portrait n"."""
    if r.kind == "character":
        return name(model, r.id[0]) or f"character {r.id[0]}"
    return f"portrait {r.id[0]}"

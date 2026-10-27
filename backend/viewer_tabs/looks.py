"""Who wears each field sprite: the looks (docs/taxonomy.md, "look").

An object set carries its own copy of every sprite it needs:
MapObjectsDataLoad (0x80065418) loads the set's sprite data list and its
pages, and MapObjectInit (0x800656CC) puts each definition on sprite data
byte 1 (kind 7 on sprite data 0, resource 2's chest). The party walks on
its own field sheets, resource 0x1E8 (MapPartySpriteDataLoad
(0x80063D48)). One sprite is copied into many sets, each copy with its
texels at a place of its own on the set's pages, so the viewer lists one
entry per **look**: the copies that draw the same pixels. Two copies are
one look when every pose is drawn from the same pieces, the same texels
and the same colours (`print_of`), wherever the copy keeps its texels.

A sprite reference is (object set, sprite data number), the number the
definitions name. The party's sheets are numbered by object set 0: set 0
loads nothing (an entrance naming it makes no objects), so sprite data n
is then the party's own sheet n. A look's reference is its first copy, the
lowest object set and then the lowest number.

Each look is put under who wears it (`classify`):

- **Party**: a look a party field sheet draws;
- **Story people**: one an entity wears whom the who-rule gives a portrait
  of their own, one no character is (viewer_tabs.whose);
- **People**: the other entities' (object kinds 1-3);
- **Monsters**: the map monsters' (kinds 5, 6);
- **Things**: the chests' (kind 7), the triggers' (4), and those only a
  script's actors (ScriptCommandMoveChrRowActorSet (0x80061EAC)) or nothing
  found draws.

The who-rule (`talker`) is an inference. An entity talks through
MapPartyTalkCheck (0x80067D1C), which runs ScriptLabelRun (0x80059FDC) with
the definition's byte 0xB in the map's script. Of the messages that label
can show without asking anything, the entity is taken to be the speaker
whose portrait alone opens at least half (whose.speaker: a character, or a
portrait no character is). A portrait says who speaks a line, not who
stands there, so a card says it is taken to be them; and the party's own
portraits open their comments on whatever the party meets, so a character
found so names no one (`classify`).

The index (`of(model)`) is built once per disc, the first time a tab or a
link asks for it.
"""

from __future__ import annotations

import hashlib
import struct
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Iterable

from viewer_tabs import whose
from viewer_tabs.refs import Ref, ref, written

#: The object set a party field sheet's reference names (see above).
PARTY_SET = 0
#: The chest's sprite data number: MapObjectInit puts kind 7 on sprite data 0.
CHEST_NUMBER = 0
#: The headings of the Sprites tab's By who view, in order.
PARTY, STORY, PEOPLE, MONSTERS, THINGS = (
    "Party", "Story people", "People", "Monsters", "Things")
GROUPS = (PARTY, STORY, PEOPLE, MONSTERS, THINGS)
#: Each heading's note in the list.
GROUP_NOTES = {
    PARTY: "the party's field sheets",
    STORY: "people who speak with a portrait of their own, by what they say",
    PEOPLE: "everyone else the party can talk to",
    MONSTERS: "the monsters walking the maps",
    THINGS: "chests, triggers, and what only scenes draw",
}
#: The characters: the party's numbers (whose.PARTY_LAST).
PARTY_LAST = whose.PARTY_LAST
#: An entity is taken to be the speaker who opens at least this share.
SHARE = 0.5
#: The functions the who-rule follows.
TALK_CHECK = "MapPartyTalkCheck (0x80067D1C)"
LABEL_RUN = "ScriptLabelRun (0x80059FDC)"
FACE_CELL_SET = "FaceCellSet (0x8001B3DC)"
MESSAGE_FACE_SET = "MessageFaceSet (0x8005B36C)"
OBJECTS_DATA_LOAD = "MapObjectsDataLoad (0x80065418)"
OBJECT_INIT = "MapObjectInit (0x800656CC)"
RECORD_INIT = "MapRecordInit (0x80065940)"
PARTY_LOAD = "MapPartySpriteDataLoad (0x80063D48)"
PARTY_RECORD_INIT = "MapPartyRecordInit (0x800649DC)"
ACTOR_SET = "ScriptCommandMoveChrRowActorSet (0x80061EAC)"

#: The object kinds by the reference kind of an object (field_view.OBJECT_REF_KINDS).
_KIND_ORDER = ("entity", "map-monster", "chest", "trigger")


# ---------------------------------------------------------------------------
# the pure parts: what the tests hand made-up data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Talk:
    """What the who-rule found for one entity: `speaker` (a character's or
    a portrait's reference) opens `opens` of the `total` messages its label
    can show without a question."""
    speaker: Ref | None
    opens: int
    total: int


def talker(messages: Iterable, speaker_of: Callable[[int], Ref]) -> Talk:
    """The who-rule over the messages an entity's label can show
    (model.Messages.of_label): those that ask nothing (`answers` None) and
    say something; each opens with the portraits of its first run
    (`said[0].faces`, (place, portrait) pairs), and counts for the speaker
    `speaker_of` names when one portrait alone opens it. The entity is the
    speaker who opens at least half; else `speaker` is None."""
    shown = [m for m in messages if m.answers is None and m.said]
    opens: Counter = Counter()
    for m in shown:
        faces = m.said[0].faces
        if len(faces) == 1:
            opens[speaker_of(faces[0][1])] += 1
    if not opens:
        return Talk(None, 0, len(shown))
    c, n = min(opens.items(), key=lambda kv: (-kv[1], kv[0]))
    return Talk(c if n >= SHARE * len(shown) else None, n, len(shown))


def look_talk(talks: Iterable[Talk | None]) -> Talk | None:
    """A look worn by several entities is the speaker most of them are
    taken to be (the lower reference on a tie); its evidence is that
    speaker's entities' messages, summed."""
    found = [t for t in talks if t is not None and t.speaker is not None]
    if not found:
        return None
    count = Counter(t.speaker for t in found)
    c = min(count, key=lambda k: (-count[k], k))
    mine = [t for t in found if t.speaker == c]
    return Talk(c, sum(t.opens for t in mine), sum(t.total for t in mine))


def classify(party: Iterable[int], talk: Talk | None, kinds: Iterable[str]
             ) -> tuple[str, int | None]:
    """(heading, character) of a look: `party` the party ids whose field
    sheets draw it, `talk` its entities' who-rule (`look_talk`), `kinds` the
    reference kinds of the objects wearing it (twins aside). The character
    is a party member's number, else None.

    A party member is known by their field sheet alone, never by the
    who-rule: the party's portraits open their own comments on whatever
    the party meets (an animal, a boat, a crate), so a character's
    portrait opening an entity's lines does not say who stands there. A
    portrait no character is does: the entity is its speaker."""
    members = sorted(party)
    if members:
        named = [m for m in members if 1 <= m <= PARTY_LAST]
        return PARTY, (named[0] if named else None)
    if talk is not None and talk.speaker is not None and talk.speaker.kind == "portrait":
        return STORY, None
    kinds = set(kinds)
    if "entity" in kinds:
        return PEOPLE, None
    if "map-monster" in kinds:
        return MONSTERS, None
    return THINGS, None


def group_prints(prints: dict[tuple[int, int], bytes | None]) -> list[list[tuple[int, int]]]:
    """Copies with the same print, each group in reference order and the
    groups by their first; a copy with no print is a look of its own."""
    by: dict[bytes, list] = {}
    alone = []
    for unit, p in prints.items():
        (alone.append([unit]) if p is None else by.setdefault(p, []).append(unit))
    return sorted([sorted(g) for g in by.values()] + alone)


@dataclass(frozen=True)
class Piece:
    """One slice of a pose as `sprite_pages.compose_pose` draws it: its
    record's flags, size and points, and the page slot and texel corner it
    reads (`slot` None when it reads no texels: it only widens the cell)."""
    flags: int
    w: int
    h: int
    pts: tuple[int, ...]
    slot: int | None
    u: int = 0
    v: int = 0


def print_of(pose_count: int, poses: dict[int, list[Piece]], pages: dict,
             palette: bytes) -> bytes:
    """A copy's print: every pose's pieces, each with the colours of the
    texels it reads (`pages`: slot -> (lines, 256 8-bit texels a line) as
    bytes or a numpy array; `palette` the 512-byte row it is drawn with).
    Copies whose prints match draw the same pixels; where a copy keeps its
    texels does not enter it."""
    import numpy as np
    pal = np.frombuffer(bytes(palette[:512]).ljust(512, b"\0"), "<u2")
    h = hashlib.blake2b(digest_size=16)
    h.update(struct.pack("<I", pose_count))
    for k in sorted(poses):
        h.update(struct.pack("<I", k))
        for p in poses[k]:
            h.update(struct.pack(f"<i3i{len(p.pts)}i", len(p.pts), p.flags, p.w, p.h, *p.pts))
            page = pages.get(p.slot) if p.slot is not None else None
            if page is None or p.u + p.w > page.shape[1] or p.v + p.h > page.shape[0]:
                h.update(b"-")                  # compose_pose draws nothing for it
                continue
            h.update(pal[page[p.v:p.v + p.h, p.u:p.u + p.w]].tobytes())
    return h.digest()


def pieces_of(data) -> tuple[int, dict[int, list[Piece]]]:
    """(pose count, pose index -> its pieces) of a sprite data block, the
    poses and slices `sprite_pages.pose_sheet` composes."""
    from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
    out: dict[int, list[Piece]] = {}
    for pose in sp.list_poses(data):
        pieces = []
        for i in range(pose.first, pose.first + pose.count):
            s = data.slice(i)
            if s is None or not (s.w and s.h) or s.corners() is None:
                continue
            d = data.descriptor(s.desc)
            pieces.append(Piece(s.flags, s.w, s.h, tuple(s.pts), *(d if d else (None,))))
        out[pose.index] = pieces
    return data.pose_count, out


def page_arrays(pages) -> dict:
    """slot -> a page's texels as a (lines, 256) array (BattlePages)."""
    import numpy as np
    return {p.index: np.frombuffer(p.pixels, np.uint8).reshape(p.lines, 256)
            for p in pages if p.lines}


# ---------------------------------------------------------------------------
# what the index holds
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Other:
    """A record other than the set's definitions put on a sprite data
    number: a script's actor or the party."""
    row: int                # the palette row it is drawn with
    what: str               # "actor" or "party"
    who: int                # the script, or the party id
    why: str                # in words, for the Object sets view


@dataclass
class SetRecord:
    """An object set as the Sprites tab and the looks read it."""
    number: int
    resource: int
    maps: tuple[int, ...]               # the maps entered with it
    rows: tuple = ()                    # map_object_sets.SpriteDataRow
    pages: int = 0
    draws: tuple = ()                   # map_object_sets.ObjectDraw
    by_data: dict = field(default_factory=dict)  # number -> [(ObjectDraw, twin?)]
    #: number -> [Other]: the records other than the set's definitions
    #: that are put on it
    others: dict = field(default_factory=dict)
    error: str = ""

    def rows_of(self, number: int) -> list[int]:
        """The palette rows the set's definitions, the scripts' actors and
        the party draw `number` with."""
        return sorted({d.draw.palette_row for d, _t in self.by_data.get(number, [])}
                      | {o.row for o in self.others.get(number, [])})


@dataclass(frozen=True)
class Wearer:
    """An object of a set's definitions wearing a copy."""
    kind: str               # the reference kind: entity, trigger, map-monster, chest
    object_set: int
    definition: int
    twin: bool              # worn as the object's twin
    event: int              # definition byte 0xB

    @property
    def ref(self) -> Ref:
        return ref(self.kind, self.object_set, self.definition)


@dataclass
class Copy:
    """One copy of a sprite: sprite data `number` of object set
    `object_set` (PARTY_SET: the party's sheet `number`)."""
    object_set: int
    number: int
    row: int | None                     # the palette row its print is drawn with
    wearers: list[Wearer] = field(default_factory=list)
    #: (party id, sheet: "own", "party-kind-0", "twin") of a party sheet
    party: list[tuple[int, str]] = field(default_factory=list)
    others: list[Other] = field(default_factory=list)
    print: bytes | None = None

    @property
    def unit(self) -> tuple[int, int]:
        return self.object_set, self.number

    @property
    def ref(self) -> Ref:
        return ref("sprite", self.object_set, self.number)

    @property
    def drawn(self) -> bool:
        return bool(self.wearers or self.party or self.others)


@dataclass
class Look:
    """Copies that draw the same pixels, and who wears them."""
    copies: list[Copy]
    group: str = THINGS
    #: the party member whose field sheet draws it
    character: int | None = None
    #: the who-rule's evidence, for a person taken to be a portrait's speaker
    talk: Talk | None = None
    title: str = ""
    subtitle: str = ""
    maps: list[int] = field(default_factory=list)

    @property
    def first(self) -> Copy:
        return self.copies[0]

    @property
    def ref(self) -> Ref:
        return self.first.ref

    @property
    def refs(self) -> list[Ref]:
        return [c.ref for c in self.copies]

    @property
    def wearers(self) -> list[Wearer]:
        return [w for c in self.copies for w in c.wearers]

    @property
    def party(self) -> list[tuple[int, str]]:
        return [p for c in self.copies for p in c.party]

    @property
    def inferred(self) -> bool:
        return self.talk is not None


# ---------------------------------------------------------------------------
# the index of one disc
# ---------------------------------------------------------------------------

#: (a resource's digest, sprite data number, the palette's digest) -> its
#: print, for every disc open: a game's discs share most of their object
#: sets byte for byte, so the second disc reads only what the first did not.
_PRINTS: dict[tuple, bytes | None] = {}


def _digest(data: bytes) -> bytes:
    return hashlib.blake2b(data, digest_size=16).digest()


class Looks:
    """Every object set's sprites and the party's, grouped into looks."""

    def __init__(self, model):
        import time
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pfs
        from viewer_tabs.links import world
        started = time.perf_counter()
        self.model = model
        self.w = w = world._world(model)
        self.fm = fm = w.fm
        self.names = w.names
        img = fm.image
        self.twins = mos.twin_numbers(img)
        self.party_twins = pfs.twin_numbers(img)
        self.party_ids = list(range(1, len(self.party_twins) + 1)) + [pfs.ID_CE]
        #: map -> its party kind (records.areas byte 0)
        self.party_kind = {mid: m.area.party_kind for mid, m in fm.maps.items()}
        self._map_palettes: dict[int, bytes | None] = {}
        #: what could not be read, a sentence each
        self.errors: list[str] = []
        on_map, spawns, kinds = self._scripts()
        self.sets: dict[int, SetRecord] = {}
        #: (object set, number) -> its copy, the party's sheets not yet among them
        self._copies: dict[tuple[int, int], Copy] = {}
        #: copy -> the key of its print in _PRINTS; None when no palette draws it
        self._keys: dict[tuple[int, int], tuple | None] = {}
        #: the chests' copies, one a set: each set's chests draw the same
        self._chests: set[tuple[int, int]] = set()
        for s, res in sorted(fm.set_resources.items()):
            self._read_set(s, res, on_map, spawns, kinds)
        self._grouped: tuple[list[Look], dict] | None = None
        self._talks: dict[tuple[int, int], Talk | None] = {}
        #: seconds the sets took to read; the looks take more (Looks.looks)
        self.seconds = time.perf_counter() - started

    # -- the looks ----------------------------------------------------------

    @property
    def looks(self) -> list[Look]:
        """Every look, by group, then as each group orders them."""
        return self._group()[0]

    @property
    def look_of(self) -> dict[tuple[int, int], Look]:
        """(object set, number) -> its look."""
        return self._group()[1]

    def _group(self) -> tuple[list[Look], dict]:
        """The looks, made the first time they are asked for: every copy's
        print (which inflates every set's pages), the copies grouped by
        print and each look's who-rule. The sets alone need none of it."""
        got = self._grouped
        if got is None:
            with self.model.lock:
                got = self._grouped
                if got is None:
                    got = self._grouped = self._make_looks()
        return got

    def _make_looks(self) -> tuple[list[Look], dict]:
        prints: dict[tuple[int, int], bytes | None] = {}
        need: dict[int, list[int]] = {}
        for unit, c in self._copies.items():
            key = self._keys.get(unit)
            if unit in self._chests:
                prints[unit] = b"chest"         # every chest is resource 2's, whatever the set
                continue
            prints[unit] = _PRINTS.get(key) if key is not None else None
            if key is not None and key not in _PRINTS:
                need.setdefault(unit[0], []).append(unit[1])
        for s, numbers in sorted(need.items()):
            self._print_set(s, numbers, prints)
        copies = dict(self._copies)
        self._read_party(copies, prints)
        looks: list[Look] = []
        look_of: dict[tuple[int, int], Look] = {}
        for units in group_prints(prints):
            look = Look([copies[u] for u in units])
            looks.append(look)
            for u in units:
                look_of[u] = look
        for look in looks:
            self._who(look)
        looks.sort(key=lambda lk: (GROUPS.index(lk.group), self._order(lk)))
        return looks, look_of

    # -- reads --------------------------------------------------------------

    def _scripts(self):
        """(map -> the scripts that can run on it, script -> its actor
        spawns, script -> the party kinds its commands 0x48 set), every
        script read once (FieldMaps.script)."""
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        fm = self.fm
        switches, spawns, kinds = {}, {}, {}
        for sid in sorted(fm.script_resources):
            try:
                buf, commands, _labels = fm.script(sid)
            except Exception:
                continue                        # FieldMaps.errors says why
            cmds = list(commands.values())
            switches[sid] = es.script_switches(buf, cmds)
            spawns[sid] = es.actor_spawns(buf, cmds)
            kinds[sid] = es.party_kinds_set(buf, cmds)
        entered = {mid: m.area.script for mid, m in fm.maps.items()}
        return es.map_scripts(entered, switches), spawns, kinds

    def map_palette(self, mid: int) -> bytes | None:
        """Row 506 on map `mid`: the map's own palette (map_object_sets.map_palette)."""
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        if mid not in self._map_palettes:
            try:
                self._map_palettes[mid] = mos.map_palette(self.fm.read(self.fm.maps[mid].resource))
            except Exception:
                self._map_palettes[mid] = None
        return self._map_palettes[mid]

    def palette(self, row: int | None, s: int) -> bytes | None:
        """The 512 bytes of palette row `row` as object set `s` is drawn:
        504 and 505 the sprite_init rows, 506 the set's first map's own."""
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        if row in self.fm.row_palettes:
            return self.fm.row_palettes[row]
        if row == mos.ROW_MAP:
            home = self.w.home_map(s)
            return self.map_palette(home) if home is not None else None
        return None

    def _read_set(self, s, res, on_map, spawns, kinds):
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        from viewer_tabs.field_view import OBJECT_REF_KINDS
        maps = tuple(self.w.set_maps.get(s, ()))
        try:
            raw = self.fm.read(res)
            header, rows = mos.set_header(raw), tuple(mos.sprite_data_rows(raw))
            draws = mos.object_draws(mos.definition_block(raw), self.twins)
        except Exception as ex:
            self.sets[s] = SetRecord(s, res, maps, error=str(ex))
            self.errors.append(f"object set {s}: {ex}")
            return
        by_data = mos.sprite_data_draws(draws)
        rec = SetRecord(s, res, maps, rows, len(header.pages), tuple(draws), by_data,
                        self._others(maps, rows, on_map, spawns, kinds))
        self.sets[s] = rec
        events = {d.index: d.event for d in self.w.definitions(s).values()}
        # MapObjectsDataLoad: the first row of a number loads, below 0x100
        numbers = list(dict.fromkeys(r.number for r in rows if r.number < mos.SPRITE_DATA_LIMIT))
        digest = _digest(raw)
        for n in numbers:
            c = Copy(s, n, None, others=list(rec.others.get(n, [])))
            for d, twin in by_data.get(n, []):
                kind = OBJECT_REF_KINDS.get(d.kind)
                if kind:
                    c.wearers.append(Wearer(kind, s, d.definition, twin,
                                            events.get(d.definition, 0)))
            # its print is drawn with the row its own objects take, else
            # their twins', else the scenes' actors' or the party's
            uses = by_data.get(n, [])
            c.row = min({d.draw.palette_row for d, twin in uses if not twin}
                        or {d.draw.palette_row for d, _t in uses}
                        or {o.row for o in rec.others.get(n, [])} or {mos.ROW_KIND_1})
            self._copies[c.unit] = c
            pal = self.palette(c.row, s)
            self._keys[c.unit] = (digest, n, _digest(pal)) if pal is not None else None
        chests = [d for d in draws if d.kind == mos.CHEST_KIND]
        if chests:
            c = Copy(s, CHEST_NUMBER, mos.ROW_CHEST)
            c.wearers = [Wearer("chest", s, d.definition, False, events.get(d.definition, 0))
                         for d in chests]
            self._copies[c.unit] = c
            self._chests.add(c.unit)

    def _print_set(self, s: int, numbers: list[int], prints: dict):
        """The prints of set `s`'s sprites `numbers`, drawn from its pages."""
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        try:
            obj = mos.parse_object_set(self.fm.read(self.sets[s].resource))
            pages = page_arrays(obj.pages)
        except Exception as ex:
            self.errors.append(f"object set {s}'s sprites: {ex}")
            return
        for n in numbers:
            try:
                actor = obj.actor(n)
                got = (print_of(*pieces_of(actor), pages, self.palette(self._copies[(s, n)].row, s))
                       if actor is not None else None)
            except Exception as ex:
                self.errors.append(f"object set {s} sprite {n}: {ex}")
                continue
            _PRINTS[self._keys[(s, n)]] = prints[(s, n)] = got

    def _others(self, maps, rows, on_map, spawns, kinds) -> dict[int, list[Other]]:
        """number -> the records other than the set's definitions put on
        the set's sprite data: the actors the scripts that can run on the
        set's maps make (ScriptCommandMoveChrRowActorSet (0x80061EAC)), and
        the party (MapPartyRecordInit (0x800649DC))."""
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pfs
        numbers = {r.number for r in rows}
        out: dict[int, list[Other]] = {}
        seen: dict[tuple, int] = {}
        for sid in sorted({s for m in maps for s in on_map.get(m, ())}):
            for sp in spawns.get(sid, ()):
                made = [(sp.sprite_data, False)]
                if sp.sprite_data < mos.TWIN_BELOW:
                    made.append((self.twins[sp.sprite_data - 1], True))
                for number, twin in made:
                    if number in numbers:
                        key = (number, sid, sp.kind, sp.mode, twin)
                        seen[key] = seen.get(key, 0) + 1
        for (number, sid, kind, mode, twin), count in sorted(seen.items()):
            row = mos.record_draw(kind, mode).palette_row
            out.setdefault(number, []).append(Other(row, "actor", sid, (
                f"script {sid}: {count} command{'s' if count != 1 else ''} 0x34 "
                f"({ACTOR_SET}) make an actor of kind {kind}, mode {mode}"
                f"{' and its twin on this number' if twin else ''}: row {row}")))
        can = {self.party_kind.get(m) for m in maps}
        can |= {k for m in maps for s in on_map.get(m, ()) for k in kinds.get(s, ())}
        can.discard(None)
        party = pfs.party_uses(self.party_twins, self.party_ids)
        for number in sorted(numbers):
            for use in party.get(number, ()):
                row = mos.record_draw(use.kind, 0).palette_row
                zero = use.which == "party-kind-0"
                worn = (0 in can) if zero else bool(can - {0})
                when = ("while g_MapPartyKind (0x800B8CEE) is 0" if zero
                        else "while g_MapPartyKind (0x800B8CEE) is not 0")
                kinds_text = ", ".join(map(str, sorted(can))) or "none read"
                out.setdefault(number, []).append(Other(row, "party", use.member, (
                    f"{self.sheet_word(use.member)}'s {SHEET_TITLES[use.which]} (character "
                    f"{use.member}): {PARTY_RECORD_INIT} gives it kind {use.kind}, "
                    f"row {row}, worn {when}; on this set's maps the party kind can be "
                    f"{kinds_text}" + ("" if worn else ", so there it is not worn"))))
        return out

    def _read_party(self, copies, prints):
        """The party's field sheets as copies of object set 0."""
        from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pfs
        for m in self.party_ids:
            try:
                ms = pfs.member_sheets(self.fm.party_buf, m, self.party_twins)
            except Exception as ex:
                self.errors.append(f"the party's sheet {m}: {ex}")
                continue
            for which, sheet, row in (("own", ms.own, ms.palette_row),
                                      ("party-kind-0", ms.kind_0, ms.palette_row),
                                      ("twin", ms.twin, ms.twin_palette_row)):
                if sheet is None:
                    continue
                unit = (PARTY_SET, sheet.number)
                c = copies.get(unit)
                if c is None:
                    c = copies[unit] = Copy(PARTY_SET, sheet.number, row)
                    pal = self.fm.row_palettes[row]
                    key = (_digest(sheet.block + sheet.picture.pixels), sheet.number, _digest(pal))
                    if key not in _PRINTS:
                        try:
                            actor = sheet.actor()
                            _PRINTS[key] = (print_of(*pieces_of(actor), page_arrays([sheet.picture]),
                                                     pal) if actor is not None else None)
                        except Exception as ex:
                            self.errors.append(f"the party's sheet {sheet.number}: {ex}")
                    prints[unit] = _PRINTS.get(key)
                c.party.append((m, which))

    # -- who ----------------------------------------------------------------

    def talk(self, w: Wearer) -> Talk | None:
        """The who-rule for one entity: every script that can be the map's
        when its set is entered (each map's own, once), its label byte 0xB."""
        key = (w.object_set, w.definition)
        if key not in self._talks:
            got = None
            if w.event:
                msgs = self.model.messages
                scripts = dict.fromkeys(self.fm.maps[m].area.script
                                        for m in self.w.set_maps.get(w.object_set, ()))
                shown, seen = [], set()
                for sid in scripts:
                    for m in msgs.of_label(sid, w.event):
                        if (sid, m.offset) not in seen:
                            seen.add((sid, m.offset))
                            shown.append(m)
                got = talker(shown, lambda f: whose.speaker(self.model, f)) if shown else None
            self._talks[key] = got
        return self._talks[key]

    def _who(self, look: Look):
        own = [w for w in look.wearers if not w.twin]
        entities = [w for w in own if w.kind == "entity"]
        talk = None
        if not look.party and entities:
            try:
                talk = look_talk(self.talk(w) for w in entities)
            except Exception as ex:
                self.errors.append(f"the who-rule for {look.ref}: {ex}")
        look.group, look.character = classify([m for m, _w in look.party], talk,
                                              [w.kind for w in own])
        look.talk = talk if look.group == STORY else None
        maps: dict[int, None] = {}
        for c in look.copies:
            if c.object_set != PARTY_SET and c.drawn:
                maps.update(dict.fromkeys(self.sets[c.object_set].maps))
        look.maps = list(maps)
        look.title, look.subtitle = self._titles(look)

    def character_word(self, c: int) -> str:
        """Character c by name, else "character n"."""
        name = self.names.character(c) if 1 <= c <= PARTY_LAST else None
        return name or f"character {c}"

    def sheet_word(self, m: int) -> str:
        """Whose a party sheet is: the character's name, else "party sheet m"."""
        return self.character_word(m) if 1 <= m <= PARTY_LAST else f"party sheet {m}"

    @staticmethod
    def speaker_title(speaker: Ref) -> str:
        """One of the story people, by the portrait they speak with: "the one in portrait 91"."""
        return f"the one in portrait {speaker.id[0]}"

    def _titles(self, look: Look) -> tuple[str, str]:
        """(title, subtitle): who wears it, then where."""
        from viewer_tabs import links
        w = self.w
        places = list(dict.fromkeys(w.map_title(m) for m in look.maps))
        more = (f" and {len(places) - 1} more place{'s' if len(places) != 2 else ''}"
                if len(places) > 1 else "")
        where = (places[0] + more) if places else ""
        if look.group == STORY:
            title = self.speaker_title(look.talk.speaker)
            return title, f"taken from what they say · {where}" if where else \
                "taken from what they say"
        if look.group == PARTY:
            sheets = {which for _m, which in look.party}
            if sheets == {"twin"}:
                members = sorted({m for m, _w in look.party})
                title = _and([self.character_word(m) for m in members]) + "'s shadow"
            elif look.character is None:
                title = f"party sheet {look.party[0][0]}"
            else:
                title = self.character_word(look.character)
                if sheets and "own" not in sheets:
                    title += " (overworld)"
            return title, where or "the party's field sheet"
        own = [x for x in look.wearers if not x.twin]
        kinds = {PEOPLE: ("entity",), MONSTERS: ("map-monster",),
                 THINGS: ("chest", "trigger")}[look.group]
        first = next((x for k in kinds for x in own if x.kind == k), None)
        if look.group == MONSTERS:
            battle = next((x.event for x in own if x.kind == "map-monster" and x.event), None)
            if battle:
                title = links.title_of(self.model, ref("battle", battle))
                return title, where
        if first is not None:
            title = links.title_of(self.model, first.ref)
            return title, (places[0] if len(places) == 1 and title.startswith(places[0])
                           and not more else where)
        c = look.first
        place = w.object_place(c.object_set)
        title = f"{place} · sprite {c.number}" if place else f"sprite {c.object_set}/{c.number}"
        what = ("made by scenes" if any(o.what == "actor" for o in c.others)
                else "a twin" if look.wearers else "nothing found draws it")
        return title, f"{what} · {where}" if where else what

    def _order(self, look: Look):
        if look.group == PARTY:
            return (look.character or 999, look.title, look.ref.id)
        if look.group == STORY:
            return (look.talk.speaker.id, look.title, look.ref.id)
        return (look.title, look.ref.id)

    # -- in words -------------------------------------------------------------

    def who_words(self, look: Look) -> str:
        """Who wears a look, in a sentence's words."""
        if look.party:
            by: dict[str, list[int]] = {}
            for m, which in look.party:
                by.setdefault(which, []).append(m)
            return "; ".join(_and([self.sheet_word(m) for m in members]) + "'s "
                             + SHEET_TITLES[which] for which, members in by.items())
        if look.talk is not None:
            t = look.talk
            return (f"taken to be {self.speaker_title(t.speaker)}: that portrait opens "
                    f"{t.opens} of the {t.total} message{'s' if t.total != 1 else ''} "
                    f"they can say")
        own = [w for w in look.wearers if not w.twin]
        count = Counter(w.kind for w in own)
        if count:
            return ", ".join(f"{n} {KINDS_WORDS[k][n != 1]}" for k, n in
                             sorted(count.items(), key=lambda kv: _KIND_ORDER.index(kv[0])))
        if look.wearers:
            return "the twin drawn beside " + _and(sorted({written(w.ref) for w in look.wearers}))
        if any(o.what == "actor" for c in look.copies for o in c.others):
            return "actors the scenes make"
        if any(c.others for c in look.copies):
            return "the party"
        return "nothing found draws it"

    def copies_words(self, look: Look) -> str:
        """"3 copies: the party's field sheet and 2 object sets"."""
        sets = len({c.object_set for c in look.copies if c.object_set != PARTY_SET})
        party = any(c.object_set == PARTY_SET for c in look.copies)
        where = [w for w in ("the party's field sheets" if party else "",
                             f"{sets} object set{'s' if sets != 1 else ''}" if sets else "") if w]
        return f"{len(look.copies)} copies, the same pixels: in {_and(where)}"

    def worn_words(self, c: Copy) -> str:
        """What wears one copy: its objects, the scenes' actors, the party."""
        parts = [written(w.ref) + (" (as its twin)" if w.twin else "") for w in c.wearers[:4]]
        if len(c.wearers) > 4:
            parts.append(f"{len(c.wearers) - 4} more")
        if any(o.what == "actor" for o in c.others):
            parts.append("actors in scenes")
        if any(o.what == "party" for o in c.others):
            parts.append("the party")
        parts += [f"{self.sheet_word(m)}'s {SHEET_TITLES[which]}" for m, which in c.party]
        return ", ".join(parts) or "nothing found draws it"

    def rule_words(self, look: Look) -> str:
        """The who-rule behind a look taken to be someone, in plain words."""
        t = look.talk
        if t is None:
            return ""
        p = t.speaker.id[0]
        return (f"Taken to be {self.speaker_title(t.speaker)}: that portrait opens most of "
                f"what they say. {TALK_CHECK} runs {LABEL_RUN} with the entity's definition "
                f"byte 0xB in the map's script; of the {t.total} "
                f"message{'s' if t.total != 1 else ''} that can show without asking "
                f"anything, {t.opens} open with portrait {p} alone ({MESSAGE_FACE_SET}). "
                f"No character's file holds portrait {p} and no character's portrait is "
                f"drawn like it ({FACE_CELL_SET}, viewer_tabs.whose), so the game names no "
                f"one for it. An entity is taken to be the speaker who opens at least half; "
                f"a portrait says who speaks, not who stands there.")

    # -- pictures -------------------------------------------------------------

    def drawn(self, c: Copy):
        """(sprite data block, {page slot: page under the copy's row}) of a
        copy, or None when it cannot be drawn."""
        from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
        from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pfs
        from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
        from decoders.plugins.SLUS_006_28.formats import stfield as sf
        if c.object_set == PARTY_SET:
            sheet = pfs.load_sheet(self.fm.party_buf, c.number)
            return sheet.actor(), {0: bg.render_page(sheet.picture, self.fm.row_palettes[c.row])}
        if c.number == CHEST_NUMBER:
            st = self.fm.stfield
            return sp.parse_actor_block(st.banks[1]), {sf.PAGE: sf.sheet_image(st, 7)}
        pal = self.palette(c.row, c.object_set)
        if pal is None:
            return None
        obj = self._parsed(c.object_set)
        return obj.actor(c.number), {p.index: bg.render_page(p, pal) for p in obj.pages if p.lines}

    def _parsed(self, s: int):
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        keep = self.__dict__.setdefault("_kept", {})
        if s not in keep:
            while len(keep) >= KEEP_PARSED:
                keep.pop(next(iter(keep)))
            keep[s] = mos.parse_object_set(self.fm.read(self.sets[s].resource))
        return keep[s]

    def picture(self, c: Copy):
        """A copy's first pose (the first animation's first step, else its
        lowest pose), cut to what it draws; None when it draws nothing."""
        from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
        with self.model.lock:
            got = self.drawn(c)
        if got is None or got[0] is None:
            return None
        actor, pages = got
        poses = {p.index: p for p in sp.list_poses(actor)}
        first = next((a.steps[0][0] for a in actor.animations() if a.steps), None)
        pose = poses.get(first) if first is not None else None
        if pose is None and poses:
            pose = poses[min(poses)]
        extent = sp.pose_extent(actor, pose) if pose is not None else None
        if extent is None:
            return None
        x0, y0, x1, y1 = extent
        image = sp.compose_pose(actor, pages, pose, origin=(-x0, -y0), size=(x1 - x0, y1 - y0))
        box = image.getchannel("A").getbbox()
        return image.crop(box) if box else None

    # -- look-ups -----------------------------------------------------------

    def look(self, r: Ref) -> Look | None:
        """The look a sprite reference is a copy of."""
        return self.look_of.get(tuple(r.id)) if r.kind == "sprite" and len(r.id) == 2 else None

    def copy(self, r: Ref) -> Copy | None:
        look = self.look(r)
        return next((c for c in look.copies if c.unit == tuple(r.id)), None) if look else None


def _and(words: list[str]) -> str:
    """"A", "A and B", "A, B and C", each word once."""
    words = list(dict.fromkeys(words))
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


#: What each party sheet is, in words.
SHEET_TITLES = {"own": "field sheet", "party-kind-0": "overworld sheet", "twin": "shadow"}
#: An object kind in words, one and many.
KINDS_WORDS = {"entity": ("entity", "entities"), "map-monster": ("map monster", "map monsters"),
               "chest": ("chest", "chests"), "trigger": ("trigger", "triggers")}
#: Object sets `Looks.drawn` keeps parsed.
KEEP_PARSED = 4


def of(model) -> Looks:
    """The disc's looks, read the first time they are asked for."""
    return model.kept("_looks", Looks)

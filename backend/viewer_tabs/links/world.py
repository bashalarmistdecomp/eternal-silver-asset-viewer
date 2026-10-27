"""The world: the maps, their places and scripts, the ways from one map
to another, the tile changes, the objects an object set puts on a map,
and the story flags they answer to.

What the code makes of each (docs/taxonomy.md, "The links"):

- a map shows its map record's place (byte 6, MapSet (0x80068780)) and
  loads its script (byte 8, MapLoad (0x80068A10) -> ScriptChange);
- an entrance is row r of a map's enter table, the one the map's command 9
  fills: MapChange (0x8005922C) takes the party from that map to the
  row's map, with the row's object set and sound;
- a tile change is a row of the map's bg change table: MapBgChangeStart
  (0x80059900) sets its story flag as it starts, and
  MapBgChangeStoryBitsCopy (0x80059B6C) copies it in on every load while
  the flag is set (the flag's card has it under Set by and Checked by, as
  every flag's links are grouped: viewer_tabs.links.flags);
- an object is a definition of the object set the map is entered with
  (MapObjectsInit (0x800655C8)): an entity (kinds 1-3), a trigger (4), a
  map monster (5, 6) or a chest (7), each numbered by the object set and
  the definition. A map monster starts the battle its byte 0xB numbers
  (MapObjectTouchRun (0x8007ACD8)); a chest gives an item, money or a
  label of the map's script (MapObjectKind7Run (0x80067F84));
- a script hands over to another (commands 0x42, 0x5D) and takes the
  party to other maps (0x26, 0x5D).

The domain's reads are kept per disc (`_world`), so a link's title costs
a dictionary look-up.
"""

from __future__ import annotations

from collections import Counter

from viewer_tabs import links
from viewer_tabs.field_view import DEBUG_ROOM, MAP_TYPES, OBJECT_REF_KINDS
from viewer_tabs.links import CardBody, Edge
from viewer_tabs.refs import KINDS, ref, written

MAP_CHANGE = "MapChange (0x8005922C)"
MAP_SET = "MapSet (0x80068780)"
MAP_LOAD = "MapLoad (0x80068A10)"
MAP_TBL_GET = "MapTblGet (0x80068618)"
MAP_SEEK = "MapSeek (0x8006891C)"
ENTER_TABLE = "resource_map_enter_table_set (0x80020B8C)"
OBJECTS_DATA_LOAD = "MapObjectsDataLoad (0x80065418)"
OBJECTS_INIT = "MapObjectsInit (0x800655C8)"
OBJECT_INIT = "MapObjectInit (0x800656CC)"
KIND7_RUN = "MapObjectKind7Run (0x80067F84)"
TOUCH_RUN = "MapObjectTouchRun (0x8007ACD8)"
TOUCH_REMOVE = "MapObjectTouchRemove (0x8007B5CC)"
TALK_CHECK = "MapPartyTalkCheck (0x80067D1C)"
THINK = "MapObjectsThink (0x8006736C)"
BG_START = "MapBgChangeStart (0x80059900)"
BG_STEP = "MapBgChangeStep (0x80059A18)"
BG_COPY = "MapBgChangeStoryBitsCopy (0x80059B6C)"
ATTRIBUTE_RUN = "MapAttributeRun (0x800590C0)"
SCRIPT_MAP_CHANGE = "ScriptCommandMapChange (0x8005DB3C)"
SCRIPT_MAP_SCRIPT_CHANGE = "ScriptCommandMapScriptChange (0x8005F068)"
SCRIPT_SCRIPT_CHANGE = "ScriptCommandScriptChange (0x8005BFCC)"
SCRIPT_BG_CHANGE = "ScriptCommandMapBgChangeStart (0x8005DD84)"
SCRIPT_LOAD = "ScriptResourceLoad (0x80020D20)"
LABEL_RUN = "ScriptLabelRun (0x80059FDC)"
PLACE_STRING = "MenuCardListDisp (0x800734F0)"

#: How the party walks a map, by its record's party kind (byte 0):
#: MapPartyRecordInit (0x800649DC) puts kind 0's members on their small
#: sheets, MapPartyRingFollow (0x800671C4) walks the rest behind the lead,
#: and MapPartyRecordsInit (0x80064898) switches members 1-5 off for kind 2.
WALKS = {0: "the whole party, drawn small", 1: "the whole party, in a line behind the leader",
         2: "the leader alone"}
#: The eight facings, as MapBoxTouchGet (0x80067BFC) numbers the sides of
#: a box: 1 above, 3 right, 5 below, 7 left, the corners between.
FACINGS = {1: "up", 2: "up and right", 3: "right", 4: "down and right", 5: "down",
           6: "down and left", 7: "left", 8: "up and left"}
#: What an object does on its own, by its think number (definition byte
#: 0xC, with bit 0x40 of byte 0): the entry of MapObjectsThink's table it
#: calls, which passes over numbers 3 and 4.
BEHAVIOURS = {
    0: ("walks about", "MapObjectWanderStep (0x8006758C)"),
    1: ("walks a set path", "StepCommandRun (0x80067768)"),
    2: ("walks a set path", "StepCommandRun (0x80067768)"),
    3: ("stands still", THINK),
    4: ("stands still", THINK),
    5: ("stands and turns about now and then", "MapObjectTurnStep (0x800678F4)"),
    6: ("keeps a look out for the party", "MapObjectPartyLookStep (0x80077F1C)"),
    7: ("has seen the party", "MapObjectPartySeenStep (0x80077FAC)"),
    8: ("keeps away from the party", "MapObjectPartyAwayStep (0x80078060)"),
}
#: What each object kind is (docs/taxonomy.md, "On the maps").
WHAT = {"entity": "someone or something the party can talk to",
        "trigger": "something that runs when the party touches it",
        "map-monster": "a monster walking the map; touching it starts a battle",
        "chest": "a chest"}
OBJECT_KINDS = ("entity", "trigger", "map-monster", "chest")
#: MapSet (0x80068780): entering a map whose place is 0x51..0x64 sets
#: story flag place + 0x28A.
VISITED_FIRST, VISITED_END, VISITED_FLAG = 0x51, 0x65, 0x28A
#: MapSet: party kind 0 with song 6 plays song 7 once this flag is set.
SONG_SIX, SONG_SEVEN, SONG_SEVEN_FLAG = 6, 7, 0x3C1
#: Places named in a sentence before "and n more".
NAMED = 3


def _a(name: str) -> str:
    """"an entity", "a chest": a kind's name with its article."""
    return f"{'an' if name[:1] in 'aeiou' else 'a'} {name}"


def _plural(kind: str) -> str:
    """"Map monsters": a kind's plural as a heading."""
    p = KINDS[kind].plural
    return p[:1].upper() + p[1:]


# ---------------------------------------------------------------------------
# what the domain reads, once per disc
# ---------------------------------------------------------------------------

class _World:
    def __init__(self, model):
        self.fm = fm = model.field
        self.names = model.need_names()
        #: map -> the object set the Maps tab shows it with
        self.shown: dict[int, int] = {}
        #: object set -> the maps entered with it, by number
        self.set_maps: dict[int, list[int]] = {}
        self.place_maps: dict[int, list[int]] = {}
        for mid in sorted(fm.maps):
            chosen, by = fm.set_for(mid)
            self.shown[mid] = chosen
            for s in sorted(by):
                if s:
                    self.set_maps.setdefault(s, []).append(mid)
            self.place_maps.setdefault(fm.maps[mid].area.location, []).append(mid)
        self._rows: dict[int, list] = {}
        self._changes: dict[int, list] = {}
        self._cells: dict[int, Counter] = {}
        self._defs: dict[int, dict] = {}
        self._titles: dict = {}
        self._amounts = None
        #: the object sets field_view.object_picture placed last
        self.placed: dict = {}

    # -- names --------------------------------------------------------------

    def place(self, mid: int) -> str | None:
        m = self.fm.maps.get(mid)
        return self.names.location(m.area.location) if m else None

    def map_title(self, mid: int) -> str:
        return self.place(mid) or written(ref("map", mid))

    def places(self, maps) -> str:
        """"A, B, C and 2 more": the maps' places, each once, the debug
        room's last."""
        shown = list(dict.fromkeys(self.map_title(m)
                                   for m in sorted(maps, key=lambda m: m == DEBUG_ROOM)))
        more = len(shown) - NAMED
        return ", ".join(shown[:NAMED]) + (f" and {more} more" if more > 0 else "")

    def home_map(self, s: int) -> int | None:
        """The first map the Maps tab shows with object set `s`, else the
        first map entered with it."""
        maps = self.set_maps.get(s, [])
        return next((m for m in maps if self.shown.get(m) == s), maps[0] if maps else None)

    def object_place(self, s: int) -> str | None:
        home = self.home_map(s)
        return self.place(home) if home is not None else None

    def script_title(self, sid: int) -> str | None:
        key = ("script", sid)
        if key not in self._titles:
            maps = sorted(self.fm.script_maps.get(sid, ()))
            self._titles[key] = self.places(maps) if maps else None
        return self._titles[key]

    # -- reads --------------------------------------------------------------

    def rows(self, mid: int) -> list:
        """The map's enter rows: (row, field_objects.MapEntry)."""
        from decoders.plugins.SLUS_006_28.formats import field_objects as fo
        if mid not in self._rows:
            self._rows[mid] = fo.table_rows(self.fm.read(self.fm.maps[mid].resource), mid)
        return self._rows[mid]

    def changes(self, mid: int) -> list:
        """The map's tile changes (formats.bg_change)."""
        from decoders.plugins.SLUS_006_28.formats import bg_change as bc
        if mid not in self._changes:
            self._changes[mid] = bc.map_changes(self.fm.read(self.fm.maps[mid].resource))
        return self._changes[mid]

    def cells(self, mid: int) -> Counter:
        """(event kind, argument) -> how many attribute cells of the map
        carry it (MapAttributeFind (0x80069A20): cell & 0x7FF, the kind in
        bits 7 up), on the plane as it loads or, where more, with every
        tile change copied in."""
        import numpy as np
        from decoders.plugins.SLUS_006_28.formats import bg_change as bc
        from decoders.plugins.SLUS_006_28.formats import world_map as wm
        if mid not in self._cells:
            raw = self.fm.read(self.fm.maps[mid].resource)
            base = wm.attribute_plane(wm.attributes(raw))
            planes = [base]
            rows = self.changes(mid)
            if rows:
                changed = [list(r) for r in base]
                for r in rows:
                    sx, sy = r.sources[-1]
                    bc.copy(changed, r.x, r.y, sx, sy, r.w, r.h)
                planes.append(changed)
            out: Counter = Counter()
            for plane in planes:
                ev = np.array(plane, dtype=np.int32) & bc.EVENT_MASK
                keys, counts = np.unique(ev[(ev & bc.EVENT_ARG) != 0], return_counts=True)
                for k, n in zip(keys.tolist(), counts.tolist()):
                    key = (k >> bc.EVENT_KIND_SHIFT, k & bc.EVENT_ARG)
                    out[key] = max(out[key], n)
            self._cells[mid] = out
        return self._cells[mid]

    def definitions(self, s: int) -> dict:
        """Object set `s`'s made definitions by number (MapObjectsInit's
        walk: byte 1 not 0); empty for a set naming no resource."""
        from decoders.plugins.SLUS_006_28.formats import field_objects as fo
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        if s not in self._defs:
            res = self.fm.set_resources.get(s)
            block = mos.definition_block(self.fm.read(res)) if res else None
            self._defs[s] = ({d.index: d for d in fo.made_definitions(block)}
                             if block is not None else {})
        return self._defs[s]

    def amounts(self):
        """g_MapObjectKind7Amounts, or the reason it cannot be read."""
        from decoders.plugins.SLUS_006_28.formats import field_objects as fo
        if self._amounts is None:
            try:
                self._amounts = fo.chest_amounts(self.fm.image)
            except (LookupError, ValueError) as ex:
                self._amounts = str(ex)
        return self._amounts

    def script_labels(self, sid: int) -> dict:
        try:
            return self.fm.script(sid)[2]
        except Exception:
            return {}


def _world(model) -> _World:
    return model.kept("_world", _World)


def home_map(model, object_set: int) -> int | None:
    """The map an object of `object_set` is shown on (its home)."""
    return _world(model).home_map(object_set)


def _the_map(w: _World, mid: int):
    m = w.fm.maps.get(mid)
    if m is None:
        raise LookupError(f"no map {mid} in the game's map table (g_MapResourcePairs)")
    return m


def _object(w: _World, r):
    """The definition an entity / trigger / map monster / chest ref names."""
    s, i = r.id
    if s not in w.fm.set_resources:
        raise LookupError(f"no object set {s} (g_MapObjectsDataResourceNumbers names none)")
    d = w.definitions(s).get(i)
    if d is None:
        raise LookupError(f"object set {s} makes nothing of definition {i}")
    what = OBJECT_REF_KINDS.get(d.kind)
    if what != r.kind:
        raise LookupError(f"definition {i} of object set {s} is "
                          f"{_a(KINDS[what].name) if what else f'of object kind {d.kind}'}, "
                          f"not {_a(KINDS[r.kind].name)}")
    return d


# ---------------------------------------------------------------------------
# the edges
# ---------------------------------------------------------------------------

@links.edges(kept=True)
def world_edges(model):
    """Every map's place, script, object sets, ways out and tile changes;
    each place's visited flag; each script's hand-overs and map changes;
    each object set's objects, the maps they stand on and what they
    answer to."""
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    from decoders.plugins.SLUS_006_28.formats import field_objects as fo
    w = _world(model)
    fm = w.fm
    for mid, m in sorted(fm.maps.items()):
        here = ref("map", mid)
        a = m.area
        yield Edge(here, ref("place", a.location), "Place", "Maps", "the place name it shows",
                   MAP_SET)
        if a.script in fm.script_resources:
            yield Edge(here, ref("script", a.script), "Script", "Run on maps",
                       "the script it loads", MAP_LOAD)
        chosen, by = fm.set_for(mid)
        for s, named in sorted(by.items()):
            if s:
                yield Edge(here, ref("object-set", s), "Object set", "Maps",
                           "shown on the map" if s == chosen
                           else f"on {len(named)} way{'s' if len(named) != 1 else ''} in",
                           MAP_CHANGE)
        for row, e in w.rows(mid):
            way = ref("entrance", mid, row)
            to = ref("map", e.map)
            yield Edge(here, way, "Ways out", "From", f"to {w.map_title(e.map)}", ENTER_TABLE)
            yield Edge(way, to, "Leads to", "Ways in", "", MAP_CHANGE)
            yield Edge(here, to, "Leads to", "Reached from", "", MAP_CHANGE)
            if e.object_set:
                yield Edge(way, ref("object-set", e.object_set), "Object set", "Entered by",
                           "", MAP_CHANGE)
            sound = _sound(model, e.sound, mid)
            if sound is not None:
                yield Edge(way, sound, "Sound", "Played by entrances",
                           "as the party goes through", MAP_CHANGE)
        if a.party_kind == 0 and a.bgm == SONG_SIX:
            yield Edge(here, ref("story-flag", SONG_SEVEN_FLAG), "Story flag", "Checked by",
                       f"plays {written(ref('song', SONG_SEVEN))} for "
                       f"{written(ref('song', SONG_SIX))} while set", MAP_SET)
        for c in w.changes(mid):
            change = ref("tile-change", mid, c.id)
            yield Edge(here, change, "Tile changes", "On map", "", BG_START)
            if c.bit:
                yield Edge(change, ref("story-flag", c.bit), "Story flag", "Set by",
                           "set as it starts", BG_START)
                yield Edge(change, ref("story-flag", c.bit), "Story flag", "Checked by",
                           "while set, the map loads changed", BG_COPY)
            sound = _sound(model, c.sound, mid)
            if sound is not None:
                yield Edge(change, sound, "Sound",
                           "Played by tile changes", "with its first copy", BG_START)
    for place in sorted(w.place_maps):
        if VISITED_FIRST <= place < VISITED_END:
            yield Edge(ref("place", place), ref("story-flag", place + VISITED_FLAG),
                       "Story flag", "Set by", "set when one of its maps is entered",
                       MAP_SET)
    for sid in sorted(fm.script_resources):
        try:
            buf, commands, _labels = fm.script(sid)
        except Exception:
            continue            # FieldMaps.errors says why
        cmds = list(commands.values())
        for to, on in es.script_switches(buf, cmds):
            if to in fm.script_resources:
                yield Edge(ref("script", sid), ref("script", to), "Hands over to",
                           "Handed over from",
                           f"on {w.map_title(on)}" if on is not None else "on the same map",
                           SCRIPT_MAP_SCRIPT_CHANGE if on is not None else SCRIPT_SCRIPT_CHANGE)
        for sc in es.scene_changes(buf, cmds):
            if sc["map"] is not None and sc["map"] in fm.maps:
                yield Edge(ref("script", sid), ref("map", sc["map"]), "Takes the party to",
                           "Reached by scripts", "",
                           SCRIPT_MAP_CHANGE if sc["id"] == es.SCENE_JUMP
                           else SCRIPT_MAP_SCRIPT_CHANGE)
    for s, maps in sorted(w.set_maps.items()):
        for i, d in sorted(w.definitions(s).items()):
            kind = OBJECT_REF_KINDS.get(d.kind)
            if kind is None:
                continue
            it = ref(kind, s, i)
            yield Edge(ref("object-set", s), it, _plural(kind), "Object set", "", OBJECTS_INIT)
            for mid in maps:
                yield Edge(it, ref("map", mid), "Stands on", _plural(kind), "", MAP_CHANGE)
                gone = fo.story_flag(d, mid)
                if gone is not None:
                    yield Edge(it, ref("story-flag", gone), "Story flag", "Checked by",
                               "it is not there while set", OBJECTS_INIT)
                    # MapObjectTouchRun runs a map monster's battle; won, the
                    # monster goes (MapObjectTouchRemove), setting this flag
                    if kind == "map-monster" and d.event:
                        yield Edge(it, ref("story-flag", gone), "Story flag", "Set by",
                                   "set when it is beaten", f"{TOUCH_REMOVE}, from {TOUCH_RUN}")
            if kind == "map-monster" and d.event:
                yield Edge(it, ref("battle", d.event), "Battle", "Map monsters",
                           "touching it starts it", TOUCH_RUN)
            if kind == "chest":
                yield from _chest_edges(w, it, d, maps)


def _chest_edges(w: _World, it, d, maps):
    from decoders.plugins.SLUS_006_28.formats import field_objects as fo
    got = fo.chest_contents(d)
    if got is not None and got.what == "item":
        yield Edge(it, ref("item", got.number), "Holds", "In chests", "", KIND7_RUN)
    lock = fo.chest_lock_flag(d)
    if lock is not None:
        yield Edge(it, ref("story-flag", lock), "Story flag", "Checked by",
                   "it opens only once set", KIND7_RUN)
    for mid in maps:
        opened = fo.chest_flag(d, mid)
        if opened is not None:
            if got is not None and got.sets_flag:
                yield Edge(it, ref("story-flag", opened), "Story flag", "Set by",
                           "set when it is emptied", KIND7_RUN)
            yield Edge(it, ref("story-flag", opened), "Story flag", "Checked by",
                       "while set it shows open", OBJECT_INIT)
        if got is not None and got.what == "label":
            sid = w.fm.maps[mid].area.script
            if got.number in w.script_labels(sid):
                yield Edge(it, ref("label", sid, got.number), "Runs", "Run by chests",
                           f"when examined on {w.map_title(mid)}", KIND7_RUN)


# ---------------------------------------------------------------------------
# titles
# ---------------------------------------------------------------------------

@links.title("map")
def map_title(model, r) -> str | None:
    return _world(model).place(r.id[0])


@links.title("place")
def place_title(model, r) -> str | None:
    names = model.names
    return names.location(r.id[0]) if names else None


@links.title("script")
def script_title(model, r) -> str | None:
    return _world(model).script_title(r.id[0])


@links.title("entrance")
def entrance_title(model, r) -> str | None:
    place = _world(model).place(r.id[0])
    return f"{place} · entrance {r.id[1]}" if place else None


@links.title("tile-change")
def tile_change_title(model, r) -> str | None:
    place = _world(model).place(r.id[0])
    return f"{place} · tile change {r.id[1]}" if place else None


def object_title(model, r) -> str | None:
    """"‹place› · entity 3": where, what and its number."""
    place = _world(model).object_place(r.id[0])
    return f"{place} · {KINDS[r.kind].name} {r.id[1]}" if place else None


for _kind in OBJECT_KINDS:
    links.title(_kind)(object_title)


#: The kinds numbered by their map first, and by their script first.
_BY_MAP = ("map", "entrance", "party-move", "tile-change", "cell")
_BY_SCRIPT = ("script", "label", "message", "actor")


@links.listed_last
def in_debug_room(model, r) -> bool:
    """The debug room's map, its place where no other map shows it, its
    scripts (its own and those only it hands over to: field_view's
    debug_scripts) and what is shown on it: listed after the rest."""
    w = _world(model)
    room = w.fm.maps.get(DEBUG_ROOM)
    if room is None:
        return False
    if r.kind in _BY_MAP:
        return r.id[0] == DEBUG_ROOM
    if r.kind == "place":
        return w.place_maps.get(r.id[0]) == [DEBUG_ROOM]
    if r.kind in _BY_SCRIPT:
        return r.id[0] in w.fm.debug_scripts or r.id[0] == room.area.script
    if r.kind in OBJECT_KINDS or r.kind == "object-set":
        return w.home_map(r.id[0]) == DEBUG_ROOM
    return False


# ---------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------

@links.card("map")
def map_card(model, r) -> CardBody:
    from viewer_tabs.field_view import MAP_TYPE_NOTES
    w = _world(model)
    mid = r.id[0]
    m = _the_map(w, mid)
    a, names, fm = m.area, w.names, w.fm
    facts = [("Place", w.place(mid) or written(ref("place", a.location)))]
    if a.party_kind in WALKS:
        facts.append(("The party walks it", WALKS[a.party_kind]))
    song = names.bgm(a.bgm) or written(ref("song", a.bgm)) if a.bgm else "none"
    if a.party_kind == 0 and a.bgm == SONG_SIX:
        song += (f"; {names.bgm(SONG_SEVEN) or written(ref('song', SONG_SEVEN))} once "
                 f"{written(ref('story-flag', SONG_SEVEN_FLAG))} is set")
    facts.append(("Song", song))
    entries = fm.entries.get(mid, [])
    from_maps = sum(1 for other in fm.maps for _row, e in w.rows(other) if e.map == mid)
    debug = sum(1 for e in entries if e in fm.debug_entries)
    scripts = len(entries) - from_maps - debug
    ways = [f"{from_maps} entrance{'s' if from_maps != 1 else ''}"]
    if scripts:
        ways.append(f"{scripts} by scripts")
    if debug:
        ways.append(f"{debug} from the debug room")
    facts.append(("Ways in", f"{len(entries)} ({', '.join(ways)})" if entries else "none"))
    chosen, by = fm.set_for(mid)
    others = [s for s in by if s and s != chosen]
    facts.append(("Object set", (written(ref("object-set", chosen)) if chosen else "none")
                  + (f"; {', '.join(written(ref('object-set', s)) for s in others)} on "
                     f"some ways in" if others else "")))
    raw = a.raw
    extended = [
        ("Map record", f"g_MapTbls[{a.record}] ({MAP_TBL_GET}): {raw.hex(' ').upper()}"),
        ("Read as", f"byte 0 party kind {a.party_kind}; 4 tile animation {a.tile_animation}; "
                    f"5 palette animation {a.palette_animation}; 6 place {a.location:#04x}; "
                    f"8 script {a.script:#04x}; 0xB effect {a.effect:#04x}; "
                    f"0xF song {a.bgm:#04x}"),
        ("Party kind", MAP_TYPE_NOTES.get(a.party_kind, f"party kind {a.party_kind}")),
        ("Resource", f"resource {m.resource} (g_MapResourcePairs, {MAP_SEEK})"),
    ]
    return CardBody(title=w.place(mid) or written(r),
                    subtitle=MAP_TYPES.get(a.party_kind, f"party kind {a.party_kind}"),
                    facts=facts, extended=extended,
                    proven=[MAP_SET, MAP_LOAD, MAP_TBL_GET, MAP_SEEK, MAP_CHANGE])


@links.card("place")
def place_card(model, r) -> CardBody:
    w = _world(model)
    n = r.id[0]
    name = w.names.location(n)
    maps = w.place_maps.get(n, [])
    if not maps and not name:
        raise LookupError(f"no map shows place {n} and the string table names none")
    facts = [("Shown on", f"{len(maps)} map{'s' if len(maps) != 1 else ''}" if maps
              else "no map")]
    short = w.names.location_short(n)
    if short:
        facts.append(("On a saved game", short))
    if VISITED_FIRST <= n < VISITED_END:
        facts.append(("Entering it", f"sets {written(ref('story-flag', n + VISITED_FLAG))}"))
    extended = [("String", f"string {n + 0x400} ({PLACE_STRING}: g_MapPlaceName + 0x400)")]
    return CardBody(title=name or written(r), subtitle="a place name the maps show",
                    facts=facts, extended=extended, proven=[MAP_SET, PLACE_STRING])


@links.card("script")
def script_card(model, r) -> CardBody:
    w = _world(model)
    fm = w.fm
    sid = r.id[0]
    res = fm.script_resources.get(sid)
    if res is None:
        raise LookupError(f"no script {sid} in g_ScriptResourcePairs")
    maps = sorted(fm.script_maps.get(sid, ()))
    facts = [("Run on", f"{len(maps)} map{'s' if len(maps) != 1 else ''}: {w.places(maps)}"
              if maps else "no map loads it; other scripts hand over to it")]
    if sid in fm.debug_scripts:
        facts.append(("The debug room's", "yes: only the debug room's own script hands "
                                          "over to it"))
    labels = w.script_labels(sid)
    facts.append(("Labels", f"{len(labels)} places it starts from"))
    extended = [("Resource", f"resource {res} (g_ScriptResourcePairs, {SCRIPT_LOAD})")]
    shared = [i for i in w.names.script_ids_for_resource(res) if i != sid]
    if shared:
        extended.append(("Shares its resource with",
                         ", ".join(written(ref("script", i)) for i in shared)))
    return CardBody(title=w.script_title(sid) or written(r),
                    subtitle="what the maps that run it say and do",
                    facts=facts, extended=extended,
                    proven=[MAP_LOAD, "ScriptChange (0x80068D7C)", SCRIPT_LOAD])


@links.card("object-set")
def object_set_card(model, r) -> CardBody:
    w = _world(model)
    s = r.id[0]
    res = w.fm.set_resources.get(s)
    if res is None:
        raise LookupError(f"no object set {s} (g_MapObjectsDataResourceNumbers names none)")
    maps = w.set_maps.get(s, [])
    defs = w.definitions(s)
    count = Counter(OBJECT_REF_KINDS.get(d.kind) for d in defs.values())
    facts = [("Entered on", w.places(maps) if maps else "no map: nothing enters with it")]
    facts += [(_plural(k), str(count[k])) for k in OBJECT_KINDS if count[k]]
    extended = [("Resource", f"resource {res} (g_MapObjectsDataResourceNumbers (0x800B4E2C)"
                             f"[{s}], {OBJECTS_DATA_LOAD})"),
                ("Definitions", f"{len(defs)} of 128 make an object (byte 1 not 0)")]
    place = w.object_place(s)
    return CardBody(title=written(r), subtitle=f"the objects of {place}" if place
                    else "the objects a map is entered with",
                    facts=facts, extended=extended,
                    proven=[OBJECTS_INIT, OBJECTS_DATA_LOAD, MAP_CHANGE])


def _taken_by(w: _World, mid: int, row: int) -> str:
    """What uses enter row `row` of map `mid`: the step cells of kind 1
    (MapAttributeRun) and the map's script's commands 0x26 naming it."""
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    out = []
    cells = w.cells(mid).get((1, row), 0)
    if cells:
        out.append(f"stepping on {cells} square{'s' if cells != 1 else ''} of the map")
    sid = w.fm.maps[mid].area.script
    try:
        buf, commands, _labels = w.fm.script(sid)
        if any(sc["entry"] == row for sc in es.scene_changes(buf, list(commands.values()))):
            out.append("the map's script")
    except Exception:
        pass
    return " or ".join(out) or "nothing found on the map or in its script"


@links.card("entrance")
def entrance_card(model, r) -> CardBody:
    w = _world(model)
    mid, row = r.id
    _the_map(w, mid)
    e = dict(w.rows(mid)).get(row)
    if e is None:
        raise LookupError(f"map {mid}'s enter table has no row {row} that leads anywhere")
    to = w.map_title(e.map)
    x, y = e.spot
    left, right, top, bottom = e.limit_rect
    facts = [("Leads to", f"{to} ({written(ref('map', e.map))})"),
             ("Puts the party", f"at ({x}, {y}), facing {FACINGS.get(e.facing, e.facing)}"),
             ("Object set", written(ref("object-set", e.object_set)) if e.object_set
              else "none: the map has no objects"),
             ("Taken by", _taken_by(w, mid, row)),
             ("The camera keeps to", f"({left}, {top}) to ({right}, {bottom})")]
    if e.sound:
        facts.append(("Sound", _sound_words(model, e.sound, mid)))
    extended = [
        ("Enter row", f"row {row} of map {mid}'s command 9 ({ENTER_TABLE}), read from "
                      f"g_MapEnterTable (0x800B8D04) by {MAP_CHANGE}"),
        ("Bytes", f"map {e.map:#04x}, object set {e.object_set:#04x}, fade {e.fade}, "
                  f"sound {e.sound:#04x}, limits {', '.join(map(str, e.limits))} (8-px cells), "
                  f"spot ({e.x}, {e.y}), facing byte {(e.facing - 1) & 0xFF}"),
    ]
    return CardBody(title=entrance_title(model, r) or written(r), subtitle=f"leads to {to}",
                    facts=facts, extended=extended,
                    proven=[MAP_CHANGE, ENTER_TABLE, ATTRIBUTE_RUN, SCRIPT_MAP_CHANGE])


def _sound(model, n: int, mid: int):
    """The sound effect sound number n is on map `mid`, where SoundPlay
    plays it: a place's own by its bank (links.sound_effects.played_ref);
    None for no sound, or one that plays nothing there."""
    from viewer_tabs.links import sound_effects
    return sound_effects.played_ref(model, n, mid) if n else None


def _sound_words(model, n: int, mid: int) -> str:
    sound = _sound(model, n, mid)
    return written(sound) if sound is not None else \
        f"number {n}, which plays nothing on this map"


@links.card("tile-change")
def tile_change_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.formats import bg_change as bc
    w = _world(model)
    mid, n = r.id
    _the_map(w, mid)
    c = next((c for c in w.changes(mid) if c.id == n), None)
    if c is None:
        raise LookupError(f"map {mid} has no tile change {n}")
    steps = len(c.sources)
    facts = [("Changes", f"a {c.w * 8} × {c.h * 8} part of the map at ({c.x * 8}, {c.y * 8})"),
             ("In", f"{steps} step{'s' if steps != 1 else ''}"
                    + (f", {c.frames} frames apart" if steps > 1 else ""))]
    if c.bit:
        facts.append(("Kept by", f"{written(ref('story-flag', c.bit))}: set as it starts, so "
                                 f"it runs once; while set the map loads changed"))
    cells = w.cells(mid).get((bc.KIND_BG_CHANGE, n), 0)
    facts.append(("Started by", f"stepping on {cells} square{'s' if cells != 1 else ''} of "
                                f"the map" if cells else "a script, or nothing found"))
    if c.sound:
        facts.append(("Sound", _sound_words(model, c.sound, mid)))
    extended = [
        ("Row", f"row {n} of the bg change table, the map's command 9 from +0xA00 "
                f"(g_MapBgChangeTable (0x800B8CFC))"),
        ("Bytes", f"at ({c.x}, {c.y}), {c.w} × {c.h} (8-px cells); story bit "
                  f"{'0x480 + %#x' % (c.bit - bc.BIT_BASE) if c.bit else 'none'}; interval "
                  f"{c.interval}; sound {c.sound:#04x}; sources "
                  + ", ".join(f"({sx}, {sy})" for sx, sy in c.sources)),
    ]
    return CardBody(title=tile_change_title(model, r) or written(r),
                    subtitle="a change of the map's tiles", facts=facts, extended=extended,
                    proven=[BG_START, BG_STEP, BG_COPY, ATTRIBUTE_RUN, SCRIPT_BG_CHANGE])


def _object_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.formats import field_objects as fo
    w = _world(model)
    d = _object(w, r)
    s, i = r.id
    maps = w.set_maps.get(s, [])
    kind = r.kind
    facts = []
    proven = [OBJECTS_INIT, OBJECT_INIT]
    subtitle = WHAT[kind]
    number = d.think & 0x3F
    if kind != "chest":
        said, fn = BEHAVIOURS.get(number, (f"behaviour {number}, not read here", THINK))
        facts.append(("Behaviour", said))
        proven.append(fn)
    label = f"definition byte 0xB: label {d.event} of the map's script ({LABEL_RUN})"
    extended = []
    if kind == "entity":
        facts.append(("When talked to", "it turns to the party, and a label of the map's "
                                         "script runs" if d.event else "nothing happens"))
        proven.append(TALK_CHECK)
        if d.event:
            extended.append(("Talk", f"{label}, run by {TALK_CHECK}"))
    elif kind == "trigger":
        facts.append(("When touched", "a label of the map's script runs" if d.event
                      else "nothing happens"))
        proven.append(TOUCH_RUN)
        if d.event:
            extended.append(("Touch", f"{label}, run by {TOUCH_RUN}"))
    elif kind == "map-monster":
        facts.append(("When touched", f"{links.title_of(model, ref('battle', d.event))} starts"
                      if d.event else "nothing happens"))
        proven.append(TOUCH_RUN)
        if d.event:
            extended.append(("Battle", f"definition byte 0xB: battle {d.event}, "
                                       f"MapBtlRun (0x8007AE58) from {TOUCH_RUN}"))
    else:
        got = fo.chest_contents(d)
        subtitle = "something to examine" if got is not None and got.what == "label" else WHAT[kind]
        facts.append(("Holds", _holds(model, w, got)))
        if fo.chest_lock_flag(d) is not None:
            facts.append(("Locked", f"it opens only once "
                                    f"{written(ref('story-flag', fo.CHEST_LOCK_FLAG))} is set"))
        proven.append(KIND7_RUN)
        extended.append(("Contents", f"definition byte 0xB: {d.event:#04x} ({KIND7_RUN}: 0 "
                                     f"nothing, 1-0xB6 an item, 0xB7-0xEF money, 0xF0 up "
                                     f"label byte + 0x230)"))
    hidden = [(mid, fo.story_flag(d, mid)) for mid in maps]
    hidden = [(mid, f) for mid, f in hidden if f is not None]
    if hidden:
        facts.append(("Gone while set", "; ".join(
            written(ref("story-flag", f)) + (f" (on {w.map_title(mid)})" if len(maps) > 1 else "")
            for mid, f in hidden)))
    facts.append(("Stands on", ", ".join(f"{w.map_title(m)} ({written(ref('map', m))})"
                                         for m in maps) or "no map is entered with its set"))
    facing = (d.facing + 1) & 0xFF
    facts.append(("Where", f"({d.x * 8}, {d.y * 8}), facing {FACINGS.get(facing, facing)}"))
    extended[:0] = [
        ("Definition", f"definition {i} of object set {s}: {d.raw.hex(' ').upper()}"),
        ("Read as", f"byte 0 kind {d.kind} (low 6 bits + 1), layer {d.layer:#04x}; byte 1 "
                    f"sprite data {d.sprite_data:#04x}"
                    + (" (a chest is drawn with sprite data 0)" if kind == "chest" else "")
                    + f"; byte 2 story flag {d.story_bit:#04x}; byte 3 mode {d.mode}; think "
                      f"{d.think:#04x}"),
        ("Story flag", "0x580 + byte 2 for kinds 1-3; the definition + 0x680 + (map - 0x65) "
                       "x 0x80 for the rest (MapObjectsInit)"),
    ]
    picture = None
    home = w.home_map(s)
    if home is not None:
        try:
            from viewer_tabs.field_view import object_picture
            picture = object_picture(w.fm, s, home, i, w.placed)
        except Exception:
            picture = None
    return CardBody(title=object_title(model, r) or written(r), subtitle=subtitle,
                    picture=picture, facts=facts, extended=extended,
                    proven=list(dict.fromkeys(proven)))


def _holds(model, w: _World, got) -> str:
    """A chest's contents in plain words (MapObjectKind7Run)."""
    if got is None:
        return "nothing happens when it is examined: it is open"
    if got.what == "empty":
        return "nothing"
    if got.what == "item":
        return links.title_of(model, ref("item", got.number))
    if got.what == "label":
        return "a label of the map's script runs when it is examined; it stays shut"
    amounts = w.amounts()
    if isinstance(amounts, str):
        return f"money: entry {got.number} of the amounts, which are not read here ({amounts})"
    return f"{amounts[got.number]} in money"


for _kind in OBJECT_KINDS:
    links.card(_kind)(_object_card)

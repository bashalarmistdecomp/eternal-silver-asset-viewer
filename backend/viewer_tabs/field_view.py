"""What the Maps tab plays: a map with the objects its set makes and
the party on its entries' spots (formats.field_objects), stepped on the
field's clock (formats.field_motion) and composed by the field's draw
rules (formats.field_picture); and the pages its Tileset view shows.

Nothing here reads game bytes but through the decoders.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace

import numpy as np
from PIL import Image

#: The groups the views' layers show apart, by MapObjectInit's kind.
ENTITIES = "entities and triggers"       # kinds 1..4
ENEMIES = "map monsters"                # kinds 5, 6
CHESTS = "chests"                       # kind 7
PARTY = "the party"
GROUPS = (ENTITIES, ENEMIES, CHESTS, PARTY)
#: Each group's name on a toggle.
GROUP_SHORT = {ENTITIES: "entities", ENEMIES: "monsters", CHESTS: "chests", PARTY: "party"}
#: The party id drawn on the entries' spots: party place 0.
LEAD = 1
#: The debug room: a room of doors to the maps, for testing.
#: The scripts only it hands over to (its own, and the room-select menu)
#: put the party on other maps with the whole plane as the view's limits;
#: the In game view leaves those ways in out.
DEBUG_ROOM = 0x09
#: The map types the list groups maps by: the area record's party kind
#: (records.areas), how the party walks the map.
MAP_TYPES = {0: "Overworld", 1: "Towns", 2: "Dungeons"}
MAP_TYPE_NOTES = {
    0: "party kind 0: small sprites, one walk step a frame",
    1: "party kind 1: the party walks in a line behind the lead",
    2: "party kind 2: the lead walks alone",
}


def debug_scripts(switches: dict[int, list], area_scripts: dict[int, int], room: int) -> set[int]:
    """The scripts only map `room`'s own script hands over to (a 0x42 or a
    0x5D, event_script.script_switches), itself included: a room-select
    menu warps to a map and goes on running there, so where a script runs
    does not tell it apart; who hands over to it does. `area_scripts`: map
    -> the script its area record names."""
    def handed(roots) -> set[int]:
        seen, todo = set(), list(roots)
        while todo:
            sid = todo.pop()
            if sid not in seen:
                seen.add(sid)
                todo += [to for to, _m in switches.get(sid, ())]
        return seen
    if room not in area_scripts:
        return set()
    return handed({area_scripts[room]}) - handed(
        {sid for mid, sid in area_scripts.items() if mid != room})


def group_of(kind: int) -> str:
    if kind == 7:
        return CHESTS
    if kind in (5, 6):
        return ENEMIES
    return ENTITIES


#: The reference kind (viewer_tabs.refs) of an object by MapObjectInit's
#: kind: 1-3 someone to talk to (MapPartyTalkCheck (0x80067D1C) passes over
#: 4-6), 4 a trigger and 5, 6 a map monster (MapObjectTouchRun
#: (0x8007ACD8): a label for 4, a battle for the rest), 7 a chest
#: (MapObjectKind7Run (0x80067F84)).
OBJECT_REF_KINDS = {1: "entity", 2: "entity", 3: "entity", 4: "trigger",
                    5: "map-monster", 6: "map-monster", 7: "chest"}


def object_name(kind: int, index: int) -> str:
    """Definition `index` on the map page, by its kind: "entity 3", "chest 5"."""
    from viewer_tabs.refs import KINDS
    k = OBJECT_REF_KINDS.get(kind)
    return f"{KINDS[k].name} {index}" if k else f"object {index}"


def object_ref(kind: int, object_set: int, index: int) -> dict | None:
    """The reference of definition `index` of an object set, as JSON; None
    for a kind no reference names."""
    from viewer_tabs.refs import ref
    k = OBJECT_REF_KINDS.get(kind)
    return ref(k, object_set, index).json() if k else None


@dataclass
class SheetRef:
    """A pose sheet and the anim table a record steps."""
    sheet: object                       # sprite_pages.PoseSheet or None
    table: object                       # field_objects.AnimTable
    data: object                        # SpriteBlockData or None
    label: str


@dataclass
class MapField:
    """One map with one object set, as MapChange leaves it."""
    map_id: int
    object_set: int
    other_sets: dict                    # set -> the entries naming it
    entries: list                       # field_objects.MapEntry with this set
    objects: list                       # field_objects.MapObject
    leads: list                         # field_objects.PartyLead, one per distinct spot
    ground: object                      # field_picture.Ground
    sheets: dict                        # (sprite data, palette row) -> SheetRef
    notes: list = field(default_factory=list)
    att: object = None                  # field_objects.Attributes


class FieldMaps:
    """The disc's maps, entries, object sets and sprite sheets, loaded once."""

    def __init__(self, names):
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        from decoders.plugins.SLUS_006_28.formats import field_objects as fo
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        from decoders.plugins.SLUS_006_28.formats import map_reach as mr
        from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
        from decoders.plugins.SLUS_006_28.formats import stfield as sf
        from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pfs
        from decoders.plugins.SLUS_006_28.formats import system_strings as ss
        img = names.binary.code
        if names.binary.text_start != fo.EXE_BASE:
            raise ValueError(f"text at {names.binary.text_start:#x}, the field's "
                             f"tables expect {fo.EXE_BASE:#x}")
        self.names = names
        self.image = img
        self.read = names.read_resource
        self.tables = fo.field_tables(img)
        self.set_resources = mos.set_resources(img)
        self.row_palettes = {row: sp.sprite_init_palette(self.read(res))
                             for row, res in sp.SPRITE_INIT_PALETTES.items()}
        self.stfield = sf.parse(self.read(sf.RESOURCE))
        self.party_buf = self.read(pfs.DIRECTORY_RESOURCE)
        self.maps = {m.map_id: m for m in names.maps()}
        self.entries: dict[int, list] = {}
        #: what could not be read, said as a provider says a failure
        self.errors: list[str] = []
        for m in self.maps.values():
            try:
                for e in fo.table_entries(self.read(m.resource), m.map_id):
                    self.entries.setdefault(e.map, []).append(e)
            except Exception as ex:
                self.errors.append(f"Could not read map {m.map_id}'s entrances: {ex}")
        self._words, self._commands = ss.words_of(img), es.command_count(img)
        self.script_resources = es.script_resources(img)
        switches: dict[int, list] = {}
        made_by: list[tuple[int, object]] = []
        #: script -> its 0x27 moves of the party: (offset, place row, own Start)
        self.script_moves: dict[int, list[tuple]] = {}
        for sid, res in sorted(self.script_resources.items()):
            try:
                buf = self.read(res)
                cmds, _gaps = es.script_code(buf, self._words, self._commands)
            except Exception as ex:
                self.errors.append(f"Could not read script {sid}: {ex}")
                continue
            switches[sid] = es.script_switches(buf, cmds)
            self.script_moves[sid] = [(c.offset, *mr.script_place(buf, c.offset))
                                      for c in cmds if c.id == mr.PARTY_PLACE]
            for c in es.scene_changes(buf, cmds):
                if c["map"] is None:
                    continue
                name = "ScriptCommandMapChange" if c["id"] == es.SCENE_JUMP \
                    else "ScriptCommandMapScriptChange"
                e = fo.script_entry(buf, c["offset"],
                                    f"script {sid} at {c['offset']:#x}, command "
                                    f"{c['id']:#x} ({name})")
                self.entries.setdefault(e.map, []).append(e)
                made_by.append((sid, e))
        #: the scripts only the debug room's own script hands over to
        self.debug_scripts = debug_scripts(
            switches, {mid: m.area.script for mid, m in self.maps.items()}, DEBUG_ROOM)
        #: area script -> the maps that load it (MapSet (0x80068780))
        self.script_maps: dict[int, set[int]] = {}
        for mid, m in self.maps.items():
            self.script_maps.setdefault(m.area.script, set()).add(mid)
        #: the entries the debug scripts make
        self.debug_entries = {e for sid, e in made_by if sid in self.debug_scripts}

    # -- one map ------------------------------------------------------------

    def set_for(self, map_id: int) -> tuple[int, dict]:
        """The object set most of the map's entries name (0 makes no objects),
        and every set named -> its entries."""
        by_set: dict[int, list] = {}
        for e in self.entries.get(map_id, []):
            by_set.setdefault(e.object_set, []).append(e)
        named = Counter({s: len(v) for s, v in by_set.items() if s})
        return (named.most_common(1)[0][0] if named else 0), by_set

    def map_field(self, map_id: int) -> MapField | None:
        from decoders.plugins.SLUS_006_28.formats import field_objects as fo
        from decoders.plugins.SLUS_006_28.formats import field_picture as fp
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        from decoders.plugins.SLUS_006_28.formats import world_map as wm
        m = self.maps[map_id]
        raw = self.read(m.resource)
        area = m.area
        g = fp.ground(raw, area.effect, area.party_kind)
        if g is None:
            return None
        att = fo.Attributes(wm.attribute_plane(wm.attributes(raw)))
        chosen, by_set = self.set_for(map_id)
        notes = list(g.notes)
        sheets = _Sheets(self, raw, area.party_kind)
        objects = []
        if chosen:
            res = self.set_resources.get(chosen)
            if not res:
                notes.append(f"object set {chosen} names no resource")
            else:
                sheets.object_set = mos.parse_object_set(self.read(res))
                block = sheets.object_set.definitions
                numbers = {d.sprite_data for d in fo.made_definitions(block)}
                numbers |= {self.tables.twins[d.sprite_data - 1]
                            for d in fo.made_definitions(block)
                            if d.sprite_data < fo.TWIN_BELOW}
                tables_of = {n: sheets.table(n) for n in numbers | {0}}
                objects = fo.place_objects(block, att, self.tables, tables_of)
        leads, seen = [], set()
        for e in by_set.get(chosen, []):
            key = (e.x, e.y, e.facing)
            if key in seen:
                continue
            seen.add(key)
            numbers = {LEAD, LEAD + fo.PARTY_KIND_0_OFFSET, self.tables.twins[LEAD - 1]}
            leads.append(fo.party_lead(e, area.party_kind, LEAD, att, self.tables,
                                       {n: sheets.table(n, party=True) for n in numbers}))
        return MapField(map_id=map_id, object_set=chosen,
                        other_sets={s: v for s, v in by_set.items() if s != chosen},
                        entries=by_set.get(chosen, []), objects=objects, leads=leads,
                        ground=g, sheets=sheets, notes=notes, att=att)

    def bg_bit_maps(self) -> dict[int, list[int]]:
        """Story bit -> the maps whose bg change rows it switches."""
        from decoders.plugins.SLUS_006_28.formats import bg_change as bc
        if getattr(self, "_bg_bits", None) is None:
            out: dict[int, set] = {}
            for m in self.maps.values():
                try:
                    rows = bc.map_changes(self.read(m.resource))
                except Exception as ex:
                    self.errors.append(f"Could not read map {m.map_id}'s tile changes: {ex}")
                    continue
                for r in rows:
                    if r.bit:
                        out.setdefault(r.bit, set()).add(m.map_id)
            self._bg_bits = {b: sorted(v) for b, v in out.items()}
        return self._bg_bits

    def sources(self, map_id: int) -> list[bytes]:
        """What `map_field` and `played` read for the map besides its file
        and area record: the entries into it, the set it places, the sheets
        and palettes the records draw with, the program's field tables,
        the area's tile animations and what the In game view walks from.
        The views place and play two discs' maps with the same sources
        alike (viewer_tabs.identity)."""
        from decoders.plugins.SLUS_006_28.formats import field_motion as fmo
        from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
        from decoders.plugins.SLUS_006_28.formats import stfield as sf
        chosen, by_set = self.set_for(map_id)
        entries = [(e.object_set, e.limits, e.x, e.y, e.facing)
                   for named in by_set.values() for e in named]
        res = self.set_resources.get(chosen) if chosen else None
        t, st = self.tables, self.stfield
        if not hasattr(self, "_data_0"):
            # sprite data 0 as _Sheets draws it: its poses, not the whole
            # image they are cut from
            sheet = sp.pose_sheet(sp.parse_actor_block(st.banks[1]),
                                  {sf.PAGE: sf.sheet_image(st, 7)})
            self._data_0 = sheet.image.tobytes() if sheet and sheet.image else b""
        tiles = fmo.tile_animations(self.image, self.maps[map_id].area.tile_animation)
        try:
            colours = repr(palette_data(self, self.maps[map_id].area.palette_animation))
        except (ValueError, LookupError) as ex:
            colours = f"unreadable: {ex}"
        try:
            reach = self.reach_inputs(map_id).key()
        except Exception as ex:
            reach = f"unreadable: {ex}".encode()
        return [repr(entries).encode(),
                self.read(res) if res else b"",
                repr(sorted(self.row_palettes.items())).encode(),
                st.banks[1], self._data_0,
                self.party_buf,
                repr((t.twins, t.speed_pixels, t.speed_intervals, t.dxs, t.dys)).encode(),
                repr(tiles).encode(), colours.encode(), reach]

    def strip_block(self) -> bytes:
        """SYSTEM.DAT's type-1 block, where the palette animations' strip
        lies (formats.palette_animation)."""
        if not hasattr(self, "_strip_block"):
            from decoders.plugins.SLUS_006_28.formats import system_dat as sd
            from decoders.plugins.SLUS_006_28.formats import system_strings as ss
            self._strip_block = ss.block(self.read(sd.RESOURCE))
        return self._strip_block


    # -- what a player can see -------------------------------------------

    def script(self, sid: int):
        """A script's bytes, its commands by offset and its labels."""
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        cache = self.__dict__.setdefault("_scripts", {})
        if sid not in cache:
            buf = self.read(self.script_resources[sid])
            cmds, _gaps = es.script_code(buf, self._words, self._commands)
            cache[sid] = (buf, {c.offset: c for c in cmds}, es.labels(buf))
        return cache[sid]

    def reach_inputs(self, map_id: int) -> ReachInputs:
        """What the In game view walks from (formats.map_reach):

        - every entry into the map, but those the debug scripts make (the
          ones only the debug room's script hands over to: DEBUG_ROOM);
        - every 0x27 move of the map's own script (the one MapSet
          (0x80068780) takes from its area record). A move by place row
          takes that row of this map's own rows, and none when the row is
          all zeros. A move with its own spot, from a script other maps
          load too, counts here when its limits are those of another way
          into this map (an entry or a place row); else it is `doubtful`
          (`reach_data` weighs it): a script does not say which of its
          maps it is on when the move runs;
        - the map's place rows, for its kind-2 cells;
        - what each kind-4 and kind-5 label of the map's script does
          (map_reach.label_act);
        - the attribute plane as the map loads, and with every bg change
          copied in (each row's last source).

        The scripts other scripts hand the map over to (event_script
        .map_scripts) are left out: a script that several maps load hands
        over to scripts meant for one of them, and their moves and labels
        read this map's rows as if they were that map's."""
        from decoders.plugins.SLUS_006_28.formats import bg_change as bc
        from decoders.plugins.SLUS_006_28.formats import command_list as cl
        from decoders.plugins.SLUS_006_28.formats import map_reach as mr
        from decoders.plugins.SLUS_006_28.formats import world_map as wm
        cache = self.__dict__.setdefault("_reach_inputs", {})
        if map_id in cache:
            return cache[map_id]
        m = self.maps[map_id]
        raw = self.read(m.resource)
        enter = cl.effective(raw, cl.MAP_ENTER_TABLES)
        places = mr.payload_places(enter.payload) if enter is not None else {}
        starts = [mr.Start(*e.spot, e.limit_rect, e.source)
                  for e in self.entries.get(map_id, []) if e not in self.debug_entries]
        known = {st.limits for st in starts} | {p.limits for p in places.values()}
        doubtful = []
        sid = m.area.script
        shared = len(self.script_maps.get(sid, ())) > 1
        for offset, row, own in self.script_moves.get(sid, ()):
            where = f"script {sid} at {offset:#x}, command 0x27"
            if row:
                if row in places:
                    starts.append(replace(places[row], source=f"{where}, place row {row}"))
            elif own is not None:
                own = replace(own, source=where)
                (doubtful if shared and own.limits not in known else starts).append(own)
        base = wm.attribute_plane(wm.attributes(raw))
        planes = [base]
        rows = bc.map_changes(raw)
        if rows:
            changed = [list(r) for r in base]
            for r in rows:
                sx, sy = r.sources[-1]
                bc.copy(changed, r.x, r.y, sx, sy, r.w, r.h)
            planes.append(changed)
        labels = set()
        for plane in planes:
            ids = np.array(plane, dtype=np.int32) & mr.EVENT_ID
            kinds, args = ids >> 7, ids & mr.EVENT_ARG
            labels |= {int(a) for a in np.unique(
                args[((kinds == mr.LABEL_KIND) | (kinds == mr.PUSH_KIND)) & (args != 0)])}
        acts = {}
        if labels and sid in self.script_resources:
            try:
                buf, commands, named = self.script(sid)
                acts = {label: mr.label_act(buf, commands, named, label)
                        for label in sorted(labels)}
            except Exception as ex:
                self.errors.append(f"Could not read script {sid}: {ex}")
        cache[map_id] = ReachInputs(m.area.party_kind, starts, places, acts, planes, doubtful)
        return cache[map_id]


@dataclass
class ReachInputs:
    """FieldMaps.reach_inputs."""
    party_kind: int
    starts: list                # map_reach.Start: the ways in and the scripts' moves
    places: dict                # place row -> map_reach.Start
    acts: dict                  # kind-4/5 label -> map_reach.GONE / STAYS
    planes: list                # attribute planes to walk
    doubtful: list              # moves of shared scripts no other way in vouches for

    def key(self) -> bytes:
        """The inputs as two discs' maps may share them: spots, limits and
        acts, not where in which script they were read."""
        def spot(st):
            return st.x, st.y, st.limits
        return repr((self.party_kind, sorted(map(spot, self.starts)),
                     sorted((k, spot(v)) for k, v in self.places.items()),
                     sorted(self.acts.items()), sorted(map(spot, self.doubtful)))).encode()


class _Sheets:
    """Pose sheets by (sprite data number, palette row), made on demand.
    The party's numbers come from the object set when the set loaded them
    first (MapPartySpriteDataMissingCount (0x800647E4) loads only the
    missing), else from resource 0x1E8."""

    def __init__(self, fm: FieldMaps, map_raw: bytes, party_kind: int):
        self.fm = fm
        self.map_raw = map_raw
        self.party_kind = party_kind
        self.object_set = None
        self._made: dict = {}
        self._party: dict = {}
        self._map_pal = None

    def _data(self, number: int, party: bool = False):
        """-> (SpriteBlockData, {page slot: BattlePage}, where) or None."""
        from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pfs
        from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
        if number == 0 and not party:
            data = sp.parse_actor_block(self.fm.stfield.banks[1])
            return data, None, "g_SpriteData1 (0x800DDFB0), resource 2"
        os_ = self.object_set
        if os_ is not None and number in os_.blocks:
            return os_.actor(number), {p.index: p for p in os_.pages if p.lines}, \
                f"sprite data {number} ({number:#04x}) of the object set"
        if not party:
            return None
        if number not in self._party:
            try:
                fs = pfs.load_sheet(self.fm.party_buf, number)
                self._party[number] = (fs.actor(), {0: fs.picture},
                                       f"party sheet {number} ({number:#04x}), resource 488 (0x1E8) directory row {fs.row}")
            except ValueError:
                self._party[number] = None
        return self._party[number]

    def table(self, number: int, party: bool = False):
        from decoders.plugins.SLUS_006_28.formats import field_objects as fo
        got = self._data(number, party)
        return fo.anim_table(got[0] if got else None)

    def palette(self, row: int) -> bytes | None:
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        if row in self.fm.row_palettes:
            return self.fm.row_palettes[row]
        if row == mos.ROW_MAP:
            if self._map_pal is None:
                self._map_pal = mos.map_palette(self.map_raw) or b""
            return self._map_pal or None
        return None

    def get(self, number: int, row: int, party: bool = False) -> SheetRef | None:
        from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
        from decoders.plugins.SLUS_006_28.formats import field_objects as fo
        from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
        from decoders.plugins.SLUS_006_28.formats import stfield as sf
        key = (number, row, party)
        if key in self._made:
            return self._made[key]
        got = self._data(number, party)
        ref = None
        if got is not None and got[0] is not None:
            data, pages, where = got
            if pages is None:
                sheet = sp.pose_sheet(data, {sf.PAGE: sf.sheet_image(self.fm.stfield, 7)})
            else:
                pal = self.palette(row)
                sheet = (sp.pose_sheet(data, {k: bg.render_page(p, pal)
                                              for k, p in pages.items()})
                         if pal is not None else None)
            ref = SheetRef(sheet=sheet, table=fo.anim_table(data), data=data,
                           label=f"{where} · row {row}")
        self._made[key] = ref
        return ref


def pose_image(ref: SheetRef, pose: int | None) -> tuple[Image.Image, int, int] | None:
    """-> (the pose's cell, anchor x, anchor y) or None when it draws nothing."""
    sh = ref.sheet if ref else None
    if sh is None or pose is None or not 0 <= pose < len(sh.cells) or sh.cells[pose] is None:
        return None
    x, y = (pose % sh.columns) * sh.cell_w, (pose // sh.columns) * sh.cell_h
    return sh.image.crop((x, y, x + sh.cell_w, y + sh.cell_h)), sh.anchor_x, sh.anchor_y


#: Object sets `object_picture` keeps placed, for the next picture of one.
KEEP_PLACED = 4


def object_picture(fm: FieldMaps, object_set: int, map_id: int, index: int,
                   keep: dict | None = None) -> Image.Image | None:
    """Definition `index` of an object set as it stands when map `map_id`
    is entered with the set: the pose MapObjectInit (0x800656CC) starts it
    on, drawn with the palette row MapRecordInit (0x80065940) gives its
    kind and mode (row 506 is that map's own), black where the draw word
    says so, cut to what it draws; chests closed. None when it draws
    nothing. `keep` holds the last sets placed, for the next call."""
    from decoders.plugins.SLUS_006_28.formats import field_objects as fo
    from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
    keep = {} if keep is None else keep
    placed = keep.get((object_set, map_id))
    if placed is None:
        m = fm.maps[map_id]
        res = fm.set_resources.get(object_set)
        if not res:
            return None
        sheets = _Sheets(fm, fm.read(m.resource), m.area.party_kind)
        sheets.object_set = mos.parse_object_set(fm.read(res))
        block = sheets.object_set.definitions
        numbers = {0} | {d.sprite_data for d in fo.made_definitions(block)}
        objects = fo.place_objects(block, fo.Attributes([]), fm.tables,
                                   {n: sheets.table(n) for n in numbers})
        while len(keep) >= KEEP_PLACED:
            keep.pop(next(iter(keep)))
        placed = keep[(object_set, map_id)] = (sheets, {o.definition.index: o for o in objects})
    sheets, objects = placed
    obj = objects.get(index)
    if obj is None:
        return None
    draw = mos.record_draw(obj.kind, obj.mode)
    ref = sheets.get(obj.sprite_data, draw.palette_row)
    got = pose_image(ref, ref.table.pose(obj.anim.step) if ref else None)
    if got is None:
        return None
    im = got[0]
    if draw.attr & 0x8000:
        black = Image.new("RGBA", im.size, (0, 0, 0, 255))
        black.putalpha(im.getchannel("A"))
        im = black
    box = im.getchannel("A").getbbox()
    return im.crop(box) if box else None


def pose_pieces(ref: SheetRef, pose: int | None, x: int, y: int) -> list[tuple[int, int, int, int]]:
    """The rectangles bg_cover_box_set (0x80013EF0) is handed for a pose
    drawn at anchor (x, y): each piece's (x0, y0, width, height)."""
    from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
    data = ref.data if ref else None
    if data is None or pose is None:
        return []
    poses = {p.index: p for p in sp.list_poses(data)}
    p = poses.get(pose)
    if p is None:
        return []
    out = []
    for i in range(p.first, p.first + p.count):
        s = data.slice(i)
        if s is not None:
            out.append((x + s.pts[0], y + s.pts[1], s.w, s.h))
    return out


def _sprite(ref: SheetRef | None, pose: int | None, x: int, y: int, depth: int,
            **kw):
    from decoders.plugins.SLUS_006_28.formats import field_picture as fp
    got = pose_image(ref, pose)
    if got is None:
        return None
    im, ax, ay = got
    return fp.Sprite(image=im, left=x - ax, top=y - ay, depth=depth,
                     pieces=pose_pieces(ref, pose, x, y), **kw)


def sprites_of(mf: MapField, groups=GROUPS) -> list:
    """The sprite list entries the map's records make as the map opens:
    the party lead on each entry's spot (entry 0, its twin 0x46), the
    objects from entry 0x10 and their twins from 0x56, in row order."""
    from decoders.plugins.SLUS_006_28.formats import field_picture as fp
    from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
    out = []
    if PARTY in groups:
        for lead in mf.leads:
            draw = mos.record_draw(lead.kind, 0)
            ref = mf.sheets.get(lead.sprite_data, draw.palette_row, party=True)
            s = _sprite(ref, ref.table.pose(lead.anim.step) if ref else None,
                        lead.x, lead.y, lead.depth, queue=fp.queue_of(0), klass=lead.klass)
            if s:
                out.append(s)
            if lead.twin_anim is not None:
                tref = mf.sheets.get(lead.twin_data, mos.record_draw(1, 0).palette_row,
                                     party=True)
                t = _sprite(tref, tref.table.pose(lead.twin_anim.step) if tref else None,
                            lead.x, lead.depth, lead.depth, twin=True,
                            queue=fp.queue_of(0x46), klass=lead.klass)
                if t:
                    out.append(t)
    twins = 0
    for obj in mf.objects:
        slot_twin = 0x56 + twins
        if obj.twin_anim is not None:
            twins += 1
        if group_of(obj.kind) not in groups:
            continue
        draw = mos.record_draw(obj.kind, obj.mode)
        ref = mf.sheets.get(obj.sprite_data, draw.palette_row)
        black = bool(draw.attr & 0x8000)
        s = _sprite(ref, ref.table.pose(obj.anim.step) if ref else None, obj.x, obj.y,
                    obj.depth, queue=fp.queue_of(0x10 + obj.row), klass=obj.klass,
                    semi=draw.semi, black=black)
        if s:
            out.append(s)
        if obj.twin_anim is not None:
            tref = mf.sheets.get(obj.twin_data, draw.palette_row)
            t = _sprite(tref, tref.table.pose(obj.twin_anim.step) if tref else None,
                        obj.x, obj.y, obj.depth, twin=True, queue=fp.queue_of(slot_twin),
                        klass=fp.CLASS_UNDER, semi=draw.semi, black=black)
            if t:
                out.append(t)
    return out


# ---------------------------------------------------------------------------
# what the Maps tab plays
# ---------------------------------------------------------------------------

#: Field frames played before the view loops: a minute at 59.94 a second.
LOOP_TICKS = 3600
#: frame_end (0x8001F30C) waits VSync(0): a field frame a vertical blank
#: while its work fits one.
TICK_HZ = 59.94
TICK_NOTE = ("one tick per field frame: MapFrameUpdate (0x80055840) once, then "
             "frame_end (0x8001F30C)'s VSync(0)")


@dataclass
class Played:
    """A map's objects, the party and the tile animations stepped
    `ticks` field frames from the moment MapChange leaves them."""
    mf: MapField
    lead: object                # field_objects.PartyLead, or None
    ticks: int
    scene: dict                 # viewer_tabs.scene's shape, depth "field"
    still: Image.Image          # tick 0
    tiles: list                 # field_motion.TileAnimation as the set starts them
    tile_cells: int             # map cells the tile animations change
    stuck: dict                 # why a row stopped thinking -> rows
    moved: int                  # rows that left their first spot
    draws: int                  # random draws taken
    notes: list = field(default_factory=list)


def _pose_pieces_all(ref: SheetRef) -> list:
    """Each pose's pieces about the anchor, as `pose_pieces` gives them."""
    from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
    n = len(ref.sheet.cells)
    out: list = [[] for _ in range(n)]
    if ref.data is None:
        return out
    for p in sp.list_poses(ref.data):
        if not 0 <= p.index < n:
            continue
        for i in range(p.first, p.first + p.count):
            s = ref.data.slice(i)
            if s is not None:
                out[p.index].append([s.pts[0], s.pts[1], s.w, s.h])
    return out


class _SceneSheets:
    """The scene's sheets, one per (sprite data, palette row, party, black)."""

    def __init__(self, mf: MapField):
        self.mf = mf
        self.out: list[dict] = []
        self._ix: dict = {}

    def get(self, number: int, row: int, party: bool = False, black: bool = False):
        """-> (scene sheet index or None, SheetRef or None)."""
        key = (number, row, party, black)
        if key not in self._ix:
            ref = self.mf.sheets.get(number, row, party=party)
            ix = None
            if ref is not None and ref.sheet is not None:
                sh = ref.sheet
                img = sh.image
                if black:
                    img = Image.new("RGBA", sh.image.size, (0, 0, 0, 255))
                    img.putalpha(sh.image.getchannel("A"))
                self.out.append({
                    "image": img, "cell_w": sh.cell_w, "cell_h": sh.cell_h,
                    "anchor_x": sh.anchor_x, "anchor_y": sh.anchor_y,
                    "columns": sh.columns, "poses": len(sh.cells),
                    "label": ref.label + (" · drawn black" if black else ""),
                    "anims": [], "pieces": _pose_pieces_all(ref),
                    "drawn": [c is not None for c in sh.cells]})
                ix = len(self.out) - 1
            self._ix[key] = (ix, ref)
        return self._ix[key]


def _drawn_pose(sheet: dict | None, ref: SheetRef | None, anim) -> int:
    pose = ref.table.pose(anim.step) if ref is not None and anim is not None else None
    if sheet is None or pose is None or not 0 <= pose < sheet["poses"] \
            or not sheet["drawn"][pose]:
        return -1
    return pose


def played(fm: FieldMaps, map_id: int, ticks: int = LOOP_TICKS) -> Played | None:
    """The map as MapChange leaves it with the first spot its entries put
    the party on, then `ticks` field frames (formats.field_motion)."""
    from decoders.plugins.SLUS_006_28.formats import command_list as cl
    from decoders.plugins.SLUS_006_28.formats import field_motion as fmo
    from decoders.plugins.SLUS_006_28.formats import field_objects as fo
    from decoders.plugins.SLUS_006_28.formats import field_picture as fp
    from decoders.plugins.SLUS_006_28.formats import inflate16
    from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
    mf = fm.map_field(map_id)
    if mf is None:
        return None
    m = fm.maps[map_id]
    area = m.area
    raw = fm.read(m.resource)
    notes: list[str] = []
    mf.leads = mf.leads[:1]
    ld = mf.leads[0] if mf.leads else None
    still = fp.compose(mf.ground, sprites_of(mf))

    sheets = _SceneSheets(mf)
    actors: list[dict] = []
    probes: list = []
    table: list[dict] = []             # the Objects panel: one row per record

    def add(ix, ref, slot, group, label, note, state, twin=False, semi=False, depth=None):
        """-> the actor's index, or None when its sheet draws nothing."""
        if ix is None:
            return None
        sheet = sheets.out[ix]
        first = state()
        actors.append({"sheet": ix, "x": first[0], "y": first[1], "mirror": False,
                       "anim": 0, "label": label, "note": note, "group": group,
                       "twin": twin, "queue": fp.queue_of(slot), "semi": semi,
                       "depth": depth, "track": None})
        probes.append((actors[-1], fmo.Track(), state, sheet))
        return len(actors) - 1

    lead = None
    if ld is not None:
        draw = mos.record_draw(ld.kind, 0)
        ix, ref = sheets.get(ld.sprite_data, draw.palette_row, party=True)
        lead = fmo.Lead(x=ld.x, depth=ld.depth, box=fo.party_box(area.party_kind),
                        anim=ld.anim, table=mf.sheets.table(ld.sprite_data, party=True),
                        twin_anim=ld.twin_anim,
                        twin_table=(mf.sheets.table(ld.twin_data, party=True)
                                    if ld.twin_anim is not None else None))
        sh = sheets.out[ix] if ix is not None else None
        body = add(ix, ref, 0, PARTY, "the party", f"party place 0 · {ld.entry.source}",
                   lambda sh=sh, ref=ref: (ld.x, ld.y, _drawn_pose(sh, ref, ld.anim), ld.klass),
                   depth=ld.depth)
        table.append({"actor": body, "row": None, "def": None, "kind": None, "name": "the party",
                      "group": GROUP_SHORT[PARTY], "data": ld.sprite_data,
                      "x": ld.x, "y": ld.y, "facing": ld.facing, "think": None,
                      "how": f"party place 0 · {ld.entry.source}", "klass": ld.klass,
                      "out": None, "open": None})
        if ld.twin_anim is not None:
            tix, tref = sheets.get(ld.twin_data, mos.record_draw(1, 0).palette_row, party=True)
            tsh = sheets.out[tix] if tix is not None else None
            add(tix, tref, 0x46, PARTY, "", "the party's twin: its ground shadow",
                lambda tsh=tsh, tref=tref: (ld.x, ld.depth,
                                            _drawn_pose(tsh, tref, ld.twin_anim), ld.klass),
                twin=True)

    rows: list = []
    if lead is not None and mf.objects:
        numbers = {o.sprite_data for o in mf.objects}
        numbers |= {o.twin_data for o in mf.objects if o.twin_anim is not None}
        rows = fmo.field_rows(mf.objects, {n: mf.sheets.table(n) for n in numbers})
    twins = 0
    for r in rows:
        o = r.obj
        draw = mos.record_draw(o.kind, o.mode)
        black = bool(draw.attr & 0x8000)
        ix, ref = sheets.get(o.sprite_data, draw.palette_row, black=black)
        sh = sheets.out[ix] if ix is not None else None
        number = o.think & 0x3F
        if o.kind == fo.CHEST_KIND:
            how = "a chest: never thinks"
        elif number in (3, 4):
            how = f"number {number}: never thinks"
        else:
            how = fmo.THINK_NAMES.get(number, f"number {number}: not transcribed here")
        if number == 6 and o.kind != fo.CHEST_KIND:
            how += f", look {o.look & 0x7F}"
        d = o.definition
        name = object_name(o.kind, d.index)
        body = add(ix, ref, 0x10 + o.row, group_of(o.kind), name,
                   f"{name} · object row {o.row} · object kind {o.kind} · think {o.think:#04x}, "
                   f"{how} · sprite data {o.sprite_data:#04x}",
                   lambda o=o, sh=sh, ref=ref: (o.x, o.y, _drawn_pose(sh, ref, o.anim)
                                                if o.kind else -1, o.klass),
                   semi=draw.semi)
        gone, opened = fo.story_flag(d, map_id), fo.chest_flag(d, map_id)
        table.append({"actor": body, "row": o.row, "def": d.index, "kind": o.kind, "name": name,
                      "group": GROUP_SHORT[group_of(o.kind)], "data": o.sprite_data,
                      "x": o.x, "y": o.y, "facing": o.facing, "think": o.think, "how": how,
                      "klass": o.klass, "out": gone, "open": opened,
                      "ref": object_ref(o.kind, mf.object_set, d.index)})
        if body is not None:
            actors[body]["out"] = gone
            if opened is not None and ref is not None:
                # MapObjectInit (0x800656CC): a chest whose bit is set turns
                # 4 facings back, which its sheet draws open
                st = fo.AnimState()
                fo.pose_set(st, ref.table, o.group, (o.facing - fo.CHEST_OPEN_TURN) & 0xFF)
                actors[body]["open"] = [opened, _drawn_pose(sh, ref, st)]
        if o.twin_anim is not None:
            tix, tref = sheets.get(o.twin_data, draw.palette_row, black=black)
            tsh = sheets.out[tix] if tix is not None else None
            tw = add(tix, tref, 0x56 + twins, group_of(o.kind), "",
                     f"{name}'s twin: its ground shadow",
                     lambda o=o, tsh=tsh, tref=tref: (o.x, o.y, _drawn_pose(tsh, tref, o.twin_anim)
                                                      if o.kind else -1, fp.CLASS_UNDER),
                     twin=True, semi=draw.semi)
            if tw is not None:
                actors[tw]["out"] = gone
            twins += 1

    tiles = fmo.tile_animations(fm.image, area.tile_animation)
    seeds = [{"delay": t.delay, "frames": t.frames, "count": t.count, "tile": t.tile,
              "source": t.source} for t in tiles]
    tile_images = b""
    if tiles:
        c = cl.effective(raw, cl.TILE_ANIMATION)
        if c is None:
            notes.append(f"tile animation set {area.tile_animation} names tiles, but the "
                         f"map's resource holds no type-16 images: not played")
            seeds = []
        else:
            tile_images = inflate16.decompress(c.payload)

    palette = None
    if area.palette_animation:
        try:
            palette = palette_data(fm, area.palette_animation)
        except (ValueError, LookupError) as ex:
            notes.append(f"palette animation set {area.palette_animation} not played: {ex}")
        if palette is not None and len(mf.ground.rows) < 2:
            notes.append(f"palette animation set {area.palette_animation} changes row 501, "
                         f"which this map's palette does not store: nothing drawn changes")
            palette = None

    try:
        reach = reach_data(fm, map_id, still)
    except Exception as ex:
        notes.append(f"the In game view could not be worked out: {ex}")
        reach = None

    block = mf.sheets.object_set.definitions if mf.sheets.object_set is not None else b""
    f = fmo.Field(rows, lead, mf.att, fm.tables, block,
                  limits=[e.limit_rect for e in fm.entries.get(map_id, [])], tiles=tiles)
    starts = [(r.obj.x, r.obj.y) for r in rows]
    for k in range(ticks + 1):
        for _a, tr, state, _sh in probes:
            tr.add(k, state())
        if k < ticks:
            f.tick()
    for a, tr, _state, _sh in probes:
        a["track"] = [list(p) for p in tr.points]

    scene = {
        "w": fp.PLANE, "h": fp.PLANE, "background": None,
        "sheets": sheets.out, "actors": actors, "depth": "field", "labels": False,
        "tick_hz": TICK_HZ, "tick_note": TICK_NOTE,
        "field": {
            "ticks": ticks,
            "ground": ground_data(mf.ground, raw, area.party_kind, seeds, tile_images,
                                  palette),
            "groups": [[g, GROUP_SHORT[g]] for g in GROUPS
                       if any(a["group"] == g for a in actors)],
            "objects": table,
            "story": story(fm, map_id, raw, mf.att.plane, actors),
            "reach": reach,
        },
    }
    stuck: dict = {}
    for r in rows:
        if r.stuck:
            stuck.setdefault(r.stuck, []).append(r.obj.row)
    moved = sum(1 for r, at in zip(rows, starts) if (r.obj.x, r.obj.y) != at)
    return Played(mf=mf, lead=ld, ticks=ticks, scene=scene, still=still, tiles=tiles,
                  tile_cells=_tile_cells(mf.ground, seeds), stuck=stuck,
                  moved=moved, draws=f.rng.draws, notes=notes)


def story(fm: FieldMaps, map_id: int, raw: bytes, att_plane: list, actors: list) -> dict:
    """What the map's story bits change, and its other bg changes
    (formats.bg_change): each row with the cells it copies from, how it
    starts (a story bit's state; a door, started by a kind-3 cell; any
    other, started by a script or never), and each bit with the rows it
    leaves copied, the actors it leaves out (MapObjectsInit (0x800655C8))
    and the chests it shows open, and the other maps whose rows use it."""
    from decoders.plugins.SLUS_006_28.formats import bg_change as bc
    from viewer_tabs.refs import ref
    rows = bc.map_changes(raw)
    trig = bc.trigger_cells(att_plane)
    out_rows = []
    bits: dict[int, dict] = {}

    def bit(b):
        return bits.setdefault(b, {"bit": b, "rows": [], "hides": [], "opens": [], "maps": [],
                                   "ref": ref("story-flag", b).json()})
    for r in rows:
        out_rows.append({"id": r.id, "ref": ref("tile-change", map_id, r.id).json(),
                         "x": r.x, "y": r.y, "w": r.w, "h": r.h, "bit": r.bit,
                         "frames": r.frames, "sound": r.sound,
                         "sources": [list(src) for src in r.sources],
                         "kind": "state" if r.bit else "door" if r.id in trig else "other",
                         "triggers": [[x * 8, y * 8] for x, y in trig.get(r.id, [])]})
        if r.bit:
            bit(r.bit)["rows"].append(r.id)
    for i, a in enumerate(actors):
        if a.get("out") is not None and not a["twin"]:
            bit(a["out"])["hides"].append(i)
        if a.get("open"):
            bit(a["open"][0])["opens"].append(i)
    shared = fm.bg_bit_maps()
    for b in bits.values():
        b["maps"] = [[m, fm.names.location(fm.maps[m].area.location) or f"map {m}"]
                     for m in shared.get(b["bit"], []) if m != map_id]
    return {"rows": out_rows, "bits": [bits[b] for b in sorted(bits)]}


def _tile_cells(g, seeds: list[dict]) -> int:
    """Map cells whose tile one of the records loads new texels into."""
    from decoders.plugins.SLUS_006_28.formats import field_motion as fmo
    from decoders.plugins.SLUS_006_28.formats import world_map as wm
    places = {fmo.tile_place(s["tile"] + j) for s in seeds for j in range(s["count"])}
    return sum(1 for row in g.plane for v in row
               if (lambda t: (t.page, t.u, t.v))(wm.decode_tile(v)) in places)


def palette_data(fm: FieldMaps, set_id: int) -> dict | None:
    """Palette animation set `set_id` as the client steps it
    (formats.palette_animation; app lib/game/paletteAnimation.ts): the
    slots in order, each mode-1 slot with its strip's words, and the
    row-508 copy. None for set 0 or a set that starts no slot."""
    from decoders.plugins.SLUS_006_28.formats import palette_animation as pa
    from decoders.plugins.SLUS_006_28.formats import system_dat as sd
    slots = pa.animations(fm.image, set_id)
    if not slots:
        return None
    pa.with_strips(slots, fm.strip_block(), sd.block_places(fm.image)[0])
    copy = pa.copy_range(fm.image, set_id)
    return {"set": set_id,
            "slots": [{"mode": a.mode, "delay": a.delay, "frames": a.frames, "first": a.first,
                       "count": a.count, "strip": list(a.strip)} for a in slots],
            "copy": list(copy) if copy else None}


#: The mask's pixel, in map pixels: every edge the walk finds is even
#: (spots on a 2-px lattice, limits in 8-px cells).
REACH_SCALE = 2
#: A doubtful move (FieldMaps.reach_inputs) counts on a map where the lead
#: can stand on its spot and this much of its first screen is drawn: a
#: pixel brighter than DRAWN_LEVEL in its brightest channel.
DRAWN_SHARE = 0.75
DRAWN_LEVEL = 24


def reach_data(fm: FieldMaps, map_id: int, picture: Image.Image | None = None) -> dict | None:
    """The In game view (formats.map_reach): what a player can see of the
    map, as a mask -- black where the camera never shows, clear where it
    does, a pixel per REACH_SCALE map pixels -- with the box round what it
    shows and how it was found. None when no way in reaches the map.

    `picture`, the map as drawn, weighs the doubtful moves: one whose
    first screen here is mostly empty is taken for another map's; without
    it they are all left out."""
    from decoders.plugins.SLUS_006_28.formats import map_reach as mr
    inp = fm.reach_inputs(map_id)
    starts, skipped = list(inp.starts), []
    if inp.doubtful:
        drawn = (np.asarray(picture.convert("RGB")).max(axis=2) > DRAWN_LEVEL
                 if picture is not None else None)
        free = mr.free_mask(np.array(inp.planes[0], dtype=np.int32), mr.party_box(inp.party_kind))
        for st in inp.doubtful:
            left, top, right, bottom = mr.view(st.x, st.y, st.limits)
            on = (drawn is not None and 0 <= st.x < mr.PLANE and 0 <= st.y < mr.PLANE
                  and free[st.y // mr.LATTICE, st.x // mr.LATTICE]
                  and right > left and bottom > top
                  and drawn[top:bottom, left:right].mean() >= DRAWN_SHARE)
            (starts if on else skipped).append(st)
    if not starts:
        return None
    r = mr.reach(inp.planes, inp.party_kind, starts, inp.acts, inp.places)
    if r.bbox is None:
        return None
    hidden = np.where(r.seen[::REACH_SCALE, ::REACH_SCALE], 0, 255).astype(np.uint8)
    black = Image.new("L", (hidden.shape[1], hidden.shape[0]), 0)
    mask = Image.merge("RGBA", (black, black, black, Image.fromarray(hidden, "L")))
    return {"mask": mask, "scale": REACH_SCALE, "bbox": list(r.bbox),
            "areas": [list(a) for a in r.areas], "ways": len(starts), "walked": len(r.starts), "spots": r.spots,
            "blocked": len(r.blocked), "skipped": len(skipped),
            "labels": sum(v == mr.GONE for v in inp.acts.values()), "label_count": len(inp.acts),
            "planes": len(inp.planes), "seen": float(r.seen.mean())}


def ground_data(g, raw: bytes, party_kind: int, seeds: list[dict],
                tile_images: bytes, palette: dict | None = None) -> dict:
    """What the client draws the map's ground from, as the game draws it:
    the tile words, the 8-bit pages, the CLUT rows as colour words, the
    tile animations' records and images, the second layer as row-508
    indexes with that row's colours, and the palette animation (app
    lib/game/ground.ts). The bytes travel as one blob, `parts` naming
    where each lies in it."""
    import struct
    from decoders.plugins.SLUS_006_28.formats import world_map as wm
    pal = wm.palettes(raw).get(wm.TILE_CLUT_PALETTE) or b""
    blob = bytearray()
    parts: dict = {}

    def put(name, data: bytes):
        parts[name] = [len(blob), len(data)]
        blob.extend(data)
    put("words", b"".join(struct.pack(f"<{len(row)}H", *row) for row in g.plane))
    pages = []
    for p in sorted(g.pages):
        if p not in wm.PAGE_SIZE:
            continue
        w, h = wm.PAGE_SIZE[p]
        data = bytes(g.pages[p][:w * h]).ljust(w * h, b"\0")
        put(f"page{p}", data)
        pages.append({"page": p, "w": w, "h": h, "part": f"page{p}"})
    put("tileImages", tile_images)
    layer2 = None
    if g.under is not None and g.layer2_indexes is not None:
        put("layer2", g.layer2_indexes)
        layer2 = {"part": "layer2", "w": wm.LAYER2_COLS * wm.LAYER2_CELL_PX,
                  "h": wm.LAYER2_ROWS * wm.LAYER2_CELL_PX,
                  "row": [c for clut in wm.layer2_cluts(g.rows[1]) for c in clut]}
    return {
        "blob": bytes(blob), "parts": parts, "pages": pages,
        "columns": len(g.plane[0]) if g.plane else 0,
        "rows": [list(r) for r in g.rows],
        "cover": [list(r) for r in wm.overlay_clut_words(pal, wm.overlay_keep_from(party_kind))]
        if pal else [],
        "blend": g.under is not None,
        "layer2": layer2,
        "tiles": seeds,
        "palette": palette,
    }


# ---------------------------------------------------------------------------
# the Tileset view: the pages the map loads
# ---------------------------------------------------------------------------

def tileset(raw: bytes) -> list[dict]:
    """The map's texture pages (resource_tpage_load (0x8002097C)), each
    through the CLUTs that draw it: pages 0 to 2 are 256 x 256 8-bit tile
    pages bg_first_draw (0x80014058) draws through VRAM row 500, or 501 for
    a word with bit 12 set; page 3 is the second layer's sheet, 256 x 128
    4-bit texels bg_second_draw (0x800148E0) reads through row 508's
    sixteen CLUTs (palette_bg_second_row_set (0x80020670)), the most used
    first. Each CLUT says how many of the map's cells take it."""
    from decoders.plugins.SLUS_006_28.formats import world_map as wm
    from decoders.psx.formats.renderer import render_indexed_layer
    pages = wm.pages(raw)
    pal = wm.palettes(raw).get(wm.TILE_CLUT_PALETTE)
    out = []
    uses: dict = {}
    lay = wm.layout(raw)
    if lay is not None:
        for line in wm.tile_plane(lay):
            for value in line:
                t = wm.decode_tile(value)
                uses[(t.page, t.clut)] = uses.get((t.page, t.clut), 0) + 1
    for page in sorted(p for p in pages if p in wm.PAGE_SIZE):
        data = pages[page]
        notes: list[str] = []
        rows = []
        if page != wm.LAYER2_PAGE:
            w, h = wm.PAGE_SIZE[page]
            words = wm.tile_clut_words(pal) if pal else []
            for i, row in enumerate(words):
                n = uses.get((page, i), 0)
                rows.append({"label": f"row {wm.TILE_CLUT_VRAM_ROWS[i]}",
                             "uses": n, "what": "tiles",
                             "image": render_indexed_layer(data, wm.words_rgba(row), w, h)})
            if pal and len(words) < wm.CLUT_ROWS:
                notes.append("the palette stores one row: row 501 is whatever the load "
                             "buffer held before, which is not read")
            out.append({"page": page, "label": f"Page {page}", "w": w, "h": h,
                        "rows": rows, "notes": notes})
            continue
        sheet = wm.layer2_sheet(data)
        cells = [0] * wm.LAYER2_CLUTS
        second = wm.second_layer(raw)
        if second is not None:
            for line in wm.layer2_cells(second):
                for d in wm.layer2_row_draws(line):
                    cells[d.cell.clut] += 1
        try:
            cluts = wm.layer2_clut_words(pal) if pal else []
        except ValueError:
            cluts = []
            notes.append(f"the palette stores one row: row {wm.LAYER2_CLUT_VRAM_ROW} is "
                         f"made of its second, which is not read")
        size = (wm.LAYER2_SHEET_W, wm.LAYER2_SHEET_H)
        for k in sorted(range(len(cluts)), key=lambda k: -cells[k]):
            rows.append({"label": f"CLUT {k}", "uses": cells[k], "what": "cells",
                         "image": render_indexed_layer(sheet, wm.words_rgba(cluts[k]), *size)})
        if not cluts:
            grey = [(v * 17, v * 17, v * 17, 255) for v in range(16)]
            rows.append({"label": "index values as grey", "uses": 0, "what": "cells",
                         "image": render_indexed_layer(sheet, grey, *size)})
        if not any(cells):
            notes.append("no cell of this map's second layer draws")
        out.append({"page": page, "label": "Back sheet", "w": size[0], "h": size[1],
                    "rows": rows, "notes": notes})
    return out

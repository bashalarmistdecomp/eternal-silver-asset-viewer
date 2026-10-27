"""Tab providers for the categorized asset viewer.

Each provider controls what items appear in the sidebar file list,
how selections are handled, and what gets rendered on the canvas. A
provider reads the disc when it is asked, through `ctx`.

Terminology:
  - Tileset / Texture Page: a 256x256 page of tile graphics a map loads
  - World Map / Area Map: the map's tile layout, placing those tiles
"""

from __future__ import annotations

import hashlib
import json
import struct
import weakref
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from PIL import Image

from decoders import config
from decoders.plugins import mangle
from decoders.plugins.SLUS_006_28.formats.lunadata import LunaDataArchive
from decoders.psx.gamedb.known_games import DISC_ID_LOOKUP
from decoders.plugins.SLUS_006_28.formats.system_dat import parse_system_dat, parse_open1_bin
from decoders.plugins.SLUS_006_28.records import programs
from viewer_tabs.identity import Identity, of_bytes, of_file, of_parts
from viewer_tabs.movie import MovieSource, raw_track
from viewer_tabs.model import GameModel
from viewer_tabs.names import GameNames, resource_source
from viewer_tabs.refs import ref
from viewer_tabs import system_font, whose
from viewer_tabs.score import ScoreSource

#: The program the LUNADATA-based tabs serve. Spelled once; tabs declare it
#: in `programs` and the registry at the bottom of this file does the rest.
SSSC = "SLUS_006.28"
#: The programs the SSSC tabs read: the US program and the Japanese
#: original, whose tables records.programs locates.
SSSC_JP = "SLPS_013.97"
SSSC_PROGRAMS = (SSSC, SSSC_JP)


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

@dataclass
class SelectResult:
    """Result of selecting an item in a tab."""
    images: list[Image.Image] = field(default_factory=list)
    info: str = ""
    summary: dict | None = None  # a box of facts: {title: str, fields: list[(label, value)]}
    text: str | None = None   # shown in a selectable text pane, not the canvas
    text_wrap: bool = True    # False for column-aligned text (tables)
    # `text` as Fan mode shows it, where that differs: no offsets or codes
    fan_text: str | None = None
    frames: list | None = None  # if set, the view cycles these as an animation
    # Playable/exportable payload: {"wav": bytes, "name": str} for a sample,
    # {"midi": bytes, "name": str} for a sequence. The view grows a transport
    # row when this is set; nothing else in the pipeline looks at it.
    audio: dict | None = None
    # An `arrangement.Arrangement`. Present only for timeline views: the app
    # draws its lanes, and a playhead that follows its tempo_ticks.
    timeline: Any = None
    # How fast to cycle `frames`, in milliseconds. None keeps the view's
    # default. Sprite poses have no inherent rate; a movie does, and playing
    # one at some other tab's cadence is just wrong.
    frame_interval_ms: int | None = None
    # Set when the item is a movie the app should PLAY rather than render
    # once: the app grows a transport and pulls the stream in chunks.
    movie: MovieSource | None = None
    # Set when the item is a score the app should play LIVE: the server
    # plays it a chunk at a time as the app asks (viewer_server.music), and
    # `audio` then has no "wav".
    music: ScoreSource | None = None
    # The two below are data the app draws itself; a waveform takes the
    # place of `images` (present() shows no layers beside one).
    #
    # {"lo": [...], "hi": [...], "seconds": float, "loop": float | None}
    # — a min/max envelope per column; `loop` is a fraction of the width.
    waveform: dict | None = None
    # {"columns": [...], "rows": [[str, ...], ...]} — a record table.
    table: dict | None = None
    # A page the app lays out itself (stage/SheetView): {"title",
    # "titleMono", "subtitle", "badges": [{text, tone, hint}], "sections":
    # [{title, aside, style ("facts": keys in words, values as data;
    # "glossary": keys as data, values in words; "prose": both in words),
    # fields: [[key, value, hint]], chips: [{label, on, why, icon}],
    # verdict: {text, tone}, hex: {offset, bytes (as hex)}, table:
    # {columns, rows, align ("left"/"right" per column)}, list: [str],
    # pictures: [{image (PIL), caption, ref}], note, cite, fanNote,
    # extended}]}. Every part but the titles is optional; tones are the
    # app's badge tones. Simple to complex (docs/taxonomy.md): a section's
    # `cite` (the function that proves it, where it is stored) shows by its
    # title in Advanced mode and goes to the folded extended info in Fan
    # mode; where its `note` cites the code, `fanNote` says it in plain
    # words for Fan mode ("" for nothing) and the note goes to the extended
    # info; an `extended` section is folded in Fan mode.
    sheet: dict | None = None
    # Actors the client animates itself from pose sheets + anim tables
    # (viewer_tabs/scene.py). Set `images` to scene.still() alongside it:
    # that is what PNG export writes.
    scene: dict | None = None
    # The thing shown (viewer_tabs.refs): a map, a battle, a song. Its
    # links (viewer_tabs.links) come with it, and the app opens its card.
    ref: Any = None
    # Its card laid out as the page (links.build_card's dict, without the
    # picture): a bromide's page is its card round its show.
    page: dict | None = None
    # A picture the screen looks down, a window of it a frame: {"image"
    # (PIL), "screen": (w, h), "hz", "rows": the picture's row the screen
    # begins at each frame, "dark": what the fade takes off each colour}.
    pan: dict | None = None


def proven_by_lines(producer: str) -> list[str]:
    """The CODE that proves an artifact's format: the functions whose reading
    established it (`inventory.Decoder.proven_by`), named as the decompiled
    program names them.

    Empty is the honest answer for a generic PlayStation decoder: a TIM is
    proven by the Sony format, not by any one program.
    """
    from decoders import inventory

    dec = inventory.get(producer)
    if dec is None or not dec.proven_by:
        return []
    out = ["proven by", "---------"]
    out += [f"  {name}" for name in dec.proven_by]
    if dec.spec:
        out.append(f"  written up in {dec.spec}")
    return out


def proven_by_section(producer: str) -> dict | None:
    """`proven_by_lines` as a sheet's section: the functions as a list,
    the write-up beside the heading. None when nothing proves it."""
    from decoders import inventory

    dec = inventory.get(producer)
    if dec is None or not dec.proven_by:
        return None
    return {"title": "Proven by", "aside": dec.spec or "",
            "list": list(dec.proven_by), "extended": True}


def no_names(ctx, what: str) -> str:
    """What a tab says when it has no names (GameNames.for_ctx gave None):
    `what` it finds through them, then why (GameNames.why_none)."""
    return f"{what}: {GameNames.why_none(ctx)}."


class TabProvider(Protocol):
    """Interface for tab content providers.

    A provider may also offer **views** — sub-tabs shown under the main tab
    bar, letting one asset be presented several ways without multiplying
    top-level tabs. Implement `get_views()` (return [] for none) and read
    `self.view` in `on_select`. The view name is set before every selection.

    `ctx` is the `DiscContext` for the disc on screen (viewer_tabs.context):
    its dump directory, its identity, its program's library folders and
    the plugin serving it. A provider must reach for the disc through `ctx`
    and never through a default serial — those two agree only while
    exactly one disc exists. `cache` is always an empty dict and `selected`
    None; no tab reads them.

    Scope is DECLARED, not discovered, with two optional class attributes
    the registry reads (see `applies_to` at the bottom of this file):

        programs   program serials this tab serves; empty = every program
        requires   filenames that must exist in the dump

    A tab that declares neither claims it can say something true about any
    PS1 disc, which is only honest for tabs built on decoders.psx.

    A game opens with all its discs, so a tab says how its items compare
    across them (viewer_tabs.identity): `item_identity(label, data, ctx)`
    per item, so discs whose copies match list its items once.

    A tab that is the home of a kind of thing (docs/taxonomy.md) says so in
    `homes`, kind -> the views it is listed in (`(None,)` for a tab without
    views), and answers `holds(data, ref, ctx)`: is this item that thing?
    A link's *Open in* finds its row that way (GameSession.locate).

    Fan mode speaks a fan's words (docs/taxonomy.md, "The rule"): a tab's
    `fan_about` says what it holds in them, where its docstring says how
    the viewer reads it; `fan_row(label, data, ctx)` words a row of its
    list for Fan mode ({"title", "sub"}, either left out to keep the row's
    own), and a result's `fan_text` is its `text` without the offsets.

    A disc's index (viewer_server.index) lists a tab without asking its
    provider; a selected item is read again from `get_items` first. A tab
    whose items are plain data (numbers and strings in tuples) and whose
    `on_select` reads what it needs itself, without its list having been
    made, says `selects_unlisted = True`: the index then holds its items,
    and they go to `on_select` as they are.
    """
    name: str
    #: the tab's stable key, which the app's rails and a link's home name
    key: str
    #: optional: the view Advanced mode opens the tab on (docs/taxonomy.md)
    technical_view: str
    supports_zoom: bool
    supports_grid: bool
    supports_layers: bool
    view: str
    programs: tuple[str, ...]
    requires: tuple[str, ...]

    def get_views(self) -> list[str]:
        ...

    def get_items(self, cache: dict, archive: LunaDataArchive | None,
                  ctx,
                  selected: set[str] | None) -> list[tuple[str, Any]]:
        ...

    def get_layer_options(self) -> list[str]:
        ...

    def on_select(self, item_data: Any,
                  cache: dict,
                  archive: LunaDataArchive | None,
                  ctx) -> SelectResult:
        ...


# ---------------------------------------------------------------------------
# Maps — one item per map: the map played, its objects, its tileset
# ---------------------------------------------------------------------------

class MapsProvider:
    """Every map the game can load, played as the field plays it, and
    named the way the game names it.

    The maps are the game's own map table: MapSeek (0x8006891C) finds a
    map's file through g_MapResourcePairs (0x800AF364) (map id -> resource,
    records.areas) — 97 maps, all one format (formats.world_map: texture
    pages, tile CLUTs and the type-5 layout, from the map's command list).
    The name is the location MapSet (0x80068780) sets on entry (the area
    record's byte 6, string 0x400 + id) and the music its byte 0xF —
    viewer_tabs.names. The list groups the maps by the area record's party
    kind, how the party walks them: the overworld (small sprites), towns
    (the party walks in a line) and dungeons (the lead walks alone).

    A map is shown as MapChange (0x8005922C) leaves it and then played on
    the field's clock (formats.field_motion): the object set the map's
    entries name makes its entities, map monsters and chests
    (MapObjectsInit (0x800655C8)), the party stands on the first spot those
    entries put it (MapPartySpotSet (0x80064B8C)), and every tick the
    objects think (MapObjectsThink (0x8006736C)) and animate and the tile
    animations step. Everything is drawn as the field draws it
    (formats.field_picture): by depth, the roofs over what stands under
    them, and the second layer behind the tiles where the game shows it
    there. The app draws the ground itself from the map's tile words,
    pages and CLUT rows, as bg_first_draw (0x80014058) does.

    Raw shows the whole plane, the areas the game never shows included (the
    copies a bg change takes its tiles from, rooms kept for scenes); In
    game blacks out all but what the camera can show, following the lead
    from every way into the map (formats.map_reach), so a town keeps its
    houses' rooms on the one screen. The toolbar shows or hides each layer
    (the second layer, the tiles, the roofs' copies, each group of
    objects, their row labels). Tileset shows
    the pages the map loads through each CLUT that draws them; Objects
    lists every record the set makes. The music button plays the map's
    song from its row in Music; Export saves pictures of the map: as
    shown, each camera area, its layers apart, its tileset.
    """

    name = "Maps"
    key = "maps"
    fan_about = """
    Every place the party walks: the overworld, the towns and the
    dungeons, each drawn as the game draws it, with the people, monsters
    and chests that stand there moving as they do in the game. Click
    someone or something to see who or what it is, and play the place's
    music from its button.
    """
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = True
    supports_grid = True
    supports_layers = True

    PRODUCER = "decoders.plugins.SLUS_006_28.formats.world_map"

    #: A map is its own row; a place is the first map listed that shows
    #: it; an entrance and a tile change are their map's; an object is the
    #: first map shown with its object set (links.world.home_map).
    homes = {k: (None,) for k in ("map", "place", "entrance", "tile-change", "entity",
                                  "trigger", "map-monster", "chest")}

    def __init__(self):
        self._layer_labels: list[str] = []

    @staticmethod
    def holds(m, r, ctx) -> bool:
        if r.kind == "place":
            return m.area.location == r.id[0]
        if r.kind in ("map", "entrance", "tile-change"):
            return m.map_id == r.id[0]
        from viewer_tabs.links import world
        return m.map_id == world.home_map(GameModel.for_ctx(ctx), r.id[0])

    def get_layer_labels(self):
        return list(self._layer_labels)

    def get_layer_options(self):
        return [str(i) for i in range(len(self._layer_labels))]

    def get_items(self, cache, archive, ctx, selected):
        names = GameNames.for_ctx(ctx)
        if names is None:
            return [(no_names(ctx, "The maps are found through the program's tables"), None)]
        from viewer_tabs.field_view import DEBUG_ROOM, MAP_TYPES
        order = list(MAP_TYPES)
        # the debug room last of its kind's maps
        maps = sorted(names.maps(), key=lambda m: (
            order.index(m.area.party_kind) if m.area.party_kind in order else len(order),
            m.area.party_kind, m.map_id == DEBUG_ROOM, m.map_id))
        return [(self._label(names, m), m) for m in maps]

    @staticmethod
    def _label(names: GameNames, m) -> str:
        place = names.location(m.area.location) or f"place {m.area.location}"
        music = names.bgm(m.area.bgm)
        return f"{place}  map {m.map_id}" + (f"  {music}" if music else "")

    def item_identity(self, label, m, ctx) -> Identity:
        """A map by its map id: its file as the code reads it, its area
        record, and what the field places on it and draws it with
        (field_view.FieldMaps.sources)."""
        names = GameNames.for_ctx(ctx)

        def parts():
            yield names.resource_source(m.resource)
            yield m.area.raw
            try:
                yield from self._field_maps(ctx).sources(m.map_id)
            except Exception as ex:
                yield f"unreadable: {ex}".encode()
        return of_parts(f"map {m.map_id:#04x}", parts)

    @staticmethod
    def _archive_name(archive, resource) -> str | None:
        """The archive entry starting at the resource's sector — the same
        bytes, so an exact identity, not a name guess."""
        if archive is None or resource is None:
            return None
        for e in archive.toc_entries:
            if e.sector == resource.start_sector:
                return e.name
        return None

    @staticmethod
    def _field_maps(ctx):
        """The disc's maps, read once for every tab (viewer_tabs.model)."""
        return GameModel.for_ctx(ctx).field

    def on_select(self, m, cache, archive, ctx):
        from viewer_tabs import field_view as fv
        self._layer_labels = []
        if m is None:
            return SelectResult(info="No maps available")
        names = GameNames.for_ctx(ctx)
        try:
            fm = self._field_maps(ctx)
            p = fv.played(fm, m.map_id)
            raw = names.read_resource(m.resource)
            pages = fv.tileset(raw)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return SelectResult(info=f"Could not play map {m.map_id}: {type(e).__name__}: {e}")
        if p is None:
            return SelectResult(info=f"map {m.map_id}: no layout command")
        images = [p.still]
        self._layer_labels = ["the map at tick 0"]
        shown = []
        for page in pages:
            rows = []
            for r in page["rows"]:
                rows.append({"label": r["label"], "uses": r["uses"], "what": r["what"],
                             "layer": len(images)})
                images.append(r["image"])
                self._layer_labels.append(f"{page['label'].lower()} · {r['label']}")
            shown.append({"page": page["page"], "label": page["label"], "w": page["w"],
                          "h": page["h"], "rows": rows, "notes": page["notes"]})
        p.scene["field"]["tileset"] = shown
        return SelectResult(images=images, scene=p.scene, ref=ref("map", m.map_id),
                            info="\n".join(self._info(m, names, archive, fm, p, raw)))

    def _info(self, m, names, archive, fm, p, raw) -> list[str]:
        from viewer_tabs import field_view as fv
        mf, a = p.mf, m.area
        place = names.location(a.location)
        short = names.location_short(a.location)
        music = names.bgm(a.bgm)
        archive_name = self._archive_name(archive, names.resource_entry(m.resource))
        header_id = raw[19] if len(raw) > 19 else None
        lead = names.character(fv.LEAD) or f"party id {fv.LEAD}"
        info = [
            place or f"place {a.location}",
            f"map {m.map_id} ({m.map_id:#04x})" + ("" if header_id == m.map_id
                                                 else f"  (! header byte 19 says {header_id})"),
            f"place {a.location} ({a.location:#04x}), string {a.location + 0x400:#05x}"
            + (f" (memory card: {short})" if short else ""),
            f"song {a.bgm}" + (f", {music}" if music else ""),
            f"party kind: {a.party_kind} (record {a.record}, byte 0)"
            + (f": {fv.MAP_TYPES[a.party_kind].lower()}, "
               f"{fv.MAP_TYPE_NOTES[a.party_kind].split(': ', 1)[1]}"
               if a.party_kind in fv.MAP_TYPES else ""),
            f"resource: {m.resource:#x}" + (f" ({archive_name})" if archive_name else ""),
            f"object set {mf.object_set} ({mf.object_set:#04x}), {len(mf.objects)} rows, named by "
            f"{len(mf.entries)} of the entrances into this map" if mf.object_set
            else "object set: none; no entrance into this map names a set other than 0",
        ]
        for s_, es_ in sorted(mf.other_sets.items()):
            what = "no objects" if s_ == 0 else "not shown"
            info.append(f"  object set {s_} too: {len(es_)} entrance{'' if len(es_) == 1 else 's'} "
                        f"({what})")
        if p.lead is not None:
            info.append(f"the party: {lead} at ({p.lead.x}, {p.lead.y}), the first spot "
                        f"the entries with this set put it ({p.lead.entry.source})")
        else:
            info.append("the party: no entry puts it on this map")
        if p.tiles:
            info.append(f"tile animation: set {a.tile_animation}, {len(p.tiles)} record"
                        f"{'s' if len(p.tiles) != 1 else ''}, {p.tile_cells} map cells "
                        f"(tile_animation_step (0x80026690))")
        elif a.tile_animation:
            info.append(f"tile animation: set {a.tile_animation} has no record of mode 1, "
                        f"the one tile_animation_step (0x80026690) loads tiles for")
        else:
            info.append("tile animation: none (area record byte 4 is 0)")
        played = p.scene["field"]["ground"]["palette"]
        if a.palette_animation and played:
            import math
            from decoders.plugins.SLUS_006_28.formats import palette_animation as pa
            slots = pa.animations(fm.image, a.palette_animation)
            delays = sorted({max(x.delay, 1) for x in slots})
            every = (f"{delays[0]}" if len(delays) == 1 else f"{delays[0]} to {delays[-1]}")
            copy = played["copy"]
            info.append(f"palette animation: set {a.palette_animation}, {len(slots)} slot"
                        f"{'s' if len(slots) != 1 else ''}; colours of row 501 change every "
                        f"{every} frames and come round every "
                        f"{math.lcm(*(x.period for x in slots))} (palette_animation_step "
                        f"(0x800263F4))"
                        + (f"; CLUT{'s' if copy[1] != 1 else ''} {copy[0]}"
                           + (f"..{copy[0] + copy[1] - 1}" if copy[1] != 1 else "")
                           + " copied to the second layer's row 508" if copy else "")
                        + "; the roofs' copies keep the colours the map loads with (rows "
                          "510 / 511 are never sent again)")
        elif a.palette_animation:
            info.append(f"palette animation: set {a.palette_animation}, not played (the notes "
                        f"say why)")
        else:
            info.append("palette animation: none (area record byte 5 is 0)")
        rows = p.scene["field"]["story"]["rows"]
        if rows:
            kinds = {k: sum(r["kind"] == k for r in rows) for k in ("state", "door", "other")}
            info.append(f"bg changes: {len(rows)} row{'s' if len(rows) != 1 else ''}: "
                        f"{kinds['state']} kept by a story bit, {kinds['door']} started "
                        f"by a step, {kinds['other']} by a script or nothing found "
                        f"(MapBgChangeStoryBitsCopy (0x80059B6C))")
        else:
            info.append("bg changes: none")
        reach = p.scene["field"].get("reach")
        if reach:
            x0, y0, x1, y1 = reach["bbox"]
            info.append(
                f"in game: {reach['seen']:.0%} of the plane, inside ({x0}, {y0})-({x1}, {y1}); "
                f"the lead walked from {reach['walked']} spots ({reach['ways']} ways in and "
                f"moves, the rest reached by a step on a move cell) on {reach['planes']} "
                f"attribute plane{'s' if reach['planes'] != 1 else ''}, {reach['spots']} spots "
                f"in all (MapAttributeFreeCheck (0x800692D4)); the camera follows him "
                f"(MapViewGoalGet (0x80069080))"
                + (f"; {reach['labels']} of the {reach['label_count']} labels its step "
                   f"cells run take the party away" if reach['label_count'] else "")
                + (f"; {reach['blocked']} way{'s' if reach['blocked'] != 1 else ''} in "
                   f"stand{'s' if reach['blocked'] == 1 else ''} where the lead cannot step"
                   if reach['blocked'] else "")
                + (f"; {reach['skipped']} move{'s' if reach['skipped'] != 1 else ''} of the "
                   f"script, which other maps load too, left out: no other way in has "
                   f"{'their' if reach['skipped'] != 1 else 'its'} limits, and here "
                   f"{'their' if reach['skipped'] != 1 else 'its'} first screen is mostly "
                   f"empty or the lead cannot stand there" if reach['skipped'] else ""))
        else:
            info.append("in game: no way in reaches this map; the In game view shows it raw")
        info += [
            f"loop: {p.ticks} field frames ({p.ticks / fv.TICK_HZ:.0f} s at "
            f"{fv.TICK_HZ} a second), then from tick 0 again",
            f"moved: {p.moved} of {len(mf.objects)} rows left their first spot; "
            f"{p.draws} random draws",
        ]
        for why, rows in sorted(p.stuck.items()):
            info.append(f"! rows {', '.join(map(str, rows))} stop thinking: {why}")
        info += [f"! {note}" for note in mf.notes + p.notes + fm.errors]
        info += [
            "The map opens with every story bit clear: an object a bit leaves out is "
            "there, chests are closed and no change is copied in. The Story bits panel "
            "sets them: the objects go, the chests open and the changes are copied as "
            "MapBgChangeStoryBitsCopy (0x80059B6C) copies them on a load. Paths are "
            "played with every bit clear.",
            "The party stands: it never sees an enemy and is never touched "
            "(MapObjectPartySeenCheck (0x8007A58C), MapObjectTouchFind (0x8007AB64)).",
            "Every row thinks and is drawn as if the camera were on it: MapObjectsThink "
            "(0x8006736C) passes over rows away from the view, and MapObjectsAnimationStep "
            "(0x80065FD8) draws at most 0x20 rows and 0x10 twins.",
            "In game: the camera follows the lead from every entry into the map and "
            "every 0x27 move of its script, inside each one's limits, and walks him "
            "by the field's box test and step cells, on the map as it loads and with "
            "every bg change copied in. A scene's own camera moves are not followed; "
            "the debug room's scripts are left out.",
            "View limits: each row takes the first entry rectangle into this map it "
            "stands in (g_MapLimitLeft..Bottom as MapChange (0x8005922C) sets them), "
            "else the whole plane.",
            "Random draws: rng_draw (0x8001C770) as system_init (0x8001EEB8) seeds it "
            "(0x3039), think phase 0; in the game the draws before the map change the "
            "wanderers' paths.",
            "source: lunadata + the program's tables",
            "names: MapSet (0x80068780)'s area record (records.areas)",
        ]
        return info


# ---------------------------------------------------------------------------
# UI — the UI's files: SYSTEM.DAT, STFIELD.DAT, OPEN1.BIN, MENU.BIN
# ---------------------------------------------------------------------------

class UIItem(NamedTuple):
    """One UI tab item: its pictures, what each is, and what the file is;
    `key` and `source` are its identity (MenusProvider.item_identity)."""
    images: list
    labels: list
    info: str
    text: str | None = None
    key: str = ""
    source: tuple = ()


class MenusProvider:
    """The UI's files, each read the way the game reads it.

    An item is a picture with its layers, each layer named (for a 4-bit
    picture, the sub-palette it is drawn with); the layer names follow the
    selection.
    """

    name = "Menus"
    key = "menus"
    fan_about = """
    The menus' own graphics: the letters they print with, the icons they
    draw for items, spells and commands, the title screen's pictures, and
    the cursors and marks of the menus, the shops and the battles.
    """
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = True
    supports_grid = True
    supports_layers = True

    def __init__(self):
        self._items: list[tuple[str, Any]] | None = None
        self._labels: list[str] = []
        self._places: tuple[int, int] | None = None

    def get_items(self, cache, archive, ctx, selected):
        if not archive:
            return []
        if self._items is None:
            self._items = self._build(archive, ctx)
        return self._items

    def item_identity(self, label, item, ctx) -> Identity:
        """An entry by the file and the number the game reads it by (a
        glyph sheet, an icon number, a bank), compared by the bytes it is
        drawn from."""
        return of_parts(item.key or label, lambda: item.source)

    #: Fan mode's words for an entry, by its key: what the code draws it
    #: for (system_dat, stfield.USES, docs/spec/overview.md's resource 3).
    FAN_WORDS = {
        "SYSTEM.DAT glyph atlas": ("The menus' letters", "what the menus print with"),
        "SYSTEM.DAT icons": ("The icons", None),
        "STFIELD.DAT sheet": ("Cursors and marks", "the sheet they are all drawn from"),
        "STFIELD.DAT bank 0": ("Menu cursors and marks",
                               "the menus', the shops' and the message window's"),
        "STFIELD.DAT bank 1": ("Chests", "and the other things to examine on the maps"),
        "STFIELD.DAT bank 2": ("Battle marks", "the target mark and a hit's impact"),
        "MENU.BIN": ("The movie player", "the code that plays the movies: no picture"),
    }

    def fan_row(self, label, item, ctx) -> dict | None:
        """An entry in Fan mode: what it is, not the file it is in; an
        icon by its name, its number under it."""
        if item is None:
            return None
        if item.key in self.FAN_WORDS:
            title, sub = self.FAN_WORDS[item.key]
            if item.key == "SYSTEM.DAT icons":
                sub = f"{label.split()[-1]} icons the menus draw"
            return {"title": title, **({"sub": sub} if sub else {})}
        if item.key.startswith("OPEN1.BIN "):
            return {"title": "The title screen", "sub": f"picture {int(item.key.split()[1]) + 1}"}
        if item.key.startswith("icon "):
            n = int(item.key.split()[1], 16)
            name = label.strip().split("  ", 1)[1].strip() if "  " in label.strip() else ""
            if n == 0 or name in ("", "no string"):
                return {"sub": "never drawn" if n == 0 else "no name in the string table"}
            return {"title": name, "sub": f"icon {n}"}
        return None

    def get_layer_options(self):
        return [str(i) for i in range(len(self._labels))]

    def get_layer_labels(self):
        return list(self._labels)

    def on_select(self, item, cache, archive, ctx):
        if item is None:
            self._labels = []
            return SelectResult(info="Nothing to show")
        self._labels = [label or f"Layer {i}" for i, label in
                        enumerate(list(item.labels) + [""] * (len(item.images) - len(item.labels)))]
        return SelectResult(images=list(item.images), info=item.info,
                            text=item.text, text_wrap=item.text is None)

    def _build(self, archive, ctx) -> list[tuple[str, Any]]:
        items: list[tuple[str, Any]] = []
        entries = {e.name: e for e in archive.toc_entries}

        if "SYSTEM.DAT" in entries:
            from decoders.plugins.SLUS_006_28.formats.system_dat import block_places
            raw = archive.extract(entries["SYSTEM.DAT"])
            names = GameNames.for_ctx(ctx)
            self._places = block_places(names.binary.code) if names else None
            asset = (parse_system_dat(raw, places=self._places) if self._places
                     else parse_system_dat(raw))
            if asset.layers:
                from decoders.plugins.SLUS_006_28.formats import command_list as cl
                atlas = tuple(struct.pack("<I", c.word) + c.payload for c in cl.commands(raw)
                              if c.type in (cl.TIM, cl.PALETTE_ROW))
                items.append(("SYSTEM.DAT  glyph atlas",
                              UIItem(asset.layers, asset.labels, asset.info,
                                     key="SYSTEM.DAT glyph atlas", source=atlas)))
            else:
                items.append(("SYSTEM.DAT  not read", UIItem([], [], asset.info,
                                                             key="SYSTEM.DAT", source=(raw,))))
            items += self._icons(raw, ctx)

        if "OPEN1.BIN" in entries:
            open1 = archive.extract(entries["OPEN1.BIN"])
            asset = parse_open1_bin(open1)
            for i, im in enumerate(asset.layers):
                items.append((f"OPEN1.BIN [{i}]", UIItem([im], ["Image"], asset.info,
                                                         key=f"OPEN1.BIN {i}", source=(open1,))))
            if not asset.layers:
                items.append(("OPEN1.BIN (no layers)", UIItem([], [], asset.info,
                                                              key="OPEN1.BIN", source=(open1,))))

        if "STFIELD.DAT" in entries:
            items += self._stfield(archive.extract(entries["STFIELD.DAT"]))

        menu_path = ctx.path("MENU.BIN")
        if menu_path.exists():
            note = self._menu_bin_note(menu_path.stat().st_size)
            items.append(("MENU.BIN  the movie player's code",
                          UIItem([], [], "MENU.BIN: the movie player's code, not graphics",
                                 text=note, key="MENU.BIN",
                                 source=(menu_path.read_bytes(),))))
        return items

    ICON_COLUMNS = 16

    def _icons(self, raw: bytes, ctx) -> list[tuple[str, Any]]:
        """The icons of resource 1's type-1 block (+0x899C), by icon number:
        the sheet, then each icon, named by the string the menus print for
        it."""
        from decoders.plugins.SLUS_006_28.formats import system_dat as sd
        from decoders.plugins.SLUS_006_28.formats import system_strings as ss
        try:
            if self._places is None:
                raise ValueError("the program could not be read for the block's places")
            icons = self._places[1]
            blk = ss.block(raw)
            row = sd.colours(sd.palette_rows(raw)[sd.ICON_ROW])
            offsets = sd.icon_offsets(blk, icons)
            texels = [sd.icon_pixels(blk, offsets, n, icons) for n in range(len(offsets))]
        except (ValueError, KeyError, IndexError, struct.error) as e:
            return [("SYSTEM.DAT  icons not read", UIItem([], [], f"The icons: {e}",
                                                          key="SYSTEM.DAT icons"))]
        colours = struct.pack("<256H", *sd.palette_rows(raw)[sd.ICON_ROW])
        shown = [sd.icon_image(t, row) for t in texels]
        dimmed = [sd.icon_image(t, row, sd.ICON_DIMMED) for t in texels]
        names = GameNames.for_ctx(ctx)
        strings = names.strings if names else None

        def name(n: int) -> str | None:
            return strings.text(n + 0x100) if strings else None

        def kind(n: int) -> str:
            c = ss.category(n + 0x100)
            return f"{c[0]} {c[1]}" if c and c[0] != "menu" else (c[0] if c else "")

        head = [f"{len(offsets)} icons, 24 x 24 at 8 bits, in resource 1's type-1 block at",
                f"+0x{icons:04X}: a u16 offset per icon number, then one lz_unpack",
                "(0x80022BF8) stream each (IconImageLoad (0x8001ADEC)). IconCellDraw",
                "(0x8001AD60) draws one with palette row 502 (0x7D80), the colour",
                "0x808080, or 0x404040 when IconCellSet (0x8001AF04) is given its flag",
                "(the menus dim the commands off the cursor: MenuCommandsDisp",
                "(0x8006C178)). Icon 0 is never drawn: IconCellSet clears the cell.",
                "",
                "The name is string n + 0x100 and the description string n + 0x200:",
                "the menus draw a byte n as icon n (a command: MenuCommandsDisp; an",
                "item or spell cell: MenuIconBytesDisp (0x8006C21C)), and for the byte",
                "under the cursor MenuCursorTextDisp (0x8006C8F0) prints string",
                "n + 0x200, then n + 0x100. The ids fall in the string table's item,",
                "spell and menu ranges (the Strings tab). Row 502 is loaded by",
                "resource 1's command 0x20C."]
        cols = self.ICON_COLUMNS
        side = sd.ICON_SIDE
        rows_n = (len(shown) + cols - 1) // cols

        def sheet(images):
            out = Image.new("RGBA", (cols * side, rows_n * side), (0, 0, 0, 0))
            for n, im in enumerate(images):
                out.paste(im, ((n % cols) * side, (n // cols) * side))
            return out

        listing = [f"icon n at column n % {cols}, row n / {cols}:"]
        listing += [f"  0x{n:02X}  {name(n) or '-'}" + (f"  ({kind(n)})" if kind(n) else "")
                    for n in range(1, len(shown))]
        # the colours, 0x808080 and 0x404040, are in the info
        labels = ["as drawn", "dimmed"]
        items = [(f"SYSTEM.DAT  icons  {len(shown)}",
                  UIItem([sheet(shown), sheet(dimmed)], labels,
                         "\n".join(["SYSTEM.DAT: the icons", ""] + head),
                         text="\n".join(listing), key="SYSTEM.DAT icons",
                         source=(colours, *texels)))]
        for n in range(len(shown)):
            title = name(n) or ("never drawn" if n == 0 else "no string")
            info = [f"icon {n} (0x{n:02X})", f"name (string 0x{n + 0x100:03X}): {name(n) or '-'}"]
            desc = strings.text(n + 0x200) if strings else None
            if desc:
                info.append(f"description (string 0x{n + 0x200:03X}): {desc.replace(chr(10), ' / ')}")
            if kind(n):
                info.append(f"string range: {kind(n)}")
            info += [f"offset +0x{offsets[n]:04X} from +0x{icons:04X}", ""] + head
            items.append((f"  icon {n}  {title}",
                          UIItem([shown[n], dimmed[n]], labels, "\n".join(info),
                                 key=f"icon {n:#04x}", source=(colours, texels[n]))))
        return items

    @staticmethod
    def _menu_bin_note(size: int) -> str:
        return "\n".join([
            f"MENU.BIN (beside LUNADATA.FIL on the disc), {size:,} bytes",
            "",
            "Not a picture file: it is the movie player's code, an overlay.",
            "Before a movie overlay_load (0x80023240) reads it whole to",
            "0x80196000, overlay_stamp_check (0x800232B0) compares its build",
            "stamp with the main program's, and MoviePlay (0x800232D4) calls",
            "it at one address, movie_play (0x80196B54).",
            "Nothing in it is shown here as graphics.",
            "",
            "docs/spec/code/subsystems/overlay.md"])

    STFIELD_PRODUCER = "decoders.plugins.SLUS_006_28.formats.stfield"

    def _stfield(self, raw: bytes) -> list[tuple[str, Any]]:
        """STFIELD.DAT (resource 2) as sprite_reset (0x80018DBC) reads it: the
        sheet under each sub-palette, and each bank's poses under the
        sub-palettes its uses take."""
        from decoders.plugins.SLUS_006_28.formats import stfield as sf
        from decoders.plugins.SLUS_006_28.formats.sprite_pages import (
            parse_actor_block, pose_sheet,
        )
        try:
            st = sf.parse(raw)
        except ValueError as e:
            return [("STFIELD.DAT  not read", UIItem([], [], f"STFIELD.DAT\n{e}",
                                                     key="STFIELD.DAT", source=(raw,)))]
        proof = proven_by_lines(self.STFIELD_PRODUCER)
        sheets = [sf.sheet_image(st, k) for k in range(16)]

        def uses_of(sub: int, bank: int | None = None) -> list[str]:
            out = [f"  {sf.BANK_NAMES[b]}, word 0x{w:04X}: {what}"
                   for b, w, what, _where in sf.USES
                   if sf.sub_palette_of(w) == sub and (bank is None or b == bank)]
            if bank is None:
                out += [f"  digits, style 0x{style:02X}: {what}"
                        for style, k, what in sf.DIGITS if k == sub]
            return out

        head = (f"STFIELD.DAT: resource {sf.RESOURCE}, {len(raw):,} bytes; not a command "
                f"list. Its head's places (x 4): "
                + ", ".join(f"{w * 4:#x}" for w in st.head))
        info = [head, "",
                f"The sheet: {sf.SHEET_WIDTH} x {st.lines} at 4 bits, sprite page "
                f"{sf.PAGE}, video memory (0x3C0, 0).",
                "Palette row 507 as sprite_reset loads it: colour 0 of each",
                "sub-palette made 0, no bit 15 set. Each layer is one sub-palette;",
                "what draws with it:"]
        for k in range(16):
            used = uses_of(k)
            info.append(f"sub-palette {k}:" + ("" if used else " no use in the C"))
            info += used
        palette = struct.pack(f"<{len(st.palette)}H", *st.palette)
        items = [("STFIELD.DAT  sheet",
                  UIItem(sheets, [f"sub-palette {k}" for k in range(16)],
                         "\n".join(info + [""] + proof), key="STFIELD.DAT sheet",
                         source=(palette, st.image)))]

        for bank, block in enumerate(st.banks):
            data = parse_actor_block(block)
            subs = sf.bank_sub_palettes(bank)
            name = sf.BANK_NAMES[bank]
            images, labels = [], []
            for k in subs:
                sheet = pose_sheet(data, {sf.PAGE: sheets[k]}) if data else None
                if sheet is not None:
                    images.append(sheet.image)
                    labels.append(f"sub-palette {k}")
            info = [f"Bank {bank}: {name}, the sprite data at the head's word "
                    f"{sf.BANK_WORDS[bank]} ({len(block):,} bytes unpacked).",
                    (f"{data.pose_count} poses, {len(data.animations())} animations; "
                     f"pose k at column k % 16, drawn from page {sf.PAGE}, the sheet."
                     if data else "! its head does not lay out a sprite data"),
                    "", "Drawn by (sub-palette = (word & 0xFF) >> 4 of row 507):"]
            for b, w, what, where in sf.USES:
                if b == bank:
                    info += [f"  0x{w:04X}, sub-palette {sf.sub_palette_of(w)}: {what}",
                             f"      {where}"]
            info += ["", "Layers: the poses under each of those sub-palettes."]
            items.append((f"STFIELD.DAT  bank {bank}  {name}",
                          UIItem(images, labels, "\n".join(info + [""] + proof),
                                 key=f"STFIELD.DAT bank {bank}",
                                 source=(palette, st.image, block))))
        return items


# ---------------------------------------------------------------------------
# CD tracks — CD Audio tracks (Red Book)
# ---------------------------------------------------------------------------

class CdTracksProvider:
    """Red Book CD audio — the disc's own tracks, played off the BIN.

    This is deliberately a *different tab* from **Sound banks**, because it
    is a different subsystem. These are the tracks a CD player would play:
    raw 16-bit stereo PCM streamed from the disc, with no involvement from
    the SPU. Most of the game's music is sequenced from the VAB banks in
    LUNADATA.FIL (**Sound banks**), but one song plays CD audio instead:
    MusicPlay (0x80054F2C) sends 0x3C to cd_track_play(2) (0x8001B684), track 2 (records.music) —
    so a track the game plays carries that song's title here, and the
    song is in **Music** too.

    Reading them needs the original BIN/CUE, not the extracted filesystem —
    a CD-DA track is not a file, so an extracted disc cannot contain it.
    """

    name = "CD tracks"
    key = "cd-tracks"
    supports_zoom = False
    supports_grid = False
    supports_layers = False

    #: A whole track is ~26 MB of PCM; previewing this much is enough to
    #: recognise it without holding the entire disc in memory to draw a
    #: picture of it.
    PREVIEW_SECONDS = 30

    #: A track is a CD track; the song MusicPlay (0x80054F2C) plays from
    #: it is the Music tab's.
    homes = {"cd-track": (None,)}

    def __init__(self):
        self._tracks = None
        self._reason = ""

    @staticmethod
    def holds(track, r, ctx) -> bool:
        """CD track n."""
        return r.kind == "cd-track" and track.number == r.id[0]

    def _ensure_loaded(self, ctx):
        """Load the image's CD-DA tracks, recording WHY when there are none.

        The three ways this comes up empty are different facts and were all
        reported as "needs the BIN/CUE": the image is missing, the image is
        there but the track layout is not (a bare .bin), or the disc simply
        carries no Red Book audio — which is true of every Lunar 2 disc.
        """
        if self._tracks is not None:
            return
        self._tracks = []
        # ctx.source is the image re-resolved against the library's
        # discs/, so a moved image is still found there.
        source = ctx.source
        if source is None:
            self._reason = ("The disc image this was extracted from was not found — "
                            "CD-DA tracks are not files and can only be read "
                            "from the image itself.")
            return
        if source.suffix.lower() != ".cue":
            self._reason = (f"{source.name} is not a .cue — the track layout "
                            f"lives in the cue sheet, not in the data track.")
            return
        try:
            from decoders.psx.disc.cd_audio import load_tracks
            self._tracks = load_tracks(source)
        except Exception as exc:
            self._reason = f"{source.name}: {exc}"
            return
        if not self._tracks:
            self._reason = (f"{source.name} has no Red Book audio tracks — "
                            f"this disc is data only.")

    def get_items(self, cache, archive, ctx, selected):
        self._ensure_loaded(ctx)
        if not self._tracks:
            return [("No CD audio on this disc", None)]
        names = GameNames.for_ctx(ctx)
        items = []
        for t in self._tracks:
            title = names and names.titles(names.bgm_numbers_for_cd_track(t.number))
            items.append((f"Track {t.number}" + (f"  {title}" if title else "")
                          + f"  {int(t.seconds // 60)}m{t.seconds % 60:04.1f}s"
                          f"  {t.size // 1048576}MB", t))
        return items

    def item_identity(self, label, track, ctx) -> Identity:
        """A track by its number; its PCM read only when two discs' tracks
        are the same length."""
        return Identity(f"track {track.number}", track.size,
                        lambda: of_bytes("", track.read()).digest())

    def get_layer_options(self):
        return []

    def on_select(self, track, cache, archive, ctx):
        # the game's music is the Music tab's, on the discs that have one
        music = applies_to(MusicProvider, ctx)
        if track is None:
            return SelectResult(
                info="No CD audio available",
                summary={"title": "No CD audio on this disc", "fields": [
                    ("Why", self._reason or "unknown"),
                    ("Note", "CD-DA tracks are not files — they live in the\n"
                             "image's track layout, which only a .cue describes"),
                    *([("In-game music", "is not here — see the Music tab")] if music else []),
                ]})

        from decoders.psx.disc.cd_audio import pcm_to_wav
        from viewer_tabs.waveform import pcm_envelope

        preview_frames = min(track.frames,
                             self.PREVIEW_SECONDS * 44100)
        head = track.read(0, preview_frames)
        lo, hi = pcm_envelope(head, 2, 900)

        names = GameNames.for_ctx(ctx)
        numbers = names.bgm_numbers_for_cd_track(track.number) if names else []
        if numbers:
            played = ["\n".join(f"song {n}: {names.bgm(n) or '(untitled)'}" for n in numbers),
                      "played by MusicPlay (0x80054F2C) -> cd_track_play (0x8001B684) "
                      "(records.music)"]
        elif names:
            played = ["no song plays this track"] + (
                ["(the in-game music is the Music tab)"] if music else [])
        else:
            played = ["in-game music is the Music tab"] if music else []
        info = "\n".join([f"CD Audio track {track.number}",
                          f"{int(track.seconds // 60)}m{track.seconds % 60:04.1f}s  "
                          f"{track.size / 1048576:.1f} MB",
                          "Red Book 44.1kHz stereo",
                          f"waveform = first {self.PREVIEW_SECONDS}s",
                          "Play/WAV = whole track", *played])
        return SelectResult(
            info=info,
            audio={"wav": pcm_to_wav(track.read()),
                   "name": f"cd_track{track.number:02d}", "songs": numbers,
                   "title": names.titles(numbers) if numbers else None},
            waveform={"lo": lo, "hi": hi, "loop": None,
                      "seconds": preview_frames / 44100,
                      "note": f"first {self.PREVIEW_SECONDS}s of "
                              f"{track.seconds:.0f}s"},
            ref=ref("cd-track", track.number),
        )


# ---------------------------------------------------------------------------
# Sound banks — VAB sample banks + SEQ sequences, plus the loose disc audio files
# ---------------------------------------------------------------------------

class SoundItem(NamedTuple):
    """A Sound banks row. `bgm` is what the game plays it as: a music
    bank's sequence 0 is what MusicPlay (0x80054F2C) plays for its songs
    (records.music), so that sequence ("song 12 · ‹title›") and its bank
    (the title) carry the songs; a sequence of a bank of sound effects
    carries the numbers SoundPlay (0x800555F0) plays it for ("sound effect
    9"), and its bank what it is ("the battle's sound effects").
    `plays` is "song" or "sound-effect" (links.sound_effects.sequence_is)."""
    kind: str                   # "vag" | "seq" | "bank" | "file"
    bank: Any                   # the SoundBank, or the file path for "file"
    index: int | None = None
    bgm: str | None = None
    plays: str | None = None


#: (score, its bank's samples, how) -> the score walked (`_walked`), for as
#: long as the score and the samples are held
_WALKED: dict[tuple, Any] = {}


def _walked(seq, vab, **how):
    """seq_synth.walk(seq, vab, **how), walked once while the score and the
    samples are held: the discs that carry the same bank share its parse
    (sound_banks.load_bank), and so its walks. A walk is only read."""
    from decoders.psx.formats.seq_synth import walk
    if vab is None:
        return walk(seq, vab, **how)
    key = (id(seq), id(vab), tuple(sorted(how.items())))
    got = _WALKED.get(key)
    if got is None:
        got = walk(seq, vab, **how)
        if _WALKED.setdefault(key, got) is got:
            # gone, the score's or the samples' id may be another's: forget it
            weakref.finalize(seq, _WALKED.pop, key, None)
            weakref.finalize(vab, _WALKED.pop, key, None)
    return got


class SoundBanksProvider:
    """Lunar's sound banks, decoded out of LUNADATA.FIL: the music's and the
    sound effects' samples and scores, as the disc stores them.

    Resources 232–358 are 127 VAB+SEQ banks — 1,029 SPU-ADPCM samples and 412
    sequences, ~16.6 MB and the archive's largest region (docs/spec/sound.md).
    Samples decode to PCM and play. Sequences play live through their bank,
    as the game plays them: an endless loop repeats for as long as the loop
    switch is on, and goes on to the score's ending when it is off. They
    re-wrap as standard MIDI, and a WAV export renders a chosen number of
    passes. The songs, by the game's titles, are the Music tab's; a bank's
    first sequence plays them. The two `.PCM` files on the disc are *not*
    here: both extract as all zeros, which the Files view says out loud
    rather than presenting as a bank.
    """

    name = "Sound banks"
    key = "sound-banks"
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = False
    supports_grid = False
    supports_layers = False

    VIEWS = ("Banks", "Sequences", "Samples", "Files")
    views_change_items = True
    #: Where each kind is listed. A song is the Music tab's.
    homes = {"sequence": ("Sequences",), "sound-bank": ("Banks",), "sample": ("Samples",)}

    #: The score's map: its endless loop twice, then its ending. The
    #: timeline, the waveform and a plain WAV export lay it out so; played
    #: live, every pass after the second is shown in the second.
    PASSES = 2
    #: The most passes an export renders.
    MAX_PASSES = 20

    def __init__(self):
        self.view = self.VIEWS[0]
        self._banks = None
        #: why the banks could not be read, the last time ("" when they were)
        self._error = ""
        self._setting = None
        self._lengths: dict[tuple[int, int], tuple[float, bool]] = {}

    def get_views(self):
        return list(self.VIEWS)

    @staticmethod
    def holds(item, r, ctx) -> bool:
        """A bank; one of its samples or scores."""
        if r.kind == "sound-bank":
            return item.kind == "bank" and item.bank.resource == r.id[0]
        if r.kind == "sample":
            return item.kind == "vag" and (item.bank.resource, item.index) == r.id
        if r.kind == "sequence":
            return item.kind == "seq" and (item.bank.resource, item.index) == r.id
        return False

    # -- bank index --------------------------------------------------------

    def _ensure_loaded(self, ctx):
        """Parse every bank once (~0.2s for all 127; no cache needed). A
        read that fails says why (`_error`) and leaves the banks unread:
        the next call reads again."""
        if self._banks is not None:
            return
        from decoders.plugins.SLUS_006_28.records.sound_setting import \
            game_setting
        self._setting = game_setting()
        try:
            from decoders.psx.analysis.exe_loader import load_exe
            from decoders.plugins.SLUS_006_28.formats.resource_table import load_resource_table
            from decoders.plugins.SLUS_006_28.formats.sound_banks import find_banks
            binary = load_exe(ctx.exe_path)
            resources = load_resource_table(binary)
            banks = find_banks(ctx.path("LUNADATA.FIL"), resources)
        except Exception as ex:
            self._error = f"{type(ex).__name__}: {ex}"
            return
        self._banks, self._error = banks, ""
        try:
            # The levels, tick and reverb the game's code sets; the reverb
            # preset is read from the same EXE (records.sound_setting).
            self._setting = game_setting(binary)
        except Exception:
            pass                            # renders dry, and says so

    def _render(self, seq, bank, passes: int | None = None):
        """The score as the game plays it: an endless loop `passes` times,
        then the score's ending."""
        from decoders.plugins.SLUS_006_28.records.sound_setting import \
            game_setting
        from decoders.psx.formats.seq_synth import render
        setting = self._setting or game_setting()
        return render(seq, bank.vab, passes=passes or self.PASSES,
                      **setting.render_args())

    def _walk(self, seq, bank):
        """The score read as `_render` plays it, without voicing it: its
        length, its loop and its time map (all 412 take ~0.1s)."""
        from decoders.plugins.SLUS_006_28.records.sound_setting import \
            game_setting
        setting = self._setting or game_setting()
        return _walked(seq, bank.vab, passes=self.PASSES,
                       tick_hz=setting.tick_hz,
                       vblank_minus=setting.vblank_minus)

    def _length(self, bank, index: int) -> tuple[float, bool]:
        """How long the score plays as `_render` plays it (libsnd's tick,
        an endless loop `PASSES` times), and whether it loops for ever."""
        key = (bank.resource, index)
        hit = self._lengths.get(key)
        if hit is None:
            stats = self._walk(bank.seqs[index], bank)
            hit = self._lengths[key] = (stats.seconds, stats.passes > 0)
        return hit

    def _score(self, seq, bank, name: str, walked, describe) -> ScoreSource:
        """What the server needs to play the score live, at the game's
        setting. `describe(stats)` turns the stats of the whole map,
        played once in the background, into the selection's text and info:
        it runs on another thread, so it reads nothing that changes."""
        from decoders.plugins.SLUS_006_28.records.sound_setting import \
            game_setting
        from decoders.psx.formats.seq_synth import Player, tail_frames
        from decoders.psx.formats.vab import SPU_BASE_RATE
        args = (self._setting or game_setting()).render_args()
        vab = bank.vab
        return ScoreSource(
            label=name,
            player=lambda passes: Player(seq, vab, passes=passes, **args),
            passes=self.PASSES, rate=SPU_BASE_RATE,
            frames=walked.end + tail_frames(SPU_BASE_RATE,
                                            reverb=args["reverb"]) + 1,
            first_pass=walked.first_pass if walked.loop else None,
            loop=walked.loop, describe=describe)

    def _audio(self, seq, bank, name: str, walked) -> dict:
        """The transport's clip: the score's MIDI, where the game's endless
        loop lies (seconds), and a WAV rendered for an export, of a chosen
        number of passes. It plays live (`_score`)."""
        from decoders.psx.disc.cd_audio import pcm_to_wav
        from decoders.psx.formats.seq import seq_to_midi
        from decoders.psx.formats.vab import SPU_BASE_RATE
        audio = {"midi": seq_to_midi(seq), "name": name,
                 "render_wav": lambda n=None: pcm_to_wav(self._render(
                     seq, bank, max(1, min(n or self.PASSES,
                                           self.MAX_PASSES)))[0])}
        if walked.loop:
            start, end = walked.loop
            audio["loop"] = (start / SPU_BASE_RATE, end / SPU_BASE_RATE)
            audio["passes"] = self.PASSES
        return audio

    @staticmethod
    def _render_lines(rstats, full: bool = True) -> list[str]:
        """What the render played, beside the setting it played with;
        without `full`, what only voicing the whole score measures is
        "…"."""
        from decoders.psx.formats.vab import SPU_BASE_RATE
        voices = (f"at most {rstats.voices_max} voices at once, "
                  f"{rstats.stolen} stolen, {rstats.lost} lost" if full
                  else "at most … voices at once, … stolen, … lost")
        out = [f"{rstats.notes:,} notes voiced on {rstats.ticks:,} sound "
               f"ticks, {rstats.seconds:.2f}s; {voices}"]
        if rstats.loop:
            start, end = (x / SPU_BASE_RATE for x in rstats.loop)
            out.append(f"endless loop: played for ever as the game plays "
                       f"it; shown {rstats.passes} times, then the ending, "
                       f"the last pass {start:.2f}s-{end:.2f}s standing for "
                       f"every pass after it")
        elif rstats.passes:
            out.append(f"loop jumps: {rstats.passes}")
        return out

    # -- item lists --------------------------------------------------------

    def get_items(self, cache, archive, ctx, selected):
        if self.view == "Files":
            return self._file_items(ctx)

        self._ensure_loaded(ctx)
        if self._error:
            return [(f"The sound banks could not be read: {self._error}", None)]
        if not self._banks:
            return [("No sound banks found in LUNADATA.FIL", None)]
        from viewer_tabs.links import sound_effects as lsx
        names = GameNames.for_ctx(ctx)
        model = GameModel.for_ctx(ctx) if names is not None else None

        def what(bank, index=None) -> tuple[str | None, str | None]:
            """What the bank or its score plays, and in what words."""
            if model is None:
                return ("sound-effect" if bank.is_sfx else "song"), None
            plays, words, _numbers = lsx.sequence_is(model, bank.resource, index)
            if index is None:
                words = (names.titles(names.bgm_numbers_for_bank(bank.resource))
                         if plays == lsx.SONG else lsx.bank_words(model, bank.resource))
            return plays, words or None

        # the songs' banks first, then the sound effects'
        banks = sorted(self._banks, key=lambda b: (b.is_sfx, b.resource))
        if self.view == "Banks":
            items = []
            for b in banks:
                plays, words = what(b)
                items.append((f"{b.label}  {words}" if words else b.label,
                              SoundItem("bank", b, None, words, plays)))
            return items

        if self.view == "Sequences":
            items = []
            for b in banks:
                for i, seq in enumerate(b.seqs):
                    plays, words = what(b, i)
                    secs, endless = self._length(b, i)
                    items.append((
                        f"sequence {b.resource}/{i}  {secs:.1f}s{' ↻' if endless else ''}"
                        f"  {seq.notes} notes" + (f"  {words}" if words else ""),
                        SoundItem("seq", b, i, words, plays)))
            return items

        items = []
        for b in self._banks:
            for vag in b.vab.vags:
                secs = vag.frames / b.vab.vag_rate(vag.index)
                size = (f"{vag.size / 1024:5.1f}K" if vag.size >= 1024
                        else f"{vag.size:5d}B")
                items.append((
                    f"sample {b.resource}/{vag.index}  {secs:.2f}s  {size.strip()}",
                    SoundItem("vag", b, vag.index)))
        return items

    def item_identity(self, label, item, ctx) -> Identity:
        """A bank by its resource number, a sample or a sequence by its
        number in the bank, a file by its name. A bank is compared by its
        VAB and sequences, a sample by its bytes and the VAB's head, a
        sequence by its bytes and the VAB it plays through."""
        if item.kind == "file":
            return of_file(item.bank.name, item.bank)
        from decoders.config import SECTOR_SIZE
        from decoders.plugins.SLUS_006_28.formats import sound_banks as sb
        b, i = item.bank, item.index

        def chunks(*kinds) -> list[bytes]:
            with open(ctx.path("LUNADATA.FIL"), "rb") as f:
                f.seek(b.sector * SECTOR_SIZE)
                raw = f.read(b.size)
            return [raw[c.payload_offset:c.payload_offset + c.size]
                    for c in b.chunks if c.kind in kinds]

        vab = (sb.CMD_VAB_HEAD, sb.CMD_VAB_BODY)
        if item.kind == "bank":
            return of_parts(f"bank {b.resource}", lambda: chunks(*vab, sb.CMD_SEQ))
        if item.kind == "vag":
            data = next(v.data for v in b.vab.vags if v.index == i)
            return of_parts(f"bank {b.resource} sample {i}",
                            lambda: [data, *chunks(sb.CMD_VAB_HEAD)])
        if len(b.seq_data) == len(b.seqs):          # each sequence read: by its bytes
            return of_parts(f"bank {b.resource} sequence {i}",
                            lambda: [b.seq_data[i], *chunks(*vab)])
        return of_parts(f"bank {b.resource} sequence {i}",
                        lambda: chunks(*vab, sb.CMD_SEQ))

    def _file_items(self, ctx):
        items = []
        for name in ctx.files:
            path = ctx.path(name)
            if path.is_file() and (name.endswith(".XA")
                                   or name.endswith(".PCM")):
                size_mb = path.stat().st_size / (1024 * 1024)
                items.append((f"{name} ({size_mb:.1f}MB)", SoundItem("file", path)))
        return items

    def get_layer_options(self):
        return []

    # -- selection ---------------------------------------------------------

    def on_select(self, item_data, cache, archive, ctx):
        if item_data is None:
            return SelectResult(info="No sound data available")
        kind = item_data[0]
        if kind == "vag":
            result = self._show_sample(item_data[1], item_data[2])
        elif kind == "file":
            result = self._show_file(item_data[1])
        else:
            if kind == "bank":
                result = self._show_bank(item_data[1])
            else:
                result = self._show_sequence(item_data[1], item_data[2])
            result = self._with_bgm(result, item_data[1], item_data[2], ctx)
            result = self._with_what(result, item_data, ctx)
        result.ref = self._ref(item_data, ctx)
        return result

    @staticmethod
    def _with_what(result: "SelectResult", item, ctx) -> "SelectResult":
        """Say what the clip is, so the transport leads with it: a song's
        score (its titles, `_with_bgm`), a sound effect ("sound effect 9"),
        a bank's samples."""
        audio = result.audio
        if audio is None:
            return result
        bank, index = item.bank, item.index
        plays, words = item.plays, item.bgm
        if item.kind == "bank":
            audio["title"] = (f"sound bank {bank.resource}, all its samples"
                              + (f" · {words}" if words else ""))
            return result
        audio["kind"] = plays
        if plays == "sound-effect":
            audio["title"] = words or f"sequence {bank.resource}/{index}"
            if words:
                result.info = (result.info or "") + (
                    f"\n{words}: played by SoundPlay (0x800555F0) "
                    f"(records.sound_effects)")
        elif not audio.get("songs"):
            audio["title"] = f"sequence {bank.resource}/{index}"
        return result

    @staticmethod
    def _ref(item, ctx):
        """The thing a row is: a bank, a sample, a score, a disc file."""
        if item.kind == "file":
            name = item.bank.name
            return ref("disc-file", ctx.files.index(name)) if name in ctx.files else None
        resource = item.bank.resource
        if item.kind == "bank":
            return ref("sound-bank", resource)
        return ref("sample" if item.kind == "vag" else "sequence", resource, item.index)

    @staticmethod
    def _with_bgm(result: "SelectResult", bank, index, ctx) -> "SelectResult":
        """Name the songs that play this bank (its sequence 0)."""
        names = GameNames.for_ctx(ctx)
        if names is None or index not in (None, 0):
            return result
        numbers = names.bgm_numbers_for_bank(bank.resource)
        if not numbers:
            return result
        lines = [f"song {n}: {names.bgm(n) or '(untitled)'}" for n in numbers]
        more = "\n" + "\n".join(lines) + \
            "\nplayed by MusicPlay (0x80054F2C) (sequence 0; records.music)"
        result.info = (result.info or "") + more
        if result.audio is not None and index == 0:
            result.audio["songs"] = numbers         # the map's music button knows it
            result.audio["title"] = names.titles(numbers)
            result.audio["kind"] = "song"
        if result.music is not None:
            describe = result.music.describe

            def described(stats) -> dict:
                out = describe(stats)
                if "info" in out:
                    out["info"] += more
                return out
            result.music = replace(result.music, describe=described)
        return result

    def _show_arrangement(self, bank, index: int) -> SelectResult:
        """The same sequence as a timeline instead of an event list."""
        from decoders.psx.formats.vab import SPU_BASE_RATE
        from viewer_tabs.arrangement import arrangement

        seq = bank.seqs[index]
        title, name = (f"sequence {bank.resource}/{index}",
                       f"sequence-{bank.resource}-{index}")

        # Label each lane with the instrument it actually plays: the program
        # its first program-change selects, and how many tones that program
        # has in this bank. A bare channel number says much less.
        programs: dict[int, str] = {}
        for ev in seq.events:
            if ev.kind == 0xC0 and ev.data and ev.channel not in programs:
                prog = ev.data[0]
                tones = len(bank.vab.tones_of(prog)) if prog < bank.vab.ps \
                    else 0
                programs[ev.channel] = (f"prog {prog}" if tones
                                        else f"prog {prog} (none)")

        walked = self._walk(seq, bank)
        # The playhead follows the score as libsnd read it: its ticks, its
        # tempo arithmetic, and the jumps back at each loop end.
        arr = arrangement(seq, programs, [(at / SPU_BASE_RATE, tick)
                                          for at, tick in walked.marks], walked.seconds)

        loop = (f"\nloop {walked.loop[0] / SPU_BASE_RATE:.2f}s-"
                f"{walked.loop[1] / SPU_BASE_RATE:.2f}s"
                if walked.loop else "")
        head = (f"{title}\n"
                f"{walked.seconds:.1f}s  {seq.bpm:.0f} bpm{loop}\n"
                f"{len(arr.lanes)} channels  {seq.notes} notes\n"
                f"sound bank {bank.resource}")

        def info(stats) -> str:
            return head + (f"\n! {stats.warnings[0]}" if stats.warnings
                           else "")

        return SelectResult(
            info=info(walked), timeline=arr,
            audio=self._audio(seq, bank, name, walked),
            music=self._score(seq, bank, name, walked,
                              lambda stats: {"info": info(stats)}),
        )

    def _show_sample(self, bank, vag_index: int) -> SelectResult:
        from decoders.psx.formats.vab import decode_adsr, pcm_to_wav
        from viewer_tabs.waveform import sample_envelope

        vab = bank.vab
        vag = next(v for v in vab.vags if v.index == vag_index)
        pcm, loop_start = vag.decode()
        rate = vab.vag_rate(vag_index)
        users = vab.tones_using(vag_index)
        title, name = f"sample {bank.resource}/{vag_index}", f"sample-{bank.resource}-{vag_index}"

        fields = [
            ("sample", f"{title}   (sound bank {bank.resource}, VAG {vag_index})"),
            ("encoded", f"{vag.size:,} bytes SPU-ADPCM"),
            ("decoded", f"{len(pcm):,} frames, {len(pcm) / rate:.2f}s"),
            ("rate", f"{rate} Hz"),
            ("loop", f"frame {loop_start:,}" if loop_start is not None
                     else "one-shot"),
            ("VB offset", f"+0x{vag.offset:06X}"),
        ]
        if users:
            t = users[0]
            adsr = decode_adsr(t.adsr1, t.adsr2)
            shared = (f"  (+{len(users) - 1} more)" if len(users) > 1 else "")
            fields += [
                ("played by", f"program {t.program}, tone {t.index}{shared}"),
                ("centre note", f"{t.center}  +{t.shift} fine"),
                ("key range", f"{t.min_note} - {t.max_note}"),
                ("tone vol/pan", f"{t.vol} / {t.pan}"),
                ("ADSR", f"A{adsr['attack_rate']} ({adsr['attack_mode']})  "
                         f"D{adsr['decay_rate']}  S{adsr['sustain_level']}"
                         f"/{adsr['sustain_rate']}  R{adsr['release_rate']}"),
                ("pitch bend", f"-{t.pbmin} / +{t.pbmax}"),
            ]
        else:
            fields.append(("played by", "no tone references this sample"))

        info = (f"{title}\n{len(pcm) / rate:.2f}s at {rate} Hz\n"
                f"{'one-shot' if loop_start is None else 'looping'}\n"
                f"{len(users)} tone(s)")
        lo, hi = sample_envelope(pcm, 1200)
        return SelectResult(
            info=info,
            audio={"wav": pcm_to_wav(pcm, rate), "name": name},
            summary={"title": title, "fields": fields},
            waveform={"lo": lo, "hi": hi, "seconds": len(pcm) / rate,
                      "loop": (loop_start / len(pcm)
                               if loop_start is not None and pcm else None)},
        )

    def _audition(self, bank) -> tuple[bytes, int]:
        """Every sample in the bank, back to back — one click to hear a bank.

        Samples are resampled to a common rate rather than concatenated raw:
        their natural rates differ by a few percent and a single WAV has one
        header. The gap keeps them distinguishable.
        """
        from decoders.psx.formats.vab import SPU_BASE_RATE, pcm_to_wav

        out: list[int] = []
        gap = [0] * (SPU_BASE_RATE // 8)
        for vag in bank.vab.vags:
            pcm, _ = vag.decode()
            rate = bank.vab.vag_rate(vag.index)
            if rate != SPU_BASE_RATE and pcm:
                ratio = rate / SPU_BASE_RATE
                n = int(len(pcm) / ratio)
                pcm = [pcm[min(len(pcm) - 1, int(i * ratio))]
                       for i in range(n)]
            out += pcm + gap
        return pcm_to_wav(out, SPU_BASE_RATE), len(out)

    def _show_bank(self, bank) -> SelectResult:
        vab = bank.vab
        out = [
            f"Sound bank — resource {bank.resource}",
            f"sector {bank.sector}  {bank.size:,} bytes span, "
            f"{bank.used_bytes:,} used",
            "",
            f"VAB v{vab.version}  id {vab.vab_id}  "
            f"master vol {vab.mvol} pan {vab.pan}",
            f"{vab.ps} programs  {vab.ts} tones  {vab.vs} samples  "
            f"{len(bank.seqs)} sequences",
            "",
            "chunks (engine command list)",
            "---------------------------",
        ]
        names = {13: "VAB header (VH)", 14: "VAB body (VB)", 15: "SEQ"}
        for c in bank.chunks:
            out.append(f"  +0x{c.offset:06X}  cmd {c.kind:2d}  "
                       f"{c.size:8,d}  {names.get(c.kind, '?')}")

        out += ["", "programs", "--------",
                "  # tones  vol  pan  prior  mode   tones -> vag (centre, range)"]
        for p in vab.used_programs:
            tones = vab.tones_of(p.index)[:p.tones]
            out.append(f"  {p.index:2d} {p.tones:5d} {p.mvol:5d} {p.mpan:4d} "
                       f"{p.prior:6d} {p.mode:5d}")
            for t in tones:
                out.append(f"        tone {t.index:2d} -> vag {t.vag:2d}  "
                           f"centre {t.center:3d}+{t.shift:<3d} "
                           f"range {t.min_note:3d}-{t.max_note:<3d} "
                           f"vol {t.vol:3d} pan {t.pan:3d}")

        out += ["", "samples", "-------",
                "   #      bytes    frames   rate  loop"]
        for v in vab.vags:
            pcm, loop = v.decode()
            rate = vab.vag_rate(v.index)
            out.append(f"  {v.index:2d} {v.size:10,d} {len(pcm):9,d} "
                       f"{rate:6d}  "
                       f"{loop if loop is not None else '-'}")

        wav, frames = self._audition(bank)
        info = (f"{bank.label}\nsector {bank.sector}\n"
                f"{bank.size:,} bytes\n"
                f"Play = all {len(vab.vags)} samples\n"
                f"in order ({frames / 44100:.0f}s)")
        return SelectResult(text="\n".join(out), text_wrap=False, info=info,
                            audio={"wav": wav,
                                   "name": f"sound-bank-{bank.resource}"})

    def _show_sequence(self, bank, index: int) -> SelectResult:
        from decoders.psx.formats.seq import controller_name
        from decoders.psx.formats.seq_synth import fidelity_lines

        seq = bank.seqs[index]
        title, name = (f"sequence {bank.resource}/{index}",
                       f"sequence-{bank.resource}-{index}")

        # Played through this bank's own VAB — the game's instruments, not
        # a general MIDI substitute — by libsnd's reader and voice manager
        # at the game's setting, live (`_score`). What only voicing the
        # whole score measures fills in once the server has played it.
        walked = self._walk(seq, bank)
        setting = self._setting.lines() if self._setting else []
        reverb = self._setting.reverb if self._setting else None

        head = [
            title,
            f"{seq.size:,} bytes  v{seq.version}  "
            f"{seq.resolution} ticks/quarter",
            f"tempo {seq.tempo} us/quarter ({seq.bpm:.1f} bpm)  "
            f"rhythm {seq.rhythm[0]},{seq.rhythm[1]}",
            f"{len(seq.events):,} events  {seq.notes:,} notes  "
            f"{seq.ticks:,} ticks  {seq.seconds:.1f}s",
            f"channels {seq.channels}",
            f"programs {seq.programs}",
            "",
        ]

        def played(stats, full: bool) -> list[str]:
            if full:
                sent = (f"reverb: {stats.reverb}" if stats.reverb else
                        "reverb: off (the EXE's preset table could not be "
                        "read)")
            elif reverb is not None:
                dl, dr = reverb.depth
                sent = (f"reverb: {reverb.preset.name} depth {dl:+.3f}/"
                        f"{dr:+.3f}, … of {stats.voices} key-ons sent")
            else:
                sent = "reverb: off (the EXE's preset table could not be read)"
            peak = stats.peak if full else "…"
            return [f"played with bank {bank.resource}, peak {peak}/32768",
                    *self._render_lines(stats, full), *setting, sent,
                    *(f"  ! {w}" for w in stats.warnings)]

        # What you are hearing, and how much of it is the game's. The
        # player is an SPU in software driven by a transcription of libsnd;
        # what it does not transcribe is listed. Saying so where the audio
        # plays is the difference between an approximation and a claim.
        out = ["", "fidelity", "--------"] + fidelity_lines()
        out += [
            "",
            "events",
            "------",
            "     tick  ch  event",
        ]
        for ev in seq.events:
            if ev.status == 0xFF:
                if ev.data[0] == 0x51 and len(ev.data) >= 4:
                    us = int.from_bytes(ev.data[1:4], "big")
                    body = f"{us} us/quarter ({60_000_000 / us:.1f} bpm)"
                else:
                    body = ev.data[1:].hex(" ")
                out.append(f"  {ev.tick:7d}   -  {ev.name:<16} {body}")
                continue
            if ev.kind == 0xB0 and len(ev.data) == 2:
                body = f"{controller_name(ev.data[0]):<18} {ev.data[1]:3d}"
            elif ev.kind in (0x80, 0x90) and len(ev.data) == 2:
                body = f"note {ev.data[0]:3d}  vel {ev.data[1]:3d}"
            else:
                body = " ".join(f"{b:3d}" for b in ev.data)
            out.append(f"  {ev.tick:7d} {ev.channel:3d}  "
                       f"{ev.name:<16} {body}")

        def info(stats) -> str:
            return (f"{title}\n{stats.seconds:.1f}s  {seq.notes} notes\n"
                    f"{len(seq.channels)} channels\n"
                    f"played with sound bank {bank.resource}"
                    + (f"\n! {stats.warnings[0]}" if stats.warnings else ""))

        def text(stats, full: bool) -> str:
            return "\n".join(head + played(stats, full) + out)

        return SelectResult(
            text=text(walked, False), text_wrap=False, info=info(walked),
            audio=self._audio(seq, bank, name, walked),
            music=self._score(seq, bank, name, walked, lambda stats: {
                "text": text(stats, True), "info": info(stats)}))

    def _show_file(self, path: Path) -> SelectResult:
        size = path.stat().st_size
        name = path.name

        if name.endswith(".XA"):
            fields = [
                ("Format", "CD-XA ADPCM"),
                ("File Size", f"{size:,} bytes ({size / 1024 / 1024:.1f} MB)"),
                ("Detail", "Interleaved audio sectors"),
                ("Usage", "the voice clips" if name == "_AUDIO.XA"
                          else "nine channels played after the game "
                               "ends (GameRun (0x800559F4))"),
                ("Status", "decoded: the Voices tab plays each voice, read from the disc "
                           "image" if name == "_AUDIO.XA" else "not decoded yet"),
            ]
            note = f"{name} — CD-XA ADPCM"
        else:
            # Both .PCM files read back as nothing but zeros. That is a fact
            # about the extraction (they are MODE2 reservations, not MODE1
            # files), and claiming they are a "sample bank" hides it.
            fields = [
                ("Format", "empty in the ISO extraction"),
                ("File Size", f"{size:,} bytes ({size / 1024 / 1024:.1f} MB)"),
                ("Content", "all zero bytes"),
                ("Why", "MODE2 sector reservation;\nneeds raw BIN extraction"),
                ("Real samples", "VAB banks — see the Samples view"),
            ]
            note = f"{name} — placeholder, all zeros"

        return SelectResult(info=note, summary={"title": name, "fields": fields})


# ---------------------------------------------------------------------------
# Music — the soundtrack, by the game's titles
# ---------------------------------------------------------------------------

class SongItem(NamedTuple):
    """A Music row: song `number`, what MusicPlay (0x80054F2C) plays for it
    (records.music.Bgm), and for a song of a sound bank that bank, whose
    first score it plays."""
    number: int
    bgm: Any
    bank: Any = None


def _clock(seconds: float) -> str:
    """"2:05": a song's length as a player shows it."""
    s = round(seconds)
    return f"{s // 60}:{s % 60:02d}"


class MusicProvider:
    """The soundtrack, by the game's own titles: every song, and where it
    plays.

    A song is a number MusicPlay (0x80054F2C) plays (records.music): a
    sound bank's first score, the bank g_MusicBankNumbers (0x800127B8)
    names, or for song 60 the disc's own audio, CD track 2. The jukebox
    lists the songs in their numbers' order (MenuUseMusicListSet
    (0x80077380)), and so does this tab; it captions song n with string
    0x546 + n (MenuUseMusicListDisp (0x800774EC)), which is the song's
    title. A song whose caption is empty has no title and is listed by its
    number.

    Where a song plays is what the links know (viewer_tabs.links.sound):
    the maps whose map record names it, the battles that start with it or
    play it when they are won, and the scenes whose script plays it
    (ScriptCommandMusicPlay (0x8005E494), viewer_tabs.links.sound_effects),
    under the places of the maps that run the script, the debug room's
    last.

    A song plays live, as the game plays it, through its bank, as Sound
    banks plays a score: its endless loop repeats while the transport's
    loop switch is on. Arrangement lays its score out as a sequencer does.
    """

    name = "Music"
    key = "music"
    fan_about = """
    The soundtrack, by the game's own titles: every song, in the jukebox's
    order, and where it plays: the places whose maps play it, the battles
    that start with it or end with it, and the scenes that play it. A song
    plays here as the game plays it, its loop repeating while the
    transport's loop switch is on.
    """
    technical_view = "Arrangement"
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = False
    supports_grid = False
    supports_layers = False

    VIEWS = ("Music", "Arrangement")
    #: Song n is its own row, in either view.
    homes = {"song": VIEWS}

    def __init__(self):
        self.view = self.VIEWS[0]
        #: the banks, read and played as Sound banks reads and plays them
        self._scores = SoundBanksProvider()
        #: the disc's audio tracks, read as CD tracks reads them
        self._cd = CdTracksProvider()
        #: bank resource -> its first score walked (seq_synth.walk)
        self._walked: dict[int, Any] = {}

    def get_views(self):
        return list(self.VIEWS)

    def get_layer_options(self):
        return []

    @staticmethod
    def holds(item, r, ctx) -> bool:
        return r.kind == "song" and item.number == r.id[0]

    # -- the songs ----------------------------------------------------------

    def _walk(self, bank):
        """The bank's first score read as it plays, without voicing it."""
        got = self._walked.get(bank.resource)
        if got is None:
            got = self._walked[bank.resource] = self._scores._walk(bank.seqs[0], bank)
        return got

    def _track(self, item, ctx):
        """The CD track a song plays, or None when the disc image does not
        give it (CdTracksProvider says why)."""
        self._cd._ensure_loaded(ctx)
        return next((t for t in self._cd._tracks if t.number == item.bgm.track), None)

    def _how(self, item, ctx) -> tuple[float, bool | None] | None:
        """How long the song plays before it repeats or ends, and whether
        it repeats: an endless loop's opening and one pass of it; None for
        a CD track, whose repeat is not read. None when it cannot be read."""
        from decoders.psx.formats.vab import SPU_BASE_RATE
        if item.bgm.kind == "cd":
            track = self._track(item, ctx)
            return (track.seconds, None) if track is not None else None
        if item.bank is None or not item.bank.seqs:
            return None
        w = self._walk(item.bank)
        if w.loop:
            start, end = w.loop
            return ((w.first_pass or 0) + end - start) / SPU_BASE_RATE, True
        return w.seconds, False

    @staticmethod
    def _songs(names) -> list:
        """Every song MusicPlay (0x80054F2C) plays something for, by number
        (records.music.Bgm)."""
        from decoders.plugins.SLUS_006_28.records import music
        return [b for b in music.jukebox(names.binary.code) if b.kind != "none"]

    @staticmethod
    def _same(item, songs) -> list[int]:
        """The other songs that play what this one plays."""
        b = item.bgm
        return [s.number for s in songs if s.number != item.number and s.kind == b.kind
                and (s.resource, s.track) == (b.resource, b.track)]

    def get_items(self, cache, archive, ctx, selected):
        names = GameNames.for_ctx(ctx)
        if names is None:
            return [(no_names(ctx, "The songs are read from the program's tables"), None)]
        self._scores._ensure_loaded(ctx)
        banks = {b.resource: b for b in self._scores._banks or []}
        songs = self._songs(names)
        items = []
        for b in songs:
            item = SongItem(b.number, b, banks.get(b.resource) if b.kind == "sequence" else None)
            title = names.bgm(b.number)
            parts = [title, f"song {b.number}"] if title else [f"song {b.number}"]
            same = self._same(item, songs)
            if same and not title:
                parts.append(f"the same score as song {same[0]}")
            how = self._how(item, ctx)
            if how is not None:
                parts.append(_clock(how[0]))
            if b.kind == "cd":
                parts.append("the disc's own audio")
            elif how is not None:
                parts.append("loops" if how[1] else "plays once")
            items.append(("  ".join(parts), item))
        return items

    def item_identity(self, label, item, ctx) -> Identity:
        """A song by its number, compared by what it plays: its bank's first
        score and the bank's VAB, as Sound banks compares a sequence, or its
        CD track's audio. Its title is not compared: a song whose music two
        discs hold the same is one entry, titled as the first disc titles it."""
        key = f"song {item.number}"
        if item.bank is not None:
            return replace(self._scores.item_identity(label, SoundItem("seq", item.bank, 0), ctx),
                           key=key)
        track = self._track(item, ctx) if item.bgm.kind == "cd" else None
        if track is not None:
            return replace(self._cd.item_identity(label, track, ctx), key=key)
        return of_parts(key, lambda: [repr(item.bgm).encode()])

    # -- the page -----------------------------------------------------------

    def on_select(self, item, cache, archive, ctx):
        if item is None:
            return SelectResult(info="No songs")
        self._scores._ensure_loaded(ctx)
        model = GameModel.for_ctx(ctx)
        n = item.number
        if item.bgm.kind == "cd":
            result = self._cd_song(item, model, cache, archive, ctx)
        elif item.bank is None or not item.bank.seqs:
            why = f": {self._scores._error}" if self._scores._error else ""
            result = SelectResult(info=f"song {n}: sound bank {item.bgm.resource} could not be "
                                       f"read{why}")
        elif self.view == "Arrangement":
            result = self._arrangement(item, model.need_names())
        else:
            result = self._page(item, model, ctx)
        result.ref = ref("song", n)
        return result

    def _arrangement(self, item, names) -> SelectResult:
        """The song's score laid out as a sequencer lays it out (Sound
        banks' timeline), under its title."""
        n = item.number
        title = names.bgm(n) or f"song {n}"
        result = self._scores._show_arrangement(item.bank, 0)
        head = f"{title}\nsong {n}\n"
        result.info = head + result.info
        result.audio.update(name=f"song-{n}", songs=[n], title=title, kind="song")
        describe = result.music.describe
        result.music = replace(result.music, label=f"song-{n}",
                               describe=lambda stats: {"info": head + describe(stats)["info"]})
        return result

    def _page(self, item, model, ctx) -> SelectResult:
        """The song, simple to complex: its title, its sound, how long it
        plays and whether it repeats, where it plays, then how the game
        keeps it (folded in Fan mode)."""
        from decoders.psx.formats.vab import SPU_BASE_RATE
        from viewer_tabs.links import media
        names = model.need_names()
        n, bank = item.number, item.bank
        seq, walked = bank.seqs[0], self._walk(bank)
        title = names.bgm(n)
        name = f"song-{n}"
        audio = self._scores._audio(seq, bank, name, walked)
        audio.update(songs=[n], title=title or f"song {n}", kind="song")
        music = self._scores._score(seq, bank, name, walked, lambda stats: {})
        length, loops = self._how(item, ctx)
        start = end = opening = 0.0
        if loops:
            start, end = (x / SPU_BASE_RATE for x in walked.loop)
            opening = (walked.first_pass or 0) / SPU_BASE_RATE
            facts = [["Length", _clock(length),
                      f"{media._length(opening)} before its loop, then a "
                      f"{media._length(end - start)} loop" if opening >= 0.05
                      else "all of it one loop"],
                     ["Repeats", "for ever, as the game plays it: the score loops "
                                 + (f"from {_clock(opening)} on" if opening >= 0.05
                                    else "from its start"), ""]]
        else:
            facts = [["Length", _clock(length), ""],
                     ["Repeats", "no: it plays once, to its end", ""]]
        facts += self._facts(item, model)
        res = bank.resource
        extended = [
            ["Sound bank", f"resource {res}: g_MusicBankNumbers (0x800127B8) names it, "
                           f"sound_music_load (0x80023E9C) loads it", ""],
            ["Sequence", f"sequence {res}/0, {seq.size:,} bytes, {seq.resolution} ticks a "
                         f"quarter note, {seq.bpm:.1f} beats a minute", ""],
            ["Arrangement", f"{len(seq.channels)} channels, {seq.notes:,} notes: the "
                            f"Arrangement view lays them out", ""],
        ]
        if loops:
            extended.append(["Loop", f"the score's endless loop: from {opening:.2f} s, "
                                     f"{end - start:.2f} s a pass (libsnd's reader)", ""])
        plays = [ref("sound-bank", res), ref("sequence", res, 0)]
        badges = [{"text": _clock(length), "tone": "muted",
                   "hint": f"{length:.2f} seconds before it "
                           + ("repeats" if loops else "ends")},
                  {"text": "loops" if loops else "plays once",
                   "tone": "info" if loops else "muted"}]
        info = [title or f"song {n}", f"song: {n}", f"length: {_clock(length)}",
                f"loop: {'from ' + _clock(opening) if loops else 'none, it plays once'}",
                f"sound bank: {res}", f"sequence: {res}/0"]
        return SelectResult(
            sheet=self._sheet(item, model, title, badges, facts, extended, plays,
                              sound=True),
            audio=audio, music=music, info="\n".join(info))

    def _cd_song(self, item, model, cache, archive, ctx) -> SelectResult:
        """A song that is the disc's own audio track: its sound is the
        track's, as CD tracks plays it."""
        names = model.need_names()
        n, number = item.number, item.bgm.track
        title = names.bgm(n)
        track = self._track(item, ctx)
        facts = [["Plays from", f"the disc's own audio, CD track {number}: what a CD "
                                f"player would play, not a score", ""]]
        facts += self._facts(item, model)
        extended = [
            ["CD track", f"track {number}: MusicPlay (0x80054F2C) sends song {n} to "
                         f"cd_track_switch (0x8001B71C), which plays it with "
                         f"cd_track_play (0x8001B684)", ""],
            ["Repeats", "not read: the drive plays it with g_CdTrackMode's mode byte, "
                        "which the viewer does not read", ""],
        ]
        info = [title or f"song {n}", f"song: {n}", f"CD track: {number}"]
        badges = [{"text": "the disc's own audio", "tone": "muted"}]
        audio = waveform = None
        if track is None:
            facts.insert(0, ["Its sound", self._cd._reason
                             or f"the disc has no audio track {number}", ""])
        else:
            got = self._cd.on_select(track, cache, archive, ctx)
            audio, waveform = got.audio, got.waveform
            audio.update(name=f"song-{n}", songs=[n], title=title or f"song {n}", kind="song")
            facts.insert(0, ["Length", _clock(track.seconds), ""])
            badges.insert(0, {"text": _clock(track.seconds), "tone": "muted",
                              "hint": f"{track.seconds:.2f} seconds"})
            info.append(f"length: {_clock(track.seconds)}")
        if self.view == "Arrangement":
            info.append("no score to lay out: the disc's own audio")
        return SelectResult(
            sheet=self._sheet(item, model, title, badges, facts, extended,
                              [ref("cd-track", number)], sound=track is not None),
            audio=audio, waveform=waveform, info="\n".join(info))

    def _facts(self, item, model) -> list:
        """What every song's page says beside its sound: the songs that
        play the same, and a title the game does not give."""
        names = model.need_names()
        out = []
        same = self._same(item, self._songs(names))
        if same:
            out.append(["The same as", ", ".join(
                f"{names.bgm(m)} (song {m})" if names.bgm(m) else f"song {m}" for m in same),
                "it plays the same score" if item.bank is not None else ""])
        if not names.bgm(item.number):
            out.append(["Title", "none: the jukebox gives it no caption", ""])
        return out

    def _sheet(self, item, model, title, badges, facts, extended, plays,
               sound: bool) -> dict:
        """The page: the title, the sound, the facts, where it plays (the
        links into the song), then the extended info."""
        from decoders.plugins.SLUS_006_28.records import music
        from viewer_tabs import links
        from viewer_tabs.refs import KINDS, number_hex, written_hex
        n = item.number
        r = ref("song", n)
        string = music.TITLE_BASE + n
        extended = [
            ["The code's name", KINDS["song"].code, ""],
            ["Number", f"song {n} · {number_hex(r)}", ""],
            ["Title", f"string {string} ({string:#x}), the jukebox's caption: "
                      f"MenuUseMusicListDisp (0x800774EC)"
                      + ("" if title else "; it is empty"), ""],
            *extended,
            ["Proven by", "MusicPlay (0x80054F2C), MenuUseMusicListSet (0x80077380), "
                          "MenuUseMusicListDisp (0x800774EC)", ""],
        ]
        sections = []
        if sound:
            sections.append({"title": "", "sound": True})
        sections.append({"title": "The song", "style": "prose", "fields": facts})
        where = {"title": "Where it plays", "cite": "MusicPlay (0x80054F2C)",
                 "fanNote": "A map plays the song its record names; a battle plays the song "
                            "that starts it, and its jingle when it is won; a scene plays it "
                            "too, listed under the places that run it, the debug room's last.",
                 "note": "A map plays the song its map record names (byte 0xF); a battle "
                         "plays the song that starts it, and its jingle when it is won "
                         "(MapBtlRun (0x8007AE58), BtlRun (0x80027434)); a scene plays it "
                         "with its script's command 0x30 (ScriptCommandMusicPlay "
                         "(0x8005E494)), listed under the places whose maps run the "
                         "script, the debug room's last."}
        try:
            index = links.LinkIndex.of(model)
            into = [g for g in links.groups(model, index, r) if g["dir"] == "in"]
            if into:
                where["links"] = into
            else:
                where["note"] = "No map, battle or scene plays it. " + where["note"]
                where["fanNote"] = "No map, battle or scene plays it."
        except Exception as ex:
            where["note"] = f"Its links could not be read: {type(ex).__name__}: {ex}"
        sections.append(where)
        sections.append({"title": "Extended info", "extended": True, "fields": extended,
                         "links": [{"title": "Plays from", "dir": "out",
                                    "links": [links.link_json(model, p) for p in plays]}]})
        return {"title": title or f"song {n}", "subtitle": "a song of the soundtrack",
                "badges": [{"text": f"song {n}", "tone": "muted", "hint": written_hex(r)},
                           *badges],
                "sections": sections}


# ---------------------------------------------------------------------------
# Voices — every voice line, by speaker, with the message it goes with
# ---------------------------------------------------------------------------

def _number_of(r) -> str:
    """A speaker's kind and number, put after their name: " (character 11)"."""
    return f" ({r.kind} {r.id[0]})"


class VoicesProvider:
    """Every voice line, by who says it, with the message it goes with.

    A voice is one of the 103 lines the game streams from _AUDIO.XA:
    xa_voice_get (0x800238BC) gives its channel and sectors from
    g_XaVoices (formats.xa_voices). A script plays one with commands 0x52
    and 0x53 (ScriptCommandVoiceSet (0x8005E9FC), ScriptCommandVoiceStart
    (0x8005EA44)); a bromide plays one of its own (PictureXaPlay
    (0x800247AC)). No table ties a voice to a message: the message it goes
    with is the one the window shows while it plays, read from the
    commands around it (formats.script_voices). A battle plays voices of
    its own: a spell's or a monster attack's show, four set battles and a
    revive (records.battle_voices). Its speakers are who the portraits of
    its messages name (MessageFaceSet (0x8005B36C)) and who the battle
    plays it for as they act: the caster of the spell or the attack, the
    battle's monster, the one who revives; it is listed under their name
    when they all have one.

    The sound is Form 2 audio, which an extracted file has lost: it is read
    from the disc image, as a movie's is.
    """

    name = "Voices"
    key = "voices"
    fan_about = """
    Every spoken line in the game, under who says it: the words on screen
    while it plays, and where it plays — in a scene, with a bromide or in
    a battle, as a spell or an attack is cast.
    """
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL", "_AUDIO.XA")
    supports_zoom = False
    supports_grid = False
    supports_layers = False

    #: Voice n is its own row.
    homes = {"voice": (None,)}
    #: The groups after the speakers', in this order.
    LATER = ("More than one speaker", "No portrait", "Over a scene", "With the bromides",
             "In battle", "Not played")
    PRODUCER = "decoders.plugins.SLUS_006_28.formats.xa_voices"

    def get_views(self):
        return []

    def get_layer_options(self):
        return []

    @staticmethod
    def holds(item, r, ctx) -> bool:
        return item[0] == "voice" and item[1] == r.id[0]

    def get_items(self, cache, archive, ctx, selected):
        from viewer_tabs.links import voices as lv
        model = GameModel.for_ctx(ctx)
        if model.names is None:
            return [(no_names(model.twin.ctx, "The voices are found through the program's "
                                              "tables"), None)]
        try:
            v = lv.voices(model)
        except Exception as ex:
            return [(f"The voices could not be read: {type(ex).__name__}: {ex}", None)]
        rows = []
        for n, voice in sorted(v.table.items()):
            group, note = lv.heading(model, n)
            u = v.uses.get(n)
            speaker = u.speaker if u is not None else None
            # the speakers by name (two of one name share a heading), the
            # rest of the speakers after them by reference (characters with
            # no name, then portraits by number), then the rest
            name = lv.speaker_name(model, u) if u is not None else None
            order = ((0, 0, name.casefold(), ()) if name else
                     (0, 1, speaker.kind, speaker.id) if speaker is not None else
                     (1, self.LATER.index(group) if group in self.LATER else len(self.LATER),
                      "", ()))
            what = self._what(model, u, n)
            where = sorted({p.script for p in u.plays}) if u is not None else []
            sub = [f"voice {n}", f"{voice.seconds:.1f} s"]
            if where:
                sub.append(f"script {where[0]}" + (f" and {len(where) - 1} more" if len(where) > 1
                                                  else ""))
            rows.append((order, n, "  ".join([what, *sub]), ("voice", n, group, note)))
        return [(label, item) for _o, _n, label, item in sorted(rows)]

    @staticmethod
    def _what(model, u, n: int) -> str:
        """What a voice's row is titled: its first message's words, or
        what a battle plays it for."""
        from viewer_tabs.links import voices as lv
        said = u.said if u is not None else []
        return (lv.quote(said[0].text, 40) if said else
                lv.battle_word(model, u) if u is not None and u.battle else f"voice {n}")

    def item_identity(self, label, item, ctx) -> Identity:
        """A voice by its number, compared by its place in _AUDIO.XA, the
        file, what the disc's scripts play it with and its row's words."""
        from decoders.plugins.SLUS_006_28.formats import xa_voices as xv
        from viewer_tabs.identity import file_digest
        from viewer_tabs.links import voices as lv
        n = item[1]

        def parts():
            v = lv.voices(GameModel.for_ctx(ctx))
            voice = v.table[n]
            u = v.uses.get(n)
            plays = [(p.script, p.play.set_at, p.play.start_at,
                      [(s.number, s.when) for s in p.said]) for p in (u.plays if u else [])]
            fought = [(b.by, b.how) for b in (u.battle if u else [])]
            xa = ctx.path(xv.FILE_NAME)
            return [repr((voice.channel, voice.start, voice.end)).encode(), label.encode(),
                    repr(plays).encode(), repr(fought).encode(),
                    file_digest(xa).encode() if xa.exists() else b""]
        return of_parts(f"voice {n}", parts)

    # -- the page -----------------------------------------------------------

    def on_select(self, item, cache, archive, ctx):
        if item is None:
            return SelectResult(info="No voices")
        from viewer_tabs.links import voices as lv
        from viewer_tabs.voice_audio import VoiceFile
        n, group = item[1], item[2]
        model = GameModel.for_ctx(ctx)
        v = lv.voices(model)
        voice = v.table[n]
        u = v.uses.get(n) or lv.Use(n)
        sections = [s for s in (self._says(model, u), self._who(model, u),
                                self._where(model, u), self._file(v, voice),
                                proven_by_section(self.PRODUCER)) if s]
        audio, problem = None, ""
        try:
            wav = VoiceFile.for_ctx(ctx).wav(voice)
            if wav:
                # the transport leads with who says what in Fan mode
                who = lv.speaker_name(model, u)
                what = self._what(model, u, n)
                audio = {"wav": wav, "name": f"voice-{n}",
                         "title": f"{who}: {what}" if who else what}
            else:
                problem = "Its sectors hold no audio of its channel."
        except (LookupError, OSError, ValueError) as ex:
            problem = f"Not played: {ex}."
        if problem:
            sections.insert(0, {"title": "The sound", "note": problem})
        badges = [{"text": f"voice {n}", "tone": "muted", "hint": f"voice {n:#04x}"},
                  {"text": f"{voice.seconds:.1f} seconds", "tone": "muted",
                   "hint": f"{voice.sectors} sectors at 150 a second"},
                  {"text": group, "tone": "info" if u.speaker is not None else "muted"}]
        sheet = {"title": lv.title(model, n), "subtitle": "a voice line", "badges": badges,
                 "sections": sections}
        return SelectResult(sheet=sheet, audio=audio, info=f"voice {n}", ref=ref("voice", n))

    @staticmethod
    def _says(model, u) -> dict:
        from viewer_tabs.links import voices as lv
        if not u.said:
            note = ("It plays over a scene: no message is up while it plays."
                    if u.plays else "A battle plays it, with no message." if u.battle else
                    "Nothing plays it, so no message goes with it.")
            return {"title": "What it goes with", "note": note}
        rows = [[f"message {s.script}/{s.number}", " ".join(s.whole.split()),
                 lv.WHEN[s.when]] for s in u.said]
        return {"title": "What it goes with", "cite": "formats.script_voices",
                "table": {"columns": ["Message", "Its words", "When"], "rows": rows,
                          "align": ["left", "left", "left"]},
                "fanNote": "",
                "note": "A message is up as the voice starts when the script left it in the "
                        "window, not closed; one comes up while it plays when the script shows "
                        "it after the voice starts and before anything in the code can have "
                        "ended the voice or waited for the player."}

    @staticmethod
    def _who(model, u) -> dict:
        from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
        from viewer_tabs.links import battle
        from viewer_tabs.links import voices as lv
        if not u.speakers:
            return {"title": "Who says it",
                    "note": ("The code names no speaker: the messages it goes with show no "
                             "portrait." if u.said else
                             "The code names no speaker: no message goes with it.")}
        faces = battle._faces(model)
        pictures = []
        shown = set()
        for p in u.portraits:
            got = faces.portraits.get(p)
            if got is not None and any(got[2]):
                who = whose.speaker(model, p)
                caption = (f"{whose.word(model, who)}, portrait {p}" if who.kind == "character"
                           else f"portrait {p}")
                pictures.append({"image": fb.image(got[2], faces.colours),
                                 "caption": caption, "ref": ref("portrait", p)})
                shown.add(who)
        for c in u.casters:
            if c.kind != "character" or c in shown or not 1 <= c.id[0] <= whose.PARTY_LAST:
                continue
            p = fb.member_face(c.id[0])
            got = faces.portraits.get(p)
            if got is not None and any(got[2]):
                pictures.append({"image": fb.image(got[2], faces.colours),
                                 "caption": f"{whose.word(model, c)}, portrait {p}",
                                 "ref": ref("portrait", p)})
        # why, with what proves it (Advanced) and without (Fan)
        why: list[tuple[str, str]] = []
        if u.said_speakers:
            why.append(("The portraits of the messages it goes with name them",
                        " (MessageFaceSet (0x8005B36C), viewer_tabs.whose)"))
        if u.casters:
            why.append(("A battle plays it as they act", " (records.battle_voices)"))
        name = lv.speaker_name(model, u)
        if name or u.speaker is not None:
            who = f"{name or lv._speaker_word(model, u.speaker)}. "
        else:
            who = f"Not one speaker: {lv.speaker_words(model, u)}. "
        out = {"title": "Who says it", "cite": "MessageFaceSet (0x8005B36C)",
               "note": who + " ".join(f"{w}{proof}." for w, proof in why),
               "fanNote": who + " ".join(f"{w}." for w, _proof in why)}
        if u.casters:
            out["table"] = {"columns": ["Who", "As it plays"],
                            "rows": [[lv._speaker_word(model, c) + _number_of(c),
                                      lv._listed(lv.acts(u, c), 6)] for c in u.casters],
                            "align": ["left", "left"]}
        if pictures:
            out["pictures"] = pictures
        return out

    @staticmethod
    def _where(model, u) -> dict:
        from viewer_tabs import links
        from viewer_tabs.links import world
        if not u.plays and not u.bromides and not u.battle:
            return {"title": "Where it plays",
                    "fanNote": "Nothing in the game plays it.",
                    "note": "Nothing plays it. VoiceSet (0x80055470) is called by the "
                            "scripts' command 0x52, the bromides (PictureXaPlay "
                            "(0x800247AC)) and the battles (records.battle_voices), and "
                            "none of them names it."}
        w = world._world(model)
        rows = []
        for p in u.plays:
            labels = [lab for sid, lab in u.labels if sid == p.script and lab in p.play.labels]
            labels = labels or p.play.labels
            with_ = (", ".join(f"message {p.script}/{s.number}" for s in p.said)
                     if p.said else "no message")
            rows.append([w.script_title(p.script) or "no map loads it as its own",
                         f"script {p.script}",
                         ", ".join(str(lab) for lab in labels[:6])
                         + (" …" if len(labels) > 6 else ""), with_])
        names = model.names
        for k in u.bromides:
            rows.append([(names.bromide(k) if names else None) or f"bromide {k}",
                         f"bromide {k}", "", "while it is shown"])
        for b in u.battle:
            rows.append(["in battle", links.title_of(model, b.by), "", b.how])
        return {"title": "Where it plays", "cite": "ScriptCommandVoiceStart (0x8005EA44)",
                "table": {"columns": ["Where", "Played by", "Labels", "With"], "rows": rows,
                          "align": ["left", "left", "left", "left"]}}

    @staticmethod
    def _file(v, voice) -> dict:
        fields = [
            ["Channel", f"{voice.channel} of 16"],
            ["Sectors", f"{voice.start} to {voice.end} of _AUDIO.XA",
             f"{voice.channel_sectors} sectors of its channel"],
            ["Table row", f"g_XaVoices + {voice.number} × 2 = {voice.entry:#06x}"],
            ["End", f"{'the next row' if voice.by_next else 'g_XaChannelEnds'} less {voice.less}, "
                    f"× 16"],
            ["Lasts", f"{voice.seconds:.2f} seconds", "150 sectors a second"],
        ]
        return {"title": "In _AUDIO.XA", "cite": v.proof, "fields": fields, "extended": True}


# ---------------------------------------------------------------------------
# Sound effects — every sound effect, and where the game plays it
# ---------------------------------------------------------------------------

class SoundEffectRow(NamedTuple):
    """A Sound effects row: a sound effect as one bank plays it, and
    whether it is its number's home (the row a link to the number opens)."""
    effect: Any                 # links.sound_effects.Effect
    home: bool
    group: str
    note: str


class SoundEffectsProvider:
    """Every sound effect, and where the game plays it.

    A sound effect is a number the game hands SoundPlay (0x800555F0)
    (records.sound_effects). Numbers 1 to 24 are the common bank's, one
    sound wherever they play; in battle the numbers from 31 are the
    battle bank's; from 131 a number is looked up in the sound ids
    (g_SoundIds (0x800E4CD8)) of the bank the map's sound area loads
    (g_SoundMapAreas (0x800AF7A8), g_SoundAreaBankPairs (0x800AF694)), so
    each place has its own sound for it, or none. A row is a number as one
    bank plays it: a number of the places can have several rows.

    What plays one is what the code shows (viewer_tabs.links.sound_effects):
    a map's entrances (MapChange (0x8005922C)) and tile changes
    (MapBgChangeStart (0x80059900)), the scripts' command 0x31
    (ScriptCommandSoundPlay (0x8005E524)) on the maps that run them, the
    monsters' rows in battle, and the calls whose number the code writes
    (the menus, a chest, a notice, the battle's hits). A sound the code
    only reaches through a table not read here (the map objects that see
    the party, a battle show's own sounds) is said to be played by nothing
    found.

    A sound effect plays live through its bank, as Sound banks plays a
    sequence.
    """

    name = "Sound effects"
    key = "sound-effects"
    fan_about = """
    Every sound effect, and where the game plays it: going through an
    entrance, as a tile changes, in a scene, in battle, in the menus. The
    common sounds are the same everywhere; from a certain number on, each
    place has sounds of its own, so one number can sound different from
    place to place, or not at all.
    """
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = False
    supports_grid = False
    supports_layers = False

    #: `sound effect 13` and `sound effect 300/131` are their rows; a
    #: place's number written without its bank, the place's sound most
    #: things play.
    homes = {"sound-effect": (None,)}
    PRODUCER = "decoders.plugins.SLUS_006_28.records.sound_effects"

    def __init__(self):
        #: the banks, read and played as Sound banks reads and plays them
        self._scores = SoundBanksProvider()

    def get_views(self):
        return []

    def get_layer_options(self):
        return []

    @staticmethod
    def holds(item, r, ctx) -> bool:
        if r.kind != "sound-effect" or item is None:
            return False
        e = item.effect
        return e.ref == r or (len(r.id) == 1 and item.home and e.number == r.id[0])

    def get_items(self, cache, archive, ctx, selected):
        from viewer_tabs.links import sound_effects as lsx
        from viewer_tabs.refs import written
        model = GameModel.for_ctx(ctx)
        if model.names is None:
            return [(no_names(model.twin.ctx, "The sound effects are found through the "
                                              "program's tables"), None)]
        try:
            sfx = lsx.sound_effects(model)
        except Exception as ex:
            return [(f"The sound effects could not be read: {type(ex).__name__}: {ex}", None)]
        rows = []
        for e in sfx.listed():
            group, note = lsx.HEADINGS[e.group]
            rows.append((f"{written(e.ref)}  {sfx.heard(e)}",
                         SoundEffectRow(e, sfx.home(e.number) is e, group, note)))
        return rows

    def _bank(self, ctx, resource: int):
        self._scores._ensure_loaded(ctx)
        return next((b for b in self._scores._banks or [] if b.resource == resource), None)

    def item_identity(self, label, item, ctx) -> Identity:
        """A sound effect by its number and its bank, compared by the
        sequence's bytes, the bank's samples and its row's words."""
        from decoders.config import SECTOR_SIZE
        from decoders.plugins.SLUS_006_28.formats import sound_banks as sb
        from viewer_tabs.refs import written
        e = item.effect

        def parts():
            b = self._bank(ctx, e.bank)
            if b is None:                   # on_select says it could not be read
                return [b"no bank", str(e.bank).encode(), label.encode()]
            with open(ctx.path("LUNADATA.FIL"), "rb") as f:
                f.seek(b.sector * SECTOR_SIZE)
                raw = f.read(b.size)
            vab = [raw[c.payload_offset:c.payload_offset + c.size] for c in b.chunks
                   if c.kind in (sb.CMD_VAB_HEAD, sb.CMD_VAB_BODY)]
            seq = b.seq_data[e.sequence] if len(b.seq_data) == len(b.seqs) else b""
            return [seq, *vab, label.encode()]
        return of_parts(written(e.ref), parts)

    # -- the page -----------------------------------------------------------

    def on_select(self, item, cache, archive, ctx):
        if item is None:
            return SelectResult(info="No sound effects")
        from viewer_tabs.links import sound_effects as lsx
        from viewer_tabs.refs import written
        model = GameModel.for_ctx(ctx)
        sfx = lsx.sound_effects(model)
        e = item.effect
        n = e.number
        bank = self._bank(ctx, e.bank)
        audio = music = None
        facts = []
        badges = [{"text": item.group, "tone": "info", "hint": item.note}]
        if bank is None or e.sequence >= len(bank.seqs):
            why = f": {self._scores._error}" if self._scores._error else ""
            facts.append(["Its sound", f"sound bank {e.bank} could not be read{why}", ""])
        else:
            seq = bank.seqs[e.sequence]
            walked = self._scores._walk(seq, bank)
            name = "sound-effect-" + "-".join(str(i) for i in e.ref.id)
            audio = self._scores._audio(seq, bank, name, walked)
            audio.update(title=written(e.ref), kind="sound-effect")
            music = self._scores._score(seq, bank, name, walked, lambda stats: {})
            secs, endless = self._scores._length(bank, e.sequence)
            facts.append(["Length", f"{secs:.1f} seconds",
                          "until it repeats" if endless else ""])
            if endless:
                facts.append(["Repeats", "for ever, until the game stops it", ""])
            badges.insert(0, {"text": f"{secs:.1f} s", "tone": "muted",
                              "hint": f"{secs:.2f} seconds"})
        facts.append(["The number", self._number_words(e), ""])
        same = [written(o.ref) for o in sfx.same(e)]
        if same:
            facts.append(["The same sound as", ", ".join(same),
                          "the same sequence of the same bank"])
        others = lsx.elsewhere(sfx, e)
        if others:
            facts.append(["Its number elsewhere",
                          f"{len(others)} other place{'s' if len(others) != 1 else ''}' "
                          f"sound{'s' if len(others) != 1 else ''} for {n}: "
                          + lsx._listed([f"{written(o.ref)} on {sfx.places(o.maps)[0]}"
                                         if o.maps else written(o.ref) for o in others], 3),
                          "each listed as its own row"])
        sections = []
        if audio is not None:
            sections.append({"title": "", "sound": True})
        sections.append({"title": "The sound effect", "style": "prose", "fields": facts})
        sections.append(self._where(model, sfx, e))
        calls = [u for u in e.uses if u.by is None]
        if calls:
            sections.append({"title": "What the game plays it for", "style": "prose",
                             "fields": [[u.what, "in battle" if u.battle else "on the field",
                                         ""] for u in calls]})
        sections.append(self._extended(model, sfx, e, calls))
        info = [written(e.ref), f"sound bank: {e.bank}",
                f"sequence: {e.bank}/{e.sequence}", sfx.heard(e)]
        sheet = {"title": written(e.ref), "subtitle": lsx.subtitle(sfx, e),
                 "badges": badges, "sections": sections}
        return SelectResult(sheet=sheet, audio=audio, music=music, info="\n".join(info),
                            ref=e.ref)

    @staticmethod
    def _number_words(e) -> str:
        from viewer_tabs.links import sound_effects as lsx
        if e.group == lsx.COMMON:
            return (f"{e.number}, one of the common sounds, numbers 1 to 24: the same sound "
                    f"wherever the game plays it")
        if e.group == lsx.BATTLE:
            return (f"{e.number}, one of the battle's sounds: in a fight, numbers from 31 "
                    f"are the battle bank's")
        return (f"{e.number}, one of the place's own sounds: each place has its own sound "
                f"for a number from 131, and this is the one of the places below; it is "
                f"written with its place's sound bank first, {e.bank}")

    @staticmethod
    def _where(model, sfx, e) -> dict:
        """What plays it, under its places (the debug room last), then in
        battle; what SoundPlay refuses, said."""
        from viewer_tabs import links
        from viewer_tabs.links import scenes
        from viewer_tabs.links import sound_effects as lsx
        battle: list = []
        found = []
        for u in e.uses:
            if u.by is None or u.refused:
                continue
            if u.battle:
                battle.append(links.link_json(model, u.by, u.what))
                continue
            found.append((tuple(sorted(u.maps)), u))
        # each thing once, under all of its places together (links.scenes)
        by_places: dict[str, list] = {}
        for heading, every, u in lsx.by_places(sfx, found):
            link = links.link_json(model, u.by, u.what + lsx._at(heading, every))
            had = by_places.setdefault(heading, [])
            if all(h["ref"] != link["ref"] for h in had):
                had.append(link)
        groups = [{"title": place if place != lsx.NO_MAP else lsx.scene_heading(place),
                   "dir": "in", "links": found} for place, found in by_places.items()]
        if battle:
            groups.append({"title": "In battle", "dir": "in", "links": battle})
        # the pieces whose code holds the command: with the extended info in Fan
        try:
            groups += [g for g in links.groups(model, links.LinkIndex.of(model), e.ref)
                       if g["title"] == scenes.HELD_IN]
        except Exception:
            pass                        # the index says why
        notes = []
        refused = [u for u in e.uses if u.refused]
        if refused:
            notes.append("Some ask for it where the game refuses its number: "
                         + lsx._listed(list(dict.fromkeys(lsx._use_word(u) for u in refused)))
                         + (" in battle" if all(u.battle for u in refused) else "")
                         + ". There the game plays sound effect 2's sound in its place.")
        if not groups and not any(u.by is None for u in e.uses):
            notes.append("Nothing found plays it. Its number is played by the code for the "
                         "map objects that see the party and by a battle's shows, through "
                         "tables not read here." if e.group != lsx.COMMON else
                         "Nothing found plays it: no entrance, tile change, script, monster "
                         "or call of the code read here names its number.")
        if not groups and not notes:
            notes.append("No place or scene plays it: the game's own code does, "
                         "for what the next section lists.")
        out = {"title": "Where it plays", "cite": "SoundPlay (0x800555F0)"}
        if groups:
            out["links"] = groups
        if notes:
            out["note"] = "\n\n".join(notes)
        return out

    def _extended(self, model, sfx, e, calls) -> dict:
        from decoders.plugins.SLUS_006_28.records import sound_effects as se
        from viewer_tabs import links
        from viewer_tabs.links import sound_effects as lsx
        from viewer_tabs.refs import KINDS, number_hex, written
        r = e.ref
        bank_words = ("the common bank, loaded into bank slot 0 (sound_common_load "
                      "(0x80023E00))" if e.group == lsx.COMMON else
                      "the battle's bank, loaded into bank slot 1 in battle" if e.group ==
                      lsx.BATTLE else
                      "the bank of the place's sound area, loaded into bank slot 1 "
                      "(sound_area_load (0x80023F78))")
        fields = [
            ["The code's name", KINDS["sound-effect"].code, ""],
            ["Number", f"{written(r)} · {number_hex(r)}", ""],
            ["Sound bank", f"resource {e.bank}: {bank_words}", ""],
            ["Sequence", f"sequence {e.bank}/{e.sequence}", ""],
        ]
        if e.group == lsx.PLACE:
            ids = sfx.ids.get(e.bank, ())
            fields.append(["Found by", f"g_SoundIds (0x800E4CD8) entry {e.sequence}: the "
                                       f"bank's command 17 holds {len(ids)} numbers "
                                       f"(sound_id_table_set (0x800244E4))", ""])
            fields.append(["Sound area", ", ".join(dict.fromkeys(
                f"{sfx.tables.area(m)}" for m in e.maps)) + " (g_SoundMapAreas (0x800AF7A8) of "
                "its maps' numbers)", ""])
        for u in calls:
            fields.append([u.what, u.proof, ""])
        dec_proof = [p for p in (proven_by_section(self.PRODUCER) or {}).get("list", [])]
        fields.append(["Proven by", ", ".join(dec_proof or [se.SOUND_PLAY]), ""])
        plays = [ref("sound-bank", e.bank), ref("sequence", e.bank, e.sequence)]
        return {"title": "Extended info", "extended": True, "fields": fields,
                "links": [{"title": "Plays from", "dir": "out",
                           "links": [links.link_json(model, p) for p in plays]}]}


# ---------------------------------------------------------------------------
# Video — STR streaming movies, on ANY disc
# ---------------------------------------------------------------------------

class MoviesProvider:
    """STR movie containers, found by CONTENT rather than by filename.

    Every Lunar disc names its movies differently — SSSC ships `_B000.STR`,
    Lunar 2 ships `S02.STR`, the making-of discs ship `LUNAR2_1.STR` — so a
    filename filter is a per-title guess. `str_stream.looks_like_str_sector`
    is a structural test on the 32-byte sector header, which is a PS1 fact
    and works on all of them.

    Everything in the summary is READ OUT OF THE STREAM
    (`decoders.psx.formats.str_stream`), not assumed from what PS1
    FMV is "typically" like: this tab used to assert 320x224 for every file
    on every disc, and SSSC's movies are 224x192.

    Frames are decoded through `decoders.psx.formats.mdec`, and every
    one shown has passed `mdec.check_frame` — a frame whose decode does not
    hold to the stream's own invariants is skipped, not displayed.
    """

    name = "Movies"
    key = "movies"
    fan_about = """
    The game's movies: the animated scenes it plays as the story goes on,
    with their sound. Each plays here as it does in the game; Frame holds
    one picture of it to look at closely or save.
    """
    technical_view = "Details"
    supports_zoom = True
    supports_grid = False
    supports_layers = False

    #: Play first: this is the video tab. The still stays one click away
    #: for a zoomable, exportable frame.
    VIEWS = ("Play", "Frame", "Details")
    views_change_items = False
    #: A movie is listed in every view, by its file.
    homes = {"movie": VIEWS}

    #: Where in the stream to sample. Frame 0 of a PS1 FMV is usually the
    #: flat lead-in, so a still taken there says nothing about the movie.
    #: This is a documented sampling choice, and the frame number actually
    #: sampled is always reported next to the picture.
    SAMPLE_FRACTION = 0.25

    #: Sectors read at the sample point. 400 x 2048 = 800 KB, ~60 frames at
    #: the 6-sectors-per-frame these streams mostly use: room to find one
    #: that decodes cleanly past a window that starts mid-frame, without
    #: holding a 529 MB documentary in memory.
    WINDOW_SECTORS = 400

    #: How many sectors to read while looking for the stream's first STR
    #: sector. A .STR legitimately opens with interleaved XA audio, so
    #: sector 0 is not guaranteed to carry a video header.
    PROBE_SECTORS = 64

    #: Sectors per second at 2x CD speed — the rate PS1 FMV streams at.
    #: Used ONLY for the duration estimate, which is labelled as one.
    SECTORS_PER_SECOND = 150

    def __init__(self):
        self._probes: dict[Path, dict | None] = {}
        self.view = self.VIEWS[0]

    def get_views(self):
        return list(self.VIEWS)

    # -- detection ---------------------------------------------------------

    def _head(self, path: Path) -> bytes:
        from decoders.psx.formats.str_stream import SECTOR_SIZE
        with path.open("rb") as fh:
            return fh.read(SECTOR_SIZE * self.PROBE_SECTORS)

    def _probe(self, path: Path) -> dict | None:
        """-> probe dict for an STR file, or None when it is not one.

        Cached per path: the item list probes every candidate, and these
        files run to hundreds of megabytes.
        """
        if path in self._probes:
            return self._probes[path]

        result = None
        try:
            from decoders.psx.formats.str_stream import (
                SECTOR_SIZE, iter_str_sectors, probe,
            )
            head = self._head(path)
            first = next(iter_str_sectors(head), None)
            if first is not None:
                offset, _ = first
                result = probe(head[offset:])
                # probe() counts the sectors it was HANDED; the real count is
                # the whole file, which is what the frame count needs.
                sectors = (path.stat().st_size - offset) // SECTOR_SIZE
                per_frame = result["sectors_per_frame"]
                result["first_sector_offset"] = offset
                result["sectors"] = sectors
                result["frames"] = sectors // per_frame if per_frame else 0
        except (OSError, ValueError, StopIteration):
            result = None

        self._probes[path] = result
        return result

    # -- provider interface ------------------------------------------------

    def get_items(self, cache, archive, ctx, selected):
        items = []
        for name in ctx.files:
            path = ctx.path(name)
            info = self._probe(path)
            if info is None:
                continue
            size_mb = path.stat().st_size / (1024 * 1024)
            geom = (f"{info['width']}x{info['height']}"
                    if info["mdec"] else "no MDEC header")
            # The game's own title first where it has one; the file after it.
            title = self._title(ctx, name)
            items.append((f"{title + '  ' if title else ''}{name}  {geom}  ({size_mb:.1f}MB)",
                          (name, path)))
        if not items:
            return [("No STR streams in this dump", None)]
        return items

    def fan_row(self, label, data, ctx) -> dict | None:
        """A movie in Fan mode: its number where the game numbers it, and
        how long it plays (its sectors at 150 a second, as the duration in
        Details is estimated) — not its file, size or picture size."""
        name, path = data
        info = self._probe(path)
        if info is None:
            return None
        r = self._movie_ref(ctx, name)
        parts = [f"movie {r.id[0]}"] if r is not None else []
        if info["mdec"]:
            seconds = int(info["sectors"] / self.SECTORS_PER_SECOND)
            parts.append(f"about {seconds // 60}:{seconds % 60:02d}")
        return {"sub": " · ".join(parts)}

    def item_identity(self, label, data, ctx) -> Identity:
        """A movie is its file: the Japanese _B001.STR is the US one's
        other version."""
        name, path = data
        return of_file(name, path)

    @staticmethod
    def _movie_ref(ctx, name: str):
        """Movie n, for the file MoviePlay (0x800232D4) plays as n, on the
        programs that number movies so (records.events)."""
        if ctx.program not in SSSC_PROGRAMS:
            return None
        from decoders.plugins.SLUS_006_28.records import events
        n = events.movie_number(name)
        return ref("movie", n) if n is not None else None

    @classmethod
    def holds(cls, data, r, ctx) -> bool:
        return data is not None and cls._movie_ref(ctx, data[0]) == r

    @staticmethod
    def _title(ctx, name: str) -> str | None:
        """The game's title for a movie file, where the program names it
        (SSSC: the theater's caption — records.events, system_strings)."""
        names = GameNames.for_ctx(ctx)
        return names.movie_file(name) if names else None

    @staticmethod
    def _shape(ctx, info: dict) -> tuple[tuple[int, int] | None, str]:
        """How the game shows this movie on a TV: a pixel's shape, and why.

        Only a program whose movie player has been read says (SSSC:
        records.movie_display); any other movie is shown with square
        pixels, and the note says so.
        """
        from decoders.plugins.SLUS_006_28.records import PROGRAM
        if getattr(ctx, "program", None) != PROGRAM or not info.get("mdec"):
            return None, ("shown with square pixels: this program's movie "
                          "player has not been read")
        from decoders.plugins.SLUS_006_28.records import movie_display
        w, h = info["width"], info["height"]
        mode = movie_display.movie_mode(w, h)
        pixel = mode.pixel_aspect
        picture = w * pixel / h
        near = picture.limit_denominator(16)
        shape = (f"{near.numerator}:{near.denominator}" if near == picture
                 else f"{float(picture):.2f}:1")
        return ((pixel.numerator, pixel.denominator),
                f"the game shows it in the {mode.width}-wide mode "
                f"({movie_display.PLAYER}): pixels "
                f"{pixel.numerator}:{pixel.denominator}, a {shape} picture")

    def _summary(self, ctx, name: str, path: Path, info: dict) -> dict:
        title = self._title(ctx, name)
        fields = self._detail_fields(path, info)
        if info["mdec"]:
            fields.insert(next(i for i, f in enumerate(fields)
                               if f[0] == "Resolution") + 1,
                          ("On a TV", self._shape(ctx, info)[1]))
        if title:
            fields = [("Title", f"{title}  (the theater's caption: entry n + 1 plays "
                               f"_Bnnn.STR, string 0x500 + entry)")] + fields
        return {"title": f"{name} — {title}" if title else name, "fields": fields}

    def get_layer_options(self):
        return []

    # -- frames ------------------------------------------------------------

    def _decode_window(self, path: Path, count: int):
        """-> [(StrFrame, DecodedFrame)] sampled SAMPLE_FRACTION into the file.

        Only frames whose decode satisfies `mdec.check_frame` are returned.
        A window that starts mid-frame yields a bogus leading group, and a
        bogus group is exactly what those invariants reject — so the filter
        that keeps the preview honest also handles the seek.
        """
        from decoders.psx.formats.str_stream import (
            SECTOR_SIZE, iter_frames,
        )
        from decoders.psx.formats import mdec

        size = path.stat().st_size
        start = int(size * self.SAMPLE_FRACTION) // SECTOR_SIZE * SECTOR_SIZE
        with path.open("rb") as fh:
            fh.seek(start)
            window = fh.read(SECTOR_SIZE * self.WINDOW_SECTORS)

        out = []
        for frame in iter_frames(window):
            try:
                decoded = mdec.decode_frame(frame.bitstream,
                                            frame.width, frame.height)
            except mdec.MdecError:
                continue
            if mdec.check_frame(decoded):
                continue
            out.append((frame, decoded))
            if len(out) >= count:
                break
        return out

    @staticmethod
    def _image(decoded):
        """-> RGBA. The view composites every image it is given, and
        `composite_layers` is alpha compositing — an RGB image reaches it
        as a mode mismatch, not as an opaque one."""
        return Image.frombytes("RGB", (decoded.width, decoded.height),
                               decoded.rgb).convert("RGBA")

    # -- provider interface ------------------------------------------------

    def on_select(self, item_data, cache, archive, ctx):
        result = self._show(item_data, ctx)
        if item_data is not None:
            result.ref = self._movie_ref(ctx, item_data[0])
        return result

    def _show(self, item_data, ctx):
        if item_data is None:
            return SelectResult(
                info="No STR streams found",
                text=("Nothing in this dump has an STR sector header.\n\n"
                      "Movies on a PS1 disc can also live outside the "
                      "filesystem as raw XA/CD-DA; those are not files and "
                      "do not appear here."),
            )

        name, path = item_data
        info = self._probe(path)
        title = self._title(ctx, name)
        heading = f"{title} — {name}" if title else name
        if not info["mdec"]:
            return SelectResult(
                info=f"{heading}\nSTR container, non-MDEC channel",
                summary=self._summary(ctx, name, path, info),
            )

        if self.view == "Details":
            return SelectResult(
                info=f"{heading}\n{info['width']}x{info['height']}",
                summary=self._summary(ctx, name, path, info),
            )

        if self.view == "Play":
            return self._play(name, path, ctx, info)

        decoded = self._decode_window(path, 1)
        if not decoded:
            return SelectResult(
                info=f"{heading}\nno decodable frame at the sample point",
                text=("No frame at the sample point decoded cleanly.\n\n"
                      "Frames are only shown when they satisfy the stream's\n"
                      "own invariants (mdec.check_frame): block count from\n"
                      "the geometry, the header's MDEC code bound, and the\n"
                      "bitstream consumed to within its padding.\n\n"
                      "A v3 bitstream lands here too — its differential DC\n"
                      "is refused rather than decoded as v2."),
            )

        first_frame, first = decoded[0]
        shared = (f"{heading}\n{first.width}x{first.height}  "
                  f"q_scale {first.header.q_scale}  v{first.header.version}\n"
                  f"decoded from frame {first_frame.frame_no} "
                  f"({self.SAMPLE_FRACTION:.0%} into the stream)")
        aspect, shape_note = self._shape(ctx, info)
        raw = (f"\nraw pixels here; {shape_note}" if aspect else "")
        return SelectResult(
            images=[self._image(first)],
            info=(f"{shared}\n{first.blocks} blocks, {first.codes} MDEC codes"
                  f"{raw}"),
        )

    def _play(self, name: str, path: Path, ctx, info: dict) -> SelectResult:
        """Hand the app this movie's sectors to stream.

        Audio lives in Form 2 sectors that an ISO extractor truncates, so
        real playback reads the DISC IMAGE and the extracted file is the
        video-only fallback. Which one is in use is stated on screen rather
        than left for the user to infer from silence.
        """
        image_path, lba, sectors = None, 0, path.stat().st_size // 2048
        track, _why = raw_track(ctx.source)
        if track is not None:
            try:
                from decoders.psx.disc.iso_reader import DiscImage, find_file
                with DiscImage(track) as image:
                    entry = find_file(image, name)
                if entry is not None:
                    image_path = track
                    lba, sectors = entry.lba, entry.size // 2048
            except (OSError, ValueError):
                image_path = None

        title = self._title(ctx, name)
        heading = f"{title} — {name}" if title else name
        aspect, shape_note = self._shape(ctx, info)
        movie = MovieSource(heading, image_path, lba, sectors, fallback=path,
                            pixel_aspect=aspect, shape_note=shape_note)
        note = ("reading raw sectors from the disc image"
                if image_path is not None else
                "video only — no disc image, and an extracted .STR has its "
                "audio sectors truncated")
        return SelectResult(
            movie=movie,
            info=(f"{heading}\n{info['width']}x{info['height']}  "
                  f"{int(movie.duration // 60)}m{int(movie.duration % 60):02d}s\n"
                  f"{note}\n{shape_note}"),
        )

    def _detail_fields(self, path: Path, info: dict) -> list[tuple[str, str]]:
        size = path.stat().st_size
        fields = [
            ("File size", f"{size:,} bytes ({size / 1024 / 1024:.1f} MB)"),
            ("Sectors", f"{info['sectors']:,} x {info['sector_size']} B"),
        ]
        if info["mdec"]:
            seconds = info["sectors"] / self.SECTORS_PER_SECOND
            fields += [
                ("Codec", "MDEC (measured: StTYPE 0x%04X)" % info["type"]),
                ("Resolution", f"{info['width']} x {info['height']}"),
                ("Sectors/frame", str(info["sectors_per_frame"])),
                ("Frames", f"{info['frames']:,}"),
                ("Duration", f"~{int(seconds) // 60}m{int(seconds) % 60:02d}s "
                             f"(estimate: 2x CD, 150 sectors/s)"),
                ("Decoder", "decoders.psx.formats.mdec\n"
                            "container: …formats.str_stream"),
                ("Audio", "interleaved XA ADPCM; Play decodes it from "
                          "the disc image"),
            ]
        else:
            fields.append(("Codec", "STR container, non-MDEC channel"))
        if info["first_sector_offset"]:
            fields.append(("Leading non-STR", f"{info['first_sector_offset']:,} B "
                                              f"(interleaved XA audio)"))
        return fields


# ---------------------------------------------------------------------------
# Sprites — the field's: the map object sets and the party's field sheets
# ---------------------------------------------------------------------------

def _page_strip(pages: list) -> Image.Image | None:
    """Rendered pages one under another, page 0 on top."""
    pages = [p for p in pages if p is not None and p.height]
    if not pages:
        return None
    out = Image.new("RGBA", (max(p.width for p in pages), sum(p.height for p in pages)),
                    (0, 0, 0, 0))
    y = 0
    for p in pages:
        out.paste(p, (0, y))
        y += p.height
    return out


#: How much of its alpha a texel keeps on a page shown for sprites that do
#: not read it.
_DIMMED = 0.2


def _dim_outside(page: Image.Image, rects, slot: int) -> Image.Image:
    """A rendered page with the texels outside `rects`
    (`sprite_pages.texel_rects`) of page slot `slot` faded to `_DIMMED`."""
    from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
    alpha = page.getchannel("A")
    out = page.copy()
    out.putalpha(Image.composite(alpha, alpha.point(lambda a: int(a * _DIMMED)),
                                 sp.texel_mask(rects, slot, page.size)))
    return out


def _as_drawn(page_lines: dict[int, int], rendered: dict[int, dict[int, Image.Image]],
              owners: dict[int, set]) -> tuple[list[Image.Image], int]:
    """Each page with every texel under the palette row of the sprites that
    read it: `rendered` is {row: {slot: page under that row}}, `owners`
    {row: texel rects of the sprites drawn with it}. A texel read under two
    rows is shown under the lower; one no sprite reads is left blank.
    -> (pages in slot order, texels read under more than one row)."""
    from PIL import ImageChops
    from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
    from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
    out, shared = [], 0
    for slot, lines in sorted(page_lines.items()):
        if not lines:
            continue
        img = Image.new("RGBA", (mos.PAGE_WIDTH, lines), (0, 0, 0, 0))
        count = Image.new("L", img.size, 0)
        for row in sorted(rendered, reverse=True):
            rects = owners.get(row)
            src = rendered[row].get(slot)
            if not rects or src is None:
                continue
            mask = sp.texel_mask(rects, slot, img.size)
            count = ImageChops.add(count, mask.point(lambda v: 1 if v else 0))
            img.paste(src, (0, 0), ImageChops.multiply(mask, src.getchannel("A")))
        shared += sum(count.histogram()[2:])
        out.append(img)
    return out, shared


class _BattleSprites:
    """The battle's sprite blocks as BtlDataLoad (0x80018694) and
    BtlPartyLoad (0x8002B114) load them: each monster set's blocks under
    its CLUT B, and the party's from resource 0x197. Read on first use and
    kept, for the Battles tab's fights and the Sprites tab's In battle."""

    def __init__(self, ctx):
        from decoders.psx.analysis.exe_loader import load_exe
        from decoders.plugins.SLUS_006_28.formats.resource_table import load_resource_table
        from decoders.plugins.SLUS_006_28.records import encounters as en
        binary = load_exe(ctx.exe_path)
        if binary.text_start != en.EXE_BASE:
            raise ValueError(f"{ctx.exe_path.name}: text at {binary.text_start:#x}, "
                             f"the battle tables expect {en.EXE_BASE:#x}")
        self.img = binary.code
        self.table = {r.index: r for r in load_resource_table(binary)}
        self.archive = ctx.path("LUNADATA.FIL")
        self._sets: dict[int, tuple] = {}
        self._sheets: dict[tuple, Any] = {}
        self._party = None

    def read(self, res: int) -> bytes:
        return self.table[res].read(self.archive)

    def set(self, set_id: int):
        """-> (monster ids, SetBundle, {page slot: page under CLUT B})."""
        if set_id not in self._sets:
            from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
            from decoders.plugins.SLUS_006_28.records import encounters as en
            res = en.set_resource(self.img, set_id)
            if not res:
                raise ValueError(f"monster set {set_id} names no resource")
            types = en.type_list(self.img, set_id)
            bundle = bg.parse_set_bundle(self.read(res), len(types))
            pages = {p.index: bg.render_page(p, bundle.clut_b) for p in bundle.pages}
            self._sets[set_id] = (types, bundle, pages)
        return self._sets[set_id]

    def party(self):
        if self._party is None:
            from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
            self._party = bg.parse_party_bundle(self.read(bg.PARTY_RESOURCE))
        return self._party

    def sheet(self, key: tuple):
        """-> (scene sheet dict | None, SpriteBlockData | None) for
        ("set", s, j) or ("party", character)."""
        if key not in self._sheets:
            from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
            from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
            from viewer_tabs import scene
            if key[0] == "set":
                _types, bundle, pages = self.set(key[1])
                blk, names = bundle.actor(key[2]), bg.ENEMY_ANIMS
                label = f"monster set {key[1]} block {key[2]}"
            else:
                pb = self.party()
                m = pb.members[key[1]]
                blk, names = m.actor(), bg.PARTY_ANIMS
                pages = {0: bg.render_page(m.page, pb.clut)}
                label = f"character {key[1]}"
            sheet = sp.pose_sheet(blk, pages) if blk is not None else None
            self._sheets[key] = ((scene.sheet_entry(sheet, blk.animations(), label, names)
                                  if sheet else None), blk)
        return self._sheets[key]


class SpritesProvider:
    """The sprites, by who wears them: the party, the story's people, the
    other people, the monsters and the things of the maps, and everyone in
    battle.

    By who lists one entry per look (viewer_tabs.looks): an object set
    carries its own copy of each sprite it needs, and the copies that draw
    the same pixels, the party's field sheets among them, are one look. A
    look is put under who wears it: a party member, by their field sheet;
    an entity the who-rule takes to be the speaker of a portrait no
    character is (viewer_tabs.whose), from the portrait that opens what
    they say (MapPartyTalkCheck (0x80067D1C) runs the label of their definition's
    byte 0xB; the party's own portraits open their comments on whatever
    the party meets, so they name nobody); the other people; the map
    monsters, titled by the battle they start; the chests, triggers and
    what only scenes draw. A look's page plays each of its animations and
    holds each of its poses, under every palette row it is drawn with; its
    card lists every map it stands on.

    In battle has every monster set's blocks and the party's battle
    sprites (resource 407) on their own, each with its anim table
    (BtlDataLoad (0x80018694), BtlPartyLoad (0x8002B114)).

    Object sets lists the party's field sheets and every map object set
    with its sprite data, as the game loads them; Pages shows the pages
    each is drawn from. A map object set is a resource MapObjectsDataLoad
    (0x80065418) reads: its definitions (who stands where), its sprite data
    list and the pages those sprites draw from. The party's sheets are
    resource 488, read by number (MapPartySpriteDataLoad (0x80063D48)). A
    sprite carries no palette: MapRecordInit (0x80065940) picks a row by
    the record's kind — 504 or 505 (resources 229 and 230), or 506, the
    entered map's own — and each sprite is shown under the rows the game
    draws it with. The records put on a set's sprite data are its
    definitions' objects, the actors the scripts that can run on its maps
    make (ScriptCommandMoveChrRowActorSet (0x80061EAC)) and the party
    (MapPartyRecordInit (0x800649DC)).
    """

    name = "Sprites"
    key = "sprites"
    fan_about = """
    Every sprite, by who wears it: the party, the story's people, the
    other people, the monsters and the things on the maps, each playing
    its animations; and everyone as they look in battle.
    """
    technical_view = "Pages"
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = True
    supports_grid = False   # sprites are not on a 16px grid; it only misleads
    supports_layers = True
    views_change_items = True

    VIEWS = ("By who", "In battle", "Pages", "Object sets")
    MOS = "decoders.plugins.SLUS_006_28.formats.map_object_sets"
    PFS = "decoders.plugins.SLUS_006_28.formats.party_field_sheets"
    SP = "decoders.plugins.SLUS_006_28.formats.sprite_pages"
    GFX = "decoders.plugins.SLUS_006_28.formats.battle_gfx"
    KEEP = 4                # parsed sets kept between selections
    PAD = 8
    #: A sprite is the entry of its look in By who; an object set its row
    #: in Object sets and Pages; a battle sprite its row in In battle.
    homes = {"sprite": ("By who",), "object-set": ("Object sets", "Pages"),
             "battle-sprite": ("In battle",)}

    #: Every field frame — GameRun (0x800559F4)'s loop, MapFrameStep
    #: (0x800557D4), ScriptFrameStep (0x8005A1F0) — steps the records once
    #: and ends in MapFrameEnd (0x8005596C), whose frame_end waits VSync(0).
    FIELD_TICK_NOTE = ("one tick per field frame: MapPartyAnimationStep (0x80065CF8) "
                       "and MapObjectsAnimationStep (0x80065FD8) step each record once "
                       "a frame by the battle's rule, and every field frame ends in "
                       "frame_end (0x8001F30C)'s VSync(0): 59.94 ticks a second while "
                       "a frame fits in one vblank")

    def __init__(self):
        self.view = self.VIEWS[0]
        self._looks = None
        self._battle = None
        self._layer_labels: list[str] = []
        self._proof: dict[str, list[str]] = {}
        self._parsed: dict[int, Any] = {}       # set number -> ObjectSet
        self._members: dict[int, Any] = {}      # party id -> MemberSheets

    def get_views(self):
        return list(self.VIEWS)

    @staticmethod
    def holds(item, r, ctx) -> bool:
        """A sprite is the look ("look", s, n, heading) it is a copy of;
        object set n is ("set", n); battle sprite s/j is ("bset", s, j)."""
        if r.kind == "sprite":
            if item[0] != "look":
                return False
            from viewer_tabs import looks
            look = looks.of(GameModel.for_ctx(ctx)).look(r)
            return look is not None and look.ref.id == (item[1], item[2])
        if r.kind == "battle-sprite":
            return item[0] == "bset" and tuple(item[1:]) == tuple(r.id)
        return item[0] == "set" and item[1] == r.id[0]

    def get_layer_options(self):
        return [str(i) for i in range(len(self._layer_labels))]

    def get_layer_labels(self):
        return list(self._layer_labels)

    # -- loading ----------------------------------------------------------

    def _ensure(self, ctx):
        if self._looks is not None:
            return
        from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pfs
        from viewer_tabs import looks
        model = GameModel.for_ctx(ctx)
        found = looks.of(model)
        self._fm = found.fm
        self._names = found.names
        self._sets = found.sets
        self._directory = pfs.parse_directory(found.fm.party_buf)
        self._looks = found

    def _battles(self, ctx) -> _BattleSprites:
        if self._battle is None:
            self._battle = _BattleSprites(ctx)
        return self._battle

    def _object_set(self, n: int):
        if n not in self._parsed:
            from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
            while len(self._parsed) >= self.KEEP:
                self._parsed.pop(next(iter(self._parsed)))
            self._parsed[n] = mos.parse_object_set(self._fm.read(self._sets[n].resource))
        return self._parsed[n]

    def _member(self, m: int):
        if m not in self._members:
            from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pfs
            self._members[m] = pfs.member_sheets(self._fm.party_buf, m, self._looks.party_twins)
        return self._members[m]

    # -- names ------------------------------------------------------------

    def _char_name(self, m: int) -> str:
        if 1 <= m <= 24:
            return self._looks.character_word(m)
        return f"party sheet {m}"

    def _map_name(self, m: int) -> str:
        try:
            name = self._names and self._names.map_name(m)
        except Exception:
            name = None
        return name or f"map {m}"

    def _place(self, fs) -> str:
        return " / ".join(dict.fromkeys(self._map_name(m) for m in fs.maps)) or "no map enters it"

    def _member_numbers(self, m: int) -> list[tuple[str, int]]:
        """[(sheet, sprite data number)] MapPartySpriteDataLoad loads for id m."""
        from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pfs
        out = [("own", m)]
        if m < pfs.MEMBER_LIMIT:
            out += [("party-kind-0", m + pfs.KIND_0_OFFSET),
                    ("twin", pfs.twin_number(self._looks.party_twins, m))]
        return out

    @property
    def _technical(self) -> bool:
        return self.view == "Pages"

    def _num(self, n: int, digits: int = 2) -> str:
        """A number as a list shows it: decimal, and in the technical view
        its hex beside."""
        return f"{n} ({n:#0{digits + 2}x})" if self._technical else str(n)

    # -- items ------------------------------------------------------------

    def get_items(self, cache, archive, ctx, selected):
        if self.view == "In battle":
            return self._battle_items(ctx)
        try:
            self._ensure(ctx)
        except Exception as e:
            return [(f"Could not read the field's sprites: {e}", None)]
        if self.view == "By who":
            return [(f"{lk.title}  {lk.subtitle}" if lk.subtitle else lk.title,
                     ("look", *lk.ref.id, lk.group)) for lk in self._looks.looks]
        from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pfs
        out = [(f"Party field sheets  resource {self._num(pfs.DIRECTORY_RESOURCE, 3)}"
                f"  {len(self._directory)} rows", ("party",))]
        for m in self._looks.party_ids:
            for i, (which, number) in enumerate(self._member_numbers(m)):
                head = f"  {self._char_name(m)}  " if i == 0 else "    "
                out.append((f"{head}{which} sheet  sprite 0/{self._num(number)}",
                             ("sheet", m, which)))
        for fs in self._sets.values():
            if fs.error:
                out.append((f"{self._place(fs)}  object set {self._num(fs.number)}  resource "
                            f"{self._num(fs.resource, 3)}  unreadable: {fs.error}", None))
                continue
            out.append((f"{self._place(fs)}  object set {self._num(fs.number)}  "
                        f"{len(fs.rows)} sprites  {fs.pages} pages", ("set", fs.number)))
            for row in fs.rows:
                out.append((f"  sprite {fs.number}/{self._num(row.number)}  "
                            f"{self._drawn_by(fs, row.number)}", ("data", fs.number, row.number)))
        return out

    def _battle_items(self, ctx):
        try:
            b = self._battles(ctx)
        except Exception as e:
            return [(f"Could not read the battle tables: {e}", None)]
        from decoders.plugins.SLUS_006_28.records import encounters as en
        names = GameNames.for_ctx(ctx)

        def monster(t: int) -> str:
            return (names and names.enemy(t)) or f"monster {t}"
        out = []
        for s in range(en.SET_FIRST, en.SET_LAST + 1):
            if not en.set_resource(b.img, s):
                continue
            for j, t in enumerate(en.type_list(b.img, s)):
                who = (f"{monster(t)}, the fallback block" if j == en.FALLBACK_TYPE
                       else monster(t))
                out.append((f"{who}  monster {t} · monster set {s}, block {j}", ("bset", s, j)))
        try:
            cids = sorted(b.party().members)
        except Exception as e:
            return out + [(f"The party's battle sprites are unreadable: {e}", None)]
        return out + [(f"{self._character(names, c)}  character {c} · the party in battle",
                       ("bparty", c)) for c in cids]

    @staticmethod
    def _character(names, c: int) -> str:
        return ((names and names.character(c)) if 1 <= c <= 12 else None) or f"character {c}"

    def item_identity(self, label, item, ctx) -> Identity:
        """A look by its first copy, compared by its print (the pixels it
        draws), its copies and who wears it; the party's sheets by party
        id, a map object set by its number and its sprite data by number,
        compared by their resource as the code reads it, the palette rows
        they are drawn with and the twin numbers the program gives them; a
        battle sprite by its monster set and block, or its character."""
        from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pfs
        if item[0] in ("bset", "bparty"):
            return self._battle_identity(item, ctx)
        self._ensure(ctx)
        found = self._looks
        if item[0] == "look":
            lk = found.look_of[(item[1], item[2])]
            return of_parts(f"sprite {item[1]}/{item[2]}", lambda: [
                lk.first.print or b"", repr([c.unit for c in lk.copies]).encode(),
                repr((lk.group, lk.character, lk.talk, lk.maps)).encode()])
        rows = [self._fm.row_palettes[r] for r in sorted(self._fm.row_palettes)]

        def party() -> bytes:
            return resource_source(self._fm.party_buf, pfs.DIRECTORY_RESOURCE)
        if item[0] == "party":
            return of_parts("party sheets", lambda: [party()])
        if item[0] == "sheet":
            m, which = item[1], item[2]
            number = dict(self._member_numbers(m))[which]
            return of_parts(f"party id {m:#x} {which} sheet",
                            lambda: [party(), struct.pack("<H", number), *rows])
        fs = self._sets[item[1]]
        key = f"object set {fs.number:#04x}"
        if item[0] == "data":
            key += f" sprite data {item[2]:#04x}"

        def parts():
            maps = [found.map_palette(m) or b"" for m in fs.maps]
            return [resource_source(self._fm.read(fs.resource), fs.resource),
                    struct.pack(f"<{len(fs.maps)}H", *fs.maps), found.twins, *rows, *maps]
        return of_parts(key, parts)

    def _battle_identity(self, item, ctx) -> Identity:
        from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
        from decoders.plugins.SLUS_006_28.records import encounters as en
        b = self._battles(ctx)

        def res(n: int) -> bytes:
            return resource_source(b.read(n), n)
        if item[0] == "bparty":
            return of_parts(f"party char {item[1]}",
                            lambda: [res(bg.PARTY_RESOURCE), bytes([item[1]])])
        s, j = item[1], item[2]

        def parts():
            n = en.set_resource(b.img, s)
            return [repr(en.type_list(b.img, s)).encode(), res(n) if n else b"", bytes([j])]
        return of_parts(f"set {s} block {j}", parts)

    def _drawn_by(self, fs, number: int) -> str:
        users = fs.by_data.get(number, [])
        others = fs.others.get(number, [])
        if not users and not others:
            return self.NOT_DRAWN
        own = sum(1 for _d, twin in users if not twin)
        twins = len(users) - own
        parts = [f"{own} object{'s' if own != 1 else ''}"] if own else []
        if twins:
            parts.append(f"{twins} twin{'s' if twins != 1 else ''}")
        if any(o.what == "actor" for o in others):
            parts.append("script actors")
        if any(o.what == "party" for o in others):
            parts.append("the party")
        return ", ".join(parts) + f"  row {', '.join(map(str, fs.rows_of(number)))}"

    #: An item's label for a number nothing found is put on.
    NOT_DRAWN = "nothing found draws it"

    # -- palettes ---------------------------------------------------------

    def _palettes(self, fs, rows: list[int]) -> tuple[list, list[str]]:
        """-> ([(label, 512-byte palette row)], notes) for palette rows."""
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
        out, notes = [], []
        for row in rows:
            if row in self._fm.row_palettes:
                res = sp.SPRITE_INIT_PALETTES[row]
                out.append((f"row {row} · resource {res} ({res:#x})",
                            self._fm.row_palettes[row]))
            elif row == mos.ROW_MAP:
                maps = fs.maps if fs else ()
                for m in maps:
                    pal = self._looks.map_palette(m)
                    if pal is None:
                        notes.append(f"row 506 for map {m}: the map has no "
                                     f"palette command this tab reads")
                        continue
                    out.append((f"row 506 · map {m}'s palette ({self._map_name(m)})", pal))
                if not maps:
                    notes.append("row 506 is the entered map's palette, and no map "
                                 "enters this set")
            else:
                notes.append(f"row {row}: resource 2's palette (sprite_reset "
                             f"(0x80018DBC)), not read here")
        return out, notes

    def _data_rows(self, fs, number: int) -> tuple[list[int], str]:
        """The palette rows `number` is drawn with, or, when nothing found
        draws it, every row a field record can take, and why."""
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        rows = fs.rows_of(number)
        if rows:
            return rows, ""
        return ([mos.ROW_KIND_1, mos.ROW_KIND_2, mos.ROW_MAP],
                "nothing found draws it: no definition of this set, no actor a script "
                "on its maps makes (command 0x34) and no party sheet is put on it, so "
                "rows 504, 505 and 506 are offered")

    # -- selection --------------------------------------------------------

    def on_select(self, item, cache, archive, ctx):
        self._layer_labels = []
        if item is None:
            return SelectResult(info="Nothing to show")
        try:
            if item[0] in ("bset", "bparty"):
                return self._battle_sprite(item, ctx)
            self._ensure(ctx)
            if item[0] == "look":
                return self._look_page(item[1], item[2], ctx)
            if item[0] == "party":
                return self._party_directory(ctx)
            if item[0] == "sheet":
                return self._party_sheet(item[1], item[2], ctx)
            if item[0] == "set":
                return self._object_set_view(item[1], ctx)
            return self._set_sprite_data(item[1], item[2], ctx)
        except Exception as e:
            return SelectResult(info=f"Could not read it: {e}")

    def _provenance(self, *producers: str) -> list[str]:
        out = []
        for p in producers:
            if p not in self._proof:
                self._proof[p] = proven_by_lines(p)
            out += self._proof[p]
        return out

    def _look_page(self, s: int, n: int, ctx) -> SelectResult:
        """A look's page: its first copy's animations and poses, who wears
        it and every map it stands on."""
        from viewer_tabs import looks
        found = self._looks
        lk = found.look_of[(s, n)]
        c = lk.first
        head = [f"{lk.title} — {lk.group}"]
        who = found.who_words(lk)
        head += [f"who: {who}"]
        if lk.maps:
            head.append(f"stands on: {found.w.places(lk.maps)}")
        if len(lk.copies) > 1:
            head.append(f"copies: {found.copies_words(lk)}")
        lines = [lk.title, "-" * 64, f"who: {who}"]
        if lk.talk is not None:
            lines += ["", *_wrap(found.rule_words(lk), 72, "")]
        if lk.maps:
            lines += ["", "stands on (the maps its object sets are entered on):"]
            lines += [f"  {found.w.map_title(m)} (map {m})" for m in lk.maps]
        lines += ["", "copies (object set / sprite data number; 0 is the party's own sheets):"]
        for x in lk.copies:
            worn = found.worn_words(x)
            lines.append(f"  sprite {x.object_set}/{x.number}"
                         + (f"  {worn}" if worn else ""))
        lines.append("")
        r = ref("sprite", s, n)
        if c.object_set == looks.PARTY_SET:
            m, which = c.party[0]
            return self._party_sheet(m, which, ctx, title=lk.title, head=head, lines=lines, r=r)
        if c.number == looks.CHEST_NUMBER:
            return self._chest_page(lk.title, head, lines, r)
        return self._set_sprite_data(s, n, ctx, title=lk.title, head=head, extra=lines, r=r)

    def _chest_page(self, title, head, lines, r) -> SelectResult:
        """Sprite data 0, the chest every set's kind-7 objects are drawn
        with: resource 2's g_SpriteData1 (0x800DDFB0) on its own page,
        coloured as field_view draws it."""
        from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
        from decoders.plugins.SLUS_006_28.formats import stfield as sf
        st = self._fm.stfield
        actor = sp.parse_actor_block(st.banks[1])
        rendered = [{sf.PAGE: sf.sheet_image(st, 7)}]
        palettes = [("row 507 · resource 2's palette", None)]
        info = head + ["sprite data: 0, g_SpriteData1 (0x800DDFB0), resource 2",
                       "palette: row 507 (sprite_reset (0x80018DBC))",
                       "source: lunadata", "tables: exe-image"]
        return self._sprite_result(actor, palettes, rendered, title, info,
                                   lines + self._block_lines(actor, {sf.PAGE: 256}), [],
                                   (self.MOS, self.SP), r)

    def _party_directory(self, ctx) -> SelectResult:
        from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pfs
        loads: dict[int, list[str]] = {}
        for m in self._looks.party_ids:
            for which, number in self._member_numbers(m):
                loads.setdefault(pfs.sprite_data_row(number), []).append(
                    f"{which} of {self._char_name(m)} (id {m})")
        kind_0 = [m for m, k in self._looks.party_kind.items() if k == 0]
        text = [f"resource {pfs.DIRECTORY_RESOURCE:#x}: {len(self._directory)} rows of "
                f"{pfs.ROW_BYTES} bytes",
                "row  data bytes  picture lines  loaded as",
                "-" * 64]
        for d in self._directory:
            text.append(f"  {d.index:2d}  {d.data_length * 4:10d}  {d.lines:13d}  "
                        f"{'; '.join(loads.get(d.index, ['no rule here loads it']))}")
        text += ["",
                 "own: sprite data id, row id - 1 (row 0x1E for id 0xCE).",
                 "party-kind-0: sprite data id + 0xF, worn while g_MapPartyKind (0x800B8CEE)",
                 "  is 0; MapSet (0x80068780) sets it from byte 0 of the map's area record,",
                 "  0 on " + (", ".join(dict.fromkeys(self._map_name(m) for m in kind_0))
                              or "no map") + ".",
                 "twin: sprite data g_MapTwinSpriteDataNumbers (0x80012C00)[id - 1], drawn",
                 "  while g_MapPartyKind is not 0; what it shows the code does not say.",
                 "",
                 "A party sheet's sprite reference names object set 0: set 0 loads",
                 "nothing, so sprite data n is then the party's own sheet n.",
                 ""] + self._provenance(self.PFS)
        info = ["Party field sheets",
                f"resource: {pfs.DIRECTORY_RESOURCE} ({pfs.DIRECTORY_RESOURCE:#x})",
                f"rows: {len(self._directory)}",
                "source: lunadata",
                "tables: exe-image"]
        return SelectResult(info="\n".join(info), text="\n".join(text), text_wrap=False)

    def _party_sheet(self, m: int, which: str, ctx, title: str | None = None,
                     head: list[str] | None = None, lines: list[str] | None = None,
                     r=None) -> SelectResult:
        from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
        from decoders.plugins.SLUS_006_28.formats import party_field_sheets as pfs
        ms = self._member(m)
        sheet = {"own": ms.own, "party-kind-0": ms.kind_0, "twin": ms.twin}[which]
        row = ms.twin_palette_row if which == "twin" else ms.palette_row
        palettes, notes = self._palettes(None, [row])
        title = title or f"{self._char_name(m)} (id {m}) — {which} sheet"
        actor = sheet.actor()
        page_lines = {0: sheet.picture.lines}
        rendered = [{0: bg.render_page(sheet.picture, pal)} for _l, pal in palettes]
        if which == "own" and m < 0x1F:
            when = "worn while g_MapPartyKind is not 0"
        elif which == "own":
            when = ("worn while g_MapPartyKind is not 0; while it is 0 the record is "
                    "put on sprite data id + 0xF, which is loaded only for ids below 0x1F")
        elif which == "party-kind-0":
            when = "worn while g_MapPartyKind (0x800B8CEE) is 0"
        else:
            when = "the twin: drawn while g_MapPartyKind is not 0, on the member's animation"
        info = list(head or [title]) + [
            f"sprite: 0/{sheet.number} (sprite data {sheet.number:#04x})",
            f"directory row: {sheet.row}",
            f"picture: {sheet.picture.lines} lines of 256",
            f"kind: {pfs.KIND_MEMBER if which == 'twin' else ms.kind} "
            f"(MapPartyRecordInit (0x800649DC))",
            f"palette: {palettes[0][0] if palettes else row}",
            when,
            "source: lunadata",
            "tables: exe-image"]
        text = list(lines or [title, "-" * 64])
        text += self._block_lines(actor, page_lines)
        return self._sprite_result(actor, palettes, rendered, title, info, text, notes,
                                   (self.PFS, self.SP), r or ref("sprite", 0, sheet.number))

    def _object_set_view(self, n: int, ctx) -> SelectResult:
        from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
        fs = self._sets[n]
        obj = self._object_set(n)
        rows = sorted({d.draw.palette_row for d in fs.draws if d.kind != mos.CHEST_KIND}
                      | {o.row for uses in fs.others.values() for o in uses}
                      ) or [mos.ROW_KIND_1, mos.ROW_KIND_2, mos.ROW_MAP]
        layers, notes = [], []
        for row in rows:
            got, more = self._palettes(fs, [row])
            layers += [(row, label, pal) for label, pal in got]
            notes += more
        pages = [p for p in obj.pages if p.lines]
        rendered = [{p.index: bg.render_page(p, pal) for p in pages} for _r, _l, pal in layers]
        # A page holds the texels of every sprite the set loads, each drawn
        # with its own row: one row's colours are right for that row's
        # sprites only.
        owners: dict[int | None, set] = {}
        for number in obj.blocks:
            actor = obj.actor(number)
            if actor is None:
                continue
            rects = sp.texel_rects(actor)
            for row in (set(fs.rows_of(number)) or {None}):
                owners.setdefault(row, set()).update(rects)
        first: dict[int, dict] = {}
        for (row, _label, _pal), by_slot in zip(layers, rendered):
            first.setdefault(row, by_slot)
        drawn, shared = _as_drawn(obj.page_lines, first, owners)
        images = [_page_strip(drawn)] if first else []
        self._layer_labels = (["pages as drawn · each sprite under its own row"]
                              if first else [])
        for (row, label, _pal), by_slot in zip(layers, rendered):
            mine = owners.get(row, set()) | owners.get(None, set())
            images.append(_page_strip([_dim_outside(by_slot[p.index], mine, p.index)
                                       for p in pages]))
            self._layer_labels.append(f"pages · {label} · other rows' sprites faded")
        unread = sorted(n for n in obj.blocks if obj.actor(n) is not None
                        and not fs.rows_of(n))
        chests = [d for d in fs.draws if d.kind == mos.CHEST_KIND]
        kinds = sorted({d.kind for d in fs.draws})
        info = [f"{self._place(fs)} — object set {n}",
                f"resource: {fs.resource} ({fs.resource:#x})",
                "entered as: " + (", ".join(f"map {m}" for m in fs.maps) or "nothing"),
                f"definitions made: {len(fs.draws)}",
                f"sprites: {len(fs.rows)}",
                f"pages: {fs.pages}",
                "source: lunadata",
                "tables: exe-image"]
        text = [f"object set {n} ({n:#04x}): resource {fs.resource:#x}, "
                f"g_MapObjectsDataResourceNumbers (0x800B4E2C)[{n:#x}]",
                "entered from enter rows naming: "
                + (", ".join(f"map {m} {self._map_name(m)}" for m in fs.maps)
                   or "none"),
                "",
                f"word 0, definition block: {len(obj.definitions)} bytes inflated — "
                f"{mos.DEFINITION_COUNT} definitions",
                f"  of {mos.DEFINITION_SIZE:#x} bytes, then the step lists from "
                f"{mos.STEP_LISTS_AT:#x}. This tab reads bytes 0, 1 and 3",
                "  of a definition (kind, sprite data, mode); where it stands, how it",
                "  moves and what it does are not decoded here.",
                f"  made (byte 1 not 0): {len(fs.draws)}, kinds "
                f"{', '.join(map(str, kinds)) or 'none'}",
                f"  chests (kind 7): {len(chests)} — sprite data 0, resource 2's chest "
                f"(g_SpriteData1 (0x800DDFB0)),",
                "  drawn with row 507 at x 0x70; not shown here.",
                "",
                "word 1, sprite data list (number, bytes, drawn by)",
                "-" * 64]
        for row in fs.rows:
            text.append(f"  {row.number:3d} ({row.number:#04x})  {row.length * 4:6d}  "
                        f"{self._drawn_by(fs, row.number)}")
        text += ["", "words 2.., pages (slot: lines)",
                 *(f"  {p.index}: {p.lines}" for p in obj.pages),
                 "",
                 "A page holds the texels of every sprite the set loads, and each sprite",
                 "is drawn with its own row, so one row's colours are right for that",
                 "row's sprites only. The first layer shows every texel under the row of",
                 "the sprites that read it"
                 + (f" (row 506 as {next(lb for r, lb, _p in layers if r == mos.ROW_MAP)})"
                    if mos.ROW_MAP in first and len(fs.maps) > 1 else "")
                 + "; the texels no sprite reads stay blank.",
                 "The other layers show the pages under one row, with the texels of",
                 "other rows' sprites faded."]
        if shared:
            text.append(f"  {shared} texels are read by sprites of more than one row; the "
                        f"first layer shows them under the lower.")
        if unread:
            text.append("  nothing found draws "
                        + ", ".join(str(n) for n in unread)
                        + ": left out of the first layer, shown unfaded under every row.")
        text += [f"! {note}" for note in notes]
        text += [""] + self._provenance(self.MOS)
        return SelectResult(images=[im for im in images if im is not None],
                            info="\n".join(info), text="\n".join(text), text_wrap=False,
                            ref=ref("object-set", n))

    def _set_sprite_data(self, n: int, number: int, ctx, title: str | None = None,
                         head: list[str] | None = None, extra: list[str] | None = None,
                         r=None) -> SelectResult:
        from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
        fs = self._sets[n]
        obj = self._object_set(n)
        rows, why = self._data_rows(fs, number)
        palettes, notes = self._palettes(fs, rows)
        if why:
            notes.insert(0, why)
        actor = obj.actor(number)
        rendered = [{p.index: bg.render_page(p, pal) for p in obj.pages if p.lines}
                    for _l, pal in palettes]
        row = next(x for x in fs.rows if x.number == number)
        title = title or f"{self._place(fs)} — sprite {n}/{number}"
        info = list(head or [title]) + [
            f"sprite: {n}/{number} (object set {n:#04x}, sprite data {number:#04x})",
            f"block: {row.length * 4} bytes",
            f"drawn by: {self._drawn_by(fs, number)}",
            f"palette: {', '.join(label for label, _p in palettes) or 'none read'}",
            "source: lunadata",
            "tables: exe-image"]
        lines = list(extra or [title, "-" * 64])
        users = fs.by_data.get(number, [])
        if users:
            lines.append("drawn by (MapObjectInit (0x800656CC), MapRecordInit (0x80065940))")
            for d, twin in users:
                lines.append(f"  definition {d.definition:3d}  kind {d.kind}  mode {d.mode}"
                             f"  word {d.draw.word:#06x}  row {d.draw.palette_row}"
                             f"{'  as its twin' if twin else ''}")
            lines.append("")
        others = fs.others.get(number, [])
        if others:
            lines.append("also put on it (the scripts that can run on the set's maps, "
                         "and the party)")
            lines += [f"  {o.why}" for o in others]
            lines.append("")
        lines += self._block_lines(actor, obj.page_lines)
        return self._sprite_result(actor, palettes, rendered, title, info, lines, notes,
                                   (self.MOS, self.SP), r or ref("sprite", n, number))

    def _block_lines(self, actor, page_lines: dict[int, int]) -> list[str]:
        from decoders.plugins.SLUS_006_28.formats import map_object_sets as mos
        from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
        if actor is None:
            return ["the block is not a sprite data layout this tab reads"]
        poses = sp.list_poses(actor)
        out = [f"poses: {len(poses)} drawable of {actor.pose_count}",
               f"anims: {len(actor.animations())}"]
        off = mos.undrawn_slices(actor, page_lines)
        if off:
            out.append(f"pieces not drawn here ({len(off)}): their texels are not on "
                       f"the pages this block is loaded with")
            out += [f"  pose {p} piece {i}: {why}" for p, i, why in off[:24]]
            if len(off) > 24:
                out.append(f"  ... {len(off) - 24} more")
        return out

    def _sprite_result(self, actor, palettes, rendered, title, info, lines, notes,
                       producers, r=None) -> SelectResult:
        """One sprite data block under each of its palettes: in Pages, the
        pages it reads, the other sprites' texels faded; elsewhere its page,
        every animation played and every pose held, under each palette."""
        from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
        from viewer_tabs import scene
        info = list(info) + [f"! {note}" for note in notes]
        text = list(lines) + [""]
        if actor is None or not palettes:
            text += self._provenance(*producers)
            return SelectResult(info="\n".join(info), text="\n".join(text),
                                text_wrap=False, ref=r)
        if self.view == "Pages":
            used = sorted({slot for pose in sp.list_poses(actor)
                           for slot in sp.pose_tpages(actor, pose)})
            # The pages hold other sprites' texels too, drawn with their own rows.
            mine = sp.texel_rects(actor)
            images = [_page_strip([_dim_outside(pages[s], mine, s) for s in used if s in pages])
                      for pages in rendered]
            self._layer_labels = [f"pages {', '.join(map(str, used))} · {label} · "
                                  f"other sprites' texels faded"
                                  for label, _p in palettes]
            text += self._provenance(*producers)
            return SelectResult(images=[im for im in images if im is not None],
                                info="\n".join(info), text="\n".join(text),
                                text_wrap=False, ref=r)
        sheets = [sp.pose_sheet(actor, pages) for pages in rendered]
        if sheets[0] is None:
            text += self._provenance(*producers)
            return SelectResult(info="\n".join(info + ["no drawable poses"]),
                                text="\n".join(text), text_wrap=False, ref=r)
        entry = scene.sheet_entry(sheets[0], actor.animations(), title)
        text += ["anim table — the field puts a record on id 4 × group + 1 + facing",
                 "column (MapAnimationPoseSet (0x8006633C)); what each group is, is not",
                 "named here",
                 "-" * 64] + scene.anim_lines(entry) + [""]
        text += self._provenance(*producers)
        playable = [a["index"] for a in entry["anims"] if a["steps"]]
        # A section's first actor is labelled in full, the rest by number:
        # a page holds hundreds, and full labels would not fit between them.
        sections = [(entry, [(a, f"anim {a}" if i == 0 else str(a))
                             for i, a in enumerate(playable)])]
        for (label, _p), sheet in zip(palettes, sheets):
            if sheet is None:
                continue
            short = label.split(" · ")[0]
            held = scene.held_poses(scene.sheet_entry(sheet, (), f"{title} · {label}"),
                                    f"{title} · poses · {label}")
            poses = [k for k, cell in enumerate(sheet.cells) if cell]
            first = f"pose {poses[0]}" + (f" · {short}" if len(palettes) > 1 else "") \
                if poses else ""
            sections.append((held, [(k, first if i == 0 else str(k))
                                    for i, k in enumerate(poses)]))
        w, h, sc_sheets, actors = scene.stack(sections)
        sc = {"w": w, "h": h, "background": None, "sheets": sc_sheets,
              "actors": actors, "depth": "order", "labels": True,
              "tick_hz": scene.TICK_HZ, "tick_note": self.FIELD_TICK_NOTE}
        self._layer_labels = [f"animations and poses · first tick · {palettes[0][0]}"]
        self._layer_labels += [f"poses · {label}" for (label, _p), s in zip(palettes, sheets)
                               if s is not None]
        images = [scene.still(sc)] + [s.image for s in sheets if s is not None]
        why = [] if playable else ["no anim has steps: every pose is held"]
        return SelectResult(images=images, scene=sc,
                            info="\n".join(info + why + [f"timing: {self.FIELD_TICK_NOTE}"]),
                            text="\n".join(text), text_wrap=False, ref=r)

    def _battle_sprite(self, key: tuple, ctx) -> SelectResult:
        """A battle sprite on its own with its anim table: a monster set's
        block, or a character's from resource 0x197."""
        from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
        from decoders.plugins.SLUS_006_28.records import encounters as en
        from viewer_tabs import scene
        b = self._battles(ctx)
        names = GameNames.for_ctx(ctx)
        if key[0] == "bset":
            s, j = key[1], key[2]
            types = en.type_list(b.img, s)
            t = types[j] if j < len(types) else None
            who = ((names and t and names.enemy(t)) or f"monster {t}") if t else "no monster"
            title = (f"{who} — monster set {s}, block {j}" if j != en.FALLBACK_TYPE
                     else f"monster set {s}, block {j} — the fallback block (lists {who})")
            entry, _blk = b.sheet(("set", s, j))
            r = ref("battle-sprite", s, j)
        else:
            c = key[1]
            title = f"{self._character(names, c)} — in battle"
            entry, _blk = b.sheet(("party", c))
            r = None
        if entry is None:
            return SelectResult(info=f"{title}\nno drawable poses", ref=r)
        playable = [a["index"] for a in entry["anims"] if a["steps"]]
        start = 0 if 0 in playable else (playable[0] if playable else 0)
        pad = self.PAD
        sc = {"w": entry["cell_w"] + 2 * pad, "h": entry["cell_h"] + 2 * pad,
              "background": None, "sheets": [entry],
              "actors": [{"sheet": 0, "x": entry["anchor_x"] + pad,
                          "y": entry["anchor_y"] + pad, "mirror": False,
                          "anim": start, "label": title}],
              "depth": "order", "labels": False,
              "tick_hz": scene.TICK_HZ, "tick_note": scene.BATTLE_TICK_NOTE}
        named = sum(1 for a in entry["anims"] if a["name"])
        info = [title,
                f"poses: {entry['poses']}",
                f"anims: {len(entry['anims'])} ({len(playable)} with steps, {named} named)",
                f"cell: {entry['cell_w']}x{entry['cell_h']}, anchor "
                f"({entry['anchor_x']}, {entry['anchor_y']})"]
        if key[0] == "bset":
            info.append(f"CLUT: B (row {bg.CLUT_ROW_ENEMY})")
        else:
            info += [f"CLUT: party (row {bg.CLUT_ROW_PARTY})",
                     f"resource: {bg.PARTY_RESOURCE:#x}"]
        info.append("source: lunadata")
        text = ["anim table — ids the battle code plays are named; the rest are",
                "unnamed rather than guessed (battle.md \"Battle animation ids\")",
                "-" * 64]
        text += scene.anim_lines(entry)
        if key[0] == "bparty":
            text += ["", "slot 5 (the companion) keeps its own ids — "
                     + ", ".join(f"{i}: {n}" for i, (n, _p) in bg.COMPANION_ANIMS.items()),
                     "which character id is which hero is not in the code."]
        text += [""] + self._provenance(self.GFX)
        self._layer_labels = ["Pose sheet"]
        return SelectResult(images=[entry["image"]], info="\n".join(info),
                            text="\n".join(text), text_wrap=False, scene=sc, ref=r)


# ---------------------------------------------------------------------------
# Battles — every fight and its monster sets, from the code path
# ---------------------------------------------------------------------------

class BattlesProvider:
    """Battle graphics, decoded through the code that loads and draws them.

    BtlEnemyLoad (0x8002B3AC) names a battle's monster set and monster group,
    BtlDataLoad (0x80018694) loads the set (arena, monster blocks, two CLUTs, pages),
    BtlFrameDraw (0x80018564) draws the arena, BtlPartyLoad (0x8002B114) loads the party's blocks
    from resource 0x197, and sprite_draw (0x8001A528) / sprite_piece_draw (0x80019DBC) compose every
    pose. The anim tables are each block's own, and the player ticks them
    as BtlAnimationStep (0x800272A8) does — once per battle frame, 59.94 Hz — so step
    lengths, loops and holds are the game's.

    Battles stands every monster on its monster group's anchor, mirrored
    where the code mirrors it, playing anim 0 as battle entry does; pick
    another anim for all of them, or click one. The party stands where BtlPartyLoad
    (0x8002B114) puts it, on g_BtlPartyPlaceXCells (0x800B8E88) /
    g_BtlPartyPlaceYCells (0x800B8E90), which MapBtlRun (0x8007AE58) fills
    from each member's place record (battle.md §"Party stage state"). That
    needs the members, so the party is placed only when a script row
    (g_ScriptMapBtlRows, 0x800B366C) runs the battle with a party list of
    its own, at the places a new game starts with (resource 0xE7); otherwise
    it is the field party of the moment and is not placed. Every monster
    block and party character on its own, with its anim table, is the
    Sprites tab's In battle. Monster sets shows each set's arena and pages.

    A battle's music is what starts it (viewer_tabs.battle_music): the
    map monsters' song 1, a script's BATTLE command's own, and the win's
    jingle; each plays from its button.
    """

    name = "Battles"
    key = "battles"
    fan_about = """
    Every battle in the game: the monsters you fight, standing in their
    arena as the game puts them, and the party where it stands when a scene
    starts the fight with a party of its own. Click one to watch its
    animations, and play the music the fight starts with and the jingle of
    the win.

    Each battle says where it is met: the places whose monsters on the map
    or scenes start it.
    """
    technical_view = "Monster sets"
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = True
    supports_grid = False
    supports_layers = True
    views_change_items = True

    VIEWS = ("Battles", "Monster sets")
    GFX = "decoders.plugins.SLUS_006_28.formats.battle_gfx"
    ENC = "decoders.plugins.SLUS_006_28.records.encounters"
    PAD = 8
    #: A battle is its row in Battles, a monster set its row in Monster sets.
    homes = {"battle": ("Battles",), "monster-set": ("Monster sets",)}

    def __init__(self):
        self.view = self.VIEWS[0]
        self._img = None            # the program's text, as code.bin lays it out
        self._gfx: _BattleSprites | None = None
        self._new_game = None       # (places, stand animations) as a new game has them
        self._proof: dict[str, list[str]] = {}
        self._layer_labels: list[str] = []

    def get_views(self):
        return list(self.VIEWS)

    @staticmethod
    def holds(item, r, ctx) -> bool:
        """Battle n is ("enc", n, boss); monster set n is ("set", n)."""
        if r.kind == "battle":
            return item[0] == "enc" and item[1] == r.id[0]
        return item[0] == "set" and len(item) == 2 and item[1] == r.id[0]

    def get_layer_options(self):
        return [str(i) for i in range(len(self._layer_labels))]

    def get_layer_labels(self):
        return list(self._layer_labels)

    # -- loading ----------------------------------------------------------

    def _ensure(self, ctx):
        if self._img is not None:
            return
        self._gfx = _BattleSprites(ctx)
        self._img = self._gfx.img
        self._names = GameNames.for_ctx(ctx)

    def _read(self, res: int) -> bytes:
        return self._gfx.read(res)

    def _enemy_name(self, enemy_id: int) -> str:
        return (self._names and self._names.enemy(enemy_id)) or f"monster {enemy_id}"

    def _char_name(self, char_id: int) -> str:
        return (self._names and self._names.character(char_id)) or f"character {char_id}"

    def _set(self, set_id: int):
        """-> (monster ids, SetBundle, {page slot: page under CLUT B})."""
        return self._gfx.set(set_id)

    def _party_bundle(self):
        return self._gfx.party()

    def _sheet(self, key: tuple):
        return self._gfx.sheet(key)

    # -- items ------------------------------------------------------------

    def get_items(self, cache, archive, ctx, selected):
        try:
            self._ensure(ctx)
        except Exception as e:
            return [(f"Could not read the program's tables: {e}", None)]
        from decoders.plugins.SLUS_006_28.records import encounters as en
        img = self._img
        if self.view == "Battles":
            out = []
            for e in en.all_encounters(img):
                if not en.set_resource(img, e.set):
                    out.append((f"battle {e.id}  empty entry (monster set {e.set}, "
                                f"monster group {e.formation})", ("enc", e.id, False)))
                    continue
                ids = [s.enemy_id for s in en.formation(img, e.formation).slots]
                out.append((f"battle {e.id}  monster set {e.set}  monster group {e.formation}"
                            f"  {_enemy_summary(ids, self._enemy_name)}",
                            ("enc", e.id, e.id >= en.BOSS_CLASS_FIRST)))
            return out
        sets = [s for s in range(en.SET_FIRST, en.SET_LAST + 1) if en.set_resource(img, s)]
        # Monster sets is the technical view: the resource in hex beside
        return [(f"monster set {s}  resource {en.set_resource(img, s)} "
                 f"({en.set_resource(img, s):#x})"
                 f"  {', '.join(self._enemy_name(t) for t in en.type_list(img, s))}",
                 ("set", s))
                for s in sets]

    def fan_row(self, label, item, ctx) -> dict | None:
        """A battle in Fan mode: who is fought and where it is met ("6×
        ‹monster› · ‹place›"), the places whose map monsters or scripts start it
        (battle_music.Fights), the debug room's last."""
        if item[0] != "enc":
            return None
        from decoders.plugins.SLUS_006_28.records import encounters as en
        from viewer_tabs.field_view import DEBUG_ROOM
        self._ensure(ctx)
        e = en.encounter(self._img, item[1])
        if not en.set_resource(self._img, e.set):
            return {"sub": "an empty entry: the game loads nothing for it"}
        ids = [s.enemy_id for s in en.formation(self._img, e.formation).slots]
        model = GameModel.for_ctx(ctx)
        fm, fights = model.field, model.fights
        maps = set(fights.monsters.get(item[1], ()))
        for sid, _music in fights.scripts.get(item[1], []):
            maps |= {DEBUG_ROOM} if sid in fm.debug_scripts else set(fm.script_maps.get(sid, ()))
        names = model.names
        places = sorted({(names and names.map_name(m)) or f"map {m}" for m in maps if m != DEBUG_ROOM})
        if DEBUG_ROOM in maps:
            places.append("the debug room")
        shown = ", ".join(places[:2]) + (f" and {len(places) - 2} more" if len(places) > 2 else "")
        return {"sub": " · ".join(p for p in (_enemy_summary(ids, self._enemy_name, "×"), shown) if p)}

    def item_identity(self, label, item, ctx) -> Identity:
        """A battle and a monster set by their numbers; compared by the
        program's rows for them and the resources they are drawn from, as
        the code reads them."""
        from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        from decoders.plugins.SLUS_006_28.formats import party_init as pi
        from decoders.plugins.SLUS_006_28.records import encounters as en
        self._ensure(ctx)
        img = self._img

        def res(n: int) -> bytes:
            return resource_source(self._read(n), n)

        def set_parts(s: int) -> list[bytes]:
            n = en.set_resource(img, s)
            return [repr(en.type_list(img, s)).encode(), res(n) if n else b""]

        if item[0] == "enc":
            eid = item[1]

            def parts() -> list[bytes]:
                e = en.encounter(img, eid)
                rows = [r for r in es.encounter_rows(img) if r.encounter == eid]
                out = [repr(e).encode(), repr(rows).encode()]
                if not en.set_resource(img, e.set):
                    return out
                out += [repr(en.formation(img, e.formation)).encode(), *set_parts(e.set)]
                if any(r.party for r in rows):
                    out += [res(bg.PARTY_RESOURCE), res(pi.RESOURCE)]
                return out
            return of_parts(f"encounter {eid}", parts)
        return of_parts(f"set {item[1]}", lambda: set_parts(item[1]))

    # -- selection --------------------------------------------------------

    def on_select(self, item, cache, archive, ctx):
        self._layer_labels = []
        if item is None:
            return SelectResult(info="Nothing to show")
        self._ensure(ctx)
        if item[0] == "enc":
            return self._encounter(item[1], ctx)
        return self._graphics_set(item[1], ctx)

    def _provenance(self, ctx, *producers: str) -> list[str]:
        out = []
        for p in producers:
            if p not in self._proof:
                self._proof[p] = proven_by_lines(p)
            out += self._proof[p]
        return out

    def _new_game_party(self):
        """-> ({char id: (place_x, place_y)}, {char id: stand anim}) as a new
        game has them: resource 0xE7's place records (ChrRecordsReset
        (0x80063B30) copies them to g_ChrPlacePresetRecords (0x800B8C74)) and
        the stand animation BtlPartyStatsSet (0x8002A138) picks by each one's
        first worn item."""
        if self._new_game is None:
            from decoders.plugins.SLUS_006_28.formats import party_init as pi
            buf = self._read(pi.RESOURCE)
            init = pi.parse(buf)
            places = {}
            for cid, raw in init.place_presets.items():
                p = pi.place_preset(raw)
                places[cid] = (p.place_x, p.place_y)
            stand = {m.char_id: m.battle.anims[1]
                     for m in pi.party(buf, pi.exe_items(self._img)) if m.battle.anims}
            self._new_game = (places, stand)
        return self._new_game

    def _party_in(self, eid: int, sheets: list, sheet_of: dict):
        """The party's actors for encounter `eid`, and the lines that say
        where they stand and why.

        BtlPartyLoad (0x8002B114) stands slots 0..4 on g_BtlPartyPlaceXCells
        (0x800B8E88) / g_BtlPartyPlaceYCells (0x800B8E90), which MapBtlRun
        (0x8007AE58) fills before the fight from each member's place record,
        the x less the battle's x shift. Who the members are is the code's
        only when a g_ScriptMapBtlRows (0x800B366C) row runs the encounter
        with a list of its own; the places are the new game's."""
        from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        rows = [r for r in es.encounter_rows(self._img) if r.encounter == eid]
        row = next((r for r in rows if r.party), None)
        used = ", ".join(f"{r.row} ({'its own party' if r.party else 'the field party'}, "
                         f"x shift {r.x_shift})" for r in rows)
        text = ["party (anchor x, y — BtlPartyLoad (0x8002B114))", "-" * 48]
        if rows:
            text.append(f"script rows (g_ScriptMapBtlRows, 0x800B366C) that run it: {used}")
        if row is None:
            text += ["not placed: the members are the field party, g_PartyIds (0x800B8BC0),",
                     "of the moment the fight starts, which is not on the disc.", ""]
            return [], "party: not placed — the field party of the moment", text
        places, stand = self._new_game_party()
        members = self._party_bundle().members
        actors, missing = [], []
        placed = bg.party_places(row.slot_ids(), places, row.x_shift)
        for p in placed:
            if p.char_id not in members:
                missing.append(f"slot {p.slot}: char {p.char_id} has no graphics in resource 0x197")
                continue
            key = ("party", p.char_id)
            if key not in sheet_of:
                entry, _blk = self._sheet(key)
                if entry is None:
                    missing.append(f"slot {p.slot}: char {p.char_id} has no drawable poses")
                    continue
                sheet_of[key] = len(sheets)
                sheets.append(entry)
            if p.cells is None:
                anim = bg.SLOT5_ANIM
            elif p.char_id in stand:
                anim = stand[p.char_id]
            else:
                anim = 0
                missing.append(f"slot {p.slot}: char {p.char_id}'s new-game worn item picks "
                               "no stand animation; anim 0 shown")
            actors.append({"sheet": sheet_of[key], "x": p.x, "y": p.y,
                           "mirror": p.mirrored, "anim": anim,
                           "label": f"slot {p.slot} · {self._char_name(p.char_id)}"})
            where = (f"cells ({p.cells[0]}, {p.cells[1]})" if p.cells
                     else "slot 5's own place")
            text.append(f"  slot {p.slot:2d}  char {p.char_id:3d} {self._char_name(p.char_id):<16}"
                        f" {where:<18} ({p.x:3d}, {p.y:3d}){'  mirrored' if p.mirrored else ''}")
        unplaced = [s for s, cid in enumerate(row.slot_ids()) if cid
                    and s not in {p.slot for p in placed}]
        missing += [f"slot {s}: char {row.slot_ids()[s]} has no new-game place" for s in unplaced]
        text += [f"! {m}" for m in missing]
        text += ["",
                 f"the members: row {row.row}'s own list, as ScriptCommandMapBtlRun (0x8005DFF0)",
                 "puts it in g_BtlSlotIds (0x800E48E0) (id 0xC to slot 5, the rest in order).",
                 "the cells: each member's place record (ChrPlacePresetRecord, chr.h) as a",
                 "new game has it (resource 0xE7 + 0x342, ChrRecordsReset (0x80063B30)), the x less",
                 f"the row's x shift {row.x_shift}, as MapBtlRun (0x8007AE58) copies it. In play the",
                 "places page MenuBtlPlacesStep (0x80071D50) moves them. x = cell * 8, y = cell * 8;",
                 "an x cell of 0x10 or more faces 0x2020 (mirrored). Slot 5 stands at (0xA0, 0x68).",
                 "the stand animation: the one BtlPartyStatsSet (0x8002A138) picks by the",
                 "member's new-game first worn item; slot 5 plays anim 5.", ""]
        info = (f"party: script row {row.row}, ids {', '.join(map(str, row.party))}, "
                f"x shift {row.x_shift}, new-game places")
        return actors, info, text

    def _encounter(self, eid: int, ctx) -> SelectResult:
        from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
        from decoders.plugins.SLUS_006_28.records import encounters as en
        from viewer_tabs import scene
        e = en.encounter(self._img, eid)
        if not en.set_resource(self._img, e.set):
            return SelectResult(info=(
                f"Battle {eid}\nmonster set: {e.set}\nmonster group: {e.formation}\n"
                f"An empty table entry: monster set {e.set} names no graphics resource "
                f"(g_BtlDataResources[{e.set}] (0x800A7E18) = 0), so BtlDataLoad (0x80018694) would load nothing."))
        form = en.formation(self._img, e.formation)
        types, bundle, _pages = self._set(e.set)
        arena = bg.compose_arena(bundle)
        sheets, sheet_of, enemies, missing = [], {}, [], []
        for slot in form.slots:
            j = en.type_slot(types, slot.enemy_id)
            entry, _blk = self._sheet(("set", e.set, j))
            if entry is None:
                missing.append(f"slot {slot.actor_slot}: monster {slot.enemy_id} -> "
                               f"block {j}, which monster set {e.set} does not hold")
                continue
            if ("set", j) not in sheet_of:
                sheet_of[("set", j)] = len(sheets)
                sheets.append(entry)
            enemies.append({"sheet": sheet_of[("set", j)], "x": slot.x, "y": slot.y,
                            "mirror": slot.mirrored, "anim": 0,
                            "label": f"slot {slot.actor_slot} · {self._enemy_name(slot.enemy_id)}"})
        party, party_info, party_text = self._party_in(eid, sheets, sheet_of)
        # slot order: the party's slots 0..5, then the enemies' 6..13
        sc = {"w": bg.SCREEN_W, "h": bg.SCREEN_H, "background": arena,
              "sheets": sheets, "actors": party + enemies, "depth": "y", "labels": False,
              "tick_hz": scene.TICK_HZ, "tick_note": scene.BATTLE_TICK_NOTE}
        info = [f"Battle {eid}",
                f"monster set: {e.set} (resource {en.set_resource(self._img, e.set):#x})",
                f"monster group: {e.formation}",
                f"monsters: {_enemy_summary([s.enemy_id for s in form.slots], self._enemy_name)}",
                "source: lunadata",
                "tables: exe-image",
                "screen: 320x224 (clip 224)",
                party_info]
        if eid >= en.BOSS_CLASS_FIRST:
            info.append(f"! boss class (id >= {en.BOSS_CLASS_FIRST:#x}): its AI "
                        f"is per-boss code, BtlEnemyActionSpecialSet (0x800417E4)")
        songs = self._songs(eid, ctx)
        info += [f"music: song {x['bgm']} {x['title']}: {x['note']}" for x in songs] or [
            "music: nothing found that starts this fight (no map monster, no script)"]
        info += [f"! {m}" for m in missing]
        text = ["actors (anchor x, y — the point slices hang off)", "-" * 48]
        for slot in form.slots:
            j = en.type_slot(types, slot.enemy_id)
            clamp = ("" if slot.y == slot.y_unclamped
                     else f"  (y {slot.y_unclamped} clamped to {en.Y_MIN:#x}..{en.Y_MAX:#x})")
            text.append(f"  slot {slot.actor_slot:2d}  monster {slot.enemy_id:3d} "
                        f"{self._enemy_name(slot.enemy_id):<16} block {j}"
                        f"  ({slot.x:3d}, {slot.y:3d})"
                        f"{'  mirrored' if slot.mirrored else ''}{clamp}")
        text += [""] + party_text
        text += ["drawn Y-sorted (draw flags 0x2000 for the party, 0x2100 for the enemies",
                 "-> OT 0x200 + 0xFF - (Y + 0x20)), lower on screen in front; at equal Y",
                 "the lower slot in front (AddPrim (0x8008E9D8) puts each packet at the head",
                 "of its OT entry, and the slots are drawn in order); the arena behind",
                 "everything (OT 0x300).",
                 f"anim ticks: {scene.BATTLE_TICK_NOTE}.", ""]
        text += self._provenance(ctx, self.ENC, self.GFX)
        self._layer_labels = ["Scene (first tick)", "Arena"]
        return SelectResult(images=[scene.still(sc), arena], info="\n".join(info),
                            text="\n".join(text), text_wrap=False, scene=sc,
                            ref=ref("battle", eid))

    def _songs(self, eid: int, ctx) -> list[dict]:
        """What the fight plays, by what starts it (viewer_tabs.battle_music)."""
        from viewer_tabs import battle_music as bm
        model = GameModel.for_ctx(ctx)
        if model.names is None:
            return []
        return bm.songs(model.field, model.names, model.fights, eid)

    def _graphics_set(self, set_id: int, ctx) -> SelectResult:
        from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
        from decoders.plugins.SLUS_006_28.records import encounters as en
        types, bundle, pages = self._set(set_id)
        images = [bg.compose_arena(bundle)] + [pages[k] for k in sorted(pages)]
        self._layer_labels = ["Arena (CLUT A)"] + [
            f"Page {k} (CLUT B)" for k in sorted(pages)]
        users = [e.id for e in en.all_encounters(self._img) if e.set == set_id]
        info = [f"Monster set {set_id}",
                f"resource: {en.set_resource(self._img, set_id):#x}",
                f"monsters: {', '.join(map(str, types))}",
                f"pages: {len(bundle.pages)}",
                f"battles: {len(users)}",
                "source: lunadata"]
        text = ["pages (slot: lines) — VRAM g_SpritePageCorners[slot] (0x800A7F88)",
                *(f"  {p.index}: {p.lines}" for p in bundle.pages),
                f"reserved lines of slot 4: {bundle.reserved_lines}",
                "",
                f"used by battles: {', '.join(map(str, users)) or 'none'}",
                ""] + self._provenance(ctx, self.GFX)
        return SelectResult(images=images, info="\n".join(info),
                            text="\n".join(text), text_wrap=False,
                            ref=ref("monster-set", set_id))


def _enemy_summary(ids: list[int], name=lambda i: f"monster {i}", times: str = "x") -> str:
    """'4x Abcd' / 'Abcd, 2x Efgh' — the monster group's order, counted."""
    from collections import Counter
    counts = Counter(ids)
    return ", ".join(f"{counts[i]}{times} {name(i)}" if counts[i] > 1 else name(i)
                     for i in dict.fromkeys(ids)) or "no enemies"


# ---------------------------------------------------------------------------
# Bromides — each bromide whole, as the game shows it, with its voice
# ---------------------------------------------------------------------------

class BromidesProvider:
    """The bromides: thirteen pictures the game shows whole, each with a
    voice line, when one of the bromide items is used from the menu.

    MoviePlay (0x800232D4) shows its numbers 55 to 67 as bromides 0 to 12
    with PictureShow (0x80024A7C): the two pictures of resource 586 + k go
    into video memory one under the other, the voice g_PictureVoices
    (0x800AF844) gives the bromide starts (PictureXaPlay (0x800247AC)), and
    for 0x2D0 frames the screen looks down the picture and back up, coming
    in from black and going out to black (PictureStep (0x800249B0),
    PictureDraw (0x80024950); formats.resource_pictures). An item shows the
    bromide its row names (MenuUsePictureRun (0x8007690C)). Each is titled
    by the string table's bromide titles.
    """

    name = "Bromides"
    key = "bromides"
    fan_about = """
    The bromides: pictures the game shows whole, each with a spoken line,
    when one of the bromide items is used from the menu. Each plays as the
    game shows it, looking down the picture and back up.
    """
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = False
    supports_grid = False
    supports_layers = False

    #: One PictureStep a frame, and a frame a vertical blank: frame_end
    #: (0x8001F30C) waits on VSync(0), sixty times a second.
    HZ = 60

    #: Bromide k is its own row.
    homes = {"bromide": (None,)}

    def get_views(self):
        return []

    def get_layer_options(self):
        return []

    @staticmethod
    def holds(k, r, ctx) -> bool:
        return k is not None and r.kind == "bromide" and r.id[0] == k

    @staticmethod
    def _voices(names) -> tuple[list[int] | None, dict]:
        """Each bromide's voice (g_PictureVoices), and the voices' rows by
        number (formats.xa_voices); None and {} when the program's table is
        not located."""
        from decoders.plugins.SLUS_006_28.formats import xa_voices as xv
        from decoders.plugins.SLUS_006_28.records import events as ev
        from decoders.plugins.SLUS_006_28.records.programs import Unmapped
        try:
            return (ev.picture_voices(names.binary.code),
                    {v.number: v for v in xv.voices(names.binary.code)})
        except Unmapped:
            return None, {}

    def get_items(self, cache, archive, ctx, selected):
        from decoders.plugins.SLUS_006_28.records import events as ev
        names = GameNames.for_ctx(ctx)
        if names is None:
            return [(no_names(ctx, "The bromides are found through the program's tables"),
                     None)]
        voices, table = self._voices(names)
        out = []
        for k in range(ev.BROMIDE_COUNT):
            if names.resource_entry(ev.BROMIDE_RESOURCE_BASE + k) is None:
                continue
            words = [names.bromide(k) or f"bromide {k}", f"bromide {k}"]
            voice = table.get(voices[k]) if voices else None
            if voice is not None:
                words.append(f"voice {voice.number}, {voice.seconds:.1f} s")
            out.append(("  ".join(words), k))
        return out or [("The program's resource table holds no bromide.", None)]

    def item_identity(self, label, k, ctx) -> Identity:
        """A bromide by its number, compared by its title, its resource as
        the code reads it, and its voice: its row and _AUDIO.XA."""
        from decoders.plugins.SLUS_006_28.formats import xa_voices as xv
        from decoders.plugins.SLUS_006_28.records import events as ev
        from viewer_tabs.identity import file_digest

        def parts():
            names = GameNames.for_ctx(ctx)
            voices, table = self._voices(names)
            voice = table.get(voices[k]) if voices else None
            xa = ctx.path(xv.FILE_NAME)
            return [label.encode(), names.resource_source(ev.BROMIDE_RESOURCE_BASE + k),
                    repr((voice.number, voice.channel, voice.start, voice.end)
                         if voice else None).encode(),
                    file_digest(xa).encode() if voice and xa.exists() else b""]
        return of_parts(f"bromide {k}", parts)

    def on_select(self, k, cache, archive, ctx):
        if k is None:
            return SelectResult(info="No bromides")
        from decoders.plugins.SLUS_006_28.formats import resource_pictures as rp
        from decoders.plugins.SLUS_006_28.records import events as ev
        from viewer_tabs import links
        model = GameModel.for_ctx(ctx)
        names = model.need_names()
        resource = ev.BROMIDE_RESOURCE_BASE + k
        whole, _drawn = rp.bromide_image(names.read_resource(resource), resource)
        show = rp.bromide_show()
        r = ref("bromide", k)
        page = links.build_card(model, r)
        pan = {"image": whole, "screen": (rp.SCREEN_W, rp.SCREEN_H), "hz": self.HZ,
               "rows": [f.row for f in show], "dark": [f.dark for f in show]}
        info = [page["title"], f"bromide {k}",
                f"movie number: {ev.BROMIDE_FIRST + k}",
                f"resource: {resource}",
                f"on screen: {len(show)} frames, {len(show) / self.HZ:.1f} s",
                f"picture: {whole.width} x {whole.height}, as the screen pans down it"]
        return SelectResult(images=[whole], info="\n".join(info), page=page, pan=pan, ref=r)


# ---------------------------------------------------------------------------
# Screens — the full-screen pictures; every picture, by resource
# ---------------------------------------------------------------------------

class Shown(NamedTuple):
    """A picture as the Screens tab lists it: its image number there
    (links.media.image_numbers), its title, and the heading it is listed
    under, with what the heading means."""
    picture: Any                # formats.resource_pictures.Picture
    number: int
    title: str
    group: str
    note: str


class ScreensProvider:
    """The game's full-screen pictures: what it shows before the title, the
    pages the title screen is drawn from, the screens that ask for the other
    disc and the two after the game's end. All images lists every picture
    there is, by resource: the bromides' two pictures each (shown whole in
    Bromides), the font's letters (in Menus too) and the pictures no code
    shows.

    A picture is command 2 of a resource's command list (resource_tim_add
    (0x800208A0)): sub-number 0 is sent to VRAM at once, any other is kept
    as picture 0, 1, ... in list order for the code to load when it shows
    it. Walking command 2 of every resource the game runs as a command list
    finds the 41 there are — the glyph atlas (resource 1), the title's five
    cards and three pages (3), the bromides' two pictures each (586 to
    598), the disc-change screens and the two pictures after the game's
    end (599) — each named by the code that shows it and drawn through the
    colours that code draws it with (formats.resource_pictures,
    docs/spec/sprites.md §"Pictures: the TIMs"). Screens shows a screen as
    the screen shows it: screen_picture_put (0x80024C04) puts up the top
    320 x 224 of the disc-change screens and the end's.
    """

    name = "Screens"
    key = "screens"
    fan_about = """
    The game's full-screen pictures: what it shows before the title, the
    title screen's pictures, the screens that ask for the other disc and
    the two after the game's end.
    """
    technical_view = "All images"
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = True
    supports_grid = True
    supports_layers = False

    VIEWS = ("Screens", "All images")
    views_change_items = True
    PRODUCER = "decoders.plugins.SLUS_006_28.formats.resource_pictures"
    #: Screens' headings, and what each holds.
    TITLE = ("The title", "shown before the title screen, and the pages the title screen "
                          "is drawn from (StartPictureShow, StartScreenDraw)")
    DISCS = ("Changing discs", "shown when a movie is on the other disc, until the drive's "
                               "lid has been opened and shut (cd_change_wait)")
    END = ("After the end", "shown once the game is over (GameRun)")

    #: Every image is a row of All images; Screens lists some of them.
    homes = {"image": ("All images",)}

    def __init__(self):
        self.view = self.VIEWS[0]
        self._found: list[tuple] | None = None     # [(Picture, image number)]

    def get_views(self):
        return list(self.VIEWS)

    def get_layer_options(self):
        return []

    @staticmethod
    def holds(item, r, ctx) -> bool:
        """Image r: its resource and its number (links.media.image_numbers)."""
        return (item is not None and r.kind == "image"
                and (item.picture.resource, item.number) == r.id)

    @staticmethod
    def _program(names) -> str:
        return programs.program_of(names.binary.code) if names else programs.US

    @classmethod
    def title(cls, names, p) -> str:
        """A picture's title in plain words, by what the code does with it
        (formats.resource_pictures.role)."""
        from decoders.plugins.SLUS_006_28.formats import resource_pictures as rp
        from decoders.plugins.SLUS_006_28.formats.resources import BROMIDE_BASE, DISC_CHANGE
        from decoders.plugins.SLUS_006_28.records import events as ev
        jp = cls._program(names) == programs.JP
        r, n = p.resource, p.picture
        if r == rp.GLYPH_ATLAS_RESOURCE and n is None:
            return "The font's letters"
        if r == rp.TITLE_RESOURCE:
            if n is None:
                page = None if jp else rp.TITLE_PAGES.get(p.vram_x)
                return f"The title screen: {page}" if page else "A page of the title screen"
            if jp and n < rp.JP_CARDS:
                return f"Before the title, {n + 1} of {rp.JP_CARDS}"
            return "Before the title" if n == 0 else "Never shown in the game"
        k = r - BROMIDE_BASE
        if 0 <= k < ev.BROMIDE_COUNT and n in (0, 1):
            name = (names.bromide(k) if names else None) or f"bromide {k}"
            return f"{name}: {'top' if n == 0 else 'bottom'} picture"
        if r == DISC_CHANGE and n is not None and n < 4:
            return f"Asks for disc {1 + (n & 1)}" + (" again, after a refused disc" if n & 2 else "")
        if r == DISC_CHANGE and n == 4:
            return "After the end, while the closing audio plays"
        if r == DISC_CHANGE and n == 5:
            return "After the end, the last screen"
        return "A picture"

    @classmethod
    def _screen(cls, p, program: str) -> tuple[str, str] | None:
        """The Screens heading a picture is listed under; None for one
        that is not a screen."""
        from decoders.plugins.SLUS_006_28.formats import resource_pictures as rp
        from decoders.plugins.SLUS_006_28.formats.resources import DISC_CHANGE
        n = p.picture
        if p.resource == rp.TITLE_RESOURCE:
            shown = rp.JP_CARDS if program == programs.JP else 1
            return cls.TITLE if n is None or n < shown else None
        if p.resource == DISC_CHANGE and n is not None:
            return cls.DISCS if n < 4 else cls.END if n < 6 else None
        return None

    @staticmethod
    def _resource(resource: int) -> tuple[str, str]:
        """All images' heading for a resource: its region (formats.resources)."""
        from decoders.plugins.SLUS_006_28.formats import resources as rs
        reg = rs.region(resource)
        if reg is None:
            return f"Resource {resource}", ""
        head = (f"Resource {reg.first}" if reg.first == reg.last
                else f"Resources {reg.first} to {reg.last}")
        return head, reg.what

    def _ensure(self, ctx) -> list[tuple]:
        if self._found is not None:
            return self._found
        from decoders.plugins.SLUS_006_28.formats import command_list as cl
        from decoders.plugins.SLUS_006_28.formats import resource_pictures as rp
        from decoders.plugins.SLUS_006_28.formats import resources as rs
        from viewer_tabs.links.media import image_numbers
        names = GameNames.for_ctx(ctx)
        found = []
        if names is not None:
            with open(ctx.path("LUNADATA.FIL"), "rb") as f:
                for res in names.resources():
                    if not rs.is_command_list(res.index):
                        continue
                    f.seek(res.offset)
                    buf = f.read(res.size)
                    numbers = image_numbers(cl.commands(buf))
                    found += [(p, numbers[p.offset][0]) for p in rp.pictures(buf, res.index)]
        self._found = found
        return found

    def get_items(self, cache, archive, ctx, selected):
        found = self._ensure(ctx)
        if not found:
            return [("No pictures found", None)]
        names = GameNames.for_ctx(ctx)
        program = self._program(names)
        out = []
        for p, n in found:
            title = self.title(names, p)
            if self.view == "All images":
                words = [title, f"image {p.resource}/{n}", f"{p.width}x{p.height}"]
                if p.sent_at_once:
                    words.append("sent at once")
                head = self._resource(p.resource)
            else:
                head = self._screen(p, program)
                if head is None:
                    continue
                words = [title, f"image {p.resource}/{n}"]
            out.append(("  ".join(words), Shown(p, n, title, *head)))
        return out or [("No screens found", None)]

    def item_identity(self, label, item, ctx) -> Identity:
        """A picture by its resource and its number there (a picture sent
        at once by its place among the resource's), compared by its title
        and its TIM; one with no CLUT of its own by the whole resource,
        whose earlier pictures leave it its colours."""
        from decoders.plugins.SLUS_006_28.formats import command_list as cl
        p = item.picture
        if p.picture is not None:
            key = f"resource {p.resource} picture {p.picture}"
        else:
            sent = [q.offset for q, _n in self._ensure(ctx)
                    if q.resource == p.resource and q.picture is None]
            key = f"resource {p.resource} sent {sent.index(p.offset)}"
        names = GameNames.for_ctx(ctx)

        def parts() -> list[bytes]:
            buf = names.read_resource(p.resource)
            if not p.has_clut:
                return [item.title.encode(), resource_source(buf, p.resource)]
            return [item.title.encode()] + [c.payload for c in cl.commands(buf)
                                            if c.offset == p.offset]
        return of_parts(key, parts)

    def on_select(self, item, cache, archive, ctx):
        if item is None:
            return SelectResult(info="No pictures available")
        from decoders.psx.formats.tim import MODE_NAMES
        from decoders.plugins.SLUS_006_28.formats import resource_pictures as rp
        from decoders.plugins.SLUS_006_28.formats.resources import DISC_CHANGE
        p = item.picture
        names = GameNames.for_ctx(ctx)
        img, colours = rp.image(names.read_resource(p.resource), p)
        r = rp.role(p, self._program(names))
        lines = [
            item.title,
            f"image {p.resource}/{item.number}",
            f"resource {p.resource}, " + (f"picture {p.picture}" if p.picture is not None
                                          else "sent to VRAM at once")
            + f" (command 2, sub {p.sub}, at {p.offset:#x})",
            f"shown by: {r.shown_by}",
            f"TIM {p.width}x{p.height} {MODE_NAMES.get(p.mode, p.mode)}, "
            f"VRAM ({p.vram_x}, {p.vram_y})",
            f"colours: {colours}",
        ]
        if p.resource == DISC_CHANGE and p.height > rp.SCREEN_PICTURE_H:
            if self.view == "Screens":
                img = img.crop((0, 0, img.width, rp.SCREEN_PICTURE_H))
                lines.append(f"! shown as the screen shows it: its top {p.width} x "
                             f"{rp.SCREEN_PICTURE_H} (screen_picture_put (0x80024C04))")
            else:
                lines.append(f"! the screen shows its top {p.width} x {rp.SCREEN_PICTURE_H}")
        lines += [""] + proven_by_lines(self.PRODUCER)
        return SelectResult(images=[img], info="\n".join(lines),
                            ref=ref("image", p.resource, item.number))


@dataclass(frozen=True)
class ResourceRow:
    """One row of All Files: a resource and what is known of it."""
    resource: Any               # formats.resource_table.Resource
    region: Any                 # formats.resources.Region, None outside 1..599
    role: str                   # what it is, named the way the game names it
    toc_name: str | None        # the archive TOC entry starting at its first sector
    commands: str               # command_list.summary; "" when not a command list
    tabs: tuple[str, ...]       # the tabs that show it

    @property
    def index(self) -> int:
        return self.resource.index


class ResourcesProvider:
    """Every resource of LUNADATA.FIL, by number — the way the game reads it.

    The game never reads the archive's own table of contents (46 names): it
    reads a resource by number from the program's g_ResourceSectorPairs
    (0x800AE904) (formats.resource_table), and resources 1 to 599 lie back to
    back from sector 16 to the archive's end. Each row gives a resource's
    sectors and size, what it is and the code that reads it
    (formats.resources, docs/spec/file-sector-map/overview.md §"The
    resources, by number"), the summary of its command list when that code
    runs one (formats.command_list), and the tab that shows it. A TOC name is
    shown where a TOC entry starts at the resource's first sector.
    """

    name = "Resources"
    key = "resources"
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = False
    supports_grid = False
    supports_layers = False

    PRODUCER = "decoders.plugins.SLUS_006_28.formats.resources"
    HEXDUMP_BYTES = 128

    #: Which tab shows a region's resources (formats.resources keys).
    TABS = {
        "system": ("strings", "screens", "menus"),
        "common-sheet": ("menus",),
        "title": ("screens", "menus"),
        "maps": ("maps",),
        "scripts": ("dialogue", "story-flags"),
        "portrait-files": ("portraits",),
        "scene-portraits": ("portraits",),
        "sprite-palettes": ("sprites",),
        "party-records": ("data-tables",),
        "sound-common": ("sound-effects", "sound-banks"),
        "sound-music": ("music", "sound-banks"),
        "sound-area": ("sound-effects", "sound-banks"),
        "sound-battle": ("sound-effects", "sound-banks"),
        "battle-sets": ("battles",),
        "battle-party": ("battles",),
        "party-sheets": ("sprites",),
        "object-sets": ("sprites",),
        "bromides": ("bromides", "screens"),
        "disc-change": ("screens",),
    }

    homes = {"resource": (None,)}

    def __init__(self):
        self._rows: list[ResourceRow] | None = None

    @staticmethod
    def holds(row, r, ctx) -> bool:
        return row is not None and row.index == r.id[0]

    def _ensure(self, archive, ctx) -> list[ResourceRow]:
        if self._rows is not None:
            return self._rows
        from decoders.plugins.SLUS_006_28.formats import command_list as cl
        from decoders.plugins.SLUS_006_28.formats import resources as rs

        names = GameNames.for_ctx(ctx)
        if names is None:
            return []                       # asked again, read again
        maps = {m.resource: m for m in names.maps()}
        toc = {e.sector: e.name for e in archive.toc_entries} if archive else {}
        rows = []
        with open(ctx.path("LUNADATA.FIL"), "rb") as f:
            for res in names.resources():
                reg = rs.region(res.index)
                summary = ""
                if reg is not None and reg.commands:
                    f.seek(res.offset)
                    summary = cl.summary(cl.commands(f.read(res.size)))
                rows.append(ResourceRow(
                    resource=res, region=reg,
                    role=self._role(names, maps, res.index, reg, ctx),
                    toc_name=toc.get(res.start_sector), commands=summary,
                    tabs=self.TABS.get(reg.key, ()) if reg else ()))
        self._rows = rows
        return rows

    @staticmethod
    def _role(names: GameNames, maps: dict, n: int, reg, ctx=None) -> str:
        """What resource n is, with the game's own name for it where there
        is one; a bank of sound by what it plays: its songs, or whose sound
        effects (links.sound_effects)."""
        from decoders.plugins.SLUS_006_28.formats import resources as rs
        from decoders.plugins.SLUS_006_28.formats import sound_banks as sb
        from viewer_tabs.links import sound_effects as lsx
        if reg is None:
            return "outside the regions the code reads"
        if n in maps:
            m = maps[n]
            place = names.location(m.area.location) or f"location {m.area.location:#04x}"
            return f"map {m.map_id:#04x}: {place}"
        if reg.key == "scripts":
            ids = names.script_ids_for_resource(n)
            return ("script " + ", ".join(f"{i:#04x}" for i in ids)) if ids \
                else "a script no script id names"
        if reg.key == "bromides":
            title = names.bromide_resource(n)
            return rs.number_in_region(n) + (f": {title}" if title else "")
        if reg.key == "sound-music":
            songs = lsx.song_words(names, names.bgm_numbers_for_bank(n))
            return "music bank" + (f": {songs}" if songs else "")
        if reg.key in sb.SFX_REGIONS and ctx is not None:
            try:
                said = lsx.bank_words(GameModel.for_ctx(ctx), n)
            except Exception:           # the bank's places are extra
                said = ""
            if said:
                return f"sound effects bank: {said}"
        return rs.number_in_region(n) or reg.what

    def get_items(self, cache, archive, ctx, selected):
        rows = self._ensure(archive, ctx)
        if not rows:
            return [(no_names(ctx, "The resources are found through the program's resource "
                                   "table"), None)]
        return [(f"{r.index:3d}  {r.role}  {r.resource.size // 1024}K", r) for r in rows]

    def item_identity(self, label, row: ResourceRow, ctx) -> Identity:
        """A resource by its number, compared by its bytes as the code reads
        them (names.resource_source): where it lies on the disc is not part
        of it."""
        archive = ctx.path("LUNADATA.FIL")
        return of_parts(f"resource {row.index}",
                        lambda: [resource_source(row.resource.read(archive), row.index)])

    def get_layer_options(self):
        return []

    def on_select(self, row: ResourceRow, cache, archive, ctx):
        if row is None:
            return SelectResult(info="No resources")
        from decoders.plugins.SLUS_006_28.formats import command_list as cl

        res, reg = row.resource, row.region
        with open(ctx.path("LUNADATA.FIL"), "rb") as f:
            f.seek(res.offset)
            buf = f.read(res.size)
        listed = reg is not None and reg.commands

        badges = [{"text": f"{res.index:#05x}", "tone": "muted",
                   "hint": "its number in hex"},
                  {"text": size_text(res.size), "tone": "muted",
                   "hint": f"{res.size:,} bytes"},
                  {"text": "command list", "tone": "info",
                   "hint": f"entry types {row.commands}"} if listed else
                  {"text": "read as it lies", "tone": "muted",
                   "hint": "its reader takes it without a command list"}]
        fields = [
            ["Sectors", f"{res.start_sector} to "
                        f"{res.start_sector + res.size_sectors - 1}",
             f"{res.size_sectors} sector{'s' if res.size_sectors != 1 else ''}"],
            ["Size", f"{res.size:,} bytes", size_text(res.size)],
            ["Offset", f"{res.offset:#x}", "in LUNADATA.FIL"],
        ]
        if row.toc_name:
            fields.append(["TOC entry", row.toc_name,
                           "the archive's own table; the game does not read it"])
        sections = [{"title": "Resource", "fields": fields}]
        if reg is None:
            sections.append({"title": "In the game",
                             "note": "No region the code reads holds it."})
        else:
            sections.append({"title": "In the game", "style": "prose", "fields": [
                ["Region", f"resources {reg.first} to {reg.last}: {reg.what}", ""],
                ["Read by", reg.reader, ""]]})
        names = {cls.key: cls.name for cls in PROVIDER_CLASSES}
        if row.tabs:
            sections.append({"title": "Shown in",
                             "chips": [{"label": names.get(t, t), "on": True, "icon": t}
                                       for t in row.tabs]})
        else:
            sections.append({"title": "Shown in", "note": "No tab shows it yet."})

        if listed:
            cmds = cl.commands(buf)
            numbers = {id(c): n for c, n in cl.pictures(cmds)}
            sections.append({
                "title": "Command list",
                "aside": "resource_command_run (0x800202FC)",
                "table": {"columns": ["offset", "type", "sub", "bytes", "what"],
                          "align": ["right"] * 4 + ["left"],
                          "rows": [[f"{c.offset:#x}", str(c.type), f"{c.arg:#x}",
                                    f"{len(c.payload):,}",
                                    cl.describe(c, numbers.get(id(c)))]
                                   for c in cmds]}})
        else:
            head = buf[:self.HEXDUMP_BYTES]
            sections.append({"title": f"First {len(head)} bytes",
                             "aside": f"of {res.size:,}",
                             "hex": {"offset": 0, "bytes": head.hex()}})
        proof = proven_by_section(self.PRODUCER)
        if proof:
            sections.append(proof)

        sheet = {"title": f"Resource {res.index}", "subtitle": row.role,
                 "badges": badges, "sections": sections}
        return SelectResult(sheet=sheet,
                            info=f"resource {res.index}\nwhat: {row.role}\n"
                                 f"size: {res.size:,} bytes",
                            ref=ref("resource", res.index))


# ---------------------------------------------------------------------------
# Program text — the program's own text
# ---------------------------------------------------------------------------

class ProgramText:
    """The Strings tab's view "In the program": the text the program keeps
    as it is — the dictionary of words packed strings put in, the
    memory-card short location names and the developers' texts the
    register names, each with the code that reads it (formats.script_text).

    The game's dialogue is not here: it lives in the scripts (command
    0x02, ScriptCommandMessageDisp (0x8005AB1C)), packed against this
    dictionary — the Dialogue tab.
    """

    def __init__(self):
        self._blocks = None
        self._exe_path = None
        #: why the program's text could not be read (it is tried again)
        self._error = ""

    def _ensure_loaded(self, ctx):
        """Lazy-load the text regions from the game executable."""
        if self._blocks is not None:
            return

        try:
            from decoders.psx.analysis.exe_loader import load_exe
            from decoders.plugins.SLUS_006_28.formats.script_text import exe_text_blocks
            exe_path = ctx.exe_path
            if not exe_path.exists():
                # Fallback: hunt the dump for a PS-X EXE by header.
                from decoders.psx.analysis.exe_loader import find_exe
                exe_path = find_exe(ctx.data_dir)
            binary = load_exe(exe_path)
            self._blocks = exe_text_blocks(binary)
            self._binary = binary
            self._error = ""
        except Exception as ex:
            self._error = f"{type(ex).__name__}: {ex}"

    def get_items(self, cache, archive, ctx, selected):
        self._ensure_loaded(ctx)
        items = []
        for block in self._blocks or ():
            items.append((f"{block.label} ({len(block.entries)})", block))
        if not items:
            items.append(("Could not read the program's text"
                          + (f": {self._error}" if self._error else ""), None))
        return items

    def item_identity(self, label, block, ctx) -> Identity:
        """A block by its name, compared by its strings' bytes in the
        program; where they lie is not part of it."""
        binary = self._binary

        def parts() -> list[bytes]:
            out = []
            for e in block.entries:
                n = min(0x100, binary.code_end - e.address)
                out.append(bytes(binary.read_bytes(e.address, n)).split(b"\0")[0])
            return out
        return of_parts(block.label, parts)

    def get_layer_options(self):
        return []

    def on_select(self, block_data, cache, archive, ctx):
        if block_data is None:
            return SelectResult(info="No text data available")

        # a program with no such region (the Japanese one's dictionary) has
        # no address to give
        top = [block_data.label, f"{len(block_data.entries)} entries"] + (
            [f"address 0x{block_data.address:08X}"] if block_data.address else [])
        head = top + ([block_data.note] if block_data.note else []) + [
            "The dialogue is in the scripts (command 0x02): the Dialogue tab."]
        lines = top + [""]
        lines += [e.text.rstrip() for e in block_data.entries if e.text.strip()]

        return SelectResult(
            text="\n".join(lines),
            info="\n".join(head),
            text_wrap=False,
        )


class DialogueProvider:
    """The game's dialogue: every message of the scripts, in the order of
    each script's code, with who says it.

    A script's text command (0x02, ScriptCommandMessageDisp (0x8005AB1C))
    walks its message with font_string_walk (0x8005A884) against the
    program's dictionary of words; a splice (0xF0nn-0xF6nn) takes a string from
    resource 1's table (MessageControlRun (0x8005AF20)). The speaker is the
    face the message puts up (0xFAnn on the left, 0xFBnn on the right,
    MessageFaceSet (0x8005B36C)), named by its file: faces (id - 1) * 5 + 1
    to id * 5 are file id, the file FaceListByteLoad (0x80076094) loads for
    character id. Command 0x07 (ScriptAnswerRun (0x8005C198)) asks a
    question of two answers.

    "Lines" is each script's messages by label, "Window" each message drawn
    as the game draws its window, a frame per stop (formats.message_window),
    "Markup" each message with its controls named. The scripts are those
    g_ScriptResourcePairs (0x800AF268) names (formats.event_script).

    On SLPS_013.97 a message's glyph codes are read as the characters they
    stand for (formats.jp_characters). The kanji are the console's BIOS
    ROM's, which is not read: they are drawn with an installed Japanese
    font (viewer_tabs.system_font), or as a box with none. "Window" lays
    the window out as that program does (message_window.JP_LAYOUT: its
    MessageRowDisp (0x8005B4A0; SLPS_013.97 0x8005E820) shows 12, 13 or
    17 cells a row by the faces up, and its faces and arrow sit apart
    from the US program's).
    """

    name = "Dialogue"
    key = "dialogue"
    fan_about = """
    Everything said in the game, scene by scene: each line with who says
    it, and the questions the game asks. Window shows each message as the
    game draws its window.

    The Japanese discs' kanji are the console's own, which the viewer does
    not read: they are drawn with a Japanese font installed on this
    computer, or as boxes without one.
    """
    technical_view = "Markup"
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = True
    supports_grid = False
    supports_layers = False

    VIEWS = ("Lines", "Window", "Markup")
    views_change_items = True
    #: on_select reads the program's tables and a script's messages itself
    #: (_ensure, _messages): a script or message the index holds is shown
    #: without the scripts' list made first (TabProvider)
    selects_unlisted = True
    #: A script is the row of the resource it is read from, in every view;
    #: a label is its script's row; a message its own row in Window.
    homes = {"script": VIEWS, "label": ("Lines", "Markup"), "message": ("Window",)}
    PRODUCER = "decoders.plugins.SLUS_006_28.formats.message_window"
    #: How long the Window view shows each stop.
    FRAME_MS = 1600
    #: ScriptCommandAnswerRun (0x8005C42C) runs command 0x07 as pages in
    #: scripts 0 and 0xC8.
    PAGED_SCRIPTS = {0, 0xC8}
    #: The drawn scripts kept.
    KEEP_DRAWN = 4

    def __init__(self):
        self.view = self.VIEWS[0]
        self._env = None
        self._error = ""
        self._scripts: list[tuple[int, list[int]]] = []
        self._read: dict[int, list] = {}
        self._drawn: dict[int, list] = {}
        self._faces: dict[int, Any] = {}
        self._place_names: dict[int, list[str]] = {}
        self._texts: dict[int, str] = {}

    def get_views(self):
        return list(self.VIEWS)

    @staticmethod
    def holds(item, r, ctx) -> bool:
        """Script n is the row of the resource ScriptResourceLoad
        (0x80020D20) reads it from (g_ScriptResourcePairs), and so are its
        labels; message n of a script is the row of its n-th text command."""
        names = GameNames.for_ctx(ctx)
        if names is None or item[0] != ("message" if r.kind == "message" else "script"):
            return False
        if r.id[0] not in names.script_ids_for_resource(item[1]):
            return False
        if r.kind != "message":
            return True
        numbered = GameModel.for_ctx(ctx).messages.numbered(r.id[0])
        n = r.id[1]
        return 1 <= n <= len(numbered) and numbered[n - 1].offset == item[2]

    def get_layer_options(self):
        return []

    # -- reading -------------------------------------------------------------

    def _ensure(self, ctx) -> bool:
        """Read what every script's messages are read with, and which
        scripts there are, all or none: a read that fails says why
        (`_error`) and is made again when asked again."""
        if self._env is not None:
            return True
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        from decoders.plugins.SLUS_006_28.formats import message_window as mw
        from decoders.plugins.SLUS_006_28.formats import system_dat as sd
        from decoders.plugins.SLUS_006_28.formats import system_strings as ss
        from decoders.plugins.SLUS_006_28.formats.face_blocks import CLUT_ROW
        names = GameNames.for_ctx(ctx)
        if names is None:
            self._error = no_names(ctx, "The scripts are found through the program's tables")
            return False
        try:
            image = names.binary.code
            res1 = names.read_resource(ss.RESOURCE)
            rows = sd.palette_rows(res1)
            kanji = system_font.find()
            env = {
                "ctx": ctx, "names": names, "words": ss.words_of(image),
                "commands": es.command_count(image),
                "layout": mw.layout_of(image),
                "chars": ss.exe_char_table(image), "table": ss.block(res1),
                "font": mw.Font(image, rom_font=kanji and kanji.pattern), "kanji": kanji,
                "text": sd.colours(rows[sd.TEXT_ROW]),
                "face": sd.colours(rows[CLUT_ROW])}
            by_res: dict[int, list[int]] = {}
            for sid, res in es.script_resources(image).items():
                by_res.setdefault(res, []).append(sid)
        except Exception as e:
            self._error = (f"Could not read the program's tables and resource 1: "
                           f"{type(e).__name__}: {e}")
            return False
        self._scripts = [(res, sorted(ids)) for res, ids in sorted(by_res.items())]
        self._env, self._error = env, ""
        return True

    def _messages(self, res: int, drawn: bool = False) -> list:
        """The script's messages, read (and drawn) through one window. Read,
        they are the game model's (model.Messages: the same reading, made
        once for the discs that carry the same program and LUNADATA.FIL),
        where it has them."""
        from decoders.plugins.SLUS_006_28.formats import message_window as mw
        keep = self._drawn if drawn else self._read
        if res not in keep:
            e = self._env
            read = None if drawn else self._read_by_model(res)
            keep[res] = read if read is not None else mw.script_messages(
                e["names"].read_resource(res), e["words"], e["chars"], e["table"], e["font"],
                drawn, e["commands"])
            if drawn and len(self._drawn) > self.KEEP_DRAWN:
                self._drawn.pop(next(iter(self._drawn)))
        return keep[res]

    def _read_by_model(self, res: int) -> list | None:
        """Resource `res`'s messages as the disc's model read them, or None
        where it did not (its Messages could not be made, or this script
        could not be read: reading it here says why)."""
        try:
            return GameModel.for_ctx(self._env["ctx"]).messages.by_resource.get(res)
        except Exception:
            return None

    def _places(self, res: int) -> list[str]:
        """The places the script names: the locations it sets (0x49,
        ScriptCommandPlaceNameSet (0x8005E9D4)) and the maps it changes to."""
        if res not in self._place_names:
            self._place_names[res] = self._read_places(res)
        return self._place_names[res]

    def _read_places(self, res: int) -> list[str]:
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        names = self._env["names"]
        buf = names.read_resource(res)
        cmds, _gaps = es.script_code(buf, self._env["words"], self._env["commands"])
        out = [names.location(c.u8(buf, 2)) for c in cmds if c.id == es.SET_LOCATION]
        out += [names.map_name(sc["map"]) for sc in es.scene_changes(buf, cmds)
                if sc["map"] is not None]
        return list(dict.fromkeys(p for p in out if p))

    # -- naming --------------------------------------------------------------

    def _face_name(self, face: int) -> str:
        from decoders.plugins.SLUS_006_28.formats.face_blocks import MEMBER_LIMIT, face_file
        file = face_file(face)[0]
        who = self._env["names"].character(file) if 1 <= file < MEMBER_LIMIT else None
        return f"{who} (portrait {face})" if who else f"portrait {face}"

    def _who(self, faces, short: bool = False) -> str:
        """The speakers for (place, face) pairs: a member's name, else the
        portrait's number."""
        names = [self._face_name(f) for _p, f in faces]
        if short:
            names = [n.split(" (portrait")[0] for n in names]
        return " & ".join(names) or "no portrait"

    def _script_title(self, res: int, ids: list[int]) -> str:
        return ("script " + ", ".join(str(i) for i in ids)) if ids else f"resource {res}"

    # -- items ---------------------------------------------------------------

    def get_items(self, cache, archive, ctx, selected):
        if not self._ensure(ctx):
            return [(self._error, None)]
        items = []
        for res, ids in self._scripts:
            msgs = self._messages(res)
            texts = sum(1 for m in msgs if m.answers is None)
            places = self._places(res)
            where = ", ".join(places[:3]) + (", ..." if len(places) > 3 else "")
            label = f"{self._script_title(res, ids)}  {where or 'names no place'}  {texts} messages"
            items.append((label, ("script", res)))
            if self.view != "Window":
                continue
            n = 0
            for m in msgs:
                n += m.answers is None
                if not m.screens:
                    continue
                first = m.said[0] if m.said else None
                line = " ".join((first.text.split("\n")[0] if first else "").split())
                who = self._who(first.faces, short=True) if first and first.faces else ""
                number = f"message {ids[0]}/{n}" if ids and m.answers is None else f"{m.offset:04X}"
                items.append((f"  {who + ': ' if who else ''}{line[:40]}  {number}",
                              ("message", res, m.offset)))
        return items

    def item_identity(self, label, item, ctx) -> Identity:
        """A script by its resource number, compared by its bytes. A
        message by its place in its script's text: a place names the same
        message only in the same text, so the text's digest is part of the
        key (a translation's messages are never another's versions)."""
        res = item[1]
        names = self._env["names"]
        key = f"script resource {res}"
        if item[0] == "message":
            if res not in self._texts:
                self._texts[res] = hashlib.sha1(names.read_resource(res)).hexdigest()
            key += f" text {self._texts[res]} message {item[2]:04X}"
        return of_parts(key, lambda: [names.read_resource(res)])

    # -- selection -----------------------------------------------------------

    def on_select(self, item, cache, archive, ctx):
        if item is None or not self._ensure(ctx):
            return SelectResult(info=self._error or "No dialogue")
        if item[0] == "message":
            return self._window(item[1], item[2])
        res = item[1]
        ids = dict(self._scripts).get(res, [])
        msgs = self._messages(res)
        fan = None
        if self.view == "Markup":
            body = self._markup(res, msgs)
        else:
            paged = bool(set(ids) & self.PAGED_SCRIPTS)
            body = self._text(msgs, paged=paged)
            fan = "\n".join(self._text(msgs, paged=paged, offsets=False))
        return SelectResult(text="\n".join(body), text_wrap=False, fan_text=fan,
                            info="\n".join(self._head(res, ids, msgs)),
                            ref=ref("script", ids[0]) if len(ids) == 1 else None)

    def fan_row(self, label, item, ctx) -> dict | None:
        """A message of Window in Fan mode: its number where it has one,
        and a question's answers said so, not by their place in the
        script."""
        if item[0] != "message" or label.rsplit("  ", 1)[-1].startswith("message "):
            return None                      # a script, or a message by its number
        if not self._ensure(ctx):
            return None
        ids = dict(self._scripts).get(item[1], [])
        m = next((m for m in self._messages(item[1]) if m.offset == item[2]), None)
        if m is None or (ids and m.answers is None):
            return None
        paged = bool(set(ids) & self.PAGED_SCRIPTS)
        return {"sub": ("the page prompt" if paged else "the answers")
                if m.answers is not None else ""}

    def _head(self, res: int, ids: list[int], msgs: list) -> list[str]:
        texts = [m for m in msgs if m.answers is None]
        rom = sum(m.rom_glyphs for m in msgs)
        boxed = sum(m.rom_boxed for m in msgs)
        empty = sum(m.empty_splices for m in msgs)
        head = [f"{self._script_title(res, ids)}: resource {res}",
                f"{len(texts)} messages, {len(msgs) - len(texts)} answer commands (0x07)",
                "places: " + (", ".join(self._places(res)) or "none named"), ""]
        head += ["Read in the order of the script's code. The window starts afresh",
                 "at each label (ScriptLabelRun (0x80059FDC)); a message that does",
                 "not close leaves its text and faces to the next one. Labels are",
                 "also jump targets, and the code's flow is not followed: a",
                 "message's state is the one before it in the file."]
        if rom:
            head += system_font.kanji_lines(self._env["kanji"], rom, boxed)
        if empty:
            head.append(f"{empty} splices name an empty slot: skipped.")
        return head + [""] + proven_by_lines(self.PRODUCER)

    def _text(self, msgs: list, paged: bool = False, offsets: bool = True) -> list[str]:
        """Each label's messages, each run of text under who says it.
        Command 0x07's two strings are a question's answers, or in a paged
        script the page prompt's (ScriptPagesRun (0x8005C2C0)). A message
        is led by its place in the script, but for Fan mode (not
        `offsets`)."""
        asks = "page prompt" if paged else "answers"
        out: list[str] = []
        label = object()
        for m in msgs:
            if m.label != label:
                label = m.label
                out += ["", f"Label {label}" if label is not None else "Before the first label"]
            at = f"  {m.offset:04X}  " if offsets else "  "
            if m.answers is not None:
                out.append(f"{at}{asks}: {m.answers[0]}  /  {m.answers[1]}")
                continue
            if not m.said:
                out.append(f"{at}(no text)")
                continue
            for k, said in enumerate(m.said):
                lead = at if k == 0 else " " * len(at)
                out.append(lead + self._who(said.faces))
                out += [" " * (len(at) + 2) + line for line in said.text.split("\n")]
        return out[1:] if out and not out[0] else out

    def _markup(self, res: int, msgs: list) -> list[str]:
        from decoders.plugins.SLUS_006_28.formats import system_strings as ss
        e = self._env
        buf = e["names"].read_resource(res)
        out = []
        for m in msgs:
            if m.answers is not None:
                continue
            mark = ss.decode(buf, m.offset + 2, e["words"], e["chars"], e["table"],
                             e["font"].characters).markup
            lines = mark.split("\n")
            out.append(f"{m.offset:04X}  {lines[0]}")
            out += [" " * 6 + line for line in lines[1:]]
        return out

    def _face_image(self, face: int):
        from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
        if face not in self._faces:
            try:
                px = fb.face_pixels(self._env["names"].read_resource, face)
                self._faces[face] = fb.image(px, self._env["face"])
            except (LookupError, ValueError):
                self._faces[face] = None
        return self._faces[face]

    def _window(self, res: int, offset: int) -> SelectResult:
        from decoders.plugins.SLUS_006_28.formats import message_window as mw
        m = next((m for m in self._messages(res, drawn=True) if m.offset == offset), None)
        if m is None or not m.screens:
            return SelectResult(info="This message puts nothing in the window.")
        layout = self._env["layout"]
        frames = [mw.draw(sc, self._env["text"], self._face_image, layout=layout)
                  for sc in m.screens]
        sheet = Image.new("RGBA", (mw.WIDTH, mw.HEIGHT * len(frames)), (0, 0, 0, 0))
        for i, f in enumerate(frames):
            sheet.paste(f, (0, i * mw.HEIGHT))
        stops = {"prompt": "waits for a press", "page": "a new page without a wait",
                 "close": "closes without a wait", "open": "the message ends, the window open"}
        info = [f"Message at {offset:#06x} of resource {res}, label {m.label}",
                f"{len(frames)} stops, one a frame:"]
        info += [f"  {i + 1}. {stops[sc.why]}" + (f": {self._who(tuple((p, f) for p, f in sc.faces.items()))}"
                                                  if sc.faces else "")
                 for i, sc in enumerate(m.screens)]
        info += ["", "The screen's rows 144 to 215 on a clear background: the half-",
                 "transparent shade, the text (row 507 from colour 0xE0), the faces",
                 "(row 503, from the face's own file) and, at a press, the arrow.",
                 "The arrow does not bob here."]
        if layout is mw.JP_LAYOUT:
            info += ["Laid out as SLPS_013.97 lays it (message_window.JP_LAYOUT): with",
                     "a face up a row shows the first 12 or 13 of its 17 cells."]
        if m.rom_glyphs:
            info += system_font.kanji_lines(self._env["kanji"], m.rom_glyphs, m.rom_boxed)
        info += [""] + proven_by_lines(self.PRODUCER)
        text = "\n\n".join(sc.text for sc in m.screens)
        return SelectResult(images=[sheet], frames=frames, frame_interval_ms=self.FRAME_MS,
                            info="\n".join(info), text=text)


class StringsProvider:
    """The game's string table — every name the menus and the battle UI
    print, by category.

    LUNADATA resource 1, loaded first thing at boot (main (0x80013D2C) ->
    resource_load_run(1) (0x800202CC)); its type-1 command is inflate16 data resource_command01_set (0x80020480)
    unpacks into g_ResourceCommand01Buffer (0x800B8868), font_string_put (0x80026F78) looks a string up by id and
    font_string_walk (0x8005A884) decodes it — a 0x0E run is ASCII - 0x1F with
    dictionary words, then 16-bit codes. formats.system_strings;
    docs/spec/text.md §"The string table".

    A string with controls shows a second, marked line, each control named
    as a message window (MessageControlRun, 0x8005AF20) acts on it: {MOVE:npx} the pen
    moves n pixels (the plain line shows one space), {STYLE:n} the glyph
    style, {FACE_LEFT:0xnn} / {FACE_RIGHT:0xnn} a portrait, {PROMPT} wait for
    the button, {PAGE} a new page, {CLOSE} close, {STR:0xnnn} another string
    spliced in.
    """

    name = "Strings"
    key = "strings"
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = False
    supports_grid = False
    supports_layers = True
    PRODUCER = "decoders.plugins.SLUS_006_28.formats.system_strings"
    #: docs/taxonomy.md: the string table, and the text the program keeps
    #: (ProgramText) — the tab once called EXE Strings
    VIEWS = ("String table", "In the program")

    def __init__(self):
        self._labels: list[str] = []
        self.view = self.VIEWS[0]
        self._program = ProgramText()

    def get_views(self):
        return list(self.VIEWS)

    @staticmethod
    def _in_table(item) -> bool:
        """A string table row is ("cat", category); the program's are
        its text blocks."""
        return isinstance(item, tuple) and item[:1] == ("cat",)

    def get_layer_options(self):
        return [str(i) for i in range(len(self._labels))]

    def get_layer_labels(self):
        return list(self._labels)

    def get_items(self, cache, archive, ctx, selected):
        if self.view == "In the program":
            return self._program.get_items(cache, archive, ctx, selected)
        from decoders.plugins.SLUS_006_28.formats import system_strings as ss
        names = GameNames.for_ctx(ctx)
        if names is None:
            return [(no_names(ctx, "The string table (resource 1) is found through the "
                                   "program's resource table"), None)]
        ids = [sid for sid, _t in names.strings.items()]
        out = []
        for c in ss.CATEGORIES:
            n = sum(1 for i in ids if c.first <= i <= c.last)
            how = f"id = {c.base:#05x} + n" if c.base else "id = n"
            out.append((f"{c.name}  {n} strings  {c.first:#05x}-{c.last:#05x}  {how}"
                        f"{'' if c.proof else '  (layout)'}", ("cat", c.name)))
        return out

    def item_identity(self, label, item, ctx) -> Identity:
        """A category by its name, compared by its strings' bytes: each id's
        string as font_string_walk (0x8005A884) reads it from the table."""
        if not self._in_table(item):
            return self._program.item_identity(label, item, ctx)
        from decoders.plugins.SLUS_006_28.formats import system_strings as ss
        names = GameNames.for_ctx(ctx)
        c = ss.BY_CATEGORY[item[1]]

        def parts() -> list[bytes]:
            image = names.binary.code
            blk = ss.block(names.read_resource(ss.RESOURCE))
            words, chars = ss.words_of(image), ss.exe_char_table(image)
            out = []
            for sid in range(c.first, min(c.last + 1, ss.table_size(blk))):
                off = ss.string_offset(blk, sid)
                if off:
                    try:
                        end = ss.codes(blk, off, words, chars)[1] + 1
                    except ValueError:              # no end: the rest of the block
                        end = len(blk)
                    out.append(struct.pack("<H", sid) + blk[off:end])
            return out
        return of_parts(f"category {c.name}", parts)

    def on_select(self, item, cache, archive, ctx):
        from decoders.plugins.SLUS_006_28.formats import system_strings as ss
        names = GameNames.for_ctx(ctx)
        self._labels = []
        if item is not None and not self._in_table(item):
            return self._program.on_select(item, cache, archive, ctx)
        if not item or names is None:
            return SelectResult(info="Nothing to show")
        c = ss.BY_CATEGORY[item[1]]
        rows = [e for e in names.strings.entries() if c.first <= e[0] <= c.last]
        info = [c.name, f"ids: {c.first:#05x}-{c.last:#05x}", f"index: id - {c.base:#05x}",
                f"strings: {len(rows)}", "source: lunadata",
                "resource: 1 (type-1 command, inflate16)",
                f"ids from: {c.proof}" if c.proof else
                "! ids placed by the table's layout: no code that builds them "
                "was found (docs/spec/text.md §\"Open\")"]
        text = [f"{'id':>5}  {'n':>4}  text", "-" * 60]
        for sid, shown, markup in rows:
            text.append(f"{sid:#05x}  {sid - c.base:4d}  {shown.replace(chr(10), ' / ')}")
            if markup != shown:
                text.append(f"{'':13}{markup!r}")
        images, layers = [], None
        if programs.program_of(names.binary.code) == programs.JP:
            kanji = system_font.find()
            ids = [sid for sid, _s, _m in rows]
            images = [self._drawn(names, ids, kanji)]
            if kanji is not None and images[0] is not None:
                images.append(self._drawn(names, ids, kanji, self.TINT))
                layers = self._labels = ["drawn", "font's kanji tinted"]
            info += ["", "Drawn: each string with SLPS_013.97's own glyphs, one under",
                     "another in the order of the list (message_window.string_image:",
                     "font_pattern_get and font_code_put's widths). The text reads",
                     "the codes as the characters they stand for (jp_characters)."]
            info += system_font.kanji_lines(kanji, tinted=layers is not None)
        return SelectResult(info="\n".join(info), text="\n".join(text), text_wrap=False,
                            images=[im for im in images if im is not None])

    #: What the second layer blends the font's kanji with.
    TINT = (0x40, 0xC0, 0xFF)

    @staticmethod
    def _drawn(names, ids: list[int], kanji, tint=None) -> Image.Image | None:
        """The strings `ids` drawn with the program's glyphs, one under
        another, splices put in (four deep at most, as the walk allows);
        the kanji ROM's with `kanji` (system_font), tinted with `tint`."""
        from decoders.plugins.SLUS_006_28.formats import message_window as mw
        from decoders.plugins.SLUS_006_28.formats import system_dat as sd
        from decoders.plugins.SLUS_006_28.formats import system_strings as ss
        image = names.binary.code
        res1 = names.read_resource(ss.RESOURCE)
        blk = ss.block(res1)
        words, chars = ss.words_of(image), ss.exe_char_table(image)
        font = mw.Font(image, rom_font=kanji and kanji.pattern)
        colours = sd.colours(sd.palette_rows(res1)[sd.TEXT_ROW])

        def codes(sid: int, depth: int = 0) -> list[int]:
            off = ss.string_offset(blk, sid)
            try:
                got = ss.codes(blk, off, words, chars)[0] if off else []
            except ValueError:
                return []
            out: list[int] = []
            for code in got:
                spliced = ss.splice_id(code)
                if spliced is None:
                    out.append(code)
                elif depth < 4:
                    out += codes(spliced, depth + 1)
            return out

        pics = [mw.string_image(font, codes(sid), colours, tint) for sid in ids]
        gap = 2
        height = sum((p.height if p else mw.CELL) + gap for p in pics)
        width = max((p.width for p in pics if p), default=0)
        if not width:
            return None
        sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        y = 0
        for p in pics:
            if p is not None:
                sheet.paste(p, (0, y))
            y += (p.height if p else mw.CELL) + gap
        return sheet


# ---------------------------------------------------------------------------
# Portraits — the faces by face number, and the scene blocks
# ---------------------------------------------------------------------------

class PortraitsProvider:
    """The portraits as the game names them: by face number (formats.face_blocks).

    "By character" lists faces 1..120 under whose they are (viewer_tabs.whose):
    each character's file and the copies of their pictures, then the faces
    no character is, then the blank ones. "Portrait lists" lists the 42
    blocks FaceSlot6Load (0x8001B50C) reads into slot 6, every one of their
    ten pictures. The palette is row 503 as SYSTEM.DAT loads it
    (system_dat.palette_rows).
    """

    name = "Portraits"
    key = "portraits"
    fan_about = """
    Every portrait the game shows beside what people say, under whose it
    is: each character's, then the ones that are no character's, then the
    blank ones.
    """
    technical_view = "Portrait lists"
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = True
    supports_grid = True
    supports_layers = False

    VIEWS = ("By character", "Portrait lists")
    COLUMNS = 10
    #: The headings of By character after the characters', with their notes.
    NO_ONE = ("No character", "faces no character's file holds, drawn like none of theirs: "
                              "the game names no one for them, and the viewer does not "
                              "name them by eye")
    BLANK = ("Blank", "pictures with nothing drawn")
    ALL = ("All portraits", "every face, by number")
    PRODUCER = "decoders.plugins.SLUS_006_28.formats.face_blocks"
    #: A portrait is its row; a portrait list, its row in Portrait lists.
    homes = {"portrait": ("By character",), "portrait-list": ("Portrait lists",)}

    def __init__(self):
        self.view = self.VIEWS[0]
        self._loaded = False
        self._error = ""
        self._faces: dict[int, tuple] = {}      # face -> (resource, picture, image, blank)
        self._scenes: list[tuple] = []          # (n, resource, FaceBlock, images)
        self._members: dict[int, str | None] = {}   # character id -> name
        self._atlas = None
        self._pixels: dict[int, bytes] = {}     # face -> its 64 x 64 indices
        self._whose: dict = {}                  # face -> whose.Whose
        self._row = b""                         # palette row 503's words

    def get_views(self):
        return list(self.VIEWS)

    @staticmethod
    def holds(item, r, ctx) -> bool:
        """Portrait n is ("face", n, …); portrait list n is ("scene", (n, …))."""
        if r.kind == "portrait-list":
            return item[0] == "scene" and item[1][0] == r.id[0]
        return r.kind == "portrait" and item[0] == "face" and item[1] == r.id[0]

    def _ensure_loaded(self, ctx):
        """Read every face, list and whose each is, all or none: a read
        that fails says why (`_error`) and is made again when asked again."""
        if self._loaded:
            return
        from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
        from decoders.plugins.SLUS_006_28.formats import system_dat

        names = GameNames.for_ctx(ctx)
        if names is None:
            self._error = no_names(ctx, "The faces are found through the program's resource "
                                        "table")
            return
        faces, pixels, scenes = {}, {}, []
        try:
            row = system_dat.palette_rows(names.read_resource(system_dat.RESOURCE))
            colours = system_dat.colours(row[fb.CLUT_ROW])
            words = struct.pack(f"<{len(row[fb.CLUT_ROW])}H", *row[fb.CLUT_ROW])
            files = {}
            for face in range(1, fb.FACES + 1):
                file, picture = fb.face_file(face)
                resource = fb.file_resource(file)
                if file not in files:
                    files[file] = fb.parse(names.read_resource(resource))
                block = files[file]
                if not block.valid or picture >= len(block.images):
                    continue
                px = block.images[picture]
                pixels[face] = bytes(px)
                faces[face] = (resource, picture, fb.image(px, colours), not any(px))
            for n in range(1, fb.SCENE_LIMIT):
                resource = fb.scene_resource(n)
                block = fb.parse(names.read_resource(resource))
                scenes.append((n, resource, block,
                               [fb.image(px, colours) for px in block.images]))
            members = {i: names.character(i) for i in range(1, fb.MEMBER_LIMIT)}
            found = whose.read(pixels)
            atlas = self._grid([faces[f][2] if f in faces else None
                                for f in range(1, fb.FACES + 1)])
        except Exception as e:
            self._error = f"The faces could not be read: {type(e).__name__}: {e}"
            return
        self._row, self._faces, self._pixels, self._scenes = words, faces, pixels, scenes
        self._members, self._whose, self._atlas = members, found, atlas
        self._error = ""
        self._loaded = True

    def _grid(self, images, columns: int | None = None):
        from decoders.plugins.SLUS_006_28.formats.face_blocks import SIDE
        cols = columns or self.COLUMNS
        rows = max(1, (len(images) + cols - 1) // cols)
        sheet = Image.new("RGBA", (cols * SIDE, rows * SIDE), (0, 0, 0, 0))
        for i, im in enumerate(images):
            if im is not None:
                sheet.paste(im, ((i % cols) * SIDE, (i // cols) * SIDE))
        return sheet

    def _member_of(self, face: int) -> int | None:
        """The character whose member face this is ((id - 1) * 5 + 1), or None."""
        from decoders.plugins.SLUS_006_28.formats.face_blocks import member_face
        return next((i for i in self._members if member_face(i) == face), None)

    def _scenes_with(self, face: int) -> list[str]:
        return [f"{n} (picture {block.faces.index(face)})"
                for n, _res, block, _imgs in self._scenes
                if block.valid and face in block.faces]

    def get_items(self, cache, archive, ctx, selected):
        self._ensure_loaded(ctx)
        if self._error:
            return [(self._error, None)]
        if self.view == "Portrait lists":
            items = []
            for scene in self._scenes:
                n, resource, block, _imgs = scene
                listed = ", ".join(str(f) for f in block.faces if f)
                items.append((f"portrait list {n}  "
                              + (f"portraits {listed}" if listed else "lists no portrait"),
                              ("scene", scene)))
            return items
        items = [(f"All portraits  1 to {max(self._faces, default=0)}", ("atlas",) + self.ALL)]
        heads: dict[int, list] = {}
        for face, (_resource, _picture, _im, blank) in sorted(self._faces.items()):
            w = self._whose.get(face, whose.Whose(None))
            if w.character is not None:
                name = self._members.get(w.character)
                twice = [c for c, other in self._members.items() if other and other == name]
                name = (f"{name} (character {w.character})" if len(twice) > 1 else
                        name or f"character {w.character}")
                group = (name, "their portrait file" + (" and the copies of its pictures"
                                                        if any(x.character == w.character and
                                                               x.copy_of for x in
                                                               self._whose.values()) else ""))
                order = w.character
                parts = [f"portrait {face}"]
                if w.copy_of is not None:
                    parts.append(f"a copy of portrait {w.copy_of}")
                elif self._member_of(face):
                    parts.append("the one the menus show")
            else:
                group, order = (self.BLANK, 99) if blank else (self.NO_ONE, 98)
                parts = [f"portrait {face}", f"file {(face - 1) // whose.PER_FILE + 1}"]
            heads.setdefault(order, []).append(("  ".join(parts), ("face", face) + group))
        for order in sorted(heads):
            items += heads[order]
        return items

    def item_identity(self, label, item, ctx) -> Identity:
        """A face by its face number, a scene block by its number, compared
        by their pixels (and a block's face list) and palette row 503."""
        if item[0] == "face":
            face = item[1]
            return of_parts(f"face {face}", lambda: [self._row, self._pixels[face]])
        if item[0] == "scene":
            n, _resource, block, _imgs = item[1]
            return of_parts(f"scene block {n}", lambda: [
                self._row, struct.pack(f"<{len(block.faces)}H", *block.faces),
                *(bytes(px) for px in block.images)])
        return of_parts("all faces", lambda: [
            self._row, *(struct.pack("<H", f) + px for f, px in sorted(self._pixels.items()))])

    def get_layer_options(self):
        return []

    def on_select(self, item, cache, archive, ctx):
        if item is None:
            return SelectResult(info=self._error or "No portraits")
        proof = proven_by_lines(self.PRODUCER)
        tail = ["",
                "64 x 64 at 8 bits; palette row 503 (FaceCellDraw (0x8001B4B0)'s 0x7DC0),",
                "as SYSTEM.DAT's command 0x30C loads it: colour 0 is not drawn."]
        if item[0] == "atlas":
            info = ["All portraits, by number: portrait k at column (k - 1) % 10,",
                    "row (k - 1) / 10. Five a file: file (k - 1) / 5 + 1,",
                    "resource file + 0xA2, picture (k - 1) % 5 (FaceCellSet (0x8001B3DC),",
                    "FaceDataLoad (0x8001B1C0)). Files 1 to 12 are characters 1 to 12's",
                    "(FaceListByteLoad (0x80076094)); files 13 to 24 are no one's."] + tail + [""] + proof
            return SelectResult(images=[self._atlas], info="\n".join(info))
        if item[0] == "scene":
            n, resource, block, imgs = item[1]
            listed = [f"  picture {i}: portrait {f}" if f else f"  picture {i}: not listed"
                      for i, f in enumerate(block.faces)]
            info = [f"Portrait list {n}: resource {resource} ({resource:#x}) (FaceSlot6Load: n + 0xBA)",
                    f"{len(imgs)} pictures, left to right; its list (+0x10), which",
                    "FaceSlot6Find (0x8001B5C4) looks a portrait up in while it is in slot 6:"]
            info += listed
            if not block.valid:
                info.append("! fails FaceDataCheck (0x8001B54C): in slot 6 it lists no portrait")
            if self._members.get(n):
                info += ["", f"Number {n} is also character {n}'s ({self._members[n]}): when the",
                         "portrait list's six places are full, ScriptCommandFaceListSet",
                         "(0x8005E610) puts a character's number in place 6, and FaceSlot6Load",
                         "loads this list."]
            info += tail + [""] + proof
            return SelectResult(images=[self._grid(imgs, columns=len(imgs) or 1)],
                                info="\n".join(info), ref=ref("portrait-list", n))
        from decoders.plugins.SLUS_006_28.formats.face_blocks import face_file
        face = item[1]
        resource, picture, im, blank = self._faces[face]
        file = face_file(face)[0]
        info = [f"Portrait {face}" + (" (blank)" if blank else ""),
                f"file {file}: resource {resource} ({resource:#x}), picture {picture}"]
        w = self._whose.get(face, whose.Whose(None))
        if w.character is not None:
            name = self._members.get(w.character)
            info.append(f"character {w.character}" + (f": {name}" if name else ""))
            if w.copy_of is not None:
                info += [f"  a copy of their portrait {w.copy_of}: all but {w.differ} of its",
                         "  4096 pixels are the same (viewer_tabs.whose)"]
            else:
                info += [f"  FaceListByteLoad (0x80076094) loads file {file} for character "
                         f"{w.character}"]
            if self._member_of(face):
                info += ["  a character's first portrait, (n - 1) * 5 + 1: ShopFaceSet",
                         "  (0x80054C0C) and BtlMenuActingFaceSet (0x80049D60) show it"]
        elif not blank:
            info += ["no character: it is in no character's file, drawn like none of theirs",
                     "  a message names it by its number alone (MessageFaceSet (0x8005B36C))",
                     "  who is drawn is not said: naming them would be a judgement by eye"]
        scenes = self._scenes_with(face)
        if scenes:
            info.append("copies in portrait lists " + ", ".join(scenes))
        info += tail + [""] + proof
        return SelectResult(images=[im], info="\n".join(info), ref=ref("portrait", face))


# ---------------------------------------------------------------------------
# Characters — the party's numbers
# ---------------------------------------------------------------------------

class CharactersProvider:
    """The characters: the party's numbers, 1 to 12, which the string table
    names (viewer_tabs.whose). Character n's portraits are file n's five
    and the copies of them elsewhere; the faces of files 13 to 24 are no
    character's, and the Portraits tab lists them.

    A character's page shows their portraits; for those with a starting
    record (resource 0xE7, ChrRecordsReset (0x80063B30)), their numbers at
    every level (ChrLevelAdd (0x8002844C), ChrLevelUp (0x80028554)), the
    magic they learn (g_BtlSpellRows) and what they start wearing; and the
    scripts their portraits come up in (MessageFaceSet (0x8005B36C)).
    """

    name = "Characters"
    key = "characters"
    fan_about = """
    The game's characters: their portraits; for each the game keeps stats
    for, their stats at every level, the magic they learn and what they
    start out wearing; and the scenes their portraits come up in.
    """
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = False
    supports_grid = False
    supports_layers = False

    #: Character n is its own row.
    homes = {"character": (None,)}

    #: The five numbers a level raises, by the code that reads them
    #: (records.enemy_templates.BATTLE_FIELDS): what each does in a battle.
    STATS = (
        ("+08", "what a hit's amount starts from (BtlHitAmountSet (0x80030070))"),
        ("+0A", "taken off a hit they take (BtlHitAmountSet (0x80030070))"),
        ("+0C", "who acts first in a round, with a draw (BtlTurnOrderMake (0x8002F4B0))"),
        ("+0E", "what the other kind of amount starts from, and a status's chance to take "
                "(BtlStat0EHitAmountSet (0x80035EF8), BtlStatusTakeCheck (0x80035378))"),
        ("+10", "taken off the other kind of amount they take "
                "(BtlStat0EHitAmountSet (0x80035EF8))"),
    )

    def get_views(self):
        return []

    def get_layer_options(self):
        return []

    @staticmethod
    def holds(item, r, ctx) -> bool:
        return item[0] == "character" and item[1] == r.id[0]

    def get_items(self, cache, archive, ctx, selected):
        names = GameNames.for_ctx(ctx)
        if names is None:
            return [(no_names(ctx, "The characters are found through the program's resource "
                                   "table"), None)]
        out = []
        for n in range(1, whose.PARTY_LAST + 1):
            name = self._name(names, n)
            out.append((f"{name}  character {n}" if name else f"character {n}",
                        ("character", n)))
        return out

    @staticmethod
    def _name(names, n: int) -> str | None:
        return names.character(n) if 1 <= n <= whose.PARTY_LAST else None

    def item_identity(self, label, item, ctx) -> Identity:
        """A character by number, compared by the portrait files (their own
        and those a copy of theirs may be in), the starting records, the
        program's tables and the scripts they speak in."""
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
        from decoders.plugins.SLUS_006_28.formats import party_init as pi
        n = item[1]

        def parts():
            names = GameNames.for_ctx(ctx)
            img = names.binary.code
            out = [img, *(names.read_resource(fb.file_resource(f)) for f in range(1, fb.FILES + 1)),
                   names.read_resource(pi.RESOURCE)]
            out += [names.read_resource(res) for _sid, res in sorted(es.script_resources(img).items())]
            return out
        return of_parts(f"character {n}", parts)

    # -- the page -----------------------------------------------------------

    def on_select(self, item, cache, archive, ctx):
        if item is None:
            return SelectResult(info="No characters")
        n = item[1]
        model = GameModel.for_ctx(ctx)
        names = model.need_names()
        name = self._name(names, n)
        sections = [s for s in (self._portraits(model, n), *self._record(model, n),
                                self._spoken(model, n)) if s]
        sheet = {"title": name or f"character {n}",
                 "subtitle": "one of the party's numbers",
                 "badges": [{"text": f"character {n}", "tone": "muted",
                             "hint": f"portrait file {n} ({n:#x})"}],
                 "sections": sections}
        return SelectResult(sheet=sheet, info=f"character {n}", ref=ref("character", n))

    @staticmethod
    def _portraits(model, n: int) -> dict | None:
        from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
        from viewer_tabs.links import battle
        faces = battle._faces(model)
        found = whose.of(model)
        pictures = []
        for p in whose.portraits_of(model, n):
            got = faces.portraits.get(p)
            if got is not None:
                copy = found[p].copy_of
                pictures.append({"image": fb.image(got[2], faces.colours),
                                 "caption": f"portrait {p}" + (f", a copy of {copy}" if copy
                                                                else ""),
                                 "ref": ref("portrait", p)})
        if not pictures:
            return {"title": "Portraits", "note": "Their portrait file holds no picture."}
        out = {"title": "Portraits", "cite": f"file {n}: resource {fb.file_resource(n):#x}",
               "pictures": pictures}
        if any(found[p].copy_of for p in whose.portraits_of(model, n)):
            out["note"] = (f"A copy is drawn as one of theirs but for at most "
                           f"{whose.COPY_PIXELS} of its pixels (the eyes, the mouth), in a "
                           f"file of no character's.")
        return out

    def _record(self, model, n: int) -> list[dict]:
        """At the start, magic and by level, for a character with a
        starting record; nothing for the others."""
        from decoders.plugins.SLUS_006_28.formats import party_init as pi
        from decoders.plugins.SLUS_006_28.records import level_up
        from viewer_tabs.links import battle
        names = model.need_names()
        member = battle._party(model).get(n)
        out = []
        if member is not None:
            p = member.level1
            worn = [names.item(i) or f"item {i}" for i in member.starting_equipment if i]
            fields = [["Level", str(p.level)], ["HP", str(p.hp_max)], ["MP", str(p.mp_max)],
                      ["Wearing", ", ".join(worn) or "nothing"]]
            out.append({"title": "At the start", "cite": "ChrRecordsReset (0x80063B30)",
                        "fields": fields,
                        "note": "The numbers a new game sets up; a scene that brings them "
                                "into the party may raise their level."})
        spells = self._spells(model, n)
        if spells:
            out.append({"title": "Magic", "cite": "ChrLevelUp (0x80028554)",
                        "table": {"columns": ["Spell", "Learned", "MP"],
                                  "rows": spells, "align": ["left", "left", "right"]}})
        if member is not None:
            img = names.binary.code
            buf = names.read_resource(pi.RESOURCE)
            items = pi.exe_items(img)
            raw = pi.level1_records(pi.parse(buf), items)[n]
            cols = pi.by_level(raw, n, items,
                               lambda r, lv: level_up.set_level(r, n, lv, img),
                               last=level_up.LEVEL_CAP)
            stats = ("stat_08", "stat_0a", "stat_0c", "stat_0e", "stat_10")
            rows = [[str(cols["level"][i]), str(cols["hp_max"][i]), str(cols["mp_max"][i]),
                     *(str(cols[s][i]) for s in stats),
                     str(cols["exp_total"][i]), str(cols["exp_next"][i])]
                    for i in range(len(cols["level"]))]
            # the five in the middle by the menu's words for them
            words = [battle.stat_word(model, st) for st in stats]
            out.append({"title": "By level", "cite": "ChrLevelAdd (0x8002844C)",
                        "table": {"columns": ["Level", "HP", "MP", *words,
                                              "EXP", "To next"],
                                  "rows": rows, "align": ["right"] * 10},
                        "fanNote": "Their stats at each level, as a scene that raises their "
                                   "level sets them, wearing what they start with, HP and MP "
                                   "full.",
                        "note": "Their numbers at each level as a scene that raises them "
                                "sets them, wearing what they start with, HP and MP full. "
                                "The five in the middle are headed by the menu's words for "
                                f"them ({battle.STAT_WORDS_PROOF}); the code names none of "
                                "them, and each is the record's place:\n\n"
                                + "\n\n".join(f"{w} ({k}): {what}."
                                                for w, (k, what) in zip(words, self.STATS))})
        return out

    @staticmethod
    def _spells(model, n: int) -> list[list[str]]:
        """[spell, when, MP] for the spells character n learns:
        ChrLevelUp (0x80028554) teaches number 0xB number 1's."""
        from viewer_tabs.links import battle
        names = model.need_names()
        rows = []
        for s, rec in battle._tables(model).spells.items():
            v = rec.values
            if n in (v["chr_id"], battle.SPELL_ALIAS.get(v["chr_id"])) and v["chr_id"]:
                rows.append((v["level"], s, [names.spell(s) or f"spell {s}",
                                             "from the start" if v["level"] <= 1
                                             else f"level {v['level']}", str(v["cost"])]))
        return [r for _lv, _s, r in sorted(rows)]

    @staticmethod
    def _spoken(model, n: int) -> dict:
        from viewer_tabs.links import story, world
        said = story.spoken(model).get(ref("character", n))
        if said is None or not said.shown:
            return {"title": "What they say", "note": "None of their portraits comes up "
                                                      "in a message."}
        w = world._world(model)
        rows = [[w.script_title(sid) or "no map loads it as its own", f"script {sid}",
                 str(count), str(said.opens.get(sid, 0))]
                for sid, count in sorted(said.shown.items())]
        return {"title": "What they say", "cite": story.MESSAGE_FACE_SET,
                "table": {"columns": ["Where", "Script", "Messages", "They open"],
                          "rows": rows, "align": ["left", "left", "right", "right"]},
                "note": f"{said.messages} messages in {len(rows)} scripts. A message counts "
                        "when one of their portraits comes up in it; they open it when its "
                        "first lines show their portrait alone."}


# ---------------------------------------------------------------------------
# Items, Magic, Monsters — what the party finds, learns and fights
# ---------------------------------------------------------------------------

class _AdventureTab:
    """What the Items, Magic, Monsters and Story flags tabs share: their
    rows and pages are read by viewer_tabs.adventure, and a row is one
    thing (its `ref`), its page laid out as its card is."""

    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = False
    supports_grid = False
    supports_layers = False
    views_change_items = True

    VIEWS: tuple[str, ...] = ()
    #: view (None for a tab without views) -> the viewer_tabs.adventure
    #: function that lists it
    LISTS: dict = {}

    def __init__(self):
        self.view = self.VIEWS[0] if self.VIEWS else None

    def get_views(self):
        return list(self.VIEWS)

    def get_layer_options(self):
        return []

    @staticmethod
    def holds(item, r, ctx) -> bool:
        return item.ref == r

    def get_items(self, cache, archive, ctx, selected):
        from viewer_tabs import adventure
        try:
            listed = getattr(adventure, self.LISTS[self.view])(GameModel.for_ctx(ctx))
        except Exception as ex:
            return [(f"Could not read the {(self.view or self.name).lower()}: "
                     f"{type(ex).__name__}: {ex}", None)]
        return listed or [("Nothing to list", None)]

    def item_identity(self, label, item, ctx) -> Identity:
        """A thing by its reference (`item 18`), compared by its row's words
        and the program and LUNADATA.FIL it is read from."""
        from viewer_tabs import adventure
        from viewer_tabs.refs import written
        return of_parts(written(item.ref), lambda: [label.encode(), adventure.same_reading(ctx)])

    def on_select(self, item, cache, archive, ctx):
        if item is None:
            return SelectResult(info=f"No {(self.view or self.name).lower()}")
        from viewer_tabs import adventure
        from viewer_tabs.refs import written
        model = GameModel.for_ctx(ctx)
        extra, shown = self._extra(model, item.ref)
        return SelectResult(sheet=adventure.page(model, item.ref, extra, shown),
                            info=written(item.ref), ref=item.ref)

    def _extra(self, model, r) -> tuple[list[dict], tuple[str, ...]]:
        """Sections the tab adds after a row's facts, and the link groups
        they say already."""
        return [], ()


class ItemsProvider(_AdventureTab):
    """Every item; what can be worn, by the place it is worn in; every shop,
    by the place that opens it, with its stock; every chest that holds
    something, by the place it stands in (one that runs a scene when
    examined is on the Maps tab). An item's picture is its menu icon: MenuIconBytesDisp
    (0x8006C21C) draws an item number as that icon (MenuIconBytesSet
    (0x8006C6F8)). The Japanese program's shops' stock and chests' money
    are not located: its pages say so."""

    name = "Items"
    key = "items"
    fan_about = """
    Every item; what can be worn, by where it is worn; every shop, by the
    place it is in, with what it sells; and every chest that holds
    something, by the place it stands in (a chest that starts a scene is on
    the Maps tab). On the Japanese discs the shops' stock and the chests'
    money are not found yet: their pages say so.
    """
    VIEWS = ("Items", "Equipment", "Shops", "Treasure")
    LISTS = {"Items": "items", "Equipment": "equipment", "Shops": "shops",
             "Treasure": "treasure"}
    homes = {"item": ("Items",), "shop": ("Shops",), "chest": ("Treasure",)}

    def _extra(self, model, r):
        from viewer_tabs import adventure
        if r.kind == "shop":
            return [adventure.shop_stock(model, r.id[0])], ("Sells",)
        return [], ()


class MagicProvider(_AdventureTab):
    """Every spell, by who learns it (its row's character: ChrLevelUp
    (0x80028554)). A spell's picture is its menu icon: MenuIconBytesSpellsSet
    (0x8006C84C) puts a spell's number + 0xB6 in the menu's icon bytes."""

    name = "Magic"
    key = "magic"
    fan_about = """
    Every spell, under the character who learns it, with its menu icon.
    """
    LISTS = {None: "magic"}
    homes = {"spell": (None,)}


class MonstersProvider(_AdventureTab):
    """Every monster: its battle sprite, its stats by the menu's words, what
    it drops, its attacks and where it is met; and every monster attack.
    The debug room's battles come last on where a monster is met."""

    name = "Monsters"
    key = "monsters"
    fan_about = """
    Every monster: how it looks in battle, its stats in the menu's words,
    what it drops, its attacks and where it is met; and every monster
    attack. The debug room's battles come last.
    """
    VIEWS = ("Monsters", "Attacks")
    LISTS = {"Monsters": "monsters", "Attacks": "attacks"}
    homes = {"monster": ("Monsters",), "monster-attack": ("Attacks",)}

    def _extra(self, model, r):
        from viewer_tabs import adventure
        if r.kind == "monster":
            return [adventure.where_met(model, r.id[0])], ("Fought in battles",)
        return [], ()


# ---------------------------------------------------------------------------
# Story flags — what the game remembers you have done
# ---------------------------------------------------------------------------

class StoryFlagsProvider(_AdventureTab):
    """What the game remembers you have done, and what each flag changes.
    One entry per story flag the code touches, under the place that sets
    it; a flag's page says what sets it, clears it and checks it.

    Every flag is one bit of g_StoryBits (0x800B8944), numbered as
    StoryBitSet (0x800576EC) numbers it. What touches one: the scripts'
    labels (commands 0x09-0x1A and 0x5C, and the flags commands 0x23,
    0x24, 0x25, 0x2D and 0x41 touch), chests, tile changes, map objects,
    places entered, movies, bromides and items worn
    (viewer_tabs.links.flags)."""

    name = "Story flags"
    key = "story-flags"
    fan_about = """
    What the game remembers you have done: every story flag, under the
    place that sets it. A flag's page says what sets it, what clears it,
    what checks it and what it changes: a chest shown open, someone no
    longer there, a tile changed on the map.
    """
    homes = {"story-flag": (None,)}

    def get_items(self, cache, archive, ctx, selected):
        from viewer_tabs import story_flags
        try:
            listed = story_flags.story_flags(GameModel.for_ctx(ctx))
        except Exception as ex:
            return [(f"Could not read the story flags: {type(ex).__name__}: {ex}", None)]
        return listed or [("Nothing to list", None)]


# ---------------------------------------------------------------------------
# Data tables — the decoded record tables (docs/spec/battle-data.md)
# ---------------------------------------------------------------------------

def _wrap(text: str, width: int, indent: str) -> list[str]:
    """Greedy wrap; the info notes are long sentences, not code."""
    out, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(indent + line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(indent + line)
    return out


class DataTablesProvider:
    """The battle tables — the monsters' rows, items, spells, attack classes,
    the runtime constants and the party — read from the opened disc.

    Every record table is static data in the program file, read by the
    records decoders (`viewer_tabs.battle_tables` lists where each one
    sits); the party is LUNADATA resource 0xE7 through the code that loads
    and equips it. Each table carries a provenance block, so a number on
    screen can always be traced to where it came from.
    """

    name = "Data tables"
    key = "data-tables"
    programs = SSSC_PROGRAMS
    requires = ("LUNADATA.FIL",)
    supports_zoom = False
    supports_grid = False
    supports_layers = False

    VIEWS = ("Records", "Fields", "Provenance")

    # Table name -> records module carrying the byte layout (offsets/kinds).
    _LAYOUT_MODULES = {
        "enemy_templates": "decoders.plugins.SLUS_006_28.records.enemy_templates",
        "items": "decoders.plugins.SLUS_006_28.records.items",
        "spells": "decoders.plugins.SLUS_006_28.records.spells",
        "attack_classes": "decoders.plugins.SLUS_006_28.records.attack_classes",
    }

    #: A record's nested dict -> the module attribute laying it out. Today
    #: one: enemy_templates' `battle_record`, the copier's output read as
    #: btl.h's BtlStats (BATTLE_FIELDS).
    _NESTED_LAYOUT = {"battle_record": "BATTLE_FIELDS"}

    def __init__(self):
        self.view = self.VIEWS[0]
        self._docs: dict[str, dict] | None = None
        self._strings = None        # GameStrings, the game's string table

    def _tables(self, ctx) -> dict[str, dict]:
        """Every table, read from this disc once."""
        if self._docs is None:
            from decoders.psx.analysis.exe_loader import load_exe
            from decoders.plugins.SLUS_006_28.formats.resource_table import \
                load_resource_table
            from viewer_tabs import battle_tables
            binary = load_exe(ctx.exe_path)
            resources = {r.index: r for r in load_resource_table(binary)}
            self._docs = battle_tables.build(binary.code, ctx.exe_path.name,
                                             resources, ctx.path("LUNADATA.FIL"))
        return self._docs

    def get_views(self):
        return list(self.VIEWS)

    # -- layouts -----------------------------------------------------------

    def _module(self, stem: str):
        """The records module behind a table, or None."""
        mod_name = self._LAYOUT_MODULES.get(stem)
        if not mod_name:
            return None
        try:
            import importlib
            return importlib.import_module(mod_name)
        except Exception:
            return None

    def _layout(self, stem: str, attr: str = "FIELDS") -> dict[str, tuple[int, str]]:
        """-> {field: (offset, kind)} from the records module, if there is one."""
        fields = getattr(self._module(stem), attr, None) or []
        return {name: (off, kind) for off, kind, name, _note in fields}

    def _covered(self, stem: str) -> set[str]:
        """Top-level fields whose every destination a nested record re-reads.

        enemy_templates says where each row byte is copied (COPIER_MAP:
        row offset -> BtlStats offset) and names the stats fields
        (BATTLE_FIELDS). A row field whose destinations all lie in that
        set is the SAME value as a `battle_record` column, so it is shown
        once, there.
        """
        mod = self._module(stem)
        copier = getattr(mod, "COPIER_MAP", None)
        proven = getattr(mod, "BATTLE_FIELDS", None)
        if not copier or not proven:
            return set()
        by_off = {off: name for off, _kind, name, _note in mod.FIELDS}
        dests: dict[str, set[int]] = {}
        for t_off, _width, c_off in copier:
            if t_off in by_off:
                dests.setdefault(by_off[t_off], set()).add(c_off)
        proven_offs = {off for off, *_ in proven}
        return {name for name, offs in dests.items() if offs <= proven_offs}

    # -- provider interface ------------------------------------------------

    def get_items(self, cache, archive, ctx, selected):
        try:
            docs = self._tables(ctx)
        except Exception as e:
            return [(f"Could not read the battle tables: {e}", None)]
        items = []
        for stem, doc in docs.items():
            records = doc.get("records")
            kind = doc.get("_meta", {}).get("source", {}).get("kind", "?")
            if isinstance(records, list):
                label = f"{stem}  {len(records)} rec  [{kind}]"
            else:
                label = f"{stem}  [{kind}]"
            items.append((label, stem))
        return items

    def item_identity(self, label, stem, ctx) -> Identity:
        """A table by its name, compared by its records as the program (and
        resource 0xE7 for the party) hold them; where they lie is not part
        of it."""
        doc = self._tables(ctx)[stem]
        return of_parts(stem, lambda: [json.dumps(
            {k: v for k, v in doc.items() if k != "_meta"},
            sort_keys=True, default=str).encode()])

    def get_layer_options(self):
        return []

    def on_select(self, stem, cache, archive, ctx):
        if stem is None:
            return SelectResult(info="Nothing to show")

        doc = self._tables(ctx)[stem]
        meta = doc.get("_meta", {})
        table = None
        self._strings = self._game_strings(ctx)
        if self.view == "Fields":
            body = self._fields_text(stem, doc)
        elif self.view == "Provenance":
            body = self._provenance_text(stem, doc)
        else:
            body = self._records_text(stem, doc)
            grid = self._records_grid(stem, doc)
            if grid["columns"]:
                table = {k: grid[k] for k in ("columns", "rows", "groups", "notes")}

        records = doc.get("records")
        src = meta.get("source", {})
        lines = [stem]
        if isinstance(records, list):
            lines.append(f"{len(records)} records")
        lines.append(f"source: {src.get('kind', '?')}")
        # Column alignment is the whole point of the record view, so this
        # text must not be word-wrapped.
        return SelectResult(text=body, text_wrap=False, table=table,
                            info="\n".join(lines))

    # -- names -------------------------------------------------------------

    #: The name columns a table gets from the game's string table
    #: (LUNADATA resource 1): (column, category, what, index of the
    #: record in that category). `what` is "name", "names" (a list) or
    #: "description" (the name's string + 0x100). The id arithmetic is
    #: formats.system_strings' (GameStrings), not this table's.
    _NAME_COLUMNS = {
        "enemy_templates": [
            # template row r is enemy id r + 1 (BtlEnemyStatsSet (0x8002A638)'s copier)
            ("name", "enemy", "name", lambda r: r["index"] + 1),
            # kind7_number: BtlEnemyActionAdjust (0x80029510) plans it, and
            # BtlActionStringDisp (0x8004987C) names it (kind 7, number | 0x300).
            # attack_number has no name on screen.
            ("kind7 name", "enemy_special", "name",
             lambda r: r["battle_record"]["kind7_number"] or None),
            # BtlWinItemsGive (0x80028A54) tries nothing unless win_item_1 is 1..0xA4,
            # then win_item_2 (not 0) when win_item_1's draw fails
            ("win items", "item", "names", lambda r: _win_items(r)),
        ],
        "items": [
            ("name", "item", "name", lambda r: r["id"]),
            ("description", "item", "description", lambda r: r["id"]),
        ],
        "spells": [
            ("name", "spell", "name", lambda r: r["number"] or None),
            ("description", "spell", "description", lambda r: r["number"] or None),
        ],
    }

    @staticmethod
    def _game_strings(ctx):
        """The game's string table as GameStrings; None if unreadable."""
        names = GameNames.for_ctx(ctx)
        return names.strings if names else None

    def _name_cells(self, stem: str, rec: dict) -> list[str]:
        out = []
        for _col, category, what, index_of in self._NAME_COLUMNS.get(stem, []):
            try:
                index = index_of(rec)
            except (KeyError, TypeError):
                index = None
            if what == "names":
                out.append(", ".join(self._strings.name(category, i) or f"#{i}"
                                     for i in index or []) or "—")
            elif index is None:
                out.append("")
            elif what == "description":
                out.append(self._strings.description(category, index) or "")
            else:
                out.append(self._strings.name(category, index) or "")
        return out

    @staticmethod
    def _name_note(category: str, what: str) -> str:
        from decoders.plugins.SLUS_006_28.formats.system_strings import BY_CATEGORY
        if what == "description":
            return ("the game's string table — the name's string + 0x100: "
                    f"{BY_CATEGORY['description'].proof}")
        proof = BY_CATEGORY[category].proof
        return f"the game's string table — {proof}" if proof else \
            "the game's string table — placed by its layout only"

    # -- views -------------------------------------------------------------

    def _records_grid(self, stem: str, doc: dict) -> dict:
        """The record table: columns, cell strings, and how they group.

        Columns are every key any live record carries, minus `raw`/`empty`.
        A dict-valued key (enemy_templates' `battle_record`) is spread into
        its own columns and put FIRST, right after the record's id: the
        stats the code reads. Top-level fields that only repeat one of them
        are dropped (`_covered`); the rest of the row follows.

        -> {columns, rows, groups, notes, live, skipped}; empty columns
        when there is no table.
        """
        records = doc.get("records")
        if not isinstance(records, list):
            return {"columns": [], "rows": [], "groups": [], "notes": {},
                    "live": [], "skipped": 0}
        live = [r for r in records if not r.get("empty")]
        top: list[str] = []
        nested: list[tuple[str, str]] = []
        for rec in live:
            for key, val in rec.items():
                if key in ("raw", "empty"):
                    continue
                if isinstance(val, dict):
                    nested += [(key, sub) for sub in val if (key, sub) not in nested]
                elif key not in top:
                    top.append(key)

        covered = self._covered(stem) if nested else set()
        lead, rest = top[:1], [c for c in top[1:] if c not in covered]
        taken = set(lead) | set(rest)
        specs = ([(c, None) for c in lead]
                 + [(sub, key) for key, sub in nested]
                 + [(c, None) for c in rest])
        cols = [f"{key}.{name}" if key and name in taken else name
                for name, key in specs]

        # Nibble pairs and bit sets a records module names, shown in hex
        # at their field's width.
        layout = self._layout(stem)
        hexed = {n: 4 if layout.get(n, (0, "u8"))[1] == "u16" else 2
                 for n in getattr(self._module(stem), "HEX_FIELDS", ())}

        def cell(rec, name, key):
            value = (rec.get(key) or {}).get(name) if key else rec.get(name)
            return _fmt_cell(value, name, 0 if key else hexed.get(name, 0))

        rows = [[cell(rec, name, key) for name, key in specs] for rec in live]

        meta = doc.get("_meta", {})
        notes = {}
        for col, (name, key) in zip(cols, specs):
            note = (meta.get(f"{key}_notes", {}) if key
                    else meta.get("field_notes", {})).get(name)
            if note:
                notes[col] = note

        # The game's names, right after the id; only when the string table
        # could be read.
        named = self._NAME_COLUMNS.get(stem, []) if getattr(self, "_strings", None) else []
        if named:
            at = len(lead)
            cols[at:at] = [col for col, *_ in named]
            rows = [r[:at] + self._name_cells(stem, rec) + r[at:] for r, rec in zip(rows, live)]
            for col, category, what, _i in named:
                notes[col] = self._name_note(category, what)
            lead = lead + [col for col, *_ in named]
        groups = []
        if nested:
            groups = [{"label": "", "span": len(lead)}]
            for key in dict.fromkeys(k for k, _ in nested):
                groups.append({"label": f"{key} — the stats the code reads",
                               "span": sum(1 for k, _ in nested if k == key),
                               "tone": "ok"})
            if rest:
                groups.append({"label": f"not in {key}",
                               "span": len(rest), "tone": "muted"})
        return {"columns": cols, "rows": rows, "groups": groups,
                "notes": notes, "live": live,
                "skipped": len(records) - len(live)}

    def _records_text(self, stem: str, doc: dict) -> str:
        records = doc.get("records")
        if not isinstance(records, list):
            # Not a record table (battle_runtime.json is constants, not rows).
            payload = {k: v for k, v in doc.items() if k != "_meta"}
            return (f"{stem} — document (no record array)\n\n"
                    + json.dumps(payload, indent=2))

        grid = self._records_grid(stem, doc)
        cols, rows = grid["columns"], grid["rows"]
        live, skipped = grid["live"], grid["skipped"]
        if not live:
            return f"{stem} — all {len(records)} records are empty."

        widths = [max(len(c), *(len(r[i]) for r in rows))
                  for i, c in enumerate(cols)]

        out = [f"{stem} — {len(live)} records"
               + (f"  ({skipped} empty omitted)" if skipped else ""), ""]
        if grid["groups"]:
            spans = [g for g in grid["groups"] if g["span"]]
            out.append("columns: " + "  |  ".join(
                f"{g['label'] or 'id'} ({g['span']})" for g in spans))
            out.append("")
        out.append("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
        out.append("  ".join("-" * w for w in widths))
        for row in rows:
            out.append("  ".join(v.ljust(w) for v, w in zip(row, widths)))

        # Undecoded bytes still matter: a reader may take unknown fields out
        # of `raw` at their own risk, so the hex has to be visible.
        if any("raw" in r for r in live):
            key = cols[0] if cols else None
            out += ["", "raw bytes", "---------"]
            for rec in live:
                tag = f"{rec.get(key)}" if key else ""
                out.append(f"{tag.rjust(4)}  {rec.get('raw', '')}")

        unread = doc.get("_meta", {}).get("unread_offsets")
        if unread:
            out += ["", f"unread offsets: {unread}"]
        return "\n".join(out)

    def _fields_text(self, stem: str, doc: dict) -> str:
        meta = doc.get("_meta", {})
        notes = meta.get("field_notes", {})
        layout = self._layout(stem)
        if not notes:
            return f"{stem} — no field notes in this document."

        mod = self._module(stem)
        out = [f"{stem} — field map",
               f"byte layout: {mod.__name__ if mod else '(no records module)'}", ""]

        # The nested records first: they are what a consumer should read.
        for key, attr in self._NESTED_LAYOUT.items():
            nested_notes = meta.get(f"{key}_notes")
            if not nested_notes:
                continue
            nested_layout = self._layout(stem, attr)
            title = f"{key} — the stats, and the code that reads each one"
            out += [title, "-" * len(title)]
            for name, note in nested_notes.items():
                off, kind = nested_layout.get(name, (None, ""))
                head = (f"  +0x{off:02X}  {kind:<6}" if off is not None
                        else "  " + " " * 12)
                out.append(f"{head} {name}")
                out += _wrap(note, 66, " " * 14)
                out.append("")
            title = "row bytes — where the copier puts each one"
            out += [title, "-" * len(title)]

        for name, note in notes.items():
            off, kind = layout.get(name, (None, ""))
            head = f"  +0x{off:02X}  {kind:<6}" if off is not None else "  " + " " * 12
            out.append(f"{head} {name}")
            out += _wrap(note, 66, " " * 14)
            out.append("")
        records = doc.get("records")
        sample = records[0] if isinstance(records, list) and records else {}
        derived = [k for k in ("modifiers", "role", "slot", "id")
                   if k in sample]
        if derived:
            out.append(f"derived (added by the decoder, not bytes): "
                       f"{', '.join(derived)}")
        return "\n".join(out)

    def _provenance_text(self, stem: str, doc: dict) -> str:
        out = [stem, "", "_meta", "-----",
               json.dumps(doc.get("_meta", {}), indent=2)]
        # The block says which decoder read these bytes. It cannot say why
        # we believe the layout, which for this table is a function somebody
        # read: show those too.
        producer = doc.get("_meta", {}).get("source", {}).get("producer", "")
        proven = proven_by_lines(producer)
        if proven:
            out += [""] + proven
        return "\n".join(out)


def _win_items(rec: dict) -> list[int]:
    """The items a won battle may give for an enemy row, as BtlWinItemsGive
    (0x80028A54) tries them."""
    br = rec["battle_record"]
    first, second = br["win_item_1"], br["win_item_2"]
    if not 1 <= first <= 0xA4:
        return []
    return [first] + ([second] if second else [])


def _fmt_cell(value, name: str = "", hex_digits: int = 0) -> str:
    """One record field as a table cell. A `*_mask` is a bit set, so hex;
    so is a field given `hex_digits` (two nibbles, or bits)."""
    if isinstance(value, int) and not isinstance(value, bool):
        if hex_digits:
            return f"0x{value:0{hex_digits}X}"
        if name.endswith("_mask"):
            return f"0x{value:04X}"
    if isinstance(value, bool):
        return "yes" if value else "-"
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            # items.json modifiers: [{selector, stat, amount}]
            return ",".join(f"{m.get('stat', '?')}+{m.get('amount')}"
                            for m in value) or "-"
        return "/".join(str(v) for v in value)
    if value is None:
        return "-"
    return str(value)


# ---------------------------------------------------------------------------
# Disc — one page per disc: its identity and what can read it, for ANY disc
# ---------------------------------------------------------------------------

def _sssc_files(ctx):
    """formats.disc_files and the game's names when the disc on screen is
    SSSC's; (None, None) otherwise."""
    if ctx.program not in SSSC_PROGRAMS or not ctx.has_plugin:
        return None, None
    from decoders.plugins.SLUS_006_28.formats import disc_files
    return disc_files, GameNames.for_ctx(ctx)


STAMP_SAME = "the same: overlay_stamp_check (0x800232B0) takes the overlay"
STAMP_DIFFER = ("they differ: overlay_disc_wait (0x80023184) would ask for the "
                "disc again, and overlay_load (0x80023240) would call its empty "
                "assert_fail and use the overlay anyway")


def _stamp(ctx, df, names):
    """overlay_stamp_check (0x800232B0)'s two texts, read from the disc:
    (overlay file name, StampCheck), or (None, why they cannot be read)."""
    if names is None:
        return None, "the program could not be read"
    overlay = df.overlay_file_name(names.binary)
    path = ctx.path(overlay)
    if not path.exists():
        return None, f"{overlay} is not on this disc"
    with path.open("rb") as fh:
        return overlay, df.stamp_check(names.binary, fh.read(df.STAMP_MAX))


def _stamp_section(ctx, df, names) -> dict:
    """The build stamp card: the two texts and whether they match."""
    section = {"title": "Build stamp"}
    overlay, check = _stamp(ctx, df, names)
    if overlay is None:
        section["note"] = check
        return section
    section["fields"] = [
        ["Program", df.show(check.program), "g_BuildStamp (0x80011000)"],
        [overlay, df.show(check.overlay), "its first bytes"],
    ]
    section["verdict"] = ({"text": STAMP_SAME, "tone": "ok"} if check.match
                          else {"text": STAMP_DIFFER, "tone": "warn"})
    return section


class DiscProvider:
    """Tab 0: one page per disc, named for its disc image — which disc it
    is, and what in the tree can read it.

    The viewer opens dumps from several programs now, and "which one am I
    looking at" must be answerable on screen rather than inferred from
    which tabs happen to have content. Identity comes from gamedb through
    `DiscContext`, and it says HOW it was reached — a checksum match
    against gamedb's measured table is exact, a serial read out of the
    dump's own SYSTEM.CNF is the dump's claim about itself.
    """

    name = "Disc"
    key = "disc"
    supports_zoom = False
    supports_grid = False
    supports_layers = False

    def get_items(self, cache, archive, ctx, selected):
        return [(ctx.image_name, "disc")]

    def item_identity(self, label, topic, ctx) -> Identity:
        """Each disc's own page: never merged with another disc's."""
        return Identity(f"disc:{ctx.disc_serial}")

    def get_layer_options(self):
        return []

    def on_select(self, topic, cache, archive, ctx):
        g = ctx.game
        said, tone, hint = self.IDENTIFIED.get(g.identified_by,
                                               ("not identified", "danger", ""))
        place = (f"disc {g.disc_number} of {g.disc_count}" if g.disc_count > 1
                 else g.role)
        sheet = {
            "title": ctx.image_name,
            "subtitle": g.title,
            "badges": [{"text": said, "tone": tone, "hint": hint},
                       {"text": g.region, "tone": "muted", "hint": "region"},
                       {"text": place, "tone": "muted",
                        "hint": f"{g.disc_count} discs in its set"
                        if g.disc_count > 1 else "role"}],
            "sections": [self._identity_section(ctx),
                         self._capability_section(ctx),
                         *self._sssc_sections(ctx),
                         self._folder_section(ctx)],
        }
        return SelectResult(sheet=sheet, info=ctx.label)

    # -- identity ----------------------------------------------------------

    #: identified_by -> (badge, tone, what it means)
    IDENTIFIED = {
        "checksum": ("identified by checksum", "ok",
                     "the data track's sha256 is in gamedb's table"),
        "serial": ("identified by SYSTEM.CNF only", "warn",
                   "the BOOT line in this dump's own SYSTEM.CNF names it; "
                   "its checksum is not in gamedb's table"),
        "unrecognized": ("not in gamedb", "danger",
                         "gamedb cannot place this disc: everything here is "
                         "the dump's own claim"),
    }

    #: related_to's relationships, as the page says them
    RELATIONS = {
        "bonus-for": "Bonus disc for",
        "demo-of": "Demo of",
        "regional-version-of": "Regional version of",
        "has-bonus": "Its bonus disc",
        "has-demo": "Its demo",
        "has-regional": "Regional version",
    }

    def _identity_section(self, ctx) -> dict:
        g = ctx.game
        total = sum((ctx.path(n).stat().st_size for n in ctx.files), 0)
        fields = [
            ["Disc serial", g.disc_id, ""],
            ["Program", g.program, "the executable this disc boots"],
            ["Volume id", g.volume_id or "—",
             "" if g.volume_id else "blank on this release"],
            ["sha256", g.checksum or "—",
             "" if g.checksum else "not recorded at extraction"],
            ["Disc image", str(g.source) if g.source else "—",
             "" if g.source else "not found"],
            ["Dump", str(ctx.data_dir),
             f"{len(ctx.files)} files · {total / 1024 / 1024:.1f} MB"],
        ]
        for rel, other in ctx.related:
            info = DISC_ID_LOOKUP.get(other)
            fields.append([self.RELATIONS.get(rel, rel.replace("-", " ")),
                           other, info.title if info else ""])
        return {"title": "Identity", "fields": fields}

    def _sssc_sections(self, ctx) -> list[dict]:
        """SSSC's files by role (docs/spec/overview.md), and its build stamp."""
        df, names = _sssc_files(ctx)
        if df is None:
            return []
        files = []
        movies = [n for n in ctx.files if df.role(n) is df.MOVIE_ROLE]
        for n in ctx.files:
            r = df.role(n)
            if r is not df.MOVIE_ROLE:
                files.append([n, r.what if r else "not in the spec", ""])
        if movies:
            files.append(["_Bnnn.STR",
                          f"{len(movies)} movies, STR/MDEC, {movies[0]} to "
                          f"{movies[-1]}", "play event n is _Bnnn.STR"])
        return [{"title": "Files", "aside": "docs/spec/overview.md",
                 "style": "glossary", "fields": files},
                _stamp_section(ctx, df, names)]

    def _folder_section(self, ctx) -> dict:
        g = ctx.game
        if g.disc_count > 1:
            shared = (f"{'Both' if g.disc_count == 2 else f'All {g.disc_count}'}"
                      " discs of this title boot the same program, so they "
                      "share this folder.")
        else:
            shared = ("This program ships on a single disc, so the disc's "
                      "serial and the program's are the same.")
        return {
            "title": "Library folder",
            "fields": [["Program folder", str(config.game_dir(ctx.program)), ""],
                       ["Exports", str(ctx.exports_dir()),
                        "everything exported from this disc"]],
            "note": ("The library files a disc under the PROGRAM it boots, not "
                     "the disc it shipped on, because the program is what its "
                     "bytes describe. " + shared),
        }

    # -- capability --------------------------------------------------------

    def _capability_section(self, ctx) -> dict:
        chips = [{"label": cls.name, "on": applies_to(cls, ctx),
                  "why": "" if applies_to(cls, ctx) else why_not(cls, ctx),
                  "icon": cls.key}
                 for cls in PROVIDER_CLASSES if cls is not DiscProvider]
        on = sum(c["on"] for c in chips)
        section = {
            "title": "What can be read",
            "aside": f"{on} of {len(chips)} tabs",
            "fields": [["Decoder plugin",
                        ctx.plugin.__name__ if ctx.has_plugin else "—",
                        "" if ctx.has_plugin else "none for this program"]],
            "chips": chips,
        }
        if not ctx.has_plugin:
            section["note"] = (
                "No per-program decoders exist for this program yet. Only the "
                "generic PlayStation ones (decoders.psx) apply, which is why "
                "the game-content tabs are off rather than empty.\n\n"
                "Adding them is decoder work, not viewer work: read the code "
                "path that loads the format, add the decoder under "
                f"backend/decoders/plugins/{mangle(ctx.program)}/formats/, "
                "register it in backend/decoders/inventory.py, and list this "
                "program in decoders.plugins.COMPAT.")
        return section


# ---------------------------------------------------------------------------
# Disc Files — the extracted filesystem of ANY disc
# ---------------------------------------------------------------------------

class DiscFilesProvider:
    """Every file the disc extraction wrote, with a probed type.

    The type is what each file's first bytes say it is, for any disc. On
    a disc of SSSC's each file also says what it is and the code that
    reads it (formats.disc_files, docs/spec/overview.md): MENU.BIN is the
    movie player's overlay, and its build stamp is shown beside the
    program's, as overlay_stamp_check (0x800232B0) compares them. A file
    is shown by its first bytes.
    """

    name = "Disc files"
    key = "disc-files"
    supports_zoom = False
    supports_grid = False
    supports_layers = False

    HEXDUMP_BYTES = 256

    #: A disc file is numbered by its place in the disc's list of files.
    homes = {"disc-file": (None,)}

    @staticmethod
    def holds(data, r, ctx) -> bool:
        files = ctx.files
        return data is not None and 0 <= r.id[0] < len(files) and files[r.id[0]] == data[0]

    def _kind(self, path: Path) -> str:
        try:
            with path.open("rb") as fh:
                head = fh.read(2048)
        except OSError:
            return "unreadable"
        if head[:8] == b"PS-X EXE":
            return "PS-X EXE"
        if head[:4] == b"\x10\x00\x00\x00":
            return "TIM image"
        if head[:4] == b"VABp":
            return "VAB sample bank"
        if head[:4] == b"pQES":
            return "SEQ sequence"
        try:
            from decoders.psx.formats.str_stream import (
                looks_like_str_sector, parse_sector_header,
            )
            if len(head) >= 32 and looks_like_str_sector(parse_sector_header(head)):
                return "STR stream"
        except ValueError:
            pass
        if path.suffix.upper() == ".XA":
            return "XA audio (interleaved)"
        if path.name == "SYSTEM.CNF":
            return "boot config"
        return "data"

    def get_items(self, cache, archive, ctx, selected):
        df, _names = _sssc_files(ctx)
        items = []
        for name in ctx.files:
            path = ctx.path(name)
            size = path.stat().st_size
            role = df.role(name) if df else None
            items.append((f"{name:<16} {size / 1024:>10,.0f}K  {self._kind(path)}",
                          (name, path, role)))
        return items or [("Nothing extracted in this dump", None)]

    def item_identity(self, label, data, ctx) -> Identity:
        name, path, _role = data
        return of_file(name, path)

    def get_layer_options(self):
        return []

    def on_select(self, item_data, cache, archive, ctx):
        if item_data is None:
            return SelectResult(info="Empty dump")
        name, path, role = item_data
        size = path.stat().st_size
        kind = self._kind(path)
        with path.open("rb") as fh:
            head = fh.read(self.HEXDUMP_BYTES)

        badges = [{"text": kind, "tone": "info", "hint": "what its first bytes say"},
                  {"text": size_text(size), "tone": "muted", "hint": f"{size:,} bytes"}]
        sections = [{"title": "File", "fields": [
            ["Size", f"{size:,} bytes", size_text(size)],
            ["Type", kind, "what its first bytes say"],
            ["Path", str(path), ""],
        ]}]
        df, names = _sssc_files(ctx)
        if df is not None:
            game = {"title": "In the game", "style": "prose", "fields": []}
            if role is None:
                game["note"] = "docs/spec/overview.md does not name this file."
            else:
                game["fields"].append(["Read by", role.reader or
                                       "no code names it", ""])
            if role is df.MOVIE_ROLE:
                event = df.movie_number(name)
                title = names.movie_file(name) if names is not None else None
                game["fields"].append(["Plays as", f"play event {event}",
                                       title or ""])
                badges.append({"text": f"play event {event}", "tone": "primary",
                               "hint": title or "MoviePlay's _B%03d.STR"})
            sections.append(game)
            if names is not None and name == df.overlay_file_name(names.binary):
                sections.append(_stamp_section(ctx, df, names))
        sections.append({"title": f"First {len(head)} bytes",
                         "aside": f"of {size:,}",
                         "hex": {"offset": 0, "bytes": head.hex()}})

        sheet = {"title": name, "titleMono": True,
                 "subtitle": role.what if role else "",
                 "badges": badges, "sections": sections}
        return SelectResult(sheet=sheet,
                            info=f"{name}\nsize: {size:,} bytes\ntype: {kind}",
                            ref=ref("disc-file", ctx.files.index(name)))


def size_text(n: int) -> str:
    """A file size for people: 1.2 MB, 340 KB, 96 B."""
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f} MB"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.0f} KB"
    return f"{n} B"


# ---------------------------------------------------------------------------
# Registry — which tabs serve which program
# ---------------------------------------------------------------------------
#
# A tab declares what it needs and the viewer decides; nothing here reaches
# for a decoder that cannot read the disc on screen. Two declarations:
#
#   programs   program serials this tab serves. Empty = every program,
#              which is the honest answer only for tabs built on
#              decoders.psx (PlayStation facts, no game knowledge).
#   requires   files that must exist in the dump for the tab to mean
#              anything.
#
# Providers are CLASSES here, not instances. They were instances, shared by
# every open view, and every one of them caches its parse lazily with no
# key — so opening a second disc showed the first disc's banks, sprites and
# strings. A fresh instance per opened disc makes that structurally
# impossible rather than a thing to remember.

def applies_to(provider, ctx) -> bool:
    """Can this tab say anything true about this disc?"""
    programs = getattr(provider, "programs", ())
    if programs and ctx.program not in programs:
        return False
    requires = getattr(provider, "requires", ())
    return not requires or ctx.has(*requires)


def why_not(provider, ctx) -> str:
    """Why a tab is off — shown on the Disc tab, never guessed at."""
    programs = getattr(provider, "programs", ())
    if programs and ctx.program not in programs:
        return f"serves {', '.join(programs)}"
    missing = [f for f in getattr(provider, "requires", ()) if not ctx.has(f)]
    if missing:
        return f"needs {', '.join(missing)}"
    return "unavailable"


PROVIDER_CLASSES: list = [
    DiscProvider,
    MapsProvider,
    MenusProvider,
    SpritesProvider,
    BattlesProvider,
    BromidesProvider,
    ScreensProvider,
    PortraitsProvider,
    CharactersProvider,
    ItemsProvider,
    MagicProvider,
    MonstersProvider,
    DataTablesProvider,
    StringsProvider,
    DialogueProvider,
    CdTracksProvider,
    MusicProvider,
    SoundBanksProvider,
    VoicesProvider,
    SoundEffectsProvider,
    MoviesProvider,
    StoryFlagsProvider,
    ResourcesProvider,
    DiscFilesProvider,
]


def providers_for(ctx) -> list:
    """Fresh provider instances for one opened disc, in tab order."""
    return [cls() for cls in PROVIDER_CLASSES if applies_to(cls, ctx)]

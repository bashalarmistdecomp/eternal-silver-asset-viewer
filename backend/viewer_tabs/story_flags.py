"""The Story flags tab (docs/taxonomy.md): what the game remembers you have
done, and what each flag changes.

One entry per story flag the code touches: every flag a link names
(viewer_tabs.links.flags), each listed once by its number. A flag's page is
its card laid out as a sheet (adventure.page), simple to complex: what it
marks in plain words, then how it is set, cleared and checked, then the
code's names and where it is stored, folded in Fan mode.

The list is grouped by where a flag is set, the surest way first: a thing
on a map (a chest, a tile change, an object, a place entered, a label run
by talking to someone) or a label of a script that runs on one place,
under that place; a label of a script that runs on several, under them all;
then the flags only movies and bromides set, those only items worn set,
those only the debug room sets (with other things checking them), those
nothing but the debug room touches, and last those nothing found sets.
A flag is set by the scenes whose run reaches its command, the scripts
handed over to included, a scene's pieces folded into it (the scene you
watch, ruled 2026-10-26: links.scenes). A scene is placed where what
starts it is: the object talked to or touched, the square stepped on or
examined; a label nothing found starts, on the places its script runs on.
Places come in the order of their first map.
"""

from __future__ import annotations

from viewer_tabs import links
from viewer_tabs.adventure import Listed, label
from viewer_tabs.field_view import DEBUG_ROOM
from viewer_tabs.links import flags
from viewer_tabs.refs import ref, written

#: The groups after the places, in order: (rank, heading, why)
MOVIES = (1, "Set by movies and bromides",
          "seeing a movie or a bromide sets them (MoviePlay (0x800232D4))")
WORN = (2, "Set by wearing items",
        "an item sets one while it is worn (ChrWornItemValuesAdd (0x800587D0))")
UNPLACED = (3, "Set by scripts no map runs",
            "a script sets them that no map loads and none hands a map over to")
DEBUG = (4, "The debug room", "only the debug room's scripts and maps set them; the game "
                              "checks them elsewhere too")
DEBUG_ONLY = (5, "Only the debug room", "nothing but the debug room's scripts and maps sets, "
                                        "clears or checks them")
UNSET = (6, "Set by nothing found", "nothing the viewer reads sets them: no script, chest, "
                                    "tile change, movie or item")


def _maps(model, t) -> list[int] | None:
    """The maps thing `t` works on, in order; None for one with no map (a
    movie, an item); [DEBUG_ROOM] for the debug room's. Each thing's are
    worked out once per disc (GameModel.kept): every flag it touches asks."""
    found = model.kept("_story_flag_maps", lambda twin: {})
    if t not in found:
        found[t] = _read_maps(model, t)
    return found[t]


def _read_maps(model, t) -> list[int] | None:
    from viewer_tabs.links import story, world
    w = world._world(model)
    f = flags._flags(model)
    kind = t.kind
    if kind == "label":
        sid = t.id[0]
        if sid in w.fm.debug_scripts:
            return [DEBUG_ROOM]
        from viewer_tabs.links import scenes
        runners = story._runs(model).get(tuple(t.id), [])
        if not runners:
            # a square of the map that starts it, else the scenes it is part of
            maps = scenes.scene_maps(model, t.id) or sorted(
                {m for at in scenes.part_of(model, *t.id) for m in scenes.scene_maps(model, at)})
            if maps:
                return maps
        homes = [w.home_map(o.id[0]) for o, _k in runners]
        homes = [m for m in homes if m is not None]
        return sorted(set(homes)) if homes else f.maps.get(sid, [])
    if kind == "tile-change" or kind == "map":
        return [t.id[0]]
    if kind == "place":
        return w.place_maps.get(t.id[0], [])
    if kind in world.OBJECT_KINDS:
        home = w.home_map(t.id[0])
        return [home] if home is not None else []
    return None


def where_set(model, r) -> tuple[tuple, str, str]:
    """(sort key, group, why) for flag `r` in the list."""
    from viewer_tabs.links import world
    w = world._world(model)
    index = links.LinkIndex.of(model)
    touches = [(e.back, e.frm) for e in index.into.get(r, [])] + \
              [(e.rel, e.to) for e in index.out.get(r, [])]
    reach = [(back, t, _maps(model, t)) for back, t in touches]
    if reach and all(maps == [DEBUG_ROOM] for _b, _t, maps in reach):
        return (DEBUG_ONLY[0],), DEBUG_ONLY[1], DEBUG_ONLY[2]
    setters = [(t, maps) for back, t, maps in reach if back == flags.SET_BY]
    placed = [(maps, list(dict.fromkeys(w.map_title(m) for m in maps)))
              for _t, maps in setters if maps and maps != [DEBUG_ROOM]]
    if placed:
        maps, places = min(placed, key=lambda p: (len(p[1]) > 1, p[0][0]))
        if len(places) == 1:
            return ((0, maps[0], 0), places[0],
                    f"set on {written(ref('map', maps[0]))}, the first such map in the "
                    f"maps' order")
        return ((0, maps[0], 1), w.places(maps),
                "set by a script that runs on all of these places")
    kinds = {t.kind for t, _maps in setters}
    for rank, group, why in (MOVIES, WORN):
        if kinds & ({"movie", "bromide"} if rank == MOVIES[0] else {"item"}):
            return (rank,), group, why
    if any(maps == [DEBUG_ROOM] for _t, maps in setters):
        return (DEBUG[0],), DEBUG[1], DEBUG[2]
    if setters:
        return (UNPLACED[0],), UNPLACED[1], UNPLACED[2]
    return (UNSET[0],), UNSET[1], UNSET[2]


def story_flags(model) -> list[tuple[str, Listed]]:
    """Every story flag the code touches, under where it is set, by number
    within."""
    keyed = []
    for r in flags.touched(model):
        key, group, why = where_set(model, r)
        keyed.append(((key, group, r.id), label(written(r), flags.summary(model, r)),
                      Listed(r, group, why)))
    return [(lab, it) for _k, lab, it in sorted(keyed, key=lambda k: k[0])]

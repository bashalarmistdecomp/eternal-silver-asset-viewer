"""The scenes a script's command is credited to, what a label is part of,
and how a list of scenes is laid out by place (docs/taxonomy.md, "How a
link works"; ruled 2026-10-26).

The ruling: "Credit every scene that ends up running the command,
including through shared pieces. That is what a player sees. Each scene
is listed once."

**The scene you watch.** A command is credited to every label whose run
can reach it: from the label's start, through its jumps and calls, every
way its tests go (event_script.labels_reaching, by walk_label), and on
into the label another script is run from when the run hands over to it
(command 0x42, ScriptCommandScriptChange (0x8005BFCC): the scene goes on
in that script). A shared label that sets a flag or plays a song is
credited, and so is every scene that calls it, jumps to it or hands over
to it. The songs, the sound effects and the story flags are credited
alike. A command no label reaches is credited to none. The debug room's
scripts hand over to every map's (event_script.map_scripts leaves them
out too); their hand-overs are not followed.

**What a label is part of.** A scene a player meets starts where the code
starts one: talking to an entity or touching a trigger runs the label its
definition's byte 0xB names (MapPartyTalkCheck (0x80067D1C),
MapObjectTouchRun (0x8007ACD8)) in the script running on the map: the one
its area record names or any one handed the map (event_script.map_scripts,
as links.flags reads it), so it can start that label of each; and so does
a square of the map's attribute plane, of the map's own script: kinds 4
and 5 when the party steps on it, kind 6 when it is examined
(MapAttributeRun (0x800590C0): g_MapPadPressedButtons & 0x40;
MapAttributeKind4Run (0x80059C48) to MapAttributeKind6Run (0x80059CA8)).
Another label is part of the scenes whose run reaches its start, and reads
as them ("part of talking to ‹who›").

**Scenes, not pieces.** What a song, a sound effect or a flag lists as
playing, setting, clearing or checking it are the scenes (`scenes_of`):
the labels something starts, each once however many of its pieces reach
the command, and the labels nothing found starts that are part of no
scene, which stand for themselves. A label that is part of a scene is
folded into it: the scene's run reaches all the piece's does, so the
scene is credited already. The pieces whose code holds the command
(`held_in`, event_script.command_labels) are listed apart, *Held in*,
with the extended info in Fan mode and open in Advanced (links.
advanced_groups); a piece's own card still links what its code does.

**Each scene once.** A script can run on several places; a scene of it is
listed once, under all of its places together ("Scenes at ‹A› and ‹B›"),
not once under each. When there are more than PLACES_NAMED places, the
heading names the first ones and says how many more, and the scene's note
names every one.

Each script's walks are made once per disc and kept (GameModel.kept).
"""

from __future__ import annotations

from viewer_tabs.refs import ref

#: Places a heading names before "and n more places".
PLACES_NAMED = 3
#: The group of the pieces whose code holds a command, on what it touches.
HELD_IN = "Held in"


class _Walks:
    """Every label's run, once per disc: the commands of its script it
    reaches, and the labels of other scripts it hands over to."""

    def __init__(self, model):
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        fm = model.field
        #: script -> label -> the offsets of the commands its run reaches
        self.reach: dict[int, dict[int, frozenset[int]]] = {}
        #: (script, label) -> the (script, label)s that hand over to it
        self.handed_from: dict[tuple[int, int], list[tuple[int, int]]] = {}
        #: (script, label) -> the (script, label)s whose run reaches its start
        self.reaching: dict[tuple[int, int], list[tuple[int, int]]] = {}
        #: script -> command offset -> the labels whose code holds it
        self.held: dict[int, dict[int, tuple[int, ...]]] = {}
        #: script -> command offset -> the labels whose run reaches it
        #: (`reach` turned round), made when the script is first asked of
        self.reached_by: dict[int, dict[int, list[int]]] = {}
        for sid in sorted(fm.script_resources):
            try:
                buf, cmds, table = fm.script(sid)
            except Exception:
                continue                # FieldMaps.errors says why
            mine = self.reach[sid] = {}
            self.held[sid] = es.command_labels(buf, cmds.values())
            for label in sorted(table):
                walk = es.walk_label(buf, cmds, label, sid, table)
                mine[label] = frozenset(walk.reached)
                if sid in fm.debug_scripts:
                    continue
                for to in dict.fromkeys(walk.handed_over):
                    self.handed_from.setdefault(tuple(to), []).append((sid, label))

    def credited(self, sid: int, offsets) -> dict[int, list[tuple[int, int]]]:
        """offset -> the (script, label)s credited with the command there:
        the labels of `sid` whose run reaches it, in order, then the labels
        that hand over to one of them, and so on, by script and label."""
        by = self.reached_by.get(sid)
        if by is None:
            by = {}
            for lab, got in self.reach.get(sid, {}).items():
                for at in got:
                    by.setdefault(at, []).append(lab)
            self.reached_by[sid] = by
        out: dict[int, list[tuple[int, int]]] = {}
        closed: dict[frozenset, list[tuple[int, int]]] = {}
        for at in dict.fromkeys(offsets):
            local = frozenset(by.get(at, ()))
            if not local:
                continue
            if local not in closed:
                closed[local] = self._handed(sid, local)
            out[at] = closed[local]
        return out

    def _handed(self, sid: int, local) -> list[tuple[int, int]]:
        found = [(sid, lab) for lab in sorted(local)]
        seen = set(found)
        todo = list(found)
        while todo:
            for by in self.handed_from.get(todo.pop(), ()):
                if by not in seen:
                    seen.add(by)
                    todo.append(by)
        return found + sorted(seen.difference(found))


def _walks(model) -> _Walks:
    return model.kept("_scene_walks", _Walks)


def credited(model, sid: int, offsets) -> dict[int, list[tuple[int, int]]]:
    """offset -> the (script, label)s credited with the command of script
    `sid` there: every label whose run reaches it, in its own script and
    through hand-overs; an offset no label reaches is left out."""
    return _walks(model).credited(sid, offsets)


def held_in(model, sid: int, offset: int) -> list[tuple[int, int]]:
    """The pieces whose code holds the command of script `sid` at `offset`
    (event_script.command_labels), as (script, label)s."""
    return [(sid, lab) for lab in _walks(model).held.get(sid, {}).get(offset, ())]


def scenes_of(model, labs) -> list[tuple[int, int]]:
    """Of the labels credited with a command (`credited`), the scenes a
    player sees, each once, in order: those something starts (`started`),
    and those nothing found starts that are part of no scene (`part_of`),
    which stand for themselves. A piece of a scene is left out: its scenes
    reach what it does, so they are among `labs` already."""
    starts = started(model)
    return [at for at in dict.fromkeys(labs) if at in starts or not part_of(model, *at)]


#: The attribute plane's kinds of square that run a label of the map's
#: script, and what doing so is (MapAttributeRun (0x800590C0)).
CELL_RUNS = {4: "stepping on", 5: "stepping on", 6: "examining"}


def started(model) -> dict[tuple[int, int], list[tuple[str, list[int]]]]:
    """(script, label) -> what starts it as a scene, in words, with the
    maps where: "talking to ‹who›" and the map the entity stands on;
    "touching ‹what›"; "stepping on a square of ‹map›", "examining a square
    of ‹map›"."""
    def build(model):
        from viewer_tabs import links
        from viewer_tabs.field_view import OBJECT_REF_KINDS
        from viewer_tabs.links import flags, world
        w = world._world(model)
        #: map -> the scripts that can run on it
        can: dict[int, set[int]] = {}
        for sid, maps in flags._flags(model).maps.items():
            for mid in maps:
                can.setdefault(mid, set()).add(sid)
        out: dict = {}
        for s, maps in sorted(w.set_maps.items()):
            for i, d in sorted(w.definitions(s).items()):
                kind = OBJECT_REF_KINDS.get(d.kind)
                if kind not in ("entity", "trigger") or not d.event:
                    continue
                verb = "talking to" if kind == "entity" else "touching"
                words = f"{verb} {links.title_of(model, ref(kind, s, i))}"
                for mid in maps:
                    for sid in sorted(can.get(mid, ())):
                        if d.event in w.script_labels(sid):
                            out.setdefault((sid, d.event), []).append((words, [mid]))
        for mid in sorted(w.fm.maps):
            sid = w.fm.maps[mid].area.script
            try:
                cells, labels = w.cells(mid), w.script_labels(sid)
            except Exception:
                continue                # the map or its script cannot be read
            for kind, label in sorted({k for k in cells if k[0] in CELL_RUNS}):
                if label in labels:
                    out.setdefault((sid, label), []).append(
                        (f"{CELL_RUNS[kind]} a square of {w.map_title(mid)}", [mid]))
        merged: dict = {}
        for at, got in out.items():
            by: dict[str, set[int]] = {}
            for words, maps in got:
                by.setdefault(words, set()).update(maps)
            merged[at] = [(words, sorted(maps)) for words, maps in by.items()]
        return merged
    return model.kept("_scene_starts", build)


def scene_words(model, at) -> str | None:
    """What starts scene `at` (script, label), in words, and how many more
    things do: "talking to ‹who› and 2 more"; None for a label nothing
    found starts."""
    got = started(model).get(tuple(at))
    if not got:
        return None
    more = len(got) - 1
    return got[0][0] + (f" and {more} more" if more > 0 else "")


def scene_maps(model, at) -> list[int]:
    """The maps where scene `at` is started."""
    return sorted({m for _words, maps in started(model).get(tuple(at), ()) for m in maps})


def part_of(model, sid: int, label: int) -> list[tuple[int, int]]:
    """The scenes a player meets (`started`) whose run reaches the start of
    label `label` of script `sid`, itself left out: what a label nothing
    starts itself is part of."""
    walks = _walks(model)
    got = walks.reaching.get((sid, label))
    if got is None:
        starts = model.field.script(sid)[2]
        at = starts.get(label)
        got = walks.credited(sid, [at]).get(at, []) if at is not None else []
        walks.reaching[(sid, label)] = got
    starts = started(model)
    return [s for s in got if s != (sid, label) and s in starts]


def part_words(model, sid: int, label: int) -> str | None:
    """"part of talking to ‹who›" (and how many more scenes) for a label
    nothing runs itself that a talked-to or touched scene reaches; None
    when none is found to."""
    parts = part_of(model, sid, label)
    if not parts:
        return None
    first = scene_words(model, parts[0])
    more = len(parts) - 1
    return f"part of {first}" + (f" and {more} more scene{'s' if more != 1 else ''}"
                                 if more else "")


def places_words(places: list[str]) -> tuple[str, str]:
    """(heading words, every one) for a scene's places: "A and B", or
    "A, B, C and 7 more places" with all ten in the second."""
    every = _and(places)
    if len(places) <= PLACES_NAMED:
        return every, every
    more = len(places) - PLACES_NAMED
    return f"{', '.join(places[:PLACES_NAMED])} and {more} more places", every


def _and(words: list[str]) -> str:
    if len(words) < 2:
        return "".join(words)
    return f"{', '.join(words[:-1])} and {words[-1]}"

"""The story flags: what the game remembers you have done, what sets,
clears and checks each flag, and what each changes (docs/taxonomy.md,
"story flag").

**One store, one number space.** Every flag the program touches is a bit
of the 0x800 bytes at g_StoryBits (0x800B8944), which GameStart
(0x80055B60) points at 0x801DC380: StoryBitSet (0x800576EC), StoryBitClear
(0x80057730) and StoryBitCheck (0x80057778) take a number n and work on
bit n & 7 of byte n >> 3, n cut to 16 bits. `story flag n` is that number,
whoever hands it over: a script's command (formats.event_script.flag_uses:
its words; 0x580 + a byte, an entity's; a map and a definition, another
object's; 0x480 + a byte, a tile change's; a map and a definition, a
chest's), a tile change (0x480 + its row's byte 4), an object
(MapObjectsInit (0x800655C8)), a chest (MapObjectInit (0x800656CC)), a
movie (MoviePlay (0x800232D4): its number + 0x154), an item worn
(ChrWornItemValuesAdd (0x800587D0): its row's byte 5 + 0x2BC), a party id
joining (0x2BC + the id) or a place entered (MapSet (0x80068780): its
number + 0x28A). A number from 0x4000 up falls past the 0x800 bytes.

Two ranges are not kept as the rest are: every change of map clears 0x3E8
to 0x47F (StoryBits3E8Clear (0x8005779C), from MapChange (0x8005922C)),
and command 0x5C clears them all (ScriptCommandStoryBitsItemsReset
(0x8005EF58)), after ending the game if flag 1 is set.

A flag's card groups what points at it as **Set by**, **Cleared by** and
**Checked by**: the scenes a player sees. The pieces whose code holds the
command are **Held in**, and a check's flag **Goes on at** the label the
check jumps to: the code's workings, shown with the extended info in Fan
mode and open in Advanced (links.advanced_groups). Read here, from the
scripts:

- a scene sets, clears or checks the flags of the commands its run
  reaches, through its jumps and calls and into the scripts it hands over
  to (links.scenes: the scene you watch them in, ruled 2026-10-26), each
  command by its handler; a label that is part of a scene is folded into
  it (links.scenes.scenes_of), and the piece holding the command links it
  from its own card;
- a label playing a movie or showing a bromide sets its flag (command
  0x2D, ScriptCommandMoviePlay (0x8005E2B4) -> MoviePlay);
- a label taking an object off the map sets its flag, one putting it on
  clears it (commands 0x25 and 0x41), where the maps its script runs on
  and the object sets they are entered with give one flag for it: the
  number depends on the map and on the object set's definition, which the
  script does not name.

The other domains give the rest: a tile change sets its flag as it starts
and is loaded changed while it is set, an object is left out while its
flag is set, a map monster sets its flag when it is beaten, a chest shows
open (and sets its flag when it is emptied) or stays shut until flag 0x267
is set, entering a place 0x51 to 0x64 sets its flag (world); a movie or a
bromide sets its flag (media); an item sets its flag while it is worn and
clears it when it is taken off (battle).

Not linked, as the bytes read do not give the number: a 0x23 that takes
its party id from a map object, 0x43's ids (it adds 0xF on a map of party
kind 0), a 0x25 or 0x41 whose maps and object sets give more than one flag
or none, an object another one walks into (MapObjectOverlappedRemove
(0x8007A458)). Not linked either: the flags the program itself sets and
checks by numbers written in its code (the battle's, the menus', the
theater's), which no thing here stands for.
"""

from __future__ import annotations

from viewer_tabs import links
from viewer_tabs.links import CardBody, Edge
from viewer_tabs.refs import ref, written

SET_BY, CLEARED_BY, CHECKED_BY = "Set by", "Cleared by", "Checked by"
GOES_ON_AT, REACHED_BY = "Goes on at", "Reached by checking"
HELD_IN = "Held in"             # links.scenes.HELD_IN
links.group_order("story-flag", SET_BY, CLEARED_BY, CHECKED_BY, HELD_IN, GOES_ON_AT)
links.advanced_groups("story-flag", HELD_IN, GOES_ON_AT)
#: what a label's card heads its links to the flags with, by what it does
SETS, CLEARS, CHECKS = "Sets story flags", "Clears story flags", "Checks story flags"

BIT_SET = "StoryBitSet (0x800576EC)"
BIT_CLEAR = "StoryBitClear (0x80057730)"
BIT_CHECK = "StoryBitCheck (0x80057778)"
STORY_BITS = "g_StoryBits (0x800B8944)"
#: GameStart (0x80055B60) stores this in g_StoryBits
STORY_BITS_AT = 0x801DC380
STORY_BYTES = 0x800
STORY_FLAGS = STORY_BYTES * 8
#: StoryBits3E8Clear (0x8005779C) zeroes bytes 0x7D to 0x8F on every change
#: of map (MapChange (0x8005922C)): these flags last while the party is on
#: the map
MAP_ONLY_FIRST, MAP_ONLY_LAST = 0x3E8, 0x47F
MAP_ONLY_CLEAR = "StoryBits3E8Clear (0x8005779C)"
MOVIE_PLAY = "ScriptCommandMoviePlay (0x8005E2B4)"
OBJECTS_REMOVE = "ScriptCommandMapObjectsRemove (0x8005D9D4)"
OBJECTS_ADD = "ScriptCommandMapObjectsAdd (0x8005D7E0)"
#: Things named in a sentence before "and n more".
NAMED = 3


def _more(words: list[str], named: int = NAMED) -> str:
    """"a, b and c", "a, b, c and 2 more"; "a, b; c" when a part has
    commas of its own."""
    words = list(dict.fromkeys(words))
    sep = "; " if any(", " in w for w in words) else ", "
    if len(words) <= named:
        return " and ".join([sep.join(words[:-1]), words[-1]]) if len(words) > 1 \
            else "".join(words)
    return f"{sep.join(words[:named])} and {len(words) - named} more"


def _flags_words(flags) -> str:
    """"story flag 12", "story flags 12 and 13"."""
    nums = [str(f) for f in flags]
    return f"story flag{'s' if len(nums) > 1 else ''} {_more(nums)}"


def condition(does: str, others) -> str:
    """When a check of a flag holds, said of that flag: "it is set", "it
    and story flag 12 are set", "it or story flag 12 is set", "it is
    clear"; `others` are the other flags of the check's list."""
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    if not others:
        return "it is clear" if does == es.NONE else "it is set"
    named = _flags_words(others)
    if does == es.ALL:
        return f"it and {named} are set"
    if does == es.NONE:
        return f"it and {named} are clear"
    return f"it or {named} is set" if len(others) == 1 else f"it or any of {named} is set"


# ---------------------------------------------------------------------------
# what the domain reads, once per disc
# ---------------------------------------------------------------------------

class _Flags:
    """The scripts' commands that touch the flags, the labels that hold
    them, and where each script runs."""

    def __init__(self, model):
        from decoders.plugins.SLUS_006_28.formats import event_script as es
        from viewer_tabs.links import scenes, world
        self.w = w = world._world(model)
        fm = w.fm
        #: script -> its labels (label -> offset)
        self.labels: dict[int, dict] = {}
        #: script -> [(scenes, event_script.FlagUse)], in the order of the
        #: code; a scene is a (script, label) credited with the command
        #: (links.scenes.credited), of this script or one handing over to it
        self.uses: dict[int, list] = {}
        #: script -> [(scenes, movie number, offset)] (command 0x2D)
        self.movies: dict[int, list] = {}
        #: script -> [(scenes, command, definitions, offset)] (commands 0x25, 0x41)
        self.objects: dict[int, list] = {}
        #: (script, label) of every piece holding a command 0x5C
        self.resets: list[tuple[int, int]] = []
        #: flag -> how the scripts write it: "command 0x0E: byte 0x21 + 0x580"
        self.forms: dict[int, list[str]] = {}
        switches = {}
        for sid in sorted(fm.script_resources):
            try:
                buf, commands, labels = fm.script(sid)
            except Exception:
                continue            # FieldMaps.errors says why
            cmds = sorted(commands.values(), key=lambda c: c.offset)
            switches[sid] = es.script_switches(buf, cmds)
            uses, movies = es.flag_uses(buf, cmds), es.movie_plays(buf, cmds)
            objects = es.objects_changed(buf, cmds)
            # the scenes credited with each: every label whose run reaches it
            at = [u.offset for u in uses] + [o for o, _n in movies] + [o for o, *_r in objects]
            held = scenes.credited(model, sid, at) if at else {}
            self.labels[sid] = labels
            self.uses[sid] = [(held[u.offset], u) for u in uses if u.offset in held]
            self.movies[sid] = [(held[o], n, o) for o, n in movies if o in held]
            self.objects[sid] = [(held[o], cid, defs, o) for o, cid, defs in objects
                                 if o in held]
            for labs, u in self.uses[sid]:
                if u.does == es.RESET:
                    self.resets += scenes.held_in(model, sid, u.offset)
                for n, w_ in zip(u.flags, u.written):
                    form = _form(u.id, w_)
                    if form not in self.forms.setdefault(n, []):
                        self.forms[n].append(form)
        # where a script runs: the maps whose record names it and those the
        # others hand over to it (event_script.map_scripts). The debug
        # room's scripts hand over to every map, so theirs are left out.
        entered = {mid: m.area.script for mid, m in fm.maps.items()}
        handed = es.map_scripts(entered, {s: v for s, v in switches.items()
                                          if s not in fm.debug_scripts})
        #: script -> the maps it can run on, in order
        self.maps: dict[int, list[int]] = {}
        for mid in sorted(handed):
            for sid in sorted(handed[mid]):
                self.maps.setdefault(sid, []).append(mid)

    def where(self, sid: int) -> str:
        """"on A, B and C": the places a script runs on, for a note."""
        if sid in self.w.fm.debug_scripts:
            return "in the debug room"
        maps = self.maps.get(sid, [])
        return f"on {self.w.places(maps)}" if maps else ""


def _form(cid: int, written_) -> str:
    """How command `cid` writes a flag: "command 0x0E: byte 0x21 + 0x580"."""
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    form = es.FLAG_COMMANDS[cid][1]
    if form == "words":
        how = f"0x{written_:04X}"
    elif form in ("580", "480"):
        how = f"byte 0x{written_:02X} + 0x{form}"
    elif form in ("pairs", "2620"):
        how = f"map 0x{written_[0]:02X}, definition 0x{written_[1]:02X}"
    else:
        how = f"party id 0x{written_:02X} + 0x2BC"
    return f"command 0x{cid:02X}: {how}"


def _flags(model) -> _Flags:
    return model.kept("_flags", _Flags)


# ---------------------------------------------------------------------------
# the edges
# ---------------------------------------------------------------------------

@links.edges(kept=True)
def flag_edges(model):
    """Each scene -> the story flags its run sets, clears and checks, the
    flag of each movie it plays and of each object it takes off or puts on
    the map; each piece holding such a command -> the flags it touches
    (Held in); each check's flag -> the label it goes on at."""
    from viewer_tabs.links import scenes
    f = _flags(model)
    for sid in sorted(f.uses):
        found = [(labs, u.offset, _use_links(model, sid, u, f.labels[sid]))
                 for labs, u in f.uses[sid]]
        found += [(labs, o, _movie_links(model, n)) for labs, n, o in f.movies[sid]]
        found += [(labs, o, _object_links(model, f, sid, cid, defs))
                  for labs, cid, defs, o in f.objects[sid]]
        for labs, offset, made in found:
            # each scene the player sees, said where its own script runs
            for at in scenes.scenes_of(model, labs):
                frm, where = ref("label", *at), f.where(at[0])
                for to, rel, back, note, _held, proof in made:
                    yield from _edges(frm, to, rel, back, note, proof, where)
            for at in scenes.held_in(model, sid, offset):
                for to, rel, _back, _note, held, proof in made:
                    yield Edge(ref("label", *at), to, rel, HELD_IN, held, proof)
        for _labs, u in f.uses[sid]:
            yield from _goes_on_at(sid, u, f.labels[sid])


def _edges(frm, to, rel: str, back: str, note: str, proof: str, where: str):
    """A scene's link to a flag: once with where its script runs, then with
    what this command does. A card lists a thing once with every note it is
    linked by (links.groups), so the place is said once however many of the
    scene's commands touch the flag."""
    if where:
        yield Edge(frm, to, rel, back, where, proof)
    if note or not where:
        yield Edge(frm, to, rel, back, note, proof)


def _use_links(model, sid: int, use, labels) -> list[tuple]:
    """(flag, rel, back, a scene's note, the piece's note, proof) for each
    flag a command `use` of script `sid` (whose `labels` its check goes on
    at) touches."""
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    handler = es.FLAG_COMMANDS[use.id][2]
    if use.does == es.RESET:
        note = "the game ends here when it is set; then every story flag is cleared"
        return [(ref("story-flag", es.END_FLAG), CHECKS, CHECKED_BY, note,
                 f"checks it: {note}", handler)]
    out = []
    for k, n in enumerate(use.flags):
        flag = ref("story-flag", n)
        if use.does in es.CHECKS:
            said_ = condition(use.does, [o for i, o in enumerate(use.flags) if i != k])
            # where the check jumps is the code's: the piece's note says it
            jump = f"if {said_}, goes on at {written(ref('label', sid, use.label))}"
            out.append((flag, CHECKS, CHECKED_BY, f"whether {said_}", f"checks it: {jump}",
                        handler))
            continue
        rel, back = (SETS, SET_BY) if use.does == es.SET else (CLEARS, CLEARED_BY)
        note = ""
        if use.id in (0x23, 0x24):
            who = _party_word(model, n - es.PARTY_BASE)
            note = f"{who} {'joins' if use.does == es.SET else 'leaves'} the party"
        verb = "sets it" if use.does == es.SET else "clears it"
        out.append((flag, rel, back, note, f"{verb}: {note}" if note else verb, handler))
    return out


def _goes_on_at(sid: int, use, labels):
    """A check's flags -> the label of script `sid` the check goes on at."""
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    if use.does not in es.CHECKS or use.label not in labels:
        return
    handler = es.FLAG_COMMANDS[use.id][2]
    to = ref("label", sid, use.label)
    for k, n in enumerate(use.flags):
        said_ = condition(use.does, [o for i, o in enumerate(use.flags) if i != k])
        yield Edge(ref("story-flag", n), to, GOES_ON_AT, REACHED_BY, f"if {said_}", handler)


def _party_word(model, k: int) -> str:
    """Party id k (the 0x2BC + k flag's): a character's name, else its id."""
    from viewer_tabs.links import battle
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    if k == es.PARTY_OTHER:
        return f"an id of {es.PARTY_OTHER_FROM} or more"
    return battle._character_word(model, k)


def _movie_links(model, n: int) -> list[tuple]:
    """The flag of movie or bromide event `n` a command 0x2D sets, as
    `_use_links` gives a flag."""
    from decoders.plugins.SLUS_006_28.records import events as ev
    shown = ev.event(n)
    if shown.kind == "bromide":
        what = links.title_of(model, ref("bromide", shown.bromide))
        verb = "shows"
    else:
        what = links.title_of(model, ref("movie", n))
        verb = "plays"
    note = f"{verb} {what}, which sets it"
    return [(ref("story-flag", n + ev.EVENT_FLAG_BASE), SETS, SET_BY, note, note,
             f"{MOVIE_PLAY}, MoviePlay (0x800232D4)")]


def object_flag(f: _Flags, sid: int, number: int):
    """The one flag definition `number`'s object has on every map script
    `sid` runs on, with every object set the map is entered with, and the
    objects that have it; None when the maps and sets give none or more
    than one (MapObjectsInit's number, field_objects.story_flag)."""
    from decoders.plugins.SLUS_006_28.formats import field_objects as fo
    from viewer_tabs.field_view import OBJECT_REF_KINDS
    w = f.w
    found: dict[int, list] = {}
    for mid in f.maps.get(sid, []):
        _chosen, by = w.fm.set_for(mid)
        for s in sorted(by):
            d = w.definitions(s).get(number) if s else None
            kind = OBJECT_REF_KINDS.get(d.kind) if d is not None else None
            n = fo.story_flag(d, mid) if kind else None
            if n is not None:
                found.setdefault(n, []).append(ref(kind, s, number))
    if len(found) != 1:
        return None
    n, objects = next(iter(found.items()))
    return n, list(dict.fromkeys(objects))


def _object_links(model, f: _Flags, sid: int, cid: int, defs) -> list[tuple]:
    """The flags of the objects a command of script `sid` takes off or puts
    on the map, by the maps `sid` runs on, as `_use_links` gives a flag."""
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    out = []
    for number in defs:
        got = object_flag(f, sid, number)
        if got is None:
            continue
        n, objects = got
        what = links.title_of(model, objects[0])
        if cid == es.OBJECTS_REMOVE:
            note = f"takes {what} off the map"
            out.append((ref("story-flag", n), SETS, SET_BY, note, note, OBJECTS_REMOVE))
        else:
            note = f"puts {what} on the map"
            out.append((ref("story-flag", n), CLEARS, CLEARED_BY, note, note, OBJECTS_ADD))
    return out


# ---------------------------------------------------------------------------
# what a flag does, in plain words
# ---------------------------------------------------------------------------

#: How sure a way of setting or clearing a flag says where: a thing on a
#: map, then a label of a script that runs on one place, then one that
#: runs on several, then the debug room's.
THING, ONE_PLACE, PLACES, DEBUG = range(4)


def _label_words(model, r) -> tuple[int, str]:
    """How sure, and in words, where label `r` runs: "talking to ‹place› ·
    entity 3", "a script on ‹places›", "the debug room's scripts". Each
    label's are worked out once per disc (GameModel.kept): every flag its
    run touches asks."""
    said_ = model.kept("_label_words", lambda twin: {})
    got = said_.get(r)
    if got is None:
        got = said_[r] = _read_label_words(model, r)
    return got


def _read_label_words(model, r) -> tuple[int, str]:
    from viewer_tabs.links import scenes, story
    f = _flags(model)
    sid = r.id[0]
    if sid in f.w.fm.debug_scripts:
        return DEBUG, "the debug room's scripts"
    runners = story._runs(model).get(tuple(r.id), [])
    if runners:
        obj, kind = runners[0]
        verb = "talking to" if kind == "entity" else "touching"
        return THING, f"{verb} {links.title_of(model, obj)}"
    # a scene something else starts (a square of the map, talking in a
    # script handed the map)
    words = scenes.scene_words(model, r.id)
    if words:
        return THING, words
    maps = f.maps.get(sid, [])
    places = {f.w.map_title(m) for m in maps}
    return (ONE_PLACE if len(places) == 1 else PLACES,
            f"a script on {f.w.places(maps)}" if maps else "a script")


def said(model, r) -> dict:
    """What sets, clears and changes with flag `r`, from the links into it:
    {"set": [(how sure, words)], "cleared": [...], "changes": [words],
    "checks": the scenes that check it, "checked": their words}."""
    from viewer_tabs.links import world
    index = links.LinkIndex.of(model)
    out: dict = {"set": [], "cleared": [], "changes": [], "checks": [], "checked": []}
    for e in index.into.get(r, []):
        t, kind = e.frm, e.frm.kind
        if kind == "label":
            sure, words = _label_words(model, t)
            if e.back == CHECKED_BY:
                out["checks"].append(t)
                out["checked"].append(words)
            elif e.back in (SET_BY, CLEARED_BY):
                out["set" if e.back == SET_BY else "cleared"].append((sure, f"by {words}"))
            continue
        title = links.title_of(model, t)
        if e.back == SET_BY:
            out["set"].append((THING, {
                "chest": f"when {title} is opened", "tile-change": f"when {title} starts",
                "place": f"on entering {title}", "movie": f"when {title} is seen",
                "bromide": f"when {title} is shown", "item": f"while {title} is worn",
                "map-monster": f"when {title} is beaten",
            }.get(kind, f"by {title}")))
        elif e.back == CLEARED_BY:
            out["cleared"].append((THING, f"when {title} is taken off" if kind == "item"
                                   else f"by {title}"))
        elif e.back == CHECKED_BY:
            if kind == "tile-change":
                out["changes"].append(f"{title} loads changed")
            elif kind == "map":
                out["changes"].append(f"{title} plays another song")
            elif e.proof == world.OBJECTS_INIT:
                out["changes"].append(f"{title} is gone")
            elif e.proof == world.OBJECT_INIT:
                out["changes"].append(f"{title} shows open")
            elif e.proof == world.KIND7_RUN:
                out["changes"].append(f"{title} can be opened")
            else:
                out["changes"].append(title)
    for k in ("set", "cleared"):
        out[k] = sorted(dict.fromkeys(out[k]), key=lambda w: w[0])
    for k in ("changes", "checks", "checked"):
        out[k] = list(dict.fromkeys(out[k]))
    return out


def _first(words: list[str]) -> str:
    """"a", "a (and 2 more)"."""
    return words[0] + (f" (and {len(words) - 1} more)" if len(words) > 1 else "")


def summary(model, r) -> str:
    """What flag `r` marks, in a line: how it is set, the surest way first,
    then what it changes ("set when ‹chest› is opened; ‹chest› shows
    open")."""
    s = said(model, r)
    out = []
    if s["set"]:
        out.append("set " + _first([w for _sure, w in s["set"]]))
    elif s["cleared"] or s["changes"] or s["checks"]:
        out.append("nothing found sets it")
    if s["changes"]:
        out.append(_first(s["changes"]))
    elif s["checks"]:
        n = len(s["checks"])
        out.append(f"checked by {n} scene{'s' if n != 1 else ''}")
    return "; ".join(out)


# ---------------------------------------------------------------------------
# the card
# ---------------------------------------------------------------------------

@links.card("story-flag")
def story_flag_card(model, r) -> CardBody:
    n = r.id[0]
    if not 0 <= n <= 0xFFFF:
        raise LookupError(f"story flag {n}: the code takes a flag's low 16 bits")
    s = said(model, r)
    facts = []
    if s["set"]:
        facts.append(("Set", _more([w for _sure, w in s["set"]])))
    if s["cleared"]:
        facts.append(("Cleared", _more([w for _sure, w in s["cleared"]])))
    if s["changes"]:
        facts.append(("Changes", _more(s["changes"])))
    if s["checks"]:
        k = len(s["checks"])
        facts.append(("Checked by scripts", f"{k} scene{'s' if k != 1 else ''}, "
                                            f"{_more(s['checked'])}"))
    if MAP_ONLY_FIRST <= n <= MAP_ONLY_LAST:
        facts.append(("Kept", "while the party stays on the map: every change of map "
                              "clears it"))
    if n >= STORY_FLAGS:
        facts.append(("Kept", f"past the {STORY_FLAGS} story flags the game keeps: the code "
                              f"reads other memory for it"))
    note = "" if facts else "Nothing the viewer reads sets, clears or checks it."
    f = _flags(model)
    extended = [("Where", f"bit {n & 7} of byte 0x{n >> 3:X} of the 0x{STORY_BYTES:X} bytes "
                          f"at {STORY_BITS}: 0x{STORY_BITS_AT + (n >> 3):08X}"
                 if n < STORY_FLAGS else
                 f"bit {n & 7} of byte 0x{n >> 3:X} from {STORY_BITS}, past its "
                 f"0x{STORY_BYTES:X} bytes")]
    if f.forms.get(n):
        extended.append(("As the scripts write it", "; ".join(f.forms[n])))
    if MAP_ONLY_FIRST <= n <= MAP_ONLY_LAST:
        extended.append(("Cleared on a change of map", f"{MAP_ONLY_CLEAR} zeroes bytes 0x7D "
                                                       f"to 0x8F, from MapChange (0x8005922C)"))
    if f.resets:
        extended.append(("Cleared with every other", _more([written(ref("label", *at))
                                                            for at in dict.fromkeys(f.resets)])
                         + " (command 0x5C, ScriptCommandStoryBitsItemsReset (0x8005EF58))"))
    return CardBody(title=written(r), subtitle=summary(model, r) or "something the game "
                                                                     "remembers",
                    facts=facts, note=note, extended=extended,
                    proven=[BIT_SET, BIT_CLEAR, BIT_CHECK])


def touched(model) -> list:
    """Every story flag the links name, by number."""
    index = links.LinkIndex.of(model)
    found = {r for r in list(index.into) + list(index.out) if r.kind == "story-flag"}
    return sorted(found, key=lambda r: r.id)


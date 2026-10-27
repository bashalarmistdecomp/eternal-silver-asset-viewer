"""The sprites: who wears each look, where it stands, and the battle's
sprite blocks (viewer_tabs.looks).

What the code makes of each (docs/taxonomy.md, "The links"):

- an object set loads its sprite data list (MapObjectsDataLoad
  (0x80065418)), and each of its definitions wears one of them, a twin
  beside it for a number below 0xF (MapObjectInit (0x800656CC));
- the party wears its field sheets (MapPartySpriteDataLoad (0x80063D48),
  MapPartyRecordInit (0x800649DC));
- an entity is taken to be the speaker of a portrait no character is by
  the who-rule (looks.talker): an inference from the portrait that opens
  what they say, not a link the code makes, and its card says so;
- a look stands on the maps its object sets are entered on;
- a monster set's blocks are its monsters' battle sprites (BtlDataLoad
  (0x80018694), BtlEnemyLoad (0x8002B3AC)).

Every link points at a look's reference, its first copy; a card of any
copy is its look's card.
"""

from __future__ import annotations

from collections import Counter

from viewer_tabs import links, looks
from viewer_tabs.links import CardBody, Edge
from viewer_tabs.refs import number_hex, ref, written

MAP_CHANGE = "MapChange (0x8005922C)"
OBJECTS_INIT = "MapObjectsInit (0x800655C8)"
BTL_DATA_LOAD = "BtlDataLoad (0x80018694)"
BTL_ENEMY_LOAD = "BtlEnemyLoad (0x8002B3AC)"
#: What each heading says of a look, as its card's subtitle.
SUBTITLES = {looks.PARTY: "in the party", looks.STORY: "someone the story gives a portrait",
             looks.PEOPLE: "someone the party can talk to",
             looks.MONSTERS: "a monster walking the maps", looks.THINGS: "a thing on the maps"}


def _found(model) -> looks.Looks:
    return looks.of(model)


@links.unread
def sprites_unread(model) -> list[str]:
    """The object sets and the party's sheets whose sprites could not be read."""
    return _found(model).errors


# ---------------------------------------------------------------------------
# the edges
# ---------------------------------------------------------------------------

@links.edges(kept=True)
def sprite_edges(model):
    """Each object set's sprites, each object's and each party member's,
    each portrait's speaker taken from what they say, and the maps each look
    stands on; each monster set's battle sprites and their monsters."""
    found = _found(model)
    for look in found.looks:
        to = look.ref
        for c in look.copies:
            note = "" if c.ref == to else f"its copy {written(c.ref)}"
            if c.object_set != looks.PARTY_SET:
                yield Edge(ref("object-set", c.object_set), to, "Sprites", "Object sets", note,
                           looks.OBJECTS_DATA_LOAD)
            for w in c.wearers:
                yield Edge(w.ref, to, "Sprite", "Worn by", "as its twin" if w.twin else "",
                           looks.OBJECT_INIT)
        for m, which in look.party:
            if 1 <= m <= looks.PARTY_LAST:
                yield Edge(ref("character", m), to, "Sprites", "Who",
                           looks.SHEET_TITLES[which], looks.PARTY_LOAD)
        if look.talk is not None:
            yield Edge(look.talk.speaker, to, "Sprites", "Who",
                       "taken to be its speaker: it opens most of what they say",
                       looks.TALK_CHECK)
        for mid in look.maps:
            yield Edge(to, ref("map", mid), "Stands on", "Sprites", "", MAP_CHANGE)
    yield from _battle_sprite_edges(model)


def _battle_sprite_edges(model):
    from decoders.plugins.SLUS_006_28.records import encounters as en
    img = model.need_names().binary.code
    for s in range(en.SET_FIRST, en.SET_LAST + 1):
        if not en.set_resource(img, s):
            continue
        for j, t in enumerate(en.type_list(img, s)):
            it = ref("battle-sprite", s, j)
            yield Edge(ref("monster-set", s), it, "Battle sprites", "Monster set", "",
                       BTL_DATA_LOAD)
            yield Edge(it, ref("monster", t), "Monster", "Battle sprites",
                       "the fallback block: the set's fourth monster and any stranger"
                       if j == en.FALLBACK_TYPE else "", BTL_ENEMY_LOAD)


# ---------------------------------------------------------------------------
# titles
# ---------------------------------------------------------------------------

@links.title("sprite")
def sprite_title(model, r) -> str | None:
    look = _found(model).look(r)
    return look.title if look else None


@links.title("battle-sprite")
def battle_sprite_title(model, r) -> str | None:
    from decoders.plugins.SLUS_006_28.records import encounters as en
    s, j = r.id
    types = en.type_list(model.need_names().binary.code, s)
    if j >= len(types):
        return None
    name = model.need_names().enemy(types[j])
    return f"{name} in battle" if name else None


# ---------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------

@links.card("sprite")
def sprite_card(model, r) -> CardBody:
    found = _found(model)
    look = found.look(r)
    if look is None:
        s, n = r.id
        if s == looks.PARTY_SET:
            raise LookupError(f"the party has no field sheet {n} (resource 0x1E8)")
        raise LookupError(f"object set {s} loads no sprite data {n}")
    copy = found.copy(r)
    w = found.w
    facts = [("Who", found.who_words(look))]
    own = Counter(x.kind for x in look.wearers if not x.twin)
    worn = [f"{n} {looks.KINDS_WORDS[k][n != 1]}" for k, n in own.items()]
    twins = sum(1 for x in look.wearers if x.twin)
    if twins:
        worn.append(f"{twins} as {'their twin' if twins != 1 else 'its twin'}")
    if any(o.what == "actor" for c in look.copies for o in c.others):
        worn.append("actors in scenes")
    if look.party or any(o.what == "party" for c in look.copies for o in c.others):
        worn.append("the party")
    if worn and ", ".join(worn) != facts[0][1]:
        facts.append(("Worn by", ", ".join(worn)))
    if look.maps:
        facts.append(("Stands on", w.places(look.maps)))
    if len(look.copies) > 1:
        facts.append(("Copies", found.copies_words(look)))
    if copy is not None and copy.ref != look.ref:
        facts.append(("A copy of", written(look.ref)))
    note = found.rule_words(look).split(". ")[0] + "." if look.talk is not None else ""
    extended = []
    if look.talk is not None:
        extended.append(("The who-rule", found.rule_words(look)))
    extended.append(("Copies", ", ".join(f"{written(c.ref)} ({number_hex(c.ref)})"
                                         for c in look.copies[:12])
                     + (f" and {len(look.copies) - 12} more" if len(look.copies) > 12 else "")))
    c = copy or look.first
    if c.object_set == looks.PARTY_SET:
        extended.append(("Sprite data", f"the party's sheet {c.number:#04x}: resource 0x1E8 "
                                        f"({looks.PARTY_LOAD}); the reference names object "
                                        f"set 0, which loads nothing"))
    elif c.number == looks.CHEST_NUMBER:
        extended.append(("Sprite data", "0: g_SpriteData1 (0x800DDFB0), resource 2's chest, "
                                        f"whatever the set ({looks.OBJECTS_DATA_LOAD})"))
    else:
        extended.append(("Sprite data", f"g_MapSpriteDataEntries (0x800B8C68)[{c.number:#x}], "
                                        f"from object set {c.object_set:#04x}'s sprite data "
                                        f"list ({looks.OBJECTS_DATA_LOAD})"))
    if c.row is not None:
        extended.append(("Palette", f"row {c.row} ({looks.RECORD_INIT})"))
    extended.append(("A look", "copies are one look when every pose is drawn from the same "
                               "pieces, the same texels and the same colours, wherever a "
                               "copy keeps its texels"))
    proven = [looks.OBJECTS_DATA_LOAD, looks.OBJECT_INIT, looks.RECORD_INIT]
    if look.party:
        proven += [looks.PARTY_LOAD, looks.PARTY_RECORD_INIT]
    if look.talk is not None:
        proven += [looks.TALK_CHECK, looks.LABEL_RUN, looks.MESSAGE_FACE_SET,
                   looks.FACE_CELL_SET]
    picture = None
    try:
        picture = found.picture(look.first)
    except Exception as ex:
        extended.append(("Picture", f"could not be drawn: {type(ex).__name__}: {ex}"))
    subtitle = SUBTITLES[look.group]
    if look.talk is not None:
        subtitle += ", taken from what they say"
    return CardBody(title=look.title, subtitle=subtitle, picture=picture, facts=facts,
                    note=note, extended=extended, proven=proven)


@links.card("battle-sprite")
def battle_sprite_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
    from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
    from decoders.plugins.SLUS_006_28.records import encounters as en
    names = model.need_names()
    img = names.binary.code
    s, j = r.id
    if not en.SET_FIRST <= s <= en.SET_LAST or not en.set_resource(img, s):
        raise LookupError(f"monster set {s} loads nothing (g_BtlDataResources names none)")
    types = en.type_list(img, s)
    if j >= len(types):
        raise LookupError(f"monster set {s} has {len(types)} blocks")
    t = types[j]
    monster = names.enemy(t) or f"monster {t}"
    facts = [("Monster", monster), ("Monster set", written(ref("monster-set", s)))]
    if j == en.FALLBACK_TYPE:
        facts.append(("Drawn for", "the set's fourth monster, and any monster the set does "
                                   "not list first"))
    res = en.set_resource(img, s)
    picture = None
    extended = [("Block", f"block {j} of monster set {s}: resource {res} ({res:#x}), "
                          f"{BTL_DATA_LOAD}"),
                ("Palette", f"CLUT B, row {bg.CLUT_ROW_ENEMY}")]
    try:
        bundle = bg.parse_set_bundle(names.read_resource(res), len(types))
        blk = bundle.actor(j)
        poses = {p.index: p for p in sp.list_poses(blk)} if blk is not None else {}
        anims = blk.animations() if blk is not None else []
        first = anims[0].steps[0][0] if anims and anims[0].steps else min(poses, default=None)
        pose = poses.get(first)
        extent = sp.pose_extent(blk, pose) if pose is not None else None
        if extent is not None:
            x0, y0, x1, y1 = extent
            pages = {p.index: bg.render_page(p, bundle.clut_b) for p in bundle.pages}
            picture = sp.compose_pose(blk, pages, pose, origin=(-x0, -y0),
                                      size=(x1 - x0, y1 - y0))
    except Exception as ex:
        extended.append(("Picture", f"could not be drawn: {type(ex).__name__}: {ex}"))
    return CardBody(title=battle_sprite_title(model, r) or written(r),
                    subtitle="a monster's sprite in battle", picture=picture, facts=facts,
                    extended=extended, proven=[BTL_DATA_LOAD, BTL_ENEMY_LOAD])

"""The fans' tabs of what the party finds, learns and fights
(docs/taxonomy.md): **Items** (every item, what can be worn, every shop,
every chest), **Magic** (every spell, by who learns it) and **Monsters**
(every monster and every monster attack).

The lists and pages are read here; the providers in tab_providers hand
them to the app. A row's page is laid out as its card is, from the same
reading (links.card_body), simple to complex: its picture, its facts in
plain words, what the tab adds (a shop's stock, where a monster is met),
its links grouped by kind, then the extended info, folded in Fan mode.

How the lists are grouped, and why:

- Items: in the game's order, the item table's (g_BtlItemTable).
- Equipment: by the place it is worn in, the item row's kind (below 5,
  worn place kind + 1: records.items). The menus' names for the places
  are not proven, so they are numbered.
- Shops: by the place whose map's script opens it (command 0x2E,
  ScriptCommandShopRun (0x8005E384)); shops no map opens come last.
- Treasure: by the place of the map each chest's object set is shown on;
  the debug room's last. A chest that runs a scene when examined (byte
  0xB 0xF0 and up: MapObjectKind7Run (0x80067F84)) holds no treasure and
  is left out; the Maps tab shows it.
- Magic: by who learns each spell (its row's character, ChrLevelUp
  (0x80028554)), in the table's order within.
- Monsters and Attacks: in the game's order, their tables'.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from viewer_tabs import links
from viewer_tabs.field_view import DEBUG_ROOM, OBJECT_REF_KINDS
from viewer_tabs.links import battle
from viewer_tabs.refs import Ref, ref, written, written_hex

class Listed(NamedTuple):
    """What a row of these tabs carries: the thing, and the group it is
    listed under (with a line on why) where its list is grouped."""
    ref: Ref
    group: str = ""
    note: str = ""


#: The worn places by item kind (records.items: below 5, worn place kind +
#: 1; kind 4 has places 5 and 6).
WORN_IN = {0: "Worn in place 1", 1: "Worn in place 2", 2: "Worn in place 3",
           3: "Worn in place 4", 4: "Worn in place 5 or 6"}
WORN_NOTE = ("the item row's kind: the character record's worn item +0x1E + kind "
             "(ChrWornItemChangeMake (0x800581B8))")
#: A row's page heads its links with this, its extended info with that.
LINKS = "Links"
EXTENDED = "Extended info"


def label(title: str, *rest: str) -> str:
    """A list row's label: the title, then what is said under it, two
    spaces apart (viewer_server.present._generic)."""
    return "  ".join([title.replace("  ", " "), *(r for r in rest if r)])


def _place_order(model) -> dict[str, int]:
    """Each place's first map: a list grouped by place keeps one place's
    rows together, the places in their maps' order."""
    from viewer_tabs.links import world
    w = world._world(model)
    out: dict[str, int] = {}
    for m in sorted(model.field.maps):
        out.setdefault(w.map_title(m), m)
    return out


def same_reading(ctx) -> bytes:
    """What every row of these tabs is read from: the program and
    LUNADATA.FIL (GameModel.twin), by their digests."""
    from viewer_tabs.identity import file_digest
    return (f"{file_digest(Path(ctx.exe_path))} "
            f"{file_digest(Path(ctx.path('LUNADATA.FIL')))}").encode()


# ---------------------------------------------------------------------------
# the lists
# ---------------------------------------------------------------------------

def _what(v: dict) -> str:
    kind = v["kind"]
    if kind in WORN_IN:
        return WORN_IN[kind].lower()
    return "carried, never given up" if kind == 6 else "carried"


def items(model) -> list[tuple[str, Listed]]:
    """Every item, in the item table's order."""
    t = battle._tables(model)
    out = []
    for n, rec in sorted(t.items.items()):
        if not any(rec.raw):
            continue
        r = ref("item", n)
        out.append((label(links.title_of(model, r), written(r), _what(rec.values)), Listed(r)))
    return out


def equipment(model) -> list[tuple[str, Listed]]:
    """What can be worn, by the place it is worn in, then in the item
    table's order."""
    t = battle._tables(model)
    out = []
    for kind, group in WORN_IN.items():
        for n, rec in sorted(t.items.items()):
            if not any(rec.raw) or rec.values["kind"] != kind:
                continue
            r = ref("item", n)
            out.append((label(links.title_of(model, r), written(r), battle.raises(model, rec)),
                        Listed(r, group, WORN_NOTE)))
    return out


def _shop_numbers(model) -> list[int]:
    """The shops listed: every row of g_ShopStockRows where it is located,
    else every shop a script opens."""
    t = battle._tables(model)
    if t.shops is not None:
        return sorted(t.shops)
    return sorted(battle.shop_runs(model))


def shops(model) -> list[tuple[str, Listed]]:
    """Every shop, under the first place whose map's script opens it, the
    places in their maps' order; then those only the debug room opens,
    those only scripts no map loads as its own open (another script hands
    over to them), those no script opens, and those that never open."""
    from decoders.plugins.SLUS_006_28.records import shops as sh
    t = battle._tables(model)
    fm = model.field
    order = _place_order(model)
    keyed = []
    for n in _shop_numbers(model):
        places, debug = battle.shop_places(model, n)
        maps = sorted({m for sid, _o in battle.shop_runs(model).get(n, [])
                       if sid not in fm.debug_scripts
                       for m in fm.script_maps.get(sid, ()) if m != DEBUG_ROOM})
        if places:
            key, group, note = ((0, order.get(places[0], maps[0])), places[0],
                                "its map's script opens it (command 0x2E)")
        elif debug:
            key, group, note = (1, 0), "The debug room", "only the debug room's scripts open it"
        elif n in battle.shop_runs(model):
            key, group, note = ((2, 0), "Opened by other scripts",
                                "scripts no map loads as its own open it: another script "
                                "hands over to them")
        elif n in sh.CLOSED:
            key, group, note = (4, 0), "Never opens", f"ShopRun (0x80050694) opens nothing for {n}"
        else:
            key, group, note = (3, 0), "Opened by no script", "no script's command 0x2E names it"
        stock = t.shops[n].items if t.shops is not None else None
        sub = (f"{len(stock)} items: " + ", ".join(battle._item_word(model, i) for i in stock)
               if stock else "sells nothing" if stock is not None else "")
        keyed.append((key, n, label(f"shop {n}", sub), Listed(ref("shop", n), group, note)))
    return [(lab, it) for _k, _n, lab, it in sorted(keyed, key=lambda k: (k[0], k[1]))]


def _chest_words(model, w, got) -> str:
    """A chest's contents, short: the item, the money, nothing."""
    if got is None:
        return "an open chest"
    if got.what == "empty":
        return "nothing"
    if got.what == "item":
        return links.title_of(model, ref("item", got.number))
    amounts = w.amounts()
    return "money" if isinstance(amounts, str) else f"{amounts[got.number]} money"


def treasure(model) -> list[tuple[str, Listed]]:
    """Every chest (object kind 7) but those that run a scene, under the
    place of the map its object set is shown on, in the maps' order; the
    debug room's last."""
    from decoders.plugins.SLUS_006_28.formats import field_objects as fo
    from viewer_tabs.links import world
    w = world._world(model)
    order = _place_order(model)
    keyed = []
    for s in sorted(w.set_maps):
        home = w.home_map(s)
        if home is None:
            continue
        for i, d in sorted(w.definitions(s).items()):
            if OBJECT_REF_KINDS.get(d.kind) != "chest":
                continue
            got = fo.chest_contents(d)
            if got is not None and got.what == "label":
                continue
            r = ref("chest", s, i)
            debug = home == DEBUG_ROOM
            place = w.map_title(home)
            group = f"{place} (the debug room)" if debug else place
            note = (f"{written(ref('map', home))}, the debug room's map" if debug
                    else f"the map its object set is shown on, {written(ref('map', home))}")
            keyed.append(((debug, order.get(place, home), home, s, i),
                          label(_chest_words(model, w, got), written(r)),
                          Listed(r, group, note)))
    return [(lab, it) for _k, lab, it in sorted(keyed, key=lambda k: k[0])]


def magic(model) -> list[tuple[str, Listed]]:
    """Every spell, under who learns it, in the spell table's order; spells
    no one learns by level last."""
    t = battle._tables(model)
    keyed = []
    for n, rec in sorted(t.spells.items()):
        v = rec.values
        c = v["chr_id"]
        r = ref("spell", n)
        if c:
            alias = battle.SPELL_ALIAS.get(c)
            name = battle._character_word(model, c)
            group = f"{name} (characters {c} and {alias})" if alias else name
            note = (f"character {c}'s spells; character {alias} learns them too "
                    f"(ChrLevelUp (0x80028554))" if alias
                    else f"character {c}'s spells (ChrLevelUp (0x80028554))")
            when = "from the start" if v["level"] <= 1 else f"level {v['level']}"
        else:
            group, note, when = ("Learned by no one by level",
                                 "its row names no character (ChrLevelUp (0x80028554))", "")
        keyed.append(((not c, c, n), label(links.title_of(model, r), written(r), when,
                                           f"{v['cost']} MP"),
                      Listed(r, group, note)))
    return [(lab, it) for _k, lab, it in sorted(keyed, key=lambda k: k[0])]


def monsters(model) -> list[tuple[str, Listed]]:
    """Every monster, in the monster table's order."""
    t = battle._tables(model)
    out = []
    for n, rec in sorted(t.monsters.items()):
        if rec.is_empty:
            continue
        r = ref("monster", n)
        out.append((label(links.title_of(model, r), written(r),
                          f"level {rec.values['level']}"), Listed(r)))
    return out


def attacks(model) -> list[tuple[str, Listed]]:
    """Every monster attack, in the attack table's order, with the monsters
    that use it."""
    t = battle._tables(model)
    users: dict[int, list[int]] = {}
    for m, rec in sorted(t.monsters.items()):
        if rec.is_empty:
            continue
        for a in (rec.values["attack_number"], rec.values["kind7_number"]):
            if a:
                users.setdefault(a, []).append(m)
    out = []
    for n, rec in sorted(t.attacks.items()):
        if rec.is_empty:
            continue
        r = ref("monster-attack", n)
        who = list(dict.fromkeys(users.get(n, [])))
        used = (f"used by {battle._summary(model, who)}" if who else "used by no monster's row")
        out.append((label(links.title_of(model, r), written(r), used), Listed(r)))
    return out


# ---------------------------------------------------------------------------
# the pages
# ---------------------------------------------------------------------------

def page(model, r: Ref, extra: list[dict] = (), shown: tuple[str, ...] = ()) -> dict:
    """A row's page: its card's body as a sheet, `extra` sections after its
    facts, its links, then the extended info (folded in Fan mode). The
    facts and link groups titled as in `shown` are left out: an extra
    section says them already."""
    body, error = links.card_body(model, r)
    sections: list[dict] = []
    if error:
        sections.append({"title": "Not read", "verdict": {"text": error, "tone": "warn"}})
    if body.facts or body.note:
        sections.append({"title": "About", "style": "prose", "note": body.note,
                         "fields": [[k, v] for k, v in body.facts if k not in shown]})
    sections += [s for s in extra if s]
    index = links.LinkIndex.of(model)
    groups = [g for g in links.groups(model, index, r) if g["title"] not in shown]
    if groups:
        sections.append({"title": LINKS, "links": groups})
    fields = [[k, v] for k, v in links.extended_of(r, body, index)]
    if body.proven:
        fields.append(["Proven by", "; ".join(body.proven)])
    sections.append({"title": EXTENDED, "extended": True, "fields": fields})
    return {"title": body.title, "subtitle": body.subtitle, "picture": body.picture,
            "badges": [{"text": written(r), "tone": "muted", "hint": written_hex(r)}],
            "sections": sections}


def shop_stock(model, n: int) -> dict:
    """A shop's stock: each item's icon, name and price, each opening the
    item's card; or why it is not known."""
    from decoders.plugins.SLUS_006_28.records import shops as sh
    t = battle._tables(model)
    if t.shops is None:
        return {"title": "Stock", "verdict": {
            "tone": "warn",
            "text": f"Not known: the shops' stock (g_ShopStockRows) is not located in "
                    f"{model.ctx.program}, so what this shop sells is not shown."}}
    shop = t.shops.get(n)
    if shop is None or not shop.items:
        return {"title": "Stock", "note": "It sells nothing."}
    pictures, unseen = [], []
    for i in shop.items:
        rec = t.items.get(i)
        price = rec.values["price"] if rec is not None else None
        words = battle._item_word(model, i)
        cost = "free" if shop.free else f"{price}" if price is not None else ""
        image = battle.icon(model, i)
        caption = f"{words} · {cost}" if cost else words
        if image is not None:
            pictures.append({"image": image, "caption": caption, "ref": ref("item", i)})
        else:
            unseen.append(caption)
    note = "Each sells for its own price, the item table's." + (
        " This shop takes no money." if shop.free else "")
    if sh.HIDDEN_WHILE_CARRIED in shop.items:
        note += (f" {battle._item_word(model, sh.HIDDEN_WHILE_CARRIED)} is not offered while "
                 "anyone in the party carries one.")
    return {"title": "Stock", "cite": "ShopListSet (0x80051768)", "pictures": pictures,
            "list": unseen, "note": note}


def where_met(model, n: int) -> dict:
    """Where monster n is met: the battles it is in, under the places of
    the maps whose map monsters or scripts start them; the debug room's
    last, then those nothing is known to start."""
    from viewer_tabs.links import world
    t = battle._tables(model)
    fights = model.fights
    fm = model.field
    w = world._world(model)
    by_place: dict[str, tuple[tuple, list]] = {}
    for b in sorted(t.battles):
        if not t.loads(b) or n not in t.monster_ids(b):
            continue
        how: dict[int, str] = {m: "a map monster starts it" for m in fights.monsters.get(b, ())}
        for sid, _music in fights.scripts.get(b, []):
            maps = ({DEBUG_ROOM} if sid in fm.debug_scripts
                    else set(fm.script_maps.get(sid, ())))
            for m in maps:
                how.setdefault(m, "a script starts it")
        if not how:
            _add(by_place, "Started by no map or script", (2, 0),
                 links.link_json(model, ref("battle", b), ""))
            continue
        for m in sorted(how):
            debug = m == DEBUG_ROOM
            place = f"{w.map_title(m)} (the debug room)" if debug else w.map_title(m)
            _add(by_place, place, (1 if debug else 0, m),
                 links.link_json(model, ref("battle", b), how[m]))
    groups = [{"title": place, "dir": "out", "links": found}
              for place, (_key, found) in sorted(by_place.items(), key=lambda p: p[1][0])]
    if not groups:
        return {"title": "Where it is met", "note": "No battle the game loads has it."}
    return {"title": "Where it is met", "links": groups,
            "fanNote": "Its battles, under the places where they start: by touching a "
                       "monster on the map, or in a scene. The debug room's come last.",
            "note": "Its battles, under the places whose maps start them: by touching a "
                    "map monster (MapObjectTouchRun (0x8007ACD8)) or by a script's BATTLE "
                    "command (ScriptCommandMapBtlRun (0x8005DFF0)). The debug room's come "
                    "last."}


def _add(by_place: dict, place: str, key: tuple, link: dict):
    """A battle under a place, once; the place sorted by its first map."""
    old_key, found = by_place.get(place, (key, []))
    if all(had["ref"] != link["ref"] for had in found):
        found.append(link)
    by_place[place] = (min(old_key, key), found)

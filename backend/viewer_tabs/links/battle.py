"""Battles, monsters, items, spells and the cast: their cards, and the links
the battle code makes between them.

A battle is a row of g_BtlNumberRows: BtlEnemyLoad (0x8002B3AC) reads its
monster set (the graphics BtlDataLoad (0x80018694) loads) and its monster
group (who stands where) and puts the group's monsters in slots 6 to 13.
A script starts one with its BATTLE command (0x2B) through a row of
g_ScriptMapBtlRows, a scripted battle (ScriptCommandMapBtlRun
(0x8005DFF0)). A monster is a row of g_BtlEnemyRows (BtlEnemyStatsSet
(0x8002A638)): its stats, what it drops, its attacks. Items, spells, the
attack rows and the shops are the program's tables (records.items,
records.spells, records.attack_classes, records.shops); the party's
starting records are resource 0xE7 (formats.party_init). The characters
are the party's numbers, 1 to 12; whose a portrait is, viewer_tabs.whose
says. Portrait list n is the scene block FaceSlot6Load (0x8001B50C) reads
(formats.face_blocks).

Names come from the disc's string table at run time (viewer_tabs.names).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from viewer_tabs import links, whose
from viewer_tabs.field_view import DEBUG_ROOM
from viewer_tabs.links import CardBody, Edge
from viewer_tabs.refs import ref

BTL_ENEMY_LOAD = "BtlEnemyLoad (0x8002B3AC)"
BTL_DATA_LOAD = "BtlDataLoad (0x80018694)"
SCRIPT_BTL_RUN = "ScriptCommandMapBtlRun (0x8005DFF0)"
MAP_BTL_RUN = "MapBtlRun (0x8007AE58)"
BOSS_CHECK = "BtlSpecialCheck (0x80038500)"
STATS_SET = "BtlEnemyStatsSet (0x8002A638)"
WIN_ITEMS = "BtlWinItemsGive (0x80028A54)"
WIN_REWARDS = "BtlWinRewardSum (0x80028D78)"
ATTACK_RUN = "BtlActionKindRun (0x8002E12C)"
SPECIAL_SET = "BtlEnemyActionAdjust (0x80029510)"
ROW_RUN = "BtlActionRowRun (0x80031ABC)"
ITEM_USE_GET = "ChrItemUseGet (0x80058088)"
WORN_ADD = "ChrWornItemValuesAdd (0x800587D0)"
WORN_REMOVE = "ChrWornItemValuesRemove (0x8005886C)"
LEVEL_UP = "ChrLevelUp (0x80028554)"
RECORDS_RESET = "ChrRecordsReset (0x80063B30)"
FACE_CELL_SET = "FaceCellSet (0x8001B3DC)"
FACE_SLOT6_FIND = "FaceSlot6Find (0x8001B5C4)"
SHOP_LIST_SET = "ShopListSet (0x80051768)"
SHOP_RUN = "ShopRun (0x80050694)"
SCRIPT_SHOP_RUN = "ScriptCommandShopRun (0x8005E384)"
ICON_BYTES_SET = "MenuIconBytesSet (0x8006C6F8)"
ICON_BYTES_DISP = "MenuIconBytesDisp (0x8006C21C)"
ICON_SPELLS_SET = "MenuIconBytesSpellsSet (0x8006C84C)"
CHANGE_ROWS_DISP = "MenuChangeRowsDisp (0x8006FB3C)"
CHANGE_ROW_SET = "ChrWornItemChangeRowSet (0x800584C0)"
PARTY_STATS_SET = "BtlPartyStatsSet (0x8002A138)"

#: The characters, the party's numbers: the string table names 1 to 12, and
#: FaceListPartySet (0x80075EFC) keeps a member's number below 0xD.
PARTY_LAST = whose.PARTY_LAST
#: ChrLevelUp (0x80028554): number 0xB learns number 1's spells.
SPELL_ALIAS = {1: 0x0B}
#: ChrWornItemValuesAdd (0x800587D0) sets story flag +0x05 + 0x2BC, and
#: ChrWornItemValuesRemove (0x8005886C) clears it.
WORN_FLAG_BASE = 0x2BC
#: BtlWinItemsGive (0x80028A54) tries nothing unless the first item is 1..0xA4.
DROP_LAST = 0xA4
#: rng_7f_draw (0x8003A0B4) draws 0..0x7F; a drop is given when the draw
#: is not above its rate.
DRAWS = 0x80
#: Places listed in a fact before "and n more".
NAMED = 3
#: MenuIconBytesSet (0x8006C6F8) puts a character's worn items and items,
#: item numbers, in the menu's icon bytes, and MenuIconBytesDisp
#: (0x8006C21C) draws byte n as icon n; MenuIconBytesSpellsSet
#: (0x8006C84C) puts a spell's number + 0xB6 there, past the items'.
SPELL_ICON_BASE = 0xB6
#: MenuChangeRowsDisp (0x8006FB3C) labels a worn item's kind k (its row's
#: +0xC nibbles) with string 0x618 + k, beside the number
#: ChrWornItemChangeRowSet (0x800584C0) reads for k from the character
#: record: 1 to 5 the words +8 to +0x10, 6 the byte +0x12, 7 +0x1D, 8 +0x13.
STAT_STRINGS = 0x618
#: The kind that names each stat. BtlPartyStatsSet (0x8002A138) copies
#: the record's +8 to +0x13 to the same places of a slot's stats, and
#: BtlEnemyStatsSet (0x8002A638) a monster's row to them, so a monster's
#: stat is the one the menu names (+0x1D goes elsewhere: kind 7 names no
#: monster's stat).
STAT_KINDS = {"stat_08": 1, "stat_0a": 2, "stat_0c": 3, "stat_0e": 4, "stat_10": 5,
              "attack_count": 6, "walk_reach": 8}
STAT_WORDS_PROOF = (f"string 0x618 + the stat's kind: {CHANGE_ROWS_DISP} shows it beside the "
                    f"number {CHANGE_ROW_SET} reads for the kind (1 to 5 stat_08 to stat_10, "
                    f"6 attack_count, 8 walk_reach); {PARTY_STATS_SET} and {STATS_SET} fill "
                    f"those stats from a character's record and a monster's row")
#: A monster's stats a card names in the menu's words (attack_count is its
#: "Hits").
MONSTER_STATS = ("stat_08", "stat_0a", "stat_0c", "stat_0e", "stat_10", "walk_reach")


def _cached(model, key: str, build):
    """`build(model)`, kept for as long as the disc is open (and shared
    with its twin: GameModel.kept)."""
    return model.kept(key, build)


# -- the program's tables ----------------------------------------------------

@dataclass
class _Tables:
    image: bytes
    battles: dict           # battle -> records.encounters.Encounter
    groups: dict            # monster group -> Formation
    sets: dict              # monster set that loads something -> (resource, monsters)
    monsters: dict          # monster -> EnemyTemplate (row monster - 1)
    items: dict             # item -> ItemRecord
    spells: dict            # spell -> SpellRecord, rows that hold one
    attacks: dict           # monster attack -> AttackClass
    scripted: dict          # scripted battle -> EncounterRow
    shops: dict | None      # shop -> records.shops.Shop; None where not located

    def loads(self, battle: int) -> bool:
        """Whether the battle's monster set loads anything: an entry whose
        set names no resource is an empty one (BtlDataLoad loads nothing)."""
        e = self.battles.get(battle)
        return e is not None and e.set in self.sets

    def monster_ids(self, battle: int) -> list[int]:
        """The battle's monsters, in their group's order."""
        return [s.enemy_id for s in self.groups[self.battles[battle].formation].slots]


def _read_tables(model) -> _Tables:
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    from decoders.plugins.SLUS_006_28.records import attack_classes as ac
    from decoders.plugins.SLUS_006_28.records import encounters as en
    from decoders.plugins.SLUS_006_28.records import enemy_templates as et
    from decoders.plugins.SLUS_006_28.records import items, programs, shops, spells
    img = model.need_names().binary.code
    sets = {}
    for s in range(en.SET_FIRST, en.SET_LAST + 1):
        res = en.set_resource(img, s)
        if res:
            sets[s] = (res, en.type_list(img, s))
    return _Tables(
        image=img,
        battles={e.id: e for e in en.all_encounters(img)},
        groups={g: en.formation(img, g) for g in range(en.FORMATION_COUNT)},
        sets=sets,
        monsters={r.index + 1: r for r in et.read_from_exe(img)},
        items={r.item_id: r for r in items.read_from_exe(img)},
        spells={r.number: r for r in spells.read_from_exe(img) if r.number and not r.is_empty},
        attacks={r.class_id: r for r in ac.read_from_exe(img)},
        scripted={r.row: r for r in es.encounter_rows(img)},
        shops=({s.number: s for s in shops.read_from_exe(img)}
               if programs.has(img, "g_ShopStockRows") else None))


def _tables(model) -> _Tables:
    return _cached(model, "_battle_tables", _read_tables)


def _battle(t: _Tables, n: int):
    e = t.battles.get(n)
    if e is None:
        raise LookupError(f"there is no battle {n}: g_BtlNumberRows numbers them 1 to 255")
    return e


def _monster(t: _Tables, n: int):
    rec = t.monsters.get(n)
    if rec is None or rec.is_empty:
        raise LookupError(f"there is no monster {n}: g_BtlEnemyRows holds monsters 1 to "
                          f"{len(t.monsters)}")
    return rec


def _item(t: _Tables, n: int):
    rec = t.items.get(n)
    if rec is None:
        raise LookupError(f"there is no item {n}: g_BtlItemTable holds items 1 to {len(t.items)}")
    if not any(rec.raw):
        raise LookupError(f"item {n}'s row of g_BtlItemTable is empty: no item is numbered so")
    return rec


def _spell(t: _Tables, n: int):
    rec = t.spells.get(n)
    if rec is None:
        raise LookupError(f"there is no spell {n}: its row of g_BtlSpellRows is empty "
                          "or past the table")
    return rec


def _attack(t: _Tables, n: int):
    rec = t.attacks.get(n)
    if rec is None or rec.is_empty:
        raise LookupError(f"there is no monster attack {n}: its row of g_BtlAttackRows is "
                          "empty or past the table")
    return rec


# -- names -------------------------------------------------------------------

def _named(model, method: str, n: int) -> str | None:
    names = model.names
    return getattr(names, method)(n) if names is not None else None


def _monster_word(model, n: int) -> str:
    return _named(model, "enemy", n) or f"monster {n}"


def _item_word(model, n: int) -> str:
    return _named(model, "item", n) or f"item {n}"


def _character_name(model, n: int) -> str | None:
    return _named(model, "character", n) if 1 <= n <= PARTY_LAST else None


def _character_word(model, n: int) -> str:
    return _character_name(model, n) or f"character {n}"


def _summary(model, ids: list[int]) -> str:
    """"‹name› ×3, ‹name›": the monsters in their group's order, counted."""
    counts = Counter(ids)
    return ", ".join(f"{_monster_word(model, i)} ×{counts[i]}" if counts[i] > 1
                     else _monster_word(model, i) for i in dict.fromkeys(ids))


def _listed(words: list[str]) -> str:
    more = len(words) - NAMED
    return ", ".join(words[:NAMED]) + (f" and {more} more" if more > 0 else "")


def _places(model, maps) -> str:
    names = model.names
    return _listed(sorted({(names.map_name(m) if names else None) or f"map {m}"
                           for m in maps}))


def _chance(rate: int) -> str:
    """A drop's chance in plain words: (rate + 1) draws in 0x80."""
    p = 100 * min(rate + 1, DRAWS) / DRAWS
    return f"{p:.0f}%" if p >= 10 else f"{p:.1f}%"


def _drops(rec) -> list[tuple[int, str]]:
    """(item, how likely) for each item a won battle may give for the
    monster, as BtlWinItemsGive (0x80028A54) tries them: the first, and
    the second only when the first's draw fails."""
    v = rec.values
    first, second = v["win_item_1"], v["win_item_2"]
    if not 1 <= first <= DROP_LAST:
        return []
    out = [(first, _chance(v["win_rate_1"]))]
    if second:
        out.append((second, f"{_chance(v['win_rate_2'])} when the first is not given"))
    return out


# -- what starts each battle ---------------------------------------------------

def _read_starts(model) -> dict[int, list[tuple[int, int, int]]]:
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    t = _tables(model)
    fm = model.field
    out: dict[int, list[tuple[int, int, int]]] = {}
    for sid in sorted(fm.script_resources):
        try:
            buf, cmds, _labels = fm.script(sid)
        except Exception:
            continue            # FieldMaps.errors says why
        for b in es.battles(buf, list(cmds.values())):
            row = t.scripted.get(b["row"])
            if row is not None:
                out.setdefault(row.encounter, []).append((sid, b["offset"], row.row))
    return out


def _starts(model) -> dict[int, list[tuple[int, int, int]]]:
    """Battle -> (script, offset, scripted battle) of each BATTLE command
    that starts it (ScriptCommandMapBtlRun (0x8005DFF0))."""
    return _cached(model, "_battle_starts", _read_starts)


# -- the shops the scripts open ------------------------------------------------

def _read_shop_runs(model) -> dict[int, list[tuple[int, int]]]:
    from decoders.plugins.SLUS_006_28.formats import event_script as es
    fm = model.field
    out: dict[int, list[tuple[int, int]]] = {}
    for sid in sorted(fm.script_resources):
        try:
            buf, cmds, _labels = fm.script(sid)
        except Exception:
            continue            # FieldMaps.errors says why
        for offset, shop in es.shop_runs(buf, list(cmds.values())):
            out.setdefault(shop, []).append((sid, offset))
    return out


def shop_runs(model) -> dict[int, list[tuple[int, int]]]:
    """Shop -> (script, offset) of each command 0x2E that opens it
    (ScriptCommandShopRun (0x8005E384))."""
    return _cached(model, "_shop_runs", _read_shop_runs)


def shop_places(model, n: int) -> tuple[list[str], bool]:
    """Where shop n is opened: the places of the maps whose scripts open it,
    each once, in the maps' order; and whether a debug-room script opens
    it too (listed apart, after them)."""
    fm = model.field
    names = model.names
    sids = list(dict.fromkeys(sid for sid, _o in shop_runs(model).get(n, [])))
    maps = sorted({m for sid in sids if sid not in fm.debug_scripts
                   for m in fm.script_maps.get(sid, ()) if m != DEBUG_ROOM})
    places = [(names.map_name(m) if names else None) or f"map {m}" for m in maps]
    debug = any(sid in fm.debug_scripts for sid in sids) or any(
        DEBUG_ROOM in fm.script_maps.get(sid, ()) for sid in sids)
    return list(dict.fromkeys(places)), debug


def shop_title(model, n: int) -> str:
    """"‹place› · shop 5": the first place that opens it, else its number."""
    try:
        places, _debug = shop_places(model, n)
    except Exception:
        places = []
    return f"{places[0]} · shop {n}" if places else f"shop {n}"


# -- the menu's words and pictures -----------------------------------------------

def stat_word(model, stat: str) -> str:
    """The menu's word for a stat (STAT_KINDS: string 0x618 + its kind),
    else the code's name for it."""
    kind = STAT_KINDS.get(stat)
    strings = getattr(model.names, "strings", None)
    word = strings.text(STAT_STRINGS + kind) if strings is not None and kind else None
    return word or stat


def kind_word(model, kind: int) -> str:
    """The menu's word for a worn item's kind 1 to 8 (string 0x618 +
    kind), else the stat the code names for it (records.items)."""
    from decoders.plugins.SLUS_006_28.records import items
    strings = getattr(model.names, "strings", None)
    word = strings.text(STAT_STRINGS + kind) if strings is not None and 1 <= kind <= 8 else None
    return word or items.STAT_SELECTORS.get(kind, f"kind {kind}")


def raises(model, rec) -> str:
    """What wearing an item raises, in the menu's words: "+12 ‹word›"."""
    return ", ".join(f"+{m['amount']} {kind_word(model, m['selector'])}" for m in rec.modifiers)


@dataclass
class _Icons:
    block: bytes
    at: int                 # the icons' place in the block (system_dat.block_places)
    offsets: list
    colours: list
    drawn: dict


def _read_icons(model) -> _Icons:
    from decoders.plugins.SLUS_006_28.formats import system_dat as sd
    from decoders.plugins.SLUS_006_28.formats import system_strings as ss
    names = model.need_names()
    raw = names.read_resource(sd.RESOURCE)
    at = sd.block_places(names.binary.code)[1]
    blk = ss.block(raw)
    return _Icons(blk, at, sd.icon_offsets(blk, at),
                  sd.colours(sd.palette_rows(raw)[sd.ICON_ROW]), {})


def icon(model, n: int):
    """Icon n as the menus draw it (IconCellDraw (0x8001AD60), formats.
    system_dat), or None when the icons cannot be read or have no n."""
    from decoders.plugins.SLUS_006_28.formats import system_dat as sd
    try:
        icons = _cached(model, "_battle_icons", _read_icons)
    except Exception:
        return None
    if n not in icons.drawn:
        try:
            texels = sd.icon_pixels(icons.block, icons.offsets, n, icons.at)
            icons.drawn[n] = sd.icon_image(texels, icons.colours) if any(texels) else None
        except (IndexError, ValueError):
            icons.drawn[n] = None
    return icons.drawn[n]


def characters_words(model, chars) -> str:
    """The characters named, each once, with their number where two share
    a name (characters 1 and 11 do)."""
    chars = list(dict.fromkeys(chars))
    words = [_character_word(model, c) for c in chars]
    twice = {w for w in words if words.count(w) > 1}
    return ", ".join(f"{w} (character {c})" if w in twice else w for c, w in zip(chars, words))


# -- portraits and the party -------------------------------------------------

@dataclass
class _Faces:
    colours: list
    portraits: dict         # portrait -> (resource, picture, its 64 x 64 texels)
    lists: dict             # portrait list -> (resource, FaceBlock)


def _read_faces(model) -> _Faces:
    from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
    from decoders.plugins.SLUS_006_28.formats import system_dat
    names = model.need_names()
    rows = system_dat.palette_rows(names.read_resource(system_dat.RESOURCE))
    if fb.CLUT_ROW not in rows:
        raise LookupError(f"resource {system_dat.RESOURCE} loads no palette row {fb.CLUT_ROW}")
    portraits = {}
    for file in range(1, fb.FILES + 1):
        resource = fb.file_resource(file)
        block = fb.parse(names.read_resource(resource))
        if not block.valid:
            continue
        for picture, px in enumerate(block.images[:fb.PER_FILE]):
            portraits[(file - 1) * fb.PER_FILE + picture + 1] = (resource, picture, px)
    lists = {}
    for n in range(1, fb.SCENE_LIMIT):
        resource = fb.scene_resource(n)
        lists[n] = (resource, fb.parse(names.read_resource(resource)))
    return _Faces(system_dat.colours(rows[fb.CLUT_ROW]), portraits, lists)


def _faces(model) -> _Faces:
    return _cached(model, "_battle_faces", _read_faces)


def _read_party(model) -> dict:
    from decoders.plugins.SLUS_006_28.formats import party_init as pi
    names = model.need_names()
    buf = names.read_resource(pi.RESOURCE)
    return {m.char_id: m for m in pi.party(buf, pi.exe_items(names.binary.code))}


def _party(model) -> dict:
    """Character -> formats.party_init.PartyMemberData, as a new game sets
    them up (ChrRecordsReset (0x80063B30))."""
    return _cached(model, "_battle_party", _read_party)


def _which(n: int) -> int:
    """Which of its file's five portrait n is, from 1 (FaceCellSet (0x8001B3DC))."""
    return (n - 1) % whose.PER_FILE + 1


def _whose(model, n: int) -> whose.Whose:
    """Whose portrait n is; no one's when the portraits cannot be read."""
    try:
        return whose.of(model).get(n) or whose.Whose(None)
    except (LookupError, ValueError):
        return whose.Whose(None)


# -- the edges -----------------------------------------------------------------

@links.edges(kept=True)
def battle_edges(model):
    """Each battle -> its monsters, monster set and monster group; each
    group a battle names -> its monsters; each monster set -> the
    monsters it draws."""
    t = _tables(model)
    groups = set()
    for n, e in t.battles.items():
        if not t.loads(n):
            continue
        b = ref("battle", n)
        yield Edge(b, ref("monster-set", e.set), "Monster set", "Battles", "", BTL_ENEMY_LOAD)
        yield Edge(b, ref("monster-group", e.formation), "Monster group", "Battles", "",
                   BTL_ENEMY_LOAD)
        groups.add(e.formation)
        # the battle's title counts them
        for m in dict.fromkeys(t.monster_ids(n)):
            yield Edge(b, ref("monster", m), "Monsters", "Fought in battles", "", BTL_ENEMY_LOAD)
    for g in sorted(groups):
        counts = Counter(s.enemy_id for s in t.groups[g].slots)
        for m, k in counts.items():
            yield Edge(ref("monster-group", g), ref("monster", m), "Monsters",
                       "In monster groups", f"×{k}" if k > 1 else "", BTL_ENEMY_LOAD)
    for s, (_res, types) in t.sets.items():
        for m in dict.fromkeys(types):
            yield Edge(ref("monster-set", s), ref("monster", m), "Draws",
                       "Drawn in monster sets", "", BTL_ENEMY_LOAD)


@links.edges(kept=True)
def scripted_battle_edges(model):
    """Each scripted battle -> its battle and its own party; each script
    -> the scripted battles and battles its BATTLE commands start."""
    t = _tables(model)
    for n, row in t.scripted.items():
        sb = ref("scripted-battle", n)
        if 1 <= row.encounter <= 255:
            yield Edge(sb, ref("battle", row.encounter), "Battle", "Scripted battles",
                       "", SCRIPT_BTL_RUN)
        for c in dict.fromkeys(row.party):
            yield Edge(sb, ref("character", c), "Party", "In scripted battles",
                       "", SCRIPT_BTL_RUN)
    seen = set()
    for battle, starts in _starts(model).items():
        for sid, _offset, n in starts:
            if (sid, n) in seen:
                continue
            seen.add((sid, n))
            s = ref("script", sid)
            yield Edge(s, ref("scripted-battle", n), "Scripted battles", "Started by",
                       "its BATTLE command", SCRIPT_BTL_RUN)
            if 1 <= battle <= 255:
                yield Edge(s, ref("battle", battle), "Battles", "Started by",
                           f"through scripted battle {n}", SCRIPT_BTL_RUN)


@links.edges(kept=True)
def monster_edges(model):
    """Each monster -> the items it drops and the attacks it uses."""
    t = _tables(model)
    for n, rec in t.monsters.items():
        if rec.is_empty:
            continue
        m = ref("monster", n)
        for item, how in _drops(rec):
            yield Edge(m, ref("item", item), "Drops", "Dropped by", how, WIN_ITEMS)
        v = rec.values
        if v["attack_number"] and v["attack_number"] in t.attacks:
            yield Edge(m, ref("monster-attack", v["attack_number"]), "Attacks", "Used by",
                       "its attack", ATTACK_RUN)
        if v["kind7_number"] and v["kind7_number"] in t.attacks:
            yield Edge(m, ref("monster-attack", v["kind7_number"]), "Attacks", "Used by",
                       "its special", SPECIAL_SET)


@links.edges(kept=True)
def goods_edges(model):
    """Each item -> who can wear it and the story flag it sets while worn;
    each spell -> who learns it; each shop -> what it sells."""
    from decoders.plugins.SLUS_006_28.records import shops
    t = _tables(model)
    for n, rec in t.items.items():
        if not any(rec.raw):
            continue
        it = ref("item", n)
        wearers = rec.values["wearers"]
        for c in range(1, PARTY_LAST + 1):
            if wearers >> (c - 1) & 1:
                yield Edge(it, ref("character", c), "Worn by", "Can wear", "", ITEM_USE_GET)
        if rec.values["story_bit"]:
            flag = ref("story-flag", rec.values["story_bit"] + WORN_FLAG_BASE)
            yield Edge(it, flag, "While worn", "Set by", "set while it is worn", WORN_ADD)
            yield Edge(it, flag, "While worn", "Cleared by", "cleared when it is taken off",
                       WORN_REMOVE)
    for n, rec in t.spells.items():
        v = rec.values
        if not v["chr_id"]:
            continue
        when = "from the start" if v["level"] <= 1 else f"at level {v['level']}"
        for c in (v["chr_id"], SPELL_ALIAS.get(v["chr_id"])):
            if c:
                yield Edge(ref("spell", n), ref("character", c), "Learned by", "Magic",
                           when, LEVEL_UP)
    for n, shop in (t.shops or {}).items():
        if not shop.opens:
            continue
        for item in dict.fromkeys(shop.items):
            note = ("not while the party carries one" if item == shops.HIDDEN_WHILE_CARRIED
                    else "")
            yield Edge(ref("shop", n), ref("item", item), "Sells", "Sold in", note,
                       SHOP_LIST_SET)


@links.edges(kept=True)
def shop_edges(model):
    """Each script -> the shops its commands 0x2E open."""
    for n, opened in shop_runs(model).items():
        for sid in dict.fromkeys(sid for sid, _offset in opened):
            yield Edge(ref("script", sid), ref("shop", n), "Shops", "Opened by",
                       "its command 0x2E", SCRIPT_SHOP_RUN)


@links.edges(kept=True)
def cast_edges(model):
    """Each character -> their portraits (whose.of) and the equipment a new
    game starts them with; each portrait list -> the portraits it lists."""
    from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
    faces = _faces(model)
    found = whose.of(model)
    for n in sorted(faces.portraits):
        w = found.get(n)
        if w is None or w.character is None:
            continue
        # a named character's portrait says which it is in its title
        note = (f"the same drawing as portrait {w.copy_of}" if w.copy_of is not None
                else "" if _character_name(model, w.character) else f"{_which(n)} of 5")
        yield Edge(ref("character", w.character), ref("portrait", n), "Portraits", "Of",
                   note, whose.BYTE_LOAD)
    for n, (_res, block) in faces.lists.items():
        if not block.valid:
            continue
        for face in dict.fromkeys(f for f in block.faces if 1 <= f <= fb.FACES):
            yield Edge(ref("portrait-list", n), ref("portrait", face), "Portraits",
                       "In portrait lists", "", FACE_SLOT6_FIND)
    for c, member in _party(model).items():
        for place, item in enumerate(member.starting_equipment, start=1):
            if item:
                yield Edge(ref("character", c), ref("item", item), "Starts wearing",
                           "Worn from the start by", f"place {place}", RECORDS_RESET)


# -- titles --------------------------------------------------------------------

def _battle_titles(model) -> dict[int, str]:
    def build(model):
        t = _tables(model)
        return {n: _summary(model, t.monster_ids(n)) for n in t.battles
                if t.loads(n) and t.monster_ids(n)}
    return _cached(model, "_battle_titles", build)


@links.title("battle")
def battle_title(model, r) -> str | None:
    return _battle_titles(model).get(r.id[0])


@links.title("monster")
def monster_title(model, r) -> str | None:
    return _named(model, "enemy", r.id[0])


@links.title("monster-attack")
def monster_attack_title(model, r) -> str | None:
    return _named(model, "enemy_special", r.id[0])


@links.title("item")
def item_title(model, r) -> str | None:
    return _named(model, "item", r.id[0])


@links.title("spell")
def spell_title(model, r) -> str | None:
    return _named(model, "spell", r.id[0])


@links.title("shop")
def shop_link_title(model, r) -> str | None:
    return shop_title(model, r.id[0])


@links.title("character")
def character_title(model, r) -> str | None:
    return _character_name(model, r.id[0])


@links.title("portrait")
def portrait_title(model, r) -> str | None:
    n = r.id[0]
    w = _whose(model, n)
    name = _character_name(model, w.character) if w.character is not None else None
    if not name:
        return None
    if w.copy_of is not None:
        return f"{name}, portrait {n}, a copy"
    return f"{name}, portrait {_which(n)} of 5"


# -- cards ---------------------------------------------------------------------

@links.card("battle")
def battle_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.records import encounters as en
    n = r.id[0]
    t = _tables(model)
    e = _battle(t, n)
    boss = n >= en.BOSS_CLASS_FIRST
    extended = [("Row", f"g_BtlNumberRows (0x800AC172) + {n} × 2: monster set {e.set}, "
                        f"monster group {e.formation}")]
    proven = [BTL_ENEMY_LOAD, BTL_DATA_LOAD]
    if not t.loads(n):
        return CardBody(
            title=f"battle {n}", subtitle="an empty entry of the battle table",
            facts=[("Monsters", "none: its monster set loads nothing")],
            extended=extended + [("Monster set", f"monster set {e.set} names no resource "
                                                 "(g_BtlDataResources (0x800A7E18) = 0)")],
            proven=proven)
    ids = t.monster_ids(n)
    facts = [("Monsters", _summary(model, ids) if ids else "none")]
    if boss:
        facts.append(("Boss fight", "yes: the battle plays each boss's own moves"))
        extended.append(("Boss class", f"battle {n:#x} is 0xEB or above: BtlInit (0x80029E68) "
                                       "runs BtlSpecialInit (0x8002A7FC), BtlRun (0x80027434) "
                                       "leaves out BtlEnemyActionSet (0x8004C958) and plays "
                                       "song 0x3E on a win"))
        proven.append(BOSS_CHECK)
    try:
        facts += _started_by(model, n)
        starts = _starts(model).get(n, [])
        if starts:
            extended.append(("BATTLE commands", "; ".join(
                f"script {sid} at {off:#x}, scripted battle {row}" for sid, off, row in starts)))
            proven += [SCRIPT_BTL_RUN, MAP_BTL_RUN]
    except Exception as ex:
        extended.append(("What starts it", f"could not be read: {type(ex).__name__}: {ex}"))
    res = t.sets[e.set][0]
    extended.append(("Monster set", f"monster set {e.set}: resource {res} ({res:#x})"))
    extended.append(("Monster group", f"monster group {e.formation}: "
                                      f"g_BtlEnemyGroups (0x800AA974) + {e.formation} × 0x18"))
    return CardBody(title=_battle_titles(model).get(n) or f"battle {n}",
                    subtitle="a boss fight" if boss else "a fight",
                    facts=facts, extended=extended, proven=proven)


def _started_by(model, n: int) -> list[tuple[str, str]]:
    """What starts battle n, in plain words: the scenes, the map monsters,
    the debug room's list."""
    fm = model.field
    starts = _starts(model).get(n, [])
    story = sorted({sid for sid, _o, _r in starts if sid not in fm.debug_scripts})
    out = []
    if story:
        out.append(("Started by a scene", _listed([
            f"script {sid}" + (f" ({_places(model, fm.script_maps[sid])})"
                               if fm.script_maps.get(sid) else "") for sid in story])))
    on_maps = model.fights.monsters.get(n)
    if on_maps:
        out.append(("Met on the field", f"touching a monster on {_places(model, on_maps)}"))
    if any(sid in fm.debug_scripts for sid, _o, _r in starts):
        out.append(("In the debug room", "its list of fights starts it"))
    if not out:
        out.append(("Started by", "nothing on the disc: no scene and no map monster starts it"))
    return out


@links.card("scripted-battle")
def scripted_battle_card(model, r) -> CardBody:
    n = r.id[0]
    t = _tables(model)
    row = t.scripted.get(n)
    if row is None:
        raise LookupError(f"there is no scripted battle {n}: its row of g_ScriptMapBtlRows "
                          "names no battle")
    party = (", ".join(_character_word(model, c) for c in row.party) if row.party
             else "the party of the moment")
    return CardBody(
        title=f"scripted battle {n}", subtitle="a fight a scene starts",
        facts=[("Battle", f"battle {row.encounter}"), ("Party", party)],
        extended=[("Row", f"g_ScriptMapBtlRows (0x800B366C) + ({n} − 1) × 8, the BATTLE "
                          f"command's operand {n}"),
                  ("Party's x shift", f"{row.x_shift}: taken off each member's place "
                                      "before the fight (MapBtlRun (0x8007AE58))"),
                  ("Party slots", "the row's own list, number 12 in slot 5"
                   if row.party else "none listed: g_PartyIds (0x800B8BC0) as it is")],
        proven=[SCRIPT_BTL_RUN, MAP_BTL_RUN])


@links.card("monster-set")
def monster_set_card(model, r) -> CardBody:
    n = r.id[0]
    t = _tables(model)
    if n not in t.sets:
        raise LookupError(f"monster set {n} loads nothing: g_BtlDataResources names no "
                          "resource for it")
    res, types = t.sets[n]
    used = sum(1 for b, e in t.battles.items() if e.set == n and t.loads(b))
    return CardBody(
        title=f"monster set {n}", subtitle="the graphics a battle loads",
        facts=[("Draws", ", ".join(_monster_word(model, m) for m in types) or "no monster"),
               ("Battles", f"{used}")],
        extended=[("Resource", f"{res} ({res:#x}): g_BtlDataResources (0x800A7E18) + {n} × 2"),
                  ("Monsters", f"g_BtlEnemySetIds (0x800AC370) + {n} × 4: "
                               + ", ".join(str(m) for m in types)),
                  ("Blocks", "each monster draws from the block of its place in the list; "
                             "only the first three are matched, anything else draws from "
                             "block 3")],
        proven=[BTL_DATA_LOAD, BTL_ENEMY_LOAD])


@links.card("monster-group")
def monster_group_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.records import encounters as en
    n = r.id[0]
    t = _tables(model)
    g = t.groups.get(n)
    if g is None:
        raise LookupError(f"there is no monster group {n}: g_BtlEnemyGroups holds "
                          f"0 to {en.FORMATION_COUNT - 1}")
    ids = [s.enemy_id for s in g.slots]
    places = [f"slot {s.actor_slot}: monster {s.enemy_id} at ({s.x}, {s.y})"
              + (", facing left" if s.mirrored else "") for s in g.slots]
    return CardBody(
        title=f"monster group {n}", subtitle="who stands where in a fight",
        facts=[("Monsters", _summary(model, ids) if ids else "none")],
        extended=[("Record", f"g_BtlEnemyGroups (0x800AA974) + {n} × 0x18")]
        + [("Place", p) for p in places],
        proven=[BTL_ENEMY_LOAD])


@links.card("monster")
def monster_card(model, r) -> CardBody:
    n = r.id[0]
    t = _tables(model)
    rec = _monster(t, n)
    v = rec.values
    facts = [("Level", f"{v['level']}"), ("HP", f"{v['hp']}")]
    facts += [(stat_word(model, k), f"{v[k]}") for k in MONSTER_STATS]
    facts += [("Experience", f"{v['experience']}"), ("Money", f"{v['money']}")]
    if v["attack_count"] > 1:
        facts.append(("Hits", f"{v['attack_count']} times an attack"))
    drops = _drops(rec)
    facts.append(("Drops", "; ".join(f"{_item_word(model, i)} ({how})" for i, how in drops)
                  or "nothing"))
    fought = sum(1 for b in t.battles if t.loads(b) and n in t.monster_ids(b))
    facts.append(("Fought in", f"{fought} battles" if fought != 1 else "1 battle"))
    extended = [("Row", f"g_BtlEnemyRows (0x800A8768) + ({n} − 1) × 0x26"),
                ("Name", f"string {0x80 + n:#x}")]
    extended += [(k, f"{v[k]}") for k in ("stat_08", "stat_0a", "stat_0c", "stat_0e",
                                          "stat_10", "walk_reach", "walk_speed", "trait",
                                          "action_pick", "attack_show")]
    extended += [(k, f"{v[k]:#06x}") for k in ("weak_mask", "resist_mask")]
    extended.append(("Stats' words", STAT_WORDS_PROOF))
    extended.append(("Attack rows", f"attack_number {v['attack_number']}, kind7_number "
                                    f"{v['kind7_number']} (g_BtlAttackRows (0x800AC640))"))
    if v["win_item_1"] and not drops:
        extended.append(("Drops", f"win_item_1 is {v['win_item_1']}: above {DROP_LAST}, so "
                                  "BtlWinItemsGive tries neither item"))
    elif drops:
        extended.append(("Drops", f"win_rate_1 {v['win_rate_1']}, win_rate_2 {v['win_rate_2']}: "
                                  "given when rng_7f_draw (0x8003A0B4), 0 to 127, is not above it"))
    picture = None
    try:
        drawn = _monster_picture(model, n)
        if drawn is not None:
            picture, s, block = drawn
            extended.append(("Picture", f"monster set {s}, block {block}: animation 0's first "
                                        "pose, as a battle starts it (CLUT row 505)"))
    except Exception as ex:
        extended.append(("Picture", f"could not be drawn: {type(ex).__name__}: {ex}"))
    return CardBody(title=_monster_word(model, n), subtitle="a monster", picture=picture,
                    facts=facts, extended=extended,
                    proven=[STATS_SET, WIN_ITEMS, WIN_REWARDS, BTL_ENEMY_LOAD, CHANGE_ROWS_DISP])


def _monster_picture(model, n: int):
    cache = _cached(model, "_battle_monster_pictures", lambda model: {})
    if n not in cache:
        cache[n] = _draw_monster(model, n)
    return cache[n]


def _draw_monster(model, n: int):
    """(picture, monster set, block) of the first monster set that draws
    monster n: its block's animation 0, first pose, under CLUT B."""
    from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
    from decoders.plugins.SLUS_006_28.formats import sprite_pages as sp
    from decoders.plugins.SLUS_006_28.records import encounters as en
    t = _tables(model)
    for s, (res, types) in sorted(t.sets.items()):
        if n not in types:
            continue
        j = en.type_slot(types, n)
        if j >= len(types):
            continue
        bundle = bg.parse_set_bundle(model.need_names().read_resource(res), len(types))
        blk = bundle.actor(j)
        if blk is None:
            continue
        poses = {p.index: p for p in sp.list_poses(blk)}
        anims = blk.animations()
        first = anims[0].steps[0][0] if anims and anims[0].steps else min(poses, default=None)
        pose = poses.get(first)
        extent = sp.pose_extent(blk, pose) if pose is not None else None
        if extent is None:
            continue
        x0, y0, x1, y1 = extent
        pages = {p.index: bg.render_page(p, bundle.clut_b) for p in bundle.pages}
        image = sp.compose_pose(blk, pages, pose, origin=(-x0, -y0), size=(x1 - x0, y1 - y0))
        return image, s, j
    return None


_TARGETS = {2: "a fighter still standing", 7: "a party member with no status"}


@links.card("monster-attack")
def monster_attack_card(model, r) -> CardBody:
    n = r.id[0]
    t = _tables(model)
    v = _attack(t, n).values
    facts = [("Aims at", _TARGETS.get(v["target_mode"], "whoever it chose"))]
    if v["effect_magnitude"]:
        facts.append(("Power", f"{v['effect_magnitude']}"))
    extended = [("Row", f"g_BtlAttackRows (0x800AC640) + {n} × 8"),
                ("Name", f"string {0x300 | n:#x}, shown when a monster uses it as its "
                         "special (BtlActionStringDisp (0x8004987C))")]
    extended += [(k, f"{v[k]}") for k in ("target_mode", "effect_id", "effect_magnitude",
                                          "effect_param1", "effect_param2", "element_id",
                                          "spell_id")]
    return CardBody(title=_named(model, "enemy_special", n) or f"monster attack {n}",
                    subtitle="something a monster does in battle",
                    facts=facts, extended=extended,
                    proven=[ROW_RUN, "BtlActionTargetAdjust (0x8002ED34)", ATTACK_RUN,
                            SPECIAL_SET])


def _item_kind(v: dict) -> str:
    kind = v["kind"]
    if kind < 4:
        return f"equipment, worn in place {kind + 1}"
    if kind == 4:
        return "equipment, worn in place 5 or 6"
    if kind == 6:
        return "an item to carry, which cannot be given up"
    return "an item to carry"


@links.card("item")
def item_card(model, r) -> CardBody:
    n = r.id[0]
    t = _tables(model)
    rec = _item(t, n)
    v = rec.values
    facts = []
    said = _named(model, "item_description", n)
    if said:
        facts.append(("What it says", said))
    facts.append(("What it is", _item_kind(v)))
    if v["price"]:
        facts.append(("Price", f"{v['price']}"))
    facts.append(("Sells for", f"{v['sell_price']}" if v["sell_price"]
                  else "nothing: it cannot be given up"))
    uses = (["in battle"] if v["function_number"] else []) + (
        ["from the menu"] if v["target_modes"] >> 4 != 9 else [])
    facts.append(("Used", " and ".join(uses) if uses else "no"))
    if v["kind"] < 5:
        wearers = [c for c in range(1, PARTY_LAST + 1) if v["wearers"] >> (c - 1) & 1]
        facts.append(("Worn by", characters_words(model, wearers) or "no one"))
        if rec.modifiers:
            facts.append(("Raises", raises(model, rec)))
    if v["story_bit"]:
        facts.append(("While worn", f"story flag {v['story_bit'] + WORN_FLAG_BASE} is set"))
    extended = [("Row", f"g_BtlItemTable (0x800A9A68) + ({n} − 1) × 0x12"),
                ("Name", f"string {0x100 + n:#x}; what it says, string {0x200 + n:#x}"),
                ("Icon", f"icon {n}: {ICON_BYTES_SET} puts an item's number in the menu's "
                         f"icon bytes, and {ICON_BYTES_DISP} draws a byte as that icon"),
                ("kind", f"{v['kind']}"),
                ("wearers", f"{v['wearers']:#06x}: bit c − 1 for each character c "
                            f"({ITEM_USE_GET}, mode 1)")]
    extended += [("Bonus", f"+{m['amount']} to {m['stat']} (kind {m['selector']}: string "
                           f"{STAT_STRINGS + m['selector']:#x}, {CHANGE_ROWS_DISP})")
                 for m in rec.modifiers]
    extended += [(k, f"{v[k]:#04x}") for k in ("target_modes", "use_picture")]
    extended += [(k, f"{v[k]}") for k in ("function_number", "show_number", "trait",
                                          "worn_item_kind")]
    return CardBody(title=_item_word(model, n),
                    subtitle="equipment" if v["kind"] < 5 else "an item",
                    picture=icon(model, n), facts=facts, extended=extended,
                    proven=[ITEM_USE_GET, WORN_ADD, "ShopDealRun (0x80053194)", ROW_RUN,
                            ICON_BYTES_SET, ICON_BYTES_DISP, CHANGE_ROWS_DISP])


@links.card("spell")
def spell_card(model, r) -> CardBody:
    n = r.id[0]
    t = _tables(model)
    v = _spell(t, n).values
    facts = []
    said = _named(model, "spell_description", n)
    if said:
        facts.append(("What it says", said))
    if v["chr_id"]:
        facts.append(("Learned by", characters_words(
            model, [c for c in (v["chr_id"], SPELL_ALIAS.get(v["chr_id"])) if c])))
        facts.append(("Learned", "from the start" if v["level"] <= 1
                      else f"at level {v['level']}"))
    facts.append(("Costs", f"{v['cost']} MP"))
    if v["area_half_width"] or v["area_half_height"]:
        facts.append(("Area", f"{2 * v['area_half_width'] + 1} × "
                              f"{2 * v['area_half_height'] + 1} cells"))
    extended = [("Row", f"g_BtlSpellRowsByNumber (0x800AA728) + {n} × 0x0C"),
                ("Name", f"string {0x1B6 + n:#x}; what it says, string {0x2B6 + n:#x}"),
                ("Icon", f"icon {n + SPELL_ICON_BASE}: {ICON_SPELLS_SET} puts a spell's "
                         f"number + {SPELL_ICON_BASE:#x} in the menu's icon bytes, and "
                         f"{ICON_BYTES_DISP} draws a byte as that icon")]
    extended += [(k, f"{v[k]:#04x}") for k in ("target_modes", "use_place")]
    extended += [(k, f"{v[k]}") for k in ("chr_id", "function_number", "power",
                                          "show_number", "bit_number",
                                          "blocked_by_status_20")]
    return CardBody(title=_named(model, "spell", n) or f"spell {n}", subtitle="a spell",
                    picture=icon(model, n + SPELL_ICON_BASE), facts=facts, extended=extended,
                    proven=[LEVEL_UP, "BtlActionSpellRun (0x8002E718)", ROW_RUN,
                            ICON_SPELLS_SET, ICON_BYTES_DISP])


@links.card("shop")
def shop_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.records import shops
    n = r.id[0]
    t = _tables(model)
    opened = shop_runs(model).get(n)
    extended = [("Opened by", "; ".join(f"script {sid} at {offset:#x}" for sid, offset in opened)
                  + f": command 0x2E, {SCRIPT_SHOP_RUN}" if opened
                  else f"no script's command 0x2E ({SCRIPT_SHOP_RUN}) names it")]
    places, debug = shop_places(model, n)
    where = ", ".join(places + (["the debug room"] if debug else []))
    if not where:
        where = ("no map's own script: scripts others hand over to open it" if opened
                 else "no script opens it")
    if t.shops is None:
        if not opened:
            raise LookupError(f"the shops' stock (g_ShopStockRows) is not located in "
                              f"{model.ctx.program}, and no script opens shop {n}")
        return CardBody(
            title=shop_title(model, n), subtitle="a shop", extended=extended,
            facts=[("Opened in", where),
                   ("Sells", f"not known: the shops' stock (g_ShopStockRows) is not located "
                             f"in {model.ctx.program}")],
            proven=[SCRIPT_SHOP_RUN, SHOP_RUN])
    shop = t.shops.get(n)
    if shop is None:
        raise LookupError(f"there is no shop {n}: g_ShopStockRows holds shops 1 to {shops.COUNT}")
    facts = [("Opened in", where),
             ("Sells", ", ".join(_item_word(model, i) for i in shop.items) or "nothing")]
    if not shop.opens:
        facts.append(("Opens", "never: the game opens nothing for this number"))
    if shop.free:
        facts.append(("Prices", "none: this shop takes no money"))
    if shops.HIDDEN_WHILE_CARRIED in shop.items:
        facts.append(("Not offered", f"{_item_word(model, shops.HIDDEN_WHILE_CARRIED)}, "
                                     "while anyone in the party carries one"))
    return CardBody(
        title=shop_title(model, n), subtitle="a shop and its stock", facts=facts,
        extended=[("Row", f"g_ShopStockRows (0x800A8468) + ({n} − 1) × 6"), *extended],
        proven=[SHOP_RUN, SHOP_LIST_SET, "ShopStockGet (0x8001BF1C)", SCRIPT_SHOP_RUN])


@links.card("character")
def character_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
    from decoders.plugins.SLUS_006_28.formats import party_init as pi
    n = r.id[0]
    if not 1 <= n <= PARTY_LAST:
        raise LookupError(f"there is no character {n}: the characters are the party's "
                          f"numbers, 1 to {PARTY_LAST}")
    facts = []
    extended = [("Portrait file", f"file {n}: resource {fb.file_resource(n):#x} "
                                  f"(FaceDataLoad (0x8001B1C0)), portraits "
                                  f"{(n - 1) * 5 + 1} to {n * 5}; {whose.BYTE_LOAD} loads "
                                  f"it for character {n}"),
                ("Name", f"string {n:#x} (BtlLevelUpGainsDisp (0x8004C324))")]
    proven = [FACE_CELL_SET, whose.BYTE_LOAD]
    member = _party(model).get(n) if pi.CHAR_FIRST <= n <= pi.CHAR_LAST else None
    note = ""
    if member is not None:
        p = member.level1
        facts += [("Starting level", f"{p.level}"), ("Starting HP", f"{p.hp_max}"),
                  ("Starting MP", f"{p.mp_max}")]
        spells = [s for s in p.spells if s]
        if spells:
            facts.append(("Magic from the start", ", ".join(
                _named(model, "spell", s) or f"spell {s}" for s in spells)))
        note = ("The starting numbers are the ones a new game sets up; a scene that "
                "brings them into the party may raise their level.")
        extended += [("Character record", f"*g_ChrRecords (0x800B8BE4) + {n} × 0x40, from "
                                          f"resource {pi.RESOURCE:#x}")]
        extended += [(k, f"{v}") for k, v in zip(
            ("stat_08", "stat_0a", "stat_0c", "stat_0e", "stat_10"), p.stats)]
        proven.append(RECORDS_RESET)
    found = whose.of(model)
    copies = [f for f in whose.portraits_of(model, n) if found[f].copy_of is not None]
    if copies:
        facts.append(("Also drawn as", ", ".join(
            f"portrait {f}, a copy of their portrait {found[f].copy_of}" for f in copies)))
    return CardBody(title=_character_word(model, n),
                    subtitle="in the party",
                    picture=_first_portrait(model, n),
                    facts=facts, note=note, extended=extended, proven=proven)


def _first_portrait(model, c: int):
    """Character c's first portrait that draws anything, as a picture."""
    from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
    faces = _faces(model)
    for n in range((c - 1) * fb.PER_FILE + 1, c * fb.PER_FILE + 1):
        got = faces.portraits.get(n)
        if got is not None and any(got[2]):
            return fb.image(got[2], faces.colours)
    return None


@links.card("portrait")
def portrait_card(model, r) -> CardBody:
    from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
    n = r.id[0]
    faces = _faces(model)
    if n not in faces.portraits:
        raise LookupError(f"there is no portrait {n}: its file holds no picture for it")
    resource, picture, px = faces.portraits[n]
    w = _whose(model, n)
    c = w.character
    if c is None:
        facts = [("Of", "no one: it is blank" if not any(px) else
                  "no one the game names: no character's file holds it, and it is drawn "
                  "like none of theirs")]
        if any(px):
            facts.append(("Who is drawn", "not said: the game shows this face by its number "
                                          "alone, so naming them would be a judgement by eye"))
    elif w.copy_of is not None:
        facts = [("Of", _character_word(model, c)),
                 ("Same drawing as", f"their portrait {w.copy_of}, all but {w.differ} of "
                                     f"its {fb.SIDE * fb.SIDE} pixels")]
    else:
        facts = [("Of", _character_word(model, c)), ("Which", f"{_which(n)} of their 5")]
    if c is not None and n == fb.member_face(c):
        facts.append(("Shown", "for them in the shop and in the battle menu"))
    lists = [m for m, (_res, block) in faces.lists.items() if block.valid and n in block.faces]
    if lists:
        facts.append(("Copied in", ", ".join(f"portrait list {m}" for m in lists)))
    return CardBody(
        title=portrait_title(model, r) or f"portrait {n}", subtitle="a portrait",
        picture=fb.image(px, faces.colours), facts=facts,
        extended=[("File", f"file {fb.face_file(n)[0]}: resource {resource} ({resource:#x}), "
                           f"picture {picture}"),
                  ("Whose", "a character's file is their number (" + whose.BYTE_LOAD
                            + "); a picture all but " + str(whose.COPY_PIXELS)
                            + " pixels like one of theirs is theirs too (viewer_tabs.whose)"),
                  ("Picture", "64 × 64 at 8 bits, palette row 503 (FaceCellDraw (0x8001B4B0))")],
        proven=[FACE_CELL_SET, "FaceDataLoad (0x8001B1C0)", "FaceImageLoad (0x8001B310)"])


@links.card("portrait-list")
def portrait_list_card(model, r) -> CardBody:
    from PIL import Image
    from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
    n = r.id[0]
    faces = _faces(model)
    if n not in faces.lists:
        raise LookupError(f"there is no portrait list {n}: FaceSlot6Load reads lists 1 to "
                          f"{fb.SCENE_LIMIT - 1}")
    resource, block = faces.lists[n]
    listed = [f for f in block.faces if f] if block.valid else []
    facts = [("Lists", f"{len(listed)} portraits" if listed
              else "none: the game takes it as listing no portrait")]
    picture = None
    if block.images:
        picture = Image.new("RGBA", (fb.SIDE * len(block.images), fb.SIDE), (0, 0, 0, 0))
        for i, px in enumerate(block.images):
            picture.paste(fb.image(px, faces.colours), (i * fb.SIDE, 0))
    return CardBody(
        title=f"portrait list {n}", subtitle="the portraits a scene loads beside the party's",
        picture=picture, facts=facts,
        extended=[("Resource", f"{resource} ({resource:#x}): FaceSlot6Load (0x8001B50C), "
                               f"list + {fb.SCENE_BASE:#x}"),
                  ("Its list", ", ".join(str(f) for f in block.faces)
                   + ("" if block.valid else " — fails FaceDataCheck (0x8001B54C)")),
                  ("Loaded by", "script command 0x3E, ScriptCommandFaceListSet (0x8005E610)")],
        proven=["FaceSlot6Load (0x8001B50C)", FACE_SLOT6_FIND, "FaceDataCheck (0x8001B54C)"])

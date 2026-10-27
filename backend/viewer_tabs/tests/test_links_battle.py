"""Battles, monsters, items, spells and the cast as links and cards
(viewer_tabs.links.battle) — a made-up program image, made-up resources
and made-up names, no game data.

What this CAN catch: a battle linked to its monster set, monster group and
monsters and titled by them, counted; an empty entry (a set that loads
nothing) linking nothing; the boss class from 235 on; a script's BATTLE
command read through its row to the scripted battle and the battle, the
row's own party, and the debug room told apart; a monster's drops tried
as the code tries them (none unless the first is 1 to 164, the second only
beside a first) and its attack and special; who can wear an item (bits of
characters 1 to 12 only), the story flag it sets while worn (+700); who
learns a spell (number 11 with number 1); a shop's stock, shop 8 never
opened; character n's portraits (file n, and a copy of one of theirs in a
file past the characters') and starting equipment; no character past 12; a
portrait list's portraits, none for a list that fails the check; a
portrait's picture; a missing thing's card saying so; and the rows the
tabs claim.

What it CANNOT catch: whether those are the rules of BtlEnemyLoad
(0x8002B3AC), ScriptCommandMapBtlRun (0x8005DFF0), BtlWinItemsGive
(0x80028A54), ChrItemUseGet (0x80058088), ChrLevelUp (0x80028554),
ShopListSet (0x80051768) and FaceCellSet (0x8001B3DC): both sides of every
assertion were written together (the on-disc test opens the real tables).
See decoders/testing.py.
"""

import struct
import threading
import zlib
from types import SimpleNamespace

import pytest

from decoders.plugins.SLUS_006_28.formats import event_script as es
from decoders.plugins.SLUS_006_28.formats import face_blocks as fb
from decoders.plugins.SLUS_006_28.formats import party_init as pi
from decoders.plugins.SLUS_006_28.records import attack_classes as ac
from decoders.plugins.SLUS_006_28.records import encounters as en
from decoders.plugins.SLUS_006_28.records import enemy_templates as et
from decoders.plugins.SLUS_006_28.records import items, shops, spells
from decoders.testing import u16, u32
from viewer_tabs import links
from viewer_tabs.links import battle
from viewer_tabs.model import GameModel
from viewer_tabs.refs import ref
from viewer_tabs.adventure import Listed
from viewer_tabs.tab_providers import (BattlesProvider, ItemsProvider, MagicProvider,
                                       MonstersProvider, PortraitsProvider)

BASE = en.EXE_BASE
#: the image reaches the end of g_ScriptMapBtlRows' 64 rows
IMAGE_END = es.ENCOUNTER_ROWS_ADDR + es.ENCOUNTER_ROW_COUNT * es.ENCOUNTER_ROW_SIZE


def _put(img: bytearray, addr: int, raw: bytes) -> None:
    img[addr - BASE:addr - BASE + len(raw)] = raw


def _row(fields, stride: int, **values) -> bytes:
    """A table row with `values` at the offsets a records module names."""
    raw = bytearray(stride)
    layout = {name: (off, kind) for off, kind, name, _note in fields}
    for name, v in values.items():
        off, kind = layout[name]
        struct.pack_into("<H" if kind == "u16" else "B", raw, off, v)
    return bytes(raw)


def _image() -> bytes:
    img = bytearray(IMAGE_END - BASE)
    # battles: 1 -> set 2, group 3; 2 -> set 4 (no resource), group 3; 240 -> set 2, group 5
    for n, (s, g) in {1: (2, 3), 2: (4, 3), 240: (2, 5)}.items():
        _put(img, en.ENCOUNTER_ADDR + n * 2, bytes([s, g]))
    _put(img, en.SET_RESOURCE_ADDR + 2 * 2, u16(0x150))
    _put(img, en.TYPE_LIST_ADDR + 2 * 4, bytes([7, 9, 0, 0]))
    # group 3: monster 7 twice and 9 once; group 5: monster 9
    _put(img, en.FORMATION_ADDR + 3 * 0x18, bytes([7, 9, 7] + [0] * 5 + [4] * 8 + [16] * 8))
    _put(img, en.FORMATION_ADDR + 5 * 0x18, bytes([9] + [0] * 7 + [30] * 8 + [16] * 8))
    # monsters 7 and 9 and 11
    rows = {7: dict(level=3, hp=20, experience=5, money=8, win_item_1=4, win_rate_1=31,
                    win_item_2=6, win_rate_2=127, attack_number=2, kind7_number=3,
                    attack_count=2),
            9: dict(level=9, hp=99, win_item_1=0xA5, win_rate_1=127, win_item_2=6),
            11: dict(level=1, hp=1, win_item_1=4, win_rate_1=0)}
    for n, values in rows.items():
        _put(img, et.BASE_ADDR + (n - 1) * et.STRIDE, _row(et.FIELDS, et.STRIDE, **values))
    _put(img, ac.BASE_ADDR + 2 * ac.STRIDE, bytes([2, 1, 40, 0, 0, 0, 5, 0]))
    _put(img, ac.BASE_ADDR + 3 * ac.STRIDE, bytes([7, 2, 0, 0, 0, 0, 6, 0]))
    # items: 4 a carried one, 5 worn in place 1 by characters 1, 3 and 12 (bit 15 is
    # no character) and sets story flag 700 + 2 while worn, 6 a carried one
    for n, values in {4: dict(kind=5, price=10, sell_price=5, function_number=3),
                      5: dict(kind=0, price=100, sell_price=50, wearers=0x8805, story_bit=2,
                              target_modes=0x90),
                      6: dict(kind=6, target_modes=0x50)}.items():
        _put(img, items.BASE_ADDR + (n - 1) * items.STRIDE,
             _row(items.FIELDS, items.STRIDE, **values))
    # spells: 3 is number 1's from the start, 4 number 2's at level 7
    for n, values in {3: dict(level=1, chr_id=1, cost=4),
                      4: dict(level=7, chr_id=2, cost=9, area_half_width=1)}.items():
        _put(img, spells.BASE_ADDR + n * spells.STRIDE,
             _row(spells.FIELDS, spells.STRIDE, **values))
    # scripted battles: 1 runs battle 1 with its own party, 2 battle 240 with the field's
    _put(img, es.ENCOUNTER_ROWS_ADDR, bytes([1, 6, 1, 0x0C, 3, 0, 0, 0]))
    _put(img, es.ENCOUNTER_ROWS_ADDR + 8, bytes([240, 0, 0, 0, 0, 0, 0, 0]))
    # shops: 1 sells 4 and 5; 8's row holds 6, but shop 8 never opens
    _put(img, shops.BASE_ADDR, bytes([4, 0, 5, 0, 0, 0]))
    _put(img, shops.BASE_ADDR + 7 * shops.STRIDE, bytes([6, 0, 0, 0, 0, 0]))
    return bytes(img)


def _face_data(images: list[bytes], faces=(), bad_sum=False) -> bytes:
    """Face data around zlib's raw deflate of the pictures, as
    test_face_blocks.py builds it."""
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    stream = co.compress(b"".join(images)) + co.flush()
    stream += b"\0" * (-len(stream) % 4)
    total = sum(struct.unpack(f"<{len(stream) // 4}I", stream)) & 0xFFFFFFFF
    head = b"FACE" + struct.pack("<II", len(stream), total ^ (1 if bad_sum else 0))
    head += b"\0" * 4 + bytes(faces).ljust(fb.LIST_LEN, b"\0") + b"\0" * 6
    return head + stream


def _picture(seed: int) -> bytes:
    return bytes((seed + i) % 7 for i in range(fb.PICTURE_BYTES))


def _resources() -> dict[int, bytes]:
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    words = co.compress(u16(*[0x8000 | k for k in range(256)])) + co.flush()
    words += b"\0" * (-len(words) % 4)
    out = {1: u32(0x30C, len(words)) + words + u32(0)}     # palette row 503
    for file in range(1, fb.FILES + 1):
        out[fb.file_resource(file)] = _face_data([])
    # character 2 has five portraits; file 13 two, the second a copy of
    # character 2's first but for five texels
    out[fb.file_resource(2)] = _face_data([_picture(k) for k in range(5)])
    copy = bytearray(_picture(0))
    for i in range(1700, 1705):
        copy[i] = (copy[i] + 1) % 7
    stripes = bytes((i // fb.SIDE) % 5 + 1 for i in range(fb.PICTURE_BYTES))   # like none
    out[fb.file_resource(13)] = _face_data([stripes, bytes(copy)])
    for n in range(1, fb.SCENE_LIMIT):
        out[fb.scene_resource(n)] = _face_data([])
    out[fb.scene_resource(4)] = _face_data([_picture(1), _picture(2)], faces=(7, 61))
    out[fb.scene_resource(5)] = _face_data([_picture(1)], faces=(8,), bad_sum=True)
    # the new-game party: character 1 starts at level 2 wearing item 5 in place 1
    party = bytearray(pi.PLACE_AT + pi.PLACE_STRIDE * pi.CHAR_LAST)
    struct.pack_into("<HHHH", party, pi.RECORD + 0, 30, 30, 6, 6)
    party[pi.RECORD + 0x1C] = 2
    party[pi.RECORD + 0x2A] = 3
    party[pi.EQUIP_AT] = 5
    out[pi.RESOURCE] = bytes(party)
    return out


class _Names:
    """Made-up names: a letter and the number."""

    def __init__(self, image, resources):
        self.binary = SimpleNamespace(code=image)
        self._resources = resources

    def enemy(self, n):
        return f"M{n}" if n in (7, 9) else None

    def item(self, n):
        return f"I{n}"

    def item_description(self, n):
        return f"about I{n}"

    def spell(self, n):
        return f"S{n}"

    def spell_description(self, n):
        return None

    def enemy_special(self, n):
        return f"A{n}"

    def character(self, n):
        return f"C{n}"

    def map_name(self, m):
        return f"P{m}"

    def read_resource(self, n):
        return self._resources[n]


def _script() -> tuple[bytes, dict, dict]:
    buf = bytes(8) + bytes([es.BATTLE, 0]) + u16(5) + bytes([1, 0, 9, 0xFF])
    return buf, {8: es.Command(8, es.BATTLE, 16)}, {}


def _debug_script() -> tuple[bytes, dict, dict]:
    buf = bytes([es.BATTLE, 0]) + u16(0) + bytes([2, 0, 0, 0xFF])
    return buf, {0: es.Command(0, es.BATTLE, 8)}, {}


class _Model:
    kept = GameModel.kept                       # its parts kept as a disc's are

    def __init__(self):
        self.lock = threading.RLock()
        self.twin = self
        self.ctx = SimpleNamespace(program="SLUS_006.28")
        self.names = _Names(_image(), _resources())
        scripts = {7: _script, 9: _debug_script}
        self.field = SimpleNamespace(script_resources={7: 0x300, 9: 0x301},
                                     script=lambda sid: scripts[sid](),
                                     script_maps={7: {21}}, debug_scripts={9})
        self.fights = SimpleNamespace(monsters={1: {21, 22}})
        self.__dict__["_link_index"] = links.LinkIndex(self, [
            battle.battle_edges, battle.scripted_battle_edges, battle.monster_edges,
            battle.goods_edges, battle.cast_edges])

    def need_names(self):
        return self.names


@pytest.fixture(scope="module")
def model():
    return _Model()


def _out(model, r) -> dict[str, list]:
    index = links.LinkIndex.of(model)
    found: dict[str, list] = {}
    for e in index.out.get(r, []):
        found.setdefault(e.rel, []).append((e.to, e.note))
    return found


def _into(model, r) -> dict[str, list]:
    index = links.LinkIndex.of(model)
    found: dict[str, list] = {}
    for e in index.into.get(r, []):
        found.setdefault(e.back, []).append(e.frm)
    return found


def _card(model, r) -> dict:
    return links.build_card(model, r, lambda picture: "stored")


def _facts(card) -> dict:
    return dict(card["facts"])


def test_the_index_reads_every_part(model):
    assert links.LinkIndex.of(model).errors == []


def test_a_battle_links_its_monster_set_group_and_monsters_and_is_titled_by_them(model):
    out = _out(model, ref("battle", 1))
    assert out["Monster set"] == [(ref("monster-set", 2), "")]
    assert out["Monster group"] == [(ref("monster-group", 3), "")]
    assert [to for to, _n in out["Monsters"]] == [ref("monster", 7), ref("monster", 9)]
    assert links.title_of(model, ref("battle", 1)) == "M7 ×2, M9"
    assert _out(model, ref("monster-group", 3))["Monsters"] == [
        (ref("monster", 7), "×2"), (ref("monster", 9), "")]
    assert [to for to, _n in _out(model, ref("monster-set", 2))["Draws"]] == [
        ref("monster", 7), ref("monster", 9)]
    card = _card(model, ref("battle", 1))
    assert card["error"] == "" and card["subtitle"] == "a fight"
    facts = _facts(card)
    assert facts["Monsters"] == "M7 ×2, M9"
    assert facts["Started by a scene"] == "script 7 (P21)"
    assert facts["Met on the field"] == "touching a monster on P21, P22"
    assert "Boss fight" not in facts


def test_an_empty_entry_links_nothing_and_says_so(model):
    assert _out(model, ref("battle", 2)) == {}
    assert links.title_of(model, ref("battle", 2)) == "battle 2"
    card = _card(model, ref("battle", 2))
    assert card["error"] == ""
    assert _facts(card)["Monsters"].startswith("none")


def test_a_battle_from_235_on_is_a_boss_fight(model):
    card = _card(model, ref("battle", 240))
    assert card["subtitle"] == "a boss fight" and "Boss fight" in _facts(card)
    assert "In the debug room" in _facts(card)
    assert battle.BOSS_CHECK in card["proven"]


def test_a_script_starts_scripted_battles_and_their_battles(model):
    out = _out(model, ref("script", 7))
    assert out["Scripted battles"] == [(ref("scripted-battle", 1), "its BATTLE command")]
    assert out["Battles"] == [(ref("battle", 1), "through scripted battle 1")]
    assert _into(model, ref("battle", 240))["Started by"] == [ref("script", 9)]
    sb = _out(model, ref("scripted-battle", 1))
    assert sb["Battle"] == [(ref("battle", 1), "")]
    assert [to for to, _n in sb["Party"]] == [ref("character", 1), ref("character", 12),
                                             ref("character", 3)]
    assert "Party" not in _out(model, ref("scripted-battle", 2))
    assert _facts(_card(model, ref("scripted-battle", 2)))["Party"] == "the party of the moment"


def test_a_script_that_cannot_be_read_is_passed_over(model):
    m = _Model()
    read = m.field.script

    def script(sid):
        if sid == 8:
            raise ValueError("a made-up script that cannot be read")
        return read(sid)
    m.field = SimpleNamespace(**{**vars(m.field), "script": script,
                                 "script_resources": {7: 0x300, 8: 0x302, 9: 0x301}})
    starts = battle._read_starts(m)
    assert starts == battle._read_starts(model) and starts


def test_a_monster_drops_as_the_win_tries_and_uses_its_attacks(model):
    out = _out(model, ref("monster", 7))
    assert out["Drops"] == [(ref("item", 4), "25%"),
                            (ref("item", 6), "100% when the first is not given")]
    assert out["Attacks"] == [(ref("monster-attack", 2), "its attack"),
                              (ref("monster-attack", 3), "its special")]
    # a first item above 164: neither is tried
    assert "Drops" not in _out(model, ref("monster", 9))
    assert _out(model, ref("monster", 11))["Drops"] == [(ref("item", 4), "0.8%")]
    card = _card(model, ref("monster", 7))
    assert card["error"] == "" and card["title"] == "M7"
    facts = _facts(card)
    assert facts["Level"] == "3" and facts["HP"] == "20" and facts["Hits"] == "2 times an attack"
    assert facts["Fought in"] == "1 battle"           # battle 2 loads nothing
    assert _facts(_card(model, ref("monster", 9)))["Fought in"] == "2 battles"
    assert _facts(_card(model, ref("monster", 9)))["Drops"] == "nothing"
    assert _into(model, ref("monster-attack", 2))["Used by"] == [ref("monster", 7)]
    assert _card(model, ref("monster-attack", 2))["title"] == "A2"


def test_who_can_wear_an_item_and_the_story_flag_it_sets(model):
    out = _out(model, ref("item", 5))
    assert [to for to, _n in out["Worn by"]] == [ref("character", 1), ref("character", 3),
                                                ref("character", 12)]
    assert out["While worn"] == [(ref("story-flag", 702), "set while it is worn"),
                                 (ref("story-flag", 702), "cleared when it is taken off")]
    worn = next(g for g in _card(model, ref("item", 5))["groups"] if g["title"] == "While worn")
    assert [link["note"] for link in worn["links"]] == \
        ["set while it is worn; cleared when it is taken off"]
    facts = _facts(_card(model, ref("item", 5)))
    assert facts["What it is"] == "equipment, worn in place 1"
    assert facts["Price"] == "100" and facts["Sells for"] == "50"
    assert facts["Used"] == "no"
    assert facts["What it says"] == "about I5"
    six = _facts(_card(model, ref("item", 6)))
    assert six["What it is"] == "an item to carry, which cannot be given up"
    assert six["Sells for"].startswith("nothing")
    assert _facts(_card(model, ref("item", 4)))["Used"] == "in battle and from the menu"


def test_who_learns_a_spell_number_11_with_number_1(model):
    assert _out(model, ref("spell", 3))["Learned by"] == [
        (ref("character", 1), "from the start"), (ref("character", 11), "from the start")]
    assert _out(model, ref("spell", 4))["Learned by"] == [(ref("character", 2), "at level 7")]
    facts = _facts(_card(model, ref("spell", 4)))
    assert facts["Costs"] == "9 MP" and facts["Area"] == "3 × 1 cells"


def test_a_shop_sells_its_stock_and_shop_8_never_opens(model):
    assert [to for to, _n in _out(model, ref("shop", 1))["Sells"]] == [ref("item", 4),
                                                                      ref("item", 5)]
    assert _out(model, ref("shop", 8)) == {}
    assert _facts(_card(model, ref("shop", 8)))["Opens"].startswith("never")


def test_a_character_has_file_ns_portraits_their_copies_and_starting_equipment(model):
    out = _out(model, ref("character", 2))
    assert [to for to, _n in out["Portraits"]] == [ref("portrait", p)
                                                   for p in (6, 7, 8, 9, 10, 62)]
    # the title says which of the five; a copy says what it copies
    assert [note for _to, note in out["Portraits"]] == [""] * 5 + [
        "the same drawing as portrait 6"]
    assert _facts(_card(model, ref("character", 2)))["Also drawn as"] == (
        "portrait 62, a copy of their portrait 6")
    assert _out(model, ref("character", 1))["Starts wearing"] == [(ref("item", 5), "place 1")]
    card = _card(model, ref("character", 1))
    assert card["title"] == "C1" and _facts(card)["Starting level"] == "2"
    assert _facts(card)["Magic from the start"] == "S3"


def test_no_character_past_the_partys_numbers(model):
    assert "Portraits" not in _out(model, ref("character", 13))
    assert "there is no character 13" in _card(model, ref("character", 13))["error"]


def test_a_portrait_shows_its_face_and_a_list_its_portraits(model):
    card = _card(model, ref("portrait", 7))
    assert card["error"] == "" and card["title"] == "C2, portrait 2 of 5"
    assert "picture" in card and (card["picture"]["w"], card["picture"]["h"]) == (64, 64)
    assert _facts(card)["Copied in"] == "portrait list 4"
    assert links.title_of(model, ref("portrait", 61)) == "portrait 61"
    assert _facts(_card(model, ref("portrait", 61)))["Of"].startswith("no one the game names")
    assert _facts(_card(model, ref("portrait", 61)))["Who is drawn"].startswith("not said")
    assert "Who is drawn" not in _facts(_card(model, ref("portrait", 62)))
    assert links.title_of(model, ref("portrait", 62)) == "C2, portrait 62, a copy"
    assert _facts(_card(model, ref("portrait", 62)))["Same drawing as"] == (
        "their portrait 6, all but 5 of its 4096 pixels")
    assert [to for to, _n in _out(model, ref("portrait-list", 4))["Portraits"]] == [
        ref("portrait", 7), ref("portrait", 61)]
    # data that fails the check lists no portrait
    assert _out(model, ref("portrait-list", 5)) == {}
    assert _card(model, ref("portrait-list", 4))["picture"]["w"] == 2 * fb.SIDE


@pytest.mark.parametrize("r", [ref("battle", 256), ref("monster", 3), ref("item", 9),
                               ref("spell", 9), ref("monster-attack", 9),
                               ref("monster-set", 4), ref("scripted-battle", 3),
                               ref("character", 13), ref("portrait", 1),
                               ref("portrait-list", 43), ref("shop", 41)])
def test_a_thing_that_is_not_there_says_so(model, r):
    assert _card(model, r)["error"].startswith(f"Could not read {r.kind.replace('-', ' ')}")


def test_the_tabs_claim_the_rows_that_are_their_homes():
    assert BattlesProvider.holds(("enc", 46, False), ref("battle", 46), None)
    assert not BattlesProvider.holds(("enc", 45, False), ref("battle", 46), None)
    assert BattlesProvider.holds(("set", 12), ref("monster-set", 12), None)
    assert not BattlesProvider.holds(("set", 12, 0), ref("monster-set", 12), None)
    assert ItemsProvider.holds(Listed(ref("item", 3)), ref("item", 3), None)
    assert ItemsProvider.holds(Listed(ref("chest", 21, 3), "P21"), ref("chest", 21, 3), None)
    assert not ItemsProvider.holds(Listed(ref("item", 3)), ref("shop", 3), None)
    assert MagicProvider.holds(Listed(ref("spell", 3), "C1"), ref("spell", 3), None)
    assert MonstersProvider.holds(Listed(ref("monster", 3)), ref("monster", 3), None)
    assert not MonstersProvider.holds(Listed(ref("monster", 3)), ref("monster-attack", 3), None)
    assert PortraitsProvider.holds(("face", 7), ref("portrait", 7), None)
    assert PortraitsProvider.holds(("face", 7, "C2", "a note"), ref("portrait", 7), None)
    assert not PortraitsProvider.holds(("face", 6), ref("character", 2), None)
    assert not PortraitsProvider.holds(("atlas",), ref("portrait", 1), None)
    assert PortraitsProvider.holds(("scene", (5, 0xBF, None, [])), ref("portrait-list", 5), None)
    for prov in (BattlesProvider, PortraitsProvider, ItemsProvider, MagicProvider,
                 MonstersProvider):
        for kind, views in prov.homes.items():
            assert set(views) <= (set(prov.VIEWS) or {None}), (prov.name, kind)

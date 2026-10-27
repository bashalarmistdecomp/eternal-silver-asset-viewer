"""The Items, Magic and Monsters tabs' lists and pages
(viewer_tabs.adventure) — the made-up program of test_links_battle, with
made-up maps, chests and shop openings; no game data.

What this CAN catch: a list's rows, order and groups (items in the
table's order; equipment by the place it is worn in; shops under the
first place whose map opens them, the debug room's, other scripts', no
script's and the one that never opens after; chests by the place of their
map, the debug room's last, one that runs a scene left out; spells under who learns them, number 1's
naming number 11 too; monsters and attacks in their tables' order), a
page laid out as its card with the tab's own sections and the facts and
links they already say left out, a shop's stock and a stock not located, where a
monster is met with the debug room last, and the tabs listing what their
views say.

What it CANNOT catch: whether the code groups them so (the on-disc tabs
test opens the real tables): both sides of every assertion were written
together. See decoders/testing.py.
"""

from types import SimpleNamespace

import pytest

from viewer_tabs import adventure
from viewer_tabs.field_view import DEBUG_ROOM
from viewer_tabs.links import battle
from viewer_tabs.refs import ref
from viewer_tabs.tab_providers import ItemsProvider, MagicProvider, MonstersProvider
from viewer_tabs.tests.test_links_battle import _Model


def _chest(event: int, facing: int = 4):
    """A kind-7 definition: facing 5 and up (stored less 1) is a shut chest."""
    return SimpleNamespace(kind=7, facing=facing, event=event)


class _World:
    """Made-up maps: object set 3 is shown on map 21, set 4 on 22, set 5 on
    the debug room's."""
    set_maps = {3: [21], 4: [22], 5: [DEBUG_ROOM]}

    def home_map(self, s):
        return self.set_maps[s][0]

    def map_title(self, m):
        return f"P{m}"

    def definitions(self, s):
        return {3: {1: _chest(4), 2: SimpleNamespace(kind=1, facing=0, event=0)},
                4: {0: _chest(0xB8), 1: _chest(0), 2: _chest(0xF2)},
                5: {7: _chest(5)}}[s]

    def amounts(self):
        return (0, 250)


class _AdventureModel(_Model):
    def __init__(self):
        super().__init__()
        # scripts 7 (map 21's) opens shop 1, 9 (the debug room's) shop 2, and
        # 12 (no map's own) shop 3
        self.field.script_maps = {7: {21}, 8: {22}}
        self.field.maps = dict.fromkeys((21, 22, DEBUG_ROOM))
        self.__dict__["_shop_runs"] = {1: [(7, 0x10)], 2: [(9, 0)], 3: [(12, 4)]}
        self.__dict__["_world"] = _World()
        # battle 1 (monsters 7, 9) is started by map 22's map monsters and by
        # the debug room's script 9; battle 240 (monster 9) by map 21's script
        self.fights = SimpleNamespace(monsters={1: {22}}, scripts={1: [(9, 0)], 240: [(7, 0)]})


@pytest.fixture(scope="module")
def model():
    return _AdventureModel()


def _rows(listed):
    return [(lab.split("  ")[0], it.ref, it.group) for lab, it in listed]


def test_items_are_in_the_tables_order_and_equipment_by_where_it_is_worn(model):
    assert [r for _t, r, _g in _rows(adventure.items(model))] == [ref("item", n)
                                                                  for n in (4, 5, 6)]
    labels = [lab for lab, _it in adventure.items(model)]
    assert labels[1] == "I5  item 5  worn in place 1"
    assert labels[2].endswith("carried, never given up")
    assert _rows(adventure.equipment(model)) == [("I5", ref("item", 5), "Worn in place 1")]


def test_shops_come_under_the_place_that_opens_them(model):
    rows = _rows(adventure.shops(model))
    assert [(r.id[0], g) for _t, r, g in rows] == [
        (1, "P21"), (2, "The debug room"), (3, "Opened by other scripts")] + [
        (n, "Opened by no script") for n in range(4, 41) if n != 8] + [(8, "Never opens")]
    assert adventure.shops(model)[0][0] == "shop 1  2 items: I4, I5"


def test_chests_come_under_their_maps_place_the_debug_rooms_last(model):
    # one that runs a scene (byte 0xB 0xF0 up) is left out
    rows = _rows(adventure.treasure(model))
    assert rows == [("I4", ref("chest", 3, 1), "P21"),
                    ("250 money", ref("chest", 4, 0), "P22"),
                    ("nothing", ref("chest", 4, 1), "P22"),
                    ("I5", ref("chest", 5, 7), f"P{DEBUG_ROOM} (the debug room)")]


def test_spells_come_under_who_learns_them(model):
    rows = _rows(adventure.magic(model))
    assert rows == [("S3", ref("spell", 3), "C1 (characters 1 and 11)"),
                    ("S4", ref("spell", 4), "C2")]


def test_monsters_and_attacks_are_in_their_tables_order(model):
    assert [r.id[0] for _t, r, _g in _rows(adventure.monsters(model))] == [7, 9, 11]
    attacks = adventure.attacks(model)
    assert [it.ref.id[0] for _lab, it in attacks] == [2, 3]
    assert attacks[0][0] == "A2  monster attack 2  used by M7"


def test_a_page_is_its_card_with_the_tabs_sections(model):
    sheet = adventure.page(model, ref("item", 5))
    assert sheet["title"] == "I5" and sheet["badges"][0]["text"] == "item 5"
    titles = [s["title"] for s in sheet["sections"]]
    assert titles == ["About", adventure.LINKS, adventure.EXTENDED]
    about = dict(map(tuple, sheet["sections"][0]["fields"]))
    assert about["Worn by"] == "C1, C3, C12"
    extended = sheet["sections"][-1]
    assert extended["extended"] and extended["fields"][0][0] == "The code's name"
    # a section that says a fact and a link group already leaves them out
    page = adventure.page(model, ref("shop", 1), [adventure.shop_stock(model, 1)], ("Sells",))
    assert "Sells" not in [g["title"] for s in page["sections"] for g in s.get("links", ())]
    assert "Sells" not in [k for k, _v in page["sections"][0]["fields"]]


def test_a_shops_stock_and_one_not_located(model):
    stock = adventure.shop_stock(model, 1)
    # the made-up resources draw no icon: the items are listed in words
    assert stock["list"] == ["I4 · 10", "I5 · 100"] and stock["pictures"] == []
    assert adventure.shop_stock(model, 2)["note"] == "It sells nothing."
    blind = SimpleNamespace(**{**battle._tables(model).__dict__, "shops": None})
    jp = _AdventureModel()
    jp.__dict__["_battle_tables"] = blind
    assert "not located" in adventure.shop_stock(jp, 1)["verdict"]["text"]


def test_where_a_monster_is_met_the_debug_room_last(model):
    met = adventure.where_met(model, 9)
    assert [(g["title"], [link["ref"]["id"] for link in g["links"]]) for g in met["links"]] == [
        ("P21", [[240]]), ("P22", [[1]]), (f"P{DEBUG_ROOM} (the debug room)", [[1]])]
    assert met["links"][1]["links"][0]["note"] == "a map monster starts it"
    assert "No battle" in adventure.where_met(model, 11)["note"]


def test_the_tabs_list_what_their_views_say():
    for prov in (ItemsProvider, MagicProvider, MonstersProvider):
        assert set(prov.LISTS) == (set(prov.VIEWS) or {None}), prov.name
        assert all(hasattr(adventure, fn) for fn in prov.LISTS.values()), prov.name


def test_the_menus_words_name_the_stats_they_label():
    words = _AdventureModel()
    words.names.strings = SimpleNamespace(text=lambda n: f"W{n:x}")
    assert battle.stat_word(words, "stat_08") == "W619"
    assert battle.stat_word(words, "attack_count") == "W61e"
    assert battle.stat_word(words, "walk_reach") == "W620"
    assert battle.stat_word(words, "trait") == "trait"          # no menu word: the code's
    assert battle.kind_word(words, 7) == "W61f" and battle.kind_word(words, 9) == "kind 9"
    sheet = adventure.page(words, ref("monster", 7))
    about = dict(map(tuple, sheet["sections"][0]["fields"]))
    assert {"W619", "W61a", "W61b", "W61c", "W61d", "W620"} <= set(about)
    # without the strings, the code's names
    assert battle.stat_word(_AdventureModel(), "stat_0a") == "stat_0a"

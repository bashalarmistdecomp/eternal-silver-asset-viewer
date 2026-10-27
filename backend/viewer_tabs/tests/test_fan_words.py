"""Fan mode speaks a fan's words (docs/taxonomy.md, "The rule"): what the
tabs give it beside their technical words, on made-up data.

- a link says when its kind's home is only in Advanced mode, and the
  debug room's things are listed after the rest;
- the tabs a fan sees say what they hold in plain words (`fan_about`);
- a row, a page's section, a text and a clip have their plain words beside
  the technical ones, which stay for Advanced mode.
"""

import io
import wave
from types import SimpleNamespace

import pytest

from viewer_server.present import present, tab_meta
from viewer_tabs import links, scene
from viewer_tabs.field_view import DEBUG_ROOM
from viewer_tabs.links import Edge, world
from viewer_tabs.names import MapEntry
from viewer_tabs.refs import ref
from viewer_tabs.tab_providers import (
    PROVIDER_CLASSES, DialogueProvider, MenusProvider, MoviesProvider, SelectResult,
    UIItem, _enemy_summary,
)
from viewer_tabs.tests.test_links_world import _area, _model

#: The tabs of Fan mode's rail (app/src/lib/tabs.ts): each says what it
#: holds in a fan's words.
FAN_TABS = ("maps", "characters", "monsters", "portraits", "sprites", "dialogue", "movies",
            "items", "magic", "battles", "music", "voices", "sound-effects", "bromides",
            "menus", "screens", "story-flags")


# -- links ---------------------------------------------------------------------

def _with_debug_room():
    """The made-up world, with the debug room: its map runs script 6."""
    model = _model()
    model.field.maps[DEBUG_ROOM] = MapEntry(DEBUG_ROOM, 109, _area(DEBUG_ROOM, 2, 6))
    return model


def test_the_debug_rooms_things_are_listed_last():
    model = _with_debug_room()
    assert links.is_last(model, ref("map", DEBUG_ROOM))
    assert links.is_last(model, ref("script", 6))          # the room's own script
    assert not links.is_last(model, ref("map", 10))
    assert not links.is_last(model, ref("script", 5))
    assert not links.is_last(model, ref("item", 18))


def test_a_group_lists_the_debug_room_after_the_rest():
    model = _with_debug_room()
    song = ref("song", 3)

    def edges(_model):
        yield Edge(ref("map", DEBUG_ROOM), song, "Music", "Played on")
        yield Edge(ref("map", 10), song, "Music", "Played on")
        yield Edge(ref("map", 11), song, "Music", "Played on")

    index = links.LinkIndex(model, sources=[edges])
    (group,) = links.groups(model, index, song)
    assert [link["ref"]["id"][0] for link in group["links"]] == [10, 11, DEBUG_ROOM]


def test_world_places_name_the_debug_room_last():
    model = _with_debug_room()
    w = world._world(model)
    assert w.places([DEBUG_ROOM, 10]).split(", ")[0] == w.map_title(10)


def test_a_link_says_when_only_advanced_mode_has_its_home():
    model = _model()
    assert links.link_json(model, ref("resource", 5))["advanced"] is True
    assert links.link_json(model, ref("map", 10))["advanced"] is False


# -- the tabs' words -----------------------------------------------------------

@pytest.mark.parametrize("key", FAN_TABS)
def test_every_fan_tab_says_what_it_holds_plainly(key):
    cls = next(c for c in PROVIDER_CLASSES if c.key == key)
    about = tab_meta(0, cls())["fanAbout"]
    assert about, f"{key} has no fan_about"
    assert "0x" not in about and "(0x" not in about
    assert about != tab_meta(0, cls())["about"]


def test_a_tab_without_fan_words_gives_none():
    class Plain:
        """How it is done."""
        name, key = "Plain", "plain"
        supports_zoom = supports_grid = supports_layers = False
    assert tab_meta(0, Plain())["fanAbout"] == ""


def test_the_census_names_every_anim_for_a_fan():
    from decoders.plugins.SLUS_006_28.formats import battle_gfx as bg
    named = {name for table in (bg.ENEMY_ANIMS, bg.PARTY_ANIMS) for name, _proof in table.values()}
    missing = sorted(n for n in named if n not in scene.FAN_ANIM_WORDS)
    assert not missing, missing
    assert not any("0x" in w or "&" in w for w in scene.FAN_ANIM_WORDS.values())


def test_a_monster_group_counts_with_the_sign_asked_for():
    name = {1: "Abc", 2: "Def"}.get
    assert _enemy_summary([1, 1, 2], name) == "2x Abc, Def"
    assert _enemy_summary([1, 1, 2], name, "×") == "2× Abc, Def"


# -- rows ----------------------------------------------------------------------

def test_menus_rows_say_what_they_are():
    p = MenusProvider()

    def row(label, key):
        return p.fan_row(label, UIItem([], [], "", key=key), None)

    assert row("SYSTEM.DAT  icons  64", "SYSTEM.DAT icons") == {
        "title": "The icons", "sub": "64 icons the menus draw"}
    assert row("  icon 5  Made-up", "icon 0x05") == {"title": "Made-up", "sub": "icon 5"}
    assert row("  icon 0  never drawn", "icon 0x00") == {"sub": "never drawn"}
    assert row("OPEN1.BIN [2]", "OPEN1.BIN 2") == {"title": "The title screen",
                                                   "sub": "picture 3"}
    assert row("MENU.BIN  the movie player's code", "MENU.BIN")["title"] == "The movie player"
    assert row("SOMETHING.DAT", "SOMETHING.DAT") is None
    for key, (title, sub) in MenusProvider.FAN_WORDS.items():
        assert "0x" not in title and "0x" not in (sub or ""), key


def test_a_movie_row_says_how_long_it_plays(monkeypatch):
    p = MoviesProvider()
    monkeypatch.setattr(p, "_probe", lambda path: {"mdec": True, "sectors": 150 * 83})
    ctx = SimpleNamespace(program="NOT_A_KNOWN_PROGRAM")
    assert p.fan_row("A.STR  224x192  (1.0MB)", ("A.STR", None), ctx) == {"sub": "about 1:23"}


def _message(offset, text, answers=None):
    said = [] if answers else [SimpleNamespace(faces=[1], text=text)]
    return SimpleNamespace(label=7, offset=offset, answers=answers, said=said)


def test_dialogue_reads_without_offsets_in_fan_mode(monkeypatch):
    p = DialogueProvider()
    monkeypatch.setattr(p, "_who", lambda faces, short=False: "Someone")
    msgs = [_message(0x1A2B, "Line one\nLine two"), _message(0x1A40, "", ("Yes", "No"))]
    technical = "\n".join(p._text(msgs))
    plain = "\n".join(p._text(msgs, offsets=False))
    assert "1A2B" in technical and "1A40" in technical
    assert "1A2B" not in plain and "1A40" not in plain
    assert plain.split("\n") == ["Label 7", "  Someone", "    Line one", "    Line two",
                                 "  answers: Yes  /  No"]


# -- what a selection gives ----------------------------------------------------

class _Store:
    def put_bytes(self, data, mime):
        return mime


def _wav() -> bytes:
    """A made-up clip: ten silent frames."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 10)
    return out.getvalue()


def test_present_passes_the_plain_text_and_the_clips_title():
    provider = SimpleNamespace(supports_layers=False)
    vm, _layers = present(SelectResult(text="  1A2B  Someone", fan_text="  Someone",
                                       audio={"wav": _wav(), "name": "voice-1",
                                              "title": "Made-up words"}),
                          provider, _Store())
    assert vm["text"] == "  1A2B  Someone" and vm["fanText"] == "  Someone"
    assert vm["audio"]["title"] == "Made-up words"


def test_present_gives_no_plain_text_where_there_is_none():
    vm, _layers = present(SelectResult(text="some text"), SimpleNamespace(supports_layers=False),
                          _Store())
    assert "fanText" not in vm


def test_a_label_no_one_runs_is_titled_by_where_its_script_runs():
    """A scene's label reads by its places, not as the code numbers it
    (the reference follows it in a link)."""
    from viewer_tabs.links import story
    model = _model()
    assert story.label_title(model, ref("label", 5, 800)) == "a scene on Place A, Place B"
    assert links.title_of(model, ref("label", 5, 800)).startswith("a scene on ")

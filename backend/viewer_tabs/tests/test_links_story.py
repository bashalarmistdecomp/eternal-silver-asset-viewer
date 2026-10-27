"""Who speaks where (viewer_tabs.links.story) — made-up messages, no game data.

What this CAN catch: a message counted for a character whose portrait is
not in it, a message counted twice for someone whose portrait comes up
twice, an opening given to a message whose first run shows two portraits
or none, two portraits no character is counted as one speaker, and the
presenter losing a page's pictures.

What it CANNOT catch: whether the messages are read as the game shows them
(test_messages_on_disc) or whether a portrait is the speaker's.
"""

from types import SimpleNamespace

from PIL import Image

from viewer_server.present import _sheet
from viewer_tabs.links.story import count_spoken
from viewer_tabs.refs import ref


def _msg(*runs):
    """A message whose runs show these portraits: each run [(place, portrait)]."""
    return SimpleNamespace(said=[SimpleNamespace(faces=list(r)) for r in runs])


def _character(p: int):
    """As whose.speaker names a made-up portrait: 1-60 the characters'
    files, the rest no one's."""
    return ref("character", (p - 1) // 5 + 1) if p <= 60 else ref("portrait", p)


C1, C2, C3 = ref("character", 1), ref("character", 2), ref("character", 3)


def test_a_message_counts_once_for_each_character_whose_portrait_comes_up():
    spoken = count_spoken({7: [_msg([(0, 1)], [(0, 3), (1, 6)]),     # characters 1 and 2
                               _msg([(0, 6)]),                        # 2 opens
                               _msg([(0, 1), (1, 11)]),               # 1 and 3, nobody opens
                               _msg()],                               # no portrait
                           9: [_msg([], [(0, 2)])]},                  # 1, after a bare run
                          _character)
    assert dict(spoken[C1].shown) == {7: 2, 9: 1} and dict(spoken[C1].opens) == {7: 1}
    assert dict(spoken[C2].shown) == {7: 2} and dict(spoken[C2].opens) == {7: 1}
    assert dict(spoken[C3].shown) == {7: 1} and not spoken[C3].opens
    assert spoken[C1].messages == 3


def test_each_portrait_no_character_is_speaks_for_itself():
    spoken = count_spoken({4: [_msg([(0, 91)]), _msg([(0, 92)]), _msg([(0, 91), (1, 1)])]},
                          _character)
    p91, p92 = ref("portrait", 91), ref("portrait", 92)
    assert set(spoken) == {p91, p92, C1}
    assert dict(spoken[p91].shown) == {4: 2} and dict(spoken[p91].opens) == {4: 1}
    assert dict(spoken[p92].shown) == {4: 1}


def test_a_page_s_pictures_go_to_the_store():
    put = []
    store = SimpleNamespace(put_image=lambda im: put.append(im) or f"b{len(put)}")
    pic = Image.new("RGBA", (4, 3))
    sheet = {"title": "t", "sections": [{"title": "a"},
                                        {"title": "b", "pictures": [
                                            {"image": pic, "caption": "c", "ref": ref("portrait", 6)},
                                            {"image": pic}]}]}
    out = _sheet(sheet, store)
    assert out["sections"][0] == {"title": "a"} and len(put) == 2
    assert out["sections"][1]["pictures"] == [
        {"blob": "b1", "w": 4, "h": 3, "caption": "c", "ref": {"kind": "portrait", "id": [6]}},
        {"blob": "b2", "w": 4, "h": 3, "caption": None, "ref": None}]
    assert sheet["sections"][1]["pictures"][0]["image"] is pic      # the provider's page is kept


def test_a_message_title_keeps_its_first_words():
    from viewer_tabs.links.story import TITLE_CHARS, _first_words
    short = _msg()
    short.said = [SimpleNamespace(faces=[], text="  \n"), SimpleNamespace(faces=[], text="Abc\n de")]
    assert _first_words(short) == "Abc de"
    long = _msg()
    long.said = [SimpleNamespace(faces=[], text="x" * (TITLE_CHARS + 5))]
    words = _first_words(long)
    assert len(words) == TITLE_CHARS and words.endswith("…")
    assert _first_words(_msg()) == ""

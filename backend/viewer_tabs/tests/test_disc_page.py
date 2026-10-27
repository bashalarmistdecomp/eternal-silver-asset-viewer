"""The Disc tab (one page per disc, named for its disc image) and the
Disc Files tab's page for a file."""

import json

from decoders.psx.gamedb.database import InstalledGame
from viewer_tabs.context import DiscContext
from viewer_tabs.tab_providers import DiscFilesProvider, DiscProvider


def _ctx(tmp_path, source=None, recorded=None, label="Made-up Game (SLUS_999.99)"):
    dump = tmp_path / "dump"
    dump.mkdir()
    (dump / "SYSTEM.CNF").write_text("BOOT = cdrom:\\SLUS_999.99;1\n")
    if recorded is not None:
        (dump / "meta.json").write_text(json.dumps({"source": recorded}))
    return DiscContext.for_game(InstalledGame(
        disc_id="SLUS_999.99", title="Made-up Game", region="USA", path=dump,
        has_lunadata=False, source=source, program="SLUS_999.99",
        label=label))


def test_a_disc_is_named_for_its_image(tmp_path):
    image = tmp_path / "Made-up Game (USA) (Disc 1).cue"
    image.write_text("")
    assert _ctx(tmp_path, source=image).image_name == "Made-up Game (USA) (Disc 1)"


def test_a_moved_image_keeps_the_name_recorded_at_extraction(tmp_path):
    ctx = _ctx(tmp_path, recorded="/gone/Made-up Game (USA) (Disc 2).cue")
    assert ctx.image_name == "Made-up Game (USA) (Disc 2)"


def test_a_disc_with_no_image_on_record_goes_by_its_label(tmp_path):
    assert _ctx(tmp_path).image_name == "Made-up Game (SLUS_999.99)"


def test_one_page_says_who_the_disc_is_and_what_can_read_it(tmp_path):
    image = tmp_path / "Made-up Game (USA).cue"
    image.write_text("")
    ctx = _ctx(tmp_path, source=image)
    prov = DiscProvider()
    items = prov.get_items({}, None, ctx, None)
    assert [label for label, _ in items] == ["Made-up Game (USA)"]
    sheet = prov.on_select(items[0][1], {}, None, ctx).sheet
    assert (sheet["title"], sheet["subtitle"]) == ("Made-up Game (USA)", "Made-up Game")
    sections = {s["title"]: s for s in sheet["sections"]}
    assert list(sections) == ["Identity", "What can be read", "Library folder"]
    assert ["Disc serial", "SLUS_999.99", ""] in sections["Identity"]["fields"]
    readable = sections["What can be read"]
    assert readable["fields"][0][1:] == ["—", "none for this program"]
    chips = {c["label"]: c for c in readable["chips"]}
    assert not chips["Dialogue"]["on"] and chips["Dialogue"]["why"]
    assert readable["aside"] == f"{sum(c['on'] for c in chips.values())} of {len(chips)} tabs"


def test_the_plugin_named_is_the_one_that_serves_the_program(tmp_path):
    jp = DiscContext.for_game(InstalledGame(
        disc_id="SLPS_013.97", title="Made-up Game", region="Japan", path=tmp_path,
        has_lunadata=False, program="SLPS_013.97", label="Made-up Game"))
    readable = DiscProvider()._capability_section(jp)
    assert readable["fields"][0][1:] == ["decoders.plugins.SLUS_006_28", ""]     # COMPAT's


def test_how_the_disc_was_identified_is_the_first_badge(tmp_path):
    badge = DiscProvider().on_select("disc", {}, None, _ctx(tmp_path)).sheet["badges"][0]
    assert (badge["text"], badge["tone"]) == ("not in gamedb", "danger")


def test_a_files_page_gives_its_size_type_and_first_bytes(tmp_path):
    ctx = _ctx(tmp_path)
    (ctx.data_dir / "MADEUP.BIN").write_bytes(b"made-up bytes\0" * 30)
    prov = DiscFilesProvider()
    items = dict((data[0], data) for _, data in prov.get_items({}, None, ctx, None))
    sheet = prov.on_select(items["MADEUP.BIN"], {}, None, ctx).sheet
    assert (sheet["title"], sheet["titleMono"]) == ("MADEUP.BIN", True)
    assert [b["text"] for b in sheet["badges"]] == ["data", "420 B"]
    file, dump = sheet["sections"]
    assert file["fields"][0] == ["Size", "420 bytes", "420 B"]
    assert dump["title"] == "First 256 bytes" and dump["aside"] == "of 420"
    assert dump["hex"] == {"offset": 0, "bytes": (b"made-up bytes\0" * 30)[:256].hex()}

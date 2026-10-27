"""All Files: a resource's page (made-up archive bytes)."""

from types import SimpleNamespace

from decoders.plugins.SLUS_006_28.formats.resource_table import SECTOR_SIZE, Resource
from viewer_tabs.tab_providers import ResourcesProvider, ResourceRow, proven_by_section


def test_a_resource_read_as_it_lies_shows_its_first_bytes(tmp_path):
    data = bytes(range(256)) * (2 * SECTOR_SIZE // 256)
    (tmp_path / "LUNADATA.FIL").write_bytes(data)
    ctx = SimpleNamespace(path=lambda name: tmp_path / name)
    row = ResourceRow(resource=Resource(700, 1, 1), region=None,
                      role="outside the regions the code reads", toc_name="MADEUP",
                      commands="", tabs=())
    sheet = ResourcesProvider().on_select(row, {}, None, ctx).sheet
    assert (sheet["title"], sheet["subtitle"]) == ("Resource 700", row.role)
    assert [b["text"] for b in sheet["badges"]] == ["0x2bc", "2 KB", "read as it lies"]
    titles = [s["title"] for s in sheet["sections"]]
    assert titles[:4] == ["Resource", "In the game", "Shown in", "First 128 bytes"]
    resource = sheet["sections"][0]["fields"]
    assert ["Sectors", "1 to 1", "1 sector"] in resource
    assert resource[-1][:2] == ["TOC entry", "MADEUP"]
    assert sheet["sections"][3]["hex"]["bytes"] == data[SECTOR_SIZE:SECTOR_SIZE + 128].hex()


def test_proof_is_a_list_of_functions_with_its_write_up_aside():
    section = proven_by_section(ResourcesProvider.PRODUCER)
    assert section["title"] == "Proven by" and section["list"]
    assert proven_by_section("no.such.decoder") is None

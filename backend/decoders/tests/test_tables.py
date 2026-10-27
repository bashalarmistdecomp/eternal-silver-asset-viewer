"""The hand-kept tables agree with the tree and with each other.

Three tables are kept by hand and drift silently: the decoder registry
(inventory.py), gamedb's disc tables, and the plugin list. Each test here
is the check that keeps one of them true.
"""

from pathlib import Path

from decoders import inventory, plugins
from decoders.psx.gamedb import known_games


def test_inventory_describes_the_tree():
    assert inventory.check_drift() == []


def test_gamedb_tables_agree():
    assert known_games.check_consistency() == []


def test_each_plugin_names_its_program():
    """Declaration, directory name and gamedb say the same serial."""
    plugins_dir = Path(plugins.__file__).parent
    on_disk = {p.name for p in plugins_dir.iterdir()
               if (p / "__init__.py").is_file()}
    assert on_disk == set(plugins.COMPAT.values())
    for package in on_disk:
        serial = inventory.unmangle(package)
        assert plugins.COMPAT[serial] == package == plugins.mangle(serial)
        assert plugins.plugin_for(serial).SERIAL == serial
    for serial, package in plugins.COMPAT.items():
        plugin = plugins.plugin_for(serial)
        assert plugin is not None and plugin.__name__.endswith(package)
        assert serial in known_games.DISC_ID_LOOKUP
        assert known_games.program_of(serial) == serial


def test_records_name_the_plugins_programs():
    """A plugin's record layouts are written by its own program's register,
    and every other program it serves is one its records tell apart."""
    for serial in plugins.COMPAT:
        plugin = plugins.plugin_for(serial)
        try:
            records = __import__(f"{plugin.__name__}.records",
                                 fromlist=["PROGRAM"])
        except ModuleNotFoundError:
            continue
        assert records.PROGRAM == plugin.SERIAL
        if serial != plugin.SERIAL:
            programs = __import__(f"{plugin.__name__}.records.programs",
                                  fromlist=["PROGRAMS"])
            assert serial in programs.PROGRAMS


def test_a_game_holds_its_versions_demos_and_bonus_discs():
    lunar1 = known_games.GAMES[0]
    programs = known_games.game_programs(lunar1)
    assert programs[0] == "SLUS_006.28"
    assert {"SLPS_013.97", "SLUS_900.55", "SLUS_009.21"} <= set(programs)
    assert known_games.game_of("SLUS_009.21") is lunar1
    assert known_games.game_of("SLUS_010.71").key == "lunar-2"
    assert known_games.game_of("SLUS_999.99") is None


def test_versions_share_a_group_and_a_bonus_disc_keeps_its_own():
    assert known_games.version_group("SLPS_013.97") == "SLUS_006.28"
    assert known_games.version_group("SLUS_900.55") == "SLUS_006.28"
    assert known_games.version_group("SLUS_009.21") == "SLUS_009.21"
    assert known_games.version_group("SLUS_006.28") == "SLUS_006.28"


def test_disc_tags():
    assert known_games.disc_tag("SLUS_006.28") == "US 1"
    assert known_games.disc_tag("SLUS_008.99") == "US 2"
    assert known_games.disc_tag("SLPS_013.97") == "JP 1"
    assert known_games.disc_tag("SLUS_009.21") == "Making-of"
    assert known_games.disc_tag("SLUS_900.83") == "Demo"
    assert known_games.disc_tag("SLUS_999.99") == "SLUS_999.99"

"""What a sound bank is for — made-up banks, no game data.

What this CAN catch: a bank the sound effects play from labelled music
(the battle's, 358, was), or a music bank labelled sound effects, by the
bank slot the code loads each into (sound_banks.SFX_REGIONS).

What it CANNOT catch: whether a bank's sequences are what its label says
to the ear; only which routine the game plays them through.
"""

import pytest

from decoders.plugins.SLUS_006_28.formats.sound_banks import SoundBank


def _bank(resource: int) -> SoundBank:
    return SoundBank(resource=resource, sector=0, size=0)


@pytest.mark.parametrize("resource", [232, 294, 300, 357, 358])
def test_the_banks_sound_effect_play_plays_are_sound_effects(resource):
    bank = _bank(resource)
    assert bank.is_sfx and "sound effects" in bank.label


@pytest.mark.parametrize("resource", [233, 260, 293])
def test_the_banks_sound_music_load_loads_are_music(resource):
    bank = _bank(resource)
    assert not bank.is_sfx and "music" in bank.label


@pytest.mark.parametrize("resource", [1, 231, 359])
def test_a_resource_that_is_no_sound_bank_is_no_sound_effects(resource):
    assert not _bank(resource).is_sfx


def test_a_bank_read_again_is_one_parse_and_new_bytes_are_read_anew(tmp_path):
    """load_bank shares the parse of the same bytes at the same place while
    it is held; a bank whose bytes changed is parsed again."""
    import struct
    from decoders.config import SECTOR_SIZE
    from decoders.plugins.SLUS_006_28.formats.sound_banks import load_bank

    def archive(kind: int) -> bytes:
        return (struct.pack("<II", kind, 4) + b"\x01\x02\x03\x04").ljust(SECTOR_SIZE, b"\0")

    path = tmp_path / "ARCHIVE.FIL"
    path.write_bytes(archive(1))
    first = load_bank(path, 240, sector=0, size_sectors=1)
    assert load_bank(path, 240, sector=0, size_sectors=1) is first
    assert [c.kind for c in first.chunks] == [1]
    assert load_bank(path, 241, sector=0, size_sectors=1) is not first
    path.write_bytes(archive(2))
    changed = load_bank(path, 240, sector=0, size_sectors=1)
    assert changed is not first and [c.kind for c in changed.chunks] == [2]

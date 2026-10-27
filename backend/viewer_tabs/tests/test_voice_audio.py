"""Where the voices' sound is read from (viewer_tabs.voice_audio), on
made-up disc images: no game data.

What this CAN catch: `_AUDIO.XA` not found on an image the library takes
(a cue sheet's data track, a bare .bin), or an .iso, which keeps 2048
bytes of each sector, refused for the wrong reason.

What it CANNOT catch: whether a voice's sectors decode
(test_voices_on_disc).
"""

from types import SimpleNamespace

from decoders.config import RAW_SECTOR_SIZE
from decoders.testing import iso_image, raw_sectors
from viewer_tabs.voice_audio import VoiceFile

#: a made-up _AUDIO.XA: two sectors whose user data is numbered
AUDIO = bytes(range(256)) * 16


def _image(tmp_path, name: str, raw: bool):
    image = iso_image({b"_AUDIO.XA;1": AUDIO})
    path = tmp_path / name
    path.write_bytes(raw_sectors(image) if raw else image)
    return path


def _voices(source):
    return VoiceFile(SimpleNamespace(source=source))


def test_a_bare_bin_and_a_cue_sheet_s_track_are_read_alike(tmp_path):
    bare = _voices(_image(tmp_path, "Disc.bin", raw=True))
    cue = tmp_path / "Disc.cue"
    cue.write_text('FILE "Disc.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    sheet = _voices(cue)
    assert bare.why == sheet.why == ""
    assert bare.image == sheet.image == tmp_path / "Disc.bin" and bare.lba == sheet.lba > 0
    voice = SimpleNamespace(start=0, sectors=2)
    raw = bare.raw(voice)
    assert len(raw) == 2 * RAW_SECTOR_SIZE and AUDIO[:2048] in raw


def test_an_iso_says_it_has_lost_the_sound(tmp_path):
    v = _voices(_image(tmp_path, "Disc.iso", raw=False))
    assert v.image is None
    assert v.why.startswith("Disc.iso keeps only 2048 bytes of each sector"), v.why


def test_no_image_on_hand_says_so(tmp_path):
    assert "not on hand" in _voices(None).why


def test_a_movie_finds_the_raw_sectors_where_a_voice_does(tmp_path):
    """viewer_tabs.movie.raw_track is the one rule: the movies' sound is read
    from a bare .bin as from a cue sheet's track."""
    from viewer_tabs.movie import raw_track
    bare = _image(tmp_path, "Disc.bin", raw=True)
    cue = tmp_path / "Disc.cue"
    cue.write_text('FILE "Disc.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    assert raw_track(bare) == raw_track(cue) == (bare, "")
    iso = _image(tmp_path, "Disc.iso", raw=False)
    assert raw_track(iso)[0] is None and raw_track(None)[0] is None

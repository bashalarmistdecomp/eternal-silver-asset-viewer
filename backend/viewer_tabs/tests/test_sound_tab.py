"""Sound banks' scores on a made-up bank (the Music tab plays its songs
the same way): the clip carries where the game's endless loop lies, the
playhead's time map follows libsnd's reading (back at each loop end), the
score plays live, and an export can choose the passes. A score is walked
once while it is held, by every disc's tab, and forgotten with it.
"""

import gc
import io
import wave
from types import SimpleNamespace

import pytest

from decoders.plugins.SLUS_006_28.records.sound_setting import game_setting
from decoders.psx.formats.seq_synth import render
from decoders.psx.formats.tests.test_seq_synth import ONE, _bank, _looped
from viewer_server.present import present
from viewer_tabs.tab_providers import SoundBanksProvider


def _provider():
    return SoundBanksProvider(), SimpleNamespace(resource=7, seqs=[_looped()],
                                            vab=_bank(ONE))


def _seconds(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


def test_a_score_held_is_walked_once(monkeypatch):
    from decoders.psx.formats import seq_synth
    from viewer_tabs import tab_providers as tp
    made = []
    real = seq_synth.walk
    monkeypatch.setattr(seq_synth, "walk", lambda *a, **k: made.append(a) or real(*a, **k))
    prov, bank = _provider()
    one = prov._walk(bank.seqs[0], bank)
    assert prov._walk(bank.seqs[0], bank) is one
    assert SoundBanksProvider()._walk(bank.seqs[0], bank) is one     # another disc's tab
    assert len(made) == 1
    _, again = _provider()                      # the same bytes, parsed again
    assert prov._walk(again.seqs[0], again).seconds == one.seconds
    assert len(made) == 2
    kept = len(tp._WALKED)
    del bank, again, made[:]
    gc.collect()
    assert len(tp._WALKED) == kept - 2


def test_the_clip_knows_the_loop_and_renders_any_passes():
    prov, bank = _provider()
    result = prov._show_sequence(bank, 0)
    audio = result.audio
    start, end = audio["loop"]
    assert 0 < start < end and audio["passes"] == 2
    assert "wav" not in audio                   # it plays live
    pass_seconds = end - start
    two, four = _seconds(audio["render_wav"]()), _seconds(audio["render_wav"](4))
    assert abs(four - two - 2 * pass_seconds) < 0.001
    assert two == pytest.approx(result.music.seconds)


def test_the_score_to_play_is_the_render_laid_out():
    """What the server plays live: a player of the score at the tab's
    setting, and the map's length, first pass and loop as the render of
    `passes` measures them."""
    prov, bank = _provider()
    music = prov._show_sequence(bank, 0).music
    pcm, stats = render(bank.seqs[0], bank.vab, passes=music.passes,
                        **game_setting().render_args())
    assert music.frames == len(pcm) // 4
    assert music.loop == stats.loop and music.first_pass == stats.first_pass
    assert music.player(music.passes).read(len(pcm)) == pcm
    endless = music.player(None)
    endless.read(len(pcm) * 3)
    assert not endless.ended


def test_what_only_a_full_pass_measures_fills_in_from_it():
    prov, bank = _provider()
    result = prov._show_sequence(bank, 0)
    assert "peak …/32768" in result.text
    player = result.music.player(result.music.passes)
    while player.read(1 << 16):
        pass
    shown = result.music.describe(player.result())
    assert "…" not in shown["text"].split("fidelity")[0]
    assert f"peak {player.stats.peak}/32768" in shown["text"]
    assert shown["info"].startswith("sequence 7/0")


def test_the_arrangement_playhead_jumps_back_at_the_loop():
    prov, bank = _provider()
    arr = prov._show_arrangement(bank, 0).timeline
    back = [(a, b) for a, b in zip(arr.tempo_ticks, arr.tempo_ticks[1:])
            if a[0] == b[0] and b[1] < a[1]]
    assert len(back) == 1 and back[0][1][1] == 0


def test_present_passes_the_loop_on():
    class Store:
        def put_bytes(self, data, mime):
            return mime

    prov, bank = _provider()
    result = prov._show_sequence(bank, 0)
    vm, _ = present(result, prov, Store())
    start, end = vm["audio"]["loop"]
    assert start < end and vm["audio"]["passes"] == 2
    assert vm["audio"]["wav"] is None
    assert vm["audio"]["seconds"] == pytest.approx(result.music.seconds)
    wave_ = vm["waveform"]
    assert wave_["pending"] and wave_["lo"] == [] and wave_["columns"] > 0
    assert wave_["loop"] * wave_["seconds"] == pytest.approx(start)
    assert wave_["loopEnd"] * wave_["seconds"] == pytest.approx(end)


def test_the_files_view_says_which_audio_files_are_played(tmp_path):
    status = {}
    for name in ("_AUDIO.XA", "_SECOND.XA"):
        (tmp_path / name).write_bytes(b"made up")
        status[name] = dict(SoundBanksProvider()._show_file(tmp_path / name).summary["fields"])
    assert "the Voices tab plays each voice" in status["_AUDIO.XA"]["Status"]
    assert status["_SECOND.XA"]["Status"] == "not decoded yet"

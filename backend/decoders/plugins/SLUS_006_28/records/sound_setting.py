"""How SSSC plays a sequence: what its code sets in libsnd and the SPU.

Each value is transcribed from the game's code (docs/spec/sound.md §6):

* **Score volume** — `sound_seq_play` (0x80023B24) opens the score, calls
  `SsSeqSetVol(seq, 0x50, 0x50)` and `SsSeqPlay(seq, 1, 1)` (one pass; the
  NRPN loops in the data loop the music). On the music slot (0) it then
  applies the music level, `sound_music_level_apply` (0x800246B0) ->
  `sound_music_volume_set` (0x80023C4C): min(level * 0x50 / 0xFF, 0x50).
  The full level is 0xFF (`sound_music_level_reset` (0x800245D0)), which
  is 0x50 again; fades move the level, and the viewer plays at full.
* **Main volume** — `sound_init` (0x80023D54) ends with
  `SpuSetCommonMasterVolume` (0x800A0DA8)(0x3F80, 0x3F80).
* **Tick** — `sound_init` calls `SsSetTickMode` (0x800995E8)(SS_TICK60),
  which on an NTSC console is the vertical blank with VBLANK_MINUS 60, and
  `SsStart2` (0x80098388) hangs the tick on `VSyncCallback`. The game's
  screens are 240 lines and non-interlaced (`system_init` (0x8001EEB8)
  and `screen_mode_set` (0x8001F0C8): `GsInitGraph` mode 4 below 480
  lines), so a tick is one NTSC field of 263 lines. Only a 480-line
  screen would make it the interlaced 262.5.
* **Reverb** — `records.spu_reverb.game_setting`.
* **Stereo** — `SoundMonoSet` (0x800550D4): stereo unless the options say
  mono.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from decoders.psx.formats.seq_synth import NTSC_FIELD_HZ
from decoders.psx.formats.spu_reverb import ReverbSetting

#: sound_seq_play (0x80023B24) / sound_music_volume_set (0x80023C4C) at the full level
SCORE_VOLUME = (0x50, 0x50)
#: sound_init (0x80023D54): SpuSetCommonMasterVolume(0x3F80, 0x3F80)
MASTER_VOLUME = 0x3F80
#: SsSetTickMode (0x800995E8)(SS_TICK60) on NTSC
VBLANK_MINUS = 60
TICK_HZ = NTSC_FIELD_HZ
#: SoundMonoSet (0x800550D4) with the options' default
MONO = False

PROVEN_BY = ("sound_seq_play (0x80023B24)", "sound_music_volume_set (0x80023C4C)",
             "sound_music_level_reset (0x800245D0)", "sound_init (0x80023D54)",
             "SsSetTickMode (0x800995E8)", "SsStart2 (0x80098388)",
             "screen_mode_set (0x8001F0C8)", "SoundMonoSet (0x800550D4)")


@dataclass(frozen=True)
class SoundSetting:
    """Everything `seq_synth.render` needs to play a score as SSSC does."""

    score_volume: tuple[int, int]
    master_volume: int
    tick_hz: Fraction
    vblank_minus: int
    mono: bool
    reverb: ReverbSetting | None

    def render_args(self) -> dict:
        return {"score_volume": self.score_volume,
                "master_volume": self.master_volume,
                "tick_hz": self.tick_hz, "vblank_minus": self.vblank_minus,
                "mono": self.mono, "reverb": self.reverb}

    def lines(self) -> list[str]:
        """The setting, for display beside a render."""
        out = [f"score volume {self.score_volume[0]:#x}/"
               f"{self.score_volume[1]:#x}, main volume "
               f"{self.master_volume:#x}",
               f"tick {float(self.tick_hz):.3f} Hz (VBLANK_MINUS "
               f"{self.vblank_minus}), {'mono' if self.mono else 'stereo'}"]
        return out


def game_setting(src=None) -> SoundSetting:
    """SSSC's setting. `src` (the EXE image, or a loaded binary) supplies
    the reverb preset; without it the setting has no reverb."""
    reverb = None
    if src is not None:
        from decoders.plugins.SLUS_006_28.records.spu_reverb import (
            game_setting as reverb_setting)
        reverb = reverb_setting(src)
    return SoundSetting(SCORE_VOLUME, MASTER_VOLUME, TICK_HZ, VBLANK_MINUS,
                        MONO, reverb)

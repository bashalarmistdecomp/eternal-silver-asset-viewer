"""Tier 1 for how the program plays a sequence: the values its code sets,
handed to the renderer as they are.

What this CAN catch: a setting that drifts from the code it cites, and
render arguments the renderer does not take. What it CANNOT catch: the
cited code itself; that is re-read in the decomp.
"""

from fractions import Fraction

from decoders.plugins.SLUS_006_28.records import sound_setting as SS
from decoders.plugins.SLUS_006_28.records.tests.test_spu_reverb import _image
from decoders.psx.formats import seq_synth


def test_the_codes_values():
    s = SS.game_setting()
    assert s.score_volume == (0x50, 0x50) and s.master_volume == 0x3F80
    assert s.vblank_minus == 60 and not s.mono and s.reverb is None
    # an NTSC field of 263 lines of 3413 clocks at 53.693175 MHz
    assert s.tick_hz == Fraction(53_693_175, 263 * 3413)
    assert round(float(s.tick_hz), 3) == 59.817


def test_the_renderer_takes_the_setting_as_it_is():
    from decoders.psx.formats.tests.test_seq_synth import ONE, _bank, _held
    s = SS.game_setting(_image())
    assert s.reverb is not None and s.reverb.preset.mode == 4
    _, stats = seq_synth.render(_held(), _bank(ONE), rate=4410,
                                **s.render_args())
    assert stats.notes == 1 and stats.reverb.startswith("STUDIO_C")

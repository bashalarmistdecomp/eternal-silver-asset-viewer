from fractions import Fraction

import pytest

from decoders.psx.formats.display import DisplayMode, mode_for


@pytest.mark.parametrize("disp_w, width", [
    (224, 256), (256, 256), (280, 256),
    (281, 320), (320, 320), (352, 320),
    (353, 368), (400, 368),
    (401, 512), (560, 512),
    (561, 640), (640, 640),
])
def test_the_width_picks_the_mode(disp_w, width):
    assert mode_for(disp_w, 240).width == width


def test_over_256_lines_is_interlaced():
    assert not mode_for(320, 256).interlaced
    assert mode_for(320, 257).interlaced


@pytest.mark.parametrize("width, aspect", [
    (256, Fraction(8, 7)),
    (320, Fraction(32, 35)),
    (368, Fraction(4, 5)),
    (512, Fraction(4, 7)),
    (640, Fraction(16, 35)),
])
def test_a_pixel_narrows_with_the_ticks_it_lasts(width, aspect):
    assert DisplayMode(width, False).pixel_aspect == aspect


def test_an_interlaced_pixel_is_twice_as_wide_for_its_height():
    assert DisplayMode(640, True).pixel_aspect == Fraction(32, 35)


def test_the_256_mode_at_224_by_192_is_a_4_by_3_picture():
    mode = mode_for(224, 192)
    assert 224 * mode.pixel_aspect / 192 == Fraction(4, 3)

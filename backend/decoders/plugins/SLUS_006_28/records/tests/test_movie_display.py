from fractions import Fraction

from decoders.plugins.SLUS_006_28.records.movie_display import movie_mode


def test_a_movie_plays_in_the_mode_its_own_width_picks():
    # The player's display is the frame's width: a narrow frame gets the
    # 256 mode, a 320-wide one the 320 mode.
    assert movie_mode(224, 192).width == 256
    assert movie_mode(320, 240).width == 320


def test_sssc_movie_pixels_are_8_by_7():
    assert movie_mode(224, 192).pixel_aspect == Fraction(8, 7)

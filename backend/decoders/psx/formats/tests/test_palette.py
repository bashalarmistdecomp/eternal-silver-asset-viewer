"""ABGR1555 — the colour encoding every other PS1 format defers to.

Spec: docs/spec/formats/palettes.md. Bit 15 is stp, 14-10 blue, 9-5 green,
4-0 RED. The low five bits being red is the fact the rest of the tree
depends on, so it is asserted here against literal hardware values rather
than against another decoder's opinion.
"""

from decoders.psx.formats.palette import parse_ps1_palette
from decoders.testing import rgb555, u16


def test_channel_order_matches_hardware():
    # Low five bits are RED, not blue. See the module docstring.
    red, green, blue = parse_ps1_palette(u16(0x001F, 0x03E0, 0x7C00))
    assert red[:3] == (248, 0, 0)
    assert green[:3] == (0, 248, 0)
    assert blue[:3] == (0, 0, 248)


def test_white_and_full_scale():
    (white,) = parse_ps1_palette(u16(0x7FFF))
    assert white == (248, 248, 248, 255)


def test_five_bits_scale_by_eight():
    # 31 -> 248, not 255: the decoder shifts left by 3 and does not
    # replicate the high bits into the low ones.
    (c,) = parse_ps1_palette(u16(rgb555(1, 2, 3)))
    assert c[:3] == (8, 16, 24)


def test_only_the_word_0_is_transparent():
    # The GPU skips a texel whose colour is 0x0000 and draws every other:
    # pure red (0x001F) and near-black (0x0001, 0x8000) are opaque.
    black, red, near, stp = parse_ps1_palette(u16(0x0000, 0x001F, 0x0001, 0x8000))
    assert black[3] == 0
    assert red == (0xF8, 0, 0, 255)
    assert near[3] == 255 and stp[3] == 255


def test_stp_bit_does_not_change_colour():
    # The semi-transparency flag is not a colour bit; setting it must not
    # bleed into blue.
    (plain,) = parse_ps1_palette(u16(0x03E0))
    (with_stp,) = parse_ps1_palette(u16(0x83E0))
    assert plain[:3] == with_stp[:3] == (0, 248, 0)


def test_odd_trailing_byte_is_ignored():
    # A halfword decoder handed an odd length must drop the stray byte
    # rather than read past the buffer.
    assert len(parse_ps1_palette(u16(0x7FFF) + b"\x12")) == 1


def test_empty_input():
    assert parse_ps1_palette(b"") == []

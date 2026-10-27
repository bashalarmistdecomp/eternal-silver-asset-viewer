"""TIM container parsing and rendering.

Two things here are easy to get wrong:

* `pix_w` counts VRAM *halfwords*, so a 4bpp TIM's real width is `pix_w * 4`.
* the 16-bit direct path's channel order (Pillow hands the bands back as
  B, G, R): `test_direct16_channel_order_matches_the_clut_path` compares
  the two paths rather than trusting either alone.
"""

from decoders.psx.formats import tim
from decoders.psx.formats.palette import parse_ps1_palette
from decoders.testing import rgb555, u16, u32


def _clut_block(colours):
    body = u16(*colours)
    return u32(12 + len(body)) + u16(0, 0, len(colours), 1) + body


def _pixel_block(pixels, pix_w, pix_h):
    return u32(12 + len(pixels)) + u16(0, 0, pix_w, pix_h) + pixels


def _tim4(colours, pixels, pix_w, pix_h):
    return (u32(tim.TIM_MAGIC, 0x08 | tim.MODE_4BIT)
            + _clut_block(colours) + _pixel_block(pixels, pix_w, pix_h))


RAMP = [rgb555(i * 2, i, 31 - i) for i in range(16)]


def test_4bpp_width_is_four_times_pix_w():
    # pix_w = 2 halfwords -> 8 pixels across at 4bpp.
    data = _tim4(RAMP, bytes([0x10, 0x32, 0x54, 0x76]) * 2, 2, 2)
    t = tim.parse_tim(data)
    assert (t.width, t.height) == (8, 2)
    assert t.mode == tim.MODE_4BIT
    assert t.clut_count == 1
    # byte_size must account for the whole TIM so bundles can be walked.
    assert t.byte_size == len(data)


def test_4bpp_low_nibble_is_the_left_pixel():
    data = _tim4(RAMP, bytes([0x10, 0x32, 0x54, 0x76]) * 2, 2, 2)
    img = tim.parse_tim(data).to_image()
    # byte 0x10 -> indices 0 then 1, in that order.
    assert img.getpixel((0, 0)) == parse_ps1_palette(u16(RAMP[0]))[0]
    assert img.getpixel((1, 0)) == parse_ps1_palette(u16(RAMP[1]))[0]
    assert img.getpixel((2, 0)) == parse_ps1_palette(u16(RAMP[2]))[0]


def test_8bpp_width_is_twice_pix_w():
    pixels = bytes(range(8))
    data = (u32(tim.TIM_MAGIC, 0x08 | tim.MODE_8BIT)
            + _clut_block(RAMP) + _pixel_block(pixels, 4, 1))
    t = tim.parse_tim(data)
    assert (t.width, t.height) == (8, 1)


def test_direct16_channel_order_matches_the_clut_path():
    """The bug this file exists for.

    A 16-bit direct pixel and a CLUT entry are the same ABGR1555 halfword,
    so the two render paths must agree. They did not: Pillow's "BGR;15" raw
    mode hands back (B, G, R) under an "RGB" label, and the low five bits —
    PS1 red — were landing in blue.
    """
    for word in (0x001F, 0x03E0, 0x7C00, 0x7FFF, rgb555(9, 18, 27)):
        pixels = u16(word)
        data = (u32(tim.TIM_MAGIC, tim.MODE_16BIT)
                + _pixel_block(pixels, 1, 1))
        direct = tim.parse_tim(data).to_image().getpixel((0, 0))
        expected = parse_ps1_palette(pixels)[0]
        assert direct[:3] == expected[:3], f"word {word:#06x}"


def test_direct24_is_three_bytes_a_pixel_in_rows_of_halfwords():
    # 3 pixels across = 9 bytes, padded to 10 = pix_w 5 halfwords.
    row = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 0xEE])
    data = u32(tim.TIM_MAGIC, tim.MODE_24BIT) + _pixel_block(row * 2, 5, 2)
    t = tim.parse_tim(data)
    assert (t.width, t.height) == (3, 2)
    img = t.to_image()
    assert [img.getpixel((x, 1)) for x in range(3)] == [
        (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)]


def test_direct16_drops_the_stp_bit_as_opaque():
    # Deliberate divergence from the CLUT path, documented in tim.py: the
    # direct path has no colour-key transparency.
    data = u32(tim.TIM_MAGIC, tim.MODE_16BIT) + _pixel_block(u16(0x0000), 1, 1)
    assert tim.parse_tim(data).to_image().getpixel((0, 0))[3] == 255


def test_multi_clut_selection():
    # clut_w = 8 colours, clut_h = 2 CLUTs, laid out one after the other.
    clut = u16(*RAMP[:8]) + u16(*RAMP[8:])
    data = (u32(tim.TIM_MAGIC, 0x08 | tim.MODE_4BIT)
            + u32(12 + len(clut)) + u16(0, 0, 8, 2) + clut
            + _pixel_block(bytes([0x00]) * 4, 1, 2))
    t = tim.parse_tim(data)
    assert t.clut_count == 2
    assert t.to_image(0).getpixel((0, 0)) != t.to_image(1).getpixel((0, 0))


def test_rejects_non_tims():
    assert tim.parse_tim(b"\x00" * 32) is None            # wrong magic
    assert tim.parse_tim(b"\x10\x00\x00\x00") is None     # too short
    # mode 7 is not one of the four pixel modes
    assert tim.parse_tim(u32(tim.TIM_MAGIC, 0x07)
                         + _pixel_block(bytes(8), 2, 2)) is None


def test_rejects_dimensions_vram_cannot_hold():
    """The guard against a coincidental 0x10 magic in unrelated data."""
    assert tim.parse_tim(u32(tim.TIM_MAGIC, tim.MODE_8BIT)
                         + _pixel_block(bytes(8), 0, 2)) is None
    assert tim.parse_tim(u32(tim.TIM_MAGIC, tim.MODE_8BIT)
                         + _pixel_block(bytes(8), 2048, 2)) is None
    assert tim.parse_tim(u32(tim.TIM_MAGIC, tim.MODE_8BIT)
                         + _pixel_block(bytes(8), 2, 1024)) is None


def test_truncated_block_is_rejected_not_read_past():
    # length claims more bytes than the buffer holds
    data = u32(tim.TIM_MAGIC, tim.MODE_8BIT) + u32(9999) + u16(0, 0, 2, 2)
    assert tim.parse_tim(data) is None


def test_tims_in_stream_walks_a_bundle():
    # Bundle entries are word-aligned; this one is 24 bytes so the walk
    # lands on each successive magic without having to hunt.
    one = u32(tim.TIM_MAGIC, tim.MODE_16BIT) + _pixel_block(u16(0x7FFF, 0), 2, 1)
    assert len(one) % 4 == 0
    found = list(tim.tims_in_stream(one * 3))
    assert [off for off, _ in found] == [0, len(one), 2 * len(one)]


def test_tims_in_stream_hunts_past_padding():
    """An unaligned or padded gap must not end the walk."""
    one = u32(tim.TIM_MAGIC, tim.MODE_16BIT) + _pixel_block(u16(0x7FFF, 0), 2, 1)
    found = list(tim.tims_in_stream(one + b"\xAB" * 16 + one))
    assert len(found) == 2


def test_clut_words_keep_the_stored_colours():
    t = tim.parse_tim(_tim4(RAMP, b"\x10" * 8, 2, 4))
    assert t.clut_words == [RAMP]
    assert tim.parse_tim(u32(tim.TIM_MAGIC, tim.MODE_8BIT)
                         + _pixel_block(b"\x00" * 8, 2, 2)).clut_words == []

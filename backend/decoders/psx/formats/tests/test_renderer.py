"""Tier-1 tests for the layer compositor — synthetic images only.

`composite_layers` is alpha compositing, so it needs RGBA layers of one
size. PIL reports either violation as `ValueError: images do not match`,
naming neither the layer nor the fault; these tests pin the diagnostics
that replaced it, after an RGB layer from the viewer's video tab produced
that message with nothing to act on.

`render_indexed_layer` is checked against the pixel-by-pixel reading it
replaced, on made-up layers: short and long data, short palettes.
"""

import random

import pytest
from PIL import Image

from decoders.psx.formats.renderer import composite_layers, render_indexed_layer


def _rgba(size=(4, 4), colour=(0, 0, 0, 0)):
    return Image.new("RGBA", size, colour)


def test_empty_layer_list_gives_an_opaque_placeholder():
    img = composite_layers([])
    assert img.mode == "RGBA" and img.size == (256, 256)
    assert img.getpixel((0, 0)) == (0, 0, 0, 255)


def test_layers_composite_bottom_to_top():
    bottom = _rgba(colour=(255, 0, 0, 255))
    top = _rgba(colour=(0, 0, 255, 255))
    assert composite_layers([bottom, top]).getpixel((0, 0)) == (0, 0, 255, 255)


def test_transparent_layer_leaves_the_one_below_visible():
    bottom = _rgba(colour=(255, 0, 0, 255))
    assert composite_layers([bottom, _rgba()]).getpixel((0, 0)) == (255, 0, 0, 255)


def test_result_is_opaque_even_when_every_layer_is_transparent():
    assert composite_layers([_rgba()]).getpixel((0, 0)) == (0, 0, 0, 255)


def test_non_rgba_layer_names_the_layer_and_its_mode():
    with pytest.raises(ValueError, match=r"layer 1 is RGB\b"):
        composite_layers([_rgba(), Image.new("RGB", (4, 4))])


def test_mismatched_size_names_both_sizes():
    with pytest.raises(ValueError, match=r"layer 1 is \(8, 8\), layer 0 is \(4, 4\)"):
        composite_layers([_rgba(), _rgba((8, 8))])


def _one_by_one(data, palette, width, height):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for i, p in enumerate(data[:width * height]):
        if p < len(palette):
            img.putpixel((i % width, i // width), palette[p])
    return img


def test_an_indexed_layer_is_its_pixels_through_the_palette():
    rng = random.Random(3)
    for _ in range(40):
        width, height = rng.randrange(1, 40), rng.randrange(1, 40)
        data = bytes(rng.randrange(256) for _ in range(rng.randrange(0, width * height + 50)))
        palette = [tuple(rng.randrange(256) for _ in range(4))
                   for _ in range(rng.choice([0, 1, 16, 200, 256, 300]))]
        for kind in (bytes, bytearray):
            got = render_indexed_layer(kind(data), palette, width, height)
            assert got.mode == "RGBA" and got.size == (width, height)
            assert got.tobytes() == _one_by_one(data, palette, width, height).tobytes()

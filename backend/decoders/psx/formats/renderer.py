"""Rendering 8-bit indexed pixel layers to PIL Images."""

from PIL import Image

from decoders.psx.formats.palette import Color


def render_indexed_layer(
    layer_data: bytes,
    palette: list[Color],
    width: int = 256,
    height: int = 256,
) -> Image.Image:
    """Render an 8-bit indexed pixel layer as an RGBA PIL Image: a pixel
    past the data's end, or whose index the palette does not have, is
    left clear."""
    table = _rgba_table(palette)
    size = width * height
    if table is not None and size > 0 and isinstance(layer_data, (bytes, bytearray)):
        pixels = b"".join(map(table.__getitem__, layer_data[:size]))
        return Image.frombytes("RGBA", (width, height),
                               pixels + bytes(4 * size - len(pixels)))
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = img.load()

    for y in range(height):
        for x in range(width):
            idx = y * width + x
            if idx >= len(layer_data):
                break
            pal_idx = layer_data[idx]
            if pal_idx < len(palette):
                pixels[x, y] = palette[pal_idx]

    return img


def _rgba_table(palette: list[Color]) -> list[bytes] | None:
    """Index -> the four bytes of its colour, every index of a byte (those
    the palette does not have clear); None for a palette whose colours are
    not four bytes each (`render_indexed_layer` sets them one by one)."""
    try:
        table = [bytes(c) for c in palette[:256]]
    except (TypeError, ValueError):
        return None
    if any(len(c) != 4 for c in table):
        return None
    return table + [bytes(4)] * (256 - len(table))


def composite_layers(layers: list[Image.Image]) -> Image.Image:
    """Composite multiple RGBA layers, bottom to top.

    Every layer must be RGBA and the same size as the first. PIL reports a
    violation of either as `ValueError: images do not match`, which names
    neither the layer nor what was wrong with it; the checks below say
    which layer, what mode and what size, because the caller is usually a
    viewer tab that built one layer differently from the rest.
    """
    if not layers:
        return Image.new("RGBA", (256, 256), (0, 0, 0, 255))

    size = layers[0].size
    for i, layer in enumerate(layers):
        if layer.mode != "RGBA":
            raise ValueError(
                f"composite_layers needs RGBA layers: layer {i} is "
                f"{layer.mode} — convert it with .convert('RGBA')")
        if layer.size != size:
            raise ValueError(
                f"composite_layers needs one size: layer {i} is "
                f"{layer.size}, layer 0 is {size}")

    result = Image.new("RGBA", size, (0, 0, 0, 255))
    for layer in layers:
        result = Image.alpha_composite(result, layer)
    return result

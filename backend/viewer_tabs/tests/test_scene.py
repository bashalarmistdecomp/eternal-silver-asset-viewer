"""The battle scene's paint order — synthetic sheets.

sprite_draw (0x8001A528) gives a battle figure the OT entry 0x200 + 0xFF -
(Y + 0x20), so lower on screen is in front; within one entry AddPrim
(0x8008E9D8) makes each new packet the head of the chain, and
BtlAnimationStep (0x800272A8) fills the sprite list slot by slot, so at
equal Y the LOWER slot, added first, is drawn last and ends on top
(docs/spec/code/subsystems/battle.md §"The actor renderer").
"""

from PIL import Image

from viewer_tabs import scene

RED, BLUE, GREEN = (255, 0, 0, 255), (0, 0, 255, 255), (0, 255, 0, 255)


def _sheet(colours) -> dict:
    """One 4x4 cell per colour, anchored at its top left; anim k shows cell k."""
    img = Image.new("RGBA", (4 * len(colours), 4))
    for k, c in enumerate(colours):
        img.paste(c, (4 * k, 0, 4 * k + 4, 4))
    return {"image": img, "cell_w": 4, "cell_h": 4, "anchor_x": 0, "anchor_y": 0,
            "columns": len(colours), "poses": len(colours),
            "anims": [{"index": k, "hold": True, "steps": [[k, 1]], "name": None,
                       "proof": None} for k in range(len(colours))]}


def _actor(anim: int, x: int, y: int, slot: int) -> dict:
    return {"sheet": 0, "x": x, "y": y, "mirror": False, "anim": anim,
            "label": f"slot {slot}"}


def test_lower_on_screen_is_in_front_and_equal_y_puts_the_lower_slot_on_top():
    a6, a7, a8 = _actor(0, 0, 120, 6), _actor(1, 0, 160, 7), _actor(2, 0, 120, 8)
    sc = {"actors": [a6, a7, a8], "depth": "y"}
    # back to front: slot 8 (y 120) under slot 6 (y 120), slot 7 (y 160) in front
    assert [a["label"] for a in scene.draw_order(sc)] == ["slot 8", "slot 6", "slot 7"]


def test_order_depth_keeps_the_list():
    acts = [_actor(0, 0, 160, 6), _actor(1, 0, 120, 7)]
    assert scene.draw_order({"actors": acts, "depth": "order"}) == acts


def test_still_paints_the_lower_slot_over_a_higher_one_at_equal_y():
    sh = _sheet([RED, BLUE, GREEN])
    # slots 6 and 9 on one row, two pixels apart, so their cells overlap
    sc = {"w": 8, "h": 8, "background": None, "sheets": [sh], "depth": "y",
          "actors": [_actor(0, 2, 2, 6), _actor(1, 0, 2, 9)]}
    img = scene.still(sc)
    assert img.getpixel((3, 3)) == RED          # the overlap: slot 6 on top
    assert img.getpixel((0, 3)) == BLUE         # slot 9 shows where 6 is not
    # one row lower wins whatever the slot
    sc["actors"] = [_actor(0, 2, 2, 6), _actor(1, 0, 3, 9)]
    assert scene.still(sc).getpixel((3, 3)) == BLUE

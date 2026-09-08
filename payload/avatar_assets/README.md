# Avatar art

This folder holds the avatar art. **It is empty of art on purpose.** No finished
art ships with this project yet. Until you add art, the phone and the Pager draw
a plain placeholder owl that marks which slots are worn, so you can test the
dress-up system without any art.

## The contract

The avatar is a stack of transparent PNG layers on one fixed canvas. Every layer
is the full canvas, so the layers line up. Wearing an item just shows its layer.

- Canvas size: see `canvas` in `manifest.json` (width x height, in pixels).
- Two resolutions:
  - `highres/` - for the phone. Larger, crisp on a phone screen.
  - `lowres/` - for the Pager's small display.
- File names (see `manifest.json` -> `layers`):
  - `base.png` - the owl with nothing worn. **Required.**
  - `<item_id>.png` - one per item, e.g. `fedora.png`, `sunglasses.png`.
- Each layer is a transparent PNG the size of its folder's canvas scaling, with
  the item drawn where it sits on the owl and everything else transparent.
- Keep each item inside its slot's box (`manifest.json` -> `slot_box`). The boxes
  do not overlap, so items in different slots can never clip each other.

## Adding an item

The item itself - its id, name, slot, cost and level - is one line in
`payload/items.py`, the single item registry. The shop, the inventory and the
avatar all read that file, so that one line makes the item buyable and wearable.
Until you add its art (below) it shows the placeholder marker for its slot.

## Adding your art

1. Draw the layers and save them into `highres/` and `lowres/` with the names
   above (same names, same transparency, same registration on the canvas).
2. From the repo root, run `python3 assets/gen_avatar.py`. This embeds the
   high-res layers into the phone page and refreshes `manifest.json`.
3. That is all. No code changes. Missing an item's file just means that item
   falls back to the placeholder marker; a present `base.png` switches the whole
   avatar from placeholder to your art.

## Concept art for testing (optional, not for shipping)

`assets/gen_concept_art.py` renders rough concept PNGs into this folder so you
can see the dress-up system with stand-in art. Those are for local testing only;
do not ship them. To return to the placeholder:

    rm -rf payload/avatar_assets/highres payload/avatar_assets/lowres
    python3 assets/gen_avatar.py

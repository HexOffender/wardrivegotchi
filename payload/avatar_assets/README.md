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

## Drawing templates (correct sizes, marked boxes)

`templates/` holds a drawing guide for every slot, made by
`python3 assets/gen_templates.py`. Each is the full canvas at the phone
(high-res) size, **384 x 504 px** (the Pager low-res copy is **128 x 168 px**):

- `overview.png` - every slot box on the owl, labelled. Reference only.
- `template_head.png`, `template_eyes.png`, `template_neck.png`,
  `template_side.png`, `template_feet.png` - one per slot. The slot's drawable
  box is bright (draw only inside it); the faint owl and neighbour boxes are for
  registration.
- `template_base.png` - a guide for drawing the owl itself (`base.png`).
- `blank_highres_384x504.png`, `blank_lowres_128x168.png` - empty transparent
  canvases at the two export sizes.

Workflow: open a slot template, add a **new layer** on top, draw the item inside
the bright box, then hide/delete the template layer and export just your layer:

- to `highres/<item_id>.png` at 384 x 504, and
- a copy scaled to 128 x 168 (nearest-neighbour) to `lowres/<item_id>.png`.

The templates are guides only - never flatten them into your art.

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

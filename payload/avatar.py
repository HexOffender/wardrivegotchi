"""The Wardrivegotchi avatar system: slots, avatar rendering and the drop-in
art contract. The wearable items themselves are listed in items.py, the single
item registry. This module ships. It contains NO final art.

How the art works:

  * The avatar is a stack of transparent PNG layers on a fixed canvas
    (GRID_W x GRID_H): a base owl, plus one layer per worn item. Every layer
    shares the canvas, so they line up, and "wearing" an item is just showing
    its layer in the fixed z-order (ZORDER).

  * Art is dropped in, not baked in. Put PNGs in avatar_assets/highres/ (phone)
    and avatar_assets/lowres/ (Pager), named base.png and <item_id>.png. Run
    assets/gen_avatar.py to embed the high-res layers into the phone page. No
    code changes. layer_paths() below is what the Pager reads.

  * Until real art is present, both the phone and the Pager draw a PLACEHOLDER
    (placeholder_grid() here): a plain owl silhouette that marks which slots are
    worn, so the dress-up system is fully testable without any art. The
    placeholder is deliberately not final art.

Two rules keep worn items from clipping or fighting, by construction:

  1. One item per slot. At most one HEAD, one EYES, one NECK, one SIDE and one
     FEET item at a time, so two things never claim the same spot.

  2. Each slot owns a box on the canvas (SLOT_BOX), and the boxes do not
     overlap, so items in different slots can never collide. check_slots()
     proves the boxes are disjoint; art must be drawn inside its slot's box.
"""

# The art canvas. All layers - and any art the artist draws - are this size.
# The owl sits in the middle with margins on every side, so an item can reach
# BEYOND the owl (a cane below the feet, a sword out to the flank, a wide brim
# past the ears).
GRID_W, GRID_H = 64, 84

# Each slot owns a box (x0, y0, x1, y1), inclusive. The boxes do not overlap.
# Art for an item must stay inside its slot's box. These positions assume the
# owl is centred on the canvas with its eyes near row 22 and talons near row 72.
SLOT_BOX = {
    'head':  (4, 0, 59, 19),    # crown and above: tall hats, wide brims
    'eyes':  (18, 20, 45, 27),  # the eye row
    'neck':  (20, 30, 43, 46),  # throat and collar, high under the head
    'side':  (0, 22, 17, 78),   # held out to the owl's left, into the margin
    'feet':  (18, 70, 55, 83),  # under the talons and below
}

# Draw order, low to high. Held and footwear first, then neck, then the head,
# and eyewear last so a hat brim never hides the glasses.
ZORDER = ['side', 'feet', 'neck', 'head', 'eyes']

# The wearable items live in items.py, the single registry for the shop, the
# inventory and the avatar. They are imported and re-exported here because much
# of the code - and gen_avatar.py - reads avatar.CATALOG / avatar.ITEM.
import items as _items

CATALOG = _items.CATALOG
ITEM = _items.ITEM


def check_slots():
    """Prove the slot boxes are disjoint, so items in different slots can never
    collide. Returns a list of overlapping pairs (empty is good)."""
    problems = []
    slots = list(SLOT_BOX.items())
    for i in range(len(slots)):
        for j in range(i + 1, len(slots)):
            a, (ax0, ay0, ax1, ay1) = slots[i]
            b, (bx0, by0, bx1, by1) = slots[j]
            if ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1:
                problems.append((a, b))
    return problems


def validate_items():
    """Check the item registry against this renderer: every item uses a slot
    that has geometry here, and the draw order covers exactly those slots.
    Returns a list of problems (empty means sound). items_test.py runs this."""
    problems = list(_items.validate(tuple(SLOT_BOX)))
    if set(ZORDER) != set(SLOT_BOX):
        problems.append('ZORDER %r does not match the slots %r' % (ZORDER, list(SLOT_BOX)))
    return problems


# ---- The placeholder renderer ----------------------------------------------
# A plain owl silhouette that marks the worn slots. It is NOT final art; it is
# here so the dress-up system can be seen and tested before the artist's PNGs
# arrive. Replace it by dropping real PNGs into avatar_assets/ (see the header).

# A tiny neutral palette, on purpose unlike any finished look.
PH_COLORS = {
    '.': None,                    # transparent
    'o': (0x5a, 0x5a, 0x5a),      # silhouette outline
    'f': (0xc9, 0xc9, 0xc2),      # silhouette fill
    'e': (0x33, 0x33, 0x33),      # eyes
    'k': (0x11, 0x11, 0x11),      # marker border
    'm': (0xff, 0xc1, 0x07),      # worn-slot marker (brand yellow)
}


def _ellipse(g, cx, cy, rx, ry, fill, edge):
    for y in range(cy - ry, cy + ry + 1):
        for x in range(cx - rx, cx + rx + 1):
            if not (0 <= x < GRID_W and 0 <= y < GRID_H):
                continue
            d = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
            if d <= 1.0:
                g[y][x] = edge if d >= 0.74 else fill


def placeholder_grid(equipped):
    """A char grid (GRID_H rows of GRID_W chars) of a plain placeholder owl,
    with a marker in the box of every worn slot. Chars index PH_COLORS."""
    g = [['.'] * GRID_W for _ in range(GRID_H)]

    # A generic owl: body, head, two ear tufts, two eyes. Deliberately plain.
    _ellipse(g, 32, 52, 17, 24, 'f', 'o')          # body
    _ellipse(g, 32, 24, 14, 13, 'f', 'o')          # head
    for tx in (22, 42):                             # ear tufts
        for dy in range(6):
            g[12 - dy][tx] = 'o'
            g[12 - dy][tx + (1 if tx < 32 else -1)] = 'o'
    _ellipse(g, 26, 24, 3, 3, 'e', 'e')            # left eye
    _ellipse(g, 38, 24, 3, 3, 'e', 'e')            # right eye
    g[24][26] = g[24][38] = 'f'                     # eye glints

    # Mark every worn slot: a border round its box and a solid fill inside, so
    # you can see which slots are filled (art pending) and where each sits. The
    # fill is solid (not a hatch) so it coalesces into a few wide runs when the
    # Pager draws it - the same flat marker the phone page uses.
    for slot in ZORDER:
        if not equipped.get(slot):
            continue
        x0, y0, x1, y1 = SLOT_BOX[slot]
        for x in range(x0, x1 + 1):
            g[y0][x] = g[y1][x] = 'k'
        for y in range(y0, y1 + 1):
            g[y][x0] = g[y][x1] = 'k'
        for y in range(y0 + 1, y1):
            for x in range(x0 + 1, x1):
                g[y][x] = 'm'
    return g


# ---- Pre-rendered asset support --------------------------------------------
# When real art is present in avatar_assets/<res>/, the Pager draws those PNG
# layers and the phone uses the high-res ones embedded in the page. When it is
# absent, layer_paths() returns [] and the placeholder above is drawn instead.

import os as _os

ASSET_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'avatar_assets')


def layer_paths(equipped, res='lowres'):
    """Ordered PNG paths for the base plus equipped items, low to high. Returns
    only files that exist; an empty list means fall back to the placeholder."""
    d = _os.path.join(ASSET_DIR, res)
    base = _os.path.join(d, 'base.png')
    if not _os.path.isfile(base):
        return []
    paths = [base]
    for slot in ZORDER:
        item_id = equipped.get(slot)
        if not item_id:
            continue
        p = _os.path.join(d, item_id + '.png')
        if _os.path.isfile(p):
            paths.append(p)
    return paths

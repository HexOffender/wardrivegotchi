"""Generate drawing templates for the avatar art, one per wearable slot.

Each template is a full-canvas PNG at the phone (high-res) size, showing:
  * a faint reference owl (the placeholder), so you register your art to it,
  * a light grid at one line per canvas unit,
  * this slot's drawable BOX drawn bright (draw only inside it), and the other
    slots' boxes faint (so you can see where neighbours sit and not overlap).

Draw your item on a NEW layer over the template, hide the template layer, and
export just your layer at the same size as <item_id>.png. See the README.

Run from the repo root:  python3 assets/gen_templates.py
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'payload'))

import avatar  # noqa: E402

OUT = os.path.join(ROOT, 'payload', 'avatar_assets', 'templates')

# The phone (high-res) canvas. 6x the GRID_W x GRID_H unit grid -> 384x504,
# matching gen_concept_art's HIGH_SCALE. Draw at this size; a 128x168 (2x) copy
# is the Pager's low-res version.
SCALE = 6
W, H = avatar.GRID_W * SCALE, avatar.GRID_H * SCALE

# Colours (RGBA). The guide is faint so your art reads clearly over it.
BG = (245, 245, 240, 28)
GRID_MINOR = (120, 120, 130, 26)
GRID_MAJOR = (120, 120, 130, 60)
OWL = {'f': (90, 90, 90, 60), 'o': (60, 60, 60, 95), 'e': (40, 40, 40, 120)}
ACTIVE_FILL = (255, 193, 7, 48)
ACTIVE_LINE = (224, 150, 0, 255)
OTHER_LINE = (120, 120, 130, 90)
LABEL = (40, 40, 45, 255)
LABEL_BG = (255, 193, 7, 235)


def _font(size):
    for path in (r'C:\Windows\Fonts\arialbd.ttf', r'C:\Windows\Fonts\arial.ttf'):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _box_px(box):
    """Slot box (inclusive grid coords) -> pixel rect [left, top, right, bottom]
    suitable for ImageDraw.rectangle (right/bottom are the last pixel drawn)."""
    x0, y0, x1, y1 = box
    return [x0 * SCALE, y0 * SCALE, (x1 + 1) * SCALE - 1, (y1 + 1) * SCALE - 1]


# The real base art, if it has been drawn. When present the templates register
# the boxes against your actual owl instead of the placeholder.
REAL_BASE = os.path.join(ROOT, 'payload', 'avatar_assets', 'highres', 'base.png')


def _base_layer():
    """The faint owl + grid, shared by every template. Uses the real base.png
    when it exists (stretched to the canvas, exactly as the app renders it),
    otherwise the placeholder owl."""
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], fill=BG)

    if os.path.isfile(REAL_BASE):
        # The owl the boxes register against, faded so the grid and boxes read
        # on top of it. Stretched to the canvas, the same way the app draws it.
        owl = Image.open(REAL_BASE).convert('RGBA').resize((W, H), Image.LANCZOS)
        owl.putalpha(owl.split()[3].point(lambda a: int(a * 0.6)))
        img.alpha_composite(owl)
    else:
        # The reference owl (the placeholder with nothing worn).
        grid = avatar.placeholder_grid({})
        for gy, row in enumerate(grid):
            for gx, ch in enumerate(row):
                col = OWL.get(ch)
                if col:
                    d.rectangle([gx * SCALE, gy * SCALE,
                                 (gx + 1) * SCALE - 1, (gy + 1) * SCALE - 1], fill=col)

    # One grid line per unit, emphasised every 4 units.
    for gx in range(avatar.GRID_W + 1):
        col = GRID_MAJOR if gx % 4 == 0 else GRID_MINOR
        x = min(gx * SCALE, W - 1)
        d.line([x, 0, x, H - 1], fill=col)
    for gy in range(avatar.GRID_H + 1):
        col = GRID_MAJOR if gy % 4 == 0 else GRID_MINOR
        y = min(gy * SCALE, H - 1)
        d.line([0, y, W - 1, y], fill=col)

    d.rectangle([0, 0, W - 1, H - 1], outline=(40, 40, 45, 200), width=2)
    return img


def _label(d, text, xy, font):
    """A small filled label so slot names read over the grid."""
    x, y = xy
    l, t, r, b = d.textbbox((x, y), text, font=font)
    d.rectangle([l - 4, t - 2, r + 4, b + 2], fill=LABEL_BG)
    d.text((x, y), text, fill=LABEL, font=font)


def slot_template(slot):
    img = _base_layer()
    d = ImageDraw.Draw(img)
    font = _font(15)

    # Neighbour boxes, faint - so you can see where adjacent items sit.
    for name, box in avatar.SLOT_BOX.items():
        if name != slot:
            d.rectangle(_box_px(box), outline=OTHER_LINE, width=1)

    # This slot's box, bright: draw ONLY inside it.
    box = avatar.SLOT_BOX[slot]
    fill = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(fill).rectangle(_box_px(box), fill=ACTIVE_FILL)
    img.alpha_composite(fill)
    d.rectangle(_box_px(box), outline=ACTIVE_LINE, width=2)

    x0, y0, x1, y1 = box
    items = [it['name'] for it in avatar.CATALOG if it['slot'] == slot]
    # Keep the label clear of the drawable box: just below it, or just above
    # when the box reaches the bottom edge (feet). The head box spans the whole
    # top, so its label lands under the box rather than inside it.
    l, t, r, b = _box_px(box)
    text = '%s  [%d,%d]-[%d,%d]  %dx%d u' % (slot.upper(), x0, y0, x1, y1,
                                             x1 - x0 + 1, y1 - y0 + 1)
    label_y = b + 6 if b + 28 <= H else max(4, t - 24)
    _label(d, text, (6, label_y), font)
    return img, items


def base_template():
    """A guide for drawing the owl itself (base.png): the whole figure, with the
    slot boxes shown faint so you leave room for worn items."""
    img = _base_layer()
    d = ImageDraw.Draw(img)
    for box in avatar.SLOT_BOX.values():
        d.rectangle(_box_px(box), outline=OTHER_LINE, width=1)
    _label(d, 'BASE  (the owl)', (6, 6), _font(15))
    return img


def overview():
    """One chart of every slot box on the owl, each labelled - reference only."""
    img = _base_layer()
    d = ImageDraw.Draw(img)
    font = _font(13)
    for name, box in avatar.SLOT_BOX.items():
        d.rectangle(_box_px(box), outline=ACTIVE_LINE, width=2)
        x0, y0, x1, y1 = box
        _label(d, name, (x0 * SCALE + 2, y0 * SCALE + 2), font)
    _label(d, 'AVATAR CANVAS %dx%d px  (%dx%d units)' % (W, H, avatar.GRID_W, avatar.GRID_H),
           (6, H - 26), _font(12))
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    made = []

    ov = overview()
    ov.save(os.path.join(OUT, 'overview.png'))
    made.append('overview.png')

    bt = base_template()
    bt.save(os.path.join(OUT, 'template_base.png'))
    made.append('template_base.png')

    for slot in avatar.SLOT_BOX:
        img, items = slot_template(slot)
        name = 'template_%s.png' % slot
        img.save(os.path.join(OUT, name))
        made.append('%s  (items: %s)' % (name, ', '.join(items)))

    # Blank, correctly-sized canvases to draw straight into if you prefer.
    Image.new('RGBA', (W, H), (0, 0, 0, 0)).save(os.path.join(OUT, 'blank_highres_%dx%d.png' % (W, H)))
    lw, lh = avatar.GRID_W * 2, avatar.GRID_H * 2
    Image.new('RGBA', (lw, lh), (0, 0, 0, 0)).save(os.path.join(OUT, 'blank_lowres_%dx%d.png' % (lw, lh)))

    print('Templates written to %s (%dx%d high-res):' % (OUT, W, H))
    for m in made:
        print('  ' + m)
    print('  blank_highres_%dx%d.png, blank_lowres_%dx%d.png' % (W, H, lw, lh))


if __name__ == '__main__':
    main()

"""Make the Pager (low-res) avatar art from the phone (high-res) art.

You draw once, at the high-res size in payload/avatar_assets/highres/. This
scales every PNG there down to the Pager size (128x168, i.e. GRID_W x GRID_H at
2x) into payload/avatar_assets/lowres/, using the same file names.

The downscale is alpha-correct: it premultiplies alpha before resampling and
divides it back out after, so soft edges do not pick up the dark halo a naive
RGBA resize leaves. Pass 'nearest' for a crisp, pixel-exact reduction instead of
the default smooth one.

Run from the repo root:  python3 assets/gen_lowres.py  [nearest|box|lanczos]
"""
import os
import sys

from PIL import Image, ImageChops, ImageMath

# Pillow renamed ImageMath.eval -> unsafe_eval (10.3) and later removed eval;
# both take the same (expression, **images) arguments. Use whichever exists so
# this runs on old and new Pillow alike.
_imeval = getattr(ImageMath, 'unsafe_eval', None) or getattr(ImageMath, 'eval')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'payload'))

import avatar  # noqa: E402

ASSETS = os.path.join(ROOT, 'payload', 'avatar_assets')
HIGH = os.path.join(ASSETS, 'highres')
LOW = os.path.join(ASSETS, 'lowres')

# The Pager draws the avatar at 2x the unit grid (see profile_ui _draw_avatar),
# so 128x168 is 1:1 on its screen.
LOW_W, LOW_H = avatar.GRID_W * 2, avatar.GRID_H * 2
CANVAS_ASPECT = avatar.GRID_W / avatar.GRID_H

FILTERS = {
    'nearest': Image.NEAREST,
    'box': Image.BOX,
    'lanczos': Image.LANCZOS,
}


def _downscale(img, size, resample):
    """Resize to `size`. For the smoothing filters, resample with premultiplied
    alpha so transparent edges do not pick up a dark halo, then divide alpha back
    out. NEAREST does no blending, so it is resized as-is. Uses only PIL (no
    numpy), so it runs wherever the rest of the asset tools do."""
    img = img.convert('RGBA')
    if resample == Image.NEAREST:
        return img.resize(size, Image.NEAREST)

    r, g, b, a = img.split()
    # Premultiply: ImageChops.multiply computes (channel * alpha) / 255.
    pm = Image.merge('RGBA', (ImageChops.multiply(r, a),
                              ImageChops.multiply(g, a),
                              ImageChops.multiply(b, a), a))
    pm = pm.resize(size, resample)
    pr, pg, pb, pa = pm.split()

    # Un-premultiply: channel * 255 / alpha, with the divisor forced to 255 where
    # alpha is 0 (those pixels are fully transparent, so their colour is moot and
    # this just avoids a divide-by-zero).
    def unp(c):
        return _imeval("convert((c * 255) / (a + (a == 0)), 'L')", c=c, a=pa)

    return Image.merge('RGBA', (unp(pr), unp(pg), unp(pb), pa))


def main():
    name = (sys.argv[1].lower() if len(sys.argv) > 1 else 'lanczos')
    resample = FILTERS.get(name)
    if resample is None:
        print("unknown filter %r - choose one of: %s" % (name, ', '.join(FILTERS)))
        sys.exit(2)

    if not os.path.isdir(HIGH):
        print("no highres/ folder at %s - draw your art there first." % HIGH)
        sys.exit(1)
    sources = sorted(f for f in os.listdir(HIGH) if f.lower().endswith('.png'))
    if not sources:
        print("highres/ has no PNGs yet - nothing to scale.")
        return

    os.makedirs(LOW, exist_ok=True)
    made = 0
    for fn in sources:
        src = os.path.join(HIGH, fn)
        try:
            img = Image.open(src)
        except Exception as e:
            print("  skip %s (cannot open: %s)" % (fn, e))
            continue
        w, h = img.size
        if abs((w / h) - CANVAS_ASPECT) > 0.01:
            print("  WARNING %s is %dx%d - not the %d:%d canvas shape; it will be"
                  " squashed to fit." % (fn, w, h, avatar.GRID_W, avatar.GRID_H))
        _downscale(img, (LOW_W, LOW_H), resample).save(os.path.join(LOW, fn))
        made += 1

    print("scaled %d layer(s) -> %s at %dx%d (%s)" % (made, LOW, LOW_W, LOW_H, name))


if __name__ == '__main__':
    main()

"""CONCEPT ART generator - developer tool, for LOCAL TESTING ONLY.

This renders the concept owl and concept accessories (assets/concept_art.py) to
throwaway PNGs in payload/avatar_assets/, so you can test the dress-up system
with visible art before the real, hand-drawn art exists. DO NOT SHIP these PNGs.

The finished art will be hand-drawn PNGs placed in avatar_assets/ by hand; when
they are there, this script is not needed - run assets/gen_avatar.py to embed
them into the phone page.

Run from the repo root:  python3 assets/gen_concept_art.py
To undo (return to the placeholder):  rm -rf payload/avatar_assets/highres \
    payload/avatar_assets/lowres  &&  python3 assets/gen_avatar.py
"""
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'payload'))

import concept_art  # noqa: E402
import gen_avatar    # noqa: E402  (reused for the embedding step)

ASSETS = os.path.join(ROOT, 'payload', 'avatar_assets')
HIGH_SCALE = 6    # 64x84 -> 384x504, crisp on a phone
LOW_SCALE = 2     # 64x84 -> 128x168, sized for the Pager


def grid_to_image(grid, scale):
    img = Image.new("RGBA", (concept_art.GRID_W, concept_art.GRID_H), (0, 0, 0, 0))
    px = img.load()
    for y in range(concept_art.GRID_H):
        for x in range(concept_art.GRID_W):
            ch = grid[y][x]
            if ch != '.' and ch in concept_art.COLORS:
                px[x, y] = concept_art.COLORS[ch] + (255,)
    return img.resize((concept_art.GRID_W * scale, concept_art.GRID_H * scale),
                      Image.NEAREST)


def layer_grids():
    grids = {'base': concept_art.base_grid()}
    for item_id in concept_art._STAMPS:
        grids[item_id] = concept_art.stamp_grid(item_id)
    return grids


if __name__ == '__main__':
    problems = concept_art.check_layout()
    if problems:
        print("WARNING: concept stamps outside their slot boxes:", problems)
    grids = layer_grids()
    for res, scale in (('highres', HIGH_SCALE), ('lowres', LOW_SCALE)):
        d = os.path.join(ASSETS, res)
        os.makedirs(d, exist_ok=True)
        for name, grid in grids.items():
            grid_to_image(grid, scale).save(os.path.join(d, name + '.png'))
    print("wrote concept PNGs to", ASSETS, "(for testing only - do not ship)")
    gen_avatar.write_manifest()
    n = gen_avatar.embed_index()
    print("embedded %d concept layers into the phone page" % n)

"""CONCEPT ART - developer tool, NOT shipped and NOT final art.

This draws the placeholder concept owl and its concept accessories as character
grids, from which assets/gen_concept_art.py can render throwaway PNGs for local
testing. The finished art will be hand-drawn PNGs dropped into avatar_assets/;
this file only exists so the dress-up system has *something* to show before then.

It reads the slot system (canvas size, slots, z-order, catalogue) from
avatar.py, so the two never disagree. Nothing here ships with the payload.
"""

import avatar

GRID_W, GRID_H = avatar.GRID_W, avatar.GRID_H   # the shared art canvas (64x84)
OWL_W, OWL_H = 24, 34          # the owl's own small grid
PAD = 3                        # the 18-wide head sits inset on the 24-wide owl
SCALE_UP = 2                   # owl blocks are 2x2 canvas cells
OX, OY = 8, 6                  # owl top-left on the canvas

_HEAD = [
    "..KK..........KK..",
    ".KbK..........KbK.",
    ".KbbK........KbbK.",
    "KGbbKKKKKKKKKKbbGK",
    "KGGbBBBBBBBBBBbGGK",
    "KGGBBGGBBBBGGBBGGK",
    "KGBBGGGBBBBGGGBBGK",
    "KGBKYYKBBBBKYYKBGK",
    "KGBKYEKBBBBKYEKBGK",
    "KGBKYYKBBBBKYYKBGK",
    "KGBBGGBBOOBBGGBBGK",
    "KGGBBBBBKOKBBBBGGK",
    "KGGGBBBBKKBBBBGGGK",
    ".KGGBBBBBBBBBBGGK.",
]

COLORS = {
    'K': (0x11, 0x11, 0x11), 'b': (0x5a, 0x3a, 0x1c), 'B': (0x8a, 0x5a, 0x2b),
    'G': (0x9a, 0x93, 0x8a), 'Y': (0xff, 0xc1, 0x07), 'E': (0x0a, 0x0a, 0x0a),
    'O': (0xe0, 0xac, 0x00), 'C': (0xd8, 0xc4, 0xa0), 'S': (0x5a, 0x3a, 0x1c),
    'L': (0xbf, 0xe3, 0xff), 'R': (0xd6, 0x33, 0x3a), 'W': (0xf7, 0xf3, 0xea),
    'D': (0x22, 0x20, 0x1e), 'M': (0xc2, 0xc6, 0xce), 'N': (0x2f, 0x53, 0xa8),
    'A': (0xff, 0x8c, 0x1a), 'g': (0x6b, 0x64, 0x5c),
}


def _blank():
    return [['.'] * GRID_W for _ in range(GRID_H)]


def _owl_local():
    g = [['.'] * OWL_W for _ in range(OWL_H)]
    for y, row in enumerate(_HEAD):
        for x, ch in enumerate(row):
            g[y][x + PAD] = ch
    center = 11.5
    body_rows = OWL_H - len(_HEAD) - 2
    for i in range(body_rows):
        y = len(_HEAD) + i
        t = i / max(1, body_rows - 1)
        half = 7.5 + 2.0 * (1 - (2 * t - 1) ** 2) - 2.5 * t
        left = int(round(center - half))
        right = int(round(center + half))
        for x in range(left, right + 1):
            g[y][x] = 'B'
        g[y][left] = g[y][right] = 'K'
        if i < body_rows - 2:
            g[y][left + 1] = g[y][right - 1] = 'b'
        for x in range(int(center) - 2, int(center) + 3):
            g[y][x] = 'C'
        if i % 2 == 0:
            g[y][int(center) - 1] = 'S'
            g[y][int(center) + 1] = 'S'
    fy = OWL_H - 2
    for x in range(6, 18):
        g[fy + 1][x] = 'b'
    for fx in (9, 14):
        g[fy][fx] = 'O'
        g[fy + 1][fx - 1] = 'O'
        g[fy + 1][fx + 1] = 'O'
    return g


def base_grid():
    g = _blank()
    owl = _owl_local()
    for y in range(OWL_H):
        for x in range(OWL_W):
            ch = owl[y][x]
            if ch == '.':
                continue
            for dy in range(SCALE_UP):
                for dx in range(SCALE_UP):
                    g[OY + y * SCALE_UP + dy][OX + x * SCALE_UP + dx] = ch
    return g


def _band(y, x0, x1, ch):
    return [(x, y, ch) for x in range(x0, x1 + 1)]


def _rect(x0, y0, x1, y1, ch):
    return [(x, y, ch) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


def _disc(cx, cy, r, fill, outline=None):
    cells = []
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            d = (x - cx) ** 2 + (y - cy) ** 2
            if d <= r * r:
                ch = fill
                if outline is not None and d > (r - 1) * (r - 1):
                    ch = outline
                cells.append((x, y, ch))
    return cells


def _build_jester():
    cells = []
    dome = {11: (24, 38), 12: (22, 40), 13: (20, 42), 14: (19, 43),
            15: (18, 44), 16: (17, 45), 17: (17, 45)}
    for y, (x0, x1) in dome.items():
        for x in range(x0, x1 + 1):
            cells.append((x, y, 'R' if ((x // 2) + (y // 2)) % 2 else 'Y'))
    left = [(18, 12), (17, 11), (16, 10), (15, 10), (14, 11), (13, 12)]
    centre = [(30, 11), (31, 11), (30, 10), (31, 10), (30, 9), (31, 9), (31, 8)]
    right = [(44, 12), (45, 11), (46, 10), (47, 10), (48, 11), (49, 12)]
    for i, (x, y) in enumerate(left):
        cells.append((x, y, 'R' if i % 2 else 'Y'))
    for i, (x, y) in enumerate(centre):
        cells.append((x, y, 'Y' if i % 2 else 'R'))
    for i, (x, y) in enumerate(right):
        cells.append((x, y, 'R' if i % 2 else 'Y'))
    cells += _disc(12, 13, 1, 'W') + _disc(31, 7, 1, 'W') + _disc(50, 13, 1, 'W')
    return cells


_STAMPS = {
    'hardhat': (
        [(x, 18, 'O') for x in range(8, 55)] + [(x, 19, 'O') for x in range(8, 55)]
        + _band(17, 12, 50, 'Y') + _band(16, 13, 49, 'Y') + _band(15, 15, 47, 'Y')
        + _band(14, 17, 45, 'Y') + _band(13, 19, 43, 'Y') + _band(12, 21, 41, 'Y')
        + _band(11, 23, 39, 'Y') + _band(10, 25, 37, 'Y') + _band(9, 27, 35, 'Y')
        + _band(8, 29, 33, 'Y')
        + [(30, y, 'K') for y in range(8, 18)] + [(31, y, 'K') for y in range(8, 18)]
    ),
    'fedora': (
        [(x, 17, 'D') for x in range(6, 57)] + [(x, 18, 'D') for x in range(6, 57)]
        + [(6, 16, 'D'), (7, 16, 'D'), (55, 16, 'D'), (56, 16, 'D')]
        + _band(16, 18, 44, 'R')
        + _band(15, 18, 44, 'D') + _band(14, 19, 43, 'D') + _band(13, 20, 42, 'D')
        + _band(12, 21, 41, 'D') + _band(11, 22, 40, 'D') + _band(10, 23, 39, 'D')
        + _band(9, 25, 37, 'D') + _band(8, 27, 35, 'D')
        + [(30, 8, 'K'), (31, 8, 'K')]
    ),
    'jester': _build_jester(),
    'round_glasses': (
        _disc(23, 23, 3, 'L', 'K') + _disc(37, 23, 3, 'L', 'K')
        + _band(23, 27, 33, 'K')
        + [(19, 23, 'K'), (18, 23, 'K'), (41, 23, 'K'), (42, 23, 'K')]
    ),
    'square_glasses': (
        _rect(20, 20, 26, 24, 'K') + _rect(22, 21, 24, 23, 'L')
        + _rect(34, 20, 40, 24, 'K') + _rect(36, 21, 38, 23, 'L')
        + _band(22, 27, 33, 'K')
        + [(19, 22, 'K'), (18, 22, 'K'), (41, 22, 'K'), (42, 22, 'K')]
    ),
    'sunglasses': (
        _rect(19, 20, 26, 24, 'D') + _rect(34, 20, 41, 24, 'D')
        + _band(20, 27, 33, 'D')
        + [(21, 21, 'L'), (36, 21, 'L')]
        + [(18, 20, 'D'), (42, 20, 'D'), (43, 20, 'D')]
    ),
    'eyepatch_l': (
        _rect(19, 20, 27, 25, 'D')
        + _band(20, 28, 45, 'K') + [(18, 21, 'K')]
    ),
    'eyepatch_r': (
        _rect(33, 20, 41, 25, 'D')
        + _band(20, 18, 32, 'K') + [(42, 21, 'K')]
    ),
    'tie': (
        _rect(29, 30, 33, 32, 'N')
        + _rect(30, 33, 32, 42, 'N')
        + [(29, 43, 'N'), (33, 43, 'N'), (30, 43, 'N'), (31, 43, 'N'), (32, 43, 'N'),
           (30, 44, 'N'), (31, 44, 'N'), (32, 44, 'N'), (31, 45, 'N')]
    ),
    'goldchain': (
        [(26, 31, 'Y'), (36, 31, 'Y'), (27, 32, 'Y'), (35, 32, 'Y'),
         (28, 33, 'Y'), (34, 33, 'Y'), (29, 34, 'Y'), (33, 34, 'Y'),
         (30, 35, 'Y'), (32, 35, 'Y')]
        + _disc(31, 37, 2, 'O', 'Y')
    ),
    'lanyard': (
        [(27, 30, 'N'), (27, 31, 'N'), (28, 32, 'N'), (28, 33, 'N'), (29, 34, 'N'),
         (35, 30, 'N'), (35, 31, 'N'), (34, 32, 'N'), (34, 33, 'N'), (33, 34, 'N')]
        + _rect(29, 35, 33, 42, 'W')
        + [(30, 35, 'N'), (31, 35, 'N'), (32, 35, 'N')]
        + _band(38, 30, 32, 'g') + _band(40, 30, 32, 'g')
    ),
    'cane': (
        [(5, 34, 'M'), (6, 33, 'M'), (7, 33, 'M'), (8, 34, 'M'), (9, 34, 'M'),
         (6, 34, 'M')]
        + [(7, y, 'M') for y in range(35, 73)] + [(8, y, 'M') for y in range(35, 73)]
        + [(7, 73, 'D'), (8, 73, 'D')]
    ),
    'sword': (
        [(7, y, 'M') for y in range(40, 65)] + [(8, y, 'M') for y in range(40, 65)]
        + [(8, y, 'W') for y in range(42, 64, 3)]
        + [(7, 39, 'M'), (7, 38, 'M')]
        + _band(65, 5, 10, 'K')
        + _rect(7, 66, 8, 73, 'D')
        + [(7, 68, 'Y'), (8, 70, 'Y')]
    ),
    'coffee': (
        _rect(4, 44, 11, 45, 'W') + _rect(5, 46, 10, 54, 'W') + _band(55, 6, 9, 'W')
        + _rect(4, 42, 11, 43, 'D') + [(7, 41, 'D')]
        + _band(49, 5, 10, 'b') + _band(50, 5, 10, 'b')
        + [(7, 51, 'A')]
        + [(7, 40, 'W'), (6, 39, 'W'), (8, 38, 'W'), (7, 37, 'W')]
    ),
    'flipper': (
        _rect(3, 44, 12, 60, 'W')
        + _rect(4, 45, 11, 50, 'A')
        + _rect(5, 46, 10, 49, 'K') + [(6, 47, 'L')]
        + [(7, 54, 'D'), (6, 55, 'D'), (8, 55, 'D'), (7, 56, 'D'), (7, 55, 'g')]
        + [(7, 58, 'A')]
    ),
    'pager': (
        _rect(3, 42, 12, 60, 'g')
        + _rect(4, 44, 11, 52, 'Y')
        + _band(46, 6, 9, 'K') + _band(48, 6, 9, 'K')
        + [(5, 55, 'K'), (7, 55, 'K'), (9, 55, 'K'), (6, 57, 'K'), (8, 57, 'K')]
        + [(4, 41, 'K'), (4, 40, 'K'), (4, 39, 'D')]
    ),
    'clownshoes': (
        _rect(20, 78, 34, 81, 'R') + [(19, 79, 'R'), (19, 80, 'R')]
        + [(20, 78, 'W'), (21, 78, 'W'), (19, 79, 'W')]
        + _band(82, 19, 34, 'K')
        + _rect(36, 78, 50, 81, 'R') + [(51, 79, 'R'), (51, 80, 'R')]
        + [(49, 78, 'W'), (50, 78, 'W'), (51, 79, 'W')]
        + _band(82, 36, 51, 'K')
        + _rect(26, 74, 27, 77, 'R') + _rect(36, 74, 37, 77, 'R')
    ),
    'skateboard': (
        _band(79, 20, 52, 'D') + _band(80, 20, 52, 'D')
        + [(18, 78, 'D'), (19, 78, 'D'), (53, 78, 'D'), (54, 78, 'D')]
        + [(24, 81, 'O'), (25, 81, 'O'), (47, 81, 'O'), (48, 81, 'O')]
        + [(24, 80, 'g'), (48, 80, 'g')]
    ),
    'fish': (
        [(31, 71, 'M'), (31, 72, 'M'), (31, 73, 'M')]
        + _rect(26, 75, 37, 80, 'A')
        + [(23, 75, 'A'), (23, 80, 'A'), (24, 76, 'A'), (24, 79, 'A'), (25, 77, 'A'),
           (25, 78, 'A')]
        + [(30, 74, 'A'), (31, 74, 'A'), (32, 74, 'A')]
        + [(30, 81, 'A'), (31, 81, 'A'), (32, 81, 'A')]
        + [(36, 77, 'K')]
        + [(28, 78, 'O'), (31, 79, 'O'), (34, 78, 'O')]
    ),
}


def stamp_grid(item_id):
    g = _blank()
    for x, y, ch in _STAMPS[item_id]:
        if 0 <= x < GRID_W and 0 <= y < GRID_H:
            g[y][x] = ch
    return g


def compose(equipped):
    g = base_grid()
    for slot in avatar.ZORDER:
        item_id = equipped.get(slot)
        if not item_id or item_id not in _STAMPS:
            continue
        for x, y, ch in _STAMPS[item_id]:
            if 0 <= x < GRID_W and 0 <= y < GRID_H:
                g[y][x] = ch
    return g


def check_layout():
    """Prove every concept stamp stays inside its slot's box."""
    problems = []
    for item in avatar.CATALOG:
        x0, y0, x1, y1 = avatar.SLOT_BOX[item['slot']]
        for x, y, ch in _STAMPS[item['id']]:
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                problems.append((item['id'], x, y))
    return problems

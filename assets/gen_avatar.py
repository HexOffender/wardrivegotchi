"""Wire the avatar art into the phone page. Run this after you add or change
the PNGs in payload/avatar_assets/.

It does two things:

  1. Writes payload/avatar_assets/manifest.json - the drop-in contract: the
     canvas size, the z-order, the slot of each item, and the slot boxes.

  2. Rewrites the AVATAR block in gps-server/index.html. It always embeds the
     slot metadata (so the page can draw the placeholder), and, for every
     high-res layer PNG that exists, embeds it as a data URI so the page is
     self-contained. With no PNGs present, the page shows the placeholder.

The art contract: transparent PNGs on the GRID_W x GRID_H canvas, named
base.png plus <item_id>.png, in avatar_assets/highres/ (phone) and
avatar_assets/lowres/ (Pager). Same names, same transparency, same registration.
Replacing the files reskins the avatar with no code change.

Run from the repo root:  python3 assets/gen_avatar.py
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'payload'))

import avatar  # noqa: E402

ASSETS = os.path.join(ROOT, 'payload', 'avatar_assets')
HIGH = os.path.join(ASSETS, 'highres')
INDEX = os.path.join(ROOT, 'gps-server', 'index.html')

LAYER_NAMES = ['base'] + [it['id'] for it in avatar.CATALOG]


def write_manifest():
    manifest = {
        'canvas': [avatar.GRID_W, avatar.GRID_H],
        'zorder': avatar.ZORDER,
        'slots': {it['id']: it['slot'] for it in avatar.CATALOG},
        'slot_box': avatar.SLOT_BOX,
        'names': {it['id']: it['name'] for it in avatar.CATALOG},
        'layers': LAYER_NAMES,
        'note': 'Transparent full-canvas PNG layers. Drop art into highres/ and '
                'lowres/ using these names to reskin; keep the transparency and '
                'the registration. No code change needed.',
    }
    os.makedirs(ASSETS, exist_ok=True)
    with open(os.path.join(ASSETS, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)


def data_uri(path):
    with open(path, 'rb') as f:
        return 'data:image/png;base64,' + base64.b64encode(f.read()).decode()


def embed_index():
    layers = {}
    if os.path.isdir(HIGH):
        for name in LAYER_NAMES:
            p = os.path.join(HIGH, name + '.png')
            if os.path.isfile(p):
                layers[name] = data_uri(p)

    js = ['window.AVATAR = {',
          '  canvas: %s,' % json.dumps([avatar.GRID_W, avatar.GRID_H]),
          '  zorder: %s,' % json.dumps(avatar.ZORDER),
          '  slots: %s,' % json.dumps({it['id']: it['slot'] for it in avatar.CATALOG}),
          '  slot_box: %s,' % json.dumps(avatar.SLOT_BOX),
          '  names: %s,' % json.dumps({it['id']: it['name'] for it in avatar.CATALOG}),
          '  layers: {']
    for name, uri in layers.items():
        js.append('    "%s": "%s",' % (name, uri))
    js += ['  }', '};']
    blob = "<script>\n" + "\n".join(js) + "\n</script>"

    start, end = "<!-- AVATAR_LAYERS_START -->", "<!-- AVATAR_LAYERS_END -->"
    # Read/write as UTF-8 explicitly: the page has non-ASCII characters, and the
    # platform default (cp1252 on Windows) fails on them. newline='' keeps the
    # file's existing line endings from being rewritten.
    with open(INDEX, encoding='utf-8') as f:
        html = f.read()
    block = start + "\n" + blob + "\n" + end
    if start in html and end in html:
        html = html[:html.index(start)] + block + html[html.index(end) + len(end):]
    elif "</head>" in html:
        html = html.replace("</head>", block + "\n</head>", 1)
    else:
        html = block + "\n" + html
    with open(INDEX, "w", encoding='utf-8', newline='') as f:
        f.write(html)
    return len(layers)


if __name__ == '__main__':
    write_manifest()
    n = embed_index()
    if n:
        print("embedded %d art layers into %s" % (n, INDEX))
    else:
        print("no art layers found - the page will draw the placeholder")

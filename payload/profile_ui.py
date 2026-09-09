"""The progression screens on the Pager itself.

Not everyone drives with a phone. A user with a GPS module sees the same level,
experience, credits and shop here, drawn in the app palette with the same
filled-block buttons as the rest of the UI.

show() runs its own input loop and returns when the user backs out. It draws on
the main thread, the same thread that owns the player, so it reads and changes
the player directly with no lock.
"""

import time

import achievements
import avatar
import blocks
import palette
from config import FONT_MENU, FONT_TITLE, SCREEN_H, SCREEN_W


# Drawing the placeholder owl cell by cell is thousands of fill_rect calls per
# frame, which is what makes the profile and shop screens lag. Coalesce each row
# into horizontal runs of one colour, cache the runs by what is equipped (they
# change only when an item is worn or removed), and cache the pager's resolved
# colours. A redraw then replays a few hundred rectangles instead of thousands.
_run_cache = {}
_rgb_cache = {}


def _placeholder_runs(equipped):
    key = tuple(sorted((slot, item) for slot, item in equipped.items() if item))
    runs = _run_cache.get(key)
    if runs is None:
        grid = avatar.placeholder_grid(equipped)
        runs = []
        for gy, row in enumerate(grid):
            gx, width = 0, len(row)
            while gx < width:
                ch = row[gx]
                if avatar.PH_COLORS.get(ch) is None:
                    gx += 1
                    continue
                gx2 = gx + 1
                while gx2 < width and row[gx2] == ch:
                    gx2 += 1
                runs.append((gx, gy, gx2 - gx, ch))
                gx = gx2
        _run_cache[key] = runs
    return runs


def _rgb_map(pager):
    m = _rgb_cache.get(id(pager))
    if m is None:
        m = {ch: pager.rgb(*rgb) for ch, rgb in avatar.PH_COLORS.items()
             if rgb is not None}
        _rgb_cache[id(pager)] = m
    return m


def show(pager, player, db_stats, use_png=True):
    """Show the profile screen. RIGHT opens the shop; B or LEFT returns."""
    while True:
        _draw_profile(pager, player, db_stats, use_png)
        button = pager.wait_button()
        if button & (pager.BTN_B | pager.BTN_LEFT):
            return
        if button & (pager.BTN_RIGHT | pager.BTN_A):
            _shop(pager, player, use_png)


def _draw_avatar(pager, player, ox, oy, scale=2, use_png=True):
    """Draw the owl at (ox, oy), wearing what is equipped.

    `scale` is the pixels per avatar-grid cell. The canvas is 64x84, so scale 2
    draws a 128x168 owl - large enough to read the items, small enough to leave
    the left of the screen for the stats.

    Prefers pre-rendered PNG layers (the artist's art); falls back to the
    placeholder owl if the assets are absent or fail to draw, so the avatar
    always appears."""
    w, h = avatar.GRID_W * scale, avatar.GRID_H * scale
    if use_png:
        paths = avatar.layer_paths(player.equipped, res='lowres')
        if paths:
            ok = True
            for i, p in enumerate(paths):
                rc = pager.draw_image_file_scaled(ox, oy, w, h, p)
                if i == 0 and rc not in (0, None):
                    ok = False       # base failed -> use the placeholder instead
                    break
            if ok:
                return
    # No art yet: draw the placeholder silhouette with worn-slot markers, from
    # cached horizontal runs so a redraw is cheap.
    rgb_map = _rgb_map(pager)
    for x, y, run_w, ch in _placeholder_runs(player.equipped):
        pager.fill_rect(ox + x * scale, oy + y * scale, run_w * scale, scale,
                        rgb_map[ch])


def _text(pager, x, y, s, colour, font, size):
    pager.draw_ttf(x, y, s, palette.rgb(pager, colour), font, size)


def _draw_profile(pager, player, db_stats, use_png=True):
    blocks.background(pager)
    prog = player.progress()

    # The owl on the right, wearing whatever is equipped.
    aw = avatar.GRID_W * 2
    ax = SCREEN_W - aw - 12
    _draw_avatar(pager, player, ax, 8, scale=2, use_png=use_png)

    # Level badge and credits, top left.
    blocks.text_button(pager, 20, 20, "LVL %d" % prog['level'], FONT_TITLE, 24, pad_y=4)
    _text(pager, 20, 58, "%d credits" % player.credits, palette.INK, FONT_MENU, 16)

    # The earned title and the achievement count, beside the badge.
    title = player.title
    n_ach = "%d/%d achv" % (len(player.unlocked), len(achievements.CATALOG))
    if title:
        _text(pager, 130, 24, title, palette.ACCENT, FONT_MENU, 14)
        _text(pager, 130, 46, n_ach, palette.INK_MUTED, FONT_MENU, 13)
    else:
        _text(pager, 130, 34, n_ach, palette.INK_MUTED, FONT_MENU, 13)

    # Experience bar under the badge, on the left half.
    bx, by, bw, bh = 20, 80, ax - 36, 18
    pager.fill_rect(bx, by, bw, bh, palette.rgb(pager, palette.SURFACE))
    if prog['span']:
        pager.fill_rect(bx, by, int(bw * prog['into'] / prog['span']), bh,
                        palette.rgb(pager, palette.BRAND))
    pager.rect(bx, by, bw, bh, palette.rgb(pager, palette.INK))
    xp = "%d / %d XP" % (prog['into'], prog['span'])
    _text(pager, bx + 4, by + 2, xp, palette.INK, FONT_MENU, 13)

    # Statistics in one left column, clear of the owl.
    c = player.counters
    rows = [
        ("APs", db_stats.get('total', 0)),
        ("WPA3", db_stats.get('wpa3', 0)),
        ("Open", db_stats.get('open', 0)),
        ("Handshakes", db_stats.get('handshakes', 0)),
        ("Best run", c.get('best_session_aps', 0)),
    ]
    y = 108
    for label, value in rows:
        _text(pager, 24, y, label.upper(), palette.INK_MUTED, FONT_MENU, 12)
        _text(pager, 150, y - 2, str(value), palette.INK, FONT_MENU, 15)
        y += 19

    _text(pager, 20, SCREEN_H - 20, "B Back", palette.INK_MUTED, FONT_MENU, 13)
    hint = "Shop >"
    hw = pager.ttf_width(hint, FONT_MENU, 13)
    _text(pager, SCREEN_W - hw - 20, SCREEN_H - 20, hint, palette.INK_MUTED, FONT_MENU, 13)
    pager.flip()


def _shop(pager, player, use_png=True):
    """List shop items with a live owl preview and a scrolling window. A buys,
    then toggles worn; UP/DOWN move and scroll the list; B or LEFT returns."""
    from player import SHOP
    selected = 0
    scroll = 0
    message = ""

    row_h = 22
    top = 48
    max_visible = max(1, (SCREEN_H - 44 - top) // row_h)

    while True:
        blocks.background(pager)

        _text(pager, 20, 16, "SHOP", palette.ACCENT, FONT_TITLE, 24)
        _text(pager, 150, 22, "%d cr" % player.credits, palette.INK, FONT_MENU, 16)

        # Live preview of the owl, so equipping shows immediately.
        aw = avatar.GRID_W * 2
        _draw_avatar(pager, player, SCREEN_W - aw - 12, 20, scale=2, use_png=use_png)

        # Keep the selected row inside the visible window.
        if selected < scroll:
            scroll = selected
        elif selected >= scroll + max_visible:
            scroll = selected - max_visible + 1

        y = top
        for i in range(scroll, min(scroll + max_visible, len(SHOP))):
            item = SHOP[i]
            owned = item['id'] in player.inventory
            worn = player.equipped.get(item['slot']) == item['id']
            if worn:
                row = "%s  [worn]" % item['name']
            elif owned:
                row = "%s  owned" % item['name']
            else:
                row = "%s  %d cr" % (item['name'], item['cost'])
            if i == selected:
                blocks.text_button(pager, 24, y, row, FONT_MENU, 15, pad_y=2)
            else:
                colour = palette.INK if not owned else palette.INK_MUTED
                _text(pager, 24, y, row, colour, FONT_MENU, 15)
            y += row_h

        # A scrollbar when the list is taller than the visible window.
        if len(SHOP) > max_visible:
            track_x, track_h = 300, max_visible * row_h
            pager.fill_rect(track_x, top, 4, track_h, palette.rgb(pager, palette.FILL))
            thumb_h = max(12, track_h * max_visible // len(SHOP))
            max_scroll = len(SHOP) - max_visible
            frac = scroll / max_scroll if max_scroll else 0
            thumb_y = top + int((track_h - thumb_h) * frac)
            pager.fill_rect(track_x, thumb_y, 4, thumb_h, palette.rgb(pager, palette.INK))

        if message:
            _text(pager, 24, SCREEN_H - 40, message, palette.INK, FONT_MENU, 13)
        _text(pager, 20, SCREEN_H - 20, "B Back", palette.INK_MUTED, FONT_MENU, 13)
        _text(pager, SCREEN_W - 150, SCREEN_H - 20, "A Buy / Wear",
              palette.INK_MUTED, FONT_MENU, 13)
        pager.flip()

        button = pager.wait_button()
        if button & (pager.BTN_B | pager.BTN_LEFT):
            return
        if button & pager.BTN_UP:
            selected = (selected - 1) % len(SHOP)
            message = ""
        elif button & pager.BTN_DOWN:
            selected = (selected + 1) % len(SHOP)
            message = ""
        elif button & pager.BTN_A:
            item = SHOP[selected]
            if item['id'] not in player.inventory:
                ok, message = player.buy(item['id'])
            elif player.equipped.get(item['slot']) == item['id']:
                ok, message = player.unequip(item['slot'])
            else:
                ok, message = player.equip(item['id'])
            _beep(pager, ok)


def _beep(pager, ok):
    try:
        pager.beep(1000 if ok else 300, 120)
    except Exception:
        pass

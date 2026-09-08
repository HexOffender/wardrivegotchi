"""Filled blocks for the Pager screen.

The palette treats the accent as a fill that you put dark ink on. It is not a
text colour: as text on the paper background it measures about 1.9:1. Thus a
screen cannot show emphasis with colour alone. A filled block is the strong
signal, and it is the same mark as the buttons on the phone page: a flat fill,
a hard ink border, and a solid offset block behind it with no blur.

Use a block for a selected menu item or a button. Keep the text colours for
information, not for emphasis.

The `y` value is the top of the text, not its baseline. Refer to the note in
`text_button`.
"""

from config import SCREEN_H, SCREEN_W

import palette

# Defaults for a dense menu. The rows of a menu are 24 pixels apart and the
# text is 18 pixels high, thus the padding and the offset must stay small. A
# larger block touches the row above it.
BORDER = 2
OFFSET = 2
PAD_X = 10
PAD_Y = 2


def block(pager, x, y, w, h, fill=palette.BRAND, offset=OFFSET, border=BORDER):
    """Draw an empty block. Draw the label on top in palette.ON_ACCENT."""
    ink = palette.rgb(pager, palette.INK)

    # The offset block first, then the face on top of it.
    pager.fill_rect(x + offset, y + offset, w, h, ink)
    pager.fill_rect(x, y, w, h, palette.rgb(pager, fill))

    # The border. The library draws an outline one pixel wide, thus a thicker
    # border is more than one rectangle.
    for i in range(border):
        pager.rect(x + i, y + i, w - 2 * i, h - 2 * i, ink)


def text_button(pager, x, y, label, font, size, fill=palette.BRAND,
                pad_x=PAD_X, pad_y=PAD_Y, offset=OFFSET):
    """Draw a block behind a label, then the label in ink.

    `x` and `y` are the position of the label without a block. Thus you can add
    a block to text that exists and the text does not move.

    Returns the position and the size of the block.
    """
    tw = pager.ttf_width(label, font, size)
    th = text_height(pager, font, size)

    bx = x - pad_x
    by = y - pad_y
    bw = tw + pad_x * 2
    bh = th + pad_y * 2

    block(pager, bx, by, bw, bh, fill, offset)
    pager.draw_ttf(x, y, label, palette.rgb(pager, palette.ON_ACCENT), font, size)

    return bx, by, bw, bh


def centered_button(pager, screen_w, y, label, font, size, **kwargs):
    """Draw a block and its label in the centre of the screen."""
    tw = pager.ttf_width(label, font, size)
    return text_button(pager, (screen_w - tw) // 2, y, label, font, size, **kwargs)


def text_height(pager, font, size):
    """Get the height of the text in pixels.

    The library gives the true height. If the call fails, the font size is a
    sufficient estimate.
    """
    try:
        h = pager.ttf_height(font, size)
        if h and h > 0:
            return h
    except Exception:
        pass
    return size


def background(pager, image=None):
    """Draw the screen background.

    The palette is dark ink on a light ground, thus the ground must be light
    before a screen draws anything. A black fallback makes every text colour
    unreadable, thus there is no black fallback.

    This draws the ground with primitives and not with an image. The dashboard
    redraws about ten times each second, and an image costs a file read, a PNG
    decode and a scale on each of those frames. Six rectangles cost almost
    nothing. Supply `image` only if you want a custom background: the cost is
    then yours to accept.
    """
    if image:
        try:
            pager.draw_image_file_scaled(0, 0, SCREEN_W, SCREEN_H, image)
            return
        except Exception:
            # Fall through to the primitives, which cannot fail.
            pass

    ink = palette.rgb(pager, palette.INK)

    pager.fill_rect(0, 0, SCREEN_W, SCREEN_H, palette.rgb(pager, palette.PAPER))

    # One accent rule across the top, under an ink line.
    pager.fill_rect(0, 0, SCREEN_W, 8, palette.rgb(pager, palette.BRAND))
    pager.fill_rect(0, 8, SCREEN_W, 3, ink)

    # A three pixel frame.
    for i in range(3):
        pager.rect(i, i, SCREEN_W - 2 * i, SCREEN_H - 2 * i, ink)

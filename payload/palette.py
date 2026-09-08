"""The screen palette, in one place.

Every screen used to declare its own literal colours. That is how the settings
menu kept drawing white text after the dashboard moved to a light background:
the two screens had no shared definition to change. Import from here instead of
writing rgb() literals.

The values come from the neo-brutalist palette that the phone page also uses.
They are the on-surface variants, not the accent fills. #ffc107 is a fill that
you put dark ink on top of; as text on paper it measures about 1.9:1. The golds
below are the same hue, dark enough to read.

There is no blue. The source palette removes blue everywhere except chart
series, and no screen here is a chart.
"""

# Ink. Body text, and the strongest mark on the screen.
INK = (0x11, 0x11, 0x11)

# Secondary text: labels, hints, unselected detail.
INK_MUTED = (0x57, 0x50, 0x4a)

# Status colours, as text on a light ground.
OK = (0x14, 0x66, 0x3a)
BAD = (0x9e, 0x26, 0x17)

# The two golds, exactly as the source palette defines them.
#
# ACCENT_ALT is a fill and large-mark colour, not body text: on the paper
# background it measures 3.24:1. Do not use it for small text. Where a screen
# needs emphasis, use a filled block from blocks.py instead of a colour.
ACCENT = (0x7a, 0x5b, 0x00)
ACCENT_ALT = (0xa8, 0x7f, 0x00)

# Fills, and the ink that goes on them. BRAND is the accent fill: dark ink on
# top of it, never the reverse. SURFACE is the face of an unselected button.
BRAND = (0xff, 0xc1, 0x07)
SURFACE = (0xff, 0xff, 0xff)
ON_ACCENT = (0x11, 0x11, 0x11)

# Surfaces. PAPER is the page. FILL is for bars and blocks drawn on it.
PAPER = (0xf5, 0xf0, 0xe6)
FILL = (0xe7, 0xe2, 0xd6)


def rgb(pager, colour):
    """Convert a palette colour into a pager colour value."""
    return pager.rgb(*colour)

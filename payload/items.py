"""The item registry - the single place that lists every wearable item.

To add an item, add ONE line to CATALOG below. Nothing else needs editing: the
shop, the inventory, the Pager avatar and the phone page all read from here, so
the item appears everywhere automatically.

Each item is a dict:

    id     Unique short identifier. Also the art file name (`<id>.png`) and the
           key stored in the player's inventory, so never change an id once it
           has shipped or players lose that item.
    name   The label shown in the shop and the inventory.
    slot   Which body slot it occupies: one of SLOTS below (head, eyes, neck,
           side, feet). At most one item per slot is worn at a time, and the
           slots never overlap, so worn items cannot clip each other.
    slots  Optional. A tuple of every slot the item spans, for items that cover
           more than one - a motorcycle helmet over ('head', 'eyes'), a onesie
           over all five. `slot` must be one of them (it is the primary slot for
           the shop filter and the art file name). Equipping the item fills all
           of its slots and removes whatever was in any of them; unequipping
           frees them all. Its art is one PNG drawn across the union of the boxes.
    cost   Credits to buy it in the shop.
    level  Minimum player level required to buy it.

Extra keys are allowed and flow through to the shop/phone untouched (e.g. add a
`'desc'` and it travels to the phone in the status snapshot), so the schema can
grow without changing any other file.

Art is optional and dropped in separately - transparent PNGs named `<id>.png`
under payload/avatar_assets/highres/ and lowres/, then `python3
assets/gen_avatar.py`. Until an item's art exists the placeholder marks its
slot. The on-canvas geometry of each slot lives in avatar.py (SLOT_BOX); see
avatar_assets/README.md for the art contract.

    # a new head item, costs 140 credits, needs level 4:
    {'id': 'tinfoil', 'name': 'Tinfoil Hat', 'slot': 'head', 'cost': 140, 'level': 4},
"""

# The valid slots. Their on-canvas geometry (where each sits on the owl) lives
# in avatar.SLOT_BOX; they are named here so the catalogue is self-contained and
# items_test.py can check every item uses a real one.
SLOTS = ('head', 'eyes', 'neck', 'side', 'feet')

CATALOG = [
    # HEAD
    {'id': 'jester', 'name': 'Jester Cap', 'slot': 'head', 'cost': 120, 'level': 3},
    {'id': 'hardhat', 'name': 'Hard Hat', 'slot': 'head', 'cost': 80, 'level': 2},
    {'id': 'fedora', 'name': 'Fedora', 'slot': 'head', 'cost': 160, 'level': 5},
    # EYES
    {'id': 'round_glasses', 'name': 'Round Glasses', 'slot': 'eyes', 'cost': 70, 'level': 2},
    {'id': 'square_glasses', 'name': 'Square Glasses', 'slot': 'eyes', 'cost': 70, 'level': 2},
    {'id': 'eyepatch_l', 'name': 'Eye Patch (L)', 'slot': 'eyes', 'cost': 90, 'level': 3},
    {'id': 'eyepatch_r', 'name': 'Eye Patch (R)', 'slot': 'eyes', 'cost': 90, 'level': 3},
    {'id': 'sunglasses', 'name': 'Sunglasses', 'slot': 'eyes', 'cost': 110, 'level': 4},
    # NECK
    {'id': 'tie', 'name': 'Tie', 'slot': 'neck', 'cost': 80, 'level': 2},
    {'id': 'goldchain', 'name': 'Gold Chain', 'slot': 'neck', 'cost': 200, 'level': 6},
    {'id': 'lanyard', 'name': 'Lanyard + Badge', 'slot': 'neck', 'cost': 120, 'level': 4},
    # SIDE
    {'id': 'pager', 'name': 'Pineapple Pager', 'slot': 'side', 'cost': 150, 'level': 5},
    {'id': 'flipper', 'name': 'Flipper Zero', 'slot': 'side', 'cost': 150, 'level': 5},
    {'id': 'coffee', 'name': 'Cup of Coffee', 'slot': 'side', 'cost': 60, 'level': 2},
    {'id': 'cane', 'name': 'Walking Cane', 'slot': 'side', 'cost': 90, 'level': 3},
    {'id': 'sword', 'name': 'Samurai Sword', 'slot': 'side', 'cost': 260, 'level': 8},
    # FEET
    {'id': 'clownshoes', 'name': 'Clown Shoes', 'slot': 'feet', 'cost': 100, 'level': 3},
    {'id': 'skateboard', 'name': 'Skateboard', 'slot': 'feet', 'cost': 180, 'level': 6},
    {'id': 'fish', 'name': 'Fresh Catch', 'slot': 'feet', 'cost': 140, 'level': 4},
    # MULTI-SLOT - span several slots at once (see `slots` above).
    {'id': 'moto_helmet', 'name': 'Moto Helmet', 'slot': 'head',
     'slots': ('head', 'eyes'), 'cost': 220, 'level': 6},
    {'id': 'onesie', 'name': 'Dino Onesie', 'slot': 'neck',
     'slots': ('head', 'eyes', 'neck', 'side', 'feet'), 'cost': 400, 'level': 10},
]

# id -> item, for quick lookup.
ITEM = {it['id']: it for it in CATALOG}


def get(item_id):
    """The item dict for an id, or None."""
    return ITEM.get(item_id)


def all_ids():
    """Every item id, in catalogue order."""
    return [it['id'] for it in CATALOG]


def slots_of(item):
    """Every slot an item occupies: just its `slot`, unless it lists `slots` to
    span several (a helmet over head+eyes, a onesie over all five)."""
    return tuple(item['slots']) if item.get('slots') else (item['slot'],)


def for_slot(slot):
    """Every item that occupies a slot (including multi-slot items that span it),
    in catalogue order."""
    return [it for it in CATALOG if slot in slots_of(it)]


def validate(valid_slots=SLOTS):
    """Return a list of problems with the catalogue (empty means it is sound):
    duplicate ids, missing names, unknown slots, or non-int/negative cost/level.
    items_test.py runs this so a mistake in a new entry is caught immediately."""
    problems = []
    seen = set()
    for it in CATALOG:
        iid = it.get('id')
        if not iid:
            problems.append('an item is missing its id: %r' % (it,))
            continue
        if iid in seen:
            problems.append('duplicate id: %s' % iid)
        seen.add(iid)
        if not it.get('name'):
            problems.append('%s: missing name' % iid)
        if it.get('slot') not in valid_slots:
            problems.append('%s: unknown slot %r (valid: %s)' % (iid, it.get('slot'), ', '.join(valid_slots)))
        multi = it.get('slots')
        if multi is not None:
            if not isinstance(multi, (list, tuple)) or not multi:
                problems.append('%s: slots must be a non-empty list' % iid)
            else:
                for s in multi:
                    if s not in valid_slots:
                        problems.append('%s: slots has unknown slot %r' % (iid, s))
                if len(set(multi)) != len(multi):
                    problems.append('%s: slots has a duplicate: %r' % (iid, tuple(multi)))
                if it.get('slot') not in multi:
                    problems.append('%s: slot %r must be one of its slots %r' % (iid, it.get('slot'), tuple(multi)))
        for key in ('cost', 'level'):
            val = it.get(key)
            if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                problems.append('%s: %s must be a non-negative integer, got %r' % (iid, key, val))
    return problems

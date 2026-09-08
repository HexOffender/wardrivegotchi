"""Registry sanity checks. Run: python3 items_test.py

Catches mistakes in a new CATALOG entry (bad slot, duplicate id, missing name,
non-integer cost/level) so adding an item is safe.
"""
import sys

import avatar
import items

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1


def main():
    # The catalogue itself is sound, judged against the renderer's real slots.
    probs = avatar.validate_items()
    check(not probs, "catalogue valid" + ("" if not probs else ": " + "; ".join(probs)))

    ids = items.all_ids()
    check(len(ids) == len(set(ids)), "item ids are unique")
    check(all(items.get(i)['slot'] in avatar.SLOT_BOX for i in ids),
          "every item uses a slot the renderer knows")
    check(not avatar.check_slots(), "slot boxes are disjoint")

    # The shop and the avatar read the same registry object.
    import player
    check(player.SHOP is items.CATALOG, "player.SHOP is the items registry (no copy)")
    check(avatar.CATALOG is items.CATALOG, "avatar.CATALOG is the items registry")

    # Helpers behave.
    check(items.get('hardhat') is not None and items.get('nope') is None, "get() looks items up")
    check(all(it['slot'] == 'head' for it in items.for_slot('head')) and items.for_slot('head'),
          "for_slot() filters by slot")

    # validate() actually catches a bad entry.
    bad = items.CATALOG + [{'id': 'x', 'name': 'X', 'slot': 'nope', 'cost': -1, 'level': 1}]
    saved = items.CATALOG
    try:
        items.CATALOG = bad
        check(len(items.validate()) >= 2, "validate() flags a bad slot and a negative cost")
    finally:
        items.CATALOG = saved

    print("\nTOTAL FAILURES: %d" % fails)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()

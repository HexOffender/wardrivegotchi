"""Tests for the progression framework. Run: python3 player_test.py

There is no test runner on the Pager, thus this is a plain script that exits
non-zero on any failure.
"""
import os
import sys
import tempfile

import player as P

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1


def main():
    # The curve rises, and each step is larger than the last.
    reach = [P.xp_to_reach(l) for l in range(1, 7)]
    check(reach == [0, 100, 300, 600, 1000, 1500], "curve %s" % reach)
    gaps = [reach[i + 1] - reach[i] for i in range(len(reach) - 1)]
    check(gaps == sorted(gaps) and len(set(gaps)) > 1, "escalating gaps %s" % gaps)

    # The inverse agrees with the curve at the boundaries.
    check(P.level_for_xp(0) == 1, "0 xp is level 1")
    check(P.level_for_xp(99) == 1 and P.level_for_xp(100) == 2, "100 xp is level 2")
    check(P.level_for_xp(999) == 4 and P.level_for_xp(1000) == 5, "1000 xp is level 5")

    d = tempfile.mkdtemp()

    # Weighted awards: base plus the encryption bonus, one credit each.
    pl = P.Player.load(os.path.join(d, "a.json"))
    pl.seeded = True
    pl.award_aps([{'encryption': 'WPA2'}, {'encryption': 'Open'},
                  {'encryption': 'WPA3'}, {'encryption': 'WEP'}])
    check(pl.total_xp == 61, "weighted xp %d" % pl.total_xp)
    check(pl.credits == 4, "credits %d" % pl.credits)

    # A handshake can cross a level, and the level-up grants credits.
    pl2 = P.Player.load(os.path.join(d, "b.json"))
    pl2.seeded = True
    pl2.total_xp = 90
    reached = pl2.award_handshake()
    check(pl2.level == 2 and reached == 2, "handshake crosses to level 2")
    check(pl2.credits == P.CREDITS_PER_HANDSHAKE + P.CREDITS_PER_LEVEL * 2,
          "level-up reward credits %d" % pl2.credits)

    # Seeding from the aggregate, once only, with no seeded credits.
    pl3 = P.Player.load(os.path.join(d, "c.json"))
    pl3.seed_from_stats({'total': 10, 'open': 2, 'wep': 1, 'wpa': 5,
                         'wpa3': 2, 'handshakes': 1})
    check(pl3.total_xp == 159, "seed xp %d" % pl3.total_xp)
    check(pl3.seeded and pl3.credits == 0, "seeded, no credits")
    pl3.seed_from_stats({'total': 999})
    check(pl3.total_xp == 159, "re-seed is a no-op")

    # The shop gates on level, then credits, then marks the item owned.
    # 'hardhat' is a head item: cost 80, level 2.
    pl4 = P.Player.load(os.path.join(d, "e.json"))
    pl4.seeded = True
    ok, msg = pl4.buy('hardhat')
    check(not ok and 'level' in msg, "blocked by level")
    pl4.total_xp = 100  # level 2
    ok, msg = pl4.buy('hardhat')
    check(not ok and 'credit' in msg, "blocked by credits")
    pl4.credits = 80
    ok, msg = pl4.buy('hardhat')
    check(ok and 'hardhat' in pl4.inventory and pl4.credits == 0, "bought")
    check(pl4.equipped.get('head') == 'hardhat', "buying auto-equips its slot")
    ok, msg = pl4.buy('hardhat')
    check(not ok and 'owned' in msg, "already owned")

    # Equip/unequip: one item per slot, swapping replaces.
    pl4.total_xp = 100000  # high enough for any level gate
    pl4.credits = 100000
    pl4.buy('fedora')  # also a head item
    check(pl4.equipped.get('head') == 'fedora', "second head item swaps the slot")
    check('hardhat' in pl4.inventory and 'fedora' in pl4.inventory, "both owned")
    ok, msg = pl4.equip('hardhat')
    check(ok and pl4.equipped['head'] == 'hardhat', "re-equip the first head item")
    ok, msg = pl4.unequip('head')
    check(ok and 'head' not in pl4.equipped, "unequip by slot")
    ok, msg = pl4.equip('nonesuch')
    check(not ok, "cannot equip an unowned item")

    # State survives a save and reload.
    pl4.equip('hardhat')
    pl4.save()
    again = P.Player.load(pl4.path)
    check('hardhat' in again.inventory and again.equipped.get('head') == 'hardhat',
          "reload keeps inventory and equipped")

    print("\nTOTAL FAILURES: %d" % fails)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()

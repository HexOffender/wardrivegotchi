"""Tests for the progression framework. Run: python3 player_test.py

Numbers are derived from the tunable constants (XP_PER_AP, the curve, credit
rates) rather than hard-coded, so tuning the balance does not break these - they
check the mechanism, not a frozen number. There is no test runner on the Pager,
thus this is a plain script that exits non-zero on any failure.
"""
import os
import sys
import tempfile

import player as P
import achievements as A
import items

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1


def main():
    # --- Curve: rises, each level costs more, and level_for_xp is its inverse.
    reach = [P.xp_to_reach(l) for l in range(1, 12)]
    check(reach[0] == 0, "level 1 is 0 xp")
    check(all(reach[i + 1] > reach[i] for i in range(len(reach) - 1)), "curve rises: %s" % reach)
    gaps = [reach[i + 1] - reach[i] for i in range(len(reach) - 1)]
    check(all(gaps[i + 1] > gaps[i] for i in range(len(gaps) - 1)), "each level costs more: %s" % gaps)
    check(all(P.level_for_xp(P.xp_to_reach(l)) == l for l in range(1, 200)),
          "level_for_xp inverts xp_to_reach at every boundary")
    check(P.level_for_xp(0) == 1 and P.level_for_xp(P.xp_to_reach(2) - 1) == 1,
          "just under level 2 is still level 1")
    check(P.level_for_xp(P.xp_to_reach(5)) == 5, "an exact boundary is that level")

    d = tempfile.mkdtemp()

    # --- Weighted awards: base + encryption bonus, derived from the constants.
    pl = P.Player.load(os.path.join(d, "a.json"))
    pl.seeded = True
    pl.award_aps([{'encryption': 'WPA2'}, {'encryption': 'Open'},
                  {'encryption': 'WPA3'}, {'encryption': 'WEP'}])
    expected = 4 * P.XP_PER_AP + P.xp_bonus('Open') + P.xp_bonus('WPA3') + P.xp_bonus('WEP')
    check(pl.total_xp == expected, "weighted xp %d (expected %d)" % (pl.total_xp, expected))

    # --- Credits: none per-AP by default; a level-up pays a flat per-level sum.
    pl2 = P.Player.load(os.path.join(d, "b.json"))
    pl2.seeded = True
    pl2.total_xp = P.xp_to_reach(3) - 1      # one xp under level 3, so level 2
    check(pl2.level == 2, "poised at level 2")
    reached = pl2.award_handshake()          # the handshake bonus crosses a level
    lvls = pl2.level - 2
    check(reached == pl2.level and lvls >= 1, "handshake crosses at least one level")
    check(pl2.credits == P.CREDITS_PER_HANDSHAKE + P.CREDITS_PER_LEVEL * lvls,
          "handshake + flat per-level credits %d" % pl2.credits)
    check(pl2.counters['credits_earned'] == pl2.credits, "credits_earned tracks lifetime earned")

    # --- Seed: xp from history, once only, achievements marked WITHOUT reward.
    pl3 = P.Player.load(os.path.join(d, "c.json"))
    stats = {'total': 1200, 'open': 150, 'wep': 2, 'wpa': 900, 'wpa3': 148, 'handshakes': 1}
    pl3.seed_from_stats(stats)
    seed_xp = (150 * (P.XP_PER_AP + P.xp_bonus('Open'))
               + 2 * (P.XP_PER_AP + P.xp_bonus('WEP'))
               + 900 * P.XP_PER_AP
               + 148 * (P.XP_PER_AP + P.xp_bonus('WPA3'))
               + 1 * P.XP_PER_HANDSHAKE)
    check(pl3.total_xp == seed_xp, "seed xp derived from constants (%d)" % pl3.total_xp)
    check(pl3.credits == 0 and pl3.counters['credits_earned'] == 0, "seeding grants no credits")
    check('aps_1k' in pl3.unlocked and 'aps_100' in pl3.unlocked and 'one_each' in pl3.unlocked,
          "seed marks the achievements history already earned")
    check(pl3.total_xp == seed_xp, "seed did NOT add achievement reward xp")
    pl3.seed_from_stats({'total': 99999})
    check(pl3.total_xp == seed_xp, "re-seed is a no-op")

    # --- check_achievements: unlock once, grant xp+credits, set the title.
    pl5 = P.Player.load(os.path.join(d, "f.json"))
    pl5.seeded = True
    db = {'total': 100, 'open': 0, 'wep': 0, 'wpa': 100, 'wpa3': 0, 'handshakes': 0}
    newly = pl5.check_achievements(db)
    ids = [a['id'] for a in newly]
    check('aps_10' in ids and 'aps_100' in ids, "unlocks aps_10 and aps_100: %s" % ids)
    check(pl5.title == 'Sniffer', "title becomes Sniffer at 100 APs")
    check(pl5.credits == A.get('aps_10')['credits'] + A.get('aps_100')['credits'],
          "achievement credit rewards are granted")
    check(pl5.check_achievements(db) == [], "an unlocked achievement does not fire again")

    # --- Cascade: several tiers of one metric unlock together to a fixpoint.
    pl6 = P.Player.load(os.path.join(d, "g.json"))
    pl6.seeded = True
    got = {a['id'] for a in pl6.check_achievements({'total': 0, 'handshakes': 50})}
    check({'hs_1', 'hs_10', 'hs_50'} <= got, "all handshake tiers unlock in one call: %s" % got)
    check(pl6.title == 'Handshake Hunter', "handshake capstone sets its title")

    # --- Shop still gates on level, then credits, and state reloads.
    pl4 = P.Player.load(os.path.join(d, "e.json"))
    pl4.seeded = True
    ok, msg = pl4.buy('hardhat')                 # hardhat: cost 80, level 2
    check(not ok and 'level' in msg, "blocked by level")
    pl4.total_xp = P.xp_to_reach(2)              # exactly level 2
    ok, msg = pl4.buy('hardhat')
    check(not ok and 'credit' in msg, "blocked by credits")
    pl4._add_credits(80)
    ok, msg = pl4.buy('hardhat')
    check(ok and 'hardhat' in pl4.inventory and pl4.credits == 0, "bought")
    check(pl4.equipped.get('head') == 'hardhat', "buying auto-equips its slot")
    pl4.unlocked.append('aps_10')
    pl4.save()
    again = P.Player.load(pl4.path)
    check('hardhat' in again.inventory and 'aps_10' in again.unlocked,
          "reload keeps inventory and unlocked achievements")

    # --- Multi-slot items fill and free every slot they span. ---
    plm = P.Player.load(os.path.join(d, "m.json"))
    plm.seeded = True
    plm.total_xp = P.xp_to_reach(12)
    plm._add_credits(5000)
    plm.buy('hardhat')          # head
    plm.buy('tie')              # body
    plm.buy('cane')             # side
    plm.buy('onesie')           # spans head, body, side, feet
    check(set(plm.equipped) == set(items.SLOTS) and set(plm.equipped.values()) == {'onesie'},
          "a full-body item fills every slot it spans")
    check('hardhat' not in plm.equipped.values() and 'tie' not in plm.equipped.values()
          and 'cane' not in plm.equipped.values(),
          "equipping it evicts the items it displaces")
    ok, _ = plm.unequip('feet')  # name any slot it occupies
    check(ok and 'onesie' not in plm.equipped.values(),
          "unequipping a multi-slot item frees all of its slots")
    plm.equip('onesie')
    plm.equip('hardhat')         # into just one of the outfit's slots
    check(plm.equipped.get('head') == 'hardhat' and 'onesie' not in plm.equipped.values(),
          "equipping into one slot of a worn outfit removes the whole outfit")

    print("\nTOTAL FAILURES: %d" % fails)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()

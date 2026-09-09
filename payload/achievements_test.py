"""Tests for the achievement registry. Run: python3 achievements_test.py"""
import sys

import achievements as A

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1


def main():
    check(A.validate() == [], "catalogue is sound: %s" % A.validate())
    check(len(A.CATALOG) == len(set(a['id'] for a in A.CATALOG)), "ids are unique")

    # Reward-loop safety: a level achievement grants no XP (its XP could push
    # another level); a credits_earned achievement grants no credits.
    for a in A.CATALOG:
        if a['metric'] == 'level':
            check(a.get('xp', 0) == 0, "%s (level metric) grants no xp" % a['id'])
        if a['metric'] == 'credits_earned':
            check(a.get('credits', 0) == 0, "%s (credits metric) grants no credits" % a['id'])

    # newly_met returns only met, not-yet-unlocked achievements, in order.
    metrics = {'aps': 150, 'open': 0, 'wep': 0, 'wpa': 0, 'wpa3': 0, 'kinds': 0,
               'handshakes': 0, 'sessions': 0, 'best_session': 0, 'level': 1,
               'credits_earned': 0}
    met = A.newly_met(metrics, set())
    ids = [a['id'] for a in met]
    check(ids == ['aps_10', 'aps_100'], "aps=150 meets aps_10 and aps_100: %s" % ids)
    check(A.newly_met(metrics, {'aps_10'}) and
          A.newly_met(metrics, {'aps_10'})[0]['id'] == 'aps_100',
          "already-unlocked ones are excluded")
    check(A.newly_met(metrics, {'aps_10', 'aps_100'}) == [], "nothing new when all met are unlocked")

    # Titles form one escalating track: the highest rank unlocked wins.
    check(A.title_for(set()) == '', "no title with nothing unlocked")
    check(A.title_for({'aps_100'}) == 'Sniffer', "aps_100 -> Sniffer")
    check(A.title_for({'aps_100', 'aps_1k'}) == 'Wardriver', "higher rank wins")
    # A non-title achievement contributes no title.
    check(A.title_for({'aps_10'}) == '', "aps_10 has no title")
    # Interleaved ranks: handshake title (rank 25) beats Wardriver (rank 20).
    check(A.title_for({'aps_1k', 'hs_50'}) == 'Handshake Hunter',
          "hs_50 rank interleaves above Wardriver")

    print("\nTOTAL FAILURES: %d" % fails)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()

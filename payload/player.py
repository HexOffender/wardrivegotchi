"""Player progression: levels, experience, credits, inventory and a shop.

This is a pwnagotchi-style layer over the wardrive. As you log access points you
gain experience and rise through levels; notable finds are worth more. Credits
are a separate balance you earn and spend in the shop. The avatar and the reward
items come later; this file is the framework they sit on.

State lives in player.json in the loot directory, next to the database, so it
survives a reinstall and you can read or reset it by hand. The level is not
stored: it is always derived from the total experience, so the two can never
disagree.

Every method that changes state runs on the main loop thread, the same thread
that applies commands and awards experience, so this file needs no lock of its
own.
"""

import json
import os
import time

SCHEMA = 1

# The level curve. The experience to REACH level L is XP_BASE * (L-1) * L / 2,
# thus each level costs XP_BASE more than the one before. With XP_BASE = 100:
# level 2 at 100, level 5 at 1000, level 10 at 4500. An average find is about
# 13 experience, so level 2 is roughly eight access points and level 10 a few
# hundred - fast at first, a grind later, which is the escalating feel asked for.
XP_BASE = 100

# Experience per newly-logged unique access point. A common WPA2 network is the
# base. The bonuses reward variety and effort: open and legacy networks are
# interesting, WPA3 is modern and less common, and a captured handshake is real
# work. These are the "weighted by find" rule.
XP_PER_AP = 5
XP_BONUS = {
    'Open': 2,
    'WEP': 3,
    'WPA3': 4,
    # WPA and WPA2 are the common case and take no bonus.
}
XP_PER_HANDSHAKE = 25

# Credits are the spendable currency. They are not experience: spending them
# never lowers your level. Earned going forward only, never seeded from history.
CREDITS_PER_AP = 1
CREDITS_PER_HANDSHAKE = 3

# Credits granted on reaching a new level, as a first reward hook. Item rewards
# arrive later; this is here so level-ups already do something.
CREDITS_PER_LEVEL = 5

# The shop sells the wearable items. They live in items.py, the single registry
# the shop, the inventory and the avatar all read, so adding an item there makes
# it show up here (and everywhere) automatically - nothing to change in this file.
import items

SHOP = items.CATALOG


def xp_to_reach(level):
    """Total experience needed to reach a level. Level 1 is 0."""
    if level <= 1:
        return 0
    return XP_BASE * (level - 1) * level // 2


def level_for_xp(total_xp):
    """The level a total experience buys. The inverse of xp_to_reach."""
    level = 1
    while xp_to_reach(level + 1) <= total_xp:
        level += 1
    return level


def xp_bonus(encryption):
    """The experience bonus for an access point's encryption."""
    return XP_BONUS.get(encryption or '', 0)


class Player:
    def __init__(self, path):
        self.path = path
        self.total_xp = 0
        self.credits = 0
        self.inventory = []
        self.equipped = {}   # slot -> item_id
        self.counters = {'aps_awarded': 0, 'handshakes': 0, 'sessions': 0,
                         'best_session_aps': 0}
        self.seeded = False
        self._last_save_at = 0.0

    # Loading and saving.

    @classmethod
    def load(cls, path):
        p = cls(path)
        try:
            with open(path) as f:
                data = json.load(f)
            p.total_xp = int(data.get('total_xp', 0))
            p.credits = int(data.get('credits', 0))
            p.inventory = list(data.get('inventory', []))
            p.equipped = dict(data.get('equipped', {}))
            p.counters.update(data.get('counters', {}))
            p.seeded = bool(data.get('seeded', False))
        except FileNotFoundError:
            pass
        except Exception:
            # A corrupt file must not stop a scan. Start fresh and let the next
            # save overwrite it.
            pass
        return p

    def save(self):
        data = {
            'schema': SCHEMA,
            'total_xp': self.total_xp,
            'credits': self.credits,
            'inventory': self.inventory,
            'equipped': self.equipped,
            'counters': self.counters,
            'seeded': self.seeded,
        }
        tmp = self.path + '.tmp'
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(tmp, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.path)  # atomic, so a crash cannot truncate it
            self._last_save_at = time.time()
        except Exception:
            pass

    def save_throttled(self, min_interval=5.0):
        """Save at most once per min_interval - for the frequent per-scan awards,
        so dense scanning does not rewrite player.json every batch. Level-ups and
        purchases still save immediately."""
        if time.time() - self._last_save_at >= min_interval:
            self.save()

    # Derived level and progress.

    @property
    def level(self):
        return level_for_xp(self.total_xp)

    def progress(self):
        """Experience within the current level, for a progress bar."""
        level = self.level
        floor = xp_to_reach(level)
        ceil = xp_to_reach(level + 1)
        into = self.total_xp - floor
        span = ceil - floor
        return {'level': level, 'into': into, 'span': span,
                'pct': round(100 * into / span) if span else 0}

    # Earning.

    def seed_from_stats(self, stats):
        """Set the starting experience from access points already in the
        database, so a returning wardriver is not sent back to level 1. Runs
        once. Credits are not seeded: those accrue only going forward."""
        if self.seeded:
            return
        total = stats.get('total', 0)
        buckets = {'Open': stats.get('open', 0), 'WEP': stats.get('wep', 0),
                   'WPA': stats.get('wpa', 0), 'WPA3': stats.get('wpa3', 0)}
        xp = 0
        counted = 0
        for enc, n in buckets.items():
            xp += n * (XP_PER_AP + xp_bonus(enc))
            counted += n
        # Any access point not in a bucket still earns the base.
        remainder = max(0, total - counted)
        xp += remainder * XP_PER_AP
        xp += stats.get('handshakes', 0) * XP_PER_HANDSHAKE

        self.total_xp = xp
        self.counters['aps_awarded'] = total
        self.counters['handshakes'] = stats.get('handshakes', 0)
        self.seeded = True
        self.save()

    def award_aps(self, aps):
        """Award experience and credits for newly-logged access points. `aps`
        is a list of AP dicts. Returns the level reached if it rose, else None."""
        if not aps:
            return None
        before = self.level
        for ap in aps:
            self.total_xp += XP_PER_AP + xp_bonus(ap.get('encryption'))
            self.credits += CREDITS_PER_AP
        self.counters['aps_awarded'] += len(aps)
        return self._settle(before)

    def award_handshake(self):
        """Award the handshake bonus. Returns the new level if it rose."""
        before = self.level
        self.total_xp += XP_PER_HANDSHAKE
        self.credits += CREDITS_PER_HANDSHAKE
        self.counters['handshakes'] += 1
        return self._settle(before)

    def note_session_aps(self, count):
        """Record the access point count of a finished session."""
        self.counters['sessions'] += 1
        if count > self.counters.get('best_session_aps', 0):
            self.counters['best_session_aps'] = count
        self.save()

    def _settle(self, level_before):
        """Grant the level-up reward for any levels crossed, then save."""
        level_after = self.level
        reached = None
        if level_after > level_before:
            for lvl in range(level_before + 1, level_after + 1):
                self.credits += CREDITS_PER_LEVEL * lvl
            reached = level_after
            self.save()            # level-up: persist immediately
        else:
            self.save_throttled()  # frequent awards: throttle disk writes
        return reached

    # Spending.

    def buy(self, item_id):
        """Buy a shop item. Returns (ok, message)."""
        item = next((i for i in SHOP if i['id'] == item_id), None)
        if item is None:
            return False, 'no such item'
        if item_id in self.inventory:
            return False, 'already owned'
        if self.level < item['level']:
            return False, 'need level %d' % item['level']
        if self.credits < item['cost']:
            return False, 'need %d credits' % item['cost']
        self.credits -= item['cost']
        self.inventory.append(item_id)
        # Wearing it straight away is the friendly default; it can be taken off.
        self.equipped[item['slot']] = item_id
        self.save()
        return True, 'bought ' + item['name']

    def equip(self, item_id):
        """Wear an owned item. It fills its slot, replacing whatever was there."""
        item = next((i for i in SHOP if i['id'] == item_id), None)
        if item is None or item_id not in self.inventory:
            return False, 'not owned'
        self.equipped[item['slot']] = item_id
        self.save()
        return True, 'equipped ' + item['name']

    def unequip(self, slot_or_item):
        """Take off an item, by slot name or by item id."""
        slot = slot_or_item
        if slot_or_item not in self.equipped:
            item = next((i for i in SHOP if i['id'] == slot_or_item), None)
            slot = item['slot'] if item else None
        if slot and slot in self.equipped:
            del self.equipped[slot]
            self.save()
            return True, 'removed'
        return False, 'not worn'

    # For the phone page.

    def snapshot(self, db_stats=None):
        """A view of the profile for the status feed. Merges the progression
        here with the access-point counts from the database."""
        prog = self.progress()
        shop = []
        for item in SHOP:
            entry = dict(item)
            entry['owned'] = item['id'] in self.inventory
            entry['equipped'] = self.equipped.get(item['slot']) == item['id']
            entry['affordable'] = self.credits >= item['cost'] and self.level >= item['level']
            shop.append(entry)
        return {
            'level': prog['level'],
            'xp': self.total_xp,
            'xp_into': prog['into'],
            'xp_span': prog['span'],
            'xp_pct': prog['pct'],
            'credits': self.credits,
            'inventory': list(self.inventory),
            'equipped': dict(self.equipped),
            'counters': dict(self.counters),
            'shop': shop,
            'db_stats': db_stats or {},
        }

"""The achievement registry - the single place that lists every achievement.

Like items.py, this is the only file to edit to add an achievement: the unlock
logic (player.py), the Pager profile and the phone page all read CATALOG, so a
new entry is tracked and shown everywhere automatically.

Each achievement is a dict:

    id       Unique short id. Stored in player.json once unlocked, so never
             change an id after it has shipped or players lose the unlock.
    name     Short label shown when it unlocks and in the achievement list.
    desc     One line: how to earn it.
    metric   Which tracked number it measures - one of METRICS below.
    goal     The value of that metric at which it unlocks (met when value >=).
    xp       Experience granted on unlock. Scale it with difficulty.
    credits  Credits granted on unlock. Scale it with difficulty.
    title    Optional. A title awarded on unlock, shown under the avatar.
    rank     Optional, required with `title`. The displayed title is the
             highest-rank one unlocked, so titles form a single escalating
             track - each fancier than the last. Spread ranks (10, 20, ...) so
             titles from different metrics can be interleaved by prestige.

METRICS are the signals an achievement can measure. player.metrics() builds them
from the player's counters and level and the database stats:

    aps            total unique access points logged
    open/wep/wpa3  count of networks with that encryption
    wpa            count of WPA/WPA2 networks (the common case)
    kinds          how many distinct encryption kinds seen (for 'one of each')
    handshakes     handshakes captured
    sessions       scan sessions finished
    best_session   most APs logged in a single session
    level          current level
    credits_earned lifetime credits earned (never falls when you spend)

Reward guidance to avoid feedback loops: a `level` achievement grants xp 0 (its
XP could push another level), and a `credits_earned` achievement grants credits
0 (its credits would count toward the same metric). player.check_achievements
resolves any remaining cascade to a fixpoint regardless.
"""

METRICS = ('aps', 'open', 'wep', 'wpa', 'wpa3', 'kinds', 'handshakes',
           'sessions', 'best_session', 'level', 'credits_earned')

CATALOG = [
    # --- Access-point count: the main progression and the escalating titles ---
    {'id': 'aps_10',   'name': 'Getting Started', 'desc': 'Log 10 networks',      'metric': 'aps', 'goal': 10,     'xp': 20,    'credits': 10},
    {'id': 'aps_100',  'name': 'First Hundred',   'desc': 'Log 100 networks',     'metric': 'aps', 'goal': 100,    'xp': 150,   'credits': 40,   'title': 'Sniffer',              'rank': 10},
    {'id': 'aps_1k',   'name': 'Thousand Club',   'desc': 'Log 1,000 networks',   'metric': 'aps', 'goal': 1000,   'xp': 800,   'credits': 120,  'title': 'Wardriver',            'rank': 20},
    {'id': 'aps_10k',  'name': 'Five Figures',    'desc': 'Log 10,000 networks',  'metric': 'aps', 'goal': 10000,  'xp': 5000,  'credits': 500,  'title': 'Spectrum Stalker',     'rank': 30},
    {'id': 'aps_50k',  'name': 'City Sweeper',    'desc': 'Log 50,000 networks',  'metric': 'aps', 'goal': 50000,  'xp': 20000, 'credits': 1500, 'title': 'Airwave Overlord',     'rank': 40},
    {'id': 'aps_250k', 'name': 'Ether Emperor',   'desc': 'Log 250,000 networks', 'metric': 'aps', 'goal': 250000, 'xp': 80000, 'credits': 5000, 'title': 'Emperor of the Ether', 'rank': 50},

    # --- Encryption variety ---
    {'id': 'open_100', 'name': 'Wide Open',      'desc': 'Find 100 open networks',       'metric': 'open',  'goal': 100,  'xp': 300,  'credits': 60},
    {'id': 'open_1k',  'name': 'Come On In',     'desc': 'Find 1,000 open networks',     'metric': 'open',  'goal': 1000, 'xp': 1500, 'credits': 200},
    {'id': 'wep_1',    'name': 'Living Fossil',  'desc': 'Find a WEP network',           'metric': 'wep',   'goal': 1,    'xp': 200,  'credits': 80},
    {'id': 'wep_10',   'name': 'Retro Collector','desc': 'Find 10 WEP networks',         'metric': 'wep',   'goal': 10,   'xp': 1200, 'credits': 300},
    {'id': 'wpa3_100', 'name': 'Modern Times',   'desc': 'Find 100 WPA3 networks',       'metric': 'wpa3',  'goal': 100,  'xp': 500,  'credits': 100},
    {'id': 'wpa3_1k',  'name': 'Future Proof',   'desc': 'Find 1,000 WPA3 networks',     'metric': 'wpa3',  'goal': 1000, 'xp': 2500, 'credits': 350},
    {'id': 'one_each', 'name': 'Full Spectrum',  'desc': 'Find open, WEP, WPA and WPA3', 'metric': 'kinds', 'goal': 4,    'xp': 400,  'credits': 100},

    # --- Handshakes ---
    {'id': 'hs_1',  'name': 'Nice to Meet You', 'desc': 'Capture a handshake',    'metric': 'handshakes', 'goal': 1,  'xp': 100,  'credits': 40},
    {'id': 'hs_10', 'name': 'Regular Greeter',  'desc': 'Capture 10 handshakes',  'metric': 'handshakes', 'goal': 10, 'xp': 600,  'credits': 150},
    {'id': 'hs_50', 'name': 'Handshake Hunter', 'desc': 'Capture 50 handshakes',  'metric': 'handshakes', 'goal': 50, 'xp': 3000, 'credits': 500, 'title': 'Handshake Hunter', 'rank': 25},

    # --- Sessions & levels ---
    {'id': 'sess_10', 'name': 'Creature of Habit', 'desc': 'Finish 10 scan sessions',      'metric': 'sessions',      'goal': 10,   'xp': 500,  'credits': 100},
    {'id': 'best_1k', 'name': 'Good Run',          'desc': '1,000 networks in one session', 'metric': 'best_session',  'goal': 1000, 'xp': 700,  'credits': 150},
    {'id': 'best_5k', 'name': 'Marathon',          'desc': '5,000 networks in one session', 'metric': 'best_session',  'goal': 5000, 'xp': 3000, 'credits': 500},
    {'id': 'lvl_25',  'name': 'Seasoned',          'desc': 'Reach level 25',                'metric': 'level',         'goal': 25,   'xp': 0,    'credits': 400},
    {'id': 'lvl_50',  'name': 'Veteran',           'desc': 'Reach level 50',                'metric': 'level',         'goal': 50,   'xp': 0,    'credits': 1500, 'title': 'Ascended', 'rank': 45},
    {'id': 'cr_5k',   'name': 'Nest Egg',          'desc': 'Earn 5,000 credits',            'metric': 'credits_earned','goal': 5000, 'xp': 1000, 'credits': 0},
]

# id -> achievement, for quick lookup.
ACH = {a['id']: a for a in CATALOG}


def get(ach_id):
    """The achievement dict for an id, or None."""
    return ACH.get(ach_id)


def all_ids():
    """Every achievement id, in catalogue order."""
    return [a['id'] for a in CATALOG]


def newly_met(metrics, unlocked):
    """Achievements whose goal is met by `metrics` and not already in the
    `unlocked` set. Returned in catalogue order (stable notification order)."""
    out = []
    for a in CATALOG:
        if a['id'] in unlocked:
            continue
        if metrics.get(a['metric'], 0) >= a['goal']:
            out.append(a)
    return out


def title_for(unlocked):
    """The displayed title for a set of unlocked ids: the highest-rank title
    among them, or '' when none is unlocked yet."""
    best_rank = None
    best_title = ''
    for aid in unlocked:
        a = ACH.get(aid)
        if not a or 'title' not in a:
            continue
        if best_rank is None or a.get('rank', 0) > best_rank:
            best_rank = a.get('rank', 0)
            best_title = a['title']
    return best_title


def validate():
    """Return a list of problems with the catalogue (empty means it is sound).
    achievements_test.py runs this so a mistake in a new entry is caught early."""
    problems = []
    seen = set()
    for a in CATALOG:
        aid = a.get('id')
        if not aid:
            problems.append('an achievement is missing its id: %r' % (a,))
            continue
        if aid in seen:
            problems.append('duplicate id: %s' % aid)
        seen.add(aid)
        if not a.get('name'):
            problems.append('%s: missing name' % aid)
        if not a.get('desc'):
            problems.append('%s: missing desc' % aid)
        if a.get('metric') not in METRICS:
            problems.append('%s: unknown metric %r (valid: %s)'
                            % (aid, a.get('metric'), ', '.join(METRICS)))
        for key in ('goal', 'xp', 'credits'):
            val = a.get(key)
            if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                problems.append('%s: %s must be a non-negative integer, got %r' % (aid, key, val))
        if 'title' in a:
            if not a['title']:
                problems.append('%s: empty title' % aid)
            if not isinstance(a.get('rank'), int) or isinstance(a.get('rank'), bool):
                problems.append('%s: a title needs an integer rank' % aid)
    # Titles must have distinct ranks, or the displayed title is ambiguous.
    ranks = [a['rank'] for a in CATALOG if 'title' in a and isinstance(a.get('rank'), int)]
    if len(ranks) != len(set(ranks)):
        problems.append('two titles share a rank: %s' % sorted(ranks))
    return problems

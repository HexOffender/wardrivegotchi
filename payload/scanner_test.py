"""Channel hop-order tests. Run: python3 scanner_test.py"""
import os
import sys
import tempfile
from collections import Counter

from scanner import _build_hop_order, detect_second_monitor

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1


def main():
    ch = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    pri = {1, 6, 11}

    order = _build_hop_order(ch, pri, 2)
    check(set(order) == set(ch), "every channel is still visited")
    c = Counter(order)
    check(min(c[p] for p in pri) > max(c[s] for s in ch if s not in pri),
          "priority channels visited more than the rest %s" % dict(c))
    check(all(c[s] == 1 for s in ch if s not in pri), "each non-priority visited once per cycle")

    # Only channels actually in the scan can be priorities.
    only24 = _build_hop_order([1, 2, 3, 4, 5, 6], {1, 6, 36, 149}, 2)
    check(set(only24) == {1, 2, 3, 4, 5, 6}, "priorities outside the scan are ignored")

    # Degenerate cases fall back to the plain list.
    check(_build_hop_order(ch, set(), 2) == ch, "no priority -> plain order")
    check(_build_hop_order(ch, pri, 0) == ch, "weight 0 -> plain order")
    check(_build_hop_order([1, 6, 11], {1, 6, 11}, 2) == [1, 6, 11], "all priority -> plain order")

    # detect_second_monitor: a plugged-in adapter is found automatically; with
    # none present it returns '' (so the payload uses the internal radio alone).
    def fake_net(ifaces):
        base = tempfile.mkdtemp()
        for name, typ in ifaces:
            d = os.path.join(base, name)
            os.makedirs(d)
            with open(os.path.join(d, 'type'), 'w') as f:
                f.write(typ + '\n')
        return base

    with_adapter = fake_net([('lo', '772'), ('wlan0cli', '1'),
                             ('wlan1mon', '803'), ('wlan2mon', '803')])
    check(detect_second_monitor('wlan1mon', with_adapter) == 'wlan2mon',
          "detects the second monitor radio (adapter present)")
    no_adapter = fake_net([('lo', '772'), ('wlan0cli', '1'), ('wlan1mon', '803')])
    check(detect_second_monitor('wlan1mon', no_adapter) == '',
          "no second radio -> '' (internal only)")
    check(detect_second_monitor('wlan1mon', '/no/such/path') == '',
          "missing sysfs -> '' (safe)")

    print("\nTOTAL FAILURES: %d" % fails)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()

"""Measure where a dashboard frame spends its time. Run on the Pager.

    cd /root/payloads/user/reconnaissance/wardrivegotchi
    export PYTHONPATH="$PWD/lib:$PWD:$PYTHONPATH"
    export LD_LIBRARY_PATH="/mmc/usr/lib:$PWD/lib:$LD_LIBRARY_PATH"
    /etc/init.d/pineapplepager stop
    python3 benchmark.py
    /etc/init.d/pineapplepager start
"""
import os
import time

import pagerctl
from config import BG_IMAGE, DB_PATH, SCREEN_H, SCREEN_W
import palette

pager = pagerctl.Pager()
pager.init()


def bench(name, fn, n=20):
    fn()                                   # warm up
    t = time.time()
    for _ in range(n):
        fn()
    ms = (time.time() - t) * 1000 / n
    print(f"  {ms:8.1f} ms  {name}")
    return ms


print("frame costs, mean of 20 runs:\n")

if os.path.isfile(BG_IMAGE):
    png = bench("background: decode and scale the PNG",
                lambda: pager.draw_image_file_scaled(0, 0, SCREEN_W, SCREEN_H, BG_IMAGE))
else:
    png = None
    print("  (no PNG background installed)")

fill = bench("background: flat fill with primitives",
             lambda: pager.fill_rect(0, 0, SCREEN_W, SCREEN_H,
                                     pager.rgb(*palette.PAPER)))

import database
db = database.Database(DB_PATH)
bench("db.get_stats()", db.get_stats)
bench("db.get_all_aps()", db.get_all_aps, n=5)
bench("db.correlate_open_bssids()", db.correlate_open_bssids, n=5)

import wardrive
bench("_get_battery()", lambda: wardrive.WardriveApp._get_battery(None), n=5)

if png:
    print(f"\nthe PNG background costs {png - fill:.1f} ms more than a fill,")
    print(f"which is {(png - fill) * 10:.0f} ms per second at 10 frames per second.")

pager.cleanup()

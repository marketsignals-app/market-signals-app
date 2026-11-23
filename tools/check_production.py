"""Checks what the DEPLOYED site actually published, as PASS / FAIL / UNVERIFIED lines.

    python tools/check_production.py                       # the live site
    python tools/check_production.py --cache signals-v42   # also confirm the service-worker cache name

It reads the live data.json (what the GitHub Actions run built) and sw.js. It cannot see the Actions logs (they need a login), so
"error logged" is only inferred from what the run published; the lines say so. Nothing here changes anything.
"""
import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.verify_market_data import SITE, load_app_data          # noqa: E402
from engine import fetch                                           # noqa: E402

BASE = SITE.rsplit("/", 1)[0] + "/"
PASS, FAIL, UNVERIFIED = "PASS", "FAIL", "UNVERIFIED"


def age_minutes(stamp, now):
    try:
        return (now - datetime.fromisoformat(stamp)).total_seconds() / 60
    except (TypeError, ValueError):
        return None


def check(data, now, sw_text=None, expect_cache=None):
    rows = []

    def add(name, status, detail):
        rows.append((name, status, detail))

    age = age_minutes(data.get("generated_at"), now)
    add("Data freshness", PASS if age is not None and age < 90 else FAIL, f"generated {data.get('generated_at')} ({'unknown' if age is None else f'{age:.0f} min ago'})")

    ev = data.get("events") or {}
    official = ev.get("official") or {}
    items = ev.get("items") or []
    confirmed = [e for e in items if e.get("verification") == "CONFIRMED"]
    if official.get("ok"):
        add("NSE feed from Actions", PASS, f"answered; read {official.get('fetched_at')}; {official.get('confirmed')} confirmed, {official.get('conflicts')} conflicts, {official.get('unverified')} unverified")
        bad = [e["symbol"] for e in confirmed if not e.get("official")]
        add("Event statuses", PASS if not bad else FAIL, f"{len(confirmed)} CONFIRMED events all carry the official record" if not bad else f"CONFIRMED without an official record: {bad[:5]}")
    elif "official" in ev:
        add("NSE feed from Actions", UNVERIFIED, f"refused or failed: {official.get('error')}; last success {official.get('fetched_at') or 'never'}")
        add("Event statuses", PASS if not confirmed else FAIL, "fallback active: every event is UNVERIFIED" if not confirmed else f"{len(confirmed)} events are CONFIRMED although the feed failed")
    else:
        add("NSE feed from Actions", UNVERIFIED, "this data.json has no official-events block: the new build is not deployed yet")
    links = [e for e in items if e.get("market") == "IN" and not str(e.get("official_url", "")).startswith("https://www.nseindia.com/")]
    add("Official source URLs", UNVERIFIED if (not items or "official" not in ev) else (PASS if not links else FAIL), f"{len(items)} events; {len(links)} Indian events without an NSE link")

    checks = {c["name"]: c for c in (data.get("status") or {}).get("checks", [])}
    for name in ("NSE official events",):
        add(f"Status card: {name}", PASS if name in checks else UNVERIFIED, checks[name]["detail"] if name in checks else "not in this data.json yet")

    if sw_text is not None:
        cache = re.search(r"CACHE\s*=\s*'([^']+)'", sw_text)
        name = cache.group(1) if cache else None
        add("Service worker cache", PASS if expect_cache and name == expect_cache else (UNVERIFIED if not expect_cache else FAIL), f"sw.js declares {name}" + (f"; expected {expect_cache}" if expect_cache else ""))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=SITE)
    parser.add_argument("--cache", help="the service-worker cache name expected, for example signals-v42")
    args = parser.parse_args(argv)
    data = load_app_data(args.data)
    sw = None
    if args.data.startswith("http"):
        try:
            sw = urllib.request.urlopen(urllib.request.Request(BASE + "sw.js", headers={"User-Agent": fetch.USER_AGENT, "Cache-Control": "no-cache"}), timeout=30).read().decode()
        except Exception:                                  # the SSL strictness of Python 3.13 on some Windows set-ups
            import ssl
            ctx = ssl.create_default_context()
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
            sw = urllib.request.urlopen(urllib.request.Request(BASE + "sw.js", headers={"User-Agent": fetch.USER_AGENT}), timeout=30, context=ctx).read().decode()
    rows = check(data, datetime.now(timezone.utc), sw, args.cache)
    width = max(len(r[0]) for r in rows)
    for name, status, detail in rows:
        print(f"{status:<10} {name:<{width}}  {detail}")
    return 1 if any(r[1] == FAIL for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())

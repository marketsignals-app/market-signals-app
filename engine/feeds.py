"""Scheduled Telegram feeds: each kind of alert goes out on its own cadence instead of in one digest per run.

A feed has a clock window and a cadence in minutes. Time is cut into slots from the start of the window (a 40-minute feed that starts at 09:00 has
slots at 09:00, 09:40, 10:20 ...). The first run inside a slot sends the feed once; a slot that was missed is not replayed after the next one has begun
(its `grace`). Which slot was last sent is remembered in `feeds_sent` (kept with the other sent-alert memory), so a restart or a failed run cannot send a slot twice.

Event feeds (readings, movers, deals ...) are filled as events happen and flushed when the feed is due. Snapshot feeds (indexes, commodities, sectors ...) are
built when due. A few events are urgent and go out at once. Cadences can be changed in config/alerts.json under "feeds" without touching code.
"""
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
WEEKDAYS = (0, 1, 2, 3, 4)
MARKET = {"start": "09:15", "end": "15:30", "days": WEEKDAYS}

FEEDS = {
    "readings": {"label": "Bullish and bearish readings", "every": 15, **MARKET, "kind": "event", "max_age_h": 6},
    "movers": {"label": "Movers", "every": 30, **MARKET, "kind": "event", "max_age_h": 3},
    "volatility": {"label": "Volatility breaches", "every": 15, **MARKET, "kind": "event", "max_age_h": 3},
    "circuits": {"label": "Circuit hits", "every": 15, **MARKET, "kind": "event", "max_age_h": 2},
    "corp_actions": {"label": "Corporate actions", "every": 15, "start": "08:00", "end": "22:00", "days": WEEKDAYS, "kind": "event", "max_age_h": 12},
    "surveillance": {"label": "Surveillance and F&O ban", "every": 60, "start": "08:30", "end": "21:30", "days": WEEKDAYS, "kind": "event", "max_age_h": 12},
    "gaps": {"label": "Gaps at the open", "every": 15, "start": "09:20", "end": "10:05", "days": WEEKDAYS, "kind": "event", "max_age_h": 2},
    "action_dates": {"label": "Share actions coming up", "every": 1440, "start": "08:40", "end": "08:40", "days": WEEKDAYS, "grace": 120, "kind": "snapshot"},
    "ipo_breakout": {"label": "IPO breakouts", "every": 30, **MARKET, "kind": "event", "max_age_h": 3},
    "deals": {"label": "Block deals", "every": 15, **MARKET, "kind": "event", "max_age_h": 6},
    "filings": {"label": "Important filings", "every": 15, "start": "08:00", "end": "22:00", "days": WEEKDAYS, "kind": "event", "max_age_h": 12},
    "news": {"label": "Company headlines", "every": 60, "start": "09:00", "end": "21:00", "days": WEEKDAYS, "kind": "event", "max_age_h": 12},
    "indexes": {"label": "Indexes", "every": 60, **MARKET, "kind": "snapshot"},
    "commodities": {"label": "Commodities and currency", "every": 40, "start": "09:00", "end": "23:30", "days": WEEKDAYS, "kind": "snapshot"},
    "sectors": {"label": "Sector growth", "every": 90, **MARKET, "kind": "snapshot"},
    "bulk_deals": {"label": "Bulk deals", "every": 1440, "start": "18:00", "end": "18:00", "days": WEEKDAYS, "grace": 240, "kind": "snapshot"},
    "news_digest": {"label": "Latest important news", "every": 60, "start": "09:30", "end": "21:30", "days": WEEKDAYS, "kind": "snapshot"},
    "ipo_upcoming": {"label": "Upcoming IPOs", "every": 1440, "start": "09:00", "end": "09:00", "days": (0, 1, 2, 3, 4, 5, 6), "grace": 180, "kind": "snapshot"},
    "events_today": {"label": "Today's events", "every": 1440, "start": "08:30", "end": "08:30", "days": WEEKDAYS, "grace": 120, "kind": "snapshot"},
    "weekly": {"label": "Weekly summary", "every": 1440, "start": "18:00", "end": "18:00", "days": (6,), "grace": 360, "kind": "snapshot"},
}

# the feed that carries each kind of alert item; kinds not listed here go out at once
FEED_OF_KIND = {"signal": "readings", "mover": "movers", "low52": "movers", "ipo": "ipo_breakout", "deal": "deals", "filing": "filings", "news": "news"}
QUEUE_LIMIT = 400


def settings(overrides=None):
    """The feed table with any changes from config/alerts.json ({"feeds": {name: {field: value}}}). Unknown names and a non-positive cadence are ignored."""
    table = {name: dict(spec) for name, spec in FEEDS.items()}
    for name, change in ((overrides or {}).get("feeds") or {}).items():
        if name in table and isinstance(change, dict):
            if "every" in change and not (isinstance(change["every"], (int, float)) and change["every"] > 0):
                continue
            table[name].update({k: v for k, v in change.items() if k in ("every", "start", "end", "days", "grace", "enabled", "label")})
    return {name: spec for name, spec in table.items() if spec.get("enabled", True)}


def _minutes(clock):
    hour, minute = clock.split(":")
    return int(hour) * 60 + int(minute)


def slot_of(spec, now):
    """The id of the slot `now` falls in for this feed, or None when it is outside the window, on a day the feed does not run, or past the slot's grace."""
    local = now.astimezone(IST)
    if local.weekday() not in tuple(spec["days"]):
        return None
    start, end, every = _minutes(spec["start"]), _minutes(spec["end"]), spec["every"]
    minute = local.hour * 60 + local.minute
    if minute < start:
        return None
    number = int((minute - start) // every)
    slot_start = start + number * every
    if slot_start > end or minute - slot_start >= spec.get("grace", every):
        return None
    return f"{local:%Y-%m-%d}#{number}"


def due(sent, now, table):
    """{feed: slot id} for the feeds whose current slot has not been sent yet."""
    out = {}
    for name, spec in table.items():
        slot = slot_of(spec, now)
        if slot and (sent or {}).get(name) != slot:
            out[name] = slot
    return out


def mark_sent(sent, name, slot):
    sent[name] = slot
    return sent


def feed_for(item):
    """The feed an alert item belongs to, or None for an item that goes out at once (a brief, an urgent index alert)."""
    if item.get("urgent"):
        return None
    return item.get("feed") or FEED_OF_KIND.get(item.get("kind"))


def split(items):
    """(items to send now, [(feed, item)] to hold for their feed)."""
    now_items, held = [], []
    for item in items:
        feed = feed_for(item)
        if feed:
            held.append((feed, item))
        else:
            now_items.append(item)
    return now_items, held


def enqueue(queue, held, now_ts):
    """The queue with newly held items added (oldest dropped past the limit)."""
    queue = [q for q in queue if isinstance(q, dict) and "feed" in q and "item" in q]
    queue += [{"feed": feed, "ts": int(now_ts), "item": item} for feed, item in held]
    return queue[-QUEUE_LIMIT:]


def take(queue, name, now_ts, table):
    """(items of this feed that are still fresh, the queue without this feed's items). Items older than the feed's max_age_h are dropped, not sent late."""
    limit = table.get(name, {}).get("max_age_h", 12) * 3600
    mine = [q for q in queue if q["feed"] == name]
    rest = [q for q in queue if q["feed"] != name]
    return [q["item"] for q in mine if now_ts - q["ts"] <= limit], rest


def clean_sent(sent):
    """Only feeds that still exist, as plain strings."""
    return {k: v for k, v in (sent or {}).items() if k in FEEDS and isinstance(v, str)}

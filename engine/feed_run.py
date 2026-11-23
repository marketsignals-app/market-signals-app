"""One run's worth of scheduled Telegram sending (see engine/feeds.py for the schedule and engine/digest_feeds.py for the layout).

`dispatch` takes the alert items found in this run, holds the ones that belong to a feed, builds the snapshot feeds that are due, sends each due feed as its own
message(s) and returns the state to remember (which slot of each feed was sent, the held items) and the track-record calls for the readings that were sent.
A feed's slot is marked sent only when all its messages were delivered, and held items go back in the queue when a send fails, so nothing is lost or sent twice.
"""
from datetime import datetime

from . import alerts, digest_feeds, feed_items, feeds, sessions, tracking

URGENT_LABEL = "Alert"
KIND_ORDER = {"signal": 0, "mover": 0, "ipo": 0, "deal": 0, "filing": 0, "news": 0, "low52": 1}
FEED_TAG = {"readings": "#Readings", "movers": "#Movers", "ipo_breakout": "#IPOBreakout", "deals": "#BlockDeals", "filings": "#Filings", "news": "#News", "indexes": "#Indexes",
            "commodities": "#Commodities", "sectors": "#Sectors", "news_digest": "#NewsDigest", "ipo_upcoming": "#UpcomingIPO", "events_today": "#Events", "weekly": "#Weekly",
            "bulk_deals": "#BulkDeals", "volatility": "#VolatilityBreaches"}


def _side_now(record, horizon):
    label = ((record or {}).get(horizon) or {}).get("label")
    return alerts.side(label) if label and label != "N/A" else None


def _still_true(item, records):
    """A reading held in the queue is sent only if the stock's reading is still on that side: otherwise it has already reversed and the alert would mislead."""
    if item.get("kind") != "signal":
        return True
    return _side_now(records.get(item.get("symbol")), item.get("horizon")) == item.get("side")


def urgent_entries(items, now):
    """(items to send at once, urgent index entries in their place): a brief goes out as it is, an urgent index item becomes an entry, other index items are dropped
    (the hourly Indexes feed carries the level and the day move; the app keeps the full alert log)."""
    out = []
    for item in items:
        if item.get("kind") == "index":
            if item.get("urgent") and str(item.get("name")).upper() in feed_items.INDEX_NAMES:      # Indian indexes and India VIX only: no US or other global cues
                out.append(feed_items.index_alert_entry(item, now))
        else:
            out.append(item)
    return out


def build_snapshot(name, src, now, today_iso):
    """The items of a snapshot feed, or [] when there is nothing to say (the feed is then not marked as sent and is tried again within its grace)."""
    try:
        if name == "indexes":
            item = feed_items.indexes_table(src.get("indices"), now) if src.get("india_open") else None
        elif name == "commodities":
            item = feed_items.commodities_table(src.get("watch"), now)
        elif name == "sectors":
            item = feed_items.sectors_table(src.get("sectors"), now) if src.get("india_open") else None
        elif name == "news_digest":
            return feed_items.news_digest_lines(src.get("news_dashboard"))
        elif name == "ipo_upcoming":
            return feed_items.upcoming_ipo_entries(src.get("ipos"), datetime.fromisoformat(today_iso).date())
        elif name == "events_today":
            return feed_items.events_today_entries(src.get("events"), today_iso)
        elif name == "weekly":
            return feed_items.weekly_entries(src.get("track_record"), src.get("learning"), src.get("health"))
        elif name == "bulk_deals":
            payload = src["bulk_payload"]() if callable(src.get("bulk_payload")) else None
            return feed_items.bulk_deal_items(payload, src.get("today_label"), src.get("names"))
        else:
            return []
    except Exception as err:                                     # one feed failing must not stop the others
        print(f"Feed {name} could not be built:", err)
        return []
    return [item] if item else []


def dispatch(items, state, now, now_ts, table, src, records, send, link_of, today_iso):
    """Returns (new state keys, calls, sent), where calls are [(position, call)] for the readings sent and sent is a list of (feed, messages sent).

    state: the remembered {"feeds_sent", "feed_queue"}. src: what the snapshot feeds read (see build_snapshot). records: {symbol: record} for the reading check and the calls.
    send(text) -> (ok, message_id). link_of(item) -> an address or None. Nothing is sent when send is None (Telegram is not set up)."""
    sent_slots = feeds.clean_sent(state.get("feeds_sent"))
    first_deploy = "feeds_sent" not in state
    queue = state.get("feed_queue") if isinstance(state.get("feed_queue"), list) else []

    now_items, held = feeds.split(urgent_entries(items, now))
    queue = feeds.enqueue(queue, held, now_ts)
    due = feeds.due(sent_slots, now, table)
    if first_deploy:                                             # a new feed table starts with the next slot: no burst of every feed at once
        for name, slot in due.items():
            feeds.mark_sent(sent_slots, name, slot)
        return {"feeds_sent": sent_slots, "feed_queue": queue}, [], []
    if send is None:
        return {"feeds_sent": sent_slots, "feed_queue": queue}, [], []

    groups = []                                                  # (name, label, icon, items to send, slot or None, whether a failed send puts them back in the queue)
    if now_items:
        groups.append(("urgent", URGENT_LABEL, digest_feeds.ICONS["urgent"], now_items, None, False))
    for name, slot in due.items():
        spec = table[name]
        if spec.get("kind") == "event":
            taken, queue = feeds.take(queue, name, now_ts, table)
            built, requeue = sorted([i for i in taken if _still_true(i, records)], key=lambda i: KIND_ORDER.get(i.get("kind"), 9)), True       # stable: same kinds sit together, one section each
        else:
            built, requeue = build_snapshot(name, src, now, today_iso), False
        if built:
            groups.append((name, spec["label"], digest_feeds.ICONS.get(name, "📊"), built, slot, requeue))

    calls, sent, base = [], [], 0
    for name, label, icon, built, slot, requeue in groups:
        links = [link_of(i) for i in built]
        messages = digest_feeds.render_feed(built, links, now_ts, label, [FEED_TAG[name]] if name in FEED_TAG else [], icon)
        positions = [n for n, i in enumerate(built) if i.get("kind") == "signal"]
        group_calls = [(positions[j], c) for j, c in tracking.make_calls([built[n] for n in positions], records, now_ts)]
        sent_until, complete = 0, True
        for text, start, end in messages:
            ok, message_id = send(text)
            print(f"Telegram {label}: {'sent' if ok else 'FAILED'} ({end - start} items)")
            if not ok:
                complete = False
                break
            tracking.attach_message(group_calls, end, message_id, start)
            sent_until = end
        if complete:
            if slot:
                feeds.mark_sent(sent_slots, name, slot)
            sent.append((name, len(messages)))
            if len(built) > sent_until:
                pass                                              # items beyond the last message were counted as "+N more" in it, and stay in the app
        elif requeue:
            queue = feeds.enqueue(queue, [(name, i) for i in built[sent_until:]], now_ts)      # only what was not delivered goes back
        calls += [(base + n, c) for n, c in group_calls if n < sent_until]
        base += len(built)
    return {"feeds_sent": sent_slots, "feed_queue": queue}, calls, sent

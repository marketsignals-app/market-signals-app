"""One run's worth of scheduled Telegram sending (see engine/feeds.py for the schedule and engine/digest_feeds.py for the layout).

`dispatch` takes the alert items found in this run, holds the ones that belong to a feed, builds the snapshot feeds that are due, sends each due feed as its own
message(s) and returns the state to remember (which slot of each feed was sent, the held items) and the track-record calls for the readings that were sent.
A feed's slot is marked sent only when all its messages were delivered, and held items go back in the queue when a send fails, so nothing is lost or sent twice.
"""
from datetime import datetime

from . import alerts, digest_feeds, feed_items, feeds, sessions, tracking

URGENT_LABEL = "Alert"
BREACHES_PER_RUN = 5          # breaches sent one by one at the next run; any more wait for the 15-minute volatility feed
ANNOUNCED_DAYS = 45          # a breach replies to the stock's reading alert only if it is this recent
ANNOUNCED_LIMIT = 500
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


def _reply_target(announced, item):
    """(message id to reply to or None, a sub-point naming the earlier reading) for a stock whose reading was announced recently."""
    entry = (announced or {}).get(item.get("symbol"))
    if not entry or not entry.get("id"):
        return None, None
    side = {"buy": "bullish", "sell": "bearish"}.get(entry.get("side"), entry.get("side"))
    return entry["id"], f"Earlier reading alert: {side}, {entry.get('horizon') or 'weeks'} view, announced {entry.get('date')}"


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
    send(text, reply_to=None) -> (ok, message_id). link_of(item) -> an address or None. Nothing is sent when send is None (Telegram is not set up)."""
    sent_slots = feeds.clean_sent(state.get("feeds_sent"))
    first_deploy = "feeds_sent" not in state
    queue = state.get("feed_queue") if isinstance(state.get("feed_queue"), list) else []

    breaches = [i for i in items if i.get("feed") == "volatility"]
    items = [i for i in items if i.get("feed") != "volatility"]
    now_items, held = feeds.split(urgent_entries(items, now))
    announced = {k: v for k, v in (state.get("announced") or {}).items() if isinstance(v, dict) and now_ts - v.get("ts", 0) <= ANNOUNCED_DAYS * 86400}
    individually = breaches[:BREACHES_PER_RUN] if send is not None and "feeds_sent" in state else []
    held += [("volatility", i) for i in breaches if i not in individually]
    queue = feeds.enqueue(queue, held, now_ts)
    due = feeds.due(sent_slots, now, table)
    if first_deploy:                                             # a new feed table starts with the next slot: no burst of every feed at once
        for name, slot in due.items():
            feeds.mark_sent(sent_slots, name, slot)
        return {"feeds_sent": sent_slots, "feed_queue": queue, "announced": announced}, [], []
    if send is None:
        return {"feeds_sent": sent_slots, "feed_queue": queue, "announced": announced}, [], []

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
    for item in individually:                                  # a breach is rare and time-sensitive: one message each, as a reply under the reading alert when there is one
        reply_to, earlier = _reply_target(announced, item)
        if earlier:
            item = {**item, "points": item["points"] + [earlier]}
        text = digest_feeds.render_feed([item], [link_of(item)], now_ts, "Volatility breach", ["#VolatilityBreach"], digest_feeds.ICONS["volatility"])[0][0]
        ok, _ = send(text, reply_to)
        if not ok and reply_to:                                # the original message may be gone: send it as a normal message
            ok, _ = send(text, None)
        print(f"Telegram volatility breach {item['heading']}: {'sent' + (' as a reply' if reply_to else '') if ok else 'FAILED'}")
        if not ok:
            queue = feeds.enqueue(queue, [("volatility", item)], now_ts)
    for name, label, icon, built, slot, requeue in groups:
        links = [link_of(i) for i in built]
        messages = digest_feeds.render_feed(built, links, now_ts, label, [FEED_TAG[name]] if name in FEED_TAG else [], icon)
        positions = [n for n, i in enumerate(built) if i.get("kind") == "signal"]
        group_calls = [(positions[j], c) for j, c in tracking.make_calls([built[n] for n in positions], records, now_ts)]
        sent_until, complete = 0, True
        for text, start, end in messages:
            ok, message_id = send(text, None)
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
        for n, c in group_calls:                               # remember which message announced each reading, so a later alert on the stock can reply to it
            if n < sent_until and c.get("telegram_message_id"):
                announced[c["symbol"]] = {"id": c["telegram_message_id"], "ts": now_ts, "side": c["side"], "horizon": c["horizon"], "date": c["date"]}
        base += len(built)
    announced = dict(sorted(announced.items(), key=lambda kv: kv[1].get("ts", 0))[-ANNOUNCED_LIMIT:])
    return {"feeds_sent": sent_slots, "feed_queue": queue, "announced": announced}, calls, sent

"""Builds the items of the scheduled feeds (engine/feeds.py) and the hashtags they carry.

Item shapes (rendered by engine/digest.py):
  style A, a numbered heading with sub-points: {"kind": "signal" ...} (a reading), {"kind": "filing" ...}, {"kind": "entry", "title", "heading", "points", "tags", "link"}
  style B, one line each:                      mover, low52, ipo, deal, news, and {"kind": "line", "title", "text", "tags", "link"}
  style C, a monospace table:                  {"kind": "table", "title", "header", "rows", "source", "tags"}
Everything here is a plain function of its inputs: no network, no clock except the one passed in.
"""
import hashlib
import re
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
SUFFIXES = (".NS", ".BO")
STALE_DAYS = 2
INDEX_NAMES = {"NIFTY 50": "Nifty 50", "NIFTY NEXT 50": "Nifty Next 50", "NIFTY BANK": "Bank Nifty", "NIFTY IT": "Nifty IT", "NIFTY AUTO": "Nifty Auto",
               "NIFTY FMCG": "Nifty FMCG", "NIFTY PHARMA": "Nifty Pharma", "NIFTY METAL": "Nifty Metal", "NIFTY ENERGY": "Nifty Energy", "NIFTY REALTY": "Nifty Realty",
               "NIFTY FIN SERVICE": "Nifty Financials", "NIFTY MIDCAP 100": "Nifty Midcap 100", "NIFTY SMLCAP 100": "Nifty Smallcap 100", "NIFTY 500": "Nifty 500",
               "INDIA VIX": "India VIX"}
MIN_FILING_IMPACT = 70
ROUTINE_EVENTS = {"routine", "investor_call", "volume"}


# ---------- hashtags ----------
def symbol_tag(symbol):
    """#AXISBANK for AXISBANK.NS, #M_M for M&M.NS: Telegram hashtags are letters, digits and underscores, and cannot be digits only."""
    base = str(symbol or "")
    for suffix in SUFFIXES:
        if base.upper().endswith(suffix):
            base = base[: -len(suffix)]
    tag = re.sub(r"[^0-9A-Za-z]+", "_", base).strip("_")
    return _safe(tag)


def word_tag(text):
    """#BankNifty for "Bank Nifty", #PharmaAndHealth for "Pharma and Health"."""
    words = [w for w in re.split(r"[^0-9A-Za-z]+", str(text or "")) if w]
    return _safe("".join(w[:1].upper() + w[1:] for w in words))


def _safe(tag):
    if not tag:
        return ""
    return "#" + ("N" + tag if tag.isdigit() else tag)


def tags(*parts):
    """A de-duplicated list of hashtags from ready tags ("#X") and words."""
    out = []
    for part in parts:
        if not part:
            continue
        tag = part if str(part).startswith("#") else word_tag(part)
        if tag and tag not in out:
            out.append(tag)
    return out


def _stamp(now):
    return now.astimezone(IST).strftime("%H:%M IST")


def _pretty_date(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b")
    except (TypeError, ValueError):
        return "date unknown"


def _signed(value, digits=2):
    return f"{value:+.{digits}f}%" if isinstance(value, (int, float)) else "–"


# ---------- style C: tables ----------
def indexes_table(indices, now, names=INDEX_NAMES):
    """The Indexes feed: the Indian indexes the NSE feed carries, with the day move and a 52-week note. None when the feed has none of them."""
    rows = []
    for key, label in names.items():
        row = (indices or {}).get(key)
        if not row or not isinstance(row.get("last"), (int, float)):
            continue
        note = ""
        if row.get("high52") and row["last"] >= row["high52"] * 0.999:
            note = "52w high"
        elif row.get("low52") and row["last"] <= row["low52"] / 0.999:
            note = "52w low"
        rows.append([label, f"{row['last']:,.2f}", _signed(row.get("pct")), note])
    if not rows:
        return None
    return {"kind": "table", "feed": "indexes", "title": "INDEXES", "header": ["Index", "Level", "Day", ""], "rows": rows,
            "source": f"NSE all-indices feed, read {_stamp(now)}", "tags": tags("#Indexes", "#Nifty50", "#BankNifty", "#IndiaVIX" if "INDIA VIX" in indices else None)}


def commodities_table(watch, now):
    """The Commodities feed: crude oil, gold and the rupee from the app's market watch, each with the date of its last data and a stale mark when it is old."""
    today = now.astimezone(IST).date()
    rows, labels = [], []
    for w in watch or []:
        if w.get("kind") not in ("commodity", "currency") or not isinstance(w.get("price"), (int, float)):
            continue
        prefix = "$" if w["kind"] == "commodity" else ""
        age = None
        try:
            age = (today - date.fromisoformat(w.get("as_of"))).days
        except (TypeError, ValueError):
            pass
        note = f"data {_pretty_date(w.get('as_of'))}" + (" STALE" if age is not None and age > STALE_DAYS else "")
        rows.append([w["name"], f"{prefix}{w['price']:,.2f}", _signed(w.get("change_pct")), note])
        labels.append(w["name"])
    if not rows:
        return None
    return {"kind": "table", "feed": "commodities", "title": "COMMODITIES", "header": ["", "Price", "Day", ""], "rows": rows,
            "source": "Yahoo Finance, delayed; no second source. Data older than 2 days is marked STALE", "tags": tags("#Commodities", *labels)}


def sectors_table(sectors, now, count=3):
    """The Sector feed: the strongest and weakest sectors today (average move of the stocks of our list in each), with the number of stocks behind each figure."""
    rated = [s for s in sectors or [] if isinstance(s.get("d1"), (int, float)) and (s.get("n") or 0) >= 3]
    if len(rated) < 2:
        return None
    ordered = sorted(rated, key=lambda s: -s["d1"])
    top, bottom = ordered[:count], [s for s in ordered[::-1][:count] if s not in ordered[:count]]
    rows = [[s["sector"], _signed(s["d1"]), _signed(s.get("d5"), 1), str(s.get("n"))] for s in top]
    if bottom:
        rows.append(["-", "-", "-", "-"])
        rows += [[s["sector"], _signed(s["d1"]), _signed(s.get("d5"), 1), str(s.get("n"))] for s in bottom]
    return {"kind": "table", "feed": "sectors", "title": "SECTOR GROWTH", "header": ["Sector", "Today", "5 days", "Stocks"], "rows": rows,
            "source": f"average move of the stocks of our list in each sector, {_stamp(now)}", "tags": tags("#Sectors", *[s["sector"] for s in top + bottom])}


# ---------- style A: entries ----------
def index_alert_entry(item, now):
    """An urgent index or volatility alert (a move of 2% or more, a volatility index past its level) as a numbered entry."""
    name = INDEX_NAMES.get(str(item.get("name")).upper(), item.get("name"))
    vix = "VIX" in str(item.get("name")).upper()
    points = [f"{t}" for t in item.get("tags", [])]
    if vix:
        points.append("Calm is below 15, above 20 means larger swings, above 25 is fearful")
    return {"kind": "entry", "urgent": True, "title": "VOLATILITY ALERT" if vix else "INDEX ALERT", "heading": f"{name} {item.get('last', 0):,.2f}",
            "points": points + [f"Source: NSE all-indices feed, {_stamp(now)}"], "tags": tags("#Volatility" if vix else "#IndexMove", word_tag(name))}


def filing_entries(stories, seen, now_ts, min_impact=MIN_FILING_IMPACT, limit=6, names=None):
    """(items, seen): official filings (NSE or BSE) whose rule-based impact is high and that have not been sent. Routine filings are skipped.
    The reading shown is the rule-based one; it is not a signal."""
    seen = {k: v for k, v in (seen or {}).items() if now_ts - v <= 3 * 86400}
    found = []
    for s in stories or []:
        if s.get("kind") not in ("nse", "bse") or (s.get("impact") or 0) < min_impact or s.get("event") in ROUTINE_EVENTS or not s.get("symbol"):
            continue
        key = hashlib.sha1(f"{s.get('symbol')}|{s.get('title')}|{s.get('ts')}".encode()).hexdigest()[:16]
        if key in seen:
            continue
        seen[key] = now_ts
        found.append(s)
    found.sort(key=lambda s: -(s.get("impact") or 0))
    items = []
    for s in found[:limit]:
        when = datetime.fromtimestamp(s["ts"], IST).strftime("%d %b %H:%M IST") if isinstance(s.get("ts"), (int, float)) else "time unknown"
        items.append({"kind": "filing", "symbol": s["symbol"], "name": (names or {}).get(s["symbol"]) or s.get("name") or symbol_tag(s["symbol"]).lstrip("#"), "event_label": s.get("event_label") or "Filing", "title": s.get("title") or "",
                      "sentiment": s.get("sentiment"), "impact": s.get("impact"), "source": s.get("source") or "NSE", "when": when, "link": s.get("link") or ""})
    return items, seen


def upcoming_ipo_entries(rows, today, horizon_days=7, limit=10):
    """Mainboard and SME IPOs that are open, close today, open within the next week or list within three days."""
    out = []
    for r in rows or []:
        try:
            opens = date.fromisoformat(r["open"]) if r.get("open") else None
            closes = date.fromisoformat(r["close"]) if r.get("close") else None
            lists = date.fromisoformat(r["listing"]) if r.get("listing") else None
        except (TypeError, ValueError):
            continue
        if closes and closes < today and not (lists and today <= lists <= today + timedelta(days=3)):
            continue
        status = None
        if closes and opens and opens <= today <= closes:
            status = "CLOSES TODAY" if closes == today else "OPEN now"
        elif opens and today < opens <= today + timedelta(days=horizon_days):
            status = f"opens in {(opens - today).days} day{'s' if (opens - today).days != 1 else ''}"
        elif lists and today <= lists <= today + timedelta(days=3):
            status = "lists " + ("today" if lists == today else _pretty_date(r["listing"]))
        if not status:
            continue
        points = [f"{status}: opens {_pretty_date(r.get('open'))}, closes {_pretty_date(r.get('close'))}, lists {_pretty_date(r.get('listing'))}"]
        bits = [f"price ₹{r['price']:,.0f}" if isinstance(r.get("price"), (int, float)) else None, f"lot {r['lot']:,}" if r.get("lot") else None,
                f"size ₹{r['size_cr']:,.1f} cr" if isinstance(r.get("size_cr"), (int, float)) else None]
        points.append(" · ".join(b for b in bits if b) or "price band not published yet")
        if isinstance(r.get("subscription"), (int, float)):
            points.append(f"Subscription so far: {r['subscription']:.2f}x")
        points.append(f"Grey-market premium (unofficial): {r['gmp_pct']:+.1f}%" if isinstance(r.get("gmp_pct"), (int, float)) else "Grey-market premium: not available")
        out.append(((opens or today), {"kind": "entry", "title": "UPCOMING IPOS", "heading": f"{r.get('name')} ({r.get('board') or 'IPO'})", "points": points,
                                       "tags": tags("#IPO", "#UpcomingIPO", "#SME" if r.get("board") == "SME" else None), "link": r.get("link") or ""}))
    out.sort(key=lambda x: x[0])
    return [item for _, item in out[:limit]]


def events_today_entries(events, today_iso, limit=12):
    """Confirmed Indian events dated today: results, ex-dividend dates and the like, with their official source."""
    out = []
    for e in events or []:
        if e.get("date") != today_iso or e.get("market") != "IN" or e.get("verification") != "CONFIRMED":
            continue
        official = e.get("official") or {}
        points = [e.get("detail") or e.get("title") or "", f"Source: {e.get('source') or 'official'}"]
        out.append({"kind": "entry", "title": "TODAY'S EVENTS", "heading": f"{e.get('name') or e.get('symbol')}: {e.get('title') or e.get('type')}", "points": [p for p in points if p],
                    "tags": tags(symbol_tag(e.get("symbol")), "#Events", word_tag(e.get("type"))), "link": official.get("link") or ""})
    return out[:limit]


def regime_entry(conditions, last_label):
    """(entry or None, label now): an entry when the market-conditions label has changed since the last one sent. The first run only records the label."""
    regime = ((conditions or {}).get("IN") or {}).get("regime") or {}
    label = regime.get("label")
    if not label or label == last_label or last_label is None:
        return None, label or last_label
    points = [f"Before: {last_label}", f"Score {regime.get('score'):+d} from seven simple checks" if isinstance(regime.get("score"), int) else "Seven simple checks on the Nifty 50"]
    points += [c.get("detail") for c in (regime.get("checks") or [])[:3] if c.get("detail")]
    return {"kind": "entry", "title": "MARKET CONDITIONS", "heading": f"Market conditions changed to {label}", "points": points, "tags": tags("#MarketConditions", "#Nifty50")}, label


def weekly_entries(track_record, learning_summary, health):
    """The Sunday summary: the track record, what the learning outlook has found, and any degraded data source. Honest about samples: small counts are said to be small."""
    out = []
    overall = (track_record or {}).get("overall") or {}
    if track_record:
        n = overall.get("n") or 0
        points = [f"{n} settled calls, {track_record.get('open', 0)} still open, {track_record.get('void', 0)} voided (price never traded)"]
        if n:
            points.append(f"Reached target {overall.get('target_pct')}% · hit the risk level {overall.get('stop_pct')}% · expired {overall.get('expired_pct')}%")
            points.append("Fewer than %s settled calls: too few to read a rate from" % track_record.get("min_sample") if not overall.get("reliable") else "Enough settled calls to read a rate, with its range on the Record tab")
        out.append({"kind": "entry", "title": "WEEKLY SUMMARY", "heading": "Track record", "points": points, "tags": tags("#Weekly", "#TrackRecord")})
    validation = (learning_summary or {}).get("validation") or {}
    if validation:
        points = []
        for horizon, v in validation.items():
            if isinstance(v, dict):
                points.append(f"{horizon} days: " + ("beat the base rate on later data" if v.get("edge") else "no better than the base rate on later data"))
        if points:
            out.append({"kind": "entry", "title": "WEEKLY SUMMARY", "heading": "Learning outlook (tested on later data)", "points": points, "tags": tags("#Weekly", "#Outlook")})
    degraded = [s["name"] for s in (health or {}).get("sources", []) if s.get("state") == "degraded"]
    quarantined = len((health or {}).get("quarantined", []))
    if degraded or quarantined:
        out.append({"kind": "entry", "title": "WEEKLY SUMMARY", "heading": "Data health",
                    "points": ([f"Degraded sources: {', '.join(degraded)}"] if degraded else []) + ([f"{quarantined} stocks paused after repeated data problems"] if quarantined else []),
                    "tags": tags("#Weekly", "#DataHealth")})
    return out


# ---------- style B: lines ----------
def news_digest_lines(dashboard, limit=4):
    """The hourly news and sentiment lines: the most positive and most negative stocks by rule-based sentiment (not signals)."""
    out = []
    for title, rows in (("MOST POSITIVE NEWS", (dashboard or {}).get("top_positive")), ("MOST NEGATIVE NEWS", (dashboard or {}).get("top_negative"))):
        for r in (rows or [])[:limit]:
            move = f" · price {_signed(r.get('change_pct'))}" if isinstance(r.get("change_pct"), (int, float)) else ""
            check = {"confirms": " · confirms the reading", "conflicts": " · conflicts with the reading"}.get(r.get("validation"), "")
            out.append({"kind": "line", "title": title, "text": f"{r.get('name')} · sentiment {r.get('sentiment'):+d} · impact {r.get('impact')}{move}{check}",
                        "tags": tags(symbol_tag(r.get("symbol")), "#News"), "link": ""})
    return out


def volatility_breach_items(records, quotes, india_open, seen, now_ts, today_iso, multiple=2.0, limit=8, skip=()):
    """(items, seen): stocks whose move today, from the previous close, is at least `multiple` times their own 14-day average daily range (ATR).

    Only while the market is open, only for stocks with trusted data (not paused, not lagging, price not disputed) and a live quote. A stock is announced once a day for each
    whole multiple it reaches (2x, then 3x ...), so a move that keeps growing is announced again but not repeated. The strongest come first."""
    seen = {k: v for k, v in (seen or {}).items() if now_ts - v <= 3 * 86400}
    if not india_open:
        return [], seen
    found = []
    for r in records or []:
        symbol = r.get("symbol")
        q = (quotes or {}).get(symbol) or {}
        atr = (r.get("indicators") or {}).get("atr")
        price, change = q.get("price"), q.get("change_pct")
        if (symbol in skip or r.get("carried") or r.get("series_lag") or r.get("quarantine") or r.get("provenance_ok") is False or "thin" in (r.get("flags") or [])
                or q.get("state") not in (None, "REGULAR") or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (atr, price, change)) or atr <= 0 or change <= -99):
            continue
        previous = price / (1 + change / 100)
        move = price - previous
        ratio = abs(move) / atr
        tier = int(ratio)
        if tier < multiple:
            continue
        key = f"{symbol}|{today_iso}|{'up' if move > 0 else 'down'}|{min(tier, 6)}"
        if key in seen:
            continue
        seen[key] = now_ts
        found.append((ratio, r, price, previous, move, atr, change))
    found.sort(key=lambda row: -row[0])
    items = []
    for ratio, r, price, previous, move, atr, change in found[:limit]:
        direction = "up" if move > 0 else "down"
        items.append({"kind": "entry", "feed": "volatility", "title": "VOLATILITY BREACHES", "heading": f"{r.get('name') or symbol_tag(r['symbol']).lstrip('#')}: {change:+.1f}% today",
                      "points": [f"Moved {direction} \u20b9{abs(move):,.2f}, which is {ratio:.1f}x its 14-day average daily range (\u20b9{atr:,.2f})",
                                 f"Price \u20b9{price:,.2f}; previous close \u20b9{previous:,.2f}",
                                 "A move beyond twice the normal daily range: unusually large for this stock",
                                 f"Source: Yahoo Finance quote (delayed), range from completed daily candles"],
                      "tags": tags(symbol_tag(r["symbol"]), "#VolatilityBreach", "#Volatility", word_tag(r.get("sector"))), "symbol": r["symbol"]})
    return items, seen


def bulk_deal_items(payload, today_label, names=None, limit=12):
    """The day's bulk deals as the NSE publishes them (after the close, with the client's name): the largest by value, as one-line items.
    payload is the NSE large-deals snapshot; today_label looks like 23-Nov-2026. Only deals dated today are used; rows without a quantity or price are skipped."""
    rows = []
    for r in (payload or {}).get("BULK_DEALS_DATA", []) if isinstance(payload, dict) else []:
        if not isinstance(r, dict) or r.get("date") != today_label:
            continue
        try:
            qty, price = float(str(r.get("qty")).replace(",", "")), float(str(r.get("watp")).replace(",", ""))
        except (TypeError, ValueError):
            continue
        symbol = str(r.get("symbol") or "").strip()
        if not symbol or qty <= 0 or price <= 0:
            continue
        side = "BUY" if str(r.get("buySell") or "").upper().startswith("B") else "SELL"
        rows.append({"kind": "bulk", "symbol": symbol + ".NS", "name": (names or {}).get(symbol + ".NS") or symbol, "side": side, "qty": qty, "price": price, "value": qty * price,
                     "client": (r.get("clientName") or "").strip().title()})
    rows.sort(key=lambda r: -r["value"])
    return rows[:limit]


# ---------- operator message ----------
def health_text(health, quarantined_count=None):
    """The private operator message: sources that are degraded and stocks that are paused. None when all is well."""
    degraded = [f"{s['name']} ({s.get('detail') or 'degraded'})" for s in (health or {}).get("sources", []) if s.get("state") == "degraded"]
    paused = quarantined_count if quarantined_count is not None else len((health or {}).get("quarantined", []))
    if not degraded and not paused:
        return None
    lines = ["Stock Signals data health"]
    lines += [f"{i}. {d}" for i, d in enumerate(degraded, 1)]
    if paused:
        lines.append(f"{len(degraded) + 1}. {paused} stocks are paused after repeated data problems")
    return "\n".join(lines)

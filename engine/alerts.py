"""Alerts: a watched stock changes signal, or a fresh headline about it appears.

Each alert says what changed, gives a resistance or support reference and a volatility risk level, lists the
indicator readings behind it, and links to the stock's full analysis on the site. Alerts are written into the site's own data file (the "alerts" list)
and, if Telegram is set up, sent there too.
"""
import hashlib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import news, signals

SEEN_LIMIT = 500
DIGEST_LINES = 15
LOG_LIMIT = 30
LOG_MAX_AGE = 3 * 86400
TELEGRAM_MAX_CHARS = 4000
MAX_REASONS = 3
NOTE = "Levels are indicative, from fixed chart rules. Not advice."

# A signal only counts as moving when its score crosses these margins, so a score that hovers around a
# threshold (say 19, 21, 19, 22) does not send a message every run. Moving into Buy or Sell needs a score of
# +/-25. A Buy or Sell is only dropped once its score falls back through +/-10.
ENTER = 25
LEAVE = 10
NEWS_PER_RUN = 6      # at most this many headlines go into one run's alerts; the rest stay on the site
NEWS_PER_STOCK_DAY = 2   # at most this many headline alerts for one stock in 24 hours, so a very talked-about stock cannot fill the channel
STORY_SIMILARITY = 0.6   # a headline this similar to one already sent for the stock in 24 hours is the same story from another outlet
HISTORY_SECONDS = 86400



# How labels and sides are worded in messages. The stored labels stay Buy/Hold/Sell so records keep working.
LABEL_TEXT = {"Strong Buy": "Strongly aligned bullish", "Buy": "Aligned bullish", "Hold": "Mixed", "Sell": "Aligned bearish",
              "Strong Sell": "Strongly aligned bearish"}
SIDE_TEXT = {"buy": "bullish", "sell": "bearish", "hold": "mixed"}
HORIZON_TEXT = {"short": "Weeks view", "long": "Months-to-years view"}


def label_text(label):
    return LABEL_TEXT.get(label, label)


def side(label):
    return "buy" if label in ("Buy", "Strong Buy") else "sell" if label in ("Sell", "Strong Sell") else "hold"


def next_side(previous_side, score):
    """The side a signal is on after a new score, given the side it was on before."""
    if previous_side == "buy":
        if score <= -ENTER:
            return "sell"
        return "buy" if score > LEAVE else "hold"
    if previous_side == "sell":
        if score >= ENTER:
            return "buy"
        return "sell" if score < -LEAVE else "hold"
    if score >= ENTER:
        return "buy"
    if score <= -ENTER:
        return "sell"
    return "hold"


def changed_side(announced, signal):
    """The new side if this signal has really moved from the side last announced, otherwise None.

    signal is {"label", "score"}. Without a score the plain label decides.
    """
    label = (signal or {}).get("label")
    if not label or label == "N/A":
        return None
    score = signal.get("score")
    has_score = isinstance(score, (int, float)) and not isinstance(score, bool)
    new = next_side(announced, score) if has_score else side(label)
    return new if new != announced else None


def watched_symbols(configured, available):
    """Which stocks to alert on. "*" or "all" means every stock; otherwise the listed ones that exist."""
    available = set(available)
    if configured == "all" or (isinstance(configured, list) and ("*" in configured or "all" in configured)):
        return sorted(available)
    if not isinstance(configured, list):
        return []
    return [s for s in configured if s in available]


def news_key(item):
    return hashlib.sha1((item.get("link") or item["title"]).encode("utf-8")).hexdigest()[:16]


def stock_link(site_url, symbol, section="signals"):
    """Address of a stock's analysis on the site. Opening it shows the full analysis for that stock."""
    return f"{site_url.rstrip('/')}/#stock={urllib.parse.quote(symbol, safe='')}&section={section}"


BASIS_TEXT = {"resistance": "nearest resistance", "support": "nearest support", "52-week high": "52-week high",
              "52-week low": "52-week low"}


def level_details(record, new_side, horizon):
    """The reference level and volatility risk level for a bullish or bearish move, or None if they cannot be worked out.

    {"kind", "price", "pct", "basis", "risk_price", "risk_pct"}"""
    indicators = record.get("indicators") or {}
    zones = (record.get("levels") or {}).get("zones")
    levels = signals.target_levels(record.get("price"), indicators.get("atr"), zones, indicators.get("hi252"),
                                   indicators.get("lo252"), new_side)
    if not levels:
        return None
    target = levels[horizon]
    basis = BASIS_TEXT.get(target["basis"])
    if basis is None:
        multiple = signals.SHORT_FALLBACK_R if horizon == "short" else signals.LONG_FALLBACK_R
        basis = f"volatility-based, {multiple:g}x the risk distance"
    return {"kind": "Resistance reference" if new_side == "buy" else "Support reference", "price": target["price"],
            "pct": target["pct"], "basis": basis, "risk_price": levels["stop"]["price"], "risk_pct": levels["stop"]["pct"]}


def _levels_line(record, new_side, horizon):
    """The reference-level line for a bullish or bearish move, or None if it cannot be worked out."""
    d = level_details(record, new_side, horizon)
    if not d:
        return None
    return (f"{d['kind']} {d['price']:.2f} ({d['pct']:+.1f}%, {d['basis']}). "
            f"Volatility risk level {d['risk_price']:.2f} ({d['risk_pct']:+.1f}%).")


def reason_texts(signal, announced, new_side):
    """The reasons behind the new signal. For a signal that faded to hold, the reasons that weaken the old side."""
    wanted = {"buy": {"pos"}, "sell": {"neg"}}.get(new_side)
    if wanted is None:
        wanted = {"neg", "neutral"} if announced == "buy" else {"pos", "neutral"} if announced == "sell" else {"neutral"}
    return [r["text"] for r in (signal.get("reasons") or []) if isinstance(r, dict) and r.get("tone") in wanted and r.get("text")][:MAX_REASONS]


def _reasons_line(signal, announced, new_side):
    texts = reason_texts(signal, announced, new_side)
    return "Indicator readings: " + "; ".join(texts) + "." if texts else None


CURRENCY_SIGNS = {"INR": "\u20b9", "USD": "$"}


def money_text(value, currency):
    """1234.5, "INR" -> "\u20b91,234.50". Currencies without a sign are shown with their code after the number."""
    sign = CURRENCY_SIGNS.get(currency)
    return f"{sign}{value:,.2f}" if sign else f"{value:,.2f} {currency or ''}".strip()


def format_signal_alert(record, symbol, horizon, announced, new_side, signal):
    name = HORIZON_TEXT[horizon]
    label, score = signal["label"], signal.get("score")
    currency = record.get("currency") or ""
    score_text = f" (indicator alignment {score:+d})" if isinstance(score, int) and not isinstance(score, bool) else ""
    lines = [f"{label_text(label).upper()}: {record['name']} ({symbol})",
             f"{name}: {SIDE_TEXT[announced].capitalize()} -> {label_text(label)}{score_text}. Price {record['price']:.2f} {currency}".strip()]
    if new_side in ("buy", "sell"):
        levels = _levels_line(record, new_side, horizon)
        if levels:
            lines.append(levels)
    else:
        lines.append("No reference level: the reading has faded to mixed.")
    reasons = _reasons_line(signal, announced, new_side)
    if reasons:
        lines.append(reasons)
    return "\n".join(lines)


_WORD = re.compile(r"[a-z0-9]+")


def _words(title):
    return {w for w in _WORD.findall((title or "").lower()) if len(w) > 2}


def same_story(a, b):
    """Two headlines that share most of their words are one story reported by two outlets."""
    x, y = _words(a), _words(b)
    return bool(x and y) and len(x & y) / len(x | y) >= STORY_SIMILARITY


def build_messages(previous, current, watch, seen, first_run, news_on=True, sides=None, items=None, news_history=None, now_ts=None):
    """previous/current: {symbol: record}. Returns (lines, updated_seen_list).

    sides remembers, for each stock and horizon, the side (buy, hold or sell) last announced. It is updated in
    place, so the caller can keep it between runs. A move is measured from that side, which means a score that
    drifts up slowly cannot slip past without an alert.

    items, if given, receives one dict per line in the same order, with what is needed to lay the alert out
    ({"kind": "signal", ...} or {"kind": "news", ...}) and to link it. Readings come before headlines.

    News is passed on exactly as published: a headline about the company from the last few hours, with its source
    and link. No good-or-bad tone is worked out from its words, and news never changes a reading.

    On the first run nothing is reported, the current headlines are only recorded as seen. On every other run the
    newest headline of each stock is considered and the NEWS_PER_RUN newest overall are reported. The others are
    recorded as seen and stay on the site.

    Fairness: a stock gets at most NEWS_PER_STOCK_DAY headline alerts in 24 hours, a headline that repeats a story already
    sent for that stock is skipped, and when more stocks have news than fit in a run the ones alerted LEAST in the last 24
    hours go first (newest first among equals), so heavily covered stocks cannot crowd out the rest. news_history
    ({symbol: [{"ts", "title"}]}) records what was sent; it is updated in place and kept by the caller between runs.
    """
    history = {} if news_history is None else news_history
    clock = now_ts if now_ts is not None else int(datetime.now(timezone.utc).timestamp())
    sides = {} if sides is None else sides
    seen_set, seen_list = set(seen), list(seen)
    readings, candidates = [], []
    for symbol in watch:
        record = current.get(symbol)
        if not record:
            continue
        old = previous.get(symbol)
        for horizon in ("short", "long"):
            signal = record.get(horizon) or {}
            label = signal.get("label")
            if not label or label == "N/A":
                continue
            stored = sides.setdefault(symbol, {})
            announced = stored.get(horizon)
            if announced is None:
                old_label = ((old or {}).get(horizon) or {}).get("label")
                known_before = bool(old_label) and old_label != "N/A" and not first_run
                announced = stored[horizon] = side(old_label) if known_before else side(label)
            new_side = changed_side(announced, signal)
            if new_side:
                stored[horizon] = new_side
                if not first_run:
                    score = signal.get("score")
                    readings.append((format_signal_alert(record, symbol, horizon, announced, new_side, signal), {
                        "symbol": symbol, "kind": "signal", "horizon": horizon, "side": new_side, "announced": announced,
                        "name": record["name"], "label": label, "score": score if isinstance(score, int) and not isinstance(score, bool) else None,
                        "price": record.get("price"), "currency": record.get("currency") or "",
                        "levels": level_details(record, new_side, horizon) if new_side in ("buy", "sell") else None,
                        "reasons": reason_texts(signal, announced, new_side)}))
        reported_for_stock = False
        recent = [h for h in history.get(symbol, []) if clock - h.get("ts", 0) <= HISTORY_SECONDS]
        history[symbol] = recent
        for item in (record.get("news") or {}).get("fresh", []):
            key = news_key(item)
            if key in seen_set:
                continue
            seen_set.add(key)
            seen_list.append(key)
            if first_run or not news_on or reported_for_stock:
                continue
            if len(recent) >= NEWS_PER_STOCK_DAY or any(same_story(item["title"], h.get("title")) for h in recent):
                continue
            reported_for_stock = True
            age = item["age_min"]
            candidates.append(((len(recent), age is None, age or 0), (f"News, {record['name']} ({symbol}): {item['title']} ({item['source']}, {news.age_text(age)})", {
                "symbol": symbol, "kind": "news", "name": record["name"], "title": item["title"], "source": item["source"],
                "link": item.get("link") or "", "age_min": age})))
    headlines = [pair for _, pair in sorted(candidates, key=lambda c: c[0])[:NEWS_PER_RUN]]
    for _, detail in headlines:
        history.setdefault(detail["symbol"], []).append({"ts": clock, "title": detail["title"]})
    lines = []
    items = [] if items is None else items
    for text, detail in readings + headlines:
        lines.append(text)
        items.append(detail)
    return lines, seen_list[-SEEN_LIMIT:]


_OPS = {"above": ">", "below": "<", "about level with": "\u2248"}
_COMPACT = [
    (r"price (above|below|about level with) 20-day average, 20-day (above|below|about level with) 50-day", lambda m: f"P{_OPS[m[1]]}20D, 20D{_OPS[m[2]]}50D"),
    (r"Price is (above|below|about level with) the 200-day average", lambda m: f"P{_OPS[m[1]]}200D"),
    (r"50-day is (above|below|about level with) the 200-day \((bullish|bearish) alignment, no recent crossover\)", lambda m: f"50D{_OPS[m[1]]}200D ({m[2]} alignment)"),
    (r"50-day is about level with the 200-day", lambda m: "50D\u2248200D"),
    (r"50-day crossed (above|below) the 200-day (.*?) \((golden|death) cross\)", lambda m: f"50D crossed {m[1]} 200D {m[2]} ({m[3]} cross)"),
    (r"MACD positive and (rising|fading)", lambda m: f"MACD + {m[1]}"),
    (r"MACD negative and (recovering|falling)", lambda m: f"MACD \u2212 {m[1]}"),
    (r"RSI (\d+) is in the normal range", lambda m: f"RSI {m[1]} normal"),
    (r"RSI (\d+) is overbought, pullback risk", lambda m: f"RSI {m[1]} overbought"),
    (r"RSI (\d+) is oversold, bounce possible", lambda m: f"RSI {m[1]} oversold"),
    (r"Volume spike on a (rising|falling) day", lambda m: f"Vol spike, {'up' if m[1] == 'rising' else 'down'} day"),
    (r"Volume is normal", lambda m: "Vol normal"),
    (r"Volume pressure: (buying pressure|selling pressure|balanced) over 20 days", lambda m: f"Vol pressure: {m[1].split()[0]} (20D)"),
    (r"6-month return is ([+\-\u2212]?[\d.]+%)", lambda m: f"6M return {m[1]}"),
    (r"Trading at (\d+)% of its 52-week range", lambda m: f"52W range: {m[1]}%"),
    (r"Volatility (\d+)% a year", lambda m: f"Volatility {m[1]}%/yr"),
]
LEGEND = "D=day, W=week, M=month, P=price, MA=moving average, Vol=volume, \u2248 about level with"


def compact(text):
    """A shorter form of an indicator line for the Telegram cards, for example 'Trend: price above 20-day average, 20-day above 50-day'
    becomes 'Trend: P>20D, 20D>50D'. Wording that matches no rule is left as it is. The site keeps the full wording."""
    out = text or ""
    for pattern, replace in _COMPACT:
        out = re.sub(pattern, replace, out)
    return out


LOW_LIMIT = 5
IPO_LIMIT = 5
KIND_LABEL = {"mover": "Mover", "low52": "52-week low", "ipo": "IPO watch"}


def mover_alerts(events, names, seen, now_ts, limit=8, small_limit=3):
    """One alert per stock whose size of move, volume, 52-week position or IPO range was not announced today. Fairness: strongest first,
    at most `limit` movers, LOW_LIMIT 52-week lows and IPO_LIMIT IPO events per run, each kind announced once per stock per day.
    A stock at a 52-week low is its own category ("low52"); an IPO breakout or breakdown is "ipo". Returns (lines, items, seen)."""
    day = datetime.fromtimestamp(now_ts, timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")
    seen = {k: v for k, v in (seen or {}).items() if now_ts - v <= 36 * 3600}
    buckets = {"mover": [], "low52": [], "ipo": []}
    caps = {"mover": limit, "low52": LOW_LIMIT, "ipo": IPO_LIMIT}
    small_sent = 0
    for event in events:
        if event.get("small") and small_sent >= small_limit:
            continue                                   # small stocks never take more than their share of a run's alerts
        tags = event["tags"]
        if event.get("ipo"):
            parts = [("ipo", tags)]
        else:
            low = [t for t in tags if "52-week low" in t]
            rest = [t for t in tags if t not in low]
            parts = ([("low52", low)] if low else []) + ([("mover", rest)] if rest else [])
        for kind, shown in parts:
            if len(buckets[kind]) >= caps[kind]:
                continue
            if kind == "ipo":
                sub = {"ipo-up" if "breakout" in shown[0] else "ipo-down"}
            elif kind == "low52":
                sub = {"52w-low"}
            else:
                sub = {("move" if "%" in t and "volume" not in t else "volume" if "volume" in t else "52w") for t in shown}
            keys = {f"{event['symbol']}|{k}|{day}" for k in sub}
            if keys <= set(seen):
                continue
            seen.update({k: now_ts for k in keys})
            small_sent += 1 if event.get("small") and kind == "mover" else 0
            symbol = event["symbol"]
            name = names.get(symbol) or symbol
            name = re.sub(r"\s+(Limited|Ltd\.?|Inc\.?|Incorporated|Corporation|Corp\.?)$", "", name).strip() or name
            currency = "INR" if symbol.endswith(".NS") else "USD"
            label = "Small-stock mover" if event.get("small") and kind == "mover" else KIND_LABEL[kind]
            buckets[kind].append((f"{label}, {name} ({symbol}): {', '.join(shown)}; price {money_text(event['price'], currency)}",
                                  {"symbol": symbol, "kind": kind, "name": name, "tags": shown, "price": event["price"], "currency": currency,
                                   "move": event["move"], "small": bool(event.get("small")) and kind == "mover"}))
    ordered = buckets["ipo"] + buckets["mover"] + buckets["low52"]
    return [l for l, _ in ordered], [i for _, i in ordered], seen


def insert_after(lines, items, kinds, new_lines, new_items):
    """Place new alerts right after the last item whose kind is in `kinds` (or first if there is none)."""
    cut = max((i + 1 for i, item in enumerate(items) if item["kind"] in kinds), default=0)
    return lines[:cut] + new_lines + lines[cut:], items[:cut] + new_items + items[cut:]


def money_crore(value):
    """A rupee value in crore (1 crore = 10 million), for the size of a block deal."""
    return f"\u20b9{value / 1e7:,.0f} crore" if value >= 1e7 else f"\u20b9{value:,.0f}"


def deal_alerts(deals, seen_keys, names, now_ts, today_iso, limit=10):
    """One alert per block deal not announced before, for ANY NSE stock, not only the tracked ones.

    deals: parse_live output. seen_keys: keys already announced. names: {symbol with .NS: company name}. Only deals dated today
    are announced, so a feed that still shows yesterday's deals never repeats them. Returns (lines, items, updated seen keys).
    Quantity, price and value are as the NSE publishes them; nothing is judged from them."""
    from . import deals_live
    seen = list(seen_keys or [])
    seen_set = set(seen)
    fresh = []
    for deal in sorted(deals, key=lambda d: -d["value"]):
        key = deals_live.deal_key(deal)
        if key in seen_set:
            continue
        seen_set.add(key)
        seen.append(key)
        if deal["date"] == today_iso:
            fresh.append(deal)
    lines, items = [], []
    for deal in fresh[:limit]:
        symbol = deal["symbol"] + ".NS"
        name = names.get(symbol) or deal["symbol"]
        window = deals_live.WINDOWS.get(deal["session"], deal["session"] or "block window")
        move = f", {deal['pchange']:+.2f}% against the previous close" if isinstance(deal.get("pchange"), (int, float)) else ""
        lines.append(f"Block deal, {name} ({symbol}): {deal['qty']:,} shares at {money_text(deal['price'], 'INR')} ({money_crore(deal['value'])}), {window}{move}")
        items.append({"symbol": symbol, "kind": "deal", "name": name, "qty": deal["qty"], "price": deal["price"], "value": deal["value"], "window": window,
                      "time": deal.get("time"), "pchange": deal.get("pchange"), "previous_close": deal.get("previous_close"), "official_url": deals_live.PAGE_URL})
    return lines, items, seen[-deals_live.SEEN_LIMIT:]


def merge_deals(lines, items, deal_lines, deal_items):
    """Readings first, then block deals, then movers, then headlines (the order the digest lays them out in)."""
    return insert_after(lines, items, ("signal",), deal_lines, deal_items)


ADVISORY = "Educational information only, not investment advice. We are not a SEBI-registered adviser or research analyst."


def anchor(url, label):
    """A Telegram HTML link: a short clickable label instead of a long address."""
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>'


_ANCHOR = re.compile(r'<a href="([^"]*)">(.*?)</a>', re.S)
_TAG = re.compile(r"<[^>]+>")


def to_plain(text):
    """A Telegram HTML message as plain text: links become "label: address" and the tags are removed."""
    text = re.sub(r"</?b>", "", text)
    text = _ANCHOR.sub(lambda m: f"{html.unescape(m.group(2))}: {html.unescape(m.group(1))}", text)
    return html.unescape(text).replace("​", "")


def visible_length(text):
    """How long a Telegram HTML message looks once the tags and hidden addresses are gone. Telegram's limit counts this."""
    return len(html.unescape(_TAG.sub("", text)))


def post_telegram(token, chat_id, text, reply_to=None, markup=False):
    """Send a message. Returns (ok, message_id). message_id is None if Telegram did not report one.

    markup=True sends it as Telegram HTML (the caller has escaped everything). reply_to threads the message under an
    earlier one.

    reply_to threads the message under an earlier one. If that message no longer exists the new one is still sent.
    Never prints the token or the request URL.
    """
    payload = {"chat_id": chat_id, "text": text if markup else text[:TELEGRAM_MAX_CHARS], "disable_web_page_preview": True}
    if markup:
        payload["parse_mode"] = "HTML"
    if reply_to:
        payload.update({"reply_to_message_id": reply_to, "allow_sending_without_reply": True})
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 200:
                return False, None
            try:
                message_id = json.loads(response.read())["result"]["message_id"]
            except (AttributeError, ValueError, KeyError, TypeError):
                return True, None
            return True, message_id if isinstance(message_id, int) and not isinstance(message_id, bool) else None
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False, None


def send_telegram(token, chat_id, text):
    """Returns True on success."""
    return post_telegram(token, chat_id, text)[0]


def outcome_figures(price, exit_price, move, days):
    """The numbers of a target or stop reply as two short bullets (a table wraps on a small phone)."""
    fmt = lambda v: f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.1f}"
    return [f"• Alerted at {fmt(price)} · Now {fmt(exit_price)}", f"• Move {move:+.1f}% in {days} trading day{'s' if days != 1 else ''}"]


def format_outcome(call, outcome, link=None, markup=False):
    """The reply sent when a reading's price reaches its reference level or its volatility risk level.

    markup=True gives Telegram HTML with the link as a short label. The default is plain text."""
    name = call.get("name") or call["symbol"]
    hit_target = outcome["outcome"] == "target"
    currency = call.get("currency") or ""
    price, exit_price = call["price"], outcome["exit_price"]
    move = (exit_price / price - 1) * 100
    verb = "rose" if exit_price >= price else "fell"
    side_word = SIDE_TEXT.get(call["side"], call["side"])
    days = outcome["days_held"]
    esc = html.escape if markup else str
    head = f"{'✅ Reference level reached' if hit_target else '⚠️ Volatility risk level reached'}: {esc(name)} ({esc(call['symbol'])})"
    figures = outcome_figures(price, exit_price, move, days)
    lines = [f"<b>{head}</b>" if markup else head,
             f"• {HORIZON_TEXT[call['horizon']]} · {side_word.capitalize()} reading",
             *figures,
             f"Price {verb} on {esc(outcome['resolved_date'])}, {days} trading day{'s' if days != 1 else ''} after the alert. Prices in {'rupees' if currency == 'INR' else currency or 'the stock currency'}"]
    if link:
        lines.append("• " + (anchor(link, "Open analysis") if markup else f"Open analysis: {link}"))
    lines.append("ℹ️ " + esc(ADVISORY))
    return chr(10).join(lines)


_NEWS_LINE = re.compile(r"^((?:Positive |Negative )?)[Nn]ews, .*? \(([^()]+)\): (.*) \((.*), [^,()]*\)$", re.S)


def drop_irrelevant(log, records):
    """Clean the logged alerts: remove news that is not clearly about its stock, and old "Positive news" or
    "Negative news" entries, whose tone was guessed from words and is no longer shown.

    records: {symbol: record}. Entries that are not news alerts, or whose stock is unknown, are kept."""
    kept = []
    for entry in log:
        text = entry.get("text") if isinstance(entry, dict) else None
        match = _NEWS_LINE.match(text) if isinstance(text, str) else None
        if match and match.group(1):
            continue
        record = records.get(match.group(2)) if match else None
        if record and not news.is_relevant(match.group(3), record["name"], match.group(2).split(".")[0], match.group(4)):
            continue
        kept.append(entry)
    return kept


def update_log(log, lines, now_ts, symbols=None):
    """Keep a short history of alerts for the page. symbols, if given, has one stock symbol per line so the page
    can open that stock. Returns (log, entries added now)."""
    day = datetime.fromtimestamp(now_ts, timezone.utc).strftime("%Y-%m-%d")
    kept = [e for e in log if isinstance(e, dict) and now_ts - e.get("ts", 0) <= LOG_MAX_AGE]
    known = {e["id"] for e in kept}
    added = []
    for index, text in enumerate(lines):
        entry = {"id": hashlib.sha1((day + text).encode("utf-8")).hexdigest()[:12], "ts": now_ts, "text": text}
        if symbols and index < len(symbols) and symbols[index]:
            entry["symbol"] = symbols[index]
        if entry["id"] not in known:
            known.add(entry["id"])
            kept.append(entry)
            added.append(entry)
    return kept[-LOG_LIMIT:], added

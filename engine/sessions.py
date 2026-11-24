"""Index alerts and the pre-open, post-close and institutional-flow briefs.

Everything here is a plain statement of what the exchange published: an index's move, the pre-open indicative prices, the day's
biggest movers, foreign and domestic institutional net flows, deals. No reading, forecast or tone is added. Each source is one request
per run for the whole market (never one per stock), uses an honest client name, and is left alone for BLOCK_BACKOFF_HOURS after a
refusal. A brief is sent once per session, and only inside its time window.
"""
import json
from datetime import datetime, timedelta, timezone

from . import backoff
from .fetch import FetchError, http_get

IST = timezone(timedelta(hours=5, minutes=30))
ALL_INDICES = "https://www.nseindia.com/api/allIndices"
PREOPEN = "https://www.nseindia.com/api/market-data-pre-open?key=ALL"
FII_DII = "https://www.nseindia.com/api/fiidiiTradeReact"
LARGE_DEALS = "https://www.nseindia.com/api/snapshot-capital-market-largedeal"
BLOCK_BACKOFF_HOURS = 6
WATCH_IN = ["NIFTY 50", "NIFTY NEXT 50", "NIFTY BANK", "NIFTY IT", "NIFTY AUTO", "NIFTY FMCG", "NIFTY PHARMA", "NIFTY METAL", "NIFTY ENERGY",
            "NIFTY REALTY", "NIFTY FIN SERVICE", "NIFTY MIDCAP 100", "NIFTY SMLCAP 100", "NIFTY 500", "INDIA VIX"]
MOVE_TIERS = (1.0, 2.0, 3.0)
VIX_TIERS = {"INDIA VIX": (20.0, 25.0), "^VIX": (20.0, 30.0)}
NEAR_EXTREME = 0.999
# window id: (market, first minute, last minute of the IST day, weekdays allowed 0=Mon)
WINDOWS = {"in_preopen": ("IN", 9 * 60 + 8, 9 * 60 + 40, (0, 1, 2, 3, 4)),
           "in_postclose": ("IN", 16 * 60, 19 * 60 + 30, (0, 1, 2, 3, 4)),
           "in_flows": ("IN", 18 * 60 + 30, 22 * 60, (0, 1, 2, 3, 4))}


class Source:
    """One NSE endpoint with the shared refusal handling."""

    def __init__(self, name, url, text=False):
        self.name, self.url, self.text = name, url, text      # text: the answer is plain text (a CSV file), not JSON

    def fetch(self, now, state, log=print, getter=http_get):
        """(payload or None, state to keep). Never raises."""
        state = dict(state or {})
        held = state.get("blocked_until")
        try:
            held_until = datetime.fromisoformat(held) if held else None
        except (TypeError, ValueError):
            held_until = None
        if backoff.still_paused(now, held_until, state.get("failures")):
            log(f"{self.name}: skipped, refused earlier; next attempt after {held}")
            return None, state
        try:
            body = getter(self.url, headers={"Accept": "application/json"}, retries=2)
            payload = body.decode("utf-8", "replace") if self.text and isinstance(body, bytes) else body if self.text else json.loads(body)
        except (FetchError, ValueError) as err:
            text = str(err)
            refused = "403" in text or "401" in text
            state["error"] = "HTTP 403: the NSE refuses automated requests" if refused else (text[:120] or "request failed")
            if refused:
                state["blocked_until"], state["failures"] = backoff.refusal_state(now, state)
            log(f"{self.name} failed: {state['error']}")
            return None, state
        return payload, {"ok": True, "fetched_at": now.isoformat(timespec="seconds"), "error": None, "blocked_until": None, "failures": 0}


def _num(value):
    try:
        return float(str(value).replace(",", "")) if value not in (None, "", "-") else None
    except ValueError:
        return None


def parse_indices(payload):
    """{index name: {"last", "pct", "high52", "low52", "advances", "declines"}} from the NSE's all-indices answer."""
    out = {}
    for row in (payload or {}).get("data", []) if isinstance(payload, dict) else []:
        if isinstance(row, dict) and row.get("index") and _num(row.get("last")) is not None:
            out[row["index"]] = {"last": _num(row["last"]), "pct": _num(row.get("percentChange")), "high52": _num(row.get("yearHigh")), "low52": _num(row.get("yearLow")),
                                 "advances": _num(row.get("advances")), "declines": _num(row.get("declines"))}
    return out


INDIAN_PREFIXES = ("^NSE", "^BSE", "^CNX", "^INDIA", "^NIFTY")


def index_events(indices, global_watch, india_open=False):
    """Factual events: a move past 1, 2 or 3 percent, a 52-week high or low, a volatility index past a level.

    indices: parse_indices output (India), used only while the Indian market is open: outside the session the figures repeat the last
    close, which the post-close brief already reports. global_watch: the app's own market watch, [{"symbol", "name", "price", "change_pct",
    "as_of"}], minus the Indian indexes the NSE feed already covers. A global index's event is keyed by its own session date."""
    rows = [(name, v["last"], v["pct"], v.get("high52"), v.get("low52"), None) for name, v in indices.items() if name in WATCH_IN] if india_open else []
    rows += [(w["name"], w["price"], w.get("change_pct"), None, None, w.get("as_of")) for w in global_watch or []
             if isinstance(w.get("price"), (int, float)) and not str(w.get("symbol", "")).startswith(INDIAN_PREFIXES)]
    symbol_of = {w["name"]: w["symbol"] for w in global_watch or []}
    events = []
    for name, last, pct, high, low, session in rows:
        tags = []
        vix = VIX_TIERS.get(name) or VIX_TIERS.get(symbol_of.get(name, ""))
        if vix:
            crossed = [level for level in vix if last >= level]
            if crossed:
                tags.append(("level", f"above {max(crossed):g}"))
        elif pct is not None:
            for tier in MOVE_TIERS:
                if abs(pct) >= tier:
                    tags.append((f"move{tier:g}", f"{pct:+.1f}%"))
        if high and last >= high * NEAR_EXTREME:
            tags.append(("high52", "at 52-week high"))
        elif low and last <= low / NEAR_EXTREME:
            tags.append(("low52", "at 52-week low"))
        if tags:
            events.append({"name": name, "last": last, "pct": pct, "tags": tags, "session": session})
    return events


def index_alerts(events, seen, now_ts):
    """One alert per index per kind of event per day; a move that grows from 1% to 2% is announced again at 2%. Returns (lines, items, seen)."""
    today = datetime.fromtimestamp(now_ts, IST).strftime("%Y-%m-%d")
    seen = {k: v for k, v in (seen or {}).items() if now_ts - v <= 72 * 3600}
    lines, items = [], []
    for event in events:
        day = event.get("session") or today
        fresh = [(kind, text) for kind, text in event["tags"] if f"{event['name']}|{kind}|{day}" not in seen]
        if not fresh:
            continue
        top = [f for f in fresh if f[0].startswith("move")][-1:] + [f for f in fresh if not f[0].startswith("move")]
        for kind, _ in fresh:
            seen[f"{event['name']}|{kind}|{day}"] = now_ts
        shown = [text for _, text in top]
        lines.append(f"Index, {event['name']}: {', '.join(shown)}; level {event['last']:,.2f}")
        items.append({"kind": "index", "symbol": "", "name": event["name"], "tags": shown, "last": event["last"],
                      "urgent": any(kind in ("level", "move2", "move3") for kind, _ in fresh)})
    return lines, items, seen


def due_windows(now, sent, markets=("IN",)):
    """The brief ids whose time window is open now and that have not been sent today (IST date)."""
    local = now.astimezone(IST)
    minute, day, weekday = local.hour * 60 + local.minute, local.strftime("%Y-%m-%d"), local.weekday()
    return [w for w, (market, start, end, days) in WINDOWS.items() if market in markets and weekday in days and start <= minute <= end and (sent or {}).get(w) != day]


def parse_preopen(payload, min_turnover=1e7, limit=5):
    """(gainers, losers, advances, declines): the biggest indicative moves among equity-series stocks with at least Rs 1 crore matched."""
    rows = []
    for row in (payload or {}).get("data", []) if isinstance(payload, dict) else []:
        m = (row or {}).get("metadata") or {}
        pct, price, turnover = _num(m.get("pChange")), _num(m.get("lastPrice")), _num(m.get("totalTurnover"))
        if m.get("series") in (None, "EQ") and m.get("symbol") and pct is not None and price and (turnover or 0) >= min_turnover:
            rows.append((m["symbol"] + ".NS", pct, price))
    rows.sort(key=lambda r: -r[1])
    return rows[:limit], sorted(rows, key=lambda r: r[1])[:limit], (payload or {}).get("advances"), (payload or {}).get("declines")


def parse_flows(payload):
    """{"FII/FPI": net crore, "DII": net crore, "date"} from the NSE's institutional trade answer, or {}."""
    out = {}
    for row in payload if isinstance(payload, list) else []:
        if isinstance(row, dict) and row.get("category") and _num(row.get("netValue")) is not None:
            out[row["category"]] = _num(row["netValue"])
            out["date"] = row.get("date")
    return out


def parse_deals(payload, today_label, limit=5):
    """The day's largest bulk and block deals with their clients: [(kind, name, side, qty, price, client)]."""
    rows = []
    for key, kind in (("BULK_DEALS_DATA", "bulk"), ("BLOCK_DEALS_DATA", "block")):
        for r in (payload or {}).get(key, []) if isinstance(payload, dict) else []:
            qty, price = _num(r.get("qty")), _num(r.get("watp"))
            if isinstance(r, dict) and r.get("date") == today_label and qty and price:
                rows.append((kind, r.get("symbol"), r.get("buySell"), qty, price, (r.get("clientName") or "").title()))
    rows.sort(key=lambda r: -(r[3] * r[4]))
    return rows[:limit]


def _crore(value):
    return f"{value:,.0f} cr"


def _stock_list(rows):
    return ", ".join(f"{s.replace('.NS', '')} {p:+.1f}%" for s, p, *_ in rows)


def preopen_brief(pre, cues, flows, events_today, watch=()):
    """Lines for the India pre-open brief. pre: parse_preopen output or None. cues: [(name, pct)]. flows: parse_flows or {}.
    watch: recently listed stocks with their listing-day range, the levels an IPO breakout or breakdown is measured from."""
    lines = []
    if pre and (pre[0] or pre[1]):
        up, down, adv, dec = pre
        lines.append(f"Pre-open indicative: up {_stock_list(up)}")
        lines.append(f"Pre-open indicative: down {_stock_list(down)}")
        if adv is not None and dec is not None:
            lines.append(f"Pre-open breadth: {adv} up, {dec} down")
    else:
        lines.append("Pre-open data not available this run")
    if cues:
        dates = sorted({c[2] for c in cues if len(c) > 2 and c[2]})
        when = ""
        if dates:
            try:
                when = f" (last close, {datetime.strptime(dates[-1], '%Y-%m-%d').strftime('%d %b').lstrip('0')}, against the close before)"
            except ValueError:
                pass
        lines.append(f"Overnight{when}: " + ", ".join(f"{c[0]} {c[1]:+.1f}%" for c in cues))
    if flows.get("date"):
        lines.append(f"Previous day net flows ({flows['date']}): FII/FPI {flows.get('FII/FPI', 0):+,.0f} cr, DII {flows.get('DII', 0):+,.0f} cr")
    if events_today:
        lines.append("Today: " + "; ".join(events_today[:6]))
    if watch:
        lines.append("Stock watch (recent listings, last close vs listing-day range): " + "; ".join(list(watch)[:8]))
    return lines


def postclose_brief(indices, movers_up, movers_down, extremes, flows, today_label, deals, events_today):
    """Lines for the India post-close brief."""
    lines = []
    shown = [f"{n.replace('NIFTY ', 'N')} {indices[n]['pct']:+.1f}%" for n in ("NIFTY 50", "NIFTY BANK", "NIFTY IT", "NIFTY MIDCAP 100", "NIFTY SMLCAP 100") if n in indices and indices[n]["pct"] is not None]
    if shown:
        lines.append("Closes: " + ", ".join(shown))
    nifty = indices.get("NIFTY 500") or indices.get("NIFTY 50")
    if nifty and nifty.get("advances") is not None:
        lines.append(f"Breadth: {nifty['advances']:.0f} advancing, {nifty['declines']:.0f} declining")
    if "INDIA VIX" in indices:
        lines.append(f"India VIX {indices['INDIA VIX']['last']:.1f} ({indices['INDIA VIX']['pct']:+.1f}%)" if indices["INDIA VIX"]["pct"] is not None else f"India VIX {indices['INDIA VIX']['last']:.1f}")
    if movers_up:
        lines.append("Top gainers: " + _stock_list(movers_up))
    if movers_down:
        lines.append("Top losers: " + _stock_list(movers_down))
    if extremes:
        lines.append(f"At 52-week high: {extremes[0]}, at 52-week low: {extremes[1]}")
    if flows.get("date") == today_label:
        lines.append(f"Net flows today: FII/FPI {flows.get('FII/FPI', 0):+,.0f} cr, DII {flows.get('DII', 0):+,.0f} cr")
    for kind, symbol, side, qty, price, client in deals:
        lines.append(f"{kind.capitalize()} deal: {client or 'client n/a'} {('bought' if side == 'BUY' else 'sold') if side else ''} {qty:,.0f} {symbol} at ₹{price:,.2f}".replace("  ", " "))
    if events_today:
        lines.append("Declared/announced today: " + "; ".join(events_today[:6]))
    return lines


TITLES = {"in_preopen": "India pre-open brief", "in_postclose": "India post-close brief", "in_flows": "India institutional flows"}


def brief_item(window, lines, now_ts):
    return {"kind": "brief", "symbol": "", "name": TITLES[window], "window": window, "lines": lines, "ts": now_ts}

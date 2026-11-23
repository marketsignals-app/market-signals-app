"""Corporate actions, circuits, surveillance and the other market events behind the Announcements tab and their Telegram alerts.

Every function here turns published data into plain records and does no network access. A record:

    {"id", "type", "label", "group", "symbol", "name", "title", "detail", "date", "ts", "source", "link"}

`type` is one of TYPES; `date` is the date the event takes effect or happened (ISO), `ts` is when the app saw it. Sources:
  * NSE corporate announcements: the exchange's own category (`desc`) decides the type; for BSE and for generic categories a precise phrase in the title does.
  * NSE corporate-actions list: bonus, split, buyback, rights, merger, demerger and scheme entries with their ex and record dates.
  * NSE price-band hitters: a stock is at its circuit when its price is within a rounding tolerance of the band limit worked out from the previous close.
  * NSE ASM and GSM surveillance lists and the F&O ban file: reported as changes against the previous run.
  * Yahoo quotes: a gap at the open, a surge or a crash.
The type of an announcement is rule-based (category, then phrases), so an unusual wording can be missed.
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

TYPES = {
    "merger": ("Merger", "Mergers and schemes"), "demerger": ("Demerger", "Mergers and schemes"), "scheme": ("Scheme of arrangement", "Mergers and schemes"),
    "open_offer": ("Open offer", "Mergers and schemes"),
    "bonus": ("Bonus issue", "Share actions"), "split": ("Stock split", "Share actions"), "buyback": ("Buyback", "Share actions"), "rights": ("Rights issue", "Share actions"),
    "record_date": ("Record date", "Share actions"),
    "suspension": ("Trading suspension", "Trading restrictions"), "delisting": ("Delisting", "Trading restrictions"), "fo_ban": ("F&O ban", "Trading restrictions"),
    "asm": ("ASM list", "Trading restrictions"), "gsm": ("GSM list", "Trading restrictions"),
    "upper_circuit": ("Upper circuit", "Circuits"), "lower_circuit": ("Lower circuit", "Circuits"),
    "gap_up": ("Gap up at open", "Price moves"), "gap_down": ("Gap down at open", "Price moves"), "surge": ("Surge", "Price moves"), "crash": ("Crash", "Price moves"),
}
DESC_TYPES = {
    "Amalgamation/Merger": "merger", "Demerger": "demerger", "Scheme of Arrangement": "scheme", "Open Offer": "open_offer", "Public Announcement-Open Offer": "open_offer",
    "Stock split": "split", "Bonus": "bonus", "Buyback": "buyback", "Public Announcement - Buyback of Shares": "buyback", "Post Buyback Public Announcement": "buyback",
    "Closure of Buy Back": "buyback", "Rights Issue": "rights", "Record Date": "record_date", "Suspension of Trading": "suspension",
}
PHRASES = [
    ("demerger", re.compile(r"\bde-?merger\b", re.I)), ("merger", re.compile(r"\b(?:merger|amalgamation)\b", re.I)),
    ("scheme", re.compile(r"\bscheme of (?:arrangement|amalgamation)\b", re.I)), ("delisting", re.compile(r"\bdelist(?:ing|ed)?\b", re.I)),
    ("suspension", re.compile(r"\b(?:suspension of trading|trading halt)\b", re.I)), ("split", re.compile(r"\b(?:stock|share) split\b|\bsub-?division of (?:equity )?shares\b", re.I)),
    ("bonus", re.compile(r"\bbonus (?:issue|shares?)\b", re.I)), ("buyback", re.compile(r"\bbuy[- ]?back\b", re.I)), ("rights", re.compile(r"\brights issue\b", re.I)),
    ("open_offer", re.compile(r"\bopen offer\b", re.I)),
]
GENERIC = {"", "General Updates", "Updates", "Outcome of Board Meeting", "Press Release", "Disclosure under SEBI Takeover Regulations", "Announcement"}
SUBJECT_TYPES = [("demerger", re.compile(r"de-?merger", re.I)), ("merger", re.compile(r"merger|amalgamation", re.I)), ("scheme", re.compile(r"scheme of arrangement", re.I)),
                 ("bonus", re.compile(r"\bbonus\b", re.I)), ("split", re.compile(r"split|sub-?division", re.I)), ("buyback", re.compile(r"buy[- ]?back", re.I)),
                 ("rights", re.compile(r"\brights\b", re.I))]
UPCOMING_TYPES = ("bonus", "split", "buyback", "rights", "demerger", "merger", "scheme")


def label_of(kind):
    return TYPES[kind][0]


def group_of(kind):
    return TYPES[kind][1]


def make_id(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _record(kind, symbol, name, title, detail, date, ts, source, link):
    return {"id": make_id(kind, symbol, title, date), "type": kind, "label": label_of(kind), "group": group_of(kind), "symbol": symbol, "name": name or (symbol or "").replace(".NS", ""),
            "title": title, "detail": detail, "date": date, "ts": int(ts), "source": source, "link": link or ""}


def _iso(day):
    """23-Nov-2026 to 2026-11-23, else None."""
    try:
        return datetime.strptime(str(day).strip(), "%d-%b-%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _num(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ---------- announcements ----------
def classify_announcement(desc, text):
    """The type of an NSE or BSE announcement, or None. The exchange's category decides when it names one; otherwise a precise phrase in a generic category."""
    kind = DESC_TYPES.get(desc or "")
    if kind:
        return kind
    if (desc or "") in GENERIC:
        for name, pattern in PHRASES:
            if pattern.search(text or ""):
                return name
    return None


def announcement_records(items, now_ts, max_age_hours=96):
    """Records for the official announcements (kind "nse" or "bse" items from engine/news_sources) that are mergers, demergers, schemes, share actions, suspensions or delistings."""
    out, seen = [], set()
    for item in items or []:
        if item.get("kind") not in ("nse", "bse") or not item.get("symbol"):
            continue
        ts = item.get("ts") or now_ts
        if now_ts - ts > max_age_hours * 3600:
            continue
        text = " ".join(str(x) for x in (item.get("title"), item.get("text")) if x)
        kind = classify_announcement(item.get("desc"), text)
        if not kind:
            continue
        date = datetime.fromtimestamp(ts, IST).strftime("%Y-%m-%d")
        record = _record(kind, item["symbol"], item.get("name"), (item.get("text") or item.get("title") or "")[:240], None, date, ts,
                         "NSE announcement (official)" if item["kind"] == "nse" else "BSE announcement (official)", item.get("link"))
        record["id"] = make_id(kind, item["symbol"], record["title"][:80], date)
        if record["id"] not in seen:
            seen.add(record["id"])
            out.append(record)
    return out


# ---------- corporate actions list ----------
def corporate_action_records(payload, now_ts):
    """Records from the NSE corporate-actions list: bonus, split, buyback, rights, merger, demerger and scheme entries with their ex and record dates. Dividends are not here (Events tab)."""
    out = []
    for row in payload if isinstance(payload, list) else []:
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        subject = str(row.get("subject") or "")
        kind = next((name for name, pattern in SUBJECT_TYPES if pattern.search(subject)), None)
        if not kind:
            continue
        ex, record_date = _iso(row.get("exDate")), _iso(row.get("recDate"))
        dates = [f"Ex-date {ex}" if ex else None, f"Record date {record_date}" if record_date else None]
        rec = _record(kind, str(row["symbol"]).strip() + ".NS", row.get("comp"), subject[:240], ", ".join(d for d in dates if d) or None, ex or record_date, now_ts,
                      "NSE corporate actions (official)", "")
        rec["ex_date"], rec["record_date"] = ex, record_date
        out.append(rec)
    return out


def upcoming_dates(records, today, days=7):
    """Share actions with an ex or record date from today to `days` ahead, soonest first."""
    end = today + timedelta(days=days)
    rows = []
    for r in records or []:
        if r.get("type") not in UPCOMING_TYPES:
            continue
        for key in ("ex_date", "record_date"):
            try:
                when = datetime.strptime(r.get(key) or "", "%Y-%m-%d").date()
            except ValueError:
                continue
            if today <= when <= end:
                rows.append((when, key, r))
    rows.sort(key=lambda x: (x[0], x[2]["symbol"] or ""))
    return rows


# ---------- circuits ----------
def circuit_records(upper, lower, now_ts, today_iso, min_band=5.0, min_turnover=1e7, tick=0.05):
    """Records for stocks at their upper or lower circuit, from the NSE price-band hitter lists.

    The lists hold stocks near their band, not only at it, so the limit is worked out from the previous close (price minus change) and the band, and a stock counts when its
    price is within a rounding tolerance of it. Bands under `min_band` percent and stocks trading less than `min_turnover` rupees today are left out (2% bands are mostly
    illiquid or surveillance stocks). A stock is one record per day and direction."""
    out = []
    for payload, direction in ((upper, "upper"), (lower, "lower")):
        rows = ((payload or {}).get("AllSec") or {}).get("data") if isinstance(payload, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            ltp, change, band, turnover = _num(row.get("ltp")), _num(row.get("change")), _num(row.get("priceBand")), _num(row.get("turnovercsv"))
            if None in (ltp, change, band) or ltp <= 0 or band < min_band or (turnover or 0) < min_turnover:
                continue
            previous = ltp - change
            if previous <= 0:
                continue
            limit = previous * (1 + band / 100) if direction == "upper" else previous * (1 - band / 100)
            if abs(ltp - limit) > max(tick * 2, 0.0002 * ltp) or (direction == "upper") != (change > 0):
                continue
            symbol = str(row.get("symbol") or "").strip()
            if not symbol:
                continue
            kind = f"{direction}_circuit"
            rec = _record(kind, symbol + ".NS", symbol, f"At the {direction} circuit ({band:g}% band)", f"Price {ltp:,.2f}, {change / previous * 100:+.1f}% on the day, turnover {turnover / 1e7:,.1f} crore",
                          today_iso, now_ts, "NSE price-band feed", "")
            rec["id"] = make_id(kind, symbol, today_iso)
            rec.update({"price": ltp, "move_pct": round(change / previous * 100, 2), "band": band, "turnover": turnover, "series": row.get("series")})
            out.append(rec)
    out.sort(key=lambda r: -r["turnover"])
    return out


# ---------- surveillance and F&O ban ----------
def _surv_rows(asm, gsm):
    """{(list, symbol, stage): (name, description)} from the NSE ASM (long and short term) and GSM lists."""
    out = {}
    for term in ("longterm", "shortterm"):
        for row in ((asm or {}).get(term) or {}).get("data", []) if isinstance(asm, dict) else []:
            if isinstance(row, dict) and row.get("symbol"):
                out[("asm", row["symbol"], f"{'Long' if term == 'longterm' else 'Short'}-term {row.get('asmSurvIndicator') or ''}".strip())] = (row.get("companyName"), row.get("survDesc"))
    for row in gsm if isinstance(gsm, list) else []:
        if isinstance(row, dict) and row.get("symbol"):
            out[("gsm", row["symbol"], f"Stage {row.get('gsmStage') or ''}".strip())] = (row.get("companyName"), row.get("survDesc"))
    return out


def surveillance_records(asm, gsm, previous, now_ts, today_iso):
    """(records, state): additions to and removals from the ASM and GSM lists since `previous` (the state returned last time). The first call only records the lists."""
    now_rows = _surv_rows(asm, gsm)
    if not now_rows and not (isinstance(asm, dict) or isinstance(gsm, list)):
        return [], previous
    keys = sorted("|".join(k) for k in now_rows)
    if not isinstance(previous, list):
        return [], keys
    old = set(previous)
    out = []
    for key, (name, description) in now_rows.items():
        joined = "|".join(key)
        if joined in old:
            continue
        kind, symbol, stage = key
        rec = _record(kind, symbol + ".NS", name, f"Added to the {label_of(kind)}: {stage}", description, today_iso, now_ts, f"NSE {kind.upper()} list (official)", "")
        rec["id"] = make_id(kind, symbol, stage, today_iso, "added")
        out.append(rec)
    for joined in sorted(old - set(keys)):
        kind, symbol, stage = (joined.split("|") + ["", ""])[:3]
        if kind not in ("asm", "gsm"):
            continue
        rec = _record(kind, symbol + ".NS", symbol, f"Removed from the {label_of(kind)}: {stage}", None, today_iso, now_ts, f"NSE {kind.upper()} list (official)", "")
        rec["id"] = make_id(kind, symbol, stage, today_iso, "removed")
        out.append(rec)
    return out, keys


def fo_ban_records(text, previous, now_ts, today_iso):
    """(records, state) for the F&O ban file ("Securities in Ban For Trade Date ...:" then "1,SYMBOL" lines): who entered or left the ban since the last run."""
    if not text or "Ban" not in text:
        return [], previous
    symbols = sorted({line.split(",")[1].strip() for line in text.splitlines() if "," in line and line.split(",")[0].strip().isdigit() and len(line.split(",")) > 1})
    if not isinstance(previous, list):
        return [], symbols
    out = []
    for symbol, verb in [(s, "entered") for s in symbols if s not in previous] + [(s, "left") for s in previous if s not in symbols]:
        rec = _record("fo_ban", symbol + ".NS", symbol, f"{symbol} {verb} the F&O ban period", "Fresh positions are not allowed in the F&O contracts of a stock in its ban period" if verb == "entered" else None,
                      today_iso, now_ts, "NSE F&O ban list (official)", "")
        rec["id"] = make_id("fo_ban", symbol, verb, today_iso)
        out.append(rec)
    return out, symbols


# ---------- price moves from quotes ----------
def gap_records(quotes, market_of, now_ts, today_iso, min_gap=3.0, thresholds=None):
    """Records for stocks that opened at least `min_gap` percent away from the previous close. Main-list liquidity floors only (the same as the mover alerts)."""
    t = thresholds or {"min_price": 10.0, "min_avg_volume": 50_000, "min_cap": 5e9}
    out = []
    for symbol, q in (quotes or {}).items():
        if market_of.get(symbol) != "IN" or q.get("state") not in (None, "REGULAR"):
            continue
        opening, previous, price, avg, cap = q.get("open"), q.get("prev_close"), q.get("price"), q.get("avg_volume"), q.get("cap") or 0
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in (opening, previous, price)) or not avg or avg < t["min_avg_volume"] or price < t["min_price"] or cap < t["min_cap"]:
            continue
        gap = (opening / previous - 1) * 100
        if abs(gap) < min_gap:
            continue
        kind = "gap_up" if gap > 0 else "gap_down"
        rec = _record(kind, symbol, symbol.replace(".NS", ""), f"Opened {gap:+.1f}% from the previous close", f"Open {opening:,.2f}, previous close {previous:,.2f}, now {price:,.2f}", today_iso, now_ts,
                      "Yahoo Finance quote (delayed)", "")
        rec["id"] = make_id(kind, symbol, today_iso)
        rec.update({"price": price, "move_pct": round(gap, 2), "open": opening, "prev_close": previous})
        out.append(rec)
    out.sort(key=lambda r: -abs(r["move_pct"]))
    return out


def surge_crash_records(events, names, now_ts, today_iso, threshold=10.0):
    """Records for movers (engine/wide.mover_events) that rose or fell at least `threshold` percent today: a surge or a crash."""
    out = []
    for e in events or []:
        move = e.get("move")
        if not isinstance(move, (int, float)) or abs(move) < threshold:
            continue
        kind = "surge" if move > 0 else "crash"
        symbol = e["symbol"]
        rec = _record(kind, symbol, (names or {}).get(symbol), f"{move:+.1f}% today", "; ".join(e.get("tags") or []) or None, today_iso, now_ts, "Yahoo Finance quote (delayed)", "")
        rec["id"] = make_id(kind, symbol, today_iso)
        rec.update({"price": e.get("price"), "move_pct": move, "small": bool(e.get("small"))})
        out.append(rec)
    return out


# ---------- archive for the website ----------
def merge_archive(old, new, now_ts, days=7, cap=800):
    """The archive with new records added (an id seen before keeps its first ts and gains any new fields), records older than `days` days dropped, newest first, at most `cap`."""
    by_id = {r["id"]: r for r in old or [] if isinstance(r, dict) and r.get("id")}
    for r in new or []:
        if r["id"] in by_id:
            by_id[r["id"]] = {**r, **{"ts": by_id[r["id"]]["ts"]}}
        else:
            by_id[r["id"]] = r
    cutoff = now_ts - days * 86400
    kept = [r for r in by_id.values() if r.get("ts", 0) >= cutoff]
    kept.sort(key=lambda r: (-r.get("ts", 0), r["id"]))
    return kept[:cap]


def counts(records):
    out = {}
    for r in records:
        out[r["type"]] = out.get(r["type"], 0) + 1
    return out

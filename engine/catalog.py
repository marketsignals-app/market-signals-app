"""Every listed stock in the table, with its analysis loaded only when it is opened.

The curated list (config/universe.json) is in data.json with full records. Every other NSE and S&P 500 stock is covered here:

  * index.json: one small row per stock for the dashboard table (price, move, volume, size, 52-week range, and the two readings once the
    stock has been analysed). It comes from the bulk quotes of the run, so it is as fresh as the run and costs no extra requests.
  * detail/NN.json: the full analysis record of each stock, in 64 shards by a fixed hash of the symbol. The page fetches one shard only when a
    stock is opened. A run analyses PER_RUN stocks (never analysed first, most traded first, then the stalest), so the whole list is
    covered within hours and each stock is refreshed about once a day, which is how often completed daily candles change.
    The previous shards are read back from the published site, because every publish replaces the whole site.

A stock whose history is too short to analyse is retried after RETRY_HOURS; until then its row shows the quote only.
"""
import json
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

from . import dividends, evidence, fundamentals, provenance, ratios, statements

SHARDS = 64
PER_RUN = 60
REFRESH_HOURS = 20
RETRY_HOURS = 72
WORKERS = 6


class _NoNews:
    """A news breaker that is always open: stocks analysed here skip the per-stock headline request (the wide headline lookup covers them)."""
    open = True

    def succeeded(self):
        pass

    def failed(self):
        pass


def news_summary(intel):
    """The few news-intelligence fields the table, screens and filters need; the stories themselves are in the stock's detail shard."""
    if not intel:
        return None
    latest = (intel.get("latest") or [{}])[0]
    return {"label": intel.get("label"), "interpretation": intel.get("interpretation"), "sentiment": intel.get("sentiment"), "impact": intel.get("impact"),
            "credibility": intel.get("credibility"), "n": intel.get("n"), "fundamental": {"level": (intel.get("fundamental") or {}).get("level"), "direction": (intel.get("fundamental") or {}).get("direction")},
            "validation": (intel.get("validation") or {}).get("state"), "reaction": (intel.get("reaction") or {}).get("state"),
            "top": {k: latest.get(k) for k in ("title", "source", "link", "ts", "event_label", "kind")} if latest else None}


def lite(record):
    """The part of a curated stock's record that the dashboard needs (table, screens, peers, alerts), without what only its own page shows:
    the older headlines, the provisional reading, the price series for charts and the backtest detail. The full record is in its detail
    shard and the page loads it when the stock is opened. This keeps data.json, which every visit downloads, small."""
    news = record.get("news") or {}
    dividend = record.get("dividend")
    statements = record.get("statements")
    return {**{k: v for k, v in record.items() if k not in ("spark_sma50", "live", "levels", "provenance", "outlook")},
            "news_intel": news_summary(record.get("news_intel")),
            "statements": {k: v for k, v in statements.items() if k not in ("quarterly", "annual")} if isinstance(statements, dict) else statements,
            "dividend": {k: v for k, v in dividend.items() if k != "history"} if isinstance(dividend, dict) else dividend,
            "spark": (record.get("spark") or [])[-2:],
            "news": {"fresh": news.get("fresh", []), "items": [], "error": news.get("error")},
            "backtest": {k: {"beats_buy_hold_oos": v.get("beats_buy_hold_oos")} for k, v in (record.get("backtest") or {}).items() if isinstance(v, dict)},
            "calc": derived(record), "fin": 1 if ratios.is_financial(record.get("fundamentals")) else None, "lite": True, "shard": shard_of(record["symbol"])}


def shard_of(symbol):
    return "%02d" % (zlib.crc32(symbol.encode("utf-8")) % SHARDS)


def _age_hours(stamp, now):
    try:
        return (now - datetime.fromisoformat(stamp)).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def pick(wide_list, quotes, index, now, size=PER_RUN, fund_version=None):
    """The stocks to analyse this run: never analysed first (most traded first), then the stalest. Only stocks that have a quote."""
    due = []
    for stock in wide_list:
        q = quotes.get(stock["symbol"])
        if not q:
            continue
        entry = index.get(stock["symbol"])
        if entry:
            age = _age_hours(entry.get("at"), now)
            behind = bool(fund_version) and entry.get("ok") and entry.get("fv") != fund_version      # analysed before the fundamentals had these fields
            if age is not None and age < (REFRESH_HOURS if entry.get("ok") else RETRY_HOURS) and not behind:
                continue
        turnover = (q.get("avg_volume") or 0) * q["price"]
        due.append(((1, entry.get("at") or "", 0) if entry else (0, "", -turnover), stock))
    due.sort(key=lambda row: row[0])
    return [stock for _, stock in due[:size]]


def load_shards(prev, loader):
    """{shard id: {symbol: record}} read back from the previous publish. A shard that does not exist yet is simply empty."""
    def one(number):
        name = "%02d" % number
        return name, (loader(prev, f"detail/{name}.json") if prev else {})
    with ThreadPoolExecutor(WORKERS) as pool:
        loaded = dict(pool.map(one, range(SHARDS)))
    return {k: (v if isinstance(v, dict) else {}) for k, v in loaded.items()}


def _round(value, digits):
    return round(value, digits) if isinstance(value, (int, float)) else None


FUND_KEYS = ("roe", "roa", "debt_to_equity", "profit_margin", "operating_margin", "ebitda_margin", "revenue_growth", "earnings_growth", "payout_ratio",
             "ebitda", "ev_ebitda", "ev_revenue", "price_to_sales", "peg", "free_cash_flow", "current_ratio", "revenue", "gross_margin")
TECH_KEYS = ("rsi", "macd_hist", "sma20", "sma50", "sma200", "atr", "momentum126", "adx", "rs126")      # what the table's technical filters need
NEAR = 0.05          # the same 5% as the "Near 52-week high / low" lists of the curated stocks


def _indicated_yield(q):
    """Yahoo's indicated annual dividend over the price, or None. A result over 50% of the price is a data error (a different currency or a stale rate)."""
    rate, price = q.get("dividend_rate"), q.get("price")
    if not rate or not price or rate / price > 0.5:
        return None
    return _round(rate / price, 5)


def quote_lists(q):
    """Lists a stock belongs to from its quote alone, so even a stock that is not analysed yet appears in them."""
    price, high, low = q["price"], q.get("high52"), q.get("low52")
    lists = []
    if high and price >= (1 - NEAR) * high:
        lists.append("Near 52-week high")
    if low and price <= (1 + NEAR) * low:
        lists.append("Near 52-week low")
    return lists


def _compact(value):
    """A ratio to four places and a large amount to a whole number: the file holds a few thousand stocks and Yahoo's long fractions only add weight."""
    return round(value) if abs(value) >= 1000 else round(value, 4)


def extra_row(record):
    """What the table needs only for its technical filters and its Valuation, Dividend, Technical and Risk column views: the stock's indicator values, pattern
    names, pressure and fundamentals. They are in index_extra.json, which the page fetches only when one of those is used, so the start-up file stays small."""
    calc = derived(record) if record else None                     # first: it also corrects the record's EV/EBITDA that the fundamentals below carry
    row = {"ind": {k: _round(v, 3) for k, v in ((record or {}).get("indicators") or {}).items() if k in TECH_KEYS and isinstance(v, (int, float))},
           "pressure": ((record or {}).get("pressure") or {}).get("label"),
           "patterns": [[p["name"], p.get("bias")] for p in (record or {}).get("patterns") or [] if isinstance(p, dict) and p.get("name")],
           "fund": {k: _compact(v) for k, v in ((record or {}).get("fundamentals") or {}).items() if k in FUND_KEYS and isinstance(v, (int, float))}}
    if record:
        risk = record.get("risk") or {}
        row["risk"] = {k: _round(risk.get(k), 3) for k in ("beta", "max_drawdown") if isinstance(risk.get(k), (int, float))}
        row["calc"] = calc
        row["fin"] = 1 if ratios.is_financial(record.get("fundamentals")) else None
    return {k: v for k, v in row.items() if v is not None and v != [] and v != {}}


def derived(record):
    """The worked-out figures of ratios.py for one record, dated by the record's own last price day."""
    try:
        today = date.fromisoformat(record.get("as_of"))
    except (TypeError, ValueError):
        today = None
    ratios.correct_fundamentals(record, today)
    return ratios.derive(record, today)


def index_row(stock, q, entry, record):
    """One compact row. Empty values are left out (the page treats a missing field as none), which roughly halves the file."""
    row = _index_row(stock, q, entry, record)
    return {k: v for k, v in row.items() if v is not None and v != [] and v != {}}


def _index_row(stock, q, entry, record):
    short = (record or {}).get("short") or {}
    long_ = (record or {}).get("long") or {}
    return {"symbol": stock["symbol"], "name": stock["name"], "market": stock["market"], "sector": "Other",
            "currency": "INR" if stock["symbol"].endswith(".NS") else "USD",
            "price": round(q["price"], 4), "change_pct": _round(q.get("change_pct"), 2), "cap": _round(q.get("cap"), 0), "volume": _round(q.get("volume"), 0),
            "avg_volume": _round(q.get("avg_volume"), 0),
            "high52": _round(q.get("high52"), 2), "low52": _round(q.get("low52"), 2), "shard": shard_of(stock["symbol"]), "analysed": bool(record), "series": stock.get("series"),
            "short": {"label": short.get("label"), "score": short.get("score")} if record else None,
            "long": {"label": long_.get("label"), "score": long_.get("score")} if record else None,
                        "pe": _round(q.get("pe"), 2), "forward_pe": _round(q.get("forward_pe"), 2), "pb": _round(q.get("pb"), 2), "eps": _round(q.get("eps"), 2),
            "book_value": _round(q.get("book_value"), 2), "dividend_rate": _round(q.get("dividend_rate"), 4),
            # for a stock that is analysed the yield is worked out from its payments; otherwise it is Yahoo's indicated rate over the price (marked on the page)
            "dividend_yield": _round((record or {}).get("dividend_yield"), 5) if record else _indicated_yield(q),
            "dividend_basis": None if record else "indicated",
            "thin": True if q.get("avg_volume") is not None and q.get("price") and q["price"] * q["avg_volume"] < evidence.THIN_TURNOVER.get("IN" if stock["symbol"].endswith(".NS") else "US", 0) else None,
            "lists": list(dict.fromkeys(quote_lists(q) + [n for n in (record or {}).get("lists", []) if n != "Other"]))}


def update(now, index, wide_list, quotes, analyse, ctx, prev, loader, out_dir, log=print, lists_fn=None, curated_records=(), fundamentals_fn=None, statements_fn=None, outlook_fn=None):
    """Analyse this run's slice, rewrite the shards and the index. Returns the analysis index to keep in the saved state.

    analyse(entry, ctx) is the same function the curated list uses. One bad stock never stops the run."""
    wide_symbols = {s["symbol"] for s in wide_list}
    kept_symbols = wide_symbols | {r["symbol"] for r in curated_records}
    index = {s: e for s, e in (index or {}).items() if s in wide_symbols}
    shards = load_shards(prev, loader)
    for symbol in list(index):                           # an index entry whose record is gone (a shard that failed to load) is analysed again
        if index[symbol].get("ok") and symbol not in shards.get(shard_of(symbol), {}):
            del index[symbol]
    chosen = pick(wide_list, quotes, index, now, fund_version=fundamentals.VERSION if fundamentals_fn else None)
    local = {**ctx, "bars": {}, "completed_bars": {}, "news_breaker": _NoNews()}

    def one(stock):
        entry = {"symbol": stock["symbol"], "name": stock["name"], "market": stock["market"], "sector": "Other", "tags": []}
        try:
            return stock["symbol"], analyse(entry, local), None
        except Exception as err:                         # a short history or a bad row is this stock's trouble only
            return stock["symbol"], None, str(err)[:100]

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(one, chosen))
    stamp, done = now.isoformat(timespec="seconds"), 0
    if fundamentals_fn:                                  # one request per stock, in the same slice, so the whole list fills in over hours
        for symbol, record, error in results:
            if record is not None:
                old = (shards.get(shard_of(symbol), {}).get(symbol) or {}).get("fundamentals") or {}
                fresh = fundamentals_fn(symbol)
                record["fundamentals"] = fresh if fresh and fresh.get("market_cap") is not None else (old or fresh or {})
                old_record = shards.get(shard_of(symbol), {}).get(symbol) or {}
                record["fundamentals_at"] = int(now.timestamp()) if record["fundamentals"] is fresh else old_record.get("fundamentals_at")
                if statements_fn:
                    held = old_record.get("statements")
                    record["statements"] = held if held and not statements.due_record(held, int(now.timestamp())) else (statements_fn(symbol) or held or {})
    for symbol, record, error in results:
        if record is not None:
            try:
                json.dumps(record, allow_nan=False)
            except ValueError:
                record, error = None, "unreadable numbers"
        if record is None:
            index[symbol] = {"at": stamp, "ok": False, "error": error}
            continue
        record["dividend_check"] = dividends.cross_check(record.get("dividend"), record.get("price"), (quotes.get(symbol) or {}).get("dividend_rate"))
        if outlook_fn:
            record["outlook"] = outlook_fn(record)
        record["provenance"], record["provenance_ok"] = provenance.build(record, int(now.timestamp()))
        record["calc"], record["fin"] = derived(record), (1 if ratios.is_financial(record.get("fundamentals")) else None)      # the page's own row of a peer table needs them too
        if lists_fn:
            lists_fn([record])                          # the lists (Oversold, Low debt and so on) the curated stocks get
        shards[shard_of(symbol)][symbol] = record
        index[symbol] = {"at": stamp, "ok": True, "fv": fundamentals.VERSION if fundamentals_fn else None}
        done += 1
    for record in curated_records:                       # the curated stocks' full records, loaded when one is opened (a carried-over or already slim record never replaces them)
        if not record.get("carried") and not record.get("lite"):
            record["calc"], record["fin"] = derived(record), (1 if ratios.is_financial(record.get("fundamentals")) else None)
            shards[shard_of(record["symbol"])][record["symbol"]] = record
    for records in shards.values():                      # drop records of stocks that left the list
        for symbol in [s for s in records if s not in kept_symbols]:
            del records[symbol]
    out = Path(out_dir)
    (out / "detail").mkdir(parents=True, exist_ok=True)
    for name, records in shards.items():
        if records:
            (out / "detail" / f"{name}.json").write_text(json.dumps(records, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    all_records = {s: r for records in shards.values() for s, r in records.items()}
    rows = [index_row(s, quotes[s["symbol"]], index.get(s["symbol"]), all_records.get(s["symbol"])) for s in wide_list if s["symbol"] in quotes]
    # A stock the quote request did not return this run (a failed batch, a Yahoo outage) keeps its row from the last publish instead of vanishing from the table.
    previous_rows = {r.get("symbol"): r for r in ((loader(prev, "index.json") if prev else {}) or {}).get("stocks", []) if isinstance(r, dict)}
    seen = {r["symbol"] for r in rows}
    kept = [previous_rows[s["symbol"]] for s in wide_list if s["symbol"] not in seen and s["symbol"] in previous_rows]
    rows += kept
    extras = {r["symbol"]: extra_row(all_records[r["symbol"]]) for r in rows if r.get("analysed") and r["symbol"] in all_records}
    previous_extra = ((loader(prev, "index_extra.json") if prev else {}) or {}).get("stocks", {})
    extras.update({r["symbol"]: previous_extra[r["symbol"]] for r in kept if r["symbol"] in previous_extra})
    payload = {"generated_at": stamp, "count": len(rows), "analysed": sum(1 for r in rows if r["analysed"]), "stocks": rows}
    (out / "index.json").write_text(json.dumps(payload, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    (out / "index_extra.json").write_text(json.dumps({"generated_at": stamp, "stocks": {s: e for s, e in extras.items() if e}}, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    if kept:
        log(f"Catalog: {len(kept)} stocks had no quote this run and keep their previous row")
    log(f"Catalog: {len(rows)} stocks listed, {payload['analysed']} analysed; {done} analysed this run, {len(results) - done} without enough history")
    return index

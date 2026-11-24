"""Build site/data.json (read by the web page) and site/state.json (kept for the next run).

Usage: python -m engine.build --out site [--prev SITE_URL_OR_DIR] [--limit N]
"""
import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import digest, event_news, events, market as market_view, verify
from . import actions, actions_run, alert_memory, digest_feeds, feed_items, feed_run, feeds, ledger_git, manifest, ai_sentiment, catalog, data_learning, evidence, learning, news_ai, news_intel, news_sources, nse_live, sentiment, provenance, statements, universe_sync, alerts, backtest, costs, deals_live, sessions, wide, discover, membership as index_membership, official, dividends, exchange, fetch, fundamentals, ipo_gmp, ledger, news, patterns, risk, signals, tracking

ROOT = Path(__file__).resolve().parent.parent
WORKERS = 6
FUNDAMENTALS_MAX_AGE = 20 * 3600
STALE_DAYS = 5
SPARK_DAYS = 90
SPLIT_MEMORY_DAYS = 1095    # splits from the last three years are kept on a stock's page
SPARK_MARKET = 30
MAX_FAILURE_SHARE = 0.6
NEW_MAX_BARS = 250
CARRY_MAX_AGE_DAYS = 4
NEWS_FAILURE_LIMIT = 12     # news lookups that fail in a row before the rest of the run skips them
TOO_NEW = "Too new for signals: about 60 trading days of history are needed"


class Breaker:
    """Stops asking a source that keeps failing, so one outage cannot make a whole run take twenty minutes.

    After `limit` failures in a row it is open and the caller skips the source for the rest of the run. Any success
    resets the count. Safe to share between the worker threads."""

    def __init__(self, limit):
        self.limit, self.count, self._lock = limit, 0, threading.Lock()

    @property
    def open(self):
        return self.count >= self.limit

    def failed(self):
        with self._lock:
            self.count += 1

    def succeeded(self):
        with self._lock:
            self.count = 0


def r(value, digits=4):
    """Round for compact JSON. NaN and infinity become None."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return round(value, digits) if isinstance(value, float) else value


def load_previous(source, name):
    """Read a JSON file from a URL or a folder. Missing or broken files give {}."""
    if not source:
        return {}
    try:
        if source.startswith("http"):
            return json.loads(fetch.http_get(source.rstrip("/") + "/" + name, retries=1))
        return json.loads((Path(source) / name).read_text(encoding="utf-8"))
    except (OSError, ValueError, fetch.FetchError):
        return {}


def signal_block(detail, ind=None, i=None, horizon=None):
    """One reading for the page: score, label, the reasons behind it and how complete the data was.

    detail is signals.short_detail / long_detail. confidence is "full", "reduced" or "limited" by the share of the rule's
    weight that had data; missing names the parts that could not be worked out. invalidation says what would weaken it."""
    score, reasons = detail["score"], detail["reasons"]
    if score is None:
        return {"score": None, "label": "N/A", "reasons": reasons or [{"text": TOO_NEW, "tone": "neutral"}],
                "coverage": detail["coverage"], "confidence": signals.confidence(detail["coverage"]), "missing": detail["missing"], "invalidation": []}
    return {"score": score, "label": signals.label(score), "reasons": reasons,
            "coverage": detail["coverage"], "confidence": signals.confidence(detail["coverage"]), "missing": detail["missing"],
            "invalidation": signals.invalidation(ind, i, horizon, score) if ind is not None else []}


def first_valid(fn, start, end):
    for i in range(start, end):
        if fn(i) is not None:
            return i
    return None


BACKTEST_NOTES = [
    "Long only: the rule holds the stock or sits in cash (cash earns nothing). The score at the close of one day decides the trade at the next day's open.",
    "Costs are assumptions (taxes, fees and slippage) charged on each entry and exit; a gross run without costs is shown as gross_return. A position still open at the end is valued as if sold at the last close, less the exit cost.",
    "Headline figures are price-only. A second set (total) includes cash dividends on the ex-date for the rule and for buy-and-hold alike, reinvested at the ex-date close at no cost, with no tax on dividends. Prices and dividend amounts are Yahoo's and are adjusted for splits and bonus issues; spin-offs and mergers are not modelled.",
    "The stocks are today's list, so companies that were delisted or dropped out are missing (survivorship bias). A stock is only tested from the day it joined the S&P 500 where that date is known (all US stocks here joined before the test window, so this changes nothing today); no addition dates are available for India. This is NOT a survivorship-bias-free test.",
    "The recent 40% is the last part of the same history tested with the same fixed rules. It is not an independent out-of-sample test, because the rules were designed knowing earlier market history.",
    "Sharpe and Sortino use daily returns and a zero risk-free rate. CAGR compounds the total return over the tested trading days.",
]


def reading_side(label):
    return "buy" if label in ("Buy", "Strong Buy") else "sell" if label in ("Sell", "Strong Sell") else "hold" if label else None


def apply_news_context(record, sector_moves):
    """Add the market reaction (price, volume and sector against the news) and the comparison with the existing reading to a record's news intelligence.
    News never creates a reading: it only confirms, conflicts with or says nothing about the one the price rules gave."""
    intel = record.get("news_intel")
    if not intel:
        return
    intel["reaction"] = news_intel.reaction(intel, record.get("change_pct"), record.get("volume_ratio"), sector_moves.get(record.get("sector")))
    intel["validation"] = news_intel.validate(intel, reading_side(((record.get("short") or {}).get("label"))))


def ai_summary(stories, ai_scores, ai_meta):
    """What the optional model job has done and how its scores compare with the rule-based ones (agreement is not accuracy: there is no labelled truth yet)."""
    both = [s for s in stories if s.get("ai_sentiment") is not None and s.get("rule_sentiment") is not None]
    firm = [s for s in both if abs(s["rule_sentiment"]) >= 20 and abs(s["ai_sentiment"]) >= 20]
    meta = ai_meta or {}
    return {"enabled": bool(ai_scores), "model": meta.get("model"), "generated_at": meta.get("generated_at"), "scored": sum(1 for s in stories if s["ai"]),
            "shadow": ai_sentiment.AI_WEIGHT == 0, "weight": ai_sentiment.AI_WEIGHT, "status": meta.get("status"),
            "agreement": {"compared": len(both), "same_direction_pct": round(100 * sum(1 for s in firm if (s["rule_sentiment"] > 0) == (s["ai_sentiment"] > 0)) / len(firm)) if firm else None,
                          "firm_pairs": len(firm), "mean_abs_difference": round(sum(abs(s["rule_sentiment"] - s["ai_sentiment"]) for s in both) / len(both), 1) if both else None}}


def news_dashboard(records, pool, market_items, names, sector_moves, provider_status, ai_scores, ai_meta, archive, now, limit=80):
    """The News tab's data: the most important stories across the market, sector sentiment, stocks where price and news disagree, and the providers' state."""
    by_symbol = {r["symbol"]: r for r in records}
    stories, duplicates_removed, total_raw = [], 0, 0
    for symbol, rows in pool.items():
        raw = []
        for r in rows:
            raw.append({**r, "ai": ai_scores.get(ai_sentiment.key(r.get("text") if r["kind"] == "nse" else r["title"]))})
        total_raw += len(raw)
        unique = news_intel.dedupe([news_intel.make_story(r, now, names.get(symbol)) for r in raw])
        duplicates_removed += len(raw) - len(unique)
        rec = by_symbol.get(symbol)
        sector = (rec or {}).get("sector") or next((r.get("industry") for r in rows if r.get("industry")), None) or "Other"
        for s in unique:
            if s["impact"] >= 20:
                stories.append({**{k: s[k] for k in ("title", "source", "link", "ts", "kind", "event_label", "tone", "sentiment", "credibility", "impact", "horizon", "sources",
                                                     "duplicates", "ai", "ai_sentiment", "rule_sentiment", "short_term", "long_term", "risk", "age_hours")},
                                "symbol": symbol, "name": names.get(symbol), "sector": sector, "tracked": rec is not None,
                                "interpretation": ((rec or {}).get("news_intel") or {}).get("interpretation")})
    for r in market_items:
        s = news_intel.make_story({**r, "ai": ai_scores.get(ai_sentiment.key(r["title"]))}, now, None)
        sector = news_intel.sector_of_text(r["title"])
        if s["impact"] >= 15 and sector:
            stories.append({**{k: s[k] for k in ("title", "source", "link", "ts", "kind", "event_label", "tone", "sentiment", "credibility", "impact", "horizon", "sources",
                                                 "duplicates", "ai", "ai_sentiment", "rule_sentiment", "short_term", "long_term", "risk", "age_hours")}, "symbol": None, "name": None, "sector": sector, "tracked": False, "interpretation": None})
    stories.sort(key=lambda s: -(s["impact"] * max(0.2, 0.5 ** ((s["age_hours"] or 0) / 36.0))))
    stories = stories[:limit]
    with_intel = [r for r in records if r.get("news_intel")]
    weight = sum(s["impact"] for s in stories)
    tone = round(sum(s["impact"] * s["sentiment"] for s in stories) / (weight + 10)) if weight else 0
    divergences = sorted((r for r in with_intel if (r["news_intel"].get("reaction") or {}).get("state") == "price diverges" and r["news_intel"]["impact"] >= 35),
                         key=lambda r: -r["news_intel"]["impact"])[:10]
    brief = lambda r: {"symbol": r["symbol"], "name": r["name"], "sector": r["sector"], "sentiment": r["news_intel"]["sentiment"], "impact": r["news_intel"]["impact"],
                       "interpretation": r["news_intel"]["interpretation"], "change_pct": r.get("change_pct"), "reaction": (r["news_intel"].get("reaction") or {}).get("text"),
                       "validation": (r["news_intel"].get("validation") or {}).get("state")}
    ranked = sorted(with_intel, key=lambda r: r["news_intel"]["sentiment"] * r["news_intel"]["impact"])
    events = {}
    for s in stories:
        events[s["event_label"]] = events.get(s["event_label"], 0) + 1
    official = sum(1 for s in stories if s["kind"] in ("nse", "bse"))
    return {"generated_at": now.isoformat(timespec="seconds"), "market_tone": tone, "stories": stories,
            "sectors": news_intel.sector_table([{"sector": r["sector"], "intel": r["news_intel"]} for r in with_intel], sector_moves),
            "top_negative": [brief(r) for r in ranked[:8] if r["news_intel"]["sentiment"] <= -20], "top_positive": [brief(r) for r in reversed(ranked[-8:]) if r["news_intel"]["sentiment"] >= 20],
            "divergences": [brief(r) for r in divergences], "events": dict(sorted(events.items(), key=lambda kv: -kv[1])),
            "providers": [{"name": k, "ok": v["ok"], "items": v.get("items", 0), "error": v.get("error"), "fetched_at": v.get("fetched_at")} for k, v in provider_status.items()],
            "counts": {"archive_items": len(archive), "stocks_with_news": len(pool), "stories_shown": len(stories), "duplicates_removed": duplicates_removed, "raw_stock_items": total_raw,
                       "official_share_pct": round(100 * official / len(stories)) if stories else None},
            "ai": ai_summary(stories, ai_scores, ai_meta)}


def learning_age_ok(learned, now):
    """Whether the weekly learned table is not older than ten days."""
    try:
        return now - datetime.fromisoformat(learned["generated_at"]) <= timedelta(days=10)
    except (KeyError, TypeError, ValueError):
        return False


def run_backtests(ind, n, market="IN", overrides=None, dividends=None, min_start=0):
    if n < 260:
        return None
    out = {}
    rules = {"short": lambda i: signals.short_score(ind, i)[0], "long": lambda i: signals.long_score(ind, i)[0]}
    for name, fn in rules.items():
        start = first_valid(fn, min_start, n - backtest.MIN_DAYS)
        entry_cost, exit_cost = costs.sides(market, overrides)
        result = backtest.backtest(ind["bars"], fn, start, entry_cost=entry_cost, exit_cost=exit_cost, dividends=dividends) if start is not None else None
        out[name] = scrub(result)
    return out


def scrub(value):
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, float):
        return r(value, 5)
    return value


def analyse(entry, ctx):
    symbol, market = entry["symbol"], entry["market"]
    min_bars = 5 if entry.get("new") else fetch.MIN_BARS
    chart = fetch.fetch_chart(symbol, "5y", min_bars)
    live_bars = chart["bars"]
    ctx.get("bars", {})[symbol] = live_bars
    # While the market is open Yahoo's newest daily bar is today's unfinished candle (live price, range so far and only the
    # volume traded so far). The price shown is that live price. Every indicator and reading is worked out from completed
    # candles, and today's unfinished candle gets a separate, clearly marked provisional reading.
    provisional = fetch.last_bar_provisional(live_bars, chart["meta"], ctx["now_ts"]) and len(live_bars["c"]) > min_bars
    bars = fetch.trim_last_bar(live_bars) if provisional else live_bars
    ctx.setdefault("completed_bars", {})[symbol] = bars      # the track record is checked against completed candles only
    close = bars["c"]
    n, i = len(close), len(close) - 1
    live_close = live_bars["c"]
    price = live_close[-1]
    change = (price / live_close[-2] - 1) * 100 if len(live_close) > 1 else None
    age_days = (ctx["today"] - date.fromisoformat(live_bars["d"][-1])).days

    ticker_base = symbol.split(".")[0]
    breaker = ctx.get("news_breaker")
    if breaker is not None and breaker.open:
        items, news_error = [], True
    else:
        try:
            items, news_error = news.fetch_news(f'"{entry["name"]}" (shares OR stock OR results)', market, ctx["now"]), False
            if breaker is not None:
                breaker.succeeded()
        except fetch.FetchError:
            items, news_error = [], True
            if breaker is not None:
                breaker.failed()
    news.mark_relevance(items, entry["name"], ticker_base)

    ind = signals.build_indicators(bars)
    # news intelligence: the stock's own headline search plus the exchanges' announcements and the RSS feeds mapped to it, de-duplicated and scored
    ai_map = ctx.get("news_ai") or {}
    raw_news = [{"title": it["title"], "text": it["title"], "source": it.get("source"), "link": it.get("link"), "ts": it.get("ts"), "kind": "media", "desc": "", "symbol": symbol}
                for it in items if it.get("relevant", True)]
    raw_news += list((ctx.get("news_pool") or {}).get(symbol, []))
    raw_news = [{**row, "ai": ai_map.get(ai_sentiment.key(row.get("text") if row["kind"] == "nse" else row["title"]))} for row in raw_news]       # (a loop variable named r would hide the rounding helper r)
    intel = news_intel.analyse_stock(news_intel.dedupe([news_intel.make_story(row, ctx["now"], entry["name"]) for row in raw_news]), ctx["now"])
    short_detail, long_detail = signals.short_detail(ind, i), signals.long_detail(ind, i)
    pressure = signals.buy_sell_pressure(ind, i)
    live = None
    if provisional:
        partial = {k: list(v) for k, v in live_bars.items()}
        partial["v"][-1] = None            # the day's volume is incomplete, so volume rules must not use it
        live_ind = signals.build_indicators(partial)
        live_i = len(partial["c"]) - 1
        live = {"short": signal_block(signals.short_detail(live_ind, live_i), live_ind, live_i, "short"),
                "long": signal_block(signals.long_detail(live_ind, live_i), live_ind, live_i, "long")}
    dividend = dividends.dividend_profile(chart["dividends"], price, ctx["now_ts"])
    recent_splits = [{"date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"), "ratio": f"{num:g}:{den:g}"}
                     for ts, num, den in chart.get("splits", []) if ctx["now_ts"] - ts <= SPLIT_MEMORY_DAYS * 86400][-3:]

    base = symbol[:-3] if symbol.endswith(".NS") else None
    delivery = exchange_view = None
    if base:
        series = [(d, v[base][0]) for d, v in sorted(ctx["delivery"].items()) if base in v]
        delivery = exchange.delivery_view(series, change)
        exchange_view = ctx["deals"].get(base)

    # A "new listing" with a long price history is an old stock the exchange re-labelled (series change).
    relabelled = bool(entry.get("new")) and n > NEW_MAX_BARS
    is_new = bool(entry.get("new")) and not relabelled
    record = {
        "symbol": symbol, "name": entry["name"], "market": market,
        "sector": "Other" if relabelled else entry["sector"],
        "tags": [] if relabelled else entry.get("tags", []), "new": is_new, "listed": entry.get("listed"),
        "currency": chart["meta"]["currency"], "exchange": chart["meta"]["exchange"],
        "price": r(price), "change_pct": r(change, 2), "as_of": live_bars["d"][-1], "stale": age_days > STALE_DAYS,
        "series_lag": bool(chart.get("lagging")) or live_bars["d"][-1] < fetch.expected_session(ctx["now_ts"]),      # the price series misses the newest session, so no call is recorded at this price
        "bars": n,
        "provisional": provisional, "confirmed_as_of": bars["d"][i],
        "short": signal_block(short_detail, ind, i, "short"),
        "long": signal_block(long_detail, ind, i, "long"),
        "pressure": {"label": pressure["label"], "money_flow": r(pressure["money_flow"]),
                     "up_volume_share": r(pressure["up_volume_share"])} if pressure else None,
        "delivery": scrub(delivery),
        "deals": scrub(exchange_view),
        "news": {"items": items[:6], "fresh": news.fresh_headlines(items), "error": news_error},
        "news_intel": intel,
        "volume_ratio": round(bars["v"][i] / ind["avg_volume20"][i], 2) if bars["v"][i] and ind["avg_volume20"][i] else None,
        "dividend_yield": r(dividend["ttm_yield"], 5) if dividend else 0.0,
        "dividend": scrub(dividend),
        "splits": recent_splits,
        "spark": [r(v) for v in live_close[-SPARK_DAYS:]],
        "spark_sma50": [r(v) for v in (ind["sma50"] + ([None] if provisional else []))[-SPARK_DAYS:]],
    }
    if live:
        record["live"] = live
    if n >= 30:
        record["patterns"] = patterns.detect_patterns(bars, ind)
    if n >= 60:
        record["levels"] = scrub({**ta_levels(bars, price)})
        record["stop"] = scrub(signals.stop_loss(price, ind["atr"][i]))
        record["indicators"] = {k: r(ind[k][i]) for k in
                                ("rsi", "macd_hist", "sma20", "sma50", "sma200", "atr", "vwap20", "vol30",
                                 "cmf20", "upvol20", "momentum126", "hi252", "lo252")}
    if n > 60:
        record["risk"] = scrub(risk.risk_stats(close, dict(zip(bars["d"], close)), ctx["bench"].get(market)))
    member_from = index_membership.lookup(ctx.get("membership"), market, symbol)
    record["backtest"] = run_backtests(ind, n, market, ctx.get("costs"), backtest.dividends_by_bar(bars, chart["dividends"]),
                                       index_membership.first_eligible_index(bars["d"], member_from))
    record["member_from"] = member_from
    record["evidence"] = evidence.stock_evidence(record["backtest"])          # the rule's own result on this stock, shown beside the reading
    record["flags"] = evidence.data_flags(price, ind["avg_volume20"][i], market, n)
    return record


def ta_levels(bars, price=None):
    from .indicators import fibonacci_levels, support_resistance
    return {"zones": support_resistance(bars["h"], bars["l"], bars["c"], price=price),
            "fib": fibonacci_levels(bars["h"], bars["l"])}


def add_lists(records):
    """Give every stock the lists it belongs to: fixed ones and ones computed from the data."""
    labels = {"psu": "Government-backed", "megacap": "US mega cap", "new": "New listings"}
    for rec in records:
        lists = [rec["sector"]] + [labels.get(t, t) for t in rec["tags"]]
        ind, rsk, fund = rec.get("indicators") or {}, rec.get("risk") or {}, rec.get("fundamentals") or {}
        threshold = 0.03 if rec["market"] == "IN" else 0.025
        recurring = (rec.get("dividend") or {}).get("ttm_regular_yield")       # one-off specials do not make a stock a high-dividend one
        if (recurring if recurring is not None else rec.get("dividend_yield") or 0) >= threshold and not (rec.get("dividend") or {}).get("overdue"):
            lists.append("High dividend")
        debt = fund.get("debt_to_equity")
        if debt is not None and debt < 0.5 and rec["sector"] not in ("Banks", "Financials"):
            lists.append("Low debt")
        if rsk.get("annual_vol") is not None and rsk["annual_vol"] < 0.25:
            lists.append("Low volatility")
        if (ind.get("momentum126") or 0) >= 0.15 and ind.get("sma200") and rec["price"] > ind["sma200"]:
            lists.append("Momentum leaders")
        if any(p.get("name") == "20-day breakout" for p in rec.get("patterns") or []):
            lists.append("Breakouts")                  # closed above the 20-day high today (a scanner, not a forecast)
        if ind.get("rsi") is not None and ind["rsi"] < 30:
            lists.append("Oversold")
        if ind.get("hi252") and rec["price"] >= 0.95 * ind["hi252"]:
            lists.append("Near 52-week high")
        if ind.get("lo252") and rec["price"] <= 1.05 * ind["lo252"]:
            lists.append("Near 52-week low")
        if (rec["long"]["score"] or 0) >= 50:
            lists.append("Strong long-term trend")
        if (rec.get("delivery") or {}).get("tone") == "pos":
            lists.append("Strong delivery buying")
        rec["lists"] = list(dict.fromkeys(lists))


def market_overview(config, now, raw=None):
    """Index, volatility and commodity cards plus world headlines. raw, if given, collects each symbol's bars."""
    def one(item):
        symbol, name, kind = item
        try:
            chart = fetch.fetch_chart(symbol, "2y", 30)
        except fetch.FetchError:
            return None
        close = chart["bars"]["c"]
        out = {"symbol": symbol, "name": name, "kind": kind, "price": r(close[-1]),
               "change_pct": r((close[-1] / close[-2] - 1) * 100, 2),
               "month_pct": r((close[-1] / close[-22] - 1) * 100, 2) if len(close) > 22 else None,
               "as_of": chart["bars"]["d"][-1], "spark": [r(v) for v in close[-SPARK_MARKET:]]}
        if raw is not None:
            raw[symbol] = chart["bars"]
        if kind == "index" and len(close) >= 200:
            sma50, sma200 = sum(close[-50:]) / 50, sum(close[-200:]) / 200
            out["regime"] = "Uptrend" if close[-1] > sma50 and close[-1] > sma200 else \
                "Downtrend" if close[-1] < sma50 and close[-1] < sma200 else "Mixed"
        if kind == "fear":
            out["regime"] = "Calm" if close[-1] < 15 else "Normal" if close[-1] < 25 else "Fearful"
        return out

    with ThreadPoolExecutor(WORKERS) as pool:
        watch = [x for x in pool.map(one, config["market_watch"]) if x]

    headlines = {}
    for market, query in config["global_news_queries"]:
        try:
            for item in news.fetch_news(query, market, now, limit=5):
                headlines.setdefault(item["title"], {**item, "topic": query})
        except fetch.FetchError:
            continue
    ordered = sorted(headlines.values(), key=lambda i: (i["age_min"] is None, i["age_min"] or 0))[:20]
    return {"watch": watch, "news": ordered}


def send_formatted(token, chat, text, reply_to=None):
    """Send a Telegram HTML message. If Telegram refuses the formatting, send the same message as plain text."""
    ok, message_id = alerts.post_telegram(token, chat, text, reply_to, markup=True)
    if not ok:
        ok, message_id = alerts.post_telegram(token, chat, alerts.to_plain(text)[: alerts.TELEGRAM_MAX_CHARS], reply_to)
    return ok, message_id


def status_block(config, records, errors, carried, overview, conditions, ipos, delivery, track_record, pending, token, chat, accuracy=None, official_events=None, live_deals=None, nse=None, live_check=None):
    """Plain checks of how healthy this run was, for the status panel: [{"name", "state": ok|warn|info, "detail"}]."""
    checks = []

    def add(name, state, detail):
        checks.append({"name": name, "state": state, "detail": detail})

    failed_new = sum(1 for e in errors if e.get("new"))
    failed = len(errors) - failed_new
    carried_new = sum(1 for c in carried if c.get("new"))
    carried_old = len(carried) - carried_new
    detail = f"{len(records)} stocks loaded" + (f", {failed} failed to load" if failed else "")
    if carried_old:
        detail += f", {carried_old} kept from the previous run"
    recent = carried_new + failed_new
    if recent:
        detail += f", {recent} recent listing{'s' if recent != 1 else ''} without enough history yet (Yahoo often returns too little for them)"
    add("Stock prices", "warn" if failed or carried_old else "ok", detail)
    news_down = sum(1 for x in records if (x.get("news") or {}).get("error"))
    add("News", "warn" if records and news_down / len(records) > 0.2 else "ok",
        "Headlines loaded" if not news_down else f"Headlines missing for {news_down} stocks" + (" (the news source is not answering)" if news_down == len(records) else ""))
    wanted, got = len(config.get("market_watch", [])), len((overview or {}).get("watch", []))
    add("Index and market data", "ok" if got >= wanted else "warn", f"{got} of {wanted} market series loaded")
    missing = [m for m, c in (conditions or {}).items() if not c.get("regime")]
    add("Market conditions", "warn" if missing else "ok",
        "Worked out for " + ", ".join(sorted(conditions or {})) if not missing else "Not available for " + ", ".join(sorted(missing)))
    latest = max(delivery) if delivery else None
    if not accuracy:
        add("Price cross-check", "info", "No second price source could be reached this run")
    else:
        parts, healthy = [], True
        for market in ("IN",):
            s = (accuracy or {}).get(market)
            if not s:
                continue
            name = "India"
            spread = f" (median difference {s['median_diff_pct']:.3f}%)" if isinstance(s.get("median_diff_pct"), (int, float)) else " (nothing to compare yet)"
            parts.append(f"{name}: {s['match']} of {s['verified']} match {s['source']} within 0.5%{spread}"
                         + (f", {s['mismatch']} disagree" if s["mismatch"] else "") + (f", {s['unverified']} not covered" if s["unverified"] else ""))
            healthy = healthy and s["mismatch"] == 0 and (s["agreement_pct"] or 0) >= 95
        add("Price cross-check", "ok" if healthy else "warn", "; ".join(parts))
    add("NSE delivery data", "ok" if latest else "info", f"Latest day {latest}" if latest else "Not loaded")
    if nse is not None:
        if nse.get("ok") and live_check:
            add("NSE live prices", "ok" if live_check["mismatch"] <= max(1, 0.05 * live_check["compared"]) else "warn",       # one fast mover read a moment apart is not a fault
                f"{live_check['match']} of {live_check['compared']} movers match Yahoo within 1% (median difference {live_check['median_diff_pct']}%, largest {live_check['max_diff_pct']}%), snapshot {live_check['as_of']}")
        elif nse.get("ok"):
            add("NSE live prices", "info", "Snapshot read, but none of its stocks are in the main list or it is not current")
        else:
            add("NSE live prices", "warn", f"{nse.get('error') or 'no answer'}; last success {(nse.get('fetched_at') or 'never')}")
    if live_deals is not None:
        add("NSE live block deals", "ok" if live_deals.get("ok") else "warn",
            f"{len(live_deals.get('deals', []))} today, read {live_deals.get('fetched_at')}" if live_deals.get("ok")
            else f"{live_deals.get('error') or 'no answer'}; last success {live_deals.get('fetched_at') or 'never'}")
    if official_events is not None:
        if official_events.get("ok"):
            add("NSE official events", "ok", f"Read {official_events.get('fetched_at')}" + (" (reused, under an hour old)" if official_events.get("reused") else ""))
        else:
            add("NSE official events", "warn", f"{official_events.get('error') or 'no answer'}; last success {official_events.get('fetched_at') or 'never'}")
    add("India IPOs", "ok" if (ipos or {}).get("india_ok") else "warn",
        "Fresh from the source" if (ipos or {}).get("india_ok") else "Source unavailable, showing older data")
    if track_record is None:
        add("Track record", "info", "Not set up")
    else:
        waiting = len(pending)
        add("Track record", "warn" if waiting else "ok",
            f"{track_record.get('calls_total', 0)} readings recorded" + (f", {waiting} waiting to be saved" if waiting else ""))
    add("Telegram alerts", "ok" if token and chat else "info", "Connected" if token and chat else "Not set up")
    overall = "warn" if any(c["state"] == "warn" for c in checks) else "ok"
    return {"overall": overall, "checks": checks}


INCOMPLETE_RETRY = 1800          # seconds before fundamentals that came back without a market cap are asked for again
INCOMPLETE_TRIES = 4             # after this many incomplete answers in a row, go back to asking once a day
INCOMPLETE_PER_RUN = 30          # at most this many such retries in one run, to stay gentle with Yahoo


def fundamentals_fresh(cached, now_ts):
    """Whether cached fundamentals can be used as they are. Yahoo sometimes answers with a partial document (for
    example no market capitalisation for Reliance and TCS), and keeping that for a whole day left the gap on the page.
    An answer without a market cap is therefore asked for again after half an hour, and after a few incomplete answers
    in a row (some small companies really have none) once a day again."""
    if not cached or "events" not in cached.get("data", {}) or cached["data"].get("v") != fundamentals.VERSION:
        return False
    age = now_ts - cached.get("ts", 0)
    if cached["data"].get("market_cap") is None:
        return age < (INCOMPLETE_RETRY if cached.get("tries", 0) < INCOMPLETE_TRIES else FUNDAMENTALS_MAX_AGE)
    return age < FUNDAMENTALS_MAX_AGE


def fill_fundamentals(records, state, now_ts, session_factory):
    """Use cached fundamentals when fresh, otherwise fetch them (once a day per stock, sooner when incomplete).

    Missing values stay missing (None): nothing is replaced by zero, and a later partial answer never overwrites an
    earlier complete one."""
    cache = state.get("fundamentals", {})
    missing, retries = [], 0
    for rec in records:
        cached = cache.get(rec["symbol"])
        if fundamentals_fresh(cached, now_ts):
            rec["fundamentals"] = cached["data"]
        elif cached and cached["data"].get("market_cap") is None and "events" in cached.get("data", {}) and retries >= INCOMPLETE_PER_RUN:
            rec["fundamentals"] = cached["data"]          # this run's share of retries is used up
        else:
            if cached and cached["data"].get("market_cap") is None and "events" in cached.get("data", {}):
                retries += 1
            missing.append(rec)
    if missing:
        session = session_factory()
        if session.start():
            for rec in missing:
                old = cache.get(rec["symbol"]) or {}
                data = fundamentals.fetch_fundamentals(session, rec["symbol"])
                complete = bool(data) and data.get("market_cap") is not None
                if not complete and old.get("data", {}).get("market_cap") is not None:
                    data = old["data"]                    # keep the earlier complete answer rather than regress
                    cache[rec["symbol"]] = {"ts": old.get("ts", now_ts), "data": data, "tries": old.get("tries", 0)}
                elif data:
                    tries = 0 if complete else old.get("tries", 0) + 1
                    cache[rec["symbol"]] = {"ts": now_ts, "data": data, "tries": tries}
                rec["fundamentals"] = data
                time.sleep(0.15)
        else:
            print("Fundamentals unavailable this run (Yahoo session failed)")
            for rec in missing:
                rec["fundamentals"] = cache.get(rec["symbol"], {}).get("data", {})
    live = {rec["symbol"] for rec in records}
    return {k: v for k, v in cache.items() if k in live}


def build_universe(config, registry, limit):
    stocks = [{"symbol": s, "name": nm, "market": m, "sector": sec, "tags": tags}
              for s, nm, m, sec, tags in config["stocks"]]
    known = {s["symbol"] for s in stocks}
    stocks += [{"symbol": e["symbol"], "name": e["name"], "market": e["market"], "sector": "New listings",
                "tags": ["new"], "new": True, "listed": e["listed"]} for e in registry if e["symbol"] not in known and e.get("market", "IN") == "IN"]
    if limit:
        picked = [s for s in stocks if s["market"] == "IN"][:limit]
        new = [s for s in stocks if s.get("new")][:2]
        stocks = picked + [s for s in new if s not in picked]
    return stocks


def carry_forward(errors, previous, today):
    """Keep last run's record for a stock that failed to load this time, so one bad answer from Yahoo does not
    make it vanish from the page. Only records with a recent price date are kept. Returns (carried, still_failed)."""
    carried, failed = [], []
    for error in errors:
        old = previous.get(error["symbol"])
        try:
            age = (today - date.fromisoformat(old["as_of"])).days if old else None
        except (KeyError, TypeError, ValueError):
            age = None
        if age is not None and 0 <= age <= CARRY_MAX_AGE_DAYS:
            # Its headlines and their ages are from an earlier run, so they must not look current.
            carried.append({**old, "carried": True, "news": {"items": [], "fresh": [], "error": True}})
        else:
            failed.append(error)
    return carried, failed


def data_remote(args):
    """The git remote holding the data branch, or "" when this run keeps nothing there (local runs and tests)."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    return args.ledger_remote or (f"https://github.com/{repo}.git" if repo and not args.ledger_dir else "")


def open_alert_memory(args):
    """(working copy folder, remote) of the data branch for the sent-alert memory, or (None, "") if it cannot be reached. Never raises."""
    remote = data_remote(args)
    if not remote:
        return None, ""
    directory = Path(tempfile.mkdtemp()) / "alert-memory"
    try:
        ledger_git.prepare(directory, remote, token=os.environ.get("GITHUB_TOKEN") or None)
        return directory, remote
    except (ledger_git.GitError, OSError) as err:
        print("Sent-alert memory unavailable, using the published state:", err)
        return None, ""


def save_alert_memory(directory, remote, new_state, now):
    """Store what has been sent on the data branch. A failure is reported and the run carries on (the published state is the fallback)."""
    if not directory:
        return False
    try:
        alert_memory.write(directory, new_state, now.isoformat())
        ledger_git.publish(directory, f"Sent alerts {now:%Y-%m-%d %H:%M}", token=os.environ.get("GITHUB_TOKEN") or None)
        return True
    except (ledger_git.GitError, OSError) as err:
        print("Sent-alert memory not saved:", err)
        return False


def track(args, state, prev_data, calls, ctx, now_ts, token, chat, link_for_symbol):
    """Record new calls, check open ones against fresh prices and reply to those that hit target or stop.

    Returns (track_record summary, calls still to be saved, reply queue, notified ids, [(symbol, text)] sent).
    Any failure leaves things to be retried next run; it never stops the site from publishing.
    """
    previous_record = prev_data.get("track_record")
    pending = [c for c in state.get("ledger_pending", []) if isinstance(c, dict) and "id" in c]
    pending += [c for _, c in calls if c["id"] not in {p["id"] for p in pending}]
    pending = pending[-tracking.PENDING_LIMIT:]
    queue = [i for i in state.get("reply_queue", []) if isinstance(i, str)]
    notified = [i for i in state.get("notified_outcomes", []) if isinstance(i, str)]

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    remote = data_remote(args)
    if not (args.ledger_dir or remote):
        return previous_record, pending, queue, notified, []
    directory = args.ledger_dir or str(Path(tempfile.mkdtemp()) / "ledger")
    git_token = os.environ.get("GITHUB_TOKEN") or None
    led = tracking.open_ledger(directory, remote, git_token)
    if led is None:
        return previous_record, pending, queue, notified, []

    try:
        for call in pending:
            led.add_call(call)
        resolved = led.resolve_open(ctx.get("completed_bars") or ctx.get("bars", {}), ctx["bench"])
        queue = queue + [o["id"] for _, o in resolved]
        led.save()
        stored = tracking.publish_ledger(directory, f"Ledger update {datetime.fromtimestamp(now_ts, timezone.utc):%Y-%m-%d %H:%M}", remote, git_token)
        print(f"Ledger: {len(calls)} new calls, {len(resolved)} resolved, {len(led.open_calls())} open" + ("" if stored else " (not saved yet)"))
    except Exception as err:
        print("Ledger update failed, will retry next run:", err)
        return previous_record, pending, queue, notified, []

    sent_lines = []
    if token and chat:
        def send(text, reply_to):
            return send_formatted(token, chat, text, reply_to)[0]
        sent, queue, texts = tracking.send_replies(
            queue, led, notified, send, lambda c: link_for_symbol(c["symbol"]))
        notified = (notified + sent)[-tracking.NOTIFIED_LIMIT:]
        sent_lines = [(led.calls[i]["symbol"], t) for i, t in zip(sent, texts)]
        if sent:
            print(f"Replied to {len(sent)} calls that reached target or stop")
    else:
        queue = []
    if stored:
        pending = []
    summary = ledger.summarise(led, now_ts)
    if repo:
        summary["data_url"] = f"https://github.com/{repo}/tree/data"
    return summary, pending, queue, notified, sent_lines


def run(args):
    now = datetime.now(timezone.utc)
    today = now.date()
    config = json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))
    member_path = ROOT / "config" / "membership.json"
    member_dates = json.loads(member_path.read_text(encoding="utf-8")) if member_path.exists() else {}
    cost_path = ROOT / "config" / "costs.json"
    cost_overrides = json.loads(cost_path.read_text(encoding="utf-8")) if cost_path.exists() else {}
    alert_path = ROOT / "config" / "alerts.json"
    alert_cfg = json.loads(alert_path.read_text(encoding="utf-8")) if alert_path.exists() else {}
    prev_data = load_previous(args.prev, "data.json")
    state = load_previous(args.prev, "state.json")
    memory_dir, memory_remote = open_alert_memory(args)
    stored_memory = alert_memory.read(memory_dir) if memory_dir else None
    state, from_memory = alert_memory.restore(state, stored_memory)
    if memory_dir:
        print("Sent-alert memory: " + ("restored from the data branch" if from_memory else "none stored yet" if not stored_memory else "older than the published state, using the published state"))

    config["stocks"], sync_state, synced = universe_sync.sync(now, state.get("universe_sync"), config["stocks"])
    registry = discover.discover(state, today)
    universe = build_universe(config, registry, args.limit)
    print(f"{len(universe)} stocks ({sum(1 for s in universe if s.get('new'))} new listings)")

    in_bases = [s["symbol"][:-3] for s in universe if s["symbol"].endswith(".NS")]
    delivery = exchange.sync_delivery(state.get("delivery", {}), today, in_bases)
    deals = exchange.summarise_deals(exchange.fetch_deals(), in_bases)

    bench = {}
    for market, symbol in config["benchmarks"].items():
        try:
            chart = fetch.fetch_chart(symbol, "5y", 100)
            bench[market] = dict(zip(chart["bars"]["d"], chart["bars"]["c"]))
        except fetch.FetchError as err:
            print("benchmark failed:", err)

    repo_name = os.environ.get("GITHUB_REPOSITORY", "")
    names = {s["symbol"]: s["name"] for s in universe}
    names.update({s["symbol"]: s["name"] for s in ((state.get("wide_universe") or {}).get("list") or []) if s.get("market") == "IN"})
    news_index = news_sources.NameIndex(names)
    try:                                         # every provider is isolated: one being down never stops the others, and the archive keeps earlier items
        raw_items, provider_status = news_sources.collect(now, state.get("news_providers"))
        mapped, market_items = news_sources.map_items(raw_items, news_index)
        fresh_mapped = [i for rows in mapped.values() for i in rows] + market_items
    except Exception as err:                     # nothing from the news layer may stop the site from publishing
        print("News providers failed:", err)
        provider_status, fresh_mapped = {}, []
    news_archive = news_sources.merge_archive(state.get("news_archive"), [news_sources.compact(i) for i in fresh_mapped], now)
    news_pool, news_market = {}, []
    for item in news_archive:
        (news_pool.setdefault(item["symbol"], []).append(item) if item.get("symbol") else news_market.append(item))
    ai_scores, ai_meta = news_ai.load_scores(repo_name, load_previous(args.prev, "news_ai.json"))
    ai_meta = {**(ai_meta or {}), "status": news_ai.load_status(repo_name)}
    print(f"News: {len(news_archive)} items kept, {len(news_pool)} stocks with news, {len(ai_scores)} AI scores, providers: "
          + ", ".join(f"{k} {'ok' if v['ok'] else 'down'}" for k, v in provider_status.items()))
    ctx = {"now": now, "today": today, "now_ts": int(now.timestamp()), "delivery": delivery, "deals": deals, "bench": bench,
           "bars": {}, "news_breaker": Breaker(NEWS_FAILURE_LIMIT), "costs": cost_overrides, "membership": member_dates,
           "news_pool": news_pool, "news_ai": ai_scores}

    def safe(entry):
        try:
            return analyse(entry, ctx)
        except fetch.FetchError as err:
            return {"symbol": entry["symbol"], "error": str(err), "new": bool(entry.get("new"))}

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(safe, universe))
    records = sorted((x for x in results if "error" not in x), key=lambda x: x["symbol"])
    errors = [x for x in results if "error" in x]
    print(f"{len(records)} analysed, {len(errors)} failed")
    if not records or len(errors) / len(results) > MAX_FAILURE_SHARE:
        print("Too many failures, refusing to publish a broken data set", file=sys.stderr)
        return 1

    previous = {s["symbol"]: s for s in prev_data.get("stocks", [])}
    carried, errors = carry_forward(errors, previous, today)
    if carried:
        print(f"{len(carried)} stocks kept from the previous run after a failed load: {', '.join(c['symbol'] for c in carried)}")
    records = sorted(records + carried, key=lambda x: x["symbol"])

    fund_cache = fill_fundamentals(records, state, ctx["now_ts"], fetch.YahooSession)
    for rec in records:
        rec["fundamentals_at"] = (fund_cache.get(rec["symbol"]) or {}).get("ts")
    statements_cache = statements.sync(records, state.get("statements"), ctx["now_ts"], fetch.YahooSession)
    news.keep_stock_specific(records)
    india_bases = [x["symbol"][:-3] for x in records if x["symbol"].endswith(".NS")]
    closes = exchange.sync_closes(state.get("eod_close"), today, india_bases)
    quality, accuracy = verify.cross_check(records, ctx["bars"], closes)
    for rec in records:
        rec["quality"] = quality.get(rec["symbol"])
    event_cache = event_news.sync(records, state.get("event_news"), now, breaker=Breaker(NEWS_FAILURE_LIMIT))
    official_events = official.fetch_official(now, {r["symbol"][:-3] for r in records if r["symbol"].endswith(".NS")}, state.get("official"))
    news_events = {s: v.get("events", []) for s, v in event_cache["stocks"].items()}
    events_data = events.build(records, today.isoformat(), news_events, official_events)
    add_lists(records)
    raw_index = {}
    overview = market_overview(config, now, raw_index)
    info = {x["symbol"]: {"market": x["market"], "sector": x["sector"]} for x in records if not x.get("new") and x["sector"] != "Other"}
    conditions = market_view.analyse(config.get("regime"), raw_index, ctx["bars"], info)
    sector_moves = {s["sector"]: s["d1"] for s in ((conditions.get("IN") or {}).get("sectors") or []) if isinstance(s.get("d1"), (int, float))}
    for rec in records:
        apply_news_context(rec, sector_moves)
    ipos = {}
    india, india_ok, india_at, ipo_cache = ipo_gmp.fetch_india(now, state.get("ipo_gmp"), fetch_news=news.fetch_news)
    ipos.update({"india": india, "india_ok": india_ok,
                 "india_source": {"name": "Investorgain", "url": ipo_gmp.URL, "fetched_at": india_at}})
    print(f"India IPOs: {len(india)} rows ({'fresh' if india_ok else 'unavailable or old'})")

    first_run = not prev_data
    watch = alerts.watched_symbols(alert_cfg.get("symbols", []), {x["symbol"] for x in records})
    watch = verify.trusted(watch, quality)     # no alerts on prices the official source disputes
    lagging = {r["symbol"] for r in records if r.get("series_lag")}
    watch = [s for s in watch if s not in lagging]
    live_feed = nse_live.fetch(now, state.get("nse_live"))      # the NSE's own live prices for the biggest movers: a second source for live prices
    live_prices = nse_live.usable(live_feed)
    live_check = nse_live.check_records(records, live_prices, live_feed.get("as_of"))
    live_mismatch = {r["symbol"] for r in records if (r.get("live_check") or {}).get("status") == "mismatch"}
    watch = [s for s in watch if s not in live_mismatch]
    learned = learning.load(os.environ.get("GITHUB_REPOSITORY", ""), load_previous(args.prev, "learning.json"), fetch.http_get)
    for rec in records:
        rec["outlook"] = learning.outlook(rec, learned)       # what happened after situations like today's, with its range and whether it beat the base rate on later data
    for rec in records:                                    # where each group of figures comes from, when it was read, and whether it is current
        rec["provenance"], rec["provenance_ok"] = provenance.build(rec, ctx["now_ts"])
    not_current = {r["symbol"] for r in records if not r["provenance_ok"]}
    watch = [s for s in watch if s not in not_current]
    chart_failures = len(carried) + len(errors)
    news_errors = sum(1 for r in records if (r.get("news") or {}).get("error"))
    fresh_fundamentals = sum(1 for r in records if isinstance(r.get("fundamentals_at"), (int, float)) and ctx["now_ts"] - r["fundamentals_at"] <= 3 * 86400)
    health, quarantined = data_learning.observe(state.get("data_health"), now, records, {
        "Yahoo price charts": (chart_failures <= max(2, 0.05 * len(records)), f"{chart_failures} of {len(records)} stocks failed to load"),
        "NSE end-of-day file": (bool(closes) and max(closes) >= fetch.expected_session(ctx["now_ts"] - 3600), f"newest session {max(closes) if closes else 'none'}"),
        "NSE live prices": (bool(live_feed.get("ok")), live_feed.get("error") or "no usable snapshot"),
        "Yahoo fundamentals": (fresh_fundamentals >= 0.9 * len(records), f"{fresh_fundamentals} of {len(records)} read in the last 3 days"),
        "Headline search": (news_errors <= 0.5 * len(records), f"{news_errors} of {len(records)} searches failed"),
        "Learned table": (bool(learned) and learning_age_ok(learned, now), "the weekly learning table is missing or old")})
    for rec in records:
        if rec["symbol"] in quarantined:
            rec["quarantine"] = quarantined[rec["symbol"]]
    watch = [s for s in watch if s not in quarantined]     # nor on a price series that lacks the newest session: its reading is a session old and would flip back later
    news_on = bool(alert_cfg.get("news", True))     # headlines in the alerts; no tone is ever worked out from them
    sides = {s: dict(v) for s, v in state.get("alert_sides", {}).items() if isinstance(v, dict)}
    items = []
    now_ts = int(now.timestamp())
    news_history = {s: list(v) for s, v in (state.get("news_alert_history") or {}).items() if isinstance(v, list)}
    # Every listed stock: the wide universe, live quotes in batches, factual mover events, and each stock's own headlines in a rotating slice.
    curated = {x["symbol"] for x in records}
    wide_list, wide_cache = wide.load_universe(state.get("wide_universe"), now, curated)
    market_of = {x["symbol"]: x["market"] for x in records}
    market_of.update({s["symbol"]: s["market"] for s in wide_list})
    quote_session = fetch.YahooSession()
    quotes = wide.fetch_quotes(quote_session, sorted(market_of)) if quote_session.start() else {}
    open_now = wide.open_markets(quotes, market_of)
    # a stock listed less than a year ago has no 52-week range, only its life so far: no 52-week alerts for it
    young = {s["symbol"] for s in wide_list if s.get("listed") and (today - date.fromisoformat(s["listed"])).days < 365}
    young |= {x["symbol"] for x in records if x.get("new") or (x.get("bars") is not None and x["bars"] < 252)}
    disputed = nse_live.disputed(quotes, live_prices)
    if disputed:
        print(f"NSE live prices disagree by more than 3% with Yahoo for {len(disputed)} stocks: {', '.join(sorted(disputed)[:10])}; no mover alerts for them")
    mover_events = wide.mover_events({s: q for s, q in quotes.items() if s not in disputed}, market_of, open_now, young)
    ipo_levels = {}                                # recently listed stocks and their listing-day range
    for x in records:
        lv = wide.ipo_levels(ctx["completed_bars"].get(x["symbol"]) if ctx.get("completed_bars") else ctx["bars"].get(x["symbol"]), x.get("listed"), today) if x.get("listed") else None
        if lv:
            ipo_levels[x["symbol"]] = lv
    mover_events = sorted(mover_events + wide.ipo_events(ipo_levels, quotes, market_of, open_now), key=lambda e: -e["magnitude"])
    wide_batch, wide_cursor = wide.pick_news_batch(wide_list, state.get("wide_cursor", 0), [e["symbol"] for e in mover_events])
    wide_found = wide.wide_news(wide_batch, now, ctx["news_breaker"])
    print(f"Wide coverage: {len(market_of)} stocks, {len(quotes)} quotes, {len(mover_events)} mover events, news looked up for {len(wide_batch)} ({len(wide_found)} with fresh headlines)")
    current_all = {x["symbol"]: x for x in records}
    current_all.update(wide_found)
    lines, seen = alerts.build_messages(previous, current_all, list(watch) + sorted(wide_found),
                                        state.get("seen_alerts", []), first_run, news_on, sides, items, news_history, now_ts)
    # Block deals come from the NSE's live feed and cover every NSE stock, tracked or not.
    live_deals = deals_live.fetch_block_deals(now, state.get("live_deals"))
    names = {s[0]: s[1] for s in config["stocks"]}
    names.update({e["symbol"]: e["name"] for e in registry})
    names.update({x["symbol"]: x["name"] for x in records})
    if any(d["symbol"] + ".NS" not in names for d in live_deals["deals"]):
        try:                                   # a deal in a stock the app does not track: look its name up once, from the NSE's own list
            names.update(discover.nse_company_names(fetch.http_get(discover.NSE_LIST_URL).decode("utf-8", "replace")))
        except fetch.FetchError:
            pass
    news_dash = news_dashboard(records, news_pool, news_market, names, sector_moves, provider_status, ai_scores, ai_meta, news_archive, now)
    deal_lines, deal_items, deal_seen = alerts.deal_alerts(live_deals["deals"], state.get("deal_seen"), names, now_ts, deals_live.today_ist(now))
    lines, items = alerts.merge_deals(lines, items, deal_lines, deal_items)
    wide_names = {s["symbol"]: s["name"] for s in wide_list}
    mover_lines, mover_items, mover_seen = alerts.mover_alerts(mover_events, {**wide_names, **names}, state.get("mover_seen"), now_ts, wide.MOVERS_PER_RUN)
    lines, items = alerts.insert_after(lines, items, ("signal", "deal"), mover_lines, mover_items)
    # Index alerts and the scheduled briefs (pre-open, post-close, flows, US close)
    nse = dict(state.get("nse_sources") or {})
    indices_payload, nse["indices"] = sessions.Source("NSE all indices", sessions.ALL_INDICES).fetch(now, nse.get("indices"))
    indices = sessions.parse_indices(indices_payload)
    index_lines, index_items, index_seen = sessions.index_alerts(sessions.index_events(indices, (overview or {}).get("watch"), "IN" in open_now), state.get("index_seen"), now_ts)
    lines, items = alerts.insert_after(lines, items, ("brief",), index_lines, index_items)
    briefs_sent = dict(state.get("briefs_sent") or {})
    today_ist = now.astimezone(sessions.IST).strftime("%Y-%m-%d")
    today_label = now.astimezone(sessions.IST).strftime("%d-%b-%Y")
    todays = [f"{e['name']} ({e['type'].replace('_', ' ')})" for e in events_data["items"] if e["date"] == today_ist and e["market"] == "IN" and e.get("verification") == "CONFIRMED"]
    cues = [(w["name"], w["change_pct"], w.get("as_of")) for w in (overview or {}).get("watch", []) if w.get("symbol") in ("^GSPC", "^IXIC", "^DJI", "^VIX") and w.get("change_pct") is not None]
    brief_lines, brief_items = [], []
    for window in sessions.due_windows(now, briefs_sent):
        flows = {}
        if window in ("in_preopen", "in_postclose", "in_flows"):
            payload, nse["flows"] = sessions.Source("NSE institutional flows", sessions.FII_DII).fetch(now, nse.get("flows"))
            flows = sessions.parse_flows(payload)
        body = []
        if window == "in_preopen":
            payload, nse["preopen"] = sessions.Source("NSE pre-open", sessions.PREOPEN).fetch(now, nse.get("preopen"))
            body = sessions.preopen_brief(sessions.parse_preopen(payload) if payload else None, cues, flows, todays, wide.stock_watch(ipo_levels, quotes))
        elif window == "in_postclose" and "IN" not in open_now:
            up, down, extremes = wide.top_moves(quotes, market_of, "IN")
            payload, nse["deals"] = sessions.Source("NSE large deals", sessions.LARGE_DEALS).fetch(now, nse.get("deals"))
            body = sessions.postclose_brief(indices, up, down, extremes, flows, today_label, sessions.parse_deals(payload, today_label), todays) if indices else []
        elif window == "in_flows" and flows.get("date") == today_label:
            body = [f"Net flows today: FII/FPI {flows.get('FII/FPI', 0):+,.0f} cr, DII {flows.get('DII', 0):+,.0f} cr"]
        if body:
            item = sessions.brief_item(window, body, now_ts)
            brief_items.append(item)
            brief_lines.append(f"{item['name']}: " + " | ".join(body)[:300])
            briefs_sent[window] = today_ist
    lines, items = alerts.insert_after(lines, items, (), brief_lines, brief_items)
    by_symbol = {x["symbol"]: x for x in records}
    for item in items:                     # a reading alert carries what the rule has done on this stock, so it is never read as a promise
        rec = by_symbol.get(item.get("symbol")) if item.get("kind") == "signal" else None
        if rec:
            item["evidence"] = evidence.evidence_text(rec.get("evidence"), item.get("horizon"))
            item["flags"] = rec.get("flags") or []
    alert_log, added = alerts.update_log(alerts.drop_irrelevant(state.get("alert_log", []), by_symbol), lines, now_ts, [i["symbol"] for i in items])
    print(f"Alerts: {len(added)} new ({len(deal_lines)} block deals), {len(watch)} stocks watched")
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    site_url = args.prev if args.prev.startswith("http") else ""

    def link_for_symbol(symbol, section="signals"):
        return alerts.stock_link(site_url, symbol, section) if site_url else None

    by_record = {x["symbol"]: x for x in records}

    def link_of(item):
        symbol = item.get("symbol")
        if not symbol or symbol not in market_of:
            return None
        return link_for_symbol(symbol, "news" if item["kind"] == "news" and symbol in by_symbol else "signals")

    # corporate actions, circuits, surveillance, gaps, surges and crashes: records for the Announcements tab, and Telegram items for the ones not alerted before
    news_items = [item for rows in news_pool.values() for item in rows]
    action_records, action_memory = actions_run.collect(now, now_ts, nse, news_items, quotes, market_of, "IN" in open_now, mover_events, names, state, alert_cfg.get("actions"))
    previous_archive = (load_previous(args.prev, "announcements.json") or {}).get("items") or []
    action_archive = actions.merge_archive(previous_archive, action_records, now_ts)
    action_items, action_seen = feed_items.action_alert_items(action_records, state.get("action_seen"), now_ts, baseline="action_seen" not in state)
    print(f"Announcements: {len(action_records)} records this run, {len(action_archive)} kept, {len(action_items)} to alert")

    if alert_cfg.get("scheduled_feeds", True):
        # scheduled feeds: each kind of alert goes out on its own cadence (engine/feeds.py); the app's alert log above is unchanged
        extra = []
        filings, filing_seen = feed_items.filing_entries(news_dash["stories"], state.get("filing_seen"), now_ts, names=names)
        extra += [] if first_run else filings
        breaches, vol_seen = feed_items.volatility_breach_items(records, quotes, "IN" in open_now, state.get("vol_seen"), now_ts, today_ist, skip=set(disputed) | set(lagging))
        extra += [] if first_run else breaches
        regime, regime_label = feed_items.regime_entry(conditions, state.get("regime_seen"))
        extra += [regime] if regime else []
        extra += action_items

        def bulk_payload():
            payload, nse["deals"] = sessions.Source("NSE large deals", sessions.LARGE_DEALS).fetch(now, nse.get("deals"))
            return payload

        sources = {"indices": indices, "india_open": "IN" in open_now, "watch": (overview or {}).get("watch"), "sectors": (conditions.get("IN") or {}).get("sectors"),
                   "news_dashboard": news_dash, "ipos": ipos.get("india") if ipos.get("india_ok") else [], "events": events_data["items"], "track_record": prev_data.get("track_record"),
                   "learning": prev_data.get("learning"), "health": prev_data.get("data_health"), "bulk_payload": bulk_payload, "digest_seen": dict(state.get("digest_seen") or {}), "today_label": today_label, "names": names, "actions_archive": action_archive}
        send_one = (lambda text, reply_to=None: send_formatted(token, chat, text, reply_to)) if token and chat else None
        feed_state, calls, _sent = feed_run.dispatch(items + extra, state, now, now_ts, feeds.settings(alert_cfg), sources, by_record, send_one, link_of, today_ist)
        feed_state["digest_seen"] = sources["digest_seen"]
        if not (token and chat) and lines:
            print("New alerts are in the app. Telegram is not set up (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).")
    else:                                                 # the earlier behaviour: one digest per run (alert_cfg "scheduled_feeds": false)
        feed_state, filing_seen, regime_label, vol_seen = {}, state.get("filing_seen"), state.get("regime_seen"), state.get("vol_seen")
        action_seen = state.get("action_seen")
        calls = tracking.make_calls(items, by_record, now_ts)
        if lines and token and chat:
            links = [link_for_symbol(i["symbol"], "news" if i["kind"] == "news" and i["symbol"] in by_symbol else "signals") if i["symbol"] in market_of else None for i in items]
            for message, start, end in digest.render(items, links, now_ts):
                ok, message_id = send_formatted(token, chat, message)
                print(f"Telegram alert {'sent' if ok else 'failed'} ({end - start} alerts)")
                if ok:
                    tracking.attach_message(calls, end, message_id, start)
        elif lines:
            print("New alerts are in the app. Telegram is not set up (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).")
    health_seen = send_health_note(state.get("health_seen"), prev_data.get("data_health"), now_ts)

    track_record, pending, queue, notified, outcome_lines = track(args, state, prev_data, calls, ctx, now_ts, token, chat, link_for_symbol)
    if outcome_lines:
        alert_log, _ = alerts.update_log(alert_log, [text for _, text in outcome_lines], now_ts, [sym for sym, _ in outcome_lines])
    for rec in records:                    # Yahoo's indicated annual dividend, as an independent check on the amounts worked out from the payments
        rec["dividend_check"] = dividends.cross_check(rec.get("dividend"), rec.get("price"), (quotes.get(rec["symbol"]) or {}).get("dividend_rate"))
    analysis_index = catalog.update(now, state.get("analysis_index"), wide_list, quotes, analyse, ctx, args.prev, load_previous, Path(args.out), lists_fn=add_lists, curated_records=records,
                                    fundamentals_fn=lambda symbol: fundamentals.fetch_fundamentals(quote_session, symbol),
                                    statements_fn=lambda symbol: statements.fetch_statements(quote_session, symbol, ctx["now_ts"]),
                                    outlook_fn=lambda record: (apply_news_context(record, sector_moves), learning.outlook(record, learned))[1])
    health = data_learning.fold_sources(health, now, {"NSE live block deals": (bool(live_deals.get("ok")), live_deals.get("error") or ""),
                                                         "NSE official events": (bool((official_events or {}).get("ok")), (official_events or {}).get("error") or "")})
    status = status_block(config, records, errors, carried, overview, conditions, ipos, delivery, track_record, pending, token, chat, accuracy, official_events, live_deals, live_feed, live_check)
    data = {"version": 1, "generated_at": now.isoformat(timespec="seconds"), "market": overview, "conditions": conditions,
            "status": status, "accuracy": accuracy, "live_check": live_check, "learning": learning.summary(learned), "news_intel": news_dash, "data_health": data_learning.summary(health, quarantined), "evidence": evidence.summarise(records), "backtest_method": {"costs": costs.describe(cost_overrides), "notes": BACKTEST_NOTES}, "events": events_data, "ipos": ipos,
            "stocks": [catalog.lite(x) for x in records], "errors": [{"symbol": e["symbol"], "error": e["error"]} for e in errors],
            "alerts": alert_log, "track_record": track_record,
            "exchange_data": {"delivery_dates": sorted(delivery)[-3:], "note": "NSE delivery data and bulk/block deals. The exchange order book (bid/ask depth) is not published for free."}}
    new_state = {"seen_alerts": seen, "delivery": delivery, "new_listings": registry,
                 "fundamentals": fund_cache, "ipo_gmp": ipo_cache, "alert_log": alert_log,
                 "alert_sides": sides, **feed_state, "filing_seen": filing_seen, "regime_seen": regime_label, "health_seen": health_seen, "vol_seen": vol_seen, "action_seen": action_seen, "surv_state": action_memory["surv_state"], "ban_state": action_memory["ban_state"], "universe_sync": sync_state, "analysis_index": analysis_index, "wide_universe": wide_cache, "wide_cursor": wide_cursor, "mover_seen": mover_seen, "index_seen": index_seen,
                 "briefs_sent": {k: v for k, v in briefs_sent.items() if v == today_ist}, "nse_sources": nse, "news_alert_history": {s: v for s, v in news_history.items() if v}, "deal_seen": deal_seen,
                 "live_deals": {k: v for k, v in live_deals.items() if k != "deals"}, "eod_close": closes, "nse_live": {k: v for k, v in live_feed.items() if k != "prices"}, "statements": statements_cache, "news_providers": provider_status, "news_archive": news_archive, "data_health": health, "event_news": event_cache, "official": official_events, "ledger_pending": pending, "reply_queue": queue, "notified_outcomes": notified}

    save_alert_memory(memory_dir, memory_remote, new_state, now)      # before the checks and the deploy: a failed publish must not make the next run send these again
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    build_id = manifest.new_build_id(time.time())
    data["build_id"] = build_id
    (out / "data.json").write_text(json.dumps(data, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    (out / "state.json").write_text(json.dumps(new_state, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    announcements = {"v": 1, "generated_at": now.isoformat(timespec="seconds"), "items": action_archive, "counts": actions.counts(action_archive),
                     "types": {k: {"label": v[0], "group": v[1]} for k, v in actions.TYPES.items()}, "sources": actions_run.source_status(nse)}
    (out / "announcements.json").write_text(json.dumps(announcements, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    if ai_scores:                                # the scores the build used, kept so a failed read of the data branch next run still has them
        (out / "news_ai.json").write_text(json.dumps({"v": 1, "model": (ai_meta or {}).get("model"), "generated_at": (ai_meta or {}).get("generated_at"), "scores": ai_scores},
                                                     allow_nan=False, separators=(",", ":")), encoding="utf-8")
    if learned:                                  # kept in the published site so a failed read of the data branch next run still has the latest table
        (out / "learning.json").write_text(json.dumps(learned, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    manifest.write(out, build_id, data.get("generated_at"))             # last: it lists every file of this build
    print(f"Wrote {out / 'data.json'} ({(out / 'data.json').stat().st_size // 1024} KB)")
    return 0


def send_health_note(seen, health, now_ts):
    """Tell the operator, in a separate private chat (TELEGRAM_ADMIN_CHAT_ID), when data sources are degraded or stocks are paused, and when that clears.
    Sent only when the picture changes, never to the public channel. Returns the state to remember. Without the secrets it does nothing."""
    token, admin = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
    text = feed_items.health_text(health)
    digest_now = hashlib.sha1((text or "ok").encode()).hexdigest()[:12]
    seen = seen if isinstance(seen, dict) else {}
    if not (token and admin) or health is None or seen.get("hash") == digest_now:
        return seen
    message = text or "Stock Signals data health: all sources are working again."
    ok = alerts.send_telegram(token, admin, message)
    print("Data health note", "sent to the operator chat" if ok else "could not be sent")
    return {"hash": digest_now, "ts": int(now_ts)} if ok else seen


def notify_failure():
    """Tell the operator that a run failed (called from the workflow when a step fails). Returns 0 either way: the notice must not hide the real failure."""
    token, admin = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
    if not (token and admin):
        print("No TELEGRAM_ADMIN_CHAT_ID: the failure is not announced.")
        return 0
    run = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    ok = alerts.send_telegram(token, admin, f"Stock Signals: the update run failed and nothing was published. The site stays on the last good build.\n{run}")
    print("Failure notice", "sent" if ok else "could not be sent")
    return 0


def send_test_alert():
    """Send one test message to Telegram. Returns 0 only if it was delivered."""
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        print("Telegram is not set up. Add the TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID secrets.")
        return 1
    ok = alerts.send_telegram(token, chat, "Test alert from Stock Signals. If you can read this, alerts are working.")
    print("Telegram test alert sent" if ok else "Telegram test alert FAILED")
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-alert", action="store_true", help="send a test message to Telegram and exit")
    parser.add_argument("--notify-failure", action="store_true", help="tell the operator chat that a run failed, and exit")
    parser.add_argument("--out", default="site")
    parser.add_argument("--prev", default=os.environ.get("SITE_URL", ""), help="URL or folder holding the previous data.json/state.json")
    parser.add_argument("--ledger-dir", default="", help="keep the track-record ledger in this folder (no git); for testing")
    parser.add_argument("--ledger-remote", default="", help="git remote holding the data branch (default: this GitHub repository)")
    parser.add_argument("--limit", type=int, default=0, help="analyse only N stocks (testing)")
    args = parser.parse_args(argv)
    return notify_failure() if args.notify_failure else send_test_alert() if args.test_alert else run(args)


if __name__ == "__main__":
    sys.exit(main())

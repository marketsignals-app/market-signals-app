import re
import unittest
from datetime import date, datetime, timedelta, timezone

from engine import alerts, digest_feeds, feed_items as fi, feed_run, feeds

IST = timezone(timedelta(hours=5, minutes=30))
TABLE = feeds.settings()
NOW = datetime(2026, 11, 23, 10, 20, tzinfo=IST)          # a Monday, inside every market feed's window
TS = int(NOW.timestamp())


def signal(symbol="AXISBANK.NS", side="buy", horizon="short", label="Buy"):
    return {"kind": "signal", "symbol": symbol, "name": symbol.split(".")[0], "horizon": horizon, "side": side, "announced": "hold", "label": label, "score": 60, "price": 100.0,
            "currency": "INR", "levels": None, "reasons": [], "evidence": None, "flags": []}


def mover(symbol="DOLATALGO.NS"):
    return {"kind": "mover", "symbol": symbol, "name": symbol.split(".")[0], "tags": ["+8.4%"], "price": 69.41, "currency": "INR", "small": False, "move": 8.4}


class FakeTelegram:
    def __init__(self, fail_after=None, refuse_replies=False):
        self.sent, self.replies, self.fail_after, self.refuse_replies = [], [], fail_after, refuse_replies

    def __call__(self, text, reply_to=None):
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            return False, None
        if reply_to and self.refuse_replies:
            return False, None
        self.sent.append(text)
        self.replies.append(reply_to)
        return True, 1000 + len(self.sent)


def dispatch(items, state, send, records=None, now=NOW, src=None):
    return feed_run.dispatch(items, state, now, int(now.timestamp()), TABLE, src or {}, records or {}, send, lambda i: None, "2026-11-23")


class HashtagTests(unittest.TestCase):
    def test_stock_and_word_tags_are_valid_telegram_hashtags(self):
        self.assertEqual(fi.symbol_tag("AXISBANK.NS"), "#AXISBANK")
        self.assertEqual(fi.symbol_tag("M&M.NS"), "#M_M")
        self.assertEqual(fi.symbol_tag("BAJAJ-AUTO.NS"), "#BAJAJ_AUTO")
        self.assertEqual(fi.symbol_tag("360ONE.NS"), "#360ONE")
        self.assertEqual(fi.symbol_tag("123.NS"), "#N123", "a hashtag cannot be digits only")
        self.assertEqual(fi.word_tag("Pharma and Health"), "#PharmaAndHealth")
        self.assertEqual(fi.tags("#A", "#A", "Bank Nifty", None), ["#A", "#BankNifty"])
        self.assertEqual(fi.symbol_tag(""), "")


class RenderTests(unittest.TestCase):
    def render(self, items, label="Feed", tags=("#Feed",)):
        return digest_feeds.render_feed(items, [None] * len(items), TS, label, tags)

    def test_readings_are_a_numbered_entry_with_bullets_and_the_stock_hashtags(self):
        text = self.render([signal()])[0][0]
        self.assertNotIn("<pre>", text, "small phones wrap tables: alerts are lists")
        self.assertIn("1. <b>AXISBANK</b>", text)
        self.assertIn("Score: +60 · Price: 100.00", text)
        self.assertRegex(text, r"Ref: .* · Risk: ")
        self.assertRegex(text, r"#AXISBANK #Bullish #WeeksView")
        self.assertIn("Ref = nearest reference level", text)
        self.assertIn("SEBI-registered", text)

    def test_movers_are_entries_and_the_words_are_a_bullet(self):
        small = {**mover("B.NS"), "small": True, "tags": ["+8.4%", "volume 7.9x average"]}
        text = self.render([mover("A.NS"), small])[0][0]
        self.assertNotIn("<pre>", text)
        self.assertIn("2. <b>B</b>", text)
        self.assertIn("Move: +8.4% · Price: 69.41", text)
        self.assertIn("vol 7.9x; small stock", text)
        self.assertNotIn("B: vol", text, "the stock is the heading, so the bullet does not repeat it")
        self.assertIn("#A #Mover", text)

    def test_each_section_has_its_own_numbering_and_falling_movers_are_apart_from_rising(self):
        ipo = {**mover("MEESHO.NS"), "kind": "ipo", "tags": ["IPO breakout: above listing-day high 258.00"], "move": 0.4}
        down = {**mover("C.NS"), "move": -9.0, "tags": ["-9.0%"]}
        text = self.render([mover("A.NS"), down, ipo])[0][0]
        self.assertLess(text.index("RISING"), text.index("FALLING"))
        self.assertEqual(text.count("1. <b>"), 3, "numbering restarts in each section")
        self.assertIn("Level: 258.00", text)

    def test_a_feed_table_is_numbered_lines_with_its_source_and_hashtags(self):
        table = fi.indexes_table({"NIFTY 50": {"last": 25653.35, "pct": -0.57}, "INDIA VIX": {"last": 17.48, "pct": 0.94}}, NOW)
        text = self.render([table], "Indexes", table["tags"][:1])[0][0]
        self.assertNotIn("<pre>", text)
        self.assertIn("1. <b>Nifty 50</b> · 25,653.35 · -0.57%", text)
        self.assertIn("Source: NSE all-indices feed", text)
        self.assertIn("#Nifty50", text)

    def test_a_scheduled_brief_renders_as_a_heading_with_bullets(self):
        brief = {"kind": "brief", "symbol": "", "name": "India post-close brief", "window": "in_postclose", "lines": ["Nifty 50 closed at 25,366.40 (-1.68%)", "Advances 120, declines 380"], "ts": TS}
        text = self.render([brief])[0][0]
        self.assertIn("<b>India post-close brief</b>", text)
        self.assertIn("Nifty 50 closed at 25,366.40 (-1.68%)", text)

    def test_outside_text_is_escaped(self):
        item = {"kind": "news", "symbol": "A.NS", "name": "A <b>", "title": "x <script>alert(1)</script>", "source": "S&P", "link": "https://x.com/a", "age_min": 5}
        text = self.render([item])[0][0]
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)

    def test_every_message_stays_under_telegram_s_limit(self):
        many = [mover(f"S{i}.NS") for i in range(400)]
        messages = digest_feeds.render_feed(many, None, TS, "Movers", ["#Movers"])
        self.assertLessEqual(len(messages), 3)
        self.assertTrue(all(alerts.visible_length(m[0]) <= alerts.TELEGRAM_MAX_CHARS for m in messages))
        huge = [{**mover(f"S{i}.NS"), "tags": ["+8.0%", "volume 12.0x average", "at 52-week high"]} for i in range(900)]
        messages = digest_feeds.render_feed(huge, None, TS, "Movers", ["#Movers"], max_messages=2)
        self.assertIn("more", messages[-1][0], "what does not fit is counted, not silently dropped")

    def test_bulk_deals_show_the_client_as_published(self):
        rows = fi.bulk_deal_items({"BULK_DEALS_DATA": [{"date": "23-Nov-2026", "symbol": "ABC", "buySell": "BUY", "qty": "520000", "watp": "120.5", "clientName": "XYZ FUND"},
                                                       {"date": "22-Nov-2026", "symbol": "OLD", "buySell": "BUY", "qty": "1", "watp": "1"},
                                                       {"date": "23-Nov-2026", "symbol": "BAD", "buySell": "SELL", "qty": "x", "watp": "1"}]}, "23-Nov-2026")
        self.assertEqual([r["symbol"] for r in rows], ["ABC.NS"], "only today's valid deals")
        text = self.render(rows)[0][0]
        self.assertIn("Side: BUY · Qty: 5.2L · Price: 120.50", text)
        self.assertIn("Value: 6.3cr", text)
        self.assertIn("Xyz Fund", text)
        self.assertIn("#BulkDeal", text)


class MediaNewsOffTests(unittest.TestCase):
    def test_media_news_feeds_are_off_by_default_and_their_items_are_not_queued(self):
        self.assertNotIn("news", TABLE)
        self.assertNotIn("news_digest", TABLE)
        news = {"kind": "news", "symbol": "A.NS", "name": "A", "title": "Headline", "source": "Mint", "link": "https://example.com/x", "age_min": 5}
        state, _, _ = feed_run.dispatch([news], {"feeds_sent": {}, "feed_queue": []}, NOW, int(NOW.timestamp()), TABLE, {}, {}, None, lambda i: None, "2026-11-23")
        self.assertEqual(state["feed_queue"], [])
        self.assertIn("filings", TABLE, "official NSE and BSE filings stay")


class BuilderTests(unittest.TestCase):
    def test_indexes_commodities_and_sectors(self):
        self.assertIsNone(fi.indexes_table({}, NOW))
        watch = [{"name": "Crude oil", "kind": "commodity", "price": 83.27, "change_pct": -0.85, "as_of": "2026-11-17"}, {"name": "Nifty 50", "kind": "index", "price": 1, "change_pct": 1, "as_of": "x"}]
        table = fi.commodities_table(watch, NOW)
        self.assertEqual(len(table["rows"]), 1)
        self.assertIn("Crude oil 17 Nov STALE", table["notes"][0], "data from 6 days ago is marked stale")
        self.assertEqual(len(table["rows"][0]), 3, "no wide note column")
        sectors = [{"sector": s, "d1": d, "d5": 1.0, "n": 8} for s, d in (("IT", 1.2), ("Banks", 0.5), ("Metals", -0.7), ("Auto", -1.1), ("FMCG", 0.1))] + [{"sector": "Tiny", "d1": 9, "n": 1}]
        table = fi.sectors_table(sectors, NOW)
        self.assertNotIn("Tiny", " ".join(r[0] for r in table["rows"]), "a sector with fewer than 3 stocks is not ranked")
        self.assertEqual(table["rows"][0][0], "IT")
        self.assertEqual(table["more"][0]["header"], ["Sector", "Stocks"])

    def test_urgent_index_alert_and_volatility_text(self):
        entry = fi.index_alert_entry({"name": "INDIA VIX", "last": 21.6, "tags": ["above 20"]}, NOW)
        self.assertTrue(entry["urgent"])
        self.assertEqual(entry["title"], "VOLATILITY ALERT")
        self.assertIn("#Volatility", entry["tags"])

    def test_important_filings_are_official_high_impact_and_sent_once(self):
        story = {"kind": "nse", "symbol": "VIDEOIND.NS", "name": "Videocon", "title": "CIRP", "event": "insolvency", "event_label": "Insolvency or default", "impact": 93, "sentiment": -82,
                 "source": "NSE", "ts": TS, "link": "https://nsearchives.nseindia.in/x.pdf"}
        weak = {**story, "symbol": "B.NS", "impact": 30}
        media = {**story, "symbol": "C.NS", "kind": "media"}
        items, seen = fi.filing_entries([story, weak, media], {}, TS)
        self.assertEqual([i["symbol"] for i in items], ["VIDEOIND.NS"])
        again, _ = fi.filing_entries([story], seen, TS + 60)
        self.assertEqual(again, [])

    def test_upcoming_ipos_pick_open_closing_and_soon_opening_issues(self):
        today = date(2026, 11, 23)
        rows = [{"name": "Open", "open": "2026-11-19", "close": "2026-11-23"}, {"name": "Soon", "open": "2026-11-25", "close": "2026-11-27", "listing": "2026-12-02"},
                {"name": "Far", "open": "2026-12-20", "close": "2026-12-22"}, {"name": "Done", "open": "2026-11-01", "close": "2026-11-05", "listing": "2026-11-10"}]
        names = [i["heading"].split(" (")[0] for i in fi.upcoming_ipo_entries(rows, today)]
        self.assertEqual(names, ["Open", "Soon"])

    def test_regime_alert_only_on_a_change_and_never_on_the_first_run(self):
        conditions = {"IN": {"regime": {"label": "Mixed conditions", "score": 0, "checks": []}}}
        self.assertEqual(fi.regime_entry(conditions, None), (None, "Mixed conditions"))
        self.assertEqual(fi.regime_entry(conditions, "Mixed conditions"), (None, "Mixed conditions"))
        entry, label = fi.regime_entry(conditions, "Bullish conditions")
        self.assertEqual(label, "Mixed conditions")
        self.assertIn("changed to Mixed conditions", entry["heading"])

    def test_weekly_summary_says_when_samples_are_too_small(self):
        out = fi.weekly_entries({"overall": {"n": 3, "reliable": False, "target_pct": 33.3, "stop_pct": 33.3, "expired_pct": 33.3}, "open": 2, "void": 1, "min_sample": 30}, None, None)
        self.assertIn("too few", " ".join(out[0]["points"]))


class VolatilityBreachTests(unittest.TestCase):
    def record(self, symbol="A.NS", atr=10.0, **over):
        return {"symbol": symbol, "name": symbol.split(".")[0], "sector": "Banks", "indicators": {"atr": atr}, **over}

    def quote(self, price, change):
        return {"price": price, "change_pct": change, "state": "REGULAR"}

    def test_a_move_of_twice_the_average_range_is_a_breach_and_a_smaller_one_is_not(self):
        # previous close 1000, price 1025: a 25 rupee move on an ATR of 10 is 2.5x
        items, seen = fi.volatility_breach_items([self.record(), self.record("B.NS", atr=30.0)], {"A.NS": self.quote(1025.0, 2.5), "B.NS": self.quote(1025.0, 2.5)}, True, {}, TS, "2026-11-23")
        self.assertEqual([i["symbol"] for i in items], ["A.NS"])
        self.assertIn("2.5x", items[0]["points"][0])
        self.assertIn("#VolatilityBreach", items[0]["tags"])
        self.assertIn("#A", items[0]["tags"])

    def test_it_is_announced_once_a_day_and_again_only_when_the_multiple_grows(self):
        first, seen = fi.volatility_breach_items([self.record()], {"A.NS": self.quote(1025.0, 2.5)}, True, {}, TS, "2026-11-23")
        again, seen = fi.volatility_breach_items([self.record()], {"A.NS": self.quote(1026.0, 2.6)}, True, seen, TS + 900, "2026-11-23")
        bigger, seen = fi.volatility_breach_items([self.record()], {"A.NS": self.quote(1031.0, 3.1)}, True, seen, TS + 1800, "2026-11-23")
        tomorrow, _ = fi.volatility_breach_items([self.record()], {"A.NS": self.quote(1025.0, 2.5)}, True, seen, TS + 86400, "2026-11-24")
        self.assertEqual((len(first), len(again), len(bigger), len(tomorrow)), (1, 0, 1, 1))

    def test_a_downward_breach_is_reported_as_down(self):
        items, _ = fi.volatility_breach_items([self.record()], {"A.NS": self.quote(970.0, -3.0)}, True, {}, TS, "2026-11-23")
        self.assertIn("down", items[0]["points"][0])

    def test_untrusted_or_missing_data_and_a_closed_market_give_nothing(self):
        quotes = {"A.NS": self.quote(1025.0, 2.5)}
        for bad in ({"quarantine": {"x": 1}}, {"series_lag": True}, {"provenance_ok": False}, {"flags": ["thin"]}, {"carried": True}):
            self.assertEqual(fi.volatility_breach_items([self.record(**bad)], quotes, True, {}, TS, "2026-11-23")[0], [], bad)
        self.assertEqual(fi.volatility_breach_items([self.record(symbol="A.NS")], quotes, True, {}, TS, "2026-11-23", skip={"A.NS"})[0], [])
        self.assertEqual(fi.volatility_breach_items([self.record()], quotes, False, {}, TS, "2026-11-23")[0], [], "market closed")
        self.assertEqual(fi.volatility_breach_items([self.record(atr=None)], quotes, True, {}, TS, "2026-11-23")[0], [])
        self.assertEqual(fi.volatility_breach_items([self.record(atr=0)], quotes, True, {}, TS, "2026-11-23")[0], [])
        self.assertEqual(fi.volatility_breach_items([self.record()], {"A.NS": {"price": 1025.0, "change_pct": 2.5, "state": "CLOSED"}}, True, {}, TS, "2026-11-23")[0], [])
        self.assertEqual(fi.volatility_breach_items([self.record()], {}, True, {}, TS, "2026-11-23")[0], [])

    def test_the_strongest_come_first_and_the_list_is_capped(self):
        records = [self.record(f"S{i}.NS") for i in range(12)]
        quotes = {f"S{i}.NS": self.quote(1000 + 25 + i * 3, (25 + i * 3) / 10) for i in range(12)}
        items, _ = fi.volatility_breach_items(records, quotes, True, {}, TS, "2026-11-23", limit=8)
        self.assertEqual(len(items), 8)
        self.assertEqual(items[0]["symbol"], "S11.NS")

    def test_the_feed_is_scheduled_and_renders_as_a_numbered_entry_with_hashtags(self):
        self.assertEqual(feeds.settings()["volatility"]["every"], 15)
        items, _ = fi.volatility_breach_items([self.record()], {"A.NS": self.quote(1025.0, 2.5)}, True, {}, TS, "2026-11-23")
        text = digest_feeds.render_feed(items, [None], TS, "Volatility breaches", ["#VolatilityBreaches"])[0][0]
        self.assertIn("Move: +2.5% · x Range: 2.5x", text)
        self.assertIn("Price: 1,025.0 · Prev: 1,000.0", text)
        self.assertIn("#VolatilityBreach", text)
        self.assertEqual(feeds.feed_for(items[0]), "volatility")


class BreachMessageTests(unittest.TestCase):
    def breach(self, symbol="A.NS"):
        records = [{"symbol": symbol, "name": symbol.split(".")[0], "sector": "Banks", "indicators": {"atr": 10.0}}]
        items, _ = fi.volatility_breach_items(records, {symbol: {"price": 1025.0, "change_pct": 2.5, "state": "REGULAR"}}, True, {}, TS, "2026-11-23")
        return items[0]

    def started(self, **extra):
        return {"feeds_sent": {"volatility": feeds.slot_of(TABLE["volatility"], NOW)}, "feed_queue": [], **extra}

    def test_a_breach_is_sent_on_its_own_at_once_not_held_for_the_slot(self):
        send = FakeTelegram()
        state, _, _ = dispatch([self.breach()], self.started(), send)
        self.assertEqual(len(send.sent), 1)
        self.assertIn("Volatility breach", send.sent[0])
        self.assertEqual(send.replies, [None], "no earlier reading alert, so a normal message")
        self.assertEqual(state["feed_queue"], [])

    def test_it_replies_under_the_reading_alert_of_the_stock_and_names_it(self):
        send = FakeTelegram()
        announced = {"A.NS": {"id": 777, "ts": TS - 86400, "side": "buy", "horizon": "short", "date": "2026-11-22"}}
        dispatch([self.breach()], self.started(announced=announced), send)
        self.assertEqual(send.replies, [777])
        self.assertIn("Earlier reading alert: bullish", send.sent[0])

    def test_an_old_reading_alert_is_not_replied_to(self):
        send = FakeTelegram()
        announced = {"A.NS": {"id": 777, "ts": TS - 60 * 86400, "side": "buy", "horizon": "short", "date": "2026-09-01"}}
        state, _, _ = dispatch([self.breach()], self.started(announced=announced), send)
        self.assertEqual(send.replies, [None])
        self.assertNotIn("A.NS", state["announced"], "stale entries are dropped")

    def test_when_telegram_refuses_the_reply_it_is_sent_as_a_normal_message(self):
        send = FakeTelegram(refuse_replies=True)
        announced = {"A.NS": {"id": 777, "ts": TS - 3600, "side": "sell", "horizon": "long", "date": "2026-11-23"}}
        dispatch([self.breach()], self.started(announced=announced), send)
        self.assertEqual(send.replies, [None])
        self.assertEqual(len(send.sent), 1)

    def test_only_five_go_out_one_by_one_and_the_rest_wait_for_the_feed(self):
        send = FakeTelegram()
        items = [self.breach(f"S{i}.NS") for i in range(8)]
        state, _, _ = dispatch(items, self.started(), send)
        self.assertEqual(len(send.sent), feed_run.BREACHES_PER_RUN)
        self.assertEqual([q["feed"] for q in state["feed_queue"]], ["volatility"] * 3)

    def test_a_failed_send_puts_the_breach_back_for_the_next_slot(self):
        send = FakeTelegram(fail_after=0)
        state, _, _ = dispatch([self.breach()], self.started(), send)
        self.assertEqual([q["feed"] for q in state["feed_queue"]], ["volatility"])

    def test_the_first_run_holds_breaches_instead_of_sending(self):
        send = FakeTelegram()
        state, _, _ = dispatch([self.breach()], {}, send)
        self.assertEqual(send.sent, [])
        self.assertEqual(len(state["feed_queue"]), 1)

    def test_a_sent_reading_is_remembered_so_a_later_breach_can_reply_to_it(self):
        send = FakeTelegram()
        record = {"symbol": "A.NS", "name": "A", "price": 100.0, "currency": "INR", "short": {"label": "Buy", "score": 60, "reasons": []}, "indicators": {"atr": 2.0, "hi252": 130, "lo252": 70},
                  "levels": {"zones": []}}
        state = {"feeds_sent": {"readings": "x"}, "feed_queue": feeds.enqueue([], [("readings", signal("A.NS"))], TS)}
        state, _, _ = dispatch([], state, send, {"A.NS": record}, now=NOW + timedelta(minutes=1))
        self.assertEqual(state["announced"]["A.NS"]["id"], 1001)
        send2 = FakeTelegram()
        dispatch([self.breach()], {**state, "feeds_sent": {"volatility": feeds.slot_of(TABLE["volatility"], NOW)}}, send2)
        self.assertEqual(send2.replies, [1001])


class NewsDigestTests(unittest.TestCase):
    def story(self, **over):
        return {"symbol": "TATACONSUM.NS", "name": "Tata Consumer Products", "kind": "media", "title": "Tata Consumer announces new plant in Gujarat", "source": "Mint", "link": "https://example.com/a",
                "event_label": "Expansion", "impact": 60, "age_hours": 2.0, "sentiment": 64, "tone": "Positive", **over}

    def test_the_digest_is_headlines_ranked_by_importance_and_carries_no_tone_or_score(self):
        weak = self.story(symbol="B.NS", name="Beta", title="Beta news", impact=45, age_hours=0.2)
        strong = self.story(symbol="A.NS", name="Alpha", title="Alpha wins big order", impact=80, age_hours=5.0)
        items = fi.news_digest_lines({"stories": [weak, strong]}, {}, TS)
        self.assertEqual([i["text"].split(" · ")[0] for i in items], ["Alpha", "Beta"])
        text = " ".join(i["text"] for i in items)
        for word in ("sentiment", "positive", "negative", "agrees", "reading"):
            self.assertNotIn(word, text.lower())
        self.assertIn("(Mint, 5 h ago)", items[0]["text"])
        self.assertIn("#News", items[0]["tags"])
        self.assertEqual(items[0]["link"], "https://example.com/a")

    def test_official_filings_other_outlets_only_and_weak_or_stockless_stories_are_left_out(self):
        stories = [self.story(kind="nse"), self.story(symbol=None), self.story(impact=20), self.story(title="")]
        self.assertEqual(fi.news_digest_lines({"stories": stories}, {}, TS), [])

    def test_a_headline_listed_in_the_last_day_is_left_out_then_can_return(self):
        first = fi.news_digest_lines({"stories": [self.story()]}, {}, TS)
        seen = {first[0]["digest_key"]: TS}
        self.assertEqual(fi.news_digest_lines({"stories": [self.story()]}, seen, TS + 3600), [])
        self.assertEqual(len(fi.news_digest_lines({"stories": [self.story(title="A different headline")]}, seen, TS + 3600)), 1)
        self.assertEqual(len(fi.news_digest_lines({"stories": [self.story()]}, seen, TS + 90000)), 1)

    def test_a_long_headline_is_cut_and_the_list_is_capped(self):
        long = fi.news_digest_lines({"stories": [self.story(title="x" * 200)]}, {}, TS)[0]["text"]
        self.assertIn("…", long)
        many = [self.story(symbol=f"S{i}.NS", title=f"Story {i}") for i in range(20)]
        self.assertEqual(len(fi.news_digest_lines({"stories": many}, {}, TS)), 8)

    def test_delivery_records_what_was_listed_and_a_failed_send_records_nothing(self):
        when = datetime(2026, 11, 23, 10, 50, tzinfo=IST)
        for fail, expected in ((False, 1), (True, 0)):
            send = FakeTelegram(fail_after=0 if fail else None)
            src = {"news_dashboard": {"stories": [self.story()]}, "digest_seen": {}}
            feed_run.dispatch([], {"feeds_sent": {"news_digest": "x"}, "feed_queue": []}, when, int(when.timestamp()), feeds.settings({"feeds": {"news_digest": {"enabled": True}}}), src, {}, send, lambda i: None, "2026-11-23")
            self.assertEqual(len(src["digest_seen"]), expected)

    def test_a_filing_message_shows_importance_not_a_tone(self):
        story = {"kind": "nse", "symbol": "ABC.NS", "name": "Abc", "title": "Outcome of Board Meeting", "event": "results", "event_label": "Financial results", "impact": 85, "sentiment": -40, "source": "NSE", "ts": TS,
                 "link": "https://x.com/a.pdf"}
        items, _ = fi.filing_entries([story], {}, TS)
        text = digest_feeds.render_feed(items, [None], TS, "Important filings", ["#Filings"])[0][0].lower()
        self.assertIn("importance: 85 of 100", text)
        self.assertNotIn("sentiment", text)


class DispatchTests(unittest.TestCase):
    def test_the_first_deployment_starts_with_the_next_slot_and_sends_nothing(self):
        send = FakeTelegram()
        state, calls, sent = dispatch([signal()], {}, send)
        self.assertEqual(send.sent, [])
        self.assertIn("readings", state["feeds_sent"])
        self.assertEqual(len(state["feed_queue"]), 1, "the reading is held for the next slot, not lost")

    def test_a_held_reading_goes_out_when_its_slot_comes_and_only_once(self):
        send = FakeTelegram()
        state = {"feeds_sent": {"readings": feeds.slot_of(TABLE["readings"], NOW)}, "feed_queue": []}
        state, calls, sent = dispatch([signal()], state, send, {"AXISBANK.NS": {"short": {"label": "Buy"}, "price": 100, "levels": {}, "indicators": {}}}, now=NOW)
        self.assertEqual(send.sent, [], "this 15-minute slot was already sent, so the reading waits")
        state, calls, sent = dispatch([], state, send, {"AXISBANK.NS": {"short": {"label": "Buy"}}}, now=NOW + timedelta(minutes=16))
        self.assertEqual(len(send.sent), 1)
        self.assertIn("#AXISBANK", send.sent[0])
        state, _, _ = dispatch([], state, send, {"AXISBANK.NS": {"short": {"label": "Buy"}}}, now=NOW + timedelta(minutes=18))
        self.assertEqual(len(send.sent), 1, "not sent twice")
        self.assertEqual(state["feed_queue"], [])

    def test_a_reading_that_reversed_while_waiting_is_dropped(self):
        send = FakeTelegram()
        state = {"feeds_sent": {"readings": "2026-11-23#0"}, "feed_queue": feeds.enqueue([], [("readings", signal())], TS)}
        dispatch([], state, send, {"AXISBANK.NS": {"short": {"label": "Sell"}}}, now=NOW + timedelta(minutes=16))
        self.assertEqual(send.sent, [])

    def test_movers_and_lows_from_different_runs_are_grouped_so_each_section_appears_once(self):
        send = FakeTelegram()
        low = {**mover("V.NS"), "kind": "low52", "tags": ["at 52-week low"]}
        queue = feeds.enqueue([], [("movers", mover("A.NS")), ("movers", low), ("movers", mover("B.NS"))], TS)
        dispatch([], {"feeds_sent": {"movers": "x"}, "feed_queue": queue}, send, now=NOW + timedelta(minutes=1))
        self.assertEqual(send.sent[0].count("RISING"), 1)
        self.assertEqual(send.sent[0].count("52-WEEK LOWS"), 1)

    def test_a_filing_uses_the_company_name_and_has_no_levels_note(self):
        story = {"kind": "bse", "symbol": "SANGHVIMOV.NS", "title": "t", "event": "fraud_legal", "event_label": "Regulatory action", "impact": 75, "sentiment": -48, "source": "BSE", "ts": TS}
        items, _ = fi.filing_entries([story], {}, TS, names={"SANGHVIMOV.NS": "Sanghvi Movers"})
        text = digest_feeds.render_feed(items, [None], TS, "Important filings", ["#Filings"])[0][0]
        self.assertIn("Sanghvi Movers: Regulatory action", text)
        self.assertNotIn("Levels are indicative", text)

    def test_a_failed_send_keeps_the_items_and_does_not_mark_the_slot(self):
        send = FakeTelegram(fail_after=0)
        state = {"feeds_sent": {"movers": "2026-11-23#-1"}, "feed_queue": feeds.enqueue([], [("movers", mover())], TS)}
        new, calls, sent = dispatch([], state, send, now=NOW + timedelta(minutes=1))
        self.assertEqual(sent, [])
        self.assertNotEqual(new["feeds_sent"].get("movers"), "2026-11-23#0")
        self.assertEqual([q["item"]["symbol"] for q in new["feed_queue"]], ["DOLATALGO.NS"])

    def test_a_snapshot_feed_is_sent_when_due_and_an_empty_one_is_retried(self):
        send = FakeTelegram()
        state = {"feeds_sent": {}}
        indices = {"NIFTY 50": {"last": 25000.0, "pct": 0.4}}
        new, _, _ = dispatch([], state, send, src={"indices": indices, "india_open": True, "watch": [], "sectors": []})
        self.assertTrue(any("Indexes" in t for t in send.sent))
        self.assertIn("indexes", new["feeds_sent"])
        self.assertNotIn("commodities", new["feeds_sent"], "nothing to say yet, so the slot stays open to retry within its grace")

    def test_non_urgent_index_alerts_are_dropped_and_urgent_ones_go_out_at_once(self):
        send = FakeTelegram()
        state = {"feeds_sent": {name: "x" for name in TABLE}}
        items = [{"kind": "index", "symbol": "", "name": "NIFTY BANK", "tags": ["+1.1%"], "last": 60000.0}, {"kind": "index", "symbol": "", "name": "INDIA VIX", "tags": ["above 20"], "last": 21.0, "urgent": True}]
        items.append({"kind": "index", "symbol": "", "name": "S&P 500", "tags": ["-3.7%"], "last": 6910.0, "urgent": True})
        dispatch(items, state, send)
        self.assertEqual(len(send.sent), 1)
        self.assertNotIn("S&P", send.sent[0], "global cues are not alerted")
        self.assertIn("VOLATILITY ALERT", send.sent[0])
        self.assertNotIn("NIFTY BANK", send.sent[0])

    def test_calls_are_made_only_for_readings_that_were_sent_and_carry_the_message_id(self):
        send = FakeTelegram()
        record = {"symbol": "AXISBANK.NS", "name": "Axis", "price": 100.0, "currency": "INR", "short": {"label": "Buy", "score": 60, "reasons": []}, "indicators": {"atr": 2.0, "hi252": 130, "lo252": 70},
                  "levels": {"zones": []}}
        state = {"feeds_sent": {"readings": "2026-11-23#-1"}, "feed_queue": feeds.enqueue([], [("readings", signal())], TS)}
        _, calls, _ = dispatch([], state, send, {"AXISBANK.NS": record}, now=NOW + timedelta(minutes=1))
        self.assertEqual(len(send.sent), 1)
        for _, call in calls:
            self.assertEqual(call["telegram_message_id"], 1001)

    def test_telegram_not_set_up_changes_nothing_and_sends_nothing(self):
        state, calls, sent = feed_run.dispatch([mover()], {"feeds_sent": {}}, NOW, TS, TABLE, {}, {}, None, lambda i: None, "2026-11-23")
        self.assertEqual((calls, sent), ([], []))
        self.assertEqual(len(state["feed_queue"]), 1)


if __name__ == "__main__":
    unittest.main()


class TableAndLinkTests(unittest.TestCase):
    def test_a_target_reply_carries_its_numbers_as_bullets(self):
        call = {"symbol": "AXISBANK.NS", "name": "Axis Bank", "horizon": "short", "side": "buy", "price": 1446.0, "currency": "INR"}
        outcome = {"outcome": "target", "exit_price": 1512.0, "resolved_date": "2026-11-27", "days_held": 3}
        html_reply = alerts.format_outcome(call, outcome, "https://x/#stock=A", markup=True)
        self.assertNotIn("<pre>", html_reply)
        self.assertIn("• Alerted at 1,446.0 · Now 1,512.0", html_reply)
        self.assertIn("• Move +4.6% in 3 trading days", html_reply)
        self.assertIn("Open analysis", html_reply)
        plain = alerts.format_outcome(call, outcome)
        self.assertNotIn("<pre>", plain)
        self.assertIn("1,512.0", plain)
        self.assertTrue(plain.endswith(alerts.ADVISORY))

    def test_news_links_use_the_short_label_read_article(self):
        news = {"kind": "news", "symbol": "A.NS", "name": "A", "title": "Headline", "source": "Mint", "link": "https://example.com/very/long/path/to/an/article?id=12345678901234567890", "age_min": 5}
        text = digest_feeds.render_feed([news], [None], TS, "Company headlines", ["#News"])[0][0]
        self.assertIn(">Read article</a>", text)
        digest_line = fi.news_digest_lines({"stories": [{"symbol": "A.NS", "name": "A", "kind": "media", "title": "Headline", "source": "Mint", "link": "https://example.com/x", "impact": 60, "age_hours": 1.0}]}, {}, TS)
        text = digest_feeds.render_feed(digest_line, [None], TS, "Latest important news", ["#NewsDigest"])[0][0]
        self.assertIn(">Read article</a>", text)
        self.assertNotIn("example.com/x<", text, "the address is not shown, only the label")

    def test_every_numeric_alert_kind_is_a_table_row(self):
        samples = [mover(), {**mover(), "kind": "low52", "tags": ["at 52-week low"]}, {**mover(), "kind": "ipo", "tags": ["IPO breakout: above listing-day high 258.00"]}, signal(),
                   {"kind": "deal", "symbol": "A.NS", "name": "A", "qty": 1000, "price": 5.0, "value": 5000.0, "pchange": 1.0},
                   {"kind": "bulk", "symbol": "A.NS", "name": "A", "side": "BUY", "qty": 1000.0, "price": 5.0, "value": 5000.0, "client": "X"}]
        for item in samples:
            self.assertIsNotNone(digest_feeds.to_row(item), item["kind"])
        self.assertIsNone(digest_feeds.to_row({"kind": "news", "symbol": "A.NS"}), "a headline has no numbers to tabulate")


class PhoneWidthTests(unittest.TestCase):
    """Small phones wrap a monospace table, so alerts are lists of short lines: no alert kind produces a <pre> block, and long names and big numbers are kept whole."""

    def text_of(self, items):
        return "".join(m[0] for m in digest_feeds.render_feed(items, [None] * len(items), TS, "Feed", ["#X"]))

    def test_no_alert_kind_is_a_table(self):
        big = {"kind": "mover", "symbol": "SHALIMARPAINTS.NS", "name": "x", "tags": ["+19.8%", "volume 10.5x average"], "price": 12345.67, "currency": "INR", "small": True, "move": 19.8}
        cases = [[big], [{**big, "kind": "ipo", "tags": ["IPO breakout: above listing-day high 25,800.00"]}],
                 [{"kind": "deal", "symbol": "LENSKARTLIMITED.NS", "name": "x", "qty": 12697702, "price": 12345.0, "value": 9.2e9, "pchange": -12.6}],
                 [{"kind": "bulk", "symbol": "LENSKARTLIMITED.NS", "name": "x", "side": "BUY", "qty": 12697702.0, "price": 12345.0, "value": 9.2e9, "client": "Some Fund"}],
                 [{**signal("BAJAJHLDNG.NS"), "price": 12345.5, "levels": {"kind": "r", "price": 13512.0, "pct": 4.6, "basis": "x", "risk_price": 11383.0, "risk_pct": -4.4}}]]
        records = a_circuits = None
        from engine import actions as act
        circuit = act.circuit_records({"AllSec": {"data": [{"symbol": "HCL-INSYS", "series": "EQ", "ltp": "11.39", "change": "1.90", "priceBand": "20", "turnovercsv": 34563581}]}}, None, TS, "2026-11-23")
        cases.append(fi.action_alert_items(circuit, {}, TS)[0])
        gap = [{"id": "1", "type": "gap_up", "label": "Gap up", "symbol": "SHALIMARPAINTS.NS", "name": "x", "title": "t", "price": 12345.67, "move_pct": 12.5, "open": 11111.11, "prev_close": 9876.54,
                "source": "s", "date": "d"}]
        cases.append(fi.action_alert_items(gap, {}, TS)[0])
        cases.append(fi.volatility_breach_items([{"symbol": "SHALIMARPAINTS.NS", "name": "x", "sector": "B", "indicators": {"atr": 10.0}}],
                                                {"SHALIMARPAINTS.NS": {"price": 12345.0, "change_pct": 2.5, "state": "REGULAR"}}, True, {}, TS, "2026-11-23")[0])
        cases.append(fi.upcoming_ipo_entries([{"name": "Shree Siddhivinayak Greentech", "board": "SME", "open": "2026-11-25", "close": "2026-11-27", "listing": "2026-12-02", "price": 142,
                                               "subscription": 111.98, "gmp_pct": -22.45}], date(2026, 11, 23)))
        cases.append(fi.action_dates_entries(act.corporate_action_records([{"symbol": "ABC", "comp": "Abc", "subject": "Bonus 1:1", "exDate": "25-Nov-2026", "recDate": "26-Nov-2026"}], 1), date(2026, 11, 23)))
        cases.append([fi.index_alert_entry({"name": "NIFTY SMLCAP 100", "last": 12345.67, "tags": ["-3.0%"]}, NOW)])
        cases.append([fi.indexes_table({k: {"last": 61557.6, "pct": -12.34, "high52": 1, "low52": 0} for k in fi.INDEX_NAMES}, NOW)])
        cases.append([fi.commodities_table([{"name": "Crude oil", "kind": "commodity", "price": 1083.27, "change_pct": -0.85, "as_of": "2026-11-17"}], NOW)])
        sectors = [{"sector": s, "d1": d1, "d5": 1.0, "n": 8} for s, d1 in (("Metals and Mining", 12.2), ("Pharma and Health", 5.5), ("Real Estate", 1.0), ("Banks", -0.5), ("Industrials", -7.7), ("New listings", -12.1))]
        cases.append([fi.sectors_table(sectors, NOW)])
        for items in cases:
            text = self.text_of(items)
            self.assertNotIn("<pre>", text, items[0]["kind"])
            self.assertIn("Educational information", text)

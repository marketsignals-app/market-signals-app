import unittest
from datetime import datetime, timezone

from engine import news_intel as ni

NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)


def raw(title, source="Mint", kind="media", age_h=2.0, desc="", symbol=None, link="https://x/y"):
    return {"title": title, "text": title, "source": source, "kind": kind, "ts": NOW.timestamp() - age_h * 3600, "desc": desc, "link": link, "symbol": symbol}


def story(title, **kw):
    return ni.make_story(raw(title, **kw), NOW, "Acme")


class StoryTests(unittest.TestCase):
    def test_event_types_from_the_exchange_category_and_from_headlines(self):
        self.assertEqual(story("Acme: Bagging", kind="nse", source="NSE", desc="Bagging/Receiving of orders/contracts")["event"], "order_win")
        self.assertEqual(story("x", kind="nse", source="NSE", desc="Copy of Newspaper Publication")["event"], "routine")
        self.assertEqual(story("Acme Q2 net profit jumps 40%")["event"], "results")
        self.assertEqual(story("SEBI issues show cause notice to Acme")["event"], "fraud_legal")
        self.assertEqual(story("Acme CFO resigns")["event"], "management")
        self.assertEqual(story("Something happened")["event"], "general")

    def test_sentiment_direction_and_range(self):
        up, down = story("Acme profit jumps, beats estimates"), story("Acme shares plunge as profit falls")
        self.assertGreaterEqual(up["sentiment"], 40)
        self.assertLessEqual(down["sentiment"], -40)
        self.assertTrue(-100 <= up["sentiment"] <= 100 and -100 <= down["sentiment"] <= 100)
        self.assertEqual((up["tone"], down["tone"]), ("Positive", "Negative"))

    def test_the_event_prior_fills_in_only_when_the_words_say_nothing(self):
        self.assertGreater(story("Acme bags order from railways")["sentiment"], 0)
        self.assertEqual(story("Acme: Press Release", kind="nse", source="NSE", desc="General Updates")["sentiment"], 0)

    def test_official_filings_outrank_unknown_sources_and_rumours_lose_credibility(self):
        official = story("Acme wins order", kind="nse", source="NSE", desc="Bagging/Receiving of orders/contracts")
        blog = story("Acme wins order", source="randomblog.example")
        rumour = story("Acme reportedly in talks to buy rival", source="Mint")
        self.assertEqual(official["credibility"], 95)
        self.assertLess(blog["credibility"], official["credibility"])
        self.assertTrue(rumour["rumour"])
        self.assertLess(rumour["credibility"], story("Acme buys rival", source="Mint")["credibility"])

    def test_routine_filings_carry_almost_no_impact_and_old_news_fades(self):
        routine = story("x", kind="nse", source="NSE", desc="Copy of Newspaper Publication")
        results = story("Acme Q2 net profit jumps 40%", age_h=1)
        old = story("Acme Q2 net profit jumps 40%", age_h=90)
        self.assertLess(routine["impact"], 10)
        self.assertGreater(results["impact"], 50)
        self.assertLess(old["impact"], results["impact"] / 3)
        self.assertTrue(0 <= results["impact"] <= 100)


class DuplicateTests(unittest.TestCase):
    def test_syndicated_headlines_are_one_story_with_all_sources_listed(self):
        a = story("Acme Q2 profit jumps 40% on strong demand", source="Mint")
        b = story("Acme Q2 profit jumps 40 per cent on strong demand", source="Business Standard")
        c = story("Acme wins railway order worth Rs 500 crore", source="Mint")
        out = ni.dedupe([a, b, c])
        self.assertEqual(len(out), 2)
        merged = next(s for s in out if s["event"] == "results")
        self.assertEqual(merged["duplicates"], 1)
        self.assertEqual(set(merged["sources"]), {"Mint", "Business Standard"})
        self.assertGreater(merged["credibility"], a["credibility"], "corroboration raises credibility, it does not count the story twice")


class StockTests(unittest.TestCase):
    def analyse(self, *titles, **kw):
        return ni.analyse_stock(ni.dedupe([story(t, **kw) for t in titles]), NOW)

    def test_nothing_gives_none(self):
        self.assertIsNone(ni.analyse_stock([], NOW))

    def test_positive_negative_mixed_and_neutral(self):
        self.assertEqual(self.analyse("Acme Q2 profit jumps, beats estimates")["interpretation"], "Bullish")
        self.assertEqual(self.analyse("Acme shares plunge after SEBI show cause notice")["interpretation"], "Bearish")
        mixed = self.analyse("Acme Q2 profit jumps, beats estimates", "SEBI show cause notice to Acme over fraud, shares plunge")
        self.assertEqual((mixed["label"], mixed["interpretation"]), ("Mixed", "Mixed"))
        self.assertEqual(self.analyse("Acme announces AGM date")["interpretation"], "Neutral")

    def test_low_credibility_holds_the_interpretation_at_neutral(self):
        out = self.analyse("Acme Q2 profit jumps, beats estimates", source="randomblog.example")
        self.assertEqual(out["interpretation"], "Neutral")
        self.assertTrue(any("credibility" in r for r in out["risks"]))

    def test_the_output_has_everything_the_page_shows(self):
        out = self.analyse("Acme Q2 profit jumps, beats estimates")
        for key in ("label", "interpretation", "sentiment", "impact", "credibility", "fundamental", "risks", "explanation", "horizons", "stories", "latest"):
            self.assertIn(key, out)
        self.assertTrue(-100 <= out["sentiment"] <= 100 and 0 <= out["impact"] <= 100)
        self.assertEqual(out["fundamental"]["direction"], "positive")
        first = out["stories"][0]
        self.assertTrue(first["source"] and first["link"] and first["ts"])


class ReactionAndValidationTests(unittest.TestCase):
    def intel(self, *titles):
        return ni.analyse_stock(ni.dedupe([story(t) for t in titles]), NOW)

    def test_price_confirms_or_diverges_with_volume_and_sector(self):
        good = self.intel("Acme Q2 profit jumps, beats estimates")
        up = ni.reaction(good, 3.0, 2.0, 0.5)
        down = ni.reaction(good, -3.0, 1.0, 0.5)
        flat = ni.reaction(good, 0.1, 1.0, 0.5)
        self.assertEqual((up["state"], down["state"], flat["state"]), ("price confirms", "price diverges", "no clear reaction"))
        self.assertIn("heavy volume", up["text"])
        self.assertIn("ahead of its sector", up["text"])
        self.assertEqual(ni.reaction(good, None, None, None)["state"], "unknown")
        self.assertIsNone(ni.reaction(None, 1.0, 1.0, 1.0))

    def test_news_validates_a_reading_but_never_creates_one(self):
        good = self.intel("Acme Q2 profit jumps, beats estimates")
        bad = self.intel("Acme shares plunge after SEBI show cause notice")
        self.assertEqual(ni.validate(good, "buy")["state"], "confirms")
        self.assertEqual(ni.validate(bad, "buy")["state"], "conflicts")
        self.assertEqual(ni.validate(good, "sell")["state"], "conflicts")
        self.assertEqual(ni.validate(good, "hold")["state"], "neutral")
        self.assertEqual(ni.validate(good, None)["state"], "neutral")
        self.assertEqual(ni.validate(None, "buy")["state"], "neutral")


class SectorTests(unittest.TestCase):
    def test_sector_rows(self):
        pos = ni.analyse_stock(ni.dedupe([story("Acme Q2 profit jumps, beats estimates")]), NOW)
        neg = ni.analyse_stock(ni.dedupe([story("Beta shares plunge after SEBI show cause notice")]), NOW)
        rows = ni.sector_table([{"sector": "IT", "intel": pos}, {"sector": "IT", "intel": pos}, {"sector": "Banks", "intel": neg}, {"sector": "Auto", "intel": None}], {"IT": 1.2, "Banks": 1.0})
        by = {r["sector"]: r for r in rows}
        self.assertEqual(by["IT"]["stocks"], 2)
        self.assertEqual(by["IT"]["state"], "price confirms")
        self.assertEqual(by["Banks"]["state"], "price diverges")
        self.assertNotIn("Auto", by)

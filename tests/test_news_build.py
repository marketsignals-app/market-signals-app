import unittest
from datetime import datetime, timezone

from engine import build, catalog, news_intel as ni

NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)


def story_from(title, source="Mint", kind="media", desc="", age_h=2.0, symbol=None):
    raw = {"title": title, "text": title, "source": source, "kind": kind, "ts": NOW.timestamp() - age_h * 3600, "desc": desc, "link": "https://x/" + title[:6], "symbol": symbol}
    return ni.make_story(raw, NOW, "Acme")


def intel(*titles):
    return ni.analyse_stock(ni.dedupe([story_from(t) for t in titles]), NOW)


def record(symbol="A.NS", label="Buy", change=2.0, volume_ratio=2.0, sector="IT", **over):
    return {"symbol": symbol, "name": symbol, "sector": sector, "change_pct": change, "volume_ratio": volume_ratio, "short": {"label": label}, "long": {"label": label}, **over}


class ReadingSideTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual([build.reading_side(x) for x in ("Strong Buy", "Buy", "Hold", "Sell", "Strong Sell", "N/A", None)], ["buy", "buy", "hold", "sell", "sell", "hold", None])


class ApplyNewsContextTests(unittest.TestCase):
    def test_reaction_and_validation_are_added_and_nothing_is_changed_in_the_reading(self):
        rec = record(news_intel=intel("Acme Q2 profit jumps, beats estimates"))
        before = dict(rec["short"])
        build.apply_news_context(rec, {"IT": 0.5})
        self.assertEqual(rec["news_intel"]["reaction"]["state"], "price confirms")
        self.assertEqual(rec["news_intel"]["validation"]["state"], "confirms")
        self.assertEqual(rec["short"], before, "news only validates, it never rewrites a reading")

    def test_bad_news_against_a_buy_conflicts_and_a_stock_without_news_is_left_alone(self):
        rec = record(news_intel=intel("Acme shares plunge after SEBI show cause notice"), change=-3.0)
        build.apply_news_context(rec, {})
        self.assertEqual(rec["news_intel"]["validation"]["state"], "conflicts")
        plain = record()
        build.apply_news_context(plain, {})
        self.assertNotIn("news_intel", plain)

    def test_a_hold_reading_is_never_confirmed_or_contradicted(self):
        rec = record(label="Hold", news_intel=intel("Acme Q2 profit jumps, beats estimates"))
        build.apply_news_context(rec, {})
        self.assertEqual(rec["news_intel"]["validation"]["state"], "neutral")


class LiteSummaryTests(unittest.TestCase):
    def test_the_table_gets_a_small_summary_without_the_stories(self):
        rec = record(news_intel=intel("Acme Q2 profit jumps, beats estimates"), symbol="A.NS", provenance={}, bars=300, lite=False)
        build.apply_news_context(rec, {})
        lite = catalog.lite({**rec, "tags": [], "lists": [], "news": {"fresh": [], "items": []}, "spark": [1, 2, 3], "dividend": None, "backtest": {}})
        summary = lite["news_intel"]
        self.assertNotIn("stories", summary)
        for key in ("label", "interpretation", "sentiment", "impact", "credibility", "validation", "reaction", "top"):
            self.assertIn(key, summary)
        self.assertEqual(summary["validation"], "confirms")
        self.assertIsNone(catalog.news_summary(None))


class DashboardTests(unittest.TestCase):
    def pool(self):
        def item(title, symbol, kind="media", source="Mint", desc="", age_h=2.0):
            return {"title": title, "text": title, "source": source, "kind": kind, "ts": NOW.timestamp() - age_h * 3600, "desc": desc, "link": "https://x/" + title[:8], "symbol": symbol,
                    "industry": "Metals"}
        return {"A.NS": [item("Acme Q2 profit jumps, beats estimates", "A.NS"), item("Acme Q2 profit jumps, beats estimates", "A.NS", source="Business Standard")],
                "B.NS": [item("Beta shares plunge after SEBI show cause notice", "B.NS")],
                "C.NS": [item("Gamma: Bagging", "C.NS", kind="nse", source="NSE", desc="Bagging/Receiving of orders/contracts")]}

    def test_dashboard_counts_dedupes_and_ranks(self):
        recs = [record("A.NS", change=3.0, news_intel=intel("Acme Q2 profit jumps, beats estimates")), record("B.NS", sector="Banks", change=2.0, label="Sell",
                                                                                                    news_intel=intel("Beta shares plunge after SEBI show cause notice"))]
        for r in recs:
            build.apply_news_context(r, {"IT": 1.0, "Banks": 1.0})
        status = {"NSE announcements": {"ok": True, "items": 10, "error": None, "fetched_at": "t"}, "BSE announcements": {"ok": False, "items": 0, "error": "down", "fetched_at": None}}
        d = build.news_dashboard(recs, self.pool(), [{"title": "Banks rally as RBI holds repo rate", "source": "Mint", "kind": "media", "ts": NOW.timestamp() - 3600, "link": "https://m", "text": "", "desc": ""}],
                                 {"A.NS": "Acme", "B.NS": "Beta", "C.NS": "Gamma"}, {"IT": 1.0, "Banks": 1.0}, status, {}, None, [], NOW)
        self.assertEqual(d["counts"]["duplicates_removed"], 1)
        self.assertEqual(d["counts"]["stocks_with_news"], 3)
        titles = [s["title"] for s in d["stories"]]
        self.assertEqual(len(titles), len(set(titles)), "a syndicated story appears once")
        self.assertTrue(all(0 <= s["impact"] <= 100 and -100 <= s["sentiment"] <= 100 for s in d["stories"]))
        self.assertTrue(all(s["link"] and s["source"] and s["ts"] for s in d["stories"]), "every story keeps its source, time and original link")
        self.assertIn("Official", ["Official" if s["kind"] == "nse" else "" for s in d["stories"]])
        self.assertEqual({p["name"]: p["ok"] for p in d["providers"]}, {"NSE announcements": True, "BSE announcements": False})
        self.assertEqual([r["symbol"] for r in d["divergences"]], ["B.NS"], "bad news with the price up is a divergence")
        self.assertEqual({k: d["ai"][k] for k in ("enabled", "model", "generated_at", "scored", "shadow", "status")}, {"enabled": False, "model": None, "generated_at": None, "scored": 0, "shadow": True, "status": None})
        self.assertIn("IT", {r["sector"] for r in d["sectors"]})
        sector_news = [s for s in d["stories"] if s["symbol"] is None]
        self.assertEqual(sector_news[0]["sector"], "Banks")

    def test_an_empty_world_gives_an_empty_dashboard(self):
        d = build.news_dashboard([], {}, [], {}, {}, {}, {}, None, [], NOW)
        self.assertEqual((d["stories"], d["market_tone"], d["counts"]["official_share_pct"]), ([], 0, None))


class AiSummaryTests(unittest.TestCase):
    def story(self, rule, ai):
        return {"ai": ai is not None, "rule_sentiment": rule, "ai_sentiment": ai}

    def test_agreement_counts_direction_only_where_both_are_clear_and_never_calls_it_accuracy(self):
        stories = [self.story(60, 40), self.story(-50, -70), self.story(50, -30), self.story(5, 80), self.story(10, None)]
        out = build.ai_summary(stories, {"k": {}}, {"model": "m", "generated_at": "t", "status": {"outcome": "scored"}})
        self.assertEqual(out["agreement"], {"compared": 4, "same_direction_pct": 67, "firm_pairs": 3, "mean_abs_difference": 48.8})
        self.assertEqual((out["shadow"], out["weight"], out["status"]), (True, 0.0, {"outcome": "scored"}))

    def test_no_scores_means_no_agreement_figures(self):
        out = build.ai_summary([self.story(10, None)], {}, None)
        self.assertEqual(out["agreement"], {"compared": 0, "same_direction_pct": None, "firm_pairs": 0, "mean_abs_difference": None})

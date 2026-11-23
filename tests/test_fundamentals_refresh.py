"""Fundamentals with a missing market capitalisation are asked for again, never replaced by zero, and never move a score."""
import inspect
import unittest

from engine import build, fundamentals, signals


class FakeSession:
    def start(self):
        return True


def complete(cap=1_000.0):
    return {"market_cap": cap, "pe": 20.0, "events": {"earnings": [], "ex_dividend": None, "dividend_pay": None}, "v": fundamentals.VERSION}


def partial():
    return {"market_cap": None, "pe": 20.0, "events": {"earnings": [], "ex_dividend": None, "dividend_pay": None}, "v": fundamentals.VERSION}


class FreshnessTests(unittest.TestCase):
    NOW = 1_000_000

    def test_a_complete_answer_is_kept_for_the_normal_period(self):
        self.assertTrue(build.fundamentals_fresh({"ts": self.NOW - 3600, "data": complete()}, self.NOW))
        self.assertFalse(build.fundamentals_fresh({"ts": self.NOW - build.FUNDAMENTALS_MAX_AGE - 1, "data": complete()}, self.NOW))

    def test_an_answer_without_a_market_cap_is_asked_for_again_after_half_an_hour(self):
        self.assertTrue(build.fundamentals_fresh({"ts": self.NOW - 600, "data": partial(), "tries": 1}, self.NOW))
        self.assertFalse(build.fundamentals_fresh({"ts": self.NOW - build.INCOMPLETE_RETRY - 1, "data": partial(), "tries": 1}, self.NOW))

    def test_after_repeated_incomplete_answers_it_goes_back_to_once_a_day(self):
        cached = {"ts": self.NOW - 4 * 3600, "data": partial(), "tries": build.INCOMPLETE_TRIES}
        self.assertTrue(build.fundamentals_fresh(cached, self.NOW))

    def test_entries_without_the_events_block_are_always_refreshed(self):
        self.assertFalse(build.fundamentals_fresh({"ts": self.NOW, "data": {"market_cap": 5.0}}, self.NOW))
        self.assertFalse(build.fundamentals_fresh(None, self.NOW))


class FillTests(unittest.TestCase):
    NOW = 1_000_000

    def fill(self, state, answers, records=("AAA.NS",)):
        from unittest import mock
        from engine import fundamentals
        recs = [{"symbol": s} for s in records]
        asked = []

        def fetch(session, symbol):
            asked.append(symbol)
            return answers[symbol]

        with mock.patch.object(fundamentals, "fetch_fundamentals", side_effect=fetch), mock.patch.object(build.time, "sleep"):
            cache = build.fill_fundamentals(recs, state, self.NOW, FakeSession)
        return recs, cache, asked

    def test_a_stale_partial_answer_is_replaced_by_a_complete_one(self):
        state = {"fundamentals": {"AAA.NS": {"ts": self.NOW - 3600, "data": partial(), "tries": 1}}}
        recs, cache, asked = self.fill(state, {"AAA.NS": complete(5.0)})
        self.assertEqual(asked, ["AAA.NS"])
        self.assertEqual(recs[0]["fundamentals"]["market_cap"], 5.0)
        self.assertEqual(cache["AAA.NS"]["tries"], 0)

    def test_a_partial_answer_never_overwrites_an_earlier_complete_one(self):
        state = {"fundamentals": {"AAA.NS": {"ts": self.NOW - build.FUNDAMENTALS_MAX_AGE - 5, "data": complete(7.0), "tries": 0}}}
        recs, cache, asked = self.fill(state, {"AAA.NS": partial()})
        self.assertEqual(recs[0]["fundamentals"]["market_cap"], 7.0)
        self.assertEqual(cache["AAA.NS"]["data"]["market_cap"], 7.0)

    def test_a_market_cap_that_never_arrives_stays_missing_not_zero(self):
        recs, cache, asked = self.fill({}, {"AAA.NS": partial()})
        self.assertIsNone(recs[0]["fundamentals"]["market_cap"])
        self.assertEqual(cache["AAA.NS"]["tries"], 1)
        recs, cache, asked = self.fill({"fundamentals": cache}, {"AAA.NS": {}})        # nothing fresh to ask for yet
        self.assertEqual(asked, [])
        self.assertIsNone(recs[0]["fundamentals"]["market_cap"])

    def test_an_empty_answer_is_not_cached_as_data(self):
        recs, cache, asked = self.fill({}, {"AAA.NS": {}})
        self.assertEqual(recs[0]["fundamentals"], {})
        self.assertNotIn("AAA.NS", cache)

    def test_retries_of_incomplete_answers_are_capped_per_run(self):
        symbols = [f"S{i}.NS" for i in range(build.INCOMPLETE_PER_RUN + 10)]
        old = {s: {"ts": self.NOW - 7200, "data": partial(), "tries": 1} for s in symbols}
        recs, cache, asked = self.fill({"fundamentals": old}, {s: complete() for s in symbols}, symbols)
        self.assertEqual(len(asked), build.INCOMPLETE_PER_RUN)
        self.assertEqual(sum(1 for r in recs if r["fundamentals"].get("market_cap") is None), 10)


class ScoresDoNotUseFundamentalsTests(unittest.TestCase):
    def test_the_scoring_code_never_reads_fundamentals(self):
        for fn in (signals.short_detail, signals.long_detail, signals.build_indicators, signals.invalidation):
            self.assertNotIn("fundamental", inspect.getsource(fn).lower(), fn.__name__)
        self.assertEqual(list(inspect.signature(signals.short_detail).parameters), ["ind", "i"])      # price and volume only: no fundamentals, no news
        self.assertEqual(list(inspect.signature(signals.long_detail).parameters), ["ind", "i"])


if __name__ == "__main__":
    unittest.main()

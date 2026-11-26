"""Regression tests for data completeness (missing volume, unfinished daily candles), crossover wording, reading
confidence and an independent check of the indicator formulas against pandas/numpy."""
import math
import unittest

from engine import fetch, indicators as ta, patterns, signals
from tests.test_engine import make_bars

try:
    import numpy as np
    import pandas as pd
except ImportError:          # the engine itself needs neither; only the cross-check below does
    np = pd = None


def chart_payload(volumes, session=None):
    n = len(volumes)
    meta = {"currency": "USD", "gmtoffset": 0, "regularMarketTime": 5}
    if session:
        meta["currentTradingPeriod"] = {"regular": {"start": session[0], "end": session[1]}}
    return {"chart": {"result": [{"meta": meta, "timestamp": [1_700_000_000 + 86400 * i for i in range(n)],
                                  "indicators": {"quote": [{"open": [10.0] * n, "high": [11.0] * n, "low": [9.0] * n,
                                                            "close": [10.5] * n, "volume": volumes}]}}], "error": None}}


class MissingVolumeTests(unittest.TestCase):
    def test_missing_volume_stays_missing_and_zero_stays_zero(self):
        volumes = [1000] * 70
        volumes[3], volumes[4] = None, 0
        v = fetch.clean_chart(chart_payload(volumes), "T")["bars"]["v"]
        self.assertIsNone(v[3])
        self.assertEqual(v[4], 0.0)
        self.assertIsNotNone(v[4])

    def test_windows_with_a_missing_volume_give_no_value(self):
        n = 60
        bars = make_bars([100 + (i % 5) for i in range(n)])
        bars["v"][30] = None
        h, l, c, v = bars["h"], bars["l"], bars["c"], bars["v"]
        for series in (ta.rolling_vwap(h, l, c, v, 20), ta.chaikin_money_flow(h, l, c, v, 20), ta.up_volume_share(c, v, 20), ta.sma_complete(v, 20)):
            self.assertIsNotNone(series[29])              # the window ends before the gap
            for i in range(30, 30 + 20):
                self.assertIsNone(series[i], f"window ending at {i} contains the gap")
            self.assertIsNotNone(series[55])               # a window after the gap is complete again

    def test_genuine_zero_volume_days_are_counted_not_rejected(self):
        bars = make_bars([100 + (i % 7) for i in range(40)])
        bars["v"][25] = 0.0                                # a real day with no trades inside the window
        out = ta.chaikin_money_flow(bars["h"], bars["l"], bars["c"], bars["v"], 20)
        self.assertIsNotNone(out[30])
        total_zero = ta.chaikin_money_flow(bars["h"][:20], bars["l"][:20], bars["c"][:20], [0.0] * 20, 20)
        self.assertIsNone(total_zero[19])                  # a window with no volume at all has no meaningful flow

    def test_missing_volume_cannot_create_a_pressure_reading(self):
        closes = [100 + 0.3 * i for i in range(260)]
        bars = make_bars(closes)
        bars["v"][-5] = None
        ind = signals.build_indicators(bars)
        self.assertIsNone(signals.buy_sell_pressure(ind, len(closes) - 1))
        full = signals.build_indicators(make_bars(closes))
        self.assertIsNotNone(signals.buy_sell_pressure(full, len(closes) - 1))

    def test_missing_volume_lowers_confidence(self):
        closes = [100 + 0.3 * i + (i % 3) for i in range(260)]
        bars = make_bars(closes)
        full = signals.short_detail(signals.build_indicators(bars), 259)
        self.assertEqual(full["coverage"], 1.0)
        self.assertEqual(signals.confidence(full["coverage"]), "full")
        bars["v"][-3] = None
        partial = signals.short_detail(signals.build_indicators(bars), 259)
        self.assertEqual(sorted(partial["missing"]), ["pressure", "volume"])
        self.assertEqual(partial["coverage"], 0.79)     # the rule weights are 30+25+20+5+15 = 95; 75 of them had data
        self.assertEqual(signals.confidence(partial["coverage"]), "reduced")
        self.assertIsNotNone(partial["score"])             # still enough data for a reading, with its confidence stated

    def test_volume_spike_needs_that_days_volume(self):
        closes = [100 + 0.2 * i for i in range(260)]
        bars = make_bars(closes)
        bars["v"][-1] = None
        detail = signals.short_detail(signals.build_indicators(bars), 259)
        self.assertNotIn("volume", [r["key"] for r in detail["reasons"]])

    def test_breakout_strength_unknown_without_volume(self):
        closes = [100.0] * 35 + [110.0]
        bars = make_bars(closes)
        bars["v"][-1] = None
        found = patterns.detect_patterns(bars, signals.build_indicators(bars))
        note = next(p["note"] for p in found if p["name"] == "20-day breakout")
        self.assertIn("volume not reported", note)
        self.assertNotIn("normal volume", note)


class ProvisionalCandleTests(unittest.TestCase):
    BARS = {"t": [1000, 2000, 3000], "d": ["a", "b", "c"], "o": [1] * 3, "h": [1] * 3, "l": [1] * 3, "c": [1] * 3, "v": [1] * 3}

    def test_open_market_makes_the_last_bar_provisional(self):
        meta = {"session_start": 3000, "session_end": 3000 + 28800}
        self.assertTrue(fetch.last_bar_provisional(self.BARS, meta, 3000 + 3600))

    def test_closed_market_gives_a_completed_bar(self):
        meta = {"session_start": 3000, "session_end": 3000 + 28800}
        self.assertFalse(fetch.last_bar_provisional(self.BARS, meta, 3000 + 28800 + fetch.PROVISIONAL_GRACE + 1))

    def test_grace_period_after_the_close_still_counts_as_provisional(self):
        meta = {"session_start": 3000, "session_end": 3000 + 28800}
        self.assertTrue(fetch.last_bar_provisional(self.BARS, meta, 3000 + 28800 + 60))

    def test_before_the_open_the_last_bar_is_yesterday_and_complete(self):
        meta = {"session_start": 4000, "session_end": 4000 + 28800}       # today's session has not started
        self.assertFalse(fetch.last_bar_provisional(self.BARS, meta, 3500))

    def test_missing_session_times_are_not_guessed(self):
        self.assertFalse(fetch.last_bar_provisional(self.BARS, {}, 5000))
        self.assertFalse(fetch.last_bar_provisional(self.BARS, {"session_start": None, "session_end": None}, 5000))

    def test_session_times_are_read_from_the_chart_metadata(self):
        out = fetch.clean_chart(chart_payload([1000] * 70, session=(1_700_000_000, 1_700_028_800)), "T")
        self.assertEqual(out["meta"]["session_start"], 1_700_000_000)
        self.assertEqual(out["meta"]["session_end"], 1_700_028_800)

    def test_trim_drops_only_the_newest_bar_and_leaves_the_original(self):
        trimmed = fetch.trim_last_bar(self.BARS)
        self.assertEqual(trimmed["c"], [1, 1])
        self.assertEqual(trimmed["t"], [1000, 2000])
        self.assertEqual(len(self.BARS["t"]), 3)


class CrossoverWordingTests(unittest.TestCase):
    def ind(self, s50, s200, price=100.0):
        n = len(s50)
        return {"sma50": s50, "sma200": s200, "bars": {"c": [price] * n}, "momentum126": [None] * n, "hi252": [None] * n,
                "lo252": [None] * n, "vol30": [None] * n}

    def cross_text(self, ind, i):
        detail = signals.long_detail(ind, i)
        return next(r["text"] for r in detail["reasons"] if r["key"] == "cross")

    def test_existing_alignment_is_not_called_a_golden_cross(self):
        s200 = [100.0] * 60
        s50 = [110.0] * 60                                  # above the whole time: aligned, no crossover event
        text = self.cross_text(self.ind(s50, s200), 59)
        self.assertIn("bullish alignment", text)
        self.assertNotIn("golden", text)
        self.assertIsNone(signals.recent_cross(self.ind(s50, s200), 59))

    def test_a_real_upward_crossover_is_reported_with_its_age(self):
        s200 = [100.0] * 60
        s50 = [95.0] * 50 + [101.0] * 10                    # crosses above at index 50
        ind = self.ind(s50, s200)
        self.assertEqual(signals.recent_cross(ind, 59), ("golden", 9))
        self.assertIn("crossed above the 200-day 9 sessions ago (golden cross)", self.cross_text(ind, 59))

    def test_a_real_downward_crossover_is_a_death_cross(self):
        s200 = [100.0] * 60
        s50 = [105.0] * 58 + [99.0] * 2
        self.assertEqual(signals.recent_cross(self.ind(s50, s200), 59), ("death", 1))
        self.assertIn("(death cross)", self.cross_text(self.ind(s50, s200), 59))

    def test_a_crossover_older_than_the_window_is_alignment_again(self):
        s200 = [100.0] * 80
        s50 = [95.0] * 20 + [110.0] * 60                    # crossed at index 20; at index 79 that was 59 sessions ago
        ind = self.ind(s50, s200)
        self.assertIsNone(signals.recent_cross(ind, 79))
        self.assertIn("alignment", self.cross_text(ind, 79))

    def test_the_score_follows_alignment_not_the_event(self):
        s200 = [100.0] * 60
        steady = signals.long_detail(self.ind([110.0] * 60, s200), 59)["reasons"]
        fresh = signals.long_detail(self.ind([95.0] * 50 + [110.0] * 10, s200), 59)["reasons"]
        value = lambda reasons: next(r["value"] for r in reasons if r["key"] == "cross")
        self.assertEqual(value(steady), value(fresh))

    def test_level_averages_without_a_crossover(self):
        text = self.cross_text(self.ind([100.2] * 60, [100.0] * 60), 59)
        self.assertEqual(text, "50-day is about level with the 200-day")


class InvalidationTests(unittest.TestCase):
    def test_bullish_short_reading_names_what_would_weaken_it(self):
        bars = make_bars([100 + 0.3 * i for i in range(260)])
        ind = signals.build_indicators(bars)
        text = " | ".join(signals.invalidation(ind, 259, "short", 70))
        self.assertIn("a close below the 20-day average", text)
        self.assertIn("MACD histogram turning negative", text)
        self.assertIn("volatility risk level", text)

    def test_bearish_and_missing_readings(self):
        bars = make_bars([100 + 0.3 * i for i in range(260)])
        ind = signals.build_indicators(bars)
        self.assertIn("a close above the 200-day average", signals.invalidation(ind, 259, "long", -60)[0])
        self.assertEqual(signals.invalidation(ind, 259, "long", None), [])


@unittest.skipIf(np is None, "pandas and numpy are only needed for this cross-check")
class IndicatorReferenceTests(unittest.TestCase):
    """Compare each indicator with an independent pandas/numpy calculation on the same random-walk data.
    Exponential averages start from a different seed in each library, so those are compared after a warm-up long enough
    for the seed to fade (more than 1e-9 of it remains for fewer than ~170 bars)."""

    @classmethod
    def setUpClass(cls):
        rng = np.random.RandomState(7)
        n = 700
        cls.close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, n)))
        spread = rng.uniform(0.003, 0.02, n)
        cls.high = cls.close * (1 + spread)
        cls.low = cls.close * (1 - spread)
        cls.volume = rng.randint(1_000, 50_000, n).astype(float)
        cls.s = pd.Series(cls.close)
        cls.n = n

    def assert_close(self, ours, ref, start, tol=1e-9):
        for i in range(start, self.n):
            self.assertIsNotNone(ours[i])
            self.assertAlmostEqual(ours[i], float(ref[i]), delta=tol * max(1.0, abs(float(ref[i]))), msg=f"index {i}")

    def test_sma_20_50_200(self):
        for n in (20, 50, 200):
            self.assert_close(ta.sma(list(self.close), n), self.s.rolling(n).mean(), n - 1)

    def test_ema_12_26_after_warmup(self):
        for n in (12, 26):
            self.assert_close(ta.ema(list(self.close), n), self.s.ewm(span=n, adjust=False).mean(), 300, 1e-8)

    def test_rsi_14_wilder(self):
        change = self.s.diff()
        gain, loss = change.clip(lower=0), (-change).clip(lower=0)
        avg_gain, avg_loss = gain.ewm(alpha=1 / 14, adjust=False).mean(), loss.ewm(alpha=1 / 14, adjust=False).mean()
        ref = 100 - 100 / (1 + avg_gain / avg_loss)
        self.assert_close(ta.rsi(list(self.close), 14), ref, 400, 1e-7)

    def test_macd_12_26_9(self):
        macd_line = self.s.ewm(span=12, adjust=False).mean() - self.s.ewm(span=26, adjust=False).mean()
        signal = macd_line.ewm(span=9, adjust=False).mean()
        line, sig, hist = ta.macd(list(self.close))
        self.assert_close(line, macd_line, 400, 1e-7)
        self.assert_close(sig, signal, 400, 1e-7)
        self.assert_close(hist, macd_line - signal, 400, 1e-7)

    def test_atr_14_wilder(self):
        h, l, c = pd.Series(self.high), pd.Series(self.low), self.s
        true_range = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        true_range.iloc[0] = h.iloc[0] - l.iloc[0]
        ref = true_range.ewm(alpha=1 / 14, adjust=False).mean()
        self.assert_close(ta.atr(list(self.high), list(self.low), list(self.close), 14), ref, 400, 1e-7)

    def test_annualised_volatility_30(self):
        returns = self.s.pct_change()
        ref = returns.rolling(30).std(ddof=1) * math.sqrt(252)
        self.assert_close(ta.rolling_vol(list(self.close), 30), ref, 30)

    def test_vwap_20(self):
        typical = (pd.Series(self.high) + pd.Series(self.low) + self.s) / 3
        vol = pd.Series(self.volume)
        ref = (typical * vol).rolling(20).sum() / vol.rolling(20).sum()
        self.assert_close(ta.rolling_vwap(list(self.high), list(self.low), list(self.close), list(self.volume), 20), ref, 19)

    def test_chaikin_money_flow_20(self):
        h, l, c, v = pd.Series(self.high), pd.Series(self.low), self.s, pd.Series(self.volume)
        flow = ((c - l) - (h - c)) / (h - l) * v
        ref = flow.rolling(20).sum() / v.rolling(20).sum()
        self.assert_close(ta.chaikin_money_flow(list(self.high), list(self.low), list(self.close), list(self.volume), 20), ref, 19)

    def test_up_volume_share_20(self):
        v = pd.Series(self.volume)
        up = (self.s > self.s.shift()).astype(float) * v
        ref = up.rolling(20).sum() / v.rolling(20).sum()
        self.assert_close(ta.up_volume_share(list(self.close), list(self.volume), 20), ref, 20)

    def test_126_day_momentum_and_252_session_range(self):
        bars = make_bars(list(self.close))
        bars["h"], bars["l"] = list(self.high), list(self.low)
        ind = signals.build_indicators(bars)
        self.assert_close(ind["momentum126"], self.s / self.s.shift(126) - 1, 126)
        self.assert_close(ind["hi252"], pd.Series(self.high).rolling(252).max(), 251)
        self.assert_close(ind["lo252"], pd.Series(self.low).rolling(252).min(), 251)


class FibonacciAndLevelTests(unittest.TestCase):
    def test_fibonacci_retracement_levels_for_an_uptrend(self):
        high = [10, 12, 14, 16, 18, 20.0]
        low = [9, 11, 13, 15, 17, 19.0]
        out = ta.fibonacci_levels(high, low)
        self.assertTrue(out["uptrend"])
        self.assertEqual((out["low"], out["high"]), (9.0, 20.0))
        self.assertAlmostEqual(out["levels"]["0.5"], 14.5)
        self.assertAlmostEqual(out["levels"]["0.618"], 20 - 0.618 * 11)

    def test_fibonacci_levels_for_a_downtrend_count_up_from_the_low(self):
        high = [20.0, 18, 16, 14, 12, 10]
        low = [19.0, 17, 15, 13, 11, 9]
        out = ta.fibonacci_levels(high, low)
        self.assertFalse(out["uptrend"])
        self.assertAlmostEqual(out["levels"]["0.382"], 9 + 0.382 * 11)

    def test_support_and_resistance_sit_on_the_right_side_of_the_price(self):
        rng = np.random.RandomState(3) if np is not None else None
        if rng is None:
            self.skipTest("numpy not installed")
        close = list(100 + 8 * np.sin(np.arange(300) / 6.0) + rng.normal(0, 0.3, 300))
        high = [c + 0.5 for c in close]
        low = [c - 0.5 for c in close]
        zones = ta.support_resistance(high, low, close)
        self.assertTrue(all(z["level"] < close[-1] for z in zones["support"]))
        self.assertTrue(all(z["level"] > close[-1] for z in zones["resistance"]))
        self.assertTrue(zones["support"] or zones["resistance"])


if __name__ == "__main__":
    unittest.main()


class AnalyseWithUnfinishedCandleTests(unittest.TestCase):
    """build.analyse on a chart whose newest bar is today's unfinished candle."""

    def setUp(self):
        from datetime import date, datetime, timedelta, timezone
        n = 300
        start = date(2026, 1, 1)
        self.closes = [100.0 + 0.2 * i + (i % 4) for i in range(n)]
        self.volumes = [10_000.0] * (n - 1) + [150.0]               # today's volume so far is a sliver of a normal day
        self.dates = [(start + timedelta(days=i)).isoformat() for i in range(n)]
        self.session = (1_800_000_000, 1_800_000_000 + 28800)
        self.ts = [self.session[0] - 86400 * (n - 1 - i) for i in range(n)]
        self.now = datetime(2026, 11, 16, tzinfo=timezone.utc)
        self.today = date(2026, 11, 16)

    def chart(self, session=True):
        bars = {"t": list(self.ts), "d": list(self.dates), "o": list(self.closes), "h": [c * 1.01 for c in self.closes],
                "l": [c * 0.99 for c in self.closes], "c": list(self.closes), "v": list(self.volumes)}
        meta = {"currency": "USD", "exchange": "NYSE", "session_start": self.session[0] if session else None, "session_end": self.session[1] if session else None}
        return {"bars": bars, "dividends": [], "splits": [], "meta": meta}

    def analyse(self, chart, now_ts):
        from unittest import mock
        from engine import build, news
        entry = {"symbol": "AAA", "name": "Aaa Inc", "market": "US", "sector": "Technology", "tags": []}
        ctx = {"today": self.today, "now": self.now, "now_ts": now_ts, "delivery": {}, "deals": {}, "bench": {}, "bars": {}}
        with mock.patch.object(fetch, "fetch_chart", return_value=chart), mock.patch.object(news, "fetch_news", return_value=[]):
            return build.analyse(entry, ctx)

    def test_open_market_readings_use_completed_candles_and_a_live_price(self):
        record = self.analyse(self.chart(), self.session[0] + 3600)
        self.assertTrue(record["provisional"])
        self.assertEqual(record["price"], round(self.closes[-1], 4))                  # the live price is still shown
        self.assertEqual(record["as_of"], self.dates[-1])
        self.assertEqual(record["confirmed_as_of"], self.dates[-2])
        # the confirmed reading equals the reading of the same history with the unfinished bar removed
        trimmed = self.chart()
        trimmed["bars"] = fetch.trim_last_bar(trimmed["bars"])
        self.assertEqual(self.analyse(trimmed, self.session[1] + 99999)["short"]["score"], record["short"]["score"])
        self.assertEqual(record["short"]["confidence"], "full")

    def test_the_record_carries_the_range_of_the_newest_candle(self):
        record = self.analyse(self.chart(), self.session[0] + 3600)
        self.assertEqual(record["day"], {"open": round(self.closes[-1], 4), "high": round(self.closes[-1] * 1.01, 4), "low": round(self.closes[-1] * 0.99, 4)})

    def test_the_unfinished_candle_gets_its_own_marked_reading_without_volume(self):
        record = self.analyse(self.chart(), self.session[0] + 3600)
        live = record["live"]["short"]
        self.assertEqual(sorted(live["missing"]), ["pressure", "volume"])
        self.assertEqual(live["confidence"], "reduced")
        self.assertNotIn("Volume pressure", " ".join(r["text"] for r in live["reasons"]))

    def test_the_partial_volume_never_reaches_a_confirmed_volume_reading(self):
        record = self.analyse(self.chart(), self.session[0] + 3600)
        texts = " ".join(r["text"] for r in record["short"]["reasons"])
        self.assertNotIn("falling day", texts)           # the 150-share sliver would otherwise look like a volume collapse
        self.assertEqual(record["short"]["missing"], [])

    def test_after_the_close_the_last_candle_is_complete_and_there_is_no_live_block(self):
        record = self.analyse(self.chart(), self.session[1] + fetch.PROVISIONAL_GRACE + 60)
        self.assertFalse(record["provisional"])
        self.assertNotIn("live", record)
        self.assertEqual(record["confirmed_as_of"], record["as_of"])

    def test_levels_are_placed_against_the_live_price(self):
        record = self.analyse(self.chart(), self.session[0] + 3600)
        zones = record["levels"]["zones"]
        self.assertTrue(all(z["level"] < record["price"] for z in zones["support"]))
        self.assertTrue(all(z["level"] > record["price"] for z in zones["resistance"]))

    def test_without_session_times_nothing_is_marked_provisional(self):
        record = self.analyse(self.chart(session=False), self.session[0] + 3600)
        self.assertFalse(record["provisional"])

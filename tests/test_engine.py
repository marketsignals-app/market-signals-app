import json
import math
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from engine import backtest as bt
from engine import fetch, fundamentals, indicators as ta, news, patterns, risk, signals

# Wilder's RSI worked example (StockCharts), values from index 14 onward.
WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
    46.00, 46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18, 44.22, 44.57,
    43.42, 42.66, 43.13,
]
WILDER_RSI = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71, 50.42, 39.99,
              41.46, 41.87, 45.46, 37.30, 33.08, 37.77]


def make_bars(closes, spread=0.01, volume=1000.0, open_prev_close=True):
    o = [closes[0]] + closes[:-1] if open_prev_close else list(closes)
    return {
        "t": list(range(len(closes))),
        "d": [str(i) for i in range(len(closes))],
        "o": o,
        "h": [max(a, b) * (1 + spread) for a, b in zip(o, closes)],
        "l": [min(a, b) * (1 - spread) for a, b in zip(o, closes)],
        "c": list(closes),
        "v": [volume] * len(closes),
    }


class IndicatorTests(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(ta.sma([1, 2, 3, 4, 5], 3), [None, None, 2, 3, 4])

    def test_sma_too_short(self):
        self.assertEqual(ta.sma([1, 2], 3), [None, None])

    def test_ema_constant_series(self):
        out = ta.ema([5.0] * 30, 10)
        self.assertTrue(all(v is None for v in out[:9]))
        self.assertTrue(all(abs(v - 5.0) < 1e-12 for v in out[9:]))

    def test_ema_known_step(self):
        out = ta.ema([1, 1, 1, 4], 3)
        self.assertAlmostEqual(out[3], 4 * 0.5 + 1 * 0.5)

    def test_rsi_matches_wilder_reference(self):
        out = ta.rsi(WILDER_CLOSES, 14)
        for offset, expected in enumerate(WILDER_RSI):
            self.assertAlmostEqual(out[14 + offset], expected, delta=0.6, msg=f"index {14 + offset}")

    def test_rsi_first_value_independent_formula(self):
        changes = [WILDER_CLOSES[i] - WILDER_CLOSES[i - 1] for i in range(1, 15)]
        avg_gain = sum(c for c in changes if c > 0) / 14
        avg_loss = sum(-c for c in changes if c < 0) / 14
        expected = 100 - 100 / (1 + avg_gain / avg_loss)
        self.assertAlmostEqual(ta.rsi(WILDER_CLOSES, 14)[14], expected, places=9)

    def test_rsi_bounds_and_extremes(self):
        rising = ta.rsi([float(i) for i in range(1, 40)], 14)
        falling = ta.rsi([float(i) for i in range(40, 1, -1)], 14)
        flat = ta.rsi([10.0] * 40, 14)
        self.assertEqual(rising[-1], 100.0)
        self.assertEqual(falling[-1], 0.0)
        self.assertEqual(flat[-1], 50.0)

    def test_macd_constant_is_zero(self):
        line, sig, hist = ta.macd([7.0] * 80)
        self.assertAlmostEqual(line[-1], 0.0)
        self.assertAlmostEqual(hist[-1], 0.0)

    def test_macd_uptrend_positive(self):
        line, sig, hist = ta.macd([float(i) for i in range(1, 120)])
        self.assertGreater(line[-1], 0)

    def test_atr_constant_range(self):
        out = ta.atr([12.0] * 30, [10.0] * 30, [11.0] * 30, 14)
        self.assertAlmostEqual(out[-1], 2.0)
        self.assertIsNone(out[12])

    def test_rolling_vol_flat_is_zero(self):
        self.assertAlmostEqual(ta.rolling_vol([10.0] * 50, 30)[-1], 0.0)

    def test_rolling_vol_known(self):
        values = [100.0]
        for i in range(40):
            values.append(values[-1] * (1.01 if i % 2 == 0 else 0.99))
        vol = ta.rolling_vol(values, 30)[-1]
        self.assertAlmostEqual(vol, 0.01 * math.sqrt(252), delta=0.01)

    def test_vwap_equal_volume_is_mean_typical(self):
        out = ta.rolling_vwap([12.0] * 25, [10.0] * 25, [11.0] * 25, [100.0] * 25, 20)
        self.assertAlmostEqual(out[-1], 11.0)

    def test_vwap_zero_volume_is_none(self):
        self.assertIsNone(ta.rolling_vwap([12.0] * 25, [10.0] * 25, [11.0] * 25, [0.0] * 25, 20)[-1])

    def test_cmf_close_at_high_is_one(self):
        out = ta.chaikin_money_flow([11.0] * 25, [9.0] * 25, [11.0] * 25, [100.0] * 25, 20)
        self.assertAlmostEqual(out[-1], 1.0)

    def test_cmf_close_at_low_is_minus_one(self):
        out = ta.chaikin_money_flow([11.0] * 25, [9.0] * 25, [9.0] * 25, [100.0] * 25, 20)
        self.assertAlmostEqual(out[-1], -1.0)

    def test_cmf_flat_bar_and_zero_volume(self):
        self.assertAlmostEqual(ta.chaikin_money_flow([10.0] * 25, [10.0] * 25, [10.0] * 25, [5.0] * 25)[-1], 0.0)
        self.assertIsNone(ta.chaikin_money_flow([11.0] * 25, [9.0] * 25, [10.0] * 25, [0.0] * 25)[-1])

    def test_up_volume_share(self):
        rising = ta.up_volume_share([float(i) for i in range(1, 40)], [10.0] * 39)
        falling = ta.up_volume_share([float(i) for i in range(40, 1, -1)], [10.0] * 39)
        self.assertEqual(rising[-1], 1.0)
        self.assertEqual(falling[-1], 0.0)

    def test_fibonacci_uptrend(self):
        high = [10.0, 12.0, 14.0, 20.0, 18.0]
        low = [9.0, 10.0, 12.0, 18.0, 16.0]
        fib = ta.fibonacci_levels(high, low)
        self.assertTrue(fib["uptrend"])
        self.assertAlmostEqual(fib["levels"]["0.5"], (20.0 + 9.0) / 2)

    def test_fibonacci_flat_is_none(self):
        self.assertIsNone(ta.fibonacci_levels([5.0] * 10, [5.0] * 10))

    def test_support_resistance_finds_zones(self):
        closes, high, low = [], [], []
        for i in range(120):
            base = 100 + 10 * math.sin(i / 6)
            closes.append(base)
            high.append(base + 0.5)
            low.append(base - 0.5)
        zones = ta.support_resistance(high, low, closes)
        price = closes[-1]
        for z in zones["support"]:
            self.assertLess(z["level"], price)
        for z in zones["resistance"]:
            self.assertGreater(z["level"], price)
        self.assertTrue(zones["support"] or zones["resistance"])


class RiskTests(unittest.TestCase):
    def test_percentile(self):
        self.assertEqual(risk.percentile([1, 2, 3, 4, 5], 0.5), 3)
        self.assertAlmostEqual(risk.percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertIsNone(risk.percentile([], 0.5))

    def test_max_drawdown(self):
        self.assertAlmostEqual(risk.max_drawdown([100, 50, 100]), -0.5)
        self.assertEqual(risk.max_drawdown([1, 2, 3]), 0.0)

    def test_risk_stats_short_history(self):
        self.assertIsNone(risk.risk_stats([100.0] * 30))

    def test_risk_stats_values(self):
        closes = [100 * (1.001 ** i) * (1 + (0.01 if i % 7 == 0 else 0)) for i in range(300)]
        stats = risk.risk_stats(closes)
        self.assertGreater(stats["annual_vol"], 0)
        self.assertGreaterEqual(stats["expected_shortfall95"], stats["var95"])
        self.assertLessEqual(stats["max_drawdown"], 0)

    def test_beta_of_double_exposure_is_two(self):
        bench = {str(i).zfill(4): 100 * (1 + 0.01 * math.sin(i)) for i in range(120)}
        dates = sorted(bench)
        stock = {}
        value = 100.0
        stock[dates[0]] = value
        for prev, cur in zip(dates, dates[1:]):
            value *= 1 + 2 * (bench[cur] / bench[prev] - 1)
            stock[cur] = value
        self.assertAlmostEqual(risk.beta(stock, bench), 2.0, delta=0.05)

    def test_beta_needs_overlap(self):
        self.assertIsNone(risk.beta({"a": 1.0}, {"b": 1.0}))


class SignalTests(unittest.TestCase):
    def scores(self, closes):
        bars = make_bars(closes)
        ind = signals.build_indicators(bars)
        i = len(closes) - 1
        return signals.short_score(ind, i)[0], signals.long_score(ind, i)[0]

    def test_label_boundaries(self):
        cases = {None: "N/A", 50: "Strong Buy", 49: "Buy", 20: "Buy", 19: "Hold", 0: "Hold", -19: "Hold",
                 -20: "Sell", -49: "Sell", -50: "Strong Sell"}
        for score, expected in cases.items():
            self.assertEqual(signals.label(score), expected, score)

    def test_uptrend_scores_bullish(self):
        closes = [100 * 1.004 ** i for i in range(300)]
        short, long_ = self.scores(closes)
        self.assertGreater(long_, 40)
        self.assertGreater(short, 0)

    def test_downtrend_scores_bearish(self):
        closes = [100 * 0.996 ** i for i in range(300)]
        short, long_ = self.scores(closes)
        self.assertLess(long_, -20)
        self.assertLess(short, 0)

    def test_scores_stay_in_range(self):
        for closes in ([100 * 1.02 ** i for i in range(300)], [100 * 0.98 ** i for i in range(300)]):
            for score in self.scores(closes):
                self.assertTrue(-100 <= score <= 100)

    def test_insufficient_history_is_none(self):
        bars = make_bars([100.0 + i for i in range(40)])
        ind = signals.build_indicators(bars)
        self.assertIsNone(signals.long_score(ind, 39)[0])
        self.assertIsNone(signals.short_score(ind, 39)[0])

    def test_readings_use_price_and_volume_rules_only_with_no_news_part(self):
        closes = [100 + math.sin(i / 5) * 3 for i in range(120)]
        ind = signals.build_indicators(make_bars(closes))
        i = len(closes) - 1
        detail = signals.short_detail(ind, i)
        self.assertNotIn("news", [r["key"] for r in detail["reasons"]])
        self.assertNotIn("news", signals.SHORT_WEIGHTS)
        self.assertNotIn("news", signals.LONG_WEIGHTS)
        self.assertEqual(signals.short_score(ind, i), (detail["score"], detail["reasons"]))
        with self.assertRaises(TypeError):
            signals.short_detail(ind, i, news=(1.0, "text"))

    def test_reasons_have_tone(self):
        ind = signals.build_indicators(make_bars([100 * 1.004 ** i for i in range(300)]))
        score, reasons = signals.long_score(ind, 299)
        self.assertTrue(reasons)
        self.assertTrue(all(r["tone"] in ("pos", "neg", "neutral") and r["text"] for r in reasons))

    def test_pressure_labels(self):
        buying = make_bars([100 * 1.003 ** i for i in range(60)])
        buying["h"] = [c * 1.01 for c in buying["c"]]
        buying["l"] = [c * 0.99 for c in buying["c"]]
        ind = signals.build_indicators(buying)
        self.assertEqual(signals.buy_sell_pressure(ind, 59)["label"], "Buying pressure")
        selling = make_bars([100 * 0.997 ** i for i in range(60)])
        selling["h"] = [c * 1.01 for c in selling["c"]]
        selling["l"] = [c * 0.99 for c in selling["c"]]
        ind = signals.build_indicators(selling)
        self.assertEqual(signals.buy_sell_pressure(ind, 59)["label"], "Selling pressure")

    def test_pressure_missing_without_volume(self):
        bars = make_bars([100.0 + i for i in range(60)], volume=0.0)
        self.assertIsNone(signals.buy_sell_pressure(signals.build_indicators(bars), 59))

    def test_stop_loss(self):
        stop = signals.stop_loss(100.0, 2.0)
        self.assertAlmostEqual(stop["price"], 96.0)
        self.assertAlmostEqual(stop["pct"], -4.0)
        self.assertIsNone(signals.stop_loss(100.0, None))
        self.assertIsNone(signals.stop_loss(1.0, 5.0))


class BacktestTests(unittest.TestCase):
    def bars(self, n=300):
        closes = [100 * (1 + 0.002 * math.sin(i / 7) + 0.001) ** 1 for i in range(n)]
        walk = [100.0]
        for i in range(1, n):
            walk.append(walk[-1] * (1.001 + 0.01 * math.sin(i / 5)))
        return make_bars(walk)

    def test_always_long_without_costs_equals_buy_and_hold(self):
        bars = self.bars()
        result = bt.backtest(bars, lambda i: 100, start=50, cost=0.0)
        self.assertAlmostEqual(result["total_return"], result["buy_hold_return"], places=9)
        self.assertEqual(result["trades"], 1)
        self.assertAlmostEqual(result["exposure"], 1.0)

    def test_costs_reduce_return(self):
        bars = self.bars()
        free = bt.backtest(bars, lambda i: 100, start=50, cost=0.0)["total_return"]
        paid = bt.backtest(bars, lambda i: 100, start=50, cost=0.002)["total_return"]
        self.assertLess(paid, free)

    def test_never_long_stays_flat(self):
        result = bt.backtest(self.bars(), lambda i: -100, start=50)
        self.assertEqual(result["trades"], 0)
        self.assertAlmostEqual(result["total_return"], 0.0)
        self.assertEqual(result["max_drawdown"], 0.0)
        self.assertIsNone(result["win_rate"])

    def test_score_never_sees_the_last_bar(self):
        bars = self.bars()
        seen = []
        bt.backtest(bars, lambda i: seen.append(i) or 0, start=50)
        self.assertEqual(max(seen), len(bars["c"]) - 2)

    def test_too_short_returns_none(self):
        self.assertIsNone(bt.backtest(self.bars(80), lambda i: 100, start=50))

    def test_flags_and_oos_present(self):
        result = bt.backtest(self.bars(), lambda i: 100 if i % 40 < 20 else -100, start=50)
        self.assertTrue(result["few_trades"] or result["trades"] >= bt.FEW_TRADES)
        for key in ("total_return", "buy_hold_return", "max_drawdown", "sharpe", "trades"):
            self.assertIn(key, result["oos"])
        json.dumps(result, allow_nan=False)

    def test_known_trade_return(self):
        closes = [100.0] * 61 + [110.0] * 59
        bars = make_bars(closes)
        bars["o"] = closes
        result = bt.backtest(bars, lambda i: 100 if i == 59 else -100, start=50, cost=0.0)
        self.assertEqual(result["trades"], 1)
        self.assertAlmostEqual(result["expectancy"], 0.10, places=9)
        self.assertEqual(result["win_rate"], 1.0)


class PatternTests(unittest.TestCase):
    def detect(self, o, h, l, c):
        bars = {"t": [], "d": [], "o": o, "h": h, "l": l, "c": c, "v": [1000.0] * len(c)}
        return {p["name"] for p in patterns.detect_patterns(bars, signals.build_indicators(bars))}

    def flat_then(self, last_open, last_high, last_low, last_close, prev_open, prev_close):
        n = 40
        c = [100.0] * (n - 2) + [prev_close, last_close]
        o = [100.0] * (n - 2) + [prev_open, last_open]
        h = [101.0] * (n - 2) + [max(prev_open, prev_close) + 0.2, last_high]
        l = [99.0] * (n - 2) + [min(prev_open, prev_close) - 0.2, last_low]
        return o, h, l, c

    def test_bullish_engulfing(self):
        o, h, l, c = self.flat_then(98.5, 101.5, 98.3, 101.0, 100.0, 99.0)
        self.assertIn("Bullish engulfing", self.detect(o, h, l, c))

    def test_bearish_engulfing(self):
        o, h, l, c = self.flat_then(101.5, 101.7, 98.5, 99.0, 100.0, 101.0)
        self.assertIn("Bearish engulfing", self.detect(o, h, l, c))

    def test_doji(self):
        o, h, l, c = self.flat_then(100.0, 101.0, 99.0, 100.05, 100.0, 100.0)
        self.assertIn("Doji", self.detect(o, h, l, c))

    def test_breakout_detected(self):
        closes = [100.0 + (i % 3) * 0.1 for i in range(60)] + [105.0]
        bars = make_bars(closes)
        found = {p["name"] for p in patterns.detect_patterns(bars, signals.build_indicators(bars))}
        self.assertIn("20-day breakout", found)

    def test_short_history_returns_nothing(self):
        bars = make_bars([100.0] * 10)
        self.assertEqual(patterns.detect_patterns(bars, signals.build_indicators(bars)), [])

    def test_golden_cross_detected(self):
        closes = [100.0 - i * 0.2 for i in range(260)] + [48.0 + i * 3 for i in range(60)]
        bars = make_bars(closes)
        ind = signals.build_indicators(bars)
        found = []
        for end in range(len(closes) - 60, len(closes)):
            sub = {k: v[: end + 1] for k, v in bars.items()}
            found += [p["name"] for p in patterns.detect_patterns(sub, signals.build_indicators(sub))]
        self.assertIn("Golden cross", found)


class FetchTests(unittest.TestCase):
    def payload(self, **overrides):
        base = {
            "chart": {"result": [{
                "meta": {"currency": "INR", "gmtoffset": 19800, "longName": "Test Ltd", "regularMarketTime": 5},
                "timestamp": list(range(1_700_000_000, 1_700_000_000 + 86400 * 70, 86400)),
                "indicators": {"quote": [{
                    "open": [10.0] * 70, "high": [11.0] * 70, "low": [9.0] * 70,
                    "close": [10.5] * 70, "volume": [1000] * 70,
                }]},
                "events": {"dividends": {"1": {"date": 1_700_000_000, "amount": 2.0}}},
            }], "error": None}
        }
        base["chart"]["result"][0].update(overrides)
        return base

    def test_clean_chart_ok(self):
        out = fetch.clean_chart(self.payload(), "T")
        self.assertEqual(len(out["bars"]["c"]), 70)
        self.assertEqual(out["meta"]["name"], "Test Ltd")
        self.assertEqual(len(out["dividends"]), 1)

    def test_drops_null_and_invalid_bars(self):
        p = self.payload()
        quote = p["chart"]["result"][0]["indicators"]["quote"][0]
        quote["close"][3] = None
        quote["low"][4] = 12.0
        quote["open"][5] = 0
        out = fetch.clean_chart(p, "T")
        self.assertEqual(len(out["bars"]["c"]), 67)

    def test_null_volume_stays_missing(self):
        p = self.payload()
        p["chart"]["result"][0]["indicators"]["quote"][0]["volume"][0] = None
        self.assertIsNone(fetch.clean_chart(p, "T")["bars"]["v"][0])

    def test_errors(self):
        with self.assertRaises(fetch.FetchError):
            fetch.clean_chart({"chart": {"result": None, "error": {"description": "Not Found"}}}, "T")
        with self.assertRaises(fetch.FetchError):
            fetch.clean_chart(None, "T")
        with self.assertRaises(fetch.FetchError):
            fetch.clean_chart(self.payload(timestamp=[1, 2, 3]), "T")
        short = self.payload()
        for key in ("open", "high", "low", "close", "volume"):
            short["chart"]["result"][0]["indicators"]["quote"][0][key] = [10.0] * 5
        short["chart"]["result"][0]["timestamp"] = list(range(5))
        with self.assertRaises(fetch.FetchError):
            fetch.clean_chart(short, "T")

    def short_payload(self, bars):
        p = self.payload()
        for key in ("open", "high", "low", "close", "volume"):
            p["chart"]["result"][0]["indicators"]["quote"][0][key] = [10.0] * bars
        p["chart"]["result"][0]["timestamp"] = list(range(1_700_000_000, 1_700_000_000 + 86400 * bars, 86400))
        return p

    def test_a_short_series_has_its_own_error_type(self):
        with self.assertRaises(fetch.ShortSeriesError):
            fetch.clean_chart(self.short_payload(5), "T")
        with self.assertRaises(fetch.ShortSeriesError) as caught:
            fetch.clean_chart(self.short_payload(3), "T", 10)
        self.assertIsInstance(caught.exception, fetch.FetchError)

    def test_a_too_short_answer_is_retried_once_and_can_recover(self):
        answers = [json.dumps(self.short_payload(1)).encode(), json.dumps(self.payload()).encode()]
        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            return answers[len(calls) - 1]

        with patch("engine.fetch.http_get", side_effect=fake_get), patch("engine.fetch.time.sleep") as pause:
            chart = fetch.fetch_chart("NEW.NS", "5y", 5)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(chart["bars"]["c"]), 70)
        pause.assert_called_once()

    def test_still_too_short_after_the_retry_gives_up(self):
        short = json.dumps(self.short_payload(1)).encode()
        with patch("engine.fetch.http_get", return_value=short) as get, patch("engine.fetch.time.sleep"):
            with self.assertRaises(fetch.ShortSeriesError):
                fetch.fetch_chart("NEW.NS", "5y", 5)
        self.assertEqual(get.call_count, 2)

    def test_other_failures_are_not_retried(self):
        with patch("engine.fetch.http_get", return_value=b"not json") as get, patch("engine.fetch.time.sleep") as pause:
            with self.assertRaises(fetch.FetchError):
                fetch.fetch_chart("X", "5y", 5)
        self.assertEqual(get.call_count, 1)
        pause.assert_not_called()
        missing = json.dumps({"chart": {"result": None, "error": {"description": "Not Found"}}}).encode()
        with patch("engine.fetch.http_get", return_value=missing) as get:
            with self.assertRaises(fetch.FetchError):
                fetch.fetch_chart("X", "5y", 5)
        self.assertEqual(get.call_count, 1)




class CarryForwardTests(unittest.TestCase):
    TODAY = datetime(2026, 11, 14).date()

    @staticmethod
    def old(symbol, as_of):
        return {"symbol": symbol, "name": symbol, "as_of": as_of, "price": 10.0, "short": {"label": "Buy", "score": 30}}

    def test_a_recent_record_is_kept_and_marked(self):
        from engine import build
        previous = {"A": self.old("A", "2026-11-13")}
        carried, failed = build.carry_forward([{"symbol": "A", "error": "A: only 1 usable bars"}], previous, self.TODAY)
        self.assertEqual(failed, [])
        self.assertEqual(carried[0]["symbol"], "A")
        self.assertTrue(carried[0]["carried"])
        self.assertEqual(carried[0]["short"]["label"], "Buy")

    def test_old_headlines_are_not_carried_as_if_they_were_current(self):
        from engine import build
        record = self.old("A", "2026-11-13")
        record["news"] = {"items": [{"title": "x", "age_min": 95}], "fresh": [{"title": "x", "age_min": 95}], "error": False}
        previous = {"A": record}
        carried, _ = build.carry_forward([{"symbol": "A", "error": "x"}], previous, self.TODAY)
        self.assertEqual(carried[0]["news"]["fresh"], [])
        self.assertEqual(carried[0]["news"]["items"], [])
        self.assertTrue(carried[0]["news"]["error"])
        self.assertEqual(len(previous["A"]["news"]["fresh"]), 1, "the saved record is not changed")

    def test_the_saved_record_itself_is_not_changed(self):
        from engine import build
        previous = {"A": self.old("A", "2026-11-13")}
        build.carry_forward([{"symbol": "A", "error": "x"}], previous, self.TODAY)
        self.assertNotIn("carried", previous["A"])

    def test_old_unknown_and_broken_records_stay_failed(self):
        from engine import build
        previous = {"OLD": self.old("OLD", "2026-11-05"), "FUTURE": self.old("FUTURE", "2026-11-20"),
                    "BAD": {"symbol": "BAD", "as_of": "not a date"}, "NODATE": {"symbol": "NODATE"}}
        errors = [{"symbol": s, "error": "x"} for s in ("OLD", "FUTURE", "BAD", "NODATE", "NEVER")]
        carried, failed = build.carry_forward(errors, previous, self.TODAY)
        self.assertEqual(carried, [])
        self.assertEqual([e["symbol"] for e in failed], ["OLD", "FUTURE", "BAD", "NODATE", "NEVER"])

    def test_the_age_limit_is_inclusive(self):
        from engine import build
        edge = f"2026-11-{14 - build.CARRY_MAX_AGE_DAYS:02d}"
        carried, _ = build.carry_forward([{"symbol": "E", "error": "x"}], {"E": self.old("E", edge)}, self.TODAY)
        self.assertEqual(len(carried), 1)
        beyond = f"2026-11-{14 - build.CARRY_MAX_AGE_DAYS - 1:02d}"
        carried, failed = build.carry_forward([{"symbol": "E", "error": "x"}], {"E": self.old("E", beyond)}, self.TODAY)
        self.assertEqual((len(carried), len(failed)), (0, 1))

    def test_a_mix_is_split_correctly(self):
        from engine import build
        previous = {"A": self.old("A", "2026-11-14"), "C": self.old("C", "2026-11-12")}
        errors = [{"symbol": s, "error": "x"} for s in ("A", "B", "C")]
        carried, failed = build.carry_forward(errors, previous, self.TODAY)
        self.assertEqual([c["symbol"] for c in carried], ["A", "C"])
        self.assertEqual([e["symbol"] for e in failed], ["B"])


class FundamentalsTests(unittest.TestCase):
    def test_parse(self):
        payload = {"quoteSummary": {"result": [{
            "summaryDetail": {"trailingPE": {"raw": 25.5}, "payoutRatio": {"raw": 0.4}},
            "defaultKeyStatistics": {"priceToBook": {"raw": 3.0}},
            "financialData": {"returnOnEquity": {"raw": 0.2}, "debtToEquity": {"raw": 35.0}},
            "assetProfile": {"sector": "Technology"},
            "price": {"marketCap": {"raw": 1_000_000}},
        }]}}
        out = fundamentals.parse_summary(payload)
        self.assertEqual(out["pe"], 25.5)
        self.assertAlmostEqual(out["debt_to_equity"], 0.35)
        self.assertEqual(out["sector"], "Technology")
        self.assertIsNone(out["forward_pe"])
        self.assertEqual(out["market_cap"], 1_000_000)

    def test_parse_empty_and_junk(self):
        self.assertEqual(fundamentals.parse_summary(None), {})
        self.assertEqual(fundamentals.parse_summary({"quoteSummary": {"result": None}}), {})
        out = fundamentals.parse_summary({"quoteSummary": {"result": [{"summaryDetail": {"trailingPE": {}}}]}})
        self.assertIsNone(out["pe"])


RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title>Acme shares surge after record profit - Example Wire</title><link>https://example.com/a</link>
<pubDate>Sat, 14 Nov 2026 06:00:00 GMT</pubDate><source url="https://example.com">Example Wire</source></item>
<item><title>Acme faces fraud probe, stock plunges - Daily News</title><link>https://example.com/b</link>
<pubDate>Sat, 14 Nov 2026 09:30:00 GMT</pubDate><source url="https://example.com">Daily News</source></item>
<item><title>Bank of Acme opens new branch</title><link>javascript:alert(1)</link>
<pubDate>not a date</pubDate></item>
</channel></rss>"""


class NewsTests(unittest.TestCase):
    NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)

    def test_parse_rss(self):
        items = news.parse_rss(RSS, self.NOW)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["title"], "Acme faces fraud probe, stock plunges")
        self.assertEqual(items[0]["age_min"], 30)
        self.assertEqual(items[-1]["age_min"], None)
        self.assertEqual(items[-1]["link"], "")

    def test_relevance_requires_the_company_name(self):
        rel = news.is_relevant
        self.assertFalse(rel("Apple unveils new iPhone", "Apple"), "one shared word and no business wording is not enough")
        self.assertTrue(rel("Apple shares rise after iPhone launch", "Apple", "AAPL"))
        self.assertFalse(rel("3 Favorite Buffett Stocks Hit Record Highs As Nvidia Sinks", "Apple"))
        self.assertTrue(rel("State Bank of India raises lending rate", "State Bank of India", "SBIN"))
        self.assertFalse(rel("Online fraud drains woman's account; bank ordered to pay", "State Bank of India", "SBIN"))
        self.assertFalse(rel("India's balance of payments surplus soars", "Bank of Baroda", "BANKBARODA"))
        self.assertTrue(rel("Baroda shares rally after results", "Bank of Baroda", "BANKBARODA"))
        self.assertTrue(rel("TCS wins large deal", "Tata Consultancy Services", "TCS"))
        self.assertFalse(rel("Tata Motors shares fall", "Tata Steel", "TATASTEEL"))
        self.assertTrue(rel("ITC announces dividend", "ITC", "ITC"))
        self.assertFalse(rel("Marketing campaign launches", "ITC", "ITC"))

    def test_a_surname_or_place_sharing_the_name_is_not_the_company(self):
        rel = news.is_relevant
        self.assertFalse(rel("The Gary Trent Jr. Investigation Could DESTROY the Franchise", "Trent", "TRENT", "Yahoo Sports"))
        self.assertFalse(rel("Gary Trent scores 30 as team wins", "Trent", "TRENT"))
        self.assertFalse(rel("Trent Alexander-Arnold injury probe", "Trent", "TRENT", "Sky Sports"))
        self.assertFalse(rel("Mars mission to Titan announced", "Titan Company", "TITAN"))
        self.assertFalse(rel("Overreliance on AI is a risk", "Reliance Industries", "RELIANCE"))
        self.assertFalse(rel("Baroda city floods after heavy rain", "Bank of Baroda", "BANKBARODA"))
        self.assertFalse(rel("Lakers star in NBA playoffs probe", "Lakers Corp", "LAKE"))

    def test_the_same_names_count_when_the_headline_is_business_news(self):
        rel = news.is_relevant
        self.assertTrue(rel("Trent shares jump after Q2 results", "Trent", "TRENT"))
        self.assertTrue(rel("Titan Company shares rally on festive demand", "Titan Company", "TITAN"))
        self.assertTrue(rel("Reliance plans $4.6bn investment in coal-to-gas project", "Reliance Industries", "RELIANCE"))
        self.assertTrue(rel("Mastercard (MA) Opens Singapore Innovation Centre", "Mastercard", "MA"))
        self.assertTrue(rel("Microsoft outage eases, but recovery timeline remains unclear", "Microsoft", "MSFT"))
        self.assertTrue(rel("Nvidia exposed to possible lawsuits", "Nvidia", "NVDA"))
        self.assertTrue(rel("TCS wins large deal", "Tata Consultancy Services", "TCS"))

    def test_the_broker_named_in_a_rating_headline_is_not_the_subject(self):
        rel = news.is_relevant
        self.assertFalse(rel("Ecolab stock upgraded by Wells Fargo on 2027 growth case", "Wells Fargo", "WFC"))
        self.assertFalse(rel("Acme downgraded by Jefferies, shares fall", "Jefferies Financial Group", "JEF"))
        self.assertTrue(rel("Wells Fargo shares rise after earnings beat", "Wells Fargo", "WFC"))

    def test_roundups_naming_many_companies_do_not_count_for_any_one(self):
        rel = news.is_relevant
        self.assertFalse(rel("Upcoming dividend, stock split, buyback record date next week: MRF, SCI, PFC, PTC", "Power Finance Corporation", "PFC"))
        self.assertFalse(rel("Stocks to watch today: PFC shares, dividend news", "Power Finance Corporation", "PFC"))
        self.assertTrue(rel("PFC shares rise after Q2 results", "Power Finance Corporation", "PFC"))
        self.assertTrue(rel("TCS wins large deal", "Tata Consultancy Services", "TCS"))

    def test_headlines_about_another_company_do_not_count_for_the_one_they_mention(self):
        rel = news.is_relevant
        self.assertFalse(rel("Ecolab (ECL) Shares Rise After Wells Fargo Upgrade Highlighting Strategic Acquisition", "Wells Fargo", "WFC"))
        self.assertFalse(rel("Reinsurance Group (RGA) Gets a Buy from Wells Fargo", "Wells Fargo", "WFC"))
        self.assertFalse(rel("Merck KGaA (XTRA:MRK) Stock Looks About Right On FDA Approval News", "Merck", "MRK"))
        self.assertFalse(rel("Grupo Televisa stock: AT&T Mexico deal awaits 2027 approvals", "AT&T", "T"))
        self.assertFalse(rel("OpenAI Introduces ChatGPT Wallet With Visa, Mastercard, Amex - Lets AI Agents Make Purchases", "Mastercard", "MA"))
        self.assertFalse(rel("Rs 231.80 Dividend, 1:10 Stock Split, 1 Buyback: 31 stocks to watch", "Power Finance Corporation", "PFC"))

    def test_headlines_that_are_about_the_company_still_count(self):
        rel = news.is_relevant
        self.assertTrue(rel("Wells Fargo Eyes $50B NII in 2026", "Wells Fargo", "WFC"))
        self.assertTrue(rel("Wells Fargo (WFC) shares rise after earnings beat", "Wells Fargo", "WFC"))
        self.assertTrue(rel("Merck & Co. (MRK) Stock: Rises as EU Backs Expanded RSV Drug Approval", "Merck", "MRK"))
        self.assertTrue(rel("AT&T (T) shares rise after earnings", "AT&T", "T"))
        self.assertTrue(rel("Amazon stock: AWS sets new AgentCore runtime as default", "Amazon", "AMZN"))
        self.assertTrue(rel("Walmart (NASDAQ:WMT) Shares Up 1.5% on Analyst Upgrade", "Walmart", "WMT"))
        self.assertTrue(rel("Berkshire's Buyback Spree Masks a Thinner Insurance Haul (BRK.B)", "Berkshire Hathaway", "BRK-B"))

    def test_ages_are_written_for_people(self):
        self.assertEqual(news.age_text(5), "5 min ago")
        self.assertEqual(news.age_text(89), "89 min ago")
        self.assertEqual(news.age_text(876), "15 h ago")
        self.assertEqual(news.age_text(47 * 60), "47 h ago")
        self.assertEqual(news.age_text(60 * 24 * 4), "4 d ago")
        self.assertEqual(news.age_text(None), "")

    def test_headlines_carry_no_tone_or_sentiment(self):
        for item in news.parse_rss(RSS, self.NOW):
            self.assertEqual(set(item), {"title", "link", "source", "ts", "age_min"})
        for name in ("headline_sentiment", "news_score", "strong_alerts"):
            self.assertFalse(hasattr(news, name), name)

    def test_only_headlines_about_the_company_from_the_last_few_hours_are_fresh(self):
        item = lambda age, relevant=True: {"title": "x", "relevant": relevant, "age_min": age}
        found = news.fresh_headlines([item(30), item(5 * 60), item(7 * 60), item(14 * 60), item(None), item(10, False)])
        self.assertEqual([i["age_min"] for i in found], [30, 300])

    def test_the_company_must_be_the_subject_of_the_headline(self):
        rel = news.is_relevant
        self.assertFalse(rel("ICICI Lombard raises Axis Bank stake in India", "ICICI Bank", "ICICIBANK"), "ICICI Lombard is not ICICI Bank")
        self.assertFalse(rel("Watch | Pope Leo XIV flies to Andes town by helicopter, once reached it in a Mahindra", "Mahindra & Mahindra", "M&M"))
        self.assertFalse(rel("SENSEX up 400 pts, NIFTY50 hovers around 25,200 in early trade; Eicher Motors, Airtel, ITC in focus", "Bharti Airtel", "BHARTIARTL"))
        self.assertFalse(rel("Eternal, Infosys & Wipro: Three Stocks, Three Different Trading Opportunities", "Wipro", "WIPRO"))
        self.assertFalse(rel("Amazon vs. Target: Which Stock Is the Better Portfolio Addition?", "Amazon", "AMZN"))
        self.assertFalse(rel("IBM Nov 2026 207.500 put (IBM261120P00207500) stock price, news, quote and history", "IBM", "IBM"))

    def test_a_company_that_is_only_the_customer_is_not_the_subject(self):
        rel = news.is_relevant
        self.assertFalse(rel("Eco Wave Power Gets BPCL Order for Mumbai Study", "Bharat Petroleum", "BPCL"))
        self.assertFalse(rel("Tata Steel wins order from Coal India for rakes", "Coal India", "COALINDIA"))
        self.assertTrue(rel("BPCL wins order for new terminal", "Bharat Petroleum", "BPCL"))
        self.assertTrue(rel("Bharat Electronics bags new defence orders worth Rs 619 crore", "Bharat Electronics", "BEL"))

    def test_filing_listings_are_not_news(self):
        rel = news.is_relevant
        self.assertFalse(rel("Form 4 Apple Inc For: 15 November By Investing.com", "Apple", "AAPL"))
        self.assertFalse(rel("Form 144 Meta Platforms For: 15 November By Investing.com", "Meta Platforms", "META"))

    def test_clear_company_headlines_still_count_under_the_subject_rule(self):
        rel = news.is_relevant
        self.assertTrue(rel("Citi maintains Buy rating on Eicher Motors with Rs 9,500 target price", "Eicher Motors", "EICHERMOT"))
        self.assertTrue(rel("Hindalco shares fall 1% after Novelis announces $265-million sale of China units", "Hindalco Industries", "HINDALCO"))
        self.assertTrue(rel("BEL share price: Defence PSU stock in focus on Rs 619 crore order win", "Bharat Electronics", "BEL"))
        self.assertTrue(rel("Intel sued by shareholders following 29% stock plunge", "Intel", "INTC"))
        self.assertTrue(rel("ICICI Bank shares rise after Q2 results", "ICICI Bank", "ICICIBANK"))
        self.assertTrue(rel("S&P says Adani Ports can absorb INR 27,000 crore Evos acquisition costs", "Adani Ports and SEZ", "ADANIPORTS"))

    def test_a_headline_about_two_listed_companies_is_credited_to_neither(self):
        def rec(symbol, name, items):
            return {"symbol": symbol, "name": name, "news": {"items": items, "fresh": items}}
        shared = {"title": "HUDCO, PFC raise bonds", "link": "https://x/shared", "relevant": True, "age_min": 10}
        own_a = {"title": "PFC results", "link": "https://x/a", "relevant": True, "age_min": 20}
        own_b = {"title": "HUDCO shares rise on plant", "link": "https://x/b", "relevant": True, "age_min": 30}
        records = [rec("PFC.NS", "Power Finance", [dict(shared), dict(own_a)]), rec("HUDCO.NS", "HUDCO", [dict(shared), dict(own_b)])]
        news.keep_stock_specific(records)
        self.assertEqual([i["title"] for i in records[0]["news"]["fresh"]], ["PFC results"])
        self.assertEqual([i["title"] for i in records[1]["news"]["fresh"]], ["HUDCO shares rise on plant"])
        self.assertFalse(records[0]["news"]["items"][0]["relevant"])

    def test_two_share_classes_of_one_company_share_its_news(self):
        item = {"title": "Alphabet results", "link": "https://x/g", "relevant": True, "age_min": 10}
        records = [{"symbol": s, "name": "Alphabet", "news": {"items": [dict(item)], "fresh": [dict(item)]}} for s in ("GOOG", "GOOGL")]
        news.keep_stock_specific(records)
        self.assertTrue(all(len(r["news"]["fresh"]) == 1 for r in records))

    def test_headlines_about_another_company_are_not_marked_relevant(self):
        items = news.parse_rss(RSS, self.NOW)
        news.mark_relevance(items, "Somebody Else Corp", "SOME")
        self.assertTrue(all(i["relevant"] is False for i in items))
        self.assertEqual(news.fresh_headlines(items), [])
        items = news.mark_relevance(news.parse_rss(RSS, self.NOW), "Acme", "ACME")
        self.assertTrue(news.fresh_headlines(items))

    def test_rejects_dtd(self):
        with self.assertRaises(fetch.FetchError):
            news.parse_rss('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss/>', self.NOW)

    def test_rejects_garbage(self):
        with self.assertRaises(fetch.FetchError):
            news.parse_rss("<html>not rss", self.NOW)


if __name__ == "__main__":
    unittest.main()


class MorePatternTests(unittest.TestCase):
    def names(self, o, h, l, c):
        bars = {"t": [], "d": [], "o": o, "h": h, "l": l, "c": c, "v": [1000.0] * len(c)}
        return {p["name"] for p in patterns.detect_patterns(bars, signals.build_indicators(bars))}

    def base(self, n=40):
        return [100.0] * n, [101.0] * n, [99.0] * n, [100.0] * n

    def test_morning_star(self):
        o, h, l, c = self.base()
        o[-3], c[-3], h[-3], l[-3] = 104.0, 100.0, 104.2, 99.8      # big red
        o[-2], c[-2], h[-2], l[-2] = 98.8, 99.0, 99.3, 98.5         # small, below the first close
        o[-1], c[-1], h[-1], l[-1] = 99.2, 103.0, 103.2, 99.0       # green back above the middle (102)
        self.assertIn("Morning star", self.names(o, h, l, c))

    def test_three_white_soldiers(self):
        o, h, l, c = self.base()
        for k, (op, cl) in zip((-3, -2, -1), ((100.0, 102.0), (101.0, 104.0), (103.0, 106.0))):
            o[k], c[k], h[k], l[k] = op, cl, cl + 0.1, op - 0.1
        self.assertIn("Three white soldiers", self.names(o, h, l, c))

    def test_gap_up_and_down(self):
        o, h, l, c = self.base()
        o[-1], h[-1], l[-1], c[-1] = 103.0, 104.0, 102.5, 103.5
        self.assertIn("Gap up", self.names(o, h, l, c))
        o, h, l, c = self.base()
        o[-1], h[-1], l[-1], c[-1] = 97.0, 97.5, 96.0, 96.5
        self.assertIn("Gap down", self.names(o, h, l, c))

    def test_tight_range_and_rising_lows(self):
        o, h, l, c = self.base()
        self.assertIn("Tight range", self.names(o, h, l, c))
        o, h, l, c = self.base()
        for step, k in enumerate((-4, -3, -2, -1), 1):
            h[k], l[k], c[k], o[k] = 101.0 + step, 99.0 + step, 100.5 + step, 100.0 + step
        self.assertIn("Higher highs and lows", self.names(o, h, l, c))

    def test_volume_surge_needs_volume_and_a_move(self):
        o, h, l, c = self.base()
        v = [1000.0] * 40
        v[-1], c[-1], h[-1] = 3000.0, 103.0, 103.2
        bars = {"t": [], "d": [], "o": o, "h": h, "l": l, "c": c, "v": v}
        found = {p["name"] for p in patterns.detect_patterns(bars, signals.build_indicators(bars))}
        self.assertIn("Volume surge", found)
        v[-1] = None
        bars["v"] = v
        self.assertNotIn("Volume surge", {p["name"] for p in patterns.detect_patterns(bars, signals.build_indicators(bars))})

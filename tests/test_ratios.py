import unittest
from datetime import date, timedelta

from engine import catalog, ratios


def annual(name, values, end="2025-03-31"):
    """Annual rows ending at `end`, one a year apart, oldest first."""
    last = date.fromisoformat(end)
    rows = [{"date": date(last.year - (len(values) - 1 - k), last.month, last.day).isoformat(), "value": v} for k, v in enumerate(values)]
    return {name: rows}


def statements(**series):
    return {"annual": {k: v for s in series.values() for k, v in s.items()}}


class GrowthTests(unittest.TestCase):
    def test_cagr_is_worked_out_between_the_two_ends(self):
        rows = ratios._rows(statements(a=annual("revenue", [100, 110, 121, 133.1])), "revenue")
        self.assertEqual(ratios.cagr(rows, 3), 10.0)

    def test_no_rate_from_a_loss_or_into_a_loss_or_without_enough_years(self):
        self.assertIsNone(ratios.cagr(ratios._rows(statements(a=annual("net_income", [-5, 10, 20, 30])), "net_income"), 3))
        self.assertIsNone(ratios.cagr(ratios._rows(statements(a=annual("net_income", [5, 10, 20, -30])), "net_income"), 3))
        self.assertIsNone(ratios.cagr(ratios._rows(statements(a=annual("revenue", [100, 120, 140])), "revenue"), 3), "only three years of figures")
        self.assertIsNone(ratios.cagr([], 3))

    def test_a_stale_newest_figure_gives_no_rate(self):
        rows = ratios._rows(statements(a=annual("revenue", [100, 110, 121, 133.1], end="2022-03-31")), "revenue")
        self.assertEqual(ratios.cagr(rows, 3), 10.0)
        self.assertIsNone(ratios.cagr(rows, 3, today=date(2026, 11, 26)))

    def test_years_the_profit_rose_needs_an_unbroken_run(self):
        rows = ratios._rows(statements(a=annual("net_income", [10, 12, 11, 15])), "net_income")
        self.assertEqual(ratios.profit_up_years(rows), 2)
        self.assertIsNone(ratios.profit_up_years(rows[:3]), "three years are only two changes")
        gap = [rows[0], rows[1], rows[3]] + [(rows[3][0] + timedelta(days=365), 20.0)]
        self.assertIsNone(ratios.profit_up_years(gap), "a missing year breaks the run")


class CashAndDebtTests(unittest.TestCase):
    def test_cash_flow_over_profit_uses_the_same_year_and_a_positive_profit(self):
        st = statements(a=annual("net_income", [10, 20]), b=annual("operating_cash_flow", [12, 30]))
        self.assertEqual(ratios.ocf_to_profit(st), 1.5)
        self.assertIsNone(ratios.ocf_to_profit(statements(a=annual("net_income", [10, -20]), b=annual("operating_cash_flow", [12, 30]))))
        self.assertIsNone(ratios.ocf_to_profit(statements(a=annual("net_income", [10, 20]), b=annual("operating_cash_flow", [12, 30], end="2023-03-31"))), "different years")

    def test_roce_is_operating_income_over_equity_plus_debt(self):
        st = statements(a=annual("operating_income", [20]), b=annual("equity", [80]), c=annual("total_debt", [20]))
        self.assertEqual(ratios.roce_approx(st), 20.0)
        self.assertEqual(ratios.roce_approx(statements(a=annual("operating_income", [20]), b=annual("equity", [100]))), 20.0, "no debt figure means no debt")
        self.assertIsNone(ratios.roce_approx(statements(a=annual("operating_income", [20]), b=annual("equity", [-30]), c=annual("total_debt", [10]))))

    def test_debt_and_price_ratios_need_positive_denominators(self):
        self.assertEqual(ratios.debt_to_ebitda({"total_debt": 300.0, "ebitda": 100.0}), 3.0)
        self.assertIsNone(ratios.debt_to_ebitda({"total_debt": 300.0, "ebitda": -5.0}))
        self.assertEqual(ratios.price_to_fcf({"market_cap": 1000.0, "free_cash_flow": 50.0}), 20.0)
        self.assertIsNone(ratios.price_to_fcf({"market_cap": 1000.0, "free_cash_flow": -50.0}))
        self.assertIsNone(ratios.price_to_fcf({}))

    def test_a_financial_company_is_flagged(self):
        self.assertTrue(ratios.is_financial({"sector": "Financial Services"}))
        self.assertFalse(ratios.is_financial({"sector": "Technology"}))
        self.assertFalse(ratios.is_financial(None))


class RelativeStrengthTests(unittest.TestCase):
    def series(self, n=200):
        start = date(2025, 1, 1)
        return [(start + timedelta(days=k)).isoformat() for k in range(n)]

    def test_stock_return_minus_index_return_over_126_sessions(self):
        dates = self.series()
        closes = [100.0] * 200
        closes[-127], closes[-1] = 100.0, 120.0                              # +20%
        bench = {d: 1000.0 for d in dates}
        bench[dates[-1]] = 1050.0                                            # +5%
        self.assertEqual(ratios.relative_strength(dates, closes, bench), 15.0)

    def test_none_without_enough_history_or_a_benchmark(self):
        dates = self.series(100)
        self.assertIsNone(ratios.relative_strength(dates, [1.0] * 100, {d: 1.0 for d in dates}))
        dates = self.series()
        self.assertIsNone(ratios.relative_strength(dates, [1.0] * 200, {}))
        self.assertIsNone(ratios.relative_strength(dates, [1.0] * 200, {"2020-01-01": 5.0}), "no benchmark close near the dates")


class DeriveTests(unittest.TestCase):
    def test_derive_keeps_only_the_figures_that_exist(self):
        record = {"symbol": "A.NS", "fundamentals": {"total_debt": 200.0, "ebitda": 100.0, "market_cap": 900.0, "free_cash_flow": 30.0},
                  "statements": {"annual": {**annual("revenue", [100, 110, 121, 133.1]), **annual("net_income", [10, 12, 14, 16])}, "summary": {"yoy": {"operating_income": 12.5}}}}
        got = ratios.derive(record)
        self.assertEqual(got, {"rev_cagr3": 10.0, "profit_cagr3": 17.0, "profit_up_years": 3, "op_growth": 12.5, "debt_to_ebitda": 2.0, "price_to_fcf": 30.0})
        self.assertNotIn("rev_cagr5", got)
        self.assertEqual(ratios.derive({}), {})


class ShippedTests(unittest.TestCase):
    record = {"symbol": "A.NS", "as_of": "2026-11-20", "risk": {"beta": 1.23456, "max_drawdown": -0.31234, "annual_vol": 0.3},
              "fundamentals": {"sector": "Financial Services", "roe": 0.183456789, "ebitda": 5123456789.4, "gross_margin": 0.4, "total_debt": 9e9},
              "statements": {"annual": {**annual("revenue", [100, 110, 121, 133.1], end="2025-03-31")}}}

    def test_the_extra_row_carries_risk_worked_out_figures_and_the_financial_flag(self):
        row = catalog.extra_row(self.record)
        self.assertEqual(row["risk"], {"beta": 1.235, "max_drawdown": -0.312})
        self.assertEqual(row["calc"], {"rev_cagr3": 10.0, "debt_to_ebitda": 1.76})
        self.assertEqual(row["fin"], 1)
        self.assertEqual(row["fund"], {"roe": 0.1835, "ebitda": 5123456789, "gross_margin": 0.4}, "ratios to four places, amounts whole, and the debt amount is not shipped")

    def test_the_extra_row_of_a_plain_company_has_no_flag_and_no_empty_blocks(self):
        row = catalog.extra_row({"symbol": "B.NS", "fundamentals": {"sector": "Technology"}})
        self.assertNotIn("fin", row)
        self.assertNotIn("risk", row)
        self.assertNotIn("calc", row)

    def test_the_slim_record_keeps_the_figures_because_it_drops_the_statements(self):
        lite = catalog.lite({**self.record, "statements": {"annual": self.record["statements"]["annual"], "quarterly": {}, "summary": {}}})
        self.assertEqual(lite["calc"], {"rev_cagr3": 10.0, "debt_to_ebitda": 1.76})
        self.assertEqual(lite["fin"], 1)
        self.assertNotIn("annual", lite["statements"])


if __name__ == "__main__":
    unittest.main()

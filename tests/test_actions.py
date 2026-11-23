import json
import unittest
from datetime import date, datetime, timedelta, timezone

from engine import actions as a, actions_run, digest_feeds, feed_items as fi, feeds

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 23, 10, 20, tzinfo=IST)
TS = int(NOW.timestamp())
TODAY = "2026-11-23"


def item(desc, text, kind="nse", symbol="ABC.NS", age_h=1):
    return {"kind": kind, "symbol": symbol, "name": "Abc Ltd", "desc": desc, "title": f"Abc: {desc}", "text": text, "ts": TS - age_h * 3600, "link": "https://example.com/f.pdf"}


class AnnouncementTests(unittest.TestCase):
    def test_the_exchange_category_decides_the_type(self):
        for desc, kind in (("Amalgamation/Merger", "merger"), ("Demerger", "demerger"), ("Scheme of Arrangement", "scheme"), ("Stock split", "split"), ("Bonus", "bonus"),
                           ("Buyback", "buyback"), ("Rights Issue", "rights"), ("Record Date", "record_date"), ("Suspension of Trading", "suspension"), ("Open Offer", "open_offer")):
            self.assertEqual(a.classify_announcement(desc, "anything"), kind)

    def test_a_precise_phrase_is_used_only_in_generic_categories(self):
        self.assertEqual(a.classify_announcement("General Updates", "Notice of delisting of equity shares"), "delisting")
        self.assertEqual(a.classify_announcement("Outcome of Board Meeting", "approved the scheme of arrangement"), "scheme")
        self.assertIsNone(a.classify_announcement("Credit Rating", "rating upgraded after merger talks"), "a specific other category is not second-guessed")
        self.assertIsNone(a.classify_announcement("General Updates", "annual general meeting notice"))

    def test_records_are_made_for_official_filings_only_and_recent_ones(self):
        rows = [item("Demerger", "NCLT order on the demerger"), item("Demerger", "x", kind="media"), item("Demerger", "old", age_h=200), item("Updates", "nothing special"),
                item(None, "BSE: Scheme of arrangement approved by shareholders", kind="bse")]
        records = a.announcement_records(rows, TS)
        self.assertEqual(sorted(r["type"] for r in records), ["demerger", "scheme"])
        self.assertTrue(all(r["source"].endswith("(official)") and r["id"] and r["group"] for r in records))

    def test_the_same_filing_twice_is_one_record(self):
        self.assertEqual(len(a.announcement_records([item("Bonus", "1:1"), item("Bonus", "1:1")], TS)), 1)


class CorporateActionTests(unittest.TestCase):
    ROWS = [{"symbol": "ABC", "comp": "Abc Ltd", "subject": "Bonus 1:1", "exDate": "25-Nov-2026", "recDate": "26-Nov-2026"},
            {"symbol": "DEF", "comp": "Def Ltd", "subject": "Interim Dividend - Rs 4 Per Share", "exDate": "25-Nov-2026", "recDate": "26-Nov-2026"},
            {"symbol": "GHI", "comp": "Ghi Ltd", "subject": "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", "exDate": "01-Dec-2026", "recDate": "-"},
            {"symbol": "OLD", "comp": "Old Ltd", "subject": "Buy Back", "exDate": "01-Nov-2026", "recDate": "02-Nov-2026"}]

    def test_share_actions_are_kept_with_their_dates_and_dividends_are_not(self):
        records = a.corporate_action_records(self.ROWS, TS)
        self.assertEqual([(r["symbol"], r["type"], r["ex_date"]) for r in records], [("ABC.NS", "bonus", "2026-11-25"), ("GHI.NS", "split", "2026-12-01"), ("OLD.NS", "buyback", "2026-11-01")])

    def test_upcoming_dates_cover_the_next_week_soonest_first(self):
        rows = a.upcoming_dates(a.corporate_action_records(self.ROWS, TS), date(2026, 11, 23), 7)
        self.assertEqual([(w.isoformat(), k, r["symbol"]) for w, k, r in rows], [("2026-11-25", "ex_date", "ABC.NS"), ("2026-11-26", "record_date", "ABC.NS")], "the split on 1 December is 8 days away")
        self.assertEqual(len(a.upcoming_dates(a.corporate_action_records(self.ROWS, TS), date(2026, 11, 23), 8)), 3)


class CircuitTests(unittest.TestCase):
    def row(self, symbol, ltp, change, band, turnover=3e7, series="EQ"):
        return {"symbol": symbol, "series": series, "ltp": str(ltp), "change": str(change), "priceBand": str(band), "turnovercsv": turnover}

    def test_a_stock_at_the_band_limit_is_a_circuit_and_one_below_it_is_not(self):
        upper = {"AllSec": {"data": [self.row("UP", 120.0, 20.0, 20), self.row("NEAR", 11.0, 1.0, 20), self.row("TINY", 105.0, 5.0, 5, turnover=1e6), self.row("TWO", 102.0, 2.0, 2)]}}
        lower = {"AllSec": {"data": [self.row("DN", 95.0, -5.0, 5, series="BE"), self.row("WRONGWAY", 95.0, 5.0, 5)]}}
        records = a.circuit_records(upper, lower, TS, TODAY)
        self.assertEqual({(r["symbol"], r["type"]) for r in records}, {("UP.NS", "upper_circuit"), ("DN.NS", "lower_circuit")})
        self.assertEqual(len(records), 2)
        self.assertEqual(len(a.circuit_records(upper, lower, TS, TODAY, min_band=2, min_turnover=1e5)), 4, "a lower bar adds the 2% band and the thin stock")

    def test_a_circuit_is_one_record_per_stock_and_day(self):
        upper = {"AllSec": {"data": [self.row("UP", 120.0, 20.0, 20)]}}
        first = a.circuit_records(upper, None, TS, TODAY)[0]["id"]
        self.assertEqual(first, a.circuit_records(upper, None, TS + 900, TODAY)[0]["id"])
        self.assertNotEqual(first, a.circuit_records(upper, None, TS, "2026-11-24")[0]["id"])

    def test_bad_rows_are_skipped_without_error(self):
        bad = {"AllSec": {"data": [{"symbol": "X"}, {"symbol": "Y", "ltp": "abc", "change": "1", "priceBand": "5"}, "nonsense"]}}
        self.assertEqual(a.circuit_records(bad, bad, TS, TODAY), [])
        self.assertEqual(a.circuit_records(None, [], TS, TODAY), [])


class SurveillanceTests(unittest.TestCase):
    ASM = {"longterm": {"data": [{"symbol": "AAA", "companyName": "Aaa Ltd", "asmSurvIndicator": "Stage I", "survDesc": "LTASM"}]}, "shortterm": {"data": []}}
    GSM = [{"symbol": "GGG", "companyName": "Ggg Ltd", "gsmStage": "II", "survDesc": "GSM stage II"}]

    def test_the_first_read_only_records_the_lists_then_changes_are_reported(self):
        records, state = a.surveillance_records(self.ASM, self.GSM, None, TS, TODAY)
        self.assertEqual(records, [])
        self.assertEqual(len(state), 2)
        bigger = {"longterm": {"data": self.ASM["longterm"]["data"] + [{"symbol": "NEW", "companyName": "New Ltd", "asmSurvIndicator": "Stage II", "survDesc": "d"}]}, "shortterm": {"data": []}}
        records, state = a.surveillance_records(bigger, [], state, TS, TODAY)
        text = sorted(r["title"] for r in records)
        self.assertEqual(text, ["Added to the ASM list: Long-term Stage II", "Removed from the GSM list: Stage II"])

    def test_the_ban_file_reports_entries_and_exits(self):
        first, state = a.fo_ban_records("Securities in Ban For Trade Date 23-NOV-2026:\n1,MANAPPURAM\n2,ZEEL\n", None, TS, TODAY)
        self.assertEqual((first, state), ([], ["MANAPPURAM", "ZEEL"]))
        records, state = a.fo_ban_records("Securities in Ban For Trade Date 24-NOV-2026:\n1,MANAPPURAM\n2,SAIL\n", state, TS, TODAY)
        self.assertEqual(sorted(r["title"] for r in records), ["SAIL entered the F&O ban period", "ZEEL left the F&O ban period"])
        self.assertEqual(a.fo_ban_records("<html>error</html>", state, TS, TODAY), ([], state), "a bad answer changes nothing")


class QuoteMoveTests(unittest.TestCase):
    def test_gaps_need_liquidity_and_both_prices(self):
        q = {"open": 104.5, "prev_close": 100.0, "price": 105.0, "avg_volume": 500000, "cap": 1e10, "state": "REGULAR"}
        records = a.gap_records({"A.NS": q, "B.NS": {**q, "open": 101.0}, "C.NS": {**q, "avg_volume": 10}, "D.NS": {**q, "open": None}, "E.NS": {**q, "open": 95.0}}, {k: "IN" for k in "ABCDE" if False} | {f"{k}.NS": "IN" for k in "ABCDE"}, TS, TODAY)
        self.assertEqual({(r["symbol"], r["type"]) for r in records}, {("A.NS", "gap_up"), ("E.NS", "gap_down")})

    def test_surge_and_crash_need_ten_percent(self):
        events = [{"symbol": "A.NS", "move": 12.0, "tags": ["+12.0%"], "price": 10.0}, {"symbol": "B.NS", "move": -11.0, "tags": [], "price": 5.0}, {"symbol": "C.NS", "move": 9.0, "tags": [], "price": 1.0}]
        self.assertEqual([(r["symbol"], r["type"]) for r in a.surge_crash_records(events, {}, TS, TODAY)], [("A.NS", "surge"), ("B.NS", "crash")])


class ArchiveTests(unittest.TestCase):
    def test_the_archive_keeps_first_seen_time_drops_old_records_and_caps(self):
        old = [{"id": "1", "ts": TS - 8 * 86400, "type": "bonus"}, {"id": "2", "ts": TS - 3600, "type": "split", "title": "a"}]
        merged = a.merge_archive(old, [{"id": "2", "ts": TS, "type": "split", "title": "b"}, {"id": "3", "ts": TS, "type": "bonus"}], TS)
        self.assertEqual([r["id"] for r in merged], ["3", "2"], "the 8-day-old record is gone, newest first")
        self.assertEqual(next(r for r in merged if r["id"] == "2")["ts"], TS - 3600, "first seen time kept")
        self.assertEqual(next(r for r in merged if r["id"] == "2")["title"], "b", "newer fields win")
        self.assertEqual(len(a.merge_archive([], [{"id": str(i), "ts": TS} for i in range(900)], TS, cap=800)), 800)


class AlertItemTests(unittest.TestCase):
    def records(self):
        return (a.announcement_records([item("Demerger", "NCLT order on the demerger")], TS)
                + a.circuit_records({"AllSec": {"data": [{"symbol": "UP", "series": "EQ", "ltp": "120", "change": "20", "priceBand": "20", "turnovercsv": 3e7}]}}, None, TS, TODAY)
                + a.surveillance_records({"longterm": {"data": [{"symbol": "N", "asmSurvIndicator": "Stage I"}]}, "shortterm": {}}, [], [], TS, TODAY)[0])

    def test_the_first_run_only_remembers_and_later_runs_alert_each_record_once(self):
        records = self.records()
        items, seen = fi.action_alert_items(records, None, TS, baseline=True)
        self.assertEqual(items, [])
        self.assertEqual(len(seen), len(records))
        items, seen = fi.action_alert_items(records, seen, TS + 60)
        self.assertEqual(items, [], "already seen")
        items, _ = fi.action_alert_items(records, {}, TS)
        self.assertEqual(sorted((i["feed"], i["kind"]) for i in items), [("circuits", "line"), ("corp_actions", "entry"), ("surveillance", "line")])

    def test_removals_from_surveillance_lists_are_not_alerted(self):
        records, _ = a.surveillance_records({"longterm": {"data": []}, "shortterm": {}}, [], ["asm|N|Long-term Stage I"], TS, TODAY)
        self.assertEqual(fi.action_alert_items(records, {}, TS)[0], [])

    def test_each_feed_is_capped_per_run(self):
        many = [{"id": str(i), "type": "upper_circuit", "label": "Upper circuit", "symbol": f"S{i}.NS", "name": f"S{i}", "band": 5.0, "price": 10.0, "move_pct": 5.0, "turnover": 2e7, "title": "t", "source": "s", "date": TODAY} for i in range(40)]
        items, _ = fi.action_alert_items(many, {}, TS)
        self.assertEqual(len(items), fi.LIMITS["circuits"])

    def test_the_messages_render_with_hashtags_and_the_new_feeds_exist(self):
        items, _ = fi.action_alert_items(self.records(), {}, TS)
        for feed in ("circuits", "corp_actions", "surveillance", "gaps", "action_dates"):
            self.assertIn(feed, feeds.settings())
        text = " ".join(digest_feeds.render_feed([i for i in items if i["feed"] == "corp_actions"], [None], TS, "Corporate actions", ["#CorporateActions"])[0][0].split())
        self.assertIn("#ABC #Demerger #CorporateAction", text)
        line = digest_feeds.render_feed([i for i in items if i["feed"] == "circuits"], [None], TS, "Circuit hits", ["#Circuits"])[0][0]
        self.assertIn("UPPER CIRCUIT", line)
        self.assertIn("#UpperCircuit", line)

    def test_ex_dates_are_listed_for_the_week_ahead(self):
        records = a.corporate_action_records(CorporateActionTests.ROWS, TS)
        entries = fi.action_dates_entries(records, date(2026, 11, 23))
        self.assertEqual(len(entries), 2)
        self.assertIn("ex-date 25 Nov", entries[0]["heading"])


class RiseCrashTests(unittest.TestCase):
    def test_movers_are_split_into_rising_and_falling_with_surge_and_crash_tags(self):
        movers = [{"kind": "mover", "symbol": "A.NS", "name": "A", "tags": ["+12.0%"], "price": 10.0, "currency": "INR", "move": 12.0},
                  {"kind": "mover", "symbol": "B.NS", "name": "B", "tags": ["-11.0%"], "price": 9.0, "currency": "INR", "move": -11.0},
                  {"kind": "mover", "symbol": "C.NS", "name": "C", "tags": ["-8.5%"], "price": 9.0, "currency": "INR", "move": -8.5}]
        text = digest_feeds.render_feed(sorted(movers, key=lambda i: (i["move"] < 0)), [None] * 3, TS, "Movers", ["#Movers"])[0][0]
        self.assertIn("RISING", text)
        self.assertIn("FALLING", text)
        self.assertIn("#Surge", text)
        self.assertIn("#Crash", text)
        self.assertIn("#Falling", text)


class CollectTests(unittest.TestCase):
    def getter(self, calls):
        def get(url, headers=None, retries=0, timeout=0):
            calls.append(url)
            if "corporateActions" in url:
                return json.dumps(CorporateActionTests.ROWS).encode()
            if "price-band" in url:
                side = "upper" if "upper" in url else "lower"
                row = {"symbol": "UP" if side == "upper" else "DN", "series": "EQ", "ltp": "120" if side == "upper" else "95", "change": "20" if side == "upper" else "-5",
                       "priceBand": "20" if side == "upper" else "5", "turnovercsv": 3e7}
                return json.dumps({"AllSec": {"data": [row]}}).encode()
            if "reportASM" in url:
                return json.dumps(SurveillanceTests.ASM).encode()
            if "reportGSM" in url:
                return json.dumps(SurveillanceTests.GSM).encode()
            if "secban" in url:
                return b"Securities in Ban For Trade Date 23-NOV-2026:\n1,ZEEL\n"
            raise AssertionError(url)
        return get

    def test_every_source_is_read_and_slow_ones_are_not_read_again_within_the_hour(self):
        calls, nse = [], {}
        records, memory = actions_run.collect(NOW, TS, nse, [item("Demerger", "x")], {}, {}, True, [], {}, {}, getter=self.getter(calls))
        kinds = {r["type"] for r in records}
        self.assertTrue({"demerger", "bonus", "upper_circuit", "lower_circuit"} <= kinds)
        self.assertEqual(len(calls), 6)
        self.assertEqual(memory["ban_state"], ["ZEEL"])
        later = NOW + timedelta(minutes=10)
        calls.clear()
        actions_run.collect(later, int(later.timestamp()), nse, [], {}, {}, True, [], {}, memory, getter=self.getter(calls))
        self.assertEqual(sorted(u.split("?")[1] for u in calls), ["index=lower", "index=upper"], "only the price bands are read every run")

    def test_circuits_are_not_read_when_the_market_is_closed_and_a_failing_source_changes_nothing(self):
        calls, nse = [], {}
        actions_run.collect(NOW, TS, nse, [], {}, {}, False, [], {}, {}, getter=self.getter(calls))
        self.assertFalse(any("price-band" in u for u in calls))

        def failing(url, **kw):
            raise actions_run.sessions.FetchError("HTTP Error 403")
        records, memory = actions_run.collect(NOW, TS, {}, [item("Bonus", "1:1")], {}, {}, True, [], {}, {"ban_state": ["X"]}, getter=failing)
        self.assertEqual([r["type"] for r in records], ["bonus"], "announcements still come from what was already read")
        self.assertEqual(memory["ban_state"], ["X"], "a failed read keeps the last state")

    def test_the_status_lists_every_source(self):
        nse = {}
        actions_run.collect(NOW, TS, nse, [], {}, {}, True, [], {}, {}, getter=self.getter([]))
        status = actions_run.source_status(nse)
        self.assertEqual(len(status), 6)
        self.assertTrue(all(s["ok"] for s in status))


if __name__ == "__main__":
    unittest.main()

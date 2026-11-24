import unittest
from datetime import datetime, timedelta, timezone

from engine import feeds

IST = timezone(timedelta(hours=5, minutes=30))
TABLE = feeds.settings()


def at(day, hour, minute):
    """An IST time on a weekday (2026-11-23 is a Monday)."""
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


class SlotTests(unittest.TestCase):
    def test_a_two_and_a_half_hour_feed_has_slots_from_the_start_of_its_window(self):
        spec = TABLE["commodities"]                              # 09:00, every 150 minutes
        self.assertEqual(feeds.slot_of(spec, at(23, 9, 5)), "2026-11-23#0")
        self.assertEqual(feeds.slot_of(spec, at(23, 11, 41)), "2026-11-23#1")
        self.assertEqual(feeds.slot_of(spec, at(23, 14, 11)), "2026-11-23#2")

    def test_outside_the_window_or_on_a_non_trading_day_there_is_no_slot(self):
        self.assertIsNone(feeds.slot_of(TABLE["movers"], at(23, 9, 0)))           # before 09:15
        self.assertIsNone(feeds.slot_of(TABLE["movers"], at(23, 16, 0)))          # after 15:30
        self.assertIsNone(feeds.slot_of(TABLE["movers"], at(22, 10, 0)))          # a Sunday

    def test_a_daily_feed_has_one_slot_and_a_missed_one_is_not_replayed_late(self):
        spec = TABLE["ipo_upcoming"]                             # 09:00, grace 180 minutes
        self.assertEqual(feeds.slot_of(spec, at(23, 9, 7)), "2026-11-23#0")
        self.assertEqual(feeds.slot_of(spec, at(23, 11, 50)), "2026-11-23#0")
        self.assertIsNone(feeds.slot_of(spec, at(23, 12, 5)), "past the grace")

    def test_the_weekly_summary_runs_on_sunday_only(self):
        self.assertEqual(feeds.slot_of(TABLE["weekly"], at(22, 18, 10)), "2026-11-22#0")
        self.assertIsNone(feeds.slot_of(TABLE["weekly"], at(23, 18, 10)))

    def test_a_slot_that_starts_after_the_window_end_is_not_a_slot(self):
        spec = TABLE["indexes"]                                  # 09:15 to 15:30, hourly: the last slot starts 15:15
        self.assertEqual(feeds.slot_of(spec, at(23, 15, 20)), "2026-11-23#6")
        self.assertIsNone(feeds.slot_of(spec, at(23, 16, 20)))


class DueTests(unittest.TestCase):
    def test_a_feed_is_due_once_per_slot(self):
        now = at(23, 10, 20)
        sent = {}
        first = feeds.due(sent, now, TABLE)
        self.assertIn("readings", first)
        feeds.mark_sent(sent, "readings", first["readings"])
        self.assertNotIn("readings", feeds.due(sent, now + timedelta(minutes=3), TABLE))
        self.assertIn("readings", feeds.due(sent, now + timedelta(minutes=16), TABLE), "the next 15-minute slot")

    def test_the_cadences_are_the_ones_asked_for(self):
        self.assertEqual([TABLE[k]["every"] for k in ("indexes", "commodities", "sectors", "movers", "readings")], [60, 150, 90, 30, 15])

    def test_config_can_change_a_cadence_and_bad_values_are_ignored(self):
        table = feeds.settings({"feeds": {"movers": {"every": 20}, "indexes": {"every": 0}, "nonsense": {"every": 5}, "sectors": {"enabled": False}}})
        self.assertEqual(table["movers"]["every"], 20)
        self.assertEqual(table["indexes"]["every"], 60)
        self.assertNotIn("sectors", table)
        self.assertNotIn("nonsense", table)


class QueueTests(unittest.TestCase):
    def test_items_go_to_their_feed_and_urgent_or_brief_items_go_at_once(self):
        items = [{"kind": "signal"}, {"kind": "mover"}, {"kind": "ipo"}, {"kind": "deal"}, {"kind": "brief"}, {"kind": "entry", "urgent": True}, {"kind": "news"}]
        now_items, held = feeds.split(items)
        self.assertEqual([i["kind"] for i in now_items], ["brief", "entry"])
        self.assertEqual([f for f, _ in held], ["readings", "movers", "ipo_breakout", "deals", "news"])

    def test_old_items_are_dropped_not_sent_late_and_other_feeds_are_kept(self):
        queue = feeds.enqueue([], [("movers", {"n": 1})], 1000)
        queue = feeds.enqueue(queue, [("movers", {"n": 2}), ("deals", {"n": 3})], 1000 + 4 * 3600)
        taken, rest = feeds.take(queue, "movers", 1000 + 4 * 3600, TABLE)          # movers expire after 3 hours
        self.assertEqual([i["n"] for i in taken], [2])
        self.assertEqual([q["item"]["n"] for q in rest], [3])

    def test_the_queue_is_bounded(self):
        queue = feeds.enqueue([], [("movers", {"n": i}) for i in range(feeds.QUEUE_LIMIT + 50)], 1)
        self.assertEqual(len(queue), feeds.QUEUE_LIMIT)
        self.assertEqual(queue[-1]["item"]["n"], feeds.QUEUE_LIMIT + 49)


if __name__ == "__main__":
    unittest.main()

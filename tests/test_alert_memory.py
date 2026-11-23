import json
import tempfile
import unittest
from pathlib import Path

from engine import alert_memory as am


class RestoreTests(unittest.TestCase):
    def memory(self, saved_at, **state):
        return {"v": 1, "saved_at": saved_at, "state": state}

    def test_newer_memory_puts_back_what_a_failed_publish_lost(self):
        published = {"seen_alerts": ["old"], "memory_at": "2026-11-23T04:00:00", "delivery": {"x": 1}}
        merged, used = am.restore(published, self.memory("2026-11-23T04:10:00", seen_alerts=["old", "new"], mover_seen={"A": 1}))
        self.assertTrue(used)
        self.assertEqual(merged["seen_alerts"], ["old", "new"])
        self.assertEqual(merged["mover_seen"], {"A": 1})
        self.assertEqual(merged["delivery"], {"x": 1}, "only the sent-alert keys come from the memory")

    def test_an_older_memory_never_overrides_a_newer_published_state(self):
        published = {"seen_alerts": ["new"], "memory_at": "2026-11-23T04:10:00"}
        merged, used = am.restore(published, self.memory("2026-11-23T04:00:00", seen_alerts=["old"]))
        self.assertFalse(used)
        self.assertEqual(merged["seen_alerts"], ["new"])

    def test_no_memory_or_a_first_run_uses_the_published_state(self):
        self.assertEqual(am.restore({"seen_alerts": ["a"]}, None), ({"seen_alerts": ["a"]}, False))
        merged, used = am.restore({}, self.memory("2026-11-23T04:00:00", seen_alerts=["a"]))
        self.assertTrue(used)
        self.assertEqual(merged["seen_alerts"], ["a"])


class FileTests(unittest.TestCase):
    def test_write_then_read_round_trips_and_stamps_the_state(self):
        root = Path(tempfile.mkdtemp())
        state = {"seen_alerts": ["a"], "briefs_sent": {"open": "2026-11-23"}, "delivery": {"big": 1}}
        am.write(root, state, "2026-11-23T04:10:00+00:00")
        data = am.read(root)
        self.assertEqual(data["state"], {"seen_alerts": ["a"], "briefs_sent": {"open": "2026-11-23"}})
        self.assertEqual(state["memory_at"], data["saved_at"])

    def test_a_missing_or_damaged_file_is_ignored(self):
        root = Path(tempfile.mkdtemp())
        self.assertIsNone(am.read(root))
        (root / "alerts").mkdir()
        (root / am.FILE).write_text("{not json", encoding="utf-8")
        self.assertIsNone(am.read(root))
        (root / am.FILE).write_text(json.dumps({"v": 2, "saved_at": "t", "state": {}}), encoding="utf-8")
        self.assertIsNone(am.read(root))


if __name__ == "__main__":
    unittest.main()

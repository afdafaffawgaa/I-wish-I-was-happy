import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from collector import hour_from_time, matches_target, normalize_popular_times


class ParsingTests(unittest.TestCase):
    def test_hour(self):
        self.assertEqual(hour_from_time("12 AM"), 0)
        self.assertEqual(hour_from_time("12 PM"), 12)
        self.assertEqual(hour_from_time("9 PM"), 21)
        self.assertEqual(hour_from_time("7:00 AM"), 7)
        self.assertIsNone(hour_from_time("wrong"))

    def test_target_brand(self):
        self.assertTrue(matches_target("LARRY FiT 下館店", "茨城県筑西市乙863-2"))
        self.assertTrue(matches_target("ラリーフィット 下館店", "筑西市乙863-2"))
        self.assertFalse(matches_target("LifeFit 下館店", "筑西市直井961-4"))
        self.assertFalse(matches_target("LARRY FiT 古河", "古河市諸川"))

    def test_weekly_live_and_missing(self):
        now = datetime(2026, 10, 27, 16, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
        payload = {"graph_results": {"tuesday": [
            {"time": "12 AM", "busyness_score": 0},
            {"time": "4 PM", "busyness_score": 46, "live_busyness_score": 31, "current": True},
            {"time": "5 PM", "busyness_score": 69},
        ]}}
        days, live = normalize_popular_times(payload, now)
        self.assertEqual(days["tuesday"][0], 0)
        self.assertEqual(days["tuesday"][16], 46)
        self.assertEqual(days["tuesday"][17], 69)
        self.assertIsNone(days["tuesday"][18])
        self.assertEqual(live["score"], 31)
        self.assertEqual(len(days["monday"]), 24)


if __name__ == "__main__":
    unittest.main()

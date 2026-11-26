import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.publish_simulation_dashboard import build_batch, metric_stats, update_feed


class SimulationDashboardPublishTests(unittest.TestCase):
    def build_timed_batch(self, started_at):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "draws.json"
            archive.write_text('{"draws": []}', encoding="utf-8")
            with patch("scripts.publish_simulation_dashboard.utc_now", return_value="2026-11-26T12:02:30+00:00"):
                return build_batch(
                    {"simulationCount": 100, "simulationSummaries": []},
                    status="success", run_id="123", run_attempt="1", run_number="1",
                    run_url="https://github.com/example/repo/actions/runs/123",
                    started_at=started_at, archive_path=archive,
                )

    def test_batch_duration_uses_recorded_start_in_utc(self):
        batch = self.build_timed_batch("2026-11-26T18:00:00+08:00")
        self.assertEqual(batch["startedAt"], "2026-11-26T10:00:00+00:00")
        self.assertEqual(batch["durationSeconds"], 7350)

    def test_missing_invalid_or_future_start_is_unknown_not_zero(self):
        for started_at in (None, "", "not-a-date", "2026-11-27T10:00:00Z"):
            with self.subTest(started_at=started_at):
                batch = self.build_timed_batch(started_at)
                self.assertIsNone(batch["startedAt"])
                self.assertIsNone(batch["durationSeconds"])

    def test_metric_stats_aggregates_seed_runs(self):
        rows = [
            {"joy": {"averageBestTotalHits": 1.0, "averageBestFrontHits": 0.7, "averageBestBackHits": 0.3}},
            {"joy": {"averageBestTotalHits": 1.2, "averageBestFrontHits": 0.8, "averageBestBackHits": 0.4}},
        ]
        stats = metric_stats(rows, "joy")
        self.assertEqual(stats["averageBestTotalHits"]["mean"], 1.1)
        self.assertEqual(stats["averageBestTotalHits"]["min"], 1.0)
        self.assertEqual(stats["averageBestTotalHits"]["max"], 1.2)
        self.assertEqual(stats["averageBestTotalHits"]["stdev"], 0.1)

    def test_feed_keeps_newest_30_and_deduplicates_batch(self):
        old = {"batches": [{"batchId": f"old-{i}"} for i in range(30)]}
        batch = {"batchId": "new-1", "status": "completed"}
        updated = update_feed(old, batch)
        self.assertEqual(len(updated["batches"]), 30)
        self.assertEqual(updated["batches"][0]["batchId"], "new-1")
        again = update_feed(updated, batch)
        self.assertEqual(len(again["batches"]), 30)
        self.assertEqual(sum(row["batchId"] == "new-1" for row in again["batches"]), 1)

    def test_schedule_is_explicit_and_active(self):
        updated = update_feed(None, {"batchId": "new-2"})
        self.assertTrue(updated["schedule"]["enabled"])
        self.assertEqual(updated["schedule"]["simulationsPerBatch"], 100)
        self.assertEqual(updated["schedule"]["localTime"], "18:00")
        self.assertEqual(updated["schedule"]["timeZone"], "Asia/Shanghai")


if __name__ == "__main__":
    unittest.main()

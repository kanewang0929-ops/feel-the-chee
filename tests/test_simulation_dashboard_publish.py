import unittest

from scripts.publish_simulation_dashboard import metric_stats, update_feed


class SimulationDashboardPublishTests(unittest.TestCase):
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

import copy
import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import closed_loop_research as research
from scripts import joy_kane_duel as duel


def archive():
    return [{"issue": str(i+1), "date": str(datetime.date(2020,1,1)+datetime.timedelta(days=i)),
             "front": [1,2,3,4,5], "back": [1,2]} for i in range(500)]


def batch(seed="batch-1"):
    return {"batchSeed": seed, "simulationCount": 100, "allFirstPredictionsDistinct": True,
            "guardrails": {"livePredictionLockReadOrWrite": False, "dailyOptimizerRan": False,
                           "allPredictionResultAuditRowsValidated": True},
            "simulationSummaries": [{"seed": i, "drawsEvaluated": 300,
              "joy": {"averageBestTotalHits": 1.0}, "kane": {"averageBestTotalHits": 1.1}}
              for i in range(100)]}


class ResearchTests(unittest.TestCase):
    def test_batch_rejects_incomplete_or_live_mutating_runs(self):
        for change in ("count", "lock", "duplicate"):
            b = batch()
            if change == "count":
                b["simulationCount"] = 99
            elif change == "lock":
                b["guardrails"]["livePredictionLockReadOrWrite"] = True
            else:
                b["simulationSummaries"][1]["seed"] = 0
            with self.assertRaises(ValueError):
                research.validate_batch(b, archive())

    def test_registry_persistence_and_no_production_mutation(self):
        draws = archive()
        live = {"agents": {agent: duel.default_state(agent) for agent in research.AGENTS}}
        saved = copy.deepcopy(live)
        def fake_replay(agent, draws, config, seed, start, score_start):
            return 1.1 if config["name"] == "fast_adaptation" else 1.0, duel.default_state(agent)
        with tempfile.TemporaryDirectory() as directory, patch.object(research, "replay", side_effect=fake_replay):
            output = Path(directory)
            first = research.build_registry(draws, batch(), live, {}, "commit", "engine", output)
            self.assertEqual(len(first["experiments"]), 2)
            self.assertEqual(first["experiments"][0]["decision"], "not_improved")
            for record in first["experiments"]:
                self.assertFalse(record["promotionEligible"])
                self.assertEqual(research.digest(research.load_json(output / record["package"])), record["id"])
            duplicate = research.build_registry(draws, batch(), live, copy.deepcopy(first), "commit", "engine", output)
            self.assertEqual(first, duplicate)
            second = research.build_registry(draws, batch("batch-2"), live, copy.deepcopy(first), "commit", "engine", output)
            self.assertEqual(len(second["experiments"]), 4)
            self.assertNotEqual(second["experiments"][0]["configuration"], second["experiments"][2]["configuration"])
            self.assertFalse(second["promotionEnabled"])
            self.assertEqual(live, saved)
            self.assertEqual(len(list((output / "production-snapshots").glob("*.json"))), 2)

    def test_actual_engine_replay_is_deterministic(self):
        draws = archive()[:203]
        config = research.evaluation.CANDIDATES[0]
        for agent in research.AGENTS:
            first = research.replay(agent, draws, config, 1234, 200, 201)
            second = research.replay(agent, draws, config, 1234, 200, 201)
            self.assertEqual(first, second)
            self.assertEqual(first[1]["observations"], 3)
            self.assertGreaterEqual(first[0], 0)
            self.assertLessEqual(first[0], 7)


if __name__ == "__main__":
    unittest.main()

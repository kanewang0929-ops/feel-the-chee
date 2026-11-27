"""Evaluation is read-only, segregates model generations, and uses exact fair-draw references."""
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import evaluate_live_predictions as evaluation
from scripts import joy_kane_live as live, quantum_models as models, quantum_protocol as protocol
from test_quantum_live import historical_rows, legacy_lock, model_package, test_clock, write_json


class LiveEvaluationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        self.rows = historical_rows()
        self.archive = self.data / "draws.json"
        self.lock = self.data / live.LOCK_NAME
        self.ledger = self.data / live.LEDGER_NAME
        self.package = self.data / "package.json"
        write_json(self.archive, {"draws": self.rows})
        engine = patch.object(protocol, "engine_digest", return_value="a" * 64)
        engine.start()
        self.addCleanup(engine.stop)

    def refresh(self, ready=True):
        if ready:
            write_json(self.package, model_package(self.rows))
        return live.run_live(self.data, self.package if ready else None, now=test_clock(self.rows))

    def settle(self):
        locked = json.loads(self.lock.read_text())
        selected = locked["agents"]["joy"]["prediction"]["results"][0]
        self.rows.append({"issue": locked["issue"], "date": locked["date"], **protocol.validate_ticket(selected)})
        write_json(self.archive, {"draws": self.rows})
        self.refresh()
        return locked

    def report(self):
        before = {p.name: p.read_bytes() for p in self.data.iterdir()}
        with patch.object(models, "train_on_draw", side_effect=AssertionError("Must not train")), \
                patch.object(models, "make_prediction", side_effect=AssertionError("Must not predict")):
            result = evaluation.build_report(self.data)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.data.iterdir()})
        return result

    def test_exact_null_distribution(self):
        pmf = evaluation.null_distribution(1)
        self.assertAlmostEqual(float(pmf.sum()), 1.0)
        self.assertAlmostEqual(sum(i * p for i, p in enumerate(pmf)), evaluation.EXPECTED)
        self.assertAlmostEqual(pmf[7], 1 / (math.comb(35, 5) * math.comb(12, 2)))
        self.assertAlmostEqual(evaluation.chance_reference(1, 7)["oneSidedTailAtLeastObserved"], pmf[7])
        self.assertAlmostEqual(evaluation.null_distribution(2)[14], pmf[7] ** 2)
        self.assertIsNone(evaluation.chance_reference(0, 0))

    def test_pending_legacy_is_not_a_quantum_result(self):
        write_json(self.lock, legacy_lock(self.rows))
        self.refresh()
        report = self.report()
        current = next(c for c in report["cohorts"] if c["isCurrent"])
        self.assertEqual(report["scoredDrawCount"], 0)
        self.assertNotEqual(report["pending"]["cohortId"], current["id"])
        self.assertIsNone(current["agents"]["joy"]["meanTotalHits"])
        self.assertIsNone(current["agents"]["joy"]["chanceReference"])

    def test_legacy_and_quantum_results_are_separate_and_likelihood_uses_sealed_vectors(self):
        write_json(self.lock, legacy_lock(self.rows))
        self.refresh()
        self.settle()
        locked_quantum = self.settle()
        report = self.report()
        self.assertEqual(report["scoredDrawCount"], 2)
        current = next(c for c in report["cohorts"] if c["isCurrent"])
        legacy = next(c for c in report["cohorts"] if not c["isCurrent"])
        self.assertEqual(current["drawCount"], 1)
        self.assertEqual(legacy["drawCount"], 1)
        self.assertEqual(current["agents"]["joy"]["meanTotalHits"], 7)
        self.assertEqual(legacy["agents"]["joy"]["nllDrawCount"], 0)
        self.assertIsNone(legacy["agents"]["joy"]["meanNegativeLogLikelihood"])
        row = current["rows"][0]
        probabilities = locked_quantum["agents"]["joy"]["probabilities"]
        expected = -sum(models.ticket_log_probability(probabilities[a], row["actual"][a]) for a in ("front", "back"))
        self.assertAlmostEqual(row["agents"]["joy"]["negativeLogLikelihood"], expected)
        self.assertIsNone(current["agents"]["joy"]["rolling"]["10"])
        self.assertIsNone(current["agents"]["joy"]["lastParameterShiftRmsRadians"])
        self.settle()
        current = next(c for c in self.report()["cohorts"] if c["isCurrent"])
        self.assertEqual(current["agents"]["joy"]["parameterComparisons"], 1)
        self.assertIsNotNone(current["agents"]["joy"]["lastParameterShiftRmsRadians"])

    def test_missing_prediction_does_not_count_as_scored(self):
        self.refresh(ready=False)
        report = self.report()
        self.assertEqual(report["scoredDrawCount"], 0)
        self.assertEqual(report["missingDrawCount"], 1)
        self.assertIsNone(report["pending"])

    def test_inconsistent_publication_or_ledger_fails_closed(self):
        self.refresh()
        dashboard_path = self.data / "joy-kane-dashboard.json"
        original = dashboard_path.read_bytes()
        data = json.loads(original)
        data["summary"]["drawsEvaluated"] = 100
        write_json(dashboard_path, data)
        self.assertEqual(evaluation.publish(self.data)["status"], "unavailable")
        dashboard_path.write_bytes(original)
        self.assertEqual(evaluation.publish(self.data)["status"], "available")
        self.ledger.write_bytes(self.ledger.read_bytes()[:-1])
        self.assertEqual(evaluation.publish(self.data)["status"], "unavailable")

    def test_full_windows_only_and_null_reference(self):
        values = [{"agents": {name: {"frontHits": 1, "backHits": 0, "totalHits": 1,
                 "negativeLogLikelihood": None, "parameterShiftRmsRadians": None}
                   for name in protocol.AGENTS}} for _ in range(30)]
        stats = evaluation.agent_metrics(values, "joy")
        self.assertEqual(stats["rolling"]["10"], {"drawCount": 10, "meanTotalHits": 1.0})
        self.assertEqual(stats["rolling"]["30"], {"drawCount": 30, "meanTotalHits": 1.0})
        self.assertIsNone(stats["rolling"]["100"])
        self.assertAlmostEqual(stats["deltaVsRandom"], 1 - evaluation.EXPECTED)


if __name__ == "__main__":
    unittest.main()

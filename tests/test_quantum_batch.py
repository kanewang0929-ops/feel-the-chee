import contextlib
import copy
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import quantum_models as quantum
from scripts import quantum_protocol as protocol
from scripts import run_simulation_batch as batch


def synthetic_draws(count=203):
    start = date(2020, 1, 1)
    return [{
        "issue": f"20{index + 1:03d}",
        "date": (start + timedelta(days=index)).isoformat(),
        "front": sorted(((index * 3 + offset * 7) % 35) + 1 for offset in range(5)),
        "back": sorted(((index * 5 + offset * 3) % 12) + 1 for offset in range(2)),
    } for index in range(count)]


def write_archive(path, rows):
    path.write_text(json.dumps({"draws": rows}), encoding="utf-8")


def fake_completed_cycle(draws, *, cycle, batch_seed, run_data, prefix_hashes=None):
    """Structural batch tests only: real mathematical replay is tested below."""
    run_data.mkdir(parents=True, exist_ok=True)
    seed = batch.seed_for(batch_seed, cycle)
    states = {name: quantum.initial_state(name, seed) for name in quantum.MODEL_FAMILIES}
    for state in states.values():
        state["observations"] = len(draws)
        state["randomness"]["trainingCounter"] = len(draws)
    for filename in ("joy-kane-predictions.jsonl", "joy-kane-results.jsonl", "joy-kane-audit.json",
                     "joy-kane-dashboard.json", "joy-kane-model-state.json"):
        (run_data / filename).write_text("{}\n", encoding="utf-8")
    return {
        "simulationId": cycle,
        "seed": seed,
        "drawsEvaluated": len(draws) - batch.WARMUP_DRAWS,
        "trainedDrawCount": len(draws),
        "firstPredictionFingerprint": f"structural-test-cycle-{cycle}",
        "finalModelHashes": {name: protocol.digest(state) for name, state in states.items()},
        "joy": {"averageBestTotalHits": 1.0},
        "kane": {"averageBestTotalHits": 1.0},
    }, states


class ChronologicalQuantumReplayTests(unittest.TestCase):
    def test_two_real_cycles_seal_before_learning_and_do_not_see_target_or_future_results(self):
        draws = synthetic_draws()
        changed = copy.deepcopy(draws)
        # The first 200 warm-up rows and target metadata are identical. Change
        # only the first scored outcome and subsequent outcomes.
        for index in range(batch.WARMUP_DRAWS, len(changed)):
            changed[index]["front"] = [1, 2, 3, 4, 5]
            changed[index]["back"] = [1, 2]
        original_trainer = quantum.train_on_draw
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_path = root / "first"
            observed_seals = []

            def require_seal_before_learning(state, actual, probabilities=None):
                index = state["observations"]
                if index >= batch.WARMUP_DRAWS:
                    locked = batch.read_jsonl(first_path / "joy-kane-predictions.jsonl")
                    scored = batch.read_jsonl(first_path / "joy-kane-results.jsonl")
                    self.assertEqual(len(locked), index - batch.WARMUP_DRAWS + 1)
                    self.assertEqual(len(scored), index - batch.WARMUP_DRAWS)
                    self.assertEqual(locked[-1]["issue"], draws[index]["issue"])
                    self.assertEqual(locked[-1]["agents"][state["name"]]["modelStateHash"], protocol.digest(state))
                    observed_seals.append((state["name"], index))
                return original_trainer(state, actual, probabilities)

            with patch.object(quantum, "train_on_draw", side_effect=require_seal_before_learning):
                first_summary, first_states = batch.replay_cycle(
                    draws, cycle=1, batch_seed="causality", run_data=first_path)
            second_summary, second_states = batch.replay_cycle(
                changed, cycle=1, batch_seed="causality", run_data=root / "changed")

            self.assertEqual(len(observed_seals), 2 * (len(draws) - batch.WARMUP_DRAWS))
            first_predictions = batch.read_jsonl(first_path / "joy-kane-predictions.jsonl")
            changed_predictions = batch.read_jsonl(root / "changed" / "joy-kane-predictions.jsonl")
            first_results = batch.read_jsonl(first_path / "joy-kane-results.jsonl")
            self.assertEqual(first_predictions[0]["agents"], changed_predictions[0]["agents"])
            self.assertEqual(first_predictions[0]["predictionId"], changed_predictions[0]["predictionId"])
            self.assertEqual(first_summary["firstPredictionFingerprint"], second_summary["firstPredictionFingerprint"])
            self.assertNotEqual(first_results[0]["actual"], batch.read_jsonl(root / "changed" / "joy-kane-results.jsonl")[0]["actual"])
            self.assertEqual(first_summary["drawsEvaluated"], 3)
            self.assertEqual(first_summary["fullReplayAuditRowsValidated"], 3)
            for name in quantum.MODEL_FAMILIES:
                self.assertEqual(first_states[name]["observations"], len(draws))
                self.assertEqual(second_states[name]["observations"], len(draws))
                self.assertNotEqual(first_states[name]["parameters"], second_states[name]["parameters"])
            for prediction, result in zip(first_predictions, first_results):
                self.assertEqual(prediction["predictionId"], result["predictionId"])
                self.assertEqual(prediction["trainingDrawCount"], 200 + first_results.index(result))
                for name in quantum.MODEL_FAMILIES:
                    sealed = prediction["agents"][name]["tickets"]
                    self.assertEqual(len(sealed), 1)
                    self.assertEqual(sealed[0]["front"], result[name]["tickets"][0]["front"])
                    self.assertEqual(sealed[0]["back"], result[name]["tickets"][0]["back"])

    def test_replaying_same_cycle_starts_fresh_and_reproduces_final_state(self):
        draws = synthetic_draws(201)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            first_summary, first_states = batch.replay_cycle(
                draws, cycle=7, batch_seed="fresh-cycle", run_data=path / "first")
            # Reusing the output directory must not load or continue its state.
            repeated_summary, repeated_states = batch.replay_cycle(
                draws, cycle=7, batch_seed="fresh-cycle", run_data=path / "first")
            self.assertEqual(first_states, repeated_states)
            self.assertEqual(first_summary, repeated_summary)
            self.assertEqual(len(batch.read_jsonl(path / "first" / "joy-kane-predictions.jsonl")), 1)
            for state in repeated_states.values():
                self.assertEqual(state["observations"], len(draws))


class QuantumBatchPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / "draws.json"
        self.output = self.root / "output"
        self.draws = synthetic_draws(201)
        write_archive(self.archive, self.draws)

    def run_quietly(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return batch.run_batch(self.archive, self.output, batch_seed="publication-test", **kwargs)

    def test_production_rejects_any_count_other_than_100(self):
        for count in (0, 1, 99, 101):
            with self.subTest(count=count), patch.object(batch, "replay_cycle") as replay:
                with self.assertRaisesRegex(ValueError, "exactly 100"):
                    self.run_quietly(count=count)
                replay.assert_not_called()

    def test_diagnostic_run_never_exports_a_production_package(self):
        self.output.mkdir()
        package = self.output / "joy-kane-batch-models.json"
        package.write_text('{"old": true}', encoding="utf-8")
        with patch.object(batch, "replay_cycle", side_effect=fake_completed_cycle):
            report = self.run_quietly(count=2, diagnostic=True)
        self.assertTrue(report["diagnosticOnly"])
        self.assertEqual(report["simulationCount"], 2)
        self.assertFalse(package.exists())
        self.assertTrue((self.output / "simulation-batch-summary.json").exists())

    def test_complete_100_cycles_export_exact_final_cycle_and_all_checkpoints(self):
        with patch.object(batch, "replay_cycle", side_effect=fake_completed_cycle) as replay:
            report = self.run_quietly(source_commit="f" * 40)
        self.assertEqual(replay.call_count, 100)
        self.assertEqual(report["simulationCount"], 100)
        self.assertEqual(report["selectedCycle"], 100)
        package = json.loads((self.output / "joy-kane-batch-models.json").read_text())
        checkpoints = json.loads((self.output / "simulation-model-checkpoints.json").read_text())["cycles"]
        self.assertEqual(len(checkpoints), 100)
        self.assertEqual([row["cycle"] for row in checkpoints], list(range(1, 101)))
        self.assertEqual(package["agents"], checkpoints[-1]["agents"])
        self.assertEqual(package["batch"]["selectionPolicy"], "fixed_final_cycle")
        self.assertEqual(package["batch"]["completedCycles"], 100)
        self.assertEqual(package["archive"], protocol.archive_metadata(self.draws))
        protocol.validate_package(package, self.draws)

    def test_mid_batch_failure_removes_old_package_and_cannot_publish_partial_models(self):
        self.output.mkdir()
        package = self.output / "joy-kane-batch-models.json"
        package.write_text('{"previousCompletedPackage": true}', encoding="utf-8")

        def fail_second_cycle(*args, **kwargs):
            if kwargs["cycle"] == 2:
                raise RuntimeError("deliberate failed second cycle")
            return fake_completed_cycle(*args, **kwargs)

        with patch.object(batch, "replay_cycle", side_effect=fail_second_cycle):
            with self.assertRaisesRegex(RuntimeError, "failed second cycle"):
                self.run_quietly()
        self.assertFalse(package.exists())
        self.assertFalse((self.output / "simulation-batch-summary.json").exists())
        self.assertFalse((self.output / "simulation-model-checkpoints.json").exists())
        self.assertEqual(json.loads((self.output / "simulation-progress.json").read_text())["completedCycles"], 1)

    def test_invalid_archive_cannot_leave_an_old_production_package_available(self):
        self.output.mkdir()
        package = self.output / "joy-kane-batch-models.json"
        package.write_text('{"previousCompletedPackage": true}', encoding="utf-8")
        self.archive.write_text('{"draws": [{"issue": "26001", "date": "2026-01-01"}]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_quietly()
        self.assertFalse(package.exists())


if __name__ == "__main__":
    unittest.main()

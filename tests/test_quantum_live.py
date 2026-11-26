"""Verify live publication gates with isolated data and immutable ledger records."""
import copy
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import joy_kane_live as live
from scripts import quantum_models as models
from scripts import quantum_protocol as protocol


def historical_rows(count=201):
    start = date(2025, 1, 1)
    return [{"issue": f"25{index + 1:03d}", "date": (start + timedelta(days=index)).isoformat(),
             "front": sorted((index * 3 + offset * 7) % 35 + 1 for offset in range(5)),
             "back": sorted((index * 5 + offset * 3) % 12 + 1 for offset in range(2))}
            for index in range(count)]


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_clock(rows):
    return datetime.fromisoformat(rows[-1]["date"] + "T12:00:00+00:00")


def model_package(rows):
    # These are protocol fixtures, not reports of performed model training.
    agents = {name: models.initial_state(name, 123) for name in protocol.AGENTS}
    for state in agents.values():
        state["observations"] = len(rows)
        state["randomness"]["trainingCounter"] = len(rows)
    return {"schemaVersion": 2, "modelVersion": protocol.MODEL_VERSION,
            "engineVersion": protocol.ENGINE_VERSION, "engineDigest": protocol.engine_digest(),
            "batch": {"id": "fixture-batch", "seed": "fixture-seed", "status": "complete",
                      "cycleCount": 100, "completedCycles": 100, "selectedCycle": 100,
                      "selectionPolicy": "fixed_final_cycle"},
            "archive": protocol.archive_metadata(rows), "warmupDraws": 200, "agents": agents,
            "generatedAt": test_clock(rows).isoformat(), "sourceCommit": "fixture-source-commit"}


def legacy_lock(rows):
    issue, day = protocol.next_target(rows[-1])
    agents = {}
    for name in protocol.AGENTS:
        version = f"{name}-adaptive-hit-model-v1"
        agents[name] = {"modelVersion": version, "weights": {"front": {"frequency": 1.0}},
                        "prediction": {"modelVersion": version, "targetIssue": issue, "targetDate": day,
                                       "results": [{"rank": 1, "label": f"{name.title()} Main",
                                                    "front": ["01", "02", "03", "04", "05"], "back": ["01", "02"]}]}}
    return {"eventType": "prediction_locked", "predictionId": "original-legacy-forecast",
            "issue": issue, "date": day, "trainingDrawCount": len(rows),
            "trainingThroughIssue": rows[-1]["issue"], "trainingThroughDate": rows[-1]["date"],
            "historyDigest": protocol.digest(rows), "predictionLockedAt": test_clock(rows).isoformat(),
            "agents": agents, "futureLeakage": False}


class QuantumLiveTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.data = Path(self.folder.name)
        self.rows = historical_rows()
        self.archive = self.data / "draws.json"
        self.package = self.data / "package.json"
        self.lock = self.data / live.LOCK_NAME
        self.ledger = self.data / live.LEDGER_NAME
        write_json(self.archive, {"draws": self.rows})
        self.engine = patch.object(protocol, "engine_digest", return_value="a" * 64)
        self.engine.start()
        self.addCleanup(self.engine.stop)
        self.no_training = patch.object(models, "train_on_draw", side_effect=AssertionError("Live workflow must never train."))
        self.no_training.start()
        self.addCleanup(self.no_training.stop)

    def run_live(self, package=True):
        return live.run_live(self.data, self.package if package else None, now=test_clock(self.rows))

    def events(self):
        return [json.loads(line) for line in self.ledger.read_text(encoding="utf-8").splitlines()]

    def append_locked_result(self):
        lock = read_json(self.lock)
        ticket = lock["agents"]["joy"]["prediction"]["results"][0]
        self.rows.append({"issue": lock["issue"], "date": lock["date"], **protocol.validate_ticket(ticket)})
        write_json(self.archive, {"draws": self.rows})
        return lock

    def test_bootstrap_preserves_legacy_lock_and_waits_for_its_result(self):
        write_json(self.lock, legacy_lock(self.rows))
        original = self.lock.read_bytes()
        write_json(self.package, model_package(self.rows))
        with patch.object(models, "make_prediction", side_effect=AssertionError("Pending tickets must not be rerolled.")):
            dashboard = self.run_live()
            first_ledger = self.ledger.read_bytes()
            repeated = self.run_live()
        self.assertEqual(self.lock.read_bytes(), original)
        self.assertEqual(self.ledger.read_bytes(), first_ledger)
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(dashboard["predictionGate"]["status"], "awaiting_result")
        self.assertEqual(repeated["nextForecast"], dashboard["nextForecast"])
        self.assertEqual(dashboard["modelVersion"], "legacy-locked-prediction")
        self.assertEqual(dashboard["nextForecast"]["joy"]["modelVersion"], "joy-adaptive-hit-model-v1")
        self.assertEqual(dashboard["trainedBatch"]["status"], "ready")
        self.assertEqual(dashboard["summary"]["drawsEvaluated"], 0)

    def test_score_is_appended_before_next_prediction_and_retries_are_idempotent(self):
        write_json(self.lock, legacy_lock(self.rows))
        self.run_live(package=False)
        original_prefix = self.ledger.read_bytes()
        previous = self.append_locked_result()
        write_json(self.package, model_package(self.rows))
        dashboard = self.run_live()
        events = self.events()
        self.assertEqual([event["eventType"] for event in events], ["prediction_locked", "result_scored", "prediction_locked"])
        self.assertTrue(self.ledger.read_bytes().startswith(original_prefix))
        self.assertEqual(events[1]["predictionId"], previous["predictionId"])
        self.assertEqual(events[1]["predictionLockedAt"], previous["predictionLockedAt"])
        self.assertEqual(events[1]["joy"]["bestTotalHits"], 7)
        self.assertEqual(dashboard["summary"]["scope"], "live_predictions_only")
        self.assertEqual(dashboard["summary"]["drawsEvaluated"], 1)
        self.assertEqual(dashboard["predictionGate"]["status"], "prediction_locked")
        self.assertEqual(dashboard["modelVersion"], protocol.MODEL_VERSION)
        sealed_bytes, ledger_bytes = self.lock.read_bytes(), self.ledger.read_bytes()
        with patch.object(models, "make_prediction", side_effect=AssertionError("No reroll on retry.")):
            self.run_live()
        self.assertEqual(self.lock.read_bytes(), sealed_bytes)
        self.assertEqual(self.ledger.read_bytes(), ledger_bytes)

    def test_missing_or_stale_batch_scores_previous_ticket_but_blocks_new_forecast(self):
        write_json(self.lock, legacy_lock(self.rows))
        write_json(self.package, model_package(self.rows))
        self.run_live()
        self.append_locked_result()
        with patch.object(models, "make_prediction", side_effect=AssertionError("Stale packages must not predict.")):
            stale = self.run_live()
            missing = self.run_live(package=False)
        self.assertEqual(stale["predictionGate"]["status"], "awaiting_batch")
        self.assertEqual(stale["trainedBatch"]["status"], "stale")
        self.assertEqual(missing["trainedBatch"]["status"], "missing")
        self.assertEqual(stale["nextForecast"]["joy"]["results"], [])
        self.assertIsNone(stale["livePredictionLock"])
        self.assertEqual([event["eventType"] for event in self.events()], ["prediction_locked", "result_scored"])

    def test_invalid_packages_fail_closed(self):
        changes = [lambda p: p["batch"].update(completedCycles=99),
                   lambda p: p["batch"].update(selectedCycle=1),
                   lambda p: p.update(engineDigest="b" * 64),
                   lambda p: p["agents"]["joy"].update(name="kane"),
                   lambda p: p["agents"]["joy"].update(observations=0)]
        with patch.object(models, "make_prediction", side_effect=AssertionError("Invalid packages must not predict.")):
            for change in changes:
                package = model_package(self.rows)
                change(package)
                write_json(self.package, package)
                dashboard = self.run_live()
                self.assertEqual(dashboard["predictionGate"]["status"], "awaiting_batch")
                self.assertEqual(dashboard["nextForecast"]["kane"]["results"], [])
        self.assertFalse(self.lock.exists())
        self.assertEqual([event["eventType"] for event in self.events()], ["no_prior_prediction"])

    def test_draws_without_prior_forecasts_are_never_backfilled_as_live_predictions(self):
        self.run_live(package=False)
        issue, day = protocol.next_target(self.rows[-1])
        self.rows.append({"issue": issue, "date": day, "front": [1, 2, 3, 4, 5], "back": [1, 2]})
        write_json(self.archive, {"draws": self.rows})
        write_json(self.package, model_package(self.rows))
        dashboard = self.run_live()
        self.assertEqual([event["eventType"] for event in self.events()], ["no_prior_prediction", "no_prior_prediction", "prediction_locked"])
        self.assertEqual(dashboard["summary"]["drawsEvaluated"], 0)
        self.assertEqual(dashboard["summary"]["missingPredictions"], 2)
        self.assertNotEqual(dashboard["nextForecast"]["targetIssue"], issue)
        self.assertEqual(read_json(self.data / "joy-kane-audit.json")["rows"], [])

    def test_durable_ledger_restores_lock_after_materialization_failure_without_reroll(self):
        write_json(self.package, model_package(self.rows))
        real_write = live._write_json
        def fail_lock_write(path, payload):
            if path.name == live.LOCK_NAME:
                raise OSError("Simulated interruption after durable prediction append.")
            return real_write(path, payload)
        with patch.object(live, "_write_json", side_effect=fail_lock_write):
            with self.assertRaises(OSError):
                self.run_live()
        durable = self.ledger.read_bytes()
        expected = self.events()[-1]["lock"]
        self.assertFalse(self.lock.exists())
        with patch.object(models, "make_prediction", side_effect=AssertionError("Recover the recorded prediction.")):
            dashboard = self.run_live()
        self.assertEqual(read_json(self.lock), expected)
        self.assertEqual(self.ledger.read_bytes(), durable)
        self.assertEqual(dashboard["nextForecast"]["joy"], expected["agents"]["joy"]["prediction"])

    def test_incomplete_ledger_write_blocks_publication_without_rewriting_history(self):
        write_json(self.lock, legacy_lock(self.rows))
        self.run_live(package=False)
        with self.ledger.open("ab") as handle:
            handle.write(b'{"eventType":')
        corrupted = self.ledger.read_bytes()
        locked = self.lock.read_bytes()
        with self.assertRaisesRegex(ValueError, "incomplete final write"):
            self.run_live(package=False)
        self.assertEqual(self.ledger.read_bytes(), corrupted)
        self.assertEqual(self.lock.read_bytes(), locked)

    def test_changed_sealed_ticket_or_recorded_outcome_is_rejected(self):
        write_json(self.package, model_package(self.rows))
        self.run_live()
        original = read_json(self.lock)
        changed = copy.deepcopy(original)
        changed["agents"]["joy"]["prediction"]["results"][0]["label"] = "Changed after sealing"
        write_json(self.lock, changed)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.run_live()
        write_json(self.lock, original)
        self.append_locked_result()
        self.run_live(package=False)
        self.rows[-1]["front"] = [31, 32, 33, 34, 35]
        write_json(self.archive, {"draws": self.rows})
        with self.assertRaisesRegex(ValueError, "disagrees"):
            self.run_live(package=False)

    def test_invalid_or_duplicate_archive_fails_before_ledger_creation(self):
        for bad_rows in ([*self.rows, self.rows[-1]], [{**self.rows[0], "front": [1, 1, 2, 3, 4]}]):
            write_json(self.archive, {"draws": bad_rows})
            with self.assertRaises(ValueError):
                self.run_live(package=False)
            self.assertFalse(self.ledger.exists())

    def test_archive_cannot_bypass_a_missing_pending_draw(self):
        write_json(self.lock, legacy_lock(self.rows))
        original = self.lock.read_bytes()
        self.run_live(package=False)
        pending = read_json(self.lock)
        later_issue, later_date = protocol.next_target(pending)
        self.rows.append({"issue": later_issue, "date": later_date, "front": [1, 2, 3, 4, 5], "back": [1, 2]})
        write_json(self.archive, {"draws": self.rows})
        write_json(self.package, model_package(self.rows))
        with patch.object(models, "make_prediction", side_effect=AssertionError("Missing previous results block new predictions.")):
            dashboard = self.run_live()
        self.assertEqual(dashboard["predictionGate"]["status"], "awaiting_result")
        self.assertIn("without the pending target result", dashboard["predictionGate"]["reason"])
        self.assertEqual(self.lock.read_bytes(), original)
        self.assertEqual([event["eventType"] for event in self.events()], ["prediction_locked"])

    def test_same_day_prediction_is_allowed_only_before_2100_beijing(self):
        _issue, day = protocol.next_target(self.rows[-1])
        for utc_time, expected in (("01:00:00", "prediction_locked"),
                                   ("12:59:59", "prediction_locked"),
                                   ("13:00:00", "blocked"), ("13:25:00", "blocked")):
            with self.subTest(utc_time=utc_time), tempfile.TemporaryDirectory() as temporary:
                data = Path(temporary)
                write_json(data / "draws.json", {"draws": self.rows})
                package = data / "package.json"
                write_json(package, model_package(self.rows))
                now = datetime.fromisoformat(day + "T" + utc_time + "+00:00")
                dashboard = live.run_live(data, package, now=now)
                self.assertEqual(dashboard["predictionGate"]["status"], expected)
                self.assertEqual(dashboard["predictionGate"]["publicationCutoff"], day + "T21:00:00+08:00")
                self.assertEqual((data / live.LOCK_NAME).exists(), expected == "prediction_locked")
                if expected == "blocked":
                    self.assertEqual(dashboard["nextForecast"]["joy"]["results"], [])
                    events = [json.loads(line) for line in (data / live.LEDGER_NAME).read_text().splitlines()]
                    self.assertEqual([event["eventType"] for event in events], ["no_prior_prediction"])

    def test_inference_crossing_cutoff_does_not_backdate_a_new_lock(self):
        write_json(self.package, model_package(self.rows))
        _issue, day = protocol.next_target(self.rows[-1])
        before = datetime.fromisoformat(day + "T12:59:59+00:00")
        after = datetime.fromisoformat(day + "T13:00:00+00:00")
        with patch.object(live, "_utc_now", side_effect=[before, after]):
            dashboard = live.run_live(self.data, self.package)
        self.assertEqual(dashboard["predictionGate"]["status"], "blocked")
        self.assertFalse(self.lock.exists())
        self.assertEqual([event["eventType"] for event in self.events()], ["no_prior_prediction"])

    def test_previously_sealed_ticket_is_preserved_after_cutoff_while_result_is_delayed(self):
        write_json(self.package, model_package(self.rows))
        self.run_live()
        lock = read_json(self.lock)
        original, events = self.lock.read_bytes(), self.ledger.read_bytes()
        now = datetime.fromisoformat(lock["date"] + "T14:00:00+00:00")
        with patch.object(models, "make_prediction", side_effect=AssertionError("Keep the existing pre-cutoff ticket.")):
            dashboard = live.run_live(self.data, self.package, now=now)
        self.assertEqual(dashboard["predictionGate"]["status"], "awaiting_result")
        self.assertEqual(self.lock.read_bytes(), original)
        self.assertEqual(self.ledger.read_bytes(), events)

    def test_import_rejects_a_lock_created_at_or_after_cutoff(self):
        lock = legacy_lock(self.rows)
        lock["predictionLockedAt"] = lock["date"] + "T21:00:00+08:00"
        write_json(self.lock, lock)
        original = self.lock.read_bytes()
        with self.assertRaisesRegex(ValueError, "sales-close deadline"):
            live.run_live(self.data, now=datetime.fromisoformat(lock["date"] + "T14:00:00+00:00"))
        self.assertEqual(self.lock.read_bytes(), original)
        self.assertEqual(self.ledger.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()

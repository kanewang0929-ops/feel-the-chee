"""Exercise optimizer retirement and forecast locks using isolated data only."""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import joy_kane_duel as duel
from scripts import run_simulation_batch as batch


def archive_rows(count=208):
    start = date(2025, 1, 1)
    return [{
        "issue": f"25{index + 1:03d}",
        "date": (start + timedelta(days=index)).isoformat(),
        "front": " ".join(str((index * 3 + offset * 7) % 35 + 1) for offset in range(5)),
        "back": " ".join(str((index * 5 + offset * 3) % 12 + 1) for offset in range(2)),
    } for index in range(count)]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_engine(data, *, simulation=False, seed=12345):
    files = {
        "DATA": data,
        "DRAW_FILE": data / "draws.json",
        "DASHBOARD_FILE": data / "joy-kane-dashboard.json",
        "AUDIT_FILE": data / "joy-kane-audit.json",
        "PREDICTION_LEDGER": data / "joy-kane-predictions.jsonl",
        "RESULT_LEDGER": data / "joy-kane-results.jsonl",
        "STATE_FILE": data / "joy-kane-model-state.json",
        "LIVE_LOCK_FILE": data / "joy-kane-live-lock.json",
        "WARMUP": 200,
    }
    env = {
        "DUEL_SIMULATION_MODE": "1" if simulation else "0",
        "DUEL_SIMULATION_SEED": str(seed),
        # Retired settings must not restore the search or affect predictions.
        "DUEL_CYCLES": "1000000",
        "MIN_HOURS_BETWEEN_DUEL_TRAINING": "0",
        "FORCE_DUEL_TRAINING": "1",
    }
    with patch.multiple(duel, **files), patch.dict("os.environ", env), contextlib.redirect_stdout(io.StringIO()):
        duel.main()
    return load(files["STATE_FILE"]), load(files["DASHBOARD_FILE"])


def write_retired_state(data):
    stale = {"agents": {}}
    for name, signals in duel.AGENTS.items():
        stale["agents"][name] = {
            "optimizedWeights": {
                area: {signal: 1.0 if index == 0 else 0.0 for index, signal in enumerate(signals)}
                for area in duel.AREAS
            },
            "dailyTraining": {"cyclesPerRun": 1000000, "accepted": True},
        }
    (data / "joy-kane-model-state.json").write_text(json.dumps(stale), encoding="utf-8")
    historical_log = '{"eventType":"daily_million_cycle_training","generatedAt":"2025-01-01T00:00:00Z"}\n'
    (data / "joy-kane-training-log.jsonl").write_text(historical_log, encoding="utf-8")
    return historical_log


class OptimizerRemovalTests(unittest.TestCase):
    def test_retired_weights_and_force_settings_cannot_change_replay_or_forecast(self):
        with tempfile.TemporaryDirectory() as tmp:
            clean, stale = Path(tmp) / "clean", Path(tmp) / "stale"
            for data in (clean, stale):
                data.mkdir()
                (data / "draws.json").write_text(json.dumps({"draws": archive_rows()}), encoding="utf-8")
            log = write_retired_state(stale)
            clean_state, clean_dashboard = run_engine(clean)
            stale_state, stale_dashboard = run_engine(stale)
            self.assertEqual(clean_dashboard["nextForecast"], stale_dashboard["nextForecast"])
            self.assertEqual(stale_state["optimizer"], {"enabled": False, "status": "removed"})
            self.assertNotIn("dailyTraining", stale_dashboard["method"])
            for name in duel.AGENTS:
                self.assertEqual(clean_state["agents"][name]["weights"], stale_state["agents"][name]["weights"])
                self.assertEqual(stale_state["agents"][name]["observations"], 8)
                self.assertNotIn("optimizedWeights", stale_state["agents"][name])
                self.assertNotIn("dailyTraining", stale_state["agents"][name])
            self.assertFalse((clean / "joy-kane-training-log.jsonl").exists())
            self.assertEqual((stale / "joy-kane-training-log.jsonl").read_text(encoding="utf-8"), log)

    def test_locked_ticket_survives_retirement_and_is_scored_when_result_arrives(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            rows = archive_rows()
            archive = data / "draws.json"
            archive.write_text(json.dumps({"draws": rows}), encoding="utf-8")
            run_engine(data)
            lock_file = data / "joy-kane-live-lock.json"
            locked_bytes = lock_file.read_bytes()
            lock = load(lock_file)
            write_retired_state(data)
            run_engine(data)
            self.assertEqual(lock_file.read_bytes(), locked_bytes)

            joy_ticket = lock["agents"]["joy"]["prediction"]["results"][0]
            rows.append({"issue": lock["issue"], "date": lock["date"],
                         "front": " ".join(joy_ticket["front"]), "back": " ".join(joy_ticket["back"])})
            archive.write_text(json.dumps({"draws": rows}), encoding="utf-8")
            run_engine(data)
            result = batch.read_jsonl(data / "joy-kane-results.jsonl")[-1]
            self.assertEqual(result["predictionId"], lock["predictionId"])
            self.assertEqual(result["predictionLockedAt"], lock["predictionLockedAt"])
            self.assertEqual(result["joy"]["bestTotalHits"], 7)
            for name in duel.AGENTS:
                scored = result[name]["tickets"][0]
                sealed = lock["agents"][name]["prediction"]["results"][0]
                self.assertEqual(scored["front"], sealed["front"])
                self.assertEqual(scored["back"], sealed["back"])
            self.assertNotEqual(load(lock_file)["issue"], lock["issue"])

    def test_seeded_simulation_keeps_full_chronological_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            streams = []
            for run in range(2):
                data = Path(tmp) / str(run)
                data.mkdir()
                (data / "draws.json").write_text(json.dumps({"draws": archive_rows()}), encoding="utf-8")
                if run:
                    write_retired_state(data)
                state, dashboard = run_engine(data, simulation=True)
                predictions, fingerprint = batch.validate_run(data, dashboard)
                self.assertEqual(len(predictions), 8)
                self.assertNotIn("livePredictionLock", state)
                streams.append(([row["agents"] for row in predictions], fingerprint))
            self.assertEqual(streams[0], streams[1])


if __name__ == "__main__":
    unittest.main()

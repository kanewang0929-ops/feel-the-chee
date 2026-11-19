#!/usr/bin/env python3
"""Run isolated, independently seeded full-history Joy/Kane simulations."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "scripts" / "joy_kane_duel.py"
DRAW_SOURCE = ROOT / "data" / "draws.json"
ENGINE_VERSION = "joy-kane-sim-v1"
WARMUP_DRAWS = 200


def seed_for(batch_seed: str, simulation_id: int) -> int:
    material = f"{batch_seed}:{simulation_id}:{ENGINE_VERSION}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSONL at {path.name}:{line_number}: {exc}") from exc
    return rows


def validate_ticket_list(tickets: list[dict], label: str) -> None:
    if len(tickets) != 1:
        raise RuntimeError(f"{label} must contain exactly one official ticket; found {len(tickets)}.")
    ticket = tickets[0]
    front = [int(value) for value in ticket.get("front", [])]
    back = [int(value) for value in ticket.get("back", [])]
    if len(front) != 5 or len(set(front)) != 5 or any(value < 1 or value > 35 for value in front):
        raise RuntimeError(f"{label} has an invalid front selection: {front}.")
    if len(back) != 2 or len(set(back)) != 2 or any(value < 1 or value > 12 for value in back):
        raise RuntimeError(f"{label} has an invalid back selection: {back}.")


def normalized_archive(run_data: Path) -> list[dict]:
    payload = json.loads((run_data / "draws.json").read_text(encoding="utf-8"))
    raw = payload.get("draws", []) if isinstance(payload, dict) else payload
    rows = []
    for row in raw:
        front = [int(value) for value in str(row.get("front", "")).replace(",", " ").split()]
        back = [int(value) for value in str(row.get("back", "")).replace(",", " ").split()]
        if len(front) != 5 or len(set(front)) != 5 or any(value < 1 or value > 35 for value in front):
            continue
        if len(back) != 2 or len(set(back)) != 2 or any(value < 1 or value > 12 for value in back):
            continue
        rows.append({
            "issue": str(row.get("issue", "")),
            "date": str(row.get("date", "")),
            "front": sorted(front),
            "back": sorted(back),
        })
    return sorted(rows, key=lambda row: (row["date"], int(row["issue"] or 0)))


def validate_run(run_data: Path, dashboard: dict) -> tuple[list[dict], str]:
    archive = normalized_archive(run_data)
    predictions = read_jsonl(run_data / "joy-kane-predictions.jsonl")
    results = read_jsonl(run_data / "joy-kane-results.jsonl")
    audit_payload = json.loads((run_data / "joy-kane-audit.json").read_text(encoding="utf-8"))
    audit = audit_payload.get("rows", [])
    if not predictions or len(predictions) != len(results) or len(predictions) != len(audit):
        raise RuntimeError(
            "Prediction, result, and audit row counts must be equal and non-zero "
            f"(got {len(predictions)}, {len(results)}, {len(audit)})."
        )
    if dashboard.get("method", {}).get("dailyTraining", {}).get("simulationMode") is not True:
        raise RuntimeError("Dashboard does not identify this run as simulation mode.")
    if dashboard.get("method", {}).get("dailyTraining", {}).get("ranToday") is not False:
        raise RuntimeError("Daily optimizer unexpectedly ran during simulation.")
    if "livePredictionLock" in dashboard:
        raise RuntimeError("Simulation dashboard must not expose a livePredictionLock object.")
    if dashboard.get("nextForecast", {}).get("forecastScope") != "archive_next_draw_not_live":
        raise RuntimeError("The next forecast is not clearly labelled as archive-derived.")
    if (run_data / "joy-kane-live-lock.json").exists():
        raise RuntimeError("Simulation created a live prediction lock file.")
    state_payload = json.loads((run_data / "joy-kane-model-state.json").read_text(encoding="utf-8"))
    if "livePredictionLock" in state_payload:
        raise RuntimeError("Simulation model state must not expose live-lock metadata.")

    previous_date = None
    seen_ids = set()
    for index, (prediction, result, audit_row) in enumerate(zip(predictions, results, audit)):
        expected_fields = ("issue", "date", "predictionId")
        for field in expected_fields:
            if prediction.get(field) != result.get(field) or prediction.get(field) != audit_row.get(field):
                raise RuntimeError(f"Prediction/result/audit {field} mismatch at replay row {index + 1}.")
        if prediction.get("eventType") != "prediction_locked" or result.get("eventType") != "result_scored":
            raise RuntimeError(f"Unexpected event type at replay row {index + 1}.")
        prediction_id = prediction.get("predictionId")
        if not prediction_id or prediction_id in seen_ids:
            raise RuntimeError(f"Missing or duplicate prediction ID at replay row {index + 1}.")
        seen_ids.add(prediction_id)
        archive_target_index = WARMUP_DRAWS + index
        if archive_target_index >= len(archive):
            raise RuntimeError("Replay contains more predictions than eligible archive draws.")
        expected_target = archive[archive_target_index]
        expected_training = archive[archive_target_index - 1]
        if prediction.get("issue") != expected_target["issue"] or prediction.get("date") != expected_target["date"]:
            raise RuntimeError(f"Prediction target does not match the frozen archive at replay row {index + 1}.")
        if prediction.get("trainingThroughIssue") != expected_training["issue"] or prediction.get("trainingThroughDate") != expected_training["date"]:
            raise RuntimeError(f"Training prefix does not match the exact prior archive at replay row {index + 1}.")
        target_date = date.fromisoformat(prediction["date"])
        training_date = date.fromisoformat(prediction["trainingThroughDate"])
        if previous_date is not None and target_date <= previous_date:
            raise RuntimeError(f"Target dates are not strictly chronological at replay row {index + 1}.")
        if training_date >= target_date:
            raise RuntimeError(f"Training prefix reaches target date at replay row {index + 1}.")
        if prediction.get("trainingDrawCount") != WARMUP_DRAWS + index:
            raise RuntimeError(f"Unexpected training-prefix length at replay row {index + 1}.")
        if prediction.get("trainingThroughIssue") == prediction.get("issue"):
            raise RuntimeError(f"Target issue appears in its own training prefix at replay row {index + 1}.")
        if prediction.get("livePredictionLock") is not False:
            raise RuntimeError(f"Live lock was reused or marked true at replay row {index + 1}.")
        if prediction.get("futureLeakage") is not False or result.get("futureLeakage") is not False:
            raise RuntimeError(f"Future-leakage flag failed at replay row {index + 1}.")
        if audit_row.get("futureLeakage") is not False or audit_row.get("usedLivePredictionLock") is not False:
            raise RuntimeError(f"Audit guardrail failed at replay row {index + 1}.")
        try:
            locked_at = datetime.fromisoformat(prediction["predictionLockedAt"].replace("Z", "+00:00"))
            revealed_at = datetime.fromisoformat(result["actualRevealedAt"].replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise RuntimeError(f"Missing or invalid prediction/reveal timestamp at replay row {index + 1}.") from exc
        if revealed_at < locked_at:
            raise RuntimeError(f"Result was revealed before prediction lock at replay row {index + 1}.")

        agents = prediction.get("agents", {})
        for agent in ("joy", "kane"):
            sealed_tickets = agents.get(agent, {}).get("tickets", [])
            validate_ticket_list(sealed_tickets, f"row {index + 1} {agent} sealed prediction")
            scored_tickets = result.get(agent, {}).get("tickets", [])
            validate_ticket_list(scored_tickets, f"row {index + 1} {agent} scored result")
            if scored_tickets[0].get("front") != sealed_tickets[0].get("front"):
                raise RuntimeError(f"{agent} front ticket changed after lock at replay row {index + 1}.")
            if scored_tickets[0].get("back") != sealed_tickets[0].get("back"):
                raise RuntimeError(f"{agent} back ticket changed after lock at replay row {index + 1}.")

        actual = result.get("actual", {})
        validate_ticket_list([actual], f"row {index + 1} revealed result")
        expected_actual = {
            "front": [f"{value:02d}" for value in expected_target["front"]],
            "back": [f"{value:02d}" for value in expected_target["back"]],
        }
        if actual != expected_actual or audit_row.get("actual") != actual:
            raise RuntimeError(f"Revealed result does not match the frozen archive at replay row {index + 1}.")
        previous_date = target_date

    if len(predictions) != len(archive) - WARMUP_DRAWS:
        raise RuntimeError("Replay did not cover every eligible historical archive draw.")

    first_prediction = predictions[0]
    fingerprint = hashlib.sha256(
        json.dumps(first_prediction["agents"], sort_keys=True).encode("utf-8")
    ).hexdigest()
    return predictions, fingerprint


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--batch-seed", default=os.environ.get("DUEL_BATCH_SEED", "pilot-2026-11-19"))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "simulation-artifacts")
    args = parser.parse_args()
    if args.count < 2:
        raise SystemExit("At least two simulations are required to test seed independence.")
    if not DRAW_SOURCE.exists():
        raise SystemExit(f"Historical draw archive not found: {DRAW_SOURCE}")

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    summaries = []
    fingerprints = set()

    with tempfile.TemporaryDirectory(prefix="joy-kane-sims-") as temp_root:
        temp_root = Path(temp_root)
        for simulation_id in range(1, args.count + 1):
            run_data = temp_root / f"run-{simulation_id:02d}" / "data"
            run_data.mkdir(parents=True)
            shutil.copy2(DRAW_SOURCE, run_data / "draws.json")
            seed = seed_for(args.batch_seed, simulation_id)
            env = os.environ.copy()
            env.update({
                "DUEL_DATA_DIR": str(run_data),
                "DUEL_SIMULATION_MODE": "1",
                "DUEL_SIMULATION_SEED": str(seed),
                "DUEL_WARMUP_DRAWS": str(WARMUP_DRAWS),
                "DUEL_CYCLES": "1",
                "MIN_HOURS_BETWEEN_DUEL_TRAINING": "999999",
            })
            completed = subprocess.run(
                [sys.executable, str(ENGINE)],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=2400,
            )
            if completed.returncode:
                raise RuntimeError(
                    f"Simulation {simulation_id} failed (exit {completed.returncode}).\n{completed.stdout[-12000:]}"
                )
            dashboard = json.loads((run_data / "joy-kane-dashboard.json").read_text(encoding="utf-8"))
            predictions, fingerprint = validate_run(run_data, dashboard)
            fingerprints.add(fingerprint)
            summary = dashboard["summary"]
            if summary.get("drawsEvaluated") != len(predictions):
                raise RuntimeError(f"Simulation {simulation_id} dashboard count does not match its ledgers.")
            summaries.append({
                "simulationId": simulation_id,
                "seed": seed,
                "drawsEvaluated": summary["drawsEvaluated"],
                "dateRange": summary["dateRange"],
                "joy": summary["joy"],
                "kane": summary["kane"],
                "duelWins": summary["duelWins"],
                "firstPredictionFingerprint": fingerprint,
                "dailyTrainingRan": dashboard["method"]["dailyTraining"]["ranToday"],
                "simulationMode": dashboard["method"]["dailyTraining"]["simulationMode"],
                "fullReplayAuditRowsValidated": len(predictions),
            })
            if simulation_id == 1:
                trace = output / "representative-trace-run-01"
                trace.mkdir(parents=True, exist_ok=True)
                for name in (
                    "joy-kane-audit.json",
                    "joy-kane-predictions.jsonl",
                    "joy-kane-results.jsonl",
                    "joy-kane-dashboard.json",
                    "joy-kane-model-state.json",
                ):
                    shutil.copy2(run_data / name, trace / name)
            print(
                f"Completed and audited {simulation_id}/{args.count}: seed={seed}, "
                f"draws={summary['drawsEvaluated']}, Joy={summary['joy']['averageBestTotalHits']}, "
                f"Kane={summary['kane']['averageBestTotalHits']}",
                flush=True,
            )

    distinct = len(fingerprints)
    report = {
        "engineVersion": ENGINE_VERSION,
        "batchSeed": args.batch_seed,
        "simulationCount": args.count,
        "independentFirstPredictions": distinct,
        "allFirstPredictionsDistinct": distinct == args.count,
        "simulationSummaries": summaries,
        "guardrails": {
            "oneOfficialTicketPerAgentPerDraw": True,
            "allPredictionResultAuditRowsValidated": True,
            "livePredictionLockReadOrWrite": False,
            "dailyOptimizerRan": False,
            "walkForwardArchiveReplay": True,
            "detailedTracePolicy": "One representative trace (run 01); compact summaries and full-row validation for every run.",
        },
    }
    (output / "simulation-batch-summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if distinct < args.count:
        raise SystemExit(
            f"Seed-independence check failed: {distinct} distinct first predictions across {args.count} simulations."
        )
    print(json.dumps({
        "simulationCount": args.count,
        "independentFirstPredictions": distinct,
        "summaryFile": str(output / "simulation-batch-summary.json"),
    }, indent=2))


if __name__ == "__main__":
    main()

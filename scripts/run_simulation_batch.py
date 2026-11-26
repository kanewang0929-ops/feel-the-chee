#!/usr/bin/env python3
"""Run isolated, independently seeded full-history Joy/Kane simulations."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAW_SOURCE = ROOT / "data" / "draws.json"
ENGINE_VERSION = "joy-kane-quantum-sim-v2"
WARMUP_DRAWS = 200
BATCH_CYCLES = 100

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
    if dashboard.get("method", {}).get("training", {}).get("simulationMode") is not True:
        raise RuntimeError("Dashboard does not identify this run as simulation mode.")
    if dashboard.get("method", {}).get("optimizer", {}).get("enabled") is not False:
        raise RuntimeError("Simulation must identify the separate optimizer as disabled.")
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


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def seal_event(handle, event) -> None:
    # Flush each prediction before accessing its target result. A failed cycle
    # is never published; fsync both complete journals at the cycle boundary.
    handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    handle.flush()


def replay_cycle(draws: list[dict], *, cycle: int, batch_seed: str, run_data: Path,
                 prefix_hashes: list[str] | None = None) -> tuple[dict, dict]:
    """One complete chronological learning cycle. Never touches live files."""
    from scripts import quantum_models as quantum
    from scripts import quantum_protocol as protocol

    if len(draws) <= WARMUP_DRAWS:
        raise ValueError("The archive must contain more than 200 warm-up draws.")
    run_data.mkdir(parents=True, exist_ok=True)
    write_json(run_data / "draws.json", {"draws": [
        {**row, "front": " ".join(map(str, row["front"])), "back": " ".join(map(str, row["back"]))}
        for row in draws
    ]})
    seed = seed_for(batch_seed, cycle)
    states = {name: quantum.initial_state(name, seed) for name in ("joy", "kane")}
    totals = {name: {"front": 0, "back": 0, "total": 0} for name in states}
    wins = {"joy": 0, "kane": 0, "tie": 0}
    audit = []
    if prefix_hashes is None:
        prefix_hashes = [protocol.digest(draws[:index]) for index in range(len(draws))]
    pred_path, result_path = run_data / "joy-kane-predictions.jsonl", run_data / "joy-kane-results.jsonl"
    with pred_path.open("w", encoding="utf-8") as predictions, result_path.open("w", encoding="utf-8") as results:
        for index in range(len(draws)):
            # Public target metadata is separate from the unrevealed outcome.
            issue, target_date = draws[index]["issue"], draws[index]["date"]
            forecasts, distributions = {}, {}
            before = {name: protocol.digest(state) for name, state in states.items()}
            for name in states:
                ticket_seed = int(protocol.digest([seed, name, issue, target_date])[:16], 16)
                forecasts[name], distributions[name] = quantum.make_prediction(
                    name, states[name], issue, target_date, ticket_seed
                )
                if protocol.digest(states[name]) != before[name]:
                    raise RuntimeError("Inference mutated a quantum model state.")
                validate_ticket_list(forecasts[name]["results"], f"cycle {cycle} {name}")
            locked_at = stamp()
            prediction_id = protocol.digest([ENGINE_VERSION, seed, issue, target_date, prefix_hashes[index]])[:24]
            if index >= WARMUP_DRAWS:
                event = {
                    "eventType": "prediction_locked", "predictionId": prediction_id,
                    "issue": issue, "date": target_date, "trainingDrawCount": index,
                    "trainingThroughIssue": draws[index - 1]["issue"],
                    "trainingThroughDate": draws[index - 1]["date"],
                    "historyDigest": prefix_hashes[index], "predictionLockedAt": locked_at,
                    "livePredictionLock": False, "futureLeakage": False,
                    "agents": {name: {
                        "modelVersion": states[name]["modelVersion"],
                        "modelFamily": states[name]["modelFamily"],
                        "modelStateHash": before[name], "tickets": forecasts[name]["results"],
                    } for name in states},
                }
                seal_event(predictions, event)

            # Only here is the target outcome passed to scoring or learning.
            actual = {"front": draws[index]["front"], "back": draws[index]["back"]}
            revealed_at = stamp()
            metrics = {name: protocol.score_ticket(forecasts[name]["results"][0], actual) for name in states}
            learning = {name: quantum.train_on_draw(states[name], actual, distributions[name]) for name in states}
            if index < WARMUP_DRAWS:
                continue
            ranks = {name: (value["bestTotalHits"], value["bestFrontHits"], value["bestBackHits"])
                     for name, value in metrics.items()}
            winner = "tie" if ranks["joy"] == ranks["kane"] else max(ranks, key=ranks.get)
            wins[winner] += 1
            for name, value in metrics.items():
                totals[name]["front"] += value["bestFrontHits"]
                totals[name]["back"] += value["bestBackHits"]
                totals[name]["total"] += value["bestTotalHits"]
            formatted = {area: [f"{number:02d}" for number in actual[area]] for area in ("front", "back")}
            result = {
                "eventType": "result_scored", "predictionId": prediction_id,
                "issue": issue, "date": target_date, "actual": formatted,
                **metrics, "winner": winner, "learning": learning,
                "modelStateBefore": before,
                "modelStateAfter": {name: protocol.digest(state) for name, state in states.items()},
                "predictionLockedAt": locked_at, "actualRevealedAt": revealed_at,
                "futureLeakage": False,
            }
            seal_event(results, result)
            audit.append({
                "issue": issue, "date": target_date, "predictionId": prediction_id,
                "actual": formatted, **metrics, "winner": winner,
                "trainingThroughIssue": draws[index - 1]["issue"],
                "predictionLockedAt": locked_at, "actualRevealedAt": revealed_at,
                "futureLeakage": False, "usedLivePredictionLock": False,
            })
        for handle in (predictions, results):
            handle.flush()
            os.fsync(handle.fileno())

    count = len(draws) - WARMUP_DRAWS
    summary = {
        "drawsEvaluated": count, "trainedDrawCount": len(draws), "warmupDraws": WARMUP_DRAWS,
        "dateRange": {"earliest": draws[WARMUP_DRAWS]["date"], "latest": draws[-1]["date"]},
        "duelWins": wins,
        "scoreDefinition": "One sealed ticket per agent and draw; exact front plus back matches.",
        "learningObjective": "unordered_ticket_negative_log_likelihood",
        "randomTicketBaseline": {"expectedFrontHits": 25 / 35, "expectedBackHits": 4 / 12,
                                 "expectedTotalHits": 25 / 35 + 4 / 12},
    }
    for name, values in totals.items():
        summary[name] = {"draws": count,
                         "averageBestFrontHits": round(values["front"] / count, 6),
                         "averageBestBackHits": round(values["back"] / count, 6),
                         "averageBestTotalHits": round(values["total"] / count, 6)}
        quantum.validate_state(states[name])
        if states[name]["observations"] != len(draws):
            raise RuntimeError("Every historical draw, including warm-up, must be learned exactly once per cycle.")
    dashboard = {
        "modelVersion": quantum.MODEL_VERSION, "generatedAt": stamp(),
        "method": {"training": {"kind": "chronological_replay", "simulationMode": True,
                                "simulationSeed": seed, "replayCycles": 1},
                   "optimizer": {"enabled": False, "status": "removed"}},
        "summary": summary, "nextForecast": {"forecastScope": "archive_next_draw_not_live"},
    }
    write_json(run_data / "joy-kane-dashboard.json", dashboard)
    write_json(run_data / "joy-kane-audit.json", {"modelVersion": quantum.MODEL_VERSION, "rows": audit})
    write_json(run_data / "joy-kane-model-state.json", {"modelVersion": quantum.MODEL_VERSION, "agents": states})
    predictions, fingerprint = validate_run(run_data, dashboard)
    summary.update({"simulationId": cycle, "seed": seed,
                    "firstPredictionFingerprint": fingerprint, "simulationMode": True,
                    "optimizerEnabled": False, "fullReplayAuditRowsValidated": len(predictions),
                    "finalModelHashes": {name: protocol.digest(state) for name, state in states.items()}})
    return summary, states


def run_batch(archive_path: Path, output: Path, *, batch_seed: str, count: int = BATCH_CYCLES,
              diagnostic: bool = False, source_commit: str | None = None) -> dict:
    from scripts import quantum_models as quantum
    from scripts import quantum_protocol as protocol

    output.mkdir(parents=True, exist_ok=True)
    # A new attempt owns these completion markers even if input validation
    # fails. Never leave a prior successful batch looking like this attempt.
    package_path = output / "joy-kane-batch-models.json"
    for filename in ("joy-kane-batch-models.json", "simulation-batch-summary.json",
                     "simulation-model-checkpoints.json", "simulation-progress.json"):
        stale_path = output / filename
        if stale_path.exists():
            stale_path.unlink()
    if count != BATCH_CYCLES and not diagnostic:
        raise ValueError("A production training batch must contain exactly 100 complete chronological cycles.")
    if count < 1:
        raise ValueError("At least one diagnostic cycle is required.")
    draws = protocol.load_archive(archive_path)
    if len(draws) <= WARMUP_DRAWS:
        raise ValueError("Need more than 200 historical draws.")
    source_digest = protocol.engine_digest()
    prefixes = [protocol.digest(draws[:index]) for index in range(len(draws))]
    summaries, checkpoints = [], []
    archive = protocol.archive_metadata(draws)
    with tempfile.TemporaryDirectory(prefix="joy-kane-quantum-") as temporary:
        run_data = Path(temporary) / "data"
        for cycle in range(1, count + 1):
            summary, states = replay_cycle(draws, cycle=cycle, batch_seed=batch_seed,
                                          run_data=run_data, prefix_hashes=prefixes)
            summaries.append(summary)
            checkpoints.append({"cycle": cycle, "seed": summary["seed"], "agents": states,
                                "modelHashes": summary["finalModelHashes"]})
            if cycle in {1, count}:
                destination = output / f"trace-cycle-{cycle:03d}"
                destination.mkdir(parents=True, exist_ok=True)
                for filename in ("joy-kane-predictions.jsonl", "joy-kane-results.jsonl", "joy-kane-audit.json",
                                 "joy-kane-dashboard.json", "joy-kane-model-state.json"):
                    shutil.copy2(run_data / filename, destination / filename)
            write_json(output / "simulation-progress.json", {"completedCycles": cycle, "requiredCycles": count,
                       "archive": archive, "engineVersion": ENGINE_VERSION, "updatedAt": stamp()})
            print(f"Completed cycle {cycle}/{count}: Joy {summary['joy']['averageBestTotalHits']:.6f}, "
                  f"Kane {summary['kane']['averageBestTotalHits']:.6f}", flush=True)
    fingerprint_count = len({row["firstPredictionFingerprint"] for row in summaries})
    if fingerprint_count != count:
        raise RuntimeError("Independent cycle model/prediction fingerprints are not distinct.")
    if protocol.engine_digest() != source_digest:
        raise RuntimeError("Engine source changed during training; no completed batch may be published.")
    report = {
        "engineVersion": ENGINE_VERSION, "modelVersion": quantum.MODEL_VERSION,
        "engineDigest": source_digest,
        "batchSeed": batch_seed, "simulationCount": count, "archive": archive,
        "independentFirstPredictions": fingerprint_count, "allFirstPredictionsDistinct": True,
        "simulationSummaries": summaries, "selectedCycle": count,
        "selectionPolicy": "fixed_final_cycle", "diagnosticOnly": diagnostic,
        "guardrails": {
            "oneOfficialTicketPerAgentPerDraw": True,
            "allPredictionResultAuditRowsValidated": True,
            "livePredictionLockReadOrWrite": False, "dailyOptimizerRan": False,
            "walkForwardArchiveReplay": True, "trainingOnlyInsideCycles": True,
            "modelInitialization": "fresh independent state at the start of each cycle",
            "learningObjective": "unordered_ticket_negative_log_likelihood",
            "warmupLearning": "First 200 draws train the model but are excluded from reported hit scores.",
            "detailedTracePolicy": "Cycles 1 and 100 retained; every cycle audited; all 100 final model checkpoints retained.",
        },
    }
    write_json(output / "simulation-model-checkpoints.json", {"engineVersion": ENGINE_VERSION,
               "archive": archive, "cycles": checkpoints})
    write_json(output / "simulation-batch-summary.json", report)
    if not diagnostic:
        package = {
            "schemaVersion": 2, "modelVersion": quantum.MODEL_VERSION,
            "engineVersion": ENGINE_VERSION, "engineDigest": source_digest,
            "batch": {"id": batch_seed, "seed": batch_seed, "status": "complete",
                      "cycleCount": BATCH_CYCLES, "completedCycles": count,
                      "selectedCycle": BATCH_CYCLES, "selectionPolicy": "fixed_final_cycle"},
            "archive": archive, "warmupDraws": WARMUP_DRAWS,
            "agents": checkpoints[-1]["agents"], "generatedAt": stamp(),
            "sourceCommit": source_commit or os.environ.get("SIMULATION_SOURCE_COMMIT") or os.environ.get("GITHUB_SHA", "local-unpublished"),
        }
        protocol.validate_package(package, draws)
        write_json(package_path, package)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Joy and Kane only through 100 complete chronological cycles.")
    parser.add_argument("--count", type=int, default=BATCH_CYCLES)
    parser.add_argument("--batch-seed", default=os.environ.get("DUEL_BATCH_SEED", "quantum-2026-11-26"))
    parser.add_argument("--archive", type=Path, default=DRAW_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "simulation-artifacts")
    parser.add_argument("--diagnostic", action="store_true", help="Test-only execution; never exports a production model package.")
    args = parser.parse_args()
    report = run_batch(args.archive, args.output_dir.resolve(), batch_seed=args.batch_seed,
                       count=args.count, diagnostic=args.diagnostic)
    print(json.dumps({"simulationCount": report["simulationCount"], "diagnosticOnly": args.diagnostic,
                      "summaryFile": str(args.output_dir / "simulation-batch-summary.json")}, indent=2))


if __name__ == "__main__":
    main()

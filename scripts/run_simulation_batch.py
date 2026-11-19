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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "scripts" / "joy_kane_duel.py"
DRAW_SOURCE = ROOT / "data" / "draws.json"
ENGINE_VERSION = "joy-kane-sim-v1"


def seed_for(batch_seed: str, simulation_id: int) -> int:
    material = f"{batch_seed}:{simulation_id}:{ENGINE_VERSION}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


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
                "DUEL_WARMUP_DRAWS": "200",
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
            prediction_lines = (run_data / "joy-kane-predictions.jsonl").read_text(encoding="utf-8").splitlines()
            first_prediction = json.loads(prediction_lines[0])
            if first_prediction.get("livePredictionLock") is not False:
                raise RuntimeError(f"Simulation {simulation_id} reused or marked a live prediction lock.")
            if first_prediction.get("futureLeakage") is not False:
                raise RuntimeError(f"Simulation {simulation_id} failed the leakage flag check.")
            ticket_material = first_prediction["agents"]
            fingerprint = hashlib.sha256(
                json.dumps(ticket_material, sort_keys=True).encode("utf-8")
            ).hexdigest()
            fingerprints.add(fingerprint)
            summary = dashboard["summary"]
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
                f"Completed {simulation_id}/{args.count}: seed={seed}, "
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
            "livePredictionLockReadOrWrite": False,
            "dailyOptimizerRan": False,
            "walkForwardArchiveReplay": True,
            "detailedTracePolicy": "One representative run only; compact summaries retained for every run.",
        },
    }
    (output / "ten-simulation-summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if distinct < args.count:
        raise SystemExit(
            f"Seed-independence check failed: {distinct} distinct first predictions across {args.count} simulations."
        )
    print(json.dumps({
        "simulationCount": args.count,
        "independentFirstPredictions": distinct,
        "summaryFile": str(output / "ten-simulation-summary.json"),
    }, indent=2))


if __name__ == "__main__":
    main()

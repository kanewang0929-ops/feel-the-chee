#!/usr/bin/env python3
"""Isolated research registry. Never writes production model state or locks."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import evaluate_chronological_holdout as evaluation
from scripts import joy_kane_duel as duel

VERSION = "research-v1"
WINDOW = 200
ADAPTATION = 100
BASE_SEED = 20261125
AGENTS = ("joy", "kane")
EXPECTED = 25 / 35 + 4 / 12


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def validate_batch(batch, draws):
    rows = batch["simulationSummaries"]
    guards = batch["guardrails"]
    if (batch["simulationCount"] != 100 or len(rows) != 100
            or not batch["allFirstPredictionsDistinct"]
            or len({r["seed"] for r in rows}) != 100
            or guards["livePredictionLockReadOrWrite"] is not False
            or guards["dailyOptimizerRan"] is not False
            or guards["allPredictionResultAuditRowsValidated"] is not True
            or any(r["drawsEvaluated"] != len(draws) - 200 for r in rows)):
        raise ValueError("Research requires a complete, isolated and audited 100-run batch")
    return {agent: statistics.fmean(r[agent]["averageBestTotalHits"] for r in rows) for agent in AGENTS}


def choose_config(agent, experiments, archive_id, engine_id):
    """Explore each configuration once per archive/engine; prioritize prior evidence."""
    configs = list(evaluation.CANDIDATES)
    relevant = [r for r in experiments if r["agent"] == agent and r["engineId"] == engine_id]
    attempted = {r["configuration"]["name"] for r in relevant if r["archiveId"] == archive_id}
    remaining = [c for c in configs if c["name"] not in attempted]
    def rank(config):
        scores = [r["deltaVsResearchBaseline"] for r in relevant if r["configuration"]["name"] == config["name"]]
        # New hypotheses first; otherwise favor configurations with stronger prior evidence.
        return (bool(scores), -statistics.fmean(scores) if scores else 0, config["name"])
    return min(remaining, key=rank) if remaining else None


def replay(agent, draws, config, seed, start, score_start):
    state = duel.default_state(agent)
    hits = []
    for index in range(start, len(draws)):
        history = draws[:index]
        target = draws[index]
        features = {area: duel.number_signals(history, area) for area in duel.AREAS}
        draw_seed = evaluation.prediction_seed(agent, history, target["issue"], target["date"], seed)
        tickets, bundles = evaluation.candidate_prediction(agent, history, state, features,
                                                           target["issue"], target["date"], draw_seed)
        actual = {"front": target["front"], "back": target["back"]}
        score = duel.score_tickets(tickets, actual)["bestTotalHits"]
        if index >= score_start:
            hits.append(score)
        evaluation.update_candidate_state(state, duel.score_signal_bundles(bundles, actual), config)
    return statistics.fmean(hits), state


def build_registry(draws, batch, live, registry, source_commit, engine_id, output):
    if len(draws) < 200 + ADAPTATION + WINDOW:
        raise ValueError("Insufficient draws for research window")
    if len({r["issue"] for r in draws}) != len(draws) or any(a["date"] >= b["date"] for a,b in zip(draws,draws[1:])):
        raise ValueError("Archive has duplicate issues or non-chronological dates")
    batch_means = validate_batch(batch, draws)
    archive_id = digest(draws)
    experiments = registry.get("experiments", [])
    batches = registry.get("batches", [])
    batch_id = str(batch["batchSeed"])
    if any(b["id"] == batch_id for b in batches):
        return registry
    score_start = len(draws) - WINDOW
    start = score_start - ADAPTATION
    created = []
    for agent in AGENTS:
        config = choose_config(agent, experiments, archive_id, engine_id)
        if config is None:
            continue
        seed = evaluation.agent_seed(BASE_SEED, agent)
        baseline_config = evaluation.CANDIDATES[0]
        baseline, _ = replay(agent, draws, baseline_config, seed, start, score_start)
        if config == baseline_config:
            score, state = replay(agent, draws, config, seed, start, score_start)
        else:
            score, state = replay(agent, draws, config, seed, start, score_start)
        package = {
            "schemaVersion": 1, "researchVersion": VERSION, "agent": agent,
            "sourceCommit": source_commit, "engineId": engine_id, "archiveId": archive_id,
            "archiveThrough": draws[-1]["date"], "configuration": config, "seed": seed,
            "researchState": state, "adaptationStart": draws[start]["date"],
            "scoringStart": draws[score_start]["date"], "scoringDraws": WINDOW,
            "scope": "exploratory historical research only", "promotionEligible": False,
        }
        candidate_id = digest(package)
        path = output / "candidates" / (candidate_id + ".json")
        if path.exists() and load_json(path) != package:
            raise ValueError("Immutable candidate collision")
        if not path.exists():
            write_json(path, package)
        delta = score - baseline
        record = {
            "id": candidate_id, "agent": agent, "engineId": engine_id,
            "archiveId": archive_id, "configuration": config, "seed": seed,
            "batchId": batch_id, "score": score, "researchBaseline": baseline,
            "randomExpectation": EXPECTED, "deltaVsResearchBaseline": delta,
            "scoringDraws": WINDOW, "archiveThrough": draws[-1]["date"],
            "decision": "research_only" if delta > 0 else "not_improved",
            "reason": "Exploratory result; fresh prospective evaluation and production comparison required"
                      if delta > 0 else "Did not outperform the matched research baseline",
            "promotionEligible": False, "package": "candidates/" + candidate_id + ".json",
        }
        experiments.append(record)
        created.append(candidate_id)
    batches.append({"id": batch_id, "archiveId": archive_id, "archiveThrough": draws[-1]["date"],
                    "replayMeans": batch_means, "candidateIds": created, "sourceCommit": source_commit})
    production = {}
    for agent in AGENTS:
        snapshot = live["agents"][agent]
        snapshot_id = digest(snapshot)
        snapshot_path = output / "production-snapshots" / (snapshot_id + ".json")
        if not snapshot_path.exists():
            write_json(snapshot_path, snapshot)
        production[agent] = {"version": snapshot["modelVersion"], "snapshotId": snapshot_id,
                             "snapshot": "production-snapshots/" + snapshot_id + ".json",
                             "observations": snapshot["observations"]}
    return {"schemaVersion": 1, "researchVersion": VERSION, "production": production,
            "experiments": experiments, "batches": batches, "promotionEnabled": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--live-state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT / "data" or (ROOT / "data") in output.parents:
        raise ValueError("Research output must be outside the live data directory")
    registry_path = output / "registry.json"
    registry = load_json(registry_path) if registry_path.exists() else {}
    engine_id = digest({name: hashlib.sha256((ROOT / "scripts" / name).read_bytes()).hexdigest()
                        for name in ("joy_kane_duel.py", "evaluate_chronological_holdout.py", "closed_loop_research.py")})
    draws = evaluation.load_archive(args.archive)
    raw = load_json(args.archive)
    raw_rows = raw["draws"] if isinstance(raw, dict) else raw
    if len(raw_rows) != len(draws):
        raise ValueError("Archive contains invalid records; refusing research")
    updated = build_registry(draws, load_json(args.batch), load_json(args.live_state),
                             registry, args.source_commit, engine_id, output)
    write_json(registry_path, updated)
    print("Research registry:", len(updated["experiments"]), "experiments;", len(updated["batches"]), "batches")


if __name__ == "__main__":
    main()

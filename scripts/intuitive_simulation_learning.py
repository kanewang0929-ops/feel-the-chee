#!/usr/bin/env python3
"""Blend the latest three-source historical audit into the live Agent state.

This runs after the general daily simulation archiver. It restores and updates
AI, Chee, and Agent Instinct weights, then appends the instinct-specific change
to the permanent Agent logs.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BACKTEST_FILE = DATA / "hybrid-backtest.json"
STATE_FILE = DATA / "hybrid-model-state.json"
SIM_LOG_FILE = DATA / "hybrid-simulation-log.json"
MASTER_LOG_FILE = DATA / "hybrid-master-learning-log.json"
CYCLE_LOG_FILE = DATA / "model-cycle-log.json"

SOURCES = ("ai", "chee", "instinct")
CATEGORIES = ("allThree", "aiChee", "aiInstinct", "cheeInstinct", "aiOnly", "cheeOnly", "instinctOnly")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append(path: Path, row: dict) -> None:
    rows = read_json(path, [])
    if not isinstance(rows, list):
        rows = []
    rows.append(row)
    write_json(path, rows)


def normalized_sources(ema: dict) -> dict:
    raw = {name: math.exp(2.0 * (float(ema.get(name, 1.0)) - 1.0)) for name in SOURCES}
    total = sum(raw.values()) or 1.0
    floor = 0.15
    free = 1.0 - floor * len(SOURCES)
    return {name: round(floor + free * raw[name] / total, 6) for name in SOURCES}


def normalized_categories(ema: dict) -> dict:
    values = {name: float(ema.get(name, 1.0)) for name in CATEGORIES}
    mean = sum(values.values()) / len(values) or 1.0
    return {name: round(max(0.65, min(1.35, value / mean)), 6) for name, value in values.items()}


def main() -> None:
    backtest = read_json(BACKTEST_FILE, {})
    final_state = backtest.get("finalState", {})
    if not isinstance(final_state, dict) or not final_state:
        raise RuntimeError("Three-source Agent backtest must finish before instinct learning.")
    current = read_json(STATE_FILE, {})
    if not isinstance(current, dict):
        current = {}
    before = json.loads(json.dumps(current))
    current.setdefault("sourceEma", {})
    current.setdefault("strategyEma", {})
    current.setdefault("sourceWeights", {})
    current.setdefault("strategyWeights", {})
    for area in ("front", "back"):
        current["sourceEma"].setdefault(area, {})
        current["strategyEma"].setdefault(area, {})
        for source in SOURCES:
            old = float(current["sourceEma"][area].get(source, 1.0))
            simulated = float(final_state.get("sourceEma", {}).get(area, {}).get(source, old))
            current["sourceEma"][area][source] = 0.72 * old + 0.28 * simulated
        for category in CATEGORIES:
            old = float(current["strategyEma"][area].get(category, 1.0))
            simulated = float(final_state.get("strategyEma", {}).get(area, {}).get(category, old))
            current["strategyEma"][area][category] = 0.72 * old + 0.28 * simulated
        current["sourceWeights"][area] = normalized_sources(current["sourceEma"][area])
        current["strategyWeights"][area] = normalized_categories(current["strategyEma"][area])
    current["version"] = 2
    current["modelVersion"] = "v2.0-intuitive-fusion-agent"
    current["observations"] = max(int(current.get("observations", 0)), int(final_state.get("observations", 0)))
    if isinstance(final_state.get("cumulative"), dict):
        current["cumulative"] = final_state["cumulative"]
    now = datetime.now(timezone.utc).isoformat()
    runs = int(current.get("instinctSimulationLearning", {}).get("runs", 0)) + 1
    summary = backtest.get("summary", {})
    observed = summary.get("observed", {})
    current["instinctSimulationLearning"] = {
        "runs": runs,
        "updatedAt": now,
        "backtestVersion": backtest.get("backtestVersion"),
        "drawsEvaluated": summary.get("drawsEvaluated"),
        "ticketsEvaluated": summary.get("ticketsEvaluated"),
        "averageFrontHits": observed.get("averageFrontHitsPerTicket"),
        "averageBackHits": observed.get("averageBackHitsPerTicket"),
        "rule": "Agent Instinct is an independent stochastic source. Its influence rises or falls only after historical or live results are revealed.",
    }
    current["updatedAt"] = now
    write_json(STATE_FILE, current)
    event = {
        "eventType": "agent-instinct-simulation-learning",
        "generatedAt": now,
        "modelVersion": current["modelVersion"],
        "backtestVersion": backtest.get("backtestVersion"),
        "drawsEvaluated": summary.get("drawsEvaluated"),
        "ticketsEvaluated": summary.get("ticketsEvaluated"),
        "averageFrontHits": observed.get("averageFrontHitsPerTicket"),
        "averageBackHits": observed.get("averageBackHitsPerTicket"),
        "weightsBefore": before.get("sourceWeights", {}),
        "weightsAfter": current.get("sourceWeights", {}),
        "strategyWeightsAfter": current.get("strategyWeights", {}),
        "simulationRuns": runs,
        "explanationPolicy": "Agent Instinct selections are logged but do not expose a reasoning narrative.",
    }
    append(SIM_LOG_FILE, event)
    append(MASTER_LOG_FILE, event)
    cycle_rows = read_json(CYCLE_LOG_FILE, [])
    if isinstance(cycle_rows, list) and cycle_rows:
        cycle_rows[-1]["agentInstinct"] = event
        write_json(CYCLE_LOG_FILE, cycle_rows)
    print(json.dumps(event, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

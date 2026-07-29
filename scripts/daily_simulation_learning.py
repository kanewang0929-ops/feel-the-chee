#!/usr/bin/env python3
"""Persist daily simulation logs and apply bounded simulation learning.

AI and the Fusion Agent adapt from their historical simulations. Feel the Chee
remains formula-only by design: its simulation is permanently logged, but its
formula parameters are never trained on draw outcomes.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

AI_BACKTEST = DATA / "ai-backtest.json"
CHEE_BACKTEST = DATA / "chee-backtest.json"
HYBRID_BACKTEST = DATA / "hybrid-backtest.json"
AI_STATE = DATA / "model-state.json"
CHEE_STATE = DATA / "chee-model-state.json"
HYBRID_STATE = DATA / "hybrid-model-state.json"

AI_LIVE_LOG = DATA / "learning-log.json"
HYBRID_LIVE_LOG = DATA / "hybrid-learning-log.json"
AI_MASTER_LOG = DATA / "ai-master-learning-log.json"
HYBRID_MASTER_LOG = DATA / "hybrid-master-learning-log.json"
AI_FORECAST_HISTORY = DATA / "forecast-history.json"
HYBRID_FORECAST_HISTORY = DATA / "hybrid-history.json"
AI_MASTER_HISTORY = DATA / "ai-forecast-master-history.json"
HYBRID_MASTER_HISTORY = DATA / "hybrid-forecast-master-history.json"

AI_SIM_LOG = DATA / "ai-simulation-log.json"
CHEE_SIM_LOG = DATA / "chee-simulation-log.json"
HYBRID_SIM_LOG = DATA / "hybrid-simulation-log.json"
CYCLE_LOG = DATA / "model-cycle-log.json"

PROFILE_LABELS = {
    "局部漂移": "local-drift",
    "自适应波形": "adaptive-wave",
    "区间换挡": "regime-shift",
    "宽带采样": "wide-band",
    "长期均值锚": "mean-anchor",
}
SOURCE_NAMES = ("ai", "chee")
STRATEGIES = ("both", "aiOnly", "cheeOnly")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clamp(lower: float, upper: float, value: float) -> float:
    return max(lower, min(upper, value))


def clone(payload):
    return json.loads(json.dumps(payload))


def append_event(path: Path, event: dict) -> None:
    rows = read_json(path, [])
    if not isinstance(rows, list):
        rows = []
    rows.append(event)
    write_json(path, rows)


def merge_unique(source_path: Path, target_path: Path, key_fields: tuple[str, ...]) -> int:
    source = read_json(source_path, [])
    target = read_json(target_path, [])
    if not isinstance(source, list):
        source = []
    if not isinstance(target, list):
        target = []

    def row_key(row: dict) -> tuple:
        return tuple(str(row.get(field, "")) for field in key_fields)

    existing = {row_key(row) for row in target if isinstance(row, dict)}
    added = 0
    for row in source:
        if not isinstance(row, dict):
            continue
        key = row_key(row)
        if key in existing:
            continue
        target.append(row)
        existing.add(key)
        added += 1
    write_json(target_path, target)
    return added


def normalized_source_weights(ema: dict[str, float]) -> dict[str, float]:
    raw = {name: math.exp(2.2 * (float(ema[name]) - 1.0)) for name in SOURCE_NAMES}
    total = sum(raw.values()) or 1.0
    ai_weight = clamp(0.25, 0.75, raw["ai"] / total)
    return {"ai": round(ai_weight, 6), "chee": round(1.0 - ai_weight, 6)}


def normalized_strategy_weights(ema: dict[str, float]) -> dict[str, float]:
    mean = sum(float(ema[name]) for name in STRATEGIES) / len(STRATEGIES)
    mean = mean or 1.0
    return {
        name: round(clamp(0.65, 1.35, float(ema[name]) / mean), 6)
        for name in STRATEGIES
    }


def update_ai_state(ai_backtest: dict, run_id: str, generated_at: str) -> dict:
    state = read_json(
        AI_STATE,
        {"version": 2, "profiles": {}, "temperatureAdjustment": 0.0},
    )
    if not isinstance(state, dict):
        state = {"version": 2, "profiles": {}, "temperatureAdjustment": 0.0}
    before = clone(state)
    summary = ai_backtest.get("summary", {})
    by_profile = summary.get("byProfile", {})

    profile_rows = []
    for label, row in by_profile.items():
        try:
            simulated_loss = float(row["averageModelCurveLoss"])
        except (KeyError, TypeError, ValueError):
            continue
        name = PROFILE_LABELS.get(label, str(label))
        current = state.setdefault("profiles", {}).setdefault(name, {})
        previous_loss = float(current.get("emaCurveDistance", simulated_loss))
        blended_loss = 0.72 * previous_loss + 0.28 * simulated_loss
        current.update(
            evaluations=max(8, int(current.get("evaluations", 0))),
            emaCurveDistance=round(blended_loss, 6),
            simulationCurveDistance=round(simulated_loss, 6),
            simulationDraws=int(row.get("draws", 0)),
            simulationUpdatedAt=generated_at,
        )
        profile_rows.append(
            {
                "name": name,
                "label": label,
                "draws": int(row.get("draws", 0)),
                "averageCurveLoss": round(simulated_loss, 6),
            }
        )

    benchmark = summary.get("curveBenchmark", {})
    model_loss = float(benchmark.get("modelAverageLoss", 0.0) or 0.0)
    mean60_loss = float(benchmark.get("trailingMean60AverageLoss", model_loss) or model_loss)
    persistence_loss = float(benchmark.get("persistenceAverageLoss", model_loss) or model_loss)
    excess_vs_mean = model_loss - mean60_loss

    # When the model loses to the 60-draw positional mean, narrow the sampling
    # band. When it beats that anchor, permit slightly broader exploration.
    target_temperature_adjustment = clamp(-0.18, 0.25, -3.0 * excess_vs_mean)
    old_adjustment = float(state.get("temperatureAdjustment", 0.0) or 0.0)
    state["temperatureAdjustment"] = round(
        0.65 * old_adjustment + 0.35 * target_temperature_adjustment,
        4,
    )

    best_profile = (
        min(profile_rows, key=lambda row: row["averageCurveLoss"])
        if profile_rows
        else None
    )
    simulation_runs = int(state.get("simulationLearning", {}).get("runs", 0)) + 1
    state["simulationLearning"] = {
        "runs": simulation_runs,
        "lastRunId": run_id,
        "updatedAt": generated_at,
        "drawsEvaluated": int(summary.get("drawsEvaluated", 0)),
        "ticketsEvaluated": int(summary.get("ticketsEvaluated", 0)),
        "bestProfile": best_profile,
        "profilePerformance": profile_rows,
        "curveBenchmark": {
            "modelAverageLoss": round(model_loss, 6),
            "persistenceAverageLoss": round(persistence_loss, 6),
            "trailingMean60AverageLoss": round(mean60_loss, 6),
            "excessVsTrailingMean60": round(excess_vs_mean, 6),
        },
        "strategyAdjustment": {
            "temperatureAdjustment": state["temperatureAdjustment"],
            "rule": (
                "Historical simulation profile losses update profile EMAs. "
                "The model narrows its sampling band when it underperforms the "
                "60-draw positional-mean benchmark."
            ),
        },
    }
    state["updatedAt"] = generated_at
    write_json(AI_STATE, state)

    observed = summary.get("observed", {})
    return {
        "runId": run_id,
        "generatedAt": generated_at,
        "model": "AI curve sampler",
        "modelVersion": ai_backtest.get("modelVersion"),
        "backtestVersion": ai_backtest.get("backtestVersion"),
        "drawsEvaluated": summary.get("drawsEvaluated"),
        "ticketsEvaluated": summary.get("ticketsEvaluated"),
        "averageFrontHits": observed.get("averageFrontHitsPerTicket"),
        "averageBackHits": observed.get("averageBackHitsPerTicket"),
        "profilePerformance": profile_rows,
        "curveBenchmark": state["simulationLearning"]["curveBenchmark"],
        "stateBefore": {
            "temperatureAdjustment": before.get("temperatureAdjustment"),
            "selectedProfile": before.get("selectedProfile"),
        },
        "stateAfter": {
            "temperatureAdjustment": state.get("temperatureAdjustment"),
            "selectedProfile": state.get("selectedProfile"),
            "simulationRuns": simulation_runs,
        },
    }


def update_chee_state(chee_backtest: dict, run_id: str, generated_at: str) -> dict:
    state = read_json(CHEE_STATE, {})
    if not isinstance(state, dict):
        state = {}
    summary = chee_backtest.get("summary", {})
    observed = summary.get("observed", {})
    runs = int(state.get("simulationRuns", 0)) + 1
    state.update(
        version=1,
        modelVersion=chee_backtest.get("modelVersion"),
        formulaVersion=chee_backtest.get("formulaVersion"),
        formulaOnly=True,
        learningEnabled=False,
        strategyAdjustment="none",
        simulationRuns=runs,
        lastSimulationRunId=run_id,
        lastSimulationAt=generated_at,
        lastSimulationSummary={
            "drawsEvaluated": summary.get("drawsEvaluated"),
            "ticketsEvaluated": summary.get("ticketsEvaluated"),
            "averageFrontHits": observed.get("averageFrontHitsPerTicket"),
            "averageBackHits": observed.get("averageBackHitsPerTicket"),
            "averageElementSimilarity": observed.get("averageElementSimilarity"),
        },
        immutableRule=(
            "Feel the Chee is audited every day but never trained on historical "
            "draw outcomes. Its issue/date He Tu and Luo Shu formula stays fixed."
        ),
        updatedAt=generated_at,
    )
    write_json(CHEE_STATE, state)
    return {
        "runId": run_id,
        "generatedAt": generated_at,
        "model": "Feel the Chee formula",
        "modelVersion": chee_backtest.get("modelVersion"),
        "formulaVersion": chee_backtest.get("formulaVersion"),
        "backtestVersion": chee_backtest.get("backtestVersion"),
        "drawsEvaluated": summary.get("drawsEvaluated"),
        "ticketsEvaluated": summary.get("ticketsEvaluated"),
        "averageFrontHits": observed.get("averageFrontHitsPerTicket"),
        "averageBackHits": observed.get("averageBackHitsPerTicket"),
        "averageElementSimilarity": observed.get("averageElementSimilarity"),
        "formulaOnly": True,
        "learningEnabled": False,
        "strategyAdjustment": "none",
        "simulationRuns": runs,
    }


def update_hybrid_state(hybrid_backtest: dict, run_id: str, generated_at: str) -> dict:
    current = read_json(HYBRID_STATE, {})
    final_state = hybrid_backtest.get("finalState", {})
    if not isinstance(current, dict):
        current = {}
    if not isinstance(final_state, dict):
        final_state = {}
    before = clone(current)

    if not current:
        current = clone(final_state)
    else:
        for area in ("front", "back"):
            current.setdefault("sourceEma", {}).setdefault(area, {})
            current.setdefault("strategyEma", {}).setdefault(area, {})
            for source in SOURCE_NAMES:
                old = float(current["sourceEma"][area].get(source, 1.0))
                simulated = float(
                    final_state.get("sourceEma", {}).get(area, {}).get(source, old)
                )
                current["sourceEma"][area][source] = 0.72 * old + 0.28 * simulated
            for strategy in STRATEGIES:
                old = float(current["strategyEma"][area].get(strategy, 1.0))
                simulated = float(
                    final_state.get("strategyEma", {}).get(area, {}).get(strategy, old)
                )
                current["strategyEma"][area][strategy] = 0.72 * old + 0.28 * simulated

    current.setdefault("sourceWeights", {})
    current.setdefault("strategyWeights", {})
    for area in ("front", "back"):
        current["sourceWeights"][area] = normalized_source_weights(
            current["sourceEma"][area]
        )
        current["strategyWeights"][area] = normalized_strategy_weights(
            current["strategyEma"][area]
        )

    current["observations"] = max(
        int(current.get("observations", 0)),
        int(final_state.get("observations", 0)),
    )
    runs = int(current.get("simulationLearning", {}).get("runs", 0)) + 1
    summary = hybrid_backtest.get("summary", {})
    observed = summary.get("observed", {})
    current["simulationLearning"] = {
        "runs": runs,
        "lastRunId": run_id,
        "updatedAt": generated_at,
        "drawsEvaluated": summary.get("drawsEvaluated"),
        "ticketsEvaluated": summary.get("ticketsEvaluated"),
        "averageFrontHits": observed.get("averageFrontHitsPerTicket"),
        "averageBackHits": observed.get("averageBackHitsPerTicket"),
        "rule": (
            "The live source and category EMAs are blended with the final state "
            "of the sequential historical fusion simulation."
        ),
    }
    current["updatedAt"] = generated_at
    write_json(HYBRID_STATE, current)

    return {
        "runId": run_id,
        "generatedAt": generated_at,
        "model": "Fusion Agent",
        "modelVersion": hybrid_backtest.get("modelVersion"),
        "backtestVersion": hybrid_backtest.get("backtestVersion"),
        "drawsEvaluated": summary.get("drawsEvaluated"),
        "ticketsEvaluated": summary.get("ticketsEvaluated"),
        "averageFrontHits": observed.get("averageFrontHitsPerTicket"),
        "averageBackHits": observed.get("averageBackHitsPerTicket"),
        "weightsBefore": {
            "source": before.get("sourceWeights"),
            "strategy": before.get("strategyWeights"),
        },
        "weightsAfter": {
            "source": current.get("sourceWeights"),
            "strategy": current.get("strategyWeights"),
        },
        "simulationRuns": runs,
    }


def main() -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    run_id = generated_at.replace(":", "").replace("+00:00", "Z")

    ai_backtest = read_json(AI_BACKTEST, {})
    chee_backtest = read_json(CHEE_BACKTEST, {})
    hybrid_backtest = read_json(HYBRID_BACKTEST, {})
    if not ai_backtest.get("summary"):
        raise RuntimeError("AI backtest must run before daily simulation learning.")
    if not chee_backtest.get("summary"):
        raise RuntimeError("Chee backtest must run before daily simulation learning.")
    if not hybrid_backtest.get("summary"):
        raise RuntimeError("Hybrid backtest must run before daily simulation learning.")

    ai_event = update_ai_state(ai_backtest, run_id, generated_at)
    chee_event = update_chee_state(chee_backtest, run_id, generated_at)
    hybrid_event = update_hybrid_state(hybrid_backtest, run_id, generated_at)

    append_event(AI_SIM_LOG, ai_event)
    append_event(CHEE_SIM_LOG, chee_event)
    append_event(HYBRID_SIM_LOG, hybrid_event)

    archived = {
        "aiLearningEvents": merge_unique(
            AI_LIVE_LOG,
            AI_MASTER_LOG,
            ("issue", "modelFamily"),
        ),
        "hybridLearningEvents": merge_unique(
            HYBRID_LIVE_LOG,
            HYBRID_MASTER_LOG,
            ("issue", "modelVersion"),
        ),
        "aiForecastSnapshots": merge_unique(
            AI_FORECAST_HISTORY,
            AI_MASTER_HISTORY,
            ("targetIssue",),
        ),
        "hybridForecastSnapshots": merge_unique(
            HYBRID_FORECAST_HISTORY,
            HYBRID_MASTER_HISTORY,
            ("targetIssue",),
        ),
    }

    cycle_event = {
        "runId": run_id,
        "generatedAt": generated_at,
        "cadence": "daily-24h plus draw-night retries",
        "models": {
            "ai": ai_event,
            "chee": chee_event,
            "hybrid": hybrid_event,
        },
        "archived": archived,
        "storage": {
            "aiSimulationLog": str(AI_SIM_LOG.relative_to(ROOT)),
            "cheeSimulationLog": str(CHEE_SIM_LOG.relative_to(ROOT)),
            "hybridSimulationLog": str(HYBRID_SIM_LOG.relative_to(ROOT)),
            "aiMasterLearningLog": str(AI_MASTER_LOG.relative_to(ROOT)),
            "hybridMasterLearningLog": str(HYBRID_MASTER_LOG.relative_to(ROOT)),
            "cycleLog": str(CYCLE_LOG.relative_to(ROOT)),
        },
    }
    append_event(CYCLE_LOG, cycle_event)
    print(json.dumps(cycle_event, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

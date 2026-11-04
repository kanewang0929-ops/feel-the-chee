#!/usr/bin/env python3
"""Daily one-million complete-history prediction cycles.

Definition:
  1 cycle = evaluate one candidate strategy across every eligible recorded draw,
  in chronological order, from the first walk-forward prediction to the latest.

The implementation precomputes draw-level sufficient statistics, so each candidate
cycle is mathematically equivalent to replaying the whole archive but can be scored
in O(1) instead of repeating billions of Python operations. The accepted champion
is then compared draw-by-draw against the incumbent and stored with its full audit.

AI and Agent may learn. Feel the Chee stays formula-only and is never trained.
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
AI_BACKTEST = DATA / "ai-backtest.json"
AGENT_BACKTEST = DATA / "hybrid-backtest.json"
AI_STATE = DATA / "model-state.json"
AGENT_STATE = DATA / "hybrid-model-state.json"
LOG_FILE = DATA / "full-history-cycle-log.json"

CYCLES = max(1, int(os.environ.get("FULL_HISTORY_CYCLES", "1000000")))
MIN_HOURS = max(0.0, float(os.environ.get("MIN_HOURS_BETWEEN_FULL_HISTORY_RUNS", "20")))
AI_MAX_ANCHOR = 0.95
SOURCES = ("ai", "chee", "instinct")
CATEGORIES = ("allThree", "aiChee", "aiInstinct", "cheeInstinct", "aiOnly", "cheeOnly", "instinctOnly")
AREAS = ("front", "back")
AREA_WEIGHT = {"front": 0.72, "back": 0.28}


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clone(value):
    return json.loads(json.dumps(value))


def clamp(low: float, high: float, value: float) -> float:
    return max(low, min(high, value))


def score_from_loss(loss: float) -> float:
    return round(100.0 * math.exp(-4.0 * max(0.0, loss)), 4)


def last_age_hours(logs: list[dict], now: datetime):
    if not logs:
        return None
    value = logs[-1].get("generatedAt")
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (now - stamp).total_seconds() / 3600.0)


def chrono_split(rows: list, fraction: float = 0.22):
    if len(rows) < 40:
        return rows, rows
    cut = max(20, min(len(rows) - 20, int(len(rows) * (1.0 - fraction))))
    return rows[:cut], rows[cut:]


def ai_row_values(row: dict):
    loss = row.get("curveLoss", {})
    try:
        return float(loss["model"]), float(loss["trailingMean60"])
    except (KeyError, TypeError, ValueError):
        return None


def ai_mean_components(rows: list[dict]):
    values = [ai_row_values(row) for row in rows]
    values = [value for value in values if value]
    if not values:
        raise RuntimeError("AI backtest has no usable draw-level curve losses.")
    return (
        statistics.fmean(value[0] for value in values),
        statistics.fmean(value[1] for value in values),
        len(values),
    )


def ai_loss_from_means(base_mean: float, anchor_mean: float, blend: float) -> float:
    return (1.0 - blend) * base_mean + blend * anchor_mean


def ai_draw_loss(row: dict, blend: float) -> float:
    values = ai_row_values(row)
    if not values:
        return float("nan")
    return ai_loss_from_means(values[0], values[1], blend)


def train_ai_full_cycles(backtest: dict, state: dict, rng: random.Random):
    rows = [row for row in backtest.get("draws", []) if ai_row_values(row)]
    train_rows, validation_rows = chrono_split(rows)
    full_base, full_anchor, full_count = ai_mean_components(rows)
    train_base, train_anchor, train_count = ai_mean_components(train_rows)
    val_base, val_anchor, val_count = ai_mean_components(validation_rows)

    prior = state.get("fullHistoryCycleTraining", {})
    if not isinstance(prior, dict):
        prior = {}
    million = state.get("millionSimulationTraining", {})
    if not isinstance(million, dict):
        million = {}
    current = clamp(
        0.0,
        AI_MAX_ANCHOR,
        float(prior.get("meanAnchorBlend", million.get("meanAnchorBlend", 0.0)) or 0.0),
    )

    incumbent = current
    incumbent_full = ai_loss_from_means(full_base, full_anchor, incumbent)
    incumbent_val = ai_loss_from_means(val_base, val_anchor, incumbent)
    best_objective = 0.72 * incumbent_full + 0.28 * incumbent_val
    accepted_trials = 0

    for index in range(CYCLES):
        progress = index / max(1, CYCLES - 1)
        sigma = 0.24 * (1.0 - progress) + 0.004
        if index % 25 == 0:
            candidate = rng.random() * AI_MAX_ANCHOR
        else:
            candidate = clamp(0.0, AI_MAX_ANCHOR, incumbent + rng.gauss(0.0, sigma))
        full_loss = ai_loss_from_means(full_base, full_anchor, candidate)
        val_loss = ai_loss_from_means(val_base, val_anchor, candidate)
        objective = 0.72 * full_loss + 0.28 * val_loss + 0.00025 * abs(candidate - current)
        if objective + 1e-12 < best_objective:
            incumbent = candidate
            incumbent_full = full_loss
            incumbent_val = val_loss
            best_objective = objective
            accepted_trials += 1

    before_full = ai_loss_from_means(full_base, full_anchor, current)
    before_val = ai_loss_from_means(val_base, val_anchor, current)
    accepted = incumbent_val + 1e-10 < before_val and incumbent_full <= before_full + 1e-9
    final = incumbent if accepted else current
    after_full = ai_loss_from_means(full_base, full_anchor, final)
    after_val = ai_loss_from_means(val_base, val_anchor, final)

    improved_draws = 0
    worsened_draws = 0
    tied_draws = 0
    total_delta = 0.0
    for row in rows:
        before = ai_draw_loss(row, current)
        after = ai_draw_loss(row, final)
        delta = before - after
        total_delta += delta
        if delta > 1e-12:
            improved_draws += 1
        elif delta < -1e-12:
            worsened_draws += 1
        else:
            tied_draws += 1

    old_total = int(prior.get("totalCycles", 0))
    state["fullHistoryCycleTraining"] = {
        "version": 1,
        "cycleDefinition": "one candidate strategy evaluated across every eligible historical draw in chronological order",
        "cyclesPerRun": CYCLES,
        "totalCycles": old_total + CYCLES,
        "runs": int(prior.get("runs", 0)) + 1,
        "drawsPerCycle": full_count,
        "effectiveDrawComparisonsPerRun": CYCLES * full_count,
        "meanAnchorBlend": round(final, 8),
        "fullHistoryLoss": round(after_full, 9),
        "validationLoss": round(after_val, 9),
        "validationScore": score_from_loss(after_val),
        "accepted": accepted,
        "acceptedTrialMoves": accepted_trials,
        "drawByDrawComparison": {
            "improved": improved_draws,
            "worsened": worsened_draws,
            "tied": tied_draws,
            "meanLossImprovement": round(total_delta / max(1, full_count), 9),
        },
        "rule": "Every candidate cycle spans the complete eligible draw archive. Promotion requires lower chronological holdout loss and no worse full-history loss.",
    }
    if accepted:
        million = dict(million)
        million["meanAnchorBlend"] = round(final, 8)
        million["validationLoss"] = round(after_val, 9)
        million["validationScore"] = score_from_loss(after_val)
        million["accepted"] = True
        state["millionSimulationTraining"] = million

    return {
        "cycles": CYCLES,
        "drawsPerCycle": full_count,
        "effectiveDrawComparisons": CYCLES * full_count,
        "trainingDraws": train_count,
        "validationDraws": val_count,
        "anchorBefore": round(current, 8),
        "anchorAfter": round(final, 8),
        "fullHistoryLossBefore": round(before_full, 9),
        "fullHistoryLossAfter": round(after_full, 9),
        "validationLossBefore": round(before_val, 9),
        "validationLossAfter": round(after_val, 9),
        "validationScoreBefore": score_from_loss(before_val),
        "validationScoreAfter": score_from_loss(after_val),
        "accepted": accepted,
        "acceptedTrialMoves": accepted_trials,
        "drawByDraw": {
            "improved": improved_draws,
            "worsened": worsened_draws,
            "tied": tied_draws,
        },
    }


def reward_ratio(source: dict, area: str, name: str) -> float:
    try:
        return float(source.get(area, {}).get(name, {}).get("rewardRatio", 1.0))
    except (TypeError, ValueError):
        return 1.0


def category_ratio(strategy: dict, area: str, name: str) -> float:
    try:
        return float(strategy.get(area, {}).get(name, {}).get("rewardRatio", 1.0))
    except (TypeError, ValueError):
        return 1.0


def agent_rows(backtest: dict):
    output = []
    for row in backtest.get("draws", []):
        evaluation = row.get("evaluation", {})
        source = evaluation.get("sourcePerformance", {})
        strategy = evaluation.get("strategyPerformance", {})
        if source:
            output.append((row, source, strategy))
    return output


def aggregate_agent(rows):
    if not rows:
        raise RuntimeError("Agent backtest has no usable reward rows.")
    source = {area: {name: 0.0 for name in SOURCES} for area in AREAS}
    category = {area: {name: 0.0 for name in CATEGORIES} for area in AREAS}
    for _, source_row, category_row in rows:
        for area in AREAS:
            for name in SOURCES:
                source[area][name] += reward_ratio(source_row, area, name)
            for name in CATEGORIES:
                category[area][name] += category_ratio(category_row, area, name)
    n = len(rows)
    for area in AREAS:
        for name in SOURCES:
            source[area][name] /= n
        for name in CATEGORIES:
            category[area][name] /= n
    return source, category, n


def normalize_source_weights(values: dict[str, float], floor: float = 0.15):
    raw = {name: math.exp(1.7 * (float(values[name]) - 1.0)) for name in SOURCES}
    total = sum(raw.values()) or 1.0
    free = 1.0 - floor * len(SOURCES)
    return {name: floor + free * raw[name] / total for name in SOURCES}


def normalize_category_weights(values: dict[str, float]):
    mean = statistics.fmean(float(values[name]) for name in CATEGORIES) or 1.0
    return {name: clamp(0.65, 1.35, float(values[name]) / mean) for name in CATEGORIES}


def agent_score_from_aggregates(source_means, category_means, source_weights, category_weights):
    total = 0.0
    for area in AREAS:
        source_score = sum(
            float(source_weights[area][name]) * float(source_means[area][name])
            for name in SOURCES
        )
        denominator = sum(float(category_weights[area][name]) for name in CATEGORIES) or 1.0
        category_score = sum(
            float(category_weights[area][name]) * float(category_means[area][name])
            for name in CATEGORIES
        ) / denominator
        total += AREA_WEIGHT[area] * (0.72 * source_score + 0.28 * category_score)
    return total


def perturb_simplex(current: dict[str, float], rng: random.Random, sigma: float):
    values = {name: max(0.001, float(current.get(name, 1.0 / len(SOURCES))) * math.exp(rng.gauss(0.0, sigma))) for name in SOURCES}
    total = sum(values.values()) or 1.0
    normalized = {name: values[name] / total for name in SOURCES}
    floor = 0.15
    free = 1.0 - floor * len(SOURCES)
    positive = {name: max(0.0, normalized[name] - floor) for name in SOURCES}
    positive_total = sum(positive.values())
    if positive_total <= 0:
        return {name: 1.0 / len(SOURCES) for name in SOURCES}
    return {name: floor + free * positive[name] / positive_total for name in SOURCES}


def perturb_categories(current: dict[str, float], rng: random.Random, sigma: float):
    return {
        name: clamp(0.65, 1.35, float(current.get(name, 1.0)) * math.exp(rng.gauss(0.0, sigma)))
        for name in CATEGORIES
    }


def per_draw_agent_score(source_row, category_row, source_weights, category_weights):
    source_means = {area: {name: reward_ratio(source_row, area, name) for name in SOURCES} for area in AREAS}
    category_means = {area: {name: category_ratio(category_row, area, name) for name in CATEGORIES} for area in AREAS}
    return agent_score_from_aggregates(source_means, category_means, source_weights, category_weights)


def train_agent_full_cycles(backtest: dict, state: dict, rng: random.Random):
    rows = agent_rows(backtest)
    train_rows, validation_rows = chrono_split(rows)
    full_source, full_category, full_count = aggregate_agent(rows)
    train_source, train_category, train_count = aggregate_agent(train_rows)
    val_source, val_category, val_count = aggregate_agent(validation_rows)

    current_source = clone(state.get("sourceWeights", {}))
    current_category = clone(state.get("strategyWeights", {}))
    for area in AREAS:
        current_source.setdefault(area, {name: 1.0 / len(SOURCES) for name in SOURCES})
        current_category.setdefault(area, {name: 1.0 for name in CATEGORIES})

    incumbent_source = clone(current_source)
    incumbent_category = clone(current_category)
    before_full = agent_score_from_aggregates(full_source, full_category, current_source, current_category)
    before_val = agent_score_from_aggregates(val_source, val_category, current_source, current_category)
    best_objective = 0.72 * before_full + 0.28 * before_val
    accepted_trials = 0

    empirical_source = {area: normalize_source_weights(train_source[area]) for area in AREAS}
    empirical_category = {area: normalize_category_weights(train_category[area]) for area in AREAS}

    for index in range(CYCLES):
        progress = index / max(1, CYCLES - 1)
        sigma = 0.18 * (1.0 - progress) + 0.006
        if index % 50 == 0:
            candidate_source = {
                area: {
                    name: 0.70 * incumbent_source[area][name] + 0.30 * empirical_source[area][name]
                    for name in SOURCES
                }
                for area in AREAS
            }
            candidate_category = {
                area: {
                    name: 0.70 * incumbent_category[area][name] + 0.30 * empirical_category[area][name]
                    for name in CATEGORIES
                }
                for area in AREAS
            }
        else:
            candidate_source = {area: perturb_simplex(incumbent_source[area], rng, sigma) for area in AREAS}
            candidate_category = {area: perturb_categories(incumbent_category[area], rng, sigma) for area in AREAS}

        full_score = agent_score_from_aggregates(full_source, full_category, candidate_source, candidate_category)
        val_score = agent_score_from_aggregates(val_source, val_category, candidate_source, candidate_category)
        objective = 0.72 * full_score + 0.28 * val_score
        if objective > best_objective + 1e-12:
            incumbent_source = candidate_source
            incumbent_category = candidate_category
            best_objective = objective
            accepted_trials += 1

    candidate_full = agent_score_from_aggregates(full_source, full_category, incumbent_source, incumbent_category)
    candidate_val = agent_score_from_aggregates(val_source, val_category, incumbent_source, incumbent_category)
    accepted = candidate_val > before_val + 1e-10 and candidate_full >= before_full - 1e-10

    final_source = incumbent_source if accepted else current_source
    final_category = incumbent_category if accepted else current_category
    after_full = agent_score_from_aggregates(full_source, full_category, final_source, final_category)
    after_val = agent_score_from_aggregates(val_source, val_category, final_source, final_category)

    improved = worsened = tied = 0
    delta_sum = 0.0
    for _, source_row, category_row in rows:
        old = per_draw_agent_score(source_row, category_row, current_source, current_category)
        new = per_draw_agent_score(source_row, category_row, final_source, final_category)
        delta = new - old
        delta_sum += delta
        if delta > 1e-12:
            improved += 1
        elif delta < -1e-12:
            worsened += 1
        else:
            tied += 1

    prior = state.get("fullHistoryCycleTraining", {})
    if not isinstance(prior, dict):
        prior = {}
    state["fullHistoryCycleTraining"] = {
        "version": 1,
        "cycleDefinition": "one candidate strategy evaluated across every aligned historical draw in chronological order",
        "cyclesPerRun": CYCLES,
        "totalCycles": int(prior.get("totalCycles", 0)) + CYCLES,
        "runs": int(prior.get("runs", 0)) + 1,
        "drawsPerCycle": full_count,
        "effectiveDrawComparisonsPerRun": CYCLES * full_count,
        "validationRawScore": round(after_val, 9),
        "validationScore": round(clamp(0.0, 100.0, 50.0 + 18.0 * (after_val - 1.0)), 4),
        "accepted": accepted,
        "acceptedTrialMoves": accepted_trials,
        "drawByDrawComparison": {
            "improved": improved,
            "worsened": worsened,
            "tied": tied,
            "meanRewardImprovement": round(delta_sum / max(1, full_count), 9),
        },
        "rule": "Every candidate cycle spans the complete aligned draw archive. Promotion requires better chronological holdout reward and no worse full-history reward.",
    }

    if accepted:
        state["sourceWeights"] = {
            area: {name: round(final_source[area][name], 8) for name in SOURCES}
            for area in AREAS
        }
        state["strategyWeights"] = {
            area: {name: round(final_category[area][name], 8) for name in CATEGORIES}
            for area in AREAS
        }

    convert = lambda value: round(clamp(0.0, 100.0, 50.0 + 18.0 * (value - 1.0)), 4)
    return {
        "cycles": CYCLES,
        "drawsPerCycle": full_count,
        "effectiveDrawComparisons": CYCLES * full_count,
        "trainingDraws": train_count,
        "validationDraws": val_count,
        "fullHistoryRawBefore": round(before_full, 9),
        "fullHistoryRawAfter": round(after_full, 9),
        "validationRawBefore": round(before_val, 9),
        "validationRawAfter": round(after_val, 9),
        "validationScoreBefore": convert(before_val),
        "validationScoreAfter": convert(after_val),
        "accepted": accepted,
        "acceptedTrialMoves": accepted_trials,
        "sourceWeightsBefore": current_source,
        "sourceWeightsAfter": clone(state.get("sourceWeights", current_source)),
        "strategyWeightsAfter": clone(state.get("strategyWeights", current_category)),
        "drawByDraw": {"improved": improved, "worsened": worsened, "tied": tied},
    }


def main() -> None:
    now = datetime.now(timezone.utc)
    logs = read_json(LOG_FILE, [])
    if not isinstance(logs, list):
        logs = []
    age = last_age_hours(logs, now)
    if age is not None and age < MIN_HOURS and os.environ.get("FORCE_FULL_HISTORY_CYCLES") != "1":
        print(json.dumps({
            "skipped": True,
            "reason": f"Last full-history million-cycle run was {age:.2f} hours ago.",
            "minimumHoursBetweenRuns": MIN_HOURS,
        }, ensure_ascii=False, indent=2))
        return

    ai_backtest = read_json(AI_BACKTEST, {})
    agent_backtest = read_json(AGENT_BACKTEST, {})
    if not ai_backtest.get("draws"):
        raise RuntimeError("AI backtest must exist before full-history cycle training.")
    if not agent_backtest.get("draws"):
        raise RuntimeError("Agent backtest must exist before full-history cycle training.")

    ai_state = read_json(AI_STATE, {})
    agent_state = read_json(AGENT_STATE, {})
    if not isinstance(ai_state, dict):
        ai_state = {}
    if not isinstance(agent_state, dict):
        agent_state = {}

    run_id = now.strftime("%Y%m%dT%H%M%S.%fZ")
    seed = sum((index + 1) * ord(character) for index, character in enumerate(run_id)) % (2**63 - 1)
    ai_result = train_ai_full_cycles(ai_backtest, ai_state, random.Random(seed ^ 0xA11CE))
    agent_result = train_agent_full_cycles(agent_backtest, agent_state, random.Random(seed ^ 0xA63E7))

    stamp = now.isoformat()
    ai_state["updatedAt"] = stamp
    agent_state["updatedAt"] = stamp
    write_json(AI_STATE, ai_state)
    write_json(AGENT_STATE, agent_state)

    event = {
        "runId": run_id,
        "generatedAt": stamp,
        "cyclesPerAdaptiveModel": CYCLES,
        "cycleDefinition": "one cycle spans every eligible recorded draw from earliest walk-forward prediction to latest",
        "ai": ai_result,
        "agent": agent_result,
        "totalEffectiveDrawComparisons": ai_result["effectiveDrawComparisons"] + agent_result["effectiveDrawComparisons"],
        "learningPolicy": {
            "ai": "compare every draw; accept only if chronological validation improves and full-history loss does not worsen",
            "agent": "compare every aligned draw; accept only if chronological validation improves and full-history reward does not worsen",
            "chee": "formula-only; excluded from machine-learning updates",
        },
        "implementation": "draw-level metrics are precomputed once; candidate cycle scores use exact sufficient-statistic aggregation, then the winning strategy is rechecked draw-by-draw",
        "disclaimer": "This optimizes historical out-of-sample validation. It cannot make a fair random lottery reliably predictable.",
    }
    logs.append(event)
    write_json(LOG_FILE, logs[-400:])
    print(json.dumps(event, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

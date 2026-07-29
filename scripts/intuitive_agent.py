#!/usr/bin/env python3
"""Adaptive three-source agent: AI, formula-only Chee, and Agent Instinct.

Agent Instinct is a seeded stochastic exploration source. It may propose any
legal number, including numbers absent from both upstream models. Its influence
is learned only after actual draws are revealed. It does not produce a narrative
chain of reasoning. All legal lottery combinations remain equally likely in a
fair draw.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DRAWS_FILE = DATA / "draws.json"
AI_FORECAST_FILE = DATA / "forecast.json"
CHEE_FORECAST_FILE = DATA / "chee-forecast.json"
AI_BACKTEST_FILE = DATA / "ai-backtest.json"
CHEE_BACKTEST_FILE = DATA / "chee-backtest.json"
FORECAST_FILE = DATA / "hybrid-forecast.json"
HISTORY_FILE = DATA / "hybrid-history.json"
LOG_FILE = DATA / "hybrid-learning-log.json"
STATE_FILE = DATA / "hybrid-model-state.json"
BACKTEST_FILE = DATA / "hybrid-backtest.json"

VERSION = "v2.0-intuitive-fusion-agent"
SOURCES = ("ai", "chee", "instinct")
CATEGORIES = ("allThree", "aiInstinct", "cheeInstinct", "instinctOnly")
BASELINES = {"front": 25 / 35, "back": 4 / 12}
AREA_CONFIG = {"front": (5, 35, 17, 80), "back": (2, 12, 10, 24)}


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def numbers(value) -> list[int]:
    values = value if isinstance(value, list) else str(value or "").split()
    return [int(number) for number in values]


def formatted(values) -> list[str]:
    return [f"{int(number):02d}" for number in sorted(values)]


def seed_value(*parts) -> int:
    digest = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def normalized_source_weights(ema: dict[str, float]) -> dict[str, float]:
    raw = {name: math.exp(2.0 * (float(ema.get(name, 1.0)) - 1.0)) for name in SOURCES}
    total = sum(raw.values()) or 1.0
    floor = 0.15
    remaining = 1.0 - floor * len(SOURCES)
    return {
        name: round(floor + remaining * raw[name] / total, 6)
        for name in SOURCES
    }


def normalized_strategy_weights(ema: dict[str, float]) -> dict[str, float]:
    values = {name: float(ema.get(name, 1.0)) for name in CATEGORIES}
    mean = statistics.fmean(values.values()) or 1.0
    return {name: round(max(0.65, min(1.35, value / mean)), 6) for name, value in values.items()}


def default_state() -> dict:
    return {
        "version": 2,
        "modelVersion": VERSION,
        "observations": 0,
        "sourceEma": {area: {name: 1.0 for name in SOURCES} for area in ("front", "back")},
        "sourceWeights": {area: {name: 1 / 3 for name in SOURCES} for area in ("front", "back")},
        "strategyEma": {area: {name: 1.0 for name in CATEGORIES} for area in ("front", "back")},
        "strategyWeights": {area: {name: 1.0 for name in CATEGORIES} for area in ("front", "back")},
        "cumulative": {"tickets": 0, "frontHits": 0, "backHits": 0, "draws": 0},
        "updatedAt": None,
    }


def ensure_state(payload) -> dict:
    state = default_state()
    if not isinstance(payload, dict):
        return state
    state["observations"] = int(payload.get("observations", 0))
    state["updatedAt"] = payload.get("updatedAt")
    for area in ("front", "back"):
        for source in SOURCES:
            try:
                state["sourceEma"][area][source] = float(payload.get("sourceEma", {}).get(area, {}).get(source, 1.0))
            except (TypeError, ValueError):
                pass
        state["sourceWeights"][area] = normalized_source_weights(state["sourceEma"][area])
        for category in CATEGORIES:
            try:
                state["strategyEma"][area][category] = float(payload.get("strategyEma", {}).get(area, {}).get(category, 1.0))
            except (TypeError, ValueError):
                pass
        state["strategyWeights"][area] = normalized_strategy_weights(state["strategyEma"][area])
    cumulative = payload.get("cumulative", {})
    for key in state["cumulative"]:
        try:
            state["cumulative"][key] = float(cumulative.get(key, 0))
        except (TypeError, ValueError):
            pass
    for key, value in payload.items():
        if key not in state:
            state[key] = value
    return state


def load_draws() -> list[dict]:
    payload = read_json(DRAWS_FILE, {})
    rows = payload if isinstance(payload, list) else payload.get("draws", [])
    output = []
    for row in rows:
        try:
            front = sorted(numbers(row["front"]))
            back = sorted(numbers(row["back"]))
            issue = str(row["issue"])
            draw_date = str(row["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if len(front) == 5 and len(set(front)) == 5 and all(1 <= n <= 35 for n in front) and len(back) == 2 and len(set(back)) == 2 and all(1 <= n <= 12 for n in back):
            output.append({"issue": issue, "date": draw_date, "front": front, "back": back})
    output.sort(key=lambda row: (row["date"], int(row["issue"])))
    return output


def result_support(results: list[dict], area: str, source: str) -> dict[int, float]:
    raw = defaultdict(float)
    for position, result in enumerate(results, start=1):
        rank = int(result.get("rank") or position)
        rank_weight = 1.0 / (1.0 + 0.24 * max(0, rank - 1))
        if source == "ai":
            quality = min(1.1, max(0.7, float(result.get("fit", 80.0)) / 84.0))
        elif source == "chee":
            quality = min(1.1, max(0.7, float(result.get("cheeValue", 80.0)) / 86.0))
        else:
            quality = 1.0
        for number in numbers(result.get(area, [])):
            raw[number] += rank_weight * quality
    peak = max(raw.values(), default=1.0)
    return {number: value / peak for number, value in raw.items()}


def instinct_payload(target_issue: str, target_date: str, state: dict) -> dict:
    signature = json.dumps(
        {
            "source": state.get("sourceWeights", {}),
            "strategy": state.get("strategyWeights", {}),
            "observations": state.get("observations", 0),
        },
        sort_keys=True,
    )
    rng = random.Random(seed_value(VERSION, target_issue, target_date, signature))
    results = []
    previous_front = set()
    previous_back = set()
    for rank in (1, 2):
        for _ in range(80):
            front = set(rng.sample(range(1, 36), 5))
            back = set(rng.sample(range(1, 13), 2))
            if rank == 1 or (len(front & previous_front) <= 2 and len(back & previous_back) <= 1):
                break
        previous_front, previous_back = front, back
        results.append(
            {
                "rank": rank,
                "label": "直觉落子" if rank == 1 else "直觉回声",
                "front": formatted(front),
                "back": formatted(back),
                "instinctValue": round(84.0 - 4.5 * (rank - 1), 1),
            }
        )
    return {
        "modelVersion": "v1.0-seeded-instinct",
        "targetIssue": str(target_issue),
        "targetDate": target_date,
        "results": results,
        "method": "seeded-stochastic-exploration",
        "explanationPolicy": "no-reasoning-narrative",
    }


def category(has_ai: bool, has_chee: bool) -> str:
    if has_ai and has_chee:
        return "allThree"
    if has_ai:
        return "aiInstinct"
    if has_chee:
        return "cheeInstinct"
    return "instinctOnly"


def candidate_records(ai_results, chee_results, instinct_results, area: str, state: dict) -> dict[int, dict]:
    supports = {
        "ai": result_support(ai_results, area, "ai"),
        "chee": result_support(chee_results, area, "chee"),
        "instinct": result_support(instinct_results, area, "instinct"),
    }
    source_weights = state["sourceWeights"][area]
    strategy_weights = state["strategyWeights"][area]
    universe = sorted(set().union(*(set(row) for row in supports.values())))
    output = {}
    for number in universe:
        has_ai = number in supports["ai"]
        has_chee = number in supports["chee"]
        group = category(has_ai, has_chee)
        score = sum(source_weights[source] * supports[source].get(number, 0.0) for source in SOURCES)
        present = [source for source in SOURCES if number in supports[source]]
        if len(present) > 1:
            score += 0.05 * (len(present) - 1)
        score *= strategy_weights[group]
        output[number] = {
            "number": number,
            "score": score,
            "category": group,
            "sources": present,
            "support": {source: supports[source].get(number, 0.0) for source in SOURCES},
        }
    return output


def gaussian(value: float, mean: float, spread: float) -> float:
    return math.exp(-0.5 * ((value - mean) / max(0.8, spread)) ** 2)


def source_shape(results: list[dict], area: str) -> tuple[float, float, float, float]:
    values = [sorted(numbers(result.get(area, []))) for result in results]
    values = [row for row in values if row]
    if not values:
        return 0.0, 1.0, 0.0, 1.0
    sums = [sum(row) for row in values]
    spans = [row[-1] - row[0] for row in values]
    return statistics.fmean(sums), statistics.pstdev(sums) or 4.0, statistics.fmean(spans), statistics.pstdev(spans) or 3.0


def curve_fit(combo: tuple[int, ...], curve: dict | None) -> float:
    if not curve:
        return 0.5
    centers = curve.get("centers", [])
    sigmas = curve.get("sigmas", [])
    if len(centers) != len(combo):
        return 0.5
    distances = [abs(number - float(centers[index])) / max(1.0, float(sigmas[index]) if index < len(sigmas) else 4.0) for index, number in enumerate(combo)]
    return math.exp(-0.5 * statistics.fmean(distances))


def combo_rows(records, area, all_results, curve=None):
    picks, _, pool_limit, keep = AREA_CONFIG[area]
    ranked = sorted(records, key=lambda n: records[n]["score"], reverse=True)[:pool_limit]
    shape = source_shape(all_results, area)
    rows = []
    for combo in itertools.combinations(sorted(ranked), picks):
        details = [records[number] for number in combo]
        number_score = statistics.fmean(detail["score"] for detail in details)
        instinct_ratio = sum("instinct" in detail["sources"] for detail in details) / picks
        shape_score = 0.58 * gaussian(sum(combo), shape[0], shape[1]) + 0.42 * gaussian(combo[-1] - combo[0], shape[2], shape[3])
        total = 0.62 * number_score + 0.18 * curve_fit(combo, curve) + 0.12 * shape_score + 0.08 * instinct_ratio
        rows.append({"numbers": combo, "score": total})
    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows[:keep]


def mix_for_numbers(values, records) -> dict:
    counts = Counter(records[number]["category"] for number in values)
    return {name: counts[name] for name in CATEGORIES}


def generate_bundle(ai_payload: dict, chee_payload: dict, state: dict) -> dict:
    ai_results = list(ai_payload.get("results", []))
    chee_results = list(chee_payload.get("results", []))
    if not ai_results or not chee_results:
        raise RuntimeError("AI and Chee results are required before Agent Instinct runs.")
    issue = str(ai_payload.get("targetIssue"))
    target_date = str(ai_payload.get("targetDate") or chee_payload.get("targetDate") or "")
    instinct = instinct_payload(issue, target_date, state)
    instinct_results = instinct["results"]
    front_records = candidate_records(ai_results, chee_results, instinct_results, "front", state)
    back_records = candidate_records(ai_results, chee_results, instinct_results, "back", state)
    all_results = [*ai_results, *chee_results, *instinct_results]
    front_rows = combo_rows(front_records, "front", all_results, ai_payload.get("curveForecast", {}).get("front"))
    back_rows = combo_rows(back_records, "back", all_results, ai_payload.get("curveForecast", {}).get("back"))
    combined = [{"front": front, "back": back, "score": 0.8 * front["score"] + 0.2 * back["score"]} for front in front_rows for back in back_rows]
    combined.sort(key=lambda row: row["score"], reverse=True)
    selected = []
    for row in combined:
        if any(len(set(row["front"]["numbers"]) & set(other["front"]["numbers"])) > 3 or len(set(row["back"]["numbers"]) & set(other["back"]["numbers"])) > 1 for other in selected):
            continue
        selected.append(row)
        if len(selected) == 2:
            break
    if len(selected) < 2:
        selected = combined[:2]
    best = combined[0]["score"]
    floor = combined[min(len(combined) - 1, 100)]["score"]
    span = best - floor or 1.0
    output = []
    for rank, row in enumerate(selected, start=1):
        front = row["front"]["numbers"]
        back = row["back"]["numbers"]
        relative = max(0.0, min(1.0, (row["score"] - floor) / span))
        output.append(
            {
                "rank": rank,
                "label": "直觉主选" if rank == 1 else "自由对冲",
                "front": formatted(front),
                "back": formatted(back),
                "agentScore": round(78.0 + 8.0 * relative - 1.2 * (rank - 1), 1),
                "sourceMix": {"front": mix_for_numbers(front, front_records), "back": mix_for_numbers(back, back_records)},
                "numberSources": {
                    "front": {f"{number:02d}": front_records[number]["sources"] for number in front},
                    "back": {f"{number:02d}": back_records[number]["sources"] for number in back},
                },
                "instinctStatement": "Agent 直觉落子，不展开推理。",
            }
        )
    return {"results": output, "instinctInput": instinct}


def generate_results(ai_payload: dict, chee_payload: dict, state: dict) -> list[dict]:
    return generate_bundle(ai_payload, chee_payload, state)["results"]


def source_average_hits(results, actual, area):
    actual_set = set(numbers(actual[area]))
    values = [len(actual_set & set(numbers(result.get(area, [])))) for result in results]
    return statistics.fmean(values) if values else 0.0


def clipped_ratio(value: float, baseline: float) -> float:
    return max(0.25, min(2.5, value / max(0.0001, baseline)))


def category_sets(ai_results, chee_results, instinct_results, area):
    ai = {n for result in ai_results for n in numbers(result.get(area, []))}
    chee = {n for result in chee_results for n in numbers(result.get(area, []))}
    instinct = {n for result in instinct_results for n in numbers(result.get(area, []))}
    return {
        "allThree": ai & chee & instinct,
        "aiInstinct": (ai & instinct) - chee,
        "cheeInstinct": (chee & instinct) - ai,
        "instinctOnly": instinct - ai - chee,
    }


def evaluate_and_update(state, ai_results, chee_results, instinct_results, agent_results, actual, alpha=0.045):
    before = json.loads(json.dumps(state))
    source_performance = {"front": {}, "back": {}}
    strategy_performance = {"front": {}, "back": {}}
    source_map = {"ai": ai_results, "chee": chee_results, "instinct": instinct_results}
    for area in ("front", "back"):
        for source, results in source_map.items():
            average_hits = source_average_hits(results, actual, area)
            ratio = clipped_ratio(average_hits, BASELINES[area])
            old = state["sourceEma"][area][source]
            state["sourceEma"][area][source] = (1 - alpha) * old + alpha * ratio
            source_performance[area][source] = {"averageHits": round(average_hits, 4), "rewardRatio": round(ratio, 4)}
        state["sourceWeights"][area] = normalized_source_weights(state["sourceEma"][area])
        actual_set = set(numbers(actual[area]))
        groups = category_sets(ai_results, chee_results, instinct_results, area)
        number_baseline = (5 / 35) if area == "front" else (2 / 12)
        for group, candidates in groups.items():
            if candidates:
                ratio = clipped_ratio(len(actual_set & candidates) / len(candidates), number_baseline)
                old = state["strategyEma"][area][group]
                state["strategyEma"][area][group] = (1 - alpha) * old + alpha * ratio
                strategy_performance[area][group] = {"candidateCount": len(candidates), "hitCount": len(actual_set & candidates), "rewardRatio": round(ratio, 4)}
        state["strategyWeights"][area] = normalized_strategy_weights(state["strategyEma"][area])
    actual_front = set(numbers(actual["front"]))
    actual_back = set(numbers(actual["back"]))
    rows = []
    for result in agent_results:
        front_hits = sorted(actual_front & set(numbers(result["front"])))
        back_hits = sorted(actual_back & set(numbers(result["back"])))
        rows.append({"rank": result.get("rank"), "label": result.get("label"), "front": result["front"], "back": result["back"], "frontHits": formatted(front_hits), "backHits": formatted(back_hits), "frontHitCount": len(front_hits), "backHitCount": len(back_hits), "sourceMix": result.get("sourceMix", {}), "numberSources": result.get("numberSources", {})})
    state["observations"] += 1
    state["cumulative"]["draws"] += 1
    state["cumulative"]["tickets"] += len(rows)
    state["cumulative"]["frontHits"] += sum(row["frontHitCount"] for row in rows)
    state["cumulative"]["backHits"] += sum(row["backHitCount"] for row in rows)
    state["updatedAt"] = datetime.now(timezone.utc).isoformat()
    return {
        "actual": {"front": formatted(actual_front), "back": formatted(actual_back)},
        "results": rows,
        "summary": {"averageFrontHits": round(statistics.fmean(row["frontHitCount"] for row in rows), 4), "averageBackHits": round(statistics.fmean(row["backHitCount"] for row in rows), 4), "bestTotalHits": max(row["frontHitCount"] + row["backHitCount"] for row in rows)},
        "sourcePerformance": source_performance,
        "strategyPerformance": strategy_performance,
        "weightsBefore": {"source": before["sourceWeights"], "strategy": before["strategyWeights"]},
        "weightsAfter": {"source": state["sourceWeights"], "strategy": state["strategyWeights"]},
        "learningRule": "AI, 风水 and Agent Instinct use bounded EMAs. Each source retains at least 15% influence.",
    }


def archive_previous(previous: dict, evaluation) -> None:
    if not previous.get("targetIssue"):
        return
    history = read_json(HISTORY_FILE, [])
    if not isinstance(history, list):
        history = []
    issue = str(previous["targetIssue"])
    if not any(str(row.get("targetIssue")) == issue for row in history):
        snapshot = dict(previous)
        snapshot["evaluation"] = evaluation
        history.append(snapshot)
        history.sort(key=lambda row: int(row.get("targetIssue", 0)))
        write_json(HISTORY_FILE, history)


def audit_summary(ai_backtest, chee_backtest, hybrid_backtest):
    def source(payload):
        summary = payload.get("summary", {})
        observed = summary.get("observed", {})
        return {"draws": summary.get("drawsEvaluated"), "averageFrontHits": observed.get("averageFrontHitsPerTicket"), "averageBackHits": observed.get("averageBackHitsPerTicket")}
    return {"ai": source(ai_backtest), "chee": source(chee_backtest), "agent": source(hybrid_backtest)}


def main() -> None:
    ai_payload = read_json(AI_FORECAST_FILE, {})
    chee_payload = read_json(CHEE_FORECAST_FILE, {})
    if not ai_payload.get("results") or not chee_payload.get("results"):
        raise RuntimeError("AI and Chee forecasts must exist before Agent Instinct.")
    if str(ai_payload.get("targetIssue")) != str(chee_payload.get("targetIssue")):
        raise RuntimeError("AI and Chee forecasts target different issues.")
    backtest = read_json(BACKTEST_FILE, {})
    state_payload = read_json(STATE_FILE, {}) or backtest.get("finalState", {})
    state = ensure_state(state_payload)
    draws = load_draws()
    previous = read_json(FORECAST_FILE, {})
    logs = read_json(LOG_FILE, [])
    if not isinstance(logs, list):
        logs = []
    evaluation = None
    previous_issue = str(previous.get("targetIssue") or "")
    actual = next((draw for draw in draws if draw["issue"] == previous_issue), None)
    already = next((row for row in logs if str(row.get("issue")) == previous_issue), None)
    if actual and previous.get("results") and not already:
        inputs = previous.get("sourceInputs", {})
        evaluation = evaluate_and_update(state, inputs.get("ai", {}).get("results", []), inputs.get("chee", {}).get("results", []), inputs.get("instinct", {}).get("results", []), previous["results"], actual)
        evaluation.update({"issue": previous_issue, "date": actual["date"], "evaluatedAt": datetime.now(timezone.utc).isoformat(), "modelVersion": previous.get("modelVersion")})
        logs.append(evaluation)
    elif already:
        evaluation = already
    archive_previous(previous, evaluation)
    bundle = generate_bundle(ai_payload, chee_payload, state)
    now = datetime.now(timezone.utc).isoformat()
    output = {
        "modelVersion": VERSION,
        "modelFamily": "adaptive-three-source-intuitive-agent",
        "generatedAt": now,
        "targetIssue": str(ai_payload["targetIssue"]),
        "targetDate": ai_payload.get("targetDate"),
        "sourceModels": {"ai": ai_payload.get("modelVersion"), "chee": chee_payload.get("modelVersion"), "instinct": bundle["instinctInput"]["modelVersion"]},
        "sourceWeights": state["sourceWeights"],
        "strategyWeights": state["strategyWeights"],
        "observations": state["observations"],
        "lastEvaluation": evaluation,
        "sourceAuditSummary": audit_summary(read_json(AI_BACKTEST_FILE, {}), read_json(CHEE_BACKTEST_FILE, {}), backtest),
        "sourceInputs": {"ai": {"modelVersion": ai_payload.get("modelVersion"), "results": ai_payload.get("results", [])}, "chee": {"modelVersion": chee_payload.get("modelVersion"), "results": chee_payload.get("results", [])}, "instinct": bundle["instinctInput"]},
        "results": bundle["results"],
        "storage": {"forecast": "data/hybrid-forecast.json", "history": "data/hybrid-history.json", "learningLog": "data/hybrid-learning-log.json", "modelState": "data/hybrid-model-state.json", "historicalBacktest": "data/hybrid-backtest.json"},
        "note": "Agent Instinct may introduce any legal number. It is stochastic exploration, not human intuition or a winning probability.",
    }
    state["modelVersion"] = VERSION
    state["updatedAt"] = now
    write_json(STATE_FILE, state)
    write_json(LOG_FILE, logs)
    write_json(FORECAST_FILE, output)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

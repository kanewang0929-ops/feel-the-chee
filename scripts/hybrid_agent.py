#!/usr/bin/env python3
"""Adaptive agent that blends AI-curve and formula-only Chee candidates.

The agent never invents numbers outside the two source-model candidate sets.
It decides the source contribution for each final ticket, scores the result after
the draw, and updates bounded source/strategy weights. All valid lottery
combinations remain equally likely in a fair draw.
"""
from __future__ import annotations

import itertools
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAWS_FILE = ROOT / "data/draws.json"
AI_FORECAST_FILE = ROOT / "data/forecast.json"
CHEE_FORECAST_FILE = ROOT / "data/chee-forecast.json"
AI_BACKTEST_FILE = ROOT / "data/ai-backtest.json"
CHEE_BACKTEST_FILE = ROOT / "data/chee-backtest.json"
FORECAST_FILE = ROOT / "data/hybrid-forecast.json"
HISTORY_FILE = ROOT / "data/hybrid-history.json"
LOG_FILE = ROOT / "data/hybrid-learning-log.json"
STATE_FILE = ROOT / "data/hybrid-model-state.json"
BACKTEST_FILE = ROOT / "data/hybrid-backtest.json"

VERSION = "v1.0-adaptive-fusion-agent"
BASELINES = {"front": 5 * 5 / 35, "back": 2 * 2 / 12}
AREA_CONFIG = {"front": (5, 35, 16, 90), "back": (2, 12, 10, 24)}
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


def numbers(value) -> list[int]:
    values = value if isinstance(value, list) else str(value or "").split()
    return [int(number) for number in values]


def formatted(values) -> list[str]:
    return [f"{int(number):02d}" for number in values]


def default_state() -> dict:
    return {
        "version": 1,
        "modelVersion": VERSION,
        "observations": 0,
        "sourceEma": {
            "front": {"ai": 1.0, "chee": 1.0},
            "back": {"ai": 1.0, "chee": 1.0},
        },
        "sourceWeights": {
            "front": {"ai": 0.5, "chee": 0.5},
            "back": {"ai": 0.5, "chee": 0.5},
        },
        "strategyEma": {
            "front": {name: 1.0 for name in STRATEGIES},
            "back": {name: 1.0 for name in STRATEGIES},
        },
        "strategyWeights": {
            "front": {name: 1.0 for name in STRATEGIES},
            "back": {name: 1.0 for name in STRATEGIES},
        },
        "cumulative": {
            "tickets": 0,
            "frontHits": 0,
            "backHits": 0,
            "draws": 0,
        },
        "updatedAt": None,
    }


def ensure_state(payload) -> dict:
    base = default_state()
    if not isinstance(payload, dict):
        return base
    base["observations"] = int(payload.get("observations", 0))
    base["updatedAt"] = payload.get("updatedAt")
    for area in ("front", "back"):
        for source in SOURCE_NAMES:
            try:
                base["sourceEma"][area][source] = float(
                    payload.get("sourceEma", {}).get(area, {}).get(source, 1.0)
                )
                base["sourceWeights"][area][source] = float(
                    payload.get("sourceWeights", {}).get(area, {}).get(source, 0.5)
                )
            except (TypeError, ValueError):
                pass
        for strategy in STRATEGIES:
            try:
                base["strategyEma"][area][strategy] = float(
                    payload.get("strategyEma", {}).get(area, {}).get(strategy, 1.0)
                )
                base["strategyWeights"][area][strategy] = float(
                    payload.get("strategyWeights", {}).get(area, {}).get(strategy, 1.0)
                )
            except (TypeError, ValueError):
                pass
    cumulative = payload.get("cumulative", {})
    for key in base["cumulative"]:
        try:
            base["cumulative"][key] = float(cumulative.get(key, 0))
        except (TypeError, ValueError):
            pass
    return base


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
        if (
            len(front) == 5
            and len(set(front)) == 5
            and all(1 <= number <= 35 for number in front)
            and len(back) == 2
            and len(set(back)) == 2
            and all(1 <= number <= 12 for number in back)
        ):
            output.append(
                {"issue": issue, "date": draw_date, "front": front, "back": back}
            )
    output.sort(key=lambda row: (row["date"], int(row["issue"])))
    return output


def result_support(results: list[dict], area: str, source: str) -> dict[int, float]:
    raw = defaultdict(float)
    for position, result in enumerate(results, start=1):
        rank = int(result.get("rank") or position)
        rank_weight = 1.0 / (1.0 + 0.24 * max(0, rank - 1))
        if source == "ai":
            quality = min(1.1, max(0.7, float(result.get("fit", 80.0)) / 84.0))
        else:
            quality = min(
                1.1, max(0.7, float(result.get("cheeValue", 80.0)) / 86.0)
            )
        for number in numbers(result.get(area, [])):
            raw[number] += rank_weight * quality
    peak = max(raw.values(), default=1.0)
    return {number: score / peak for number, score in raw.items()}


def category(ai_present: bool, chee_present: bool) -> str:
    if ai_present and chee_present:
        return "both"
    return "aiOnly" if ai_present else "cheeOnly"


def candidate_records(
    ai_results: list[dict],
    chee_results: list[dict],
    area: str,
    state: dict,
) -> dict[int, dict]:
    ai_support = result_support(ai_results, area, "ai")
    chee_support = result_support(chee_results, area, "chee")
    source_weights = state["sourceWeights"][area]
    strategy_weights = state["strategyWeights"][area]
    output = {}
    for number in sorted(set(ai_support) | set(chee_support)):
        has_ai = number in ai_support
        has_chee = number in chee_support
        group = category(has_ai, has_chee)
        score = (
            source_weights["ai"] * ai_support.get(number, 0.0)
            + source_weights["chee"] * chee_support.get(number, 0.0)
        )
        if group == "both":
            score += 0.14 * min(
                ai_support.get(number, 0.0), chee_support.get(number, 0.0)
            )
        score *= strategy_weights[group]
        output[number] = {
            "number": number,
            "score": score,
            "category": group,
            "sources": [
                source
                for source, present in (("ai", has_ai), ("chee", has_chee))
                if present
            ],
            "aiSupport": ai_support.get(number, 0.0),
            "cheeSupport": chee_support.get(number, 0.0),
        }
    return output


def gaussian(value: float, mean: float, spread: float) -> float:
    spread = max(0.8, spread)
    return math.exp(-0.5 * ((value - mean) / spread) ** 2)


def source_shape(results: list[dict], area: str) -> tuple[float, float, float, float]:
    values = [sorted(numbers(result.get(area, []))) for result in results]
    values = [row for row in values if row]
    if not values:
        return 0.0, 1.0, 0.0, 1.0
    sums = [sum(row) for row in values]
    spans = [row[-1] - row[0] for row in values]
    return (
        statistics.fmean(sums),
        statistics.pstdev(sums) or max(1.0, statistics.fmean(sums) * 0.12),
        statistics.fmean(spans),
        statistics.pstdev(spans) or max(1.0, statistics.fmean(spans) * 0.15),
    )


def curve_fit(combo: tuple[int, ...], curve: dict | None) -> float:
    if not curve:
        return 0.5
    centers = curve.get("centers", [])
    sigmas = curve.get("sigmas", [])
    if len(centers) != len(combo):
        return 0.5
    normalized = []
    for index, number in enumerate(combo):
        sigma = float(sigmas[index]) if index < len(sigmas) else 4.0
        normalized.append(abs(number - float(centers[index])) / max(1.0, sigma))
    return math.exp(-0.5 * statistics.fmean(normalized))


def combo_rows(
    records: dict[int, dict],
    area: str,
    ai_results: list[dict],
    chee_results: list[dict],
    curve: dict | None = None,
) -> list[dict]:
    picks, _, pool_limit, keep = AREA_CONFIG[area]
    ranked_numbers = sorted(
        records, key=lambda number: records[number]["score"], reverse=True
    )[:pool_limit]
    shape = source_shape([*ai_results, *chee_results], area)
    rows = []
    for combo in itertools.combinations(sorted(ranked_numbers), picks):
        details = [records[number] for number in combo]
        uses_ai = any("ai" in detail["sources"] for detail in details)
        uses_chee = any("chee" in detail["sources"] for detail in details)
        if not uses_ai or not uses_chee:
            continue
        number_score = statistics.fmean(detail["score"] for detail in details)
        consensus = sum(detail["category"] == "both" for detail in details) / picks
        shape_score = 0.58 * gaussian(sum(combo), shape[0], shape[1]) + 0.42 * gaussian(
            combo[-1] - combo[0], shape[2], shape[3]
        )
        curve_score = curve_fit(combo, curve)
        total = (
            0.60 * number_score
            + 0.22 * curve_score
            + 0.12 * shape_score
            + 0.06 * consensus
        )
        rows.append(
            {
                "numbers": combo,
                "score": total,
                "numberScore": number_score,
                "curveScore": curve_score,
                "shapeScore": shape_score,
                "consensusRatio": consensus,
            }
        )
    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows[:keep]


def mix_for_numbers(values: tuple[int, ...], records: dict[int, dict]) -> dict:
    counter = Counter(records[number]["category"] for number in values)
    return {
        "aiOnly": counter["aiOnly"],
        "cheeOnly": counter["cheeOnly"],
        "both": counter["both"],
    }


def score_to_fit(score: float, best: float, floor: float, rank: int) -> float:
    span = best - floor or 1.0
    relative = max(0.0, min(1.0, (score - floor) / span))
    return round(78.0 + 8.0 * relative - 1.2 * (rank - 1), 1)


def generate_results(ai_payload: dict, chee_payload: dict, state: dict) -> list[dict]:
    ai_results = list(ai_payload.get("results", []))
    chee_results = list(chee_payload.get("results", []))
    if not ai_results or not chee_results:
        raise RuntimeError("Both AI and Chee source results are required.")

    front_records = candidate_records(ai_results, chee_results, "front", state)
    back_records = candidate_records(ai_results, chee_results, "back", state)
    front_rows = combo_rows(
        front_records,
        "front",
        ai_results,
        chee_results,
        ai_payload.get("curveForecast", {}).get("front"),
    )
    back_rows = combo_rows(
        back_records,
        "back",
        ai_results,
        chee_results,
        ai_payload.get("curveForecast", {}).get("back"),
    )
    combined = []
    for front_row in front_rows:
        for back_row in back_rows:
            combined.append(
                {
                    "front": front_row,
                    "back": back_row,
                    "score": 0.80 * front_row["score"] + 0.20 * back_row["score"],
                }
            )
    combined.sort(key=lambda row: row["score"], reverse=True)
    if not combined:
        raise RuntimeError("No valid hybrid combinations could be generated.")

    selected = []
    for row in combined:
        front = set(row["front"]["numbers"])
        back = set(row["back"]["numbers"])
        if any(
            len(front & set(other["front"]["numbers"])) > 3
            or len(back & set(other["back"]["numbers"])) > 1
            for other in selected
        ):
            continue
        selected.append(row)
        if len(selected) == 2:
            break
    if len(selected) < 2:
        selected = combined[:2]

    best = combined[0]["score"]
    floor = combined[min(len(combined) - 1, 120)]["score"]
    labels = ["融合主策", "交叉对冲"]
    output = []
    for index, row in enumerate(selected, start=1):
        front = row["front"]["numbers"]
        back = row["back"]["numbers"]
        front_mix = mix_for_numbers(front, front_records)
        back_mix = mix_for_numbers(back, back_records)
        output.append(
            {
                "rank": index,
                "label": labels[index - 1],
                "front": formatted(front),
                "back": formatted(back),
                "agentScore": score_to_fit(row["score"], best, floor, index),
                "sourceMix": {"front": front_mix, "back": back_mix},
                "numberSources": {
                    "front": {
                        f"{number:02d}": front_records[number]["sources"]
                        for number in front
                    },
                    "back": {
                        f"{number:02d}": back_records[number]["sources"]
                        for number in back
                    },
                },
                "reason": (
                    f"前区来源 AI独有{front_mix['aiOnly']}、风水独有{front_mix['cheeOnly']}、"
                    f"双方共识{front_mix['both']}；后区来源 AI独有{back_mix['aiOnly']}、"
                    f"风水独有{back_mix['cheeOnly']}、双方共识{back_mix['both']}。"
                    "代理按历史来源权重、号码支持强度、AI曲线吻合度和两组间分散度联合选择。"
                ),
            }
        )
    return output


def source_average_hits(results: list[dict], actual: dict, area: str) -> float:
    actual_set = set(numbers(actual[area]))
    values = [
        len(actual_set & set(numbers(result.get(area, [])))) for result in results
    ]
    return statistics.fmean(values) if values else 0.0


def clipped_ratio(value: float, baseline: float) -> float:
    return max(0.25, min(2.5, value / max(0.0001, baseline)))


def normalized_source_weights(ema: dict[str, float]) -> dict[str, float]:
    raw = {name: math.exp(2.2 * (ema[name] - 1.0)) for name in SOURCE_NAMES}
    total = sum(raw.values()) or 1.0
    ai_weight = max(0.25, min(0.75, raw["ai"] / total))
    return {"ai": round(ai_weight, 6), "chee": round(1.0 - ai_weight, 6)}


def normalized_strategy_weights(ema: dict[str, float]) -> dict[str, float]:
    mean = statistics.fmean(ema.values()) or 1.0
    return {
        name: round(max(0.65, min(1.35, ema[name] / mean)), 6)
        for name in STRATEGIES
    }


def category_sets(ai_results: list[dict], chee_results: list[dict], area: str) -> dict:
    ai_numbers = {
        number for result in ai_results for number in numbers(result.get(area, []))
    }
    chee_numbers = {
        number for result in chee_results for number in numbers(result.get(area, []))
    }
    return {
        "both": ai_numbers & chee_numbers,
        "aiOnly": ai_numbers - chee_numbers,
        "cheeOnly": chee_numbers - ai_numbers,
    }


def evaluate_and_update(
    state: dict,
    ai_results: list[dict],
    chee_results: list[dict],
    hybrid_results: list[dict],
    actual: dict,
    alpha: float = 0.045,
) -> dict:
    before = json.loads(json.dumps(state))
    source_performance = {"front": {}, "back": {}}
    strategy_performance = {"front": {}, "back": {}}

    for area in ("front", "back"):
        for source, results in (("ai", ai_results), ("chee", chee_results)):
            average_hits = source_average_hits(results, actual, area)
            ratio = clipped_ratio(average_hits, BASELINES[area])
            old = state["sourceEma"][area][source]
            state["sourceEma"][area][source] = (1 - alpha) * old + alpha * ratio
            source_performance[area][source] = {
                "averageHits": round(average_hits, 4),
                "rewardRatio": round(ratio, 4),
            }
        state["sourceWeights"][area] = normalized_source_weights(
            state["sourceEma"][area]
        )

        actual_set = set(numbers(actual[area]))
        groups = category_sets(ai_results, chee_results, area)
        winners = 5 if area == "front" else 2
        population = 35 if area == "front" else 12
        number_baseline = winners / population
        for strategy, candidates in groups.items():
            if candidates:
                hit_rate = len(actual_set & candidates) / len(candidates)
                ratio = clipped_ratio(hit_rate, number_baseline)
                old = state["strategyEma"][area][strategy]
                state["strategyEma"][area][strategy] = (
                    (1 - alpha) * old + alpha * ratio
                )
                strategy_performance[area][strategy] = {
                    "candidateCount": len(candidates),
                    "hitCount": len(actual_set & candidates),
                    "rewardRatio": round(ratio, 4),
                }
        state["strategyWeights"][area] = normalized_strategy_weights(
            state["strategyEma"][area]
        )

    actual_front = set(numbers(actual["front"]))
    actual_back = set(numbers(actual["back"]))
    ticket_rows = []
    for result in hybrid_results:
        front_hits = sorted(actual_front & set(numbers(result["front"])))
        back_hits = sorted(actual_back & set(numbers(result["back"])))
        ticket_rows.append(
            {
                "rank": result.get("rank"),
                "label": result.get("label"),
                "front": result["front"],
                "back": result["back"],
                "frontHits": formatted(front_hits),
                "backHits": formatted(back_hits),
                "frontHitCount": len(front_hits),
                "backHitCount": len(back_hits),
                "sourceMix": result.get("sourceMix", {}),
            }
        )

    state["observations"] += 1
    state["cumulative"]["draws"] += 1
    state["cumulative"]["tickets"] += len(ticket_rows)
    state["cumulative"]["frontHits"] += sum(row["frontHitCount"] for row in ticket_rows)
    state["cumulative"]["backHits"] += sum(row["backHitCount"] for row in ticket_rows)
    state["updatedAt"] = datetime.now(timezone.utc).isoformat()

    return {
        "actual": {
            "front": formatted(actual_front),
            "back": formatted(actual_back),
        },
        "results": ticket_rows,
        "summary": {
            "averageFrontHits": round(
                statistics.fmean(row["frontHitCount"] for row in ticket_rows), 4
            ),
            "averageBackHits": round(
                statistics.fmean(row["backHitCount"] for row in ticket_rows), 4
            ),
            "bestTotalHits": max(
                row["frontHitCount"] + row["backHitCount"] for row in ticket_rows
            ),
        },
        "sourcePerformance": source_performance,
        "strategyPerformance": strategy_performance,
        "weightsBefore": {
            "source": before["sourceWeights"],
            "strategy": before["strategyWeights"],
        },
        "weightsAfter": {
            "source": state["sourceWeights"],
            "strategy": state["strategyWeights"],
        },
        "learningRule": (
            "Source and source-category rewards use bounded exponential moving "
            "averages. Weights cannot collapse below 25% for either source."
        ),
    }


def audit_summary(ai_backtest: dict, chee_backtest: dict, hybrid_backtest: dict) -> dict:
    ai = ai_backtest.get("summary", {})
    chee = chee_backtest.get("summary", {})
    hybrid = hybrid_backtest.get("summary", {})
    return {
        "ai": {
            "draws": ai.get("drawsEvaluated"),
            "averageFrontHits": ai.get("observed", {}).get(
                "averageFrontHitsPerTicket"
            ),
            "averageBackHits": ai.get("observed", {}).get(
                "averageBackHitsPerTicket"
            ),
        },
        "chee": {
            "draws": chee.get("drawsEvaluated"),
            "averageFrontHits": chee.get("observed", {}).get(
                "averageFrontHitsPerTicket"
            ),
            "averageBackHits": chee.get("observed", {}).get(
                "averageBackHitsPerTicket"
            ),
        },
        "hybrid": {
            "draws": hybrid.get("drawsEvaluated"),
            "averageFrontHits": hybrid.get("observed", {}).get(
                "averageFrontHitsPerTicket"
            ),
            "averageBackHits": hybrid.get("observed", {}).get(
                "averageBackHitsPerTicket"
            ),
        },
    }


def archive_previous(previous: dict, evaluation: dict | None) -> None:
    if not previous.get("targetIssue"):
        return
    history = read_json(HISTORY_FILE, [])
    if not isinstance(history, list):
        history = []
    issue = str(previous["targetIssue"])
    if any(str(row.get("targetIssue")) == issue for row in history):
        return
    snapshot = dict(previous)
    snapshot["evaluation"] = evaluation
    history.append(snapshot)
    history.sort(key=lambda row: int(row.get("targetIssue", 0)))
    write_json(HISTORY_FILE, history[-500:])


def main() -> None:
    ai_payload = read_json(AI_FORECAST_FILE, {})
    chee_payload = read_json(CHEE_FORECAST_FILE, {})
    if not ai_payload.get("results") or not chee_payload.get("results"):
        raise RuntimeError("AI and Chee forecasts must exist before the hybrid agent.")
    if str(ai_payload.get("targetIssue")) != str(chee_payload.get("targetIssue")):
        raise RuntimeError("AI and Chee forecasts target different issues.")

    backtest = read_json(BACKTEST_FILE, {})
    state_payload = read_json(STATE_FILE, {})
    if not state_payload and isinstance(backtest.get("finalState"), dict):
        state_payload = backtest["finalState"]
    state = ensure_state(state_payload)

    draws = load_draws()
    previous = read_json(FORECAST_FILE, {})
    logs = read_json(LOG_FILE, [])
    if not isinstance(logs, list):
        logs = []

    evaluation = None
    previous_issue = str(previous.get("targetIssue") or "")
    actual = next((draw for draw in draws if draw["issue"] == previous_issue), None)
    already_logged = any(str(row.get("issue")) == previous_issue for row in logs)
    if actual and previous.get("results") and not already_logged:
        source_inputs = previous.get("sourceInputs", {})
        evaluation = evaluate_and_update(
            state,
            source_inputs.get("ai", {}).get("results", []),
            source_inputs.get("chee", {}).get("results", []),
            previous["results"],
            actual,
        )
        evaluation.update(
            {
                "issue": previous_issue,
                "date": actual["date"],
                "evaluatedAt": datetime.now(timezone.utc).isoformat(),
                "modelVersion": previous.get("modelVersion"),
            }
        )
        logs.append(evaluation)
    elif already_logged:
        evaluation = next(
            row for row in logs if str(row.get("issue")) == previous_issue
        )

    archive_previous(previous, evaluation)
    results = generate_results(ai_payload, chee_payload, state)
    now = datetime.now(timezone.utc).isoformat()
    output = {
        "modelVersion": VERSION,
        "modelFamily": "adaptive-source-fusion-agent",
        "generatedAt": now,
        "targetIssue": str(ai_payload["targetIssue"]),
        "targetDate": ai_payload.get("targetDate"),
        "sourceModels": {
            "ai": ai_payload.get("modelVersion"),
            "chee": chee_payload.get("modelVersion"),
        },
        "sourceWeights": state["sourceWeights"],
        "strategyWeights": state["strategyWeights"],
        "observations": state["observations"],
        "lastEvaluation": evaluation,
        "sourceAuditSummary": audit_summary(
            read_json(AI_BACKTEST_FILE, {}),
            read_json(CHEE_BACKTEST_FILE, {}),
            backtest,
        ),
        "sourceInputs": {
            "ai": {
                "modelVersion": ai_payload.get("modelVersion"),
                "results": ai_payload.get("results", []),
            },
            "chee": {
                "modelVersion": chee_payload.get("modelVersion"),
                "results": chee_payload.get("results", []),
            },
        },
        "results": results,
        "storage": {
            "forecast": "data/hybrid-forecast.json",
            "history": "data/hybrid-history.json",
            "learningLog": "data/hybrid-learning-log.json",
            "modelState": "data/hybrid-model-state.json",
            "historicalBacktest": "data/hybrid-backtest.json",
        },
        "note": (
            "The agent only recombines numbers proposed by the AI and Chee models. "
            "Agent score is an internal fusion score, not a winning probability."
        ),
    }
    state["modelVersion"] = VERSION
    state["updatedAt"] = now
    write_json(STATE_FILE, state)
    write_json(LOG_FILE, logs[-500:])
    write_json(FORECAST_FILE, output)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

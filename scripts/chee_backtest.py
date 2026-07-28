#!/usr/bin/env python3
"""Audit formula-only Feel the Chee predictions against every stored draw.

For each historical draw, the formula receives only that draw's issue and date.
The actual numbers are revealed afterward for comparison. No historical result
feeds the prediction and the backtest never changes formula parameters.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import chee_formula as formula

ROOT = Path(__file__).resolve().parents[1]
DRAWS_FILE = ROOT / "data" / "draws.json"
OUTPUT_FILE = ROOT / "data" / "chee-backtest.json"
BACKTEST_VERSION = "v1.1-full-archive"
ELEMENTS = ["木", "火", "土", "金", "水"]


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


def normalize_numbers(value) -> list[int]:
    values = value if isinstance(value, list) else str(value or "").split()
    return [int(number) for number in values]


def load_draws() -> list[dict]:
    payload = read_json(DRAWS_FILE, {})
    rows = payload if isinstance(payload, list) else payload.get("draws", [])
    draws = []
    for row in rows:
        try:
            front = normalize_numbers(row["front"])
            back = normalize_numbers(row["back"])
            issue = str(row["issue"]).strip()
            draw_date = str(row["date"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if (
            issue
            and len(front) == 5
            and len(set(front)) == 5
            and all(1 <= number <= 35 for number in front)
            and len(back) == 2
            and len(set(back)) == 2
            and all(1 <= number <= 12 for number in back)
        ):
            draws.append(
                {
                    "issue": issue,
                    "date": draw_date,
                    "front": sorted(front),
                    "back": sorted(back),
                }
            )
    draws.sort(key=lambda row: (row["date"], int(row["issue"])))
    return draws


def element_counts(numbers) -> dict[str, int]:
    counter = Counter(formula.elem(int(number)) for number in numbers)
    return {name: counter[name] for name in ELEMENTS}


def element_similarity(left, right) -> float:
    left_counts = element_counts(left)
    right_counts = element_counts(right)
    total = max(1, sum(left_counts.values()), sum(right_counts.values()))
    distance = sum(abs(left_counts[name] - right_counts[name]) for name in ELEMENTS)
    return max(0.0, 1.0 - distance / (2 * total))


def formula_signature(calculation: dict) -> tuple:
    """Values that completely determine the current formula's scored output."""
    return (
        calculation["heavenNumber"],
        calculation["earthNumber"],
        calculation["humanNumber"],
        calculation["movingLine"],
        calculation["guaNumber"],
        calculation["primaryDigit"],
        calculation["issueTailDigit"],
        calculation["dateTailDigit"],
        calculation["yinYang"],
        calculation["primaryElement"],
        calculation["supportElement"],
        calculation["balanceElement"],
        calculation["controlElement"],
    )


def score_draw(draw: dict, calculation: dict, predictions: list[dict]) -> dict:
    actual_front = set(draw["front"])
    actual_back = set(draw["back"])
    actual_all = [*draw["front"], *draw["back"]]
    ticket_rows = []

    for ticket in predictions:
        predicted_front = set(ticket["front"])
        predicted_back = set(ticket["back"])
        front_hits = sorted(actual_front & predicted_front)
        back_hits = sorted(actual_back & predicted_back)
        ticket_rows.append(
            {
                "rank": ticket["rank"],
                "label": ticket["label"],
                "front": [f"{number:02d}" for number in ticket["front"]],
                "back": [f"{number:02d}" for number in ticket["back"]],
                "frontHits": [f"{number:02d}" for number in front_hits],
                "backHits": [f"{number:02d}" for number in back_hits],
                "frontHitCount": len(front_hits),
                "backHitCount": len(back_hits),
                "elementSimilarity": round(
                    element_similarity(
                        [*ticket["front"], *ticket["back"]],
                        actual_all,
                    ),
                    4,
                ),
                "cheeValue": ticket["cheeValue"],
            }
        )

    best = max(
        ticket_rows,
        key=lambda row: (
            row["frontHitCount"] + row["backHitCount"],
            row["frontHitCount"],
            row["backHitCount"],
            row["elementSimilarity"],
        ),
    )

    return {
        "issue": draw["issue"],
        "date": draw["date"],
        "actual": {
            "front": [f"{number:02d}" for number in draw["front"]],
            "back": [f"{number:02d}" for number in draw["back"]],
        },
        "formulaContext": {
            "heavenNumber": calculation["heavenNumber"],
            "earthNumber": calculation["earthNumber"],
            "humanNumber": calculation["humanNumber"],
            "movingLine": calculation["movingLine"],
            "guaNumber": calculation["guaNumber"],
            "yinYang": calculation["yinYang"],
            "primaryElement": calculation["primaryElement"],
            "supportElement": calculation["supportElement"],
            "balanceElement": calculation["balanceElement"],
        },
        "tickets": ticket_rows,
        "bestTicket": {
            "rank": best["rank"],
            "frontHitCount": best["frontHitCount"],
            "backHitCount": best["backHitCount"],
            "elementSimilarity": best["elementSimilarity"],
        },
    }


def hypergeometric_distribution(
    population: int,
    winners: int,
    picks: int,
) -> dict[str, float]:
    denominator = math.comb(population, picks)
    result = {}
    for hits in range(min(winners, picks) + 1):
        probability = (
            math.comb(winners, hits)
            * math.comb(population - winners, picks - hits)
            / denominator
        )
        result[str(hits)] = probability
    return result


def aggregate(draw_results: list[dict]) -> dict:
    tickets = [ticket for draw in draw_results for ticket in draw["tickets"]]
    draw_count = len(draw_results)
    ticket_count = len(tickets)

    front_distribution = Counter(ticket["frontHitCount"] for ticket in tickets)
    back_distribution = Counter(ticket["backHitCount"] for ticket in tickets)
    pattern_distribution = Counter(
        f'{ticket["frontHitCount"]}+{ticket["backHitCount"]}'
        for ticket in tickets
    )

    average_front = (
        sum(ticket["frontHitCount"] for ticket in tickets) / ticket_count
        if ticket_count
        else 0.0
    )
    average_back = (
        sum(ticket["backHitCount"] for ticket in tickets) / ticket_count
        if ticket_count
        else 0.0
    )
    average_similarity = (
        sum(ticket["elementSimilarity"] for ticket in tickets) / ticket_count
        if ticket_count
        else 0.0
    )

    front_baseline = 5 * 5 / 35
    back_baseline = 2 * 2 / 12
    front_probabilities = hypergeometric_distribution(35, 5, 5)
    back_probabilities = hypergeometric_distribution(12, 2, 2)

    best_front_distribution = Counter(
        draw["bestTicket"]["frontHitCount"] for draw in draw_results
    )
    best_back_distribution = Counter(
        draw["bestTicket"]["backHitCount"] for draw in draw_results
    )

    group_template = lambda: {
        "draws": 0,
        "tickets": 0,
        "frontHits": 0,
        "backHits": 0,
        "elementSimilarity": 0.0,
    }
    by_year = defaultdict(group_template)
    by_element = defaultdict(group_template)

    for draw in draw_results:
        for group in (
            by_year[draw["date"][:4]],
            by_element[draw["formulaContext"]["primaryElement"]],
        ):
            group["draws"] += 1
            group["tickets"] += len(draw["tickets"])
            group["frontHits"] += sum(
                ticket["frontHitCount"] for ticket in draw["tickets"]
            )
            group["backHits"] += sum(
                ticket["backHitCount"] for ticket in draw["tickets"]
            )
            group["elementSimilarity"] += sum(
                ticket["elementSimilarity"] for ticket in draw["tickets"]
            )

    def finish_groups(groups):
        output = {}
        for key, row in groups.items():
            count = max(1, row["tickets"])
            output[key] = {
                "draws": row["draws"],
                "tickets": row["tickets"],
                "averageFrontHits": round(row["frontHits"] / count, 4),
                "averageBackHits": round(row["backHits"] / count, 4),
                "averageElementSimilarity": round(
                    row["elementSimilarity"] / count,
                    4,
                ),
            }
        return output

    ranked_examples = sorted(
        draw_results,
        key=lambda row: (
            row["bestTicket"]["frontHitCount"]
            + row["bestTicket"]["backHitCount"],
            row["bestTicket"]["frontHitCount"],
            row["bestTicket"]["backHitCount"],
            row["bestTicket"]["elementSimilarity"],
        ),
        reverse=True,
    )

    return {
        "drawsEvaluated": draw_count,
        "ticketsEvaluated": ticket_count,
        "dateRange": {
            "earliest": draw_results[0]["date"] if draw_results else None,
            "latest": draw_results[-1]["date"] if draw_results else None,
        },
        "observed": {
            "averageFrontHitsPerTicket": round(average_front, 6),
            "averageBackHitsPerTicket": round(average_back, 6),
            "averageTotalHitsPerTicket": round(average_front + average_back, 6),
            "averageElementSimilarity": round(average_similarity, 6),
            "ticketsWithAnyFrontHit": sum(
                ticket["frontHitCount"] >= 1 for ticket in tickets
            ),
            "ticketsWithAnyBackHit": sum(
                ticket["backHitCount"] >= 1 for ticket in tickets
            ),
            "ticketsWithFrontAndBackHit": sum(
                ticket["frontHitCount"] >= 1
                and ticket["backHitCount"] >= 1
                for ticket in tickets
            ),
            "frontHitDistribution": {
                str(hits): front_distribution[hits] for hits in range(6)
            },
            "backHitDistribution": {
                str(hits): back_distribution[hits] for hits in range(3)
            },
            "hitPatternDistribution": dict(sorted(pattern_distribution.items())),
            "bestOfTwoFrontDistribution": {
                str(hits): best_front_distribution[hits] for hits in range(6)
            },
            "bestOfTwoBackDistribution": {
                str(hits): best_back_distribution[hits] for hits in range(3)
            },
            "exactFivePlusTwo": pattern_distribution["5+2"],
        },
        "theoreticalFixedTicketBaseline": {
            "averageFrontHitsPerTicket": round(front_baseline, 6),
            "averageBackHitsPerTicket": round(back_baseline, 6),
            "averageTotalHitsPerTicket": round(
                front_baseline + back_baseline,
                6,
            ),
            "frontHitProbabilities": {
                key: round(value, 10)
                for key, value in front_probabilities.items()
            },
            "backHitProbabilities": {
                key: round(value, 10)
                for key, value in back_probabilities.items()
            },
            "expectedFrontHitCounts": {
                key: round(value * ticket_count, 3)
                for key, value in front_probabilities.items()
            },
            "expectedBackHitCounts": {
                key: round(value * ticket_count, 3)
                for key, value in back_probabilities.items()
            },
            "note": (
                "Exact fixed-ticket expectation under a fair draw. It is a "
                "benchmark, not a promise of independence in every operational "
                "detail."
            ),
        },
        "comparison": {
            "frontMeanDifference": round(average_front - front_baseline, 6),
            "backMeanDifference": round(average_back - back_baseline, 6),
            "totalMeanDifference": round(
                average_front + average_back - front_baseline - back_baseline,
                6,
            ),
            "frontMeanRatio": round(
                average_front / front_baseline if front_baseline else 0,
                6,
            ),
            "backMeanRatio": round(
                average_back / back_baseline if back_baseline else 0,
                6,
            ),
        },
        "byYear": finish_groups(by_year),
        "byPrimaryElement": finish_groups(by_element),
        "bestExamples": ranked_examples[:20],
        "recentExamples": draw_results[-20:][::-1],
    }


def main() -> None:
    draws = load_draws()
    if not draws:
        raise RuntimeError("No valid draw records found.")

    previous = read_json(OUTPUT_FILE, {})
    existing_rows = previous.get("drawResults", [])
    if not isinstance(existing_rows, list):
        existing_rows = []
    existing_by_issue = {
        str(row.get("issue")): row
        for row in existing_rows
        if row.get("issue")
        and previous.get("formulaVersion") == formula.FORMULA
    }

    calculation_cache: dict[tuple, list[dict]] = {}
    rows = []
    cache_hits = 0

    for position, draw in enumerate(draws, start=1):
        existing = existing_by_issue.get(draw["issue"])
        if existing:
            rows.append(existing)
            continue

        calculation = formula.context(draw["issue"], draw["date"])
        signature = formula_signature(calculation)
        if signature in calculation_cache:
            predictions = calculation_cache[signature]
            cache_hits += 1
        else:
            _, predictions = formula.calculate(draw["issue"], draw["date"])
            calculation_cache[signature] = predictions

        rows.append(score_draw(draw, calculation, predictions))
        if position % 100 == 0 or position == len(draws):
            print(
                f"Backtested {position}/{len(draws)} draws "
                f"({len(calculation_cache)} unique formula contexts)"
            )

    rows.sort(key=lambda row: (row["date"], int(row["issue"])))
    summary = aggregate(rows)
    payload = {
        "backtestVersion": BACKTEST_VERSION,
        "formulaVersion": formula.FORMULA,
        "modelVersion": formula.VERSION,
        "formulaOnly": True,
        "historyUsedForPrediction": False,
        "learningEnabled": False,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "drawResults": rows,
        "performance": {
            "uniqueFormulaContexts": len(calculation_cache),
            "cacheHits": cache_hits,
            "frontCandidatePool": formula.FRONT_POOL_SIZE,
            "backCandidatePool": formula.BACK_POOL_SIZE,
        },
        "methodology": {
            "predictionInputs": ["target issue", "target draw date"],
            "actualResultUsage": "comparison only after prediction",
            "formula": (
                "The same He Tu / Luo Shu date-and-issue calculation used by "
                "the live formula-only Feel the Chee generator."
            ),
            "selection": (
                f"The live formula ranks a {formula.FRONT_POOL_SIZE}-number "
                f"front shortlist and a {formula.BACK_POOL_SIZE}-number back "
                "shortlist, then scores every valid combination within those "
                "formula-only pools."
            ),
        },
        "warning": (
            "Historical alignment does not make a fair random draw predictable. "
            "All valid combinations retain the same theoretical probability."
        ),
    }
    write_json(OUTPUT_FILE, payload)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

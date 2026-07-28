#!/usr/bin/env python3
"""Backtest the formula-only Feel the Chee calculation against every stored draw.

The formula receives only the historical draw's issue and date. Actual numbers are
used after prediction solely for scoring. No historical result is fed into the
formula and no parameter is learned from the backtest.
"""
from __future__ import annotations

import itertools
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import chee_formula as formula

ROOT = Path(__file__).resolve().parents[1]
DRAWS_FILE = ROOT / "data" / "draws.json"
OUTPUT_FILE = ROOT / "data" / "chee-backtest.json"
BACKTEST_VERSION = "v1.0-full-archive"
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


def make_combo_table(max_number: int, pick: int) -> dict:
    combos = np.asarray(
        list(itertools.combinations(range(1, max_number + 1), pick)),
        dtype=np.int16,
    )
    element_index = {name: index for index, name in enumerate(ELEMENTS)}
    counts = np.zeros((len(combos), len(ELEMENTS)), dtype=np.int8)
    for column in range(pick):
        mapped = np.asarray(
            [element_index[formula.elem(int(number))] for number in combos[:, column]],
            dtype=np.int8,
        )
        for index in range(len(ELEMENTS)):
            counts[:, index] += mapped == index

    sums = combos.sum(axis=1)
    sum_roots = np.where(sums % 9 == 0, 9, sums % 9).astype(np.int8)
    odd_counts = (combos % 2).sum(axis=1).astype(np.int8)
    spans = (combos[:, -1] - combos[:, 0]) / max_number

    root_masks = np.zeros(len(combos), dtype=np.int16)
    for column in range(pick):
        roots = np.where(combos[:, column] % 9 == 0, 9, combos[:, column] % 9)
        root_masks |= (1 << (roots - 1)).astype(np.int16)

    return {
        "maxNumber": max_number,
        "pick": pick,
        "combos": combos,
        "elementCounts": counts,
        "sumRoots": sum_roots,
        "oddCounts": odd_counts,
        "spans": spans,
        "rootMasks": root_masks,
    }


def circular_distance_vector(values: np.ndarray, target: int) -> np.ndarray:
    difference = np.abs(values.astype(np.int16) - int(target))
    return np.minimum(difference, 9 - difference)


def score_combo_table(table: dict, context: dict, variant: int) -> np.ndarray:
    max_number = table["maxNumber"]
    pick = table["pick"]
    combos = table["combos"]

    number_scores = np.zeros(max_number + 1, dtype=np.float64)
    for number in range(1, max_number + 1):
        number_scores[number] = formula.nscore(number, context, variant)
    number_component = number_scores[combos].mean(axis=1)

    target_pattern = formula.pattern(context, pick, variant)
    target_vector = np.asarray(
        [target_pattern[name] for name in ELEMENTS],
        dtype=np.float64,
    )
    balance = np.maximum(
        0.0,
        1.0
        - np.abs(table["elementCounts"] - target_vector).sum(axis=1) / (2 * pick),
    )

    gua_distance = circular_distance_vector(table["sumRoots"], context["guaNumber"])
    gua_match = np.where(
        table["sumRoots"] == context["guaNumber"],
        1.0,
        np.maximum(0.0, 1.0 - gua_distance / 4.5),
    )

    desired_odd = min(pick, 3 if context["yinYang"] == "阳" else 2)
    odd_match = np.exp(
        -np.abs(table["oddCounts"].astype(np.float64) - desired_odd) / max(1, pick)
    )

    context_mask = 0
    for root_value in {
        context["heavenNumber"],
        context["earthNumber"],
        context["humanNumber"],
        context["guaNumber"],
    }:
        context_mask |= 1 << (int(root_value) - 1)
    coverage = np.fromiter(
        (
            (int(mask) & context_mask).bit_count() / 4
            for mask in table["rootMasks"]
        ),
        dtype=np.float64,
        count=len(table["rootMasks"]),
    )

    target_span = 0.64 if pick == 5 else 0.48
    spacing = np.exp(-np.abs(table["spans"] - target_span) / 0.30)

    return (
        0.48 * number_component
        + 0.24 * balance
        + 0.10 * gua_match
        + 0.07 * odd_match
        + 0.06 * coverage
        + 0.05 * spacing
    )


def top_indices(scores: np.ndarray, count: int) -> np.ndarray:
    count = min(count, len(scores))
    if count == len(scores):
        indices = np.arange(len(scores))
    else:
        indices = np.argpartition(scores, -count)[-count:]
    return indices[np.argsort(scores[indices])[::-1]]


def select_candidate(
    front_table: dict,
    back_table: dict,
    context: dict,
    variant: int,
    old: dict | None,
) -> dict:
    front_scores = score_combo_table(front_table, context, variant)
    back_scores = score_combo_table(back_table, context, variant)
    front_indices = top_indices(front_scores, 800)
    back_indices = top_indices(back_scores, 50)

    old_front = set(old["front"]) if old else set()
    old_back = set(old["back"]) if old else set()

    for front_index in front_indices:
        front = tuple(int(number) for number in front_table["combos"][front_index])
        if old and len(set(front) & old_front) > 2:
            continue
        for back_index in back_indices:
            back = tuple(int(number) for number in back_table["combos"][back_index])
            if old and len(set(back) & old_back) > 1:
                continue
            return {
                "front": front,
                "back": back,
                "raw": float(
                    0.79 * front_scores[front_index]
                    + 0.21 * back_scores[back_index]
                ),
                "variant": variant,
            }

    front_index = int(front_indices[0])
    back_index = int(back_indices[0])
    return {
        "front": tuple(
            int(number) for number in front_table["combos"][front_index]
        ),
        "back": tuple(
            int(number) for number in back_table["combos"][back_index]
        ),
        "raw": float(
            0.79 * front_scores[front_index] + 0.21 * back_scores[back_index]
        ),
        "variant": variant,
    }


def generate_formula_results(
    issue: str,
    draw_date: str,
    front_table: dict,
    back_table: dict,
) -> tuple[dict, list[dict]]:
    context = formula.context(issue, draw_date)
    first = select_candidate(front_table, back_table, context, 1, None)
    second = select_candidate(front_table, back_table, context, 2, first)
    labels = ["五行主衡", "生化对冲"]
    rows = []
    best = max(first["raw"], second["raw"])
    worst = min(first["raw"], second["raw"])
    span = best - worst or 1.0

    for index, candidate in enumerate([first, second]):
        chee_value = round(
            80 + (candidate["raw"] - worst) / span * 6 - index * 0.4,
            1,
        )
        rows.append(
            {
                "rank": index + 1,
                "label": labels[index],
                "front": list(candidate["front"]),
                "back": list(candidate["back"]),
                "cheeValue": chee_value,
            }
        )
    return context, rows


def score_draw(draw: dict, context: dict, predictions: list[dict]) -> dict:
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
            "heavenNumber": context["heavenNumber"],
            "earthNumber": context["earthNumber"],
            "humanNumber": context["humanNumber"],
            "movingLine": context["movingLine"],
            "guaNumber": context["guaNumber"],
            "yinYang": context["yinYang"],
            "primaryElement": context["primaryElement"],
            "supportElement": context["supportElement"],
            "balanceElement": context["balanceElement"],
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
        if picks - hits > population - winners:
            probability = 0.0
        else:
            probability = (
                math.comb(winners, hits)
                * math.comb(population - winners, picks - hits)
                / denominator
            )
        result[str(hits)] = probability
    return result


def aggregate(draw_results: list[dict]) -> dict:
    ticket_rows = [
        ticket
        for draw in draw_results
        for ticket in draw["tickets"]
    ]
    draw_count = len(draw_results)
    ticket_count = len(ticket_rows)

    front_distribution = Counter(
        ticket["frontHitCount"] for ticket in ticket_rows
    )
    back_distribution = Counter(
        ticket["backHitCount"] for ticket in ticket_rows
    )
    pattern_distribution = Counter(
        f'{ticket["frontHitCount"]}+{ticket["backHitCount"]}'
        for ticket in ticket_rows
    )

    average_front = (
        sum(ticket["frontHitCount"] for ticket in ticket_rows) / ticket_count
        if ticket_count
        else 0.0
    )
    average_back = (
        sum(ticket["backHitCount"] for ticket in ticket_rows) / ticket_count
        if ticket_count
        else 0.0
    )
    average_similarity = (
        sum(ticket["elementSimilarity"] for ticket in ticket_rows) / ticket_count
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

    by_year_accumulator = defaultdict(
        lambda: {
            "draws": 0,
            "tickets": 0,
            "frontHits": 0,
            "backHits": 0,
            "elementSimilarity": 0.0,
        }
    )
    by_element_accumulator = defaultdict(
        lambda: {
            "draws": 0,
            "tickets": 0,
            "frontHits": 0,
            "backHits": 0,
            "elementSimilarity": 0.0,
        }
    )

    for draw in draw_results:
        year = draw["date"][:4]
        primary = draw["formulaContext"]["primaryElement"]
        for accumulator in [by_year_accumulator[year], by_element_accumulator[primary]]:
            accumulator["draws"] += 1
            accumulator["tickets"] += len(draw["tickets"])
            accumulator["frontHits"] += sum(
                ticket["frontHitCount"] for ticket in draw["tickets"]
            )
            accumulator["backHits"] += sum(
                ticket["backHitCount"] for ticket in draw["tickets"]
            )
            accumulator["elementSimilarity"] += sum(
                ticket["elementSimilarity"] for ticket in draw["tickets"]
            )

    def finish_groups(groups):
        output = {}
        for key, row in groups.items():
            tickets = max(1, row["tickets"])
            output[key] = {
                "draws": row["draws"],
                "tickets": row["tickets"],
                "averageFrontHits": round(row["frontHits"] / tickets, 4),
                "averageBackHits": round(row["backHits"] / tickets, 4),
                "averageElementSimilarity": round(
                    row["elementSimilarity"] / tickets,
                    4,
                ),
            }
        return output

    sorted_examples = sorted(
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
                ticket["frontHitCount"] >= 1 for ticket in ticket_rows
            ),
            "ticketsWithAnyBackHit": sum(
                ticket["backHitCount"] >= 1 for ticket in ticket_rows
            ),
            "ticketsWithFrontAndBackHit": sum(
                ticket["frontHitCount"] >= 1
                and ticket["backHitCount"] >= 1
                for ticket in ticket_rows
            ),
            "frontHitDistribution": {
                str(hits): front_distribution[hits] for hits in range(6)
            },
            "backHitDistribution": {
                str(hits): back_distribution[hits] for hits in range(3)
            },
            "hitPatternDistribution": dict(
                sorted(pattern_distribution.items())
            ),
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
                "This is the exact expectation for any fixed five-front/two-back "
                "ticket under a fair draw. It is a benchmark, not a claim that "
                "historical draws are independent in every operational detail."
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
        "byYear": finish_groups(by_year_accumulator),
        "byPrimaryElement": finish_groups(by_element_accumulator),
        "bestExamples": sorted_examples[:20],
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
    }

    front_table = make_combo_table(35, 5)
    back_table = make_combo_table(12, 2)

    rows = []
    for position, draw in enumerate(draws, start=1):
        existing = existing_by_issue.get(draw["issue"])
        if existing:
            rows.append(existing)
            continue
        context, predictions = generate_formula_results(
            draw["issue"],
            draw["date"],
            front_table,
            back_table,
        )
        rows.append(score_draw(draw, context, predictions))
        if position % 100 == 0 or position == len(draws):
            print(f"Backtested {position}/{len(draws)} draws")

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
        "methodology": {
            "predictionInputs": ["target issue", "target draw date"],
            "actualResultUsage": "comparison only after prediction",
            "formula": (
                "The same He Tu / Luo Shu date-and-issue scoring functions used "
                "by the live formula-only Feel the Chee generator."
            ),
            "selection": (
                "Exact enumeration of all valid front and back combinations, "
                "then the same two-ticket diversity rule used by the live model."
            ),
        },
        "warning": (
            "A historical backtest can describe past alignment but cannot make "
            "a fair random draw predictable. All valid combinations retain the "
            "same theoretical probability."
        ),
    }
    write_json(OUTPUT_FILE, payload)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

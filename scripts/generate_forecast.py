#!/usr/bin/env python3
"""Generate three diversified DLT candidate combinations from the full draw archive.

This is a pattern-fitting experiment, not a claim that lottery outcomes are predictable.
The engine calibrates feature weights with walk-forward tests and then scores number
combinations using long-run priors, recent windows, gaps, transitions, pair structure,
and historical shape constraints.
"""

from __future__ import annotations

import itertools
import json
import math
import statistics
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SOURCE_URL = "https://raw.githubusercontent.com/yangxb919/lottery-data/main/data/dlt.json"
OUTPUT = Path("data/forecast.json")
MODEL_VERSION = "v2.0-full-history"

WEIGHT_CONFIGS = [
    {
        "name": "balanced",
        "long": 0.08,
        "r10": 0.12,
        "r30": 0.18,
        "r100": 0.18,
        "r300": 0.08,
        "gap": 0.12,
        "momentum": 0.10,
        "transition": 0.14,
    },
    {
        "name": "recent-cycle",
        "long": 0.05,
        "r10": 0.17,
        "r30": 0.20,
        "r100": 0.15,
        "r300": 0.05,
        "gap": 0.16,
        "momentum": 0.12,
        "transition": 0.10,
    },
    {
        "name": "transition-led",
        "long": 0.06,
        "r10": 0.10,
        "r30": 0.14,
        "r100": 0.16,
        "r300": 0.08,
        "gap": 0.11,
        "momentum": 0.10,
        "transition": 0.25,
    },
    {
        "name": "stable-history",
        "long": 0.16,
        "r10": 0.07,
        "r30": 0.12,
        "r100": 0.20,
        "r300": 0.14,
        "gap": 0.11,
        "momentum": 0.08,
        "transition": 0.12,
    },
    {
        "name": "gap-reversion",
        "long": 0.07,
        "r10": 0.09,
        "r30": 0.14,
        "r100": 0.15,
        "r300": 0.08,
        "gap": 0.25,
        "momentum": 0.08,
        "transition": 0.14,
    },
]


def fetch_json(url: str):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "feel-the-chee-history-forecast/2.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def valid_record(item: dict) -> bool:
    try:
        front = [int(x) for x in item["front"]]
        back = [int(x) for x in item["back"]]
        date.fromisoformat(item["date"])
        return (
            len(front) == 5
            and len(set(front)) == 5
            and all(1 <= n <= 35 for n in front)
            and len(back) == 2
            and len(set(back)) == 2
            and all(1 <= n <= 12 for n in back)
        )
    except (KeyError, TypeError, ValueError):
        return False


def normalize(values: dict[int, float]) -> dict[int, float]:
    numbers = list(values)
    raw = [values[n] for n in numbers]
    mean = statistics.fmean(raw)
    std = statistics.pstdev(raw) or 1.0
    return {n: (values[n] - mean) / std for n in numbers}


def minmax(values: dict) -> dict:
    low = min(values.values())
    high = max(values.values())
    span = high - low or 1.0
    return {key: (value - low) / span for key, value in values.items()}


def rate(records: list[set[int]], number: int, window: int | None = None) -> float:
    sample = records[-window:] if window else records
    return sum(number in draw for draw in sample) / max(1, len(sample))


def current_gap(records: list[set[int]], number: int) -> int:
    for gap, draw in enumerate(reversed(records)):
        if number in draw:
            return gap
    return len(records)


def mean_gap(records: list[set[int]], number: int) -> float:
    positions = [i for i, draw in enumerate(records) if number in draw]
    if len(positions) < 2:
        return max(1.0, len(records) / 3)
    return statistics.fmean(b - a for a, b in zip(positions, positions[1:]))


def transition_feature(records: list[set[int]], max_number: int) -> dict[int, float]:
    latest = records[-1]
    totals = Counter()
    hits = {n: Counter() for n in latest}
    for current, nxt in zip(records, records[1:]):
        overlap = latest.intersection(current)
        for source in overlap:
            totals[source] += 1
            for candidate in nxt:
                hits[source][candidate] += 1
    values = {}
    for candidate in range(1, max_number + 1):
        probabilities = [
            hits[source][candidate] / totals[source]
            for source in latest
            if totals[source]
        ]
        values[candidate] = statistics.fmean(probabilities) if probabilities else 0.0
    return values


def feature_table(records: list[set[int]], max_number: int) -> dict[str, dict[int, float]]:
    long_rate = {n: rate(records, n) for n in range(1, max_number + 1)}
    r10 = {n: rate(records, n, 10) for n in range(1, max_number + 1)}
    r30 = {n: rate(records, n, 30) for n in range(1, max_number + 1)}
    r100 = {n: rate(records, n, 100) for n in range(1, max_number + 1)}
    r300 = {n: rate(records, n, 300) for n in range(1, max_number + 1)}
    gap = {
        n: current_gap(records, n) / max(1.0, mean_gap(records, n))
        for n in range(1, max_number + 1)
    }
    momentum = {n: r30[n] - r300[n] for n in range(1, max_number + 1)}
    transition = transition_feature(records, max_number)
    return {
        "long": normalize(long_rate),
        "r10": normalize(r10),
        "r30": normalize(r30),
        "r100": normalize(r100),
        "r300": normalize(r300),
        "gap": normalize(gap),
        "momentum": normalize(momentum),
        "transition": normalize(transition),
    }


def score_numbers(
    records: list[set[int]],
    max_number: int,
    weights: dict[str, float],
) -> tuple[dict[int, float], dict[str, dict[int, float]]]:
    features = feature_table(records, max_number)
    scores = {
        n: sum(weights[key] * features[key][n] for key in features)
        for n in range(1, max_number + 1)
    }
    return scores, features


def walk_forward_select(
    records: list[set[int]],
    max_number: int,
    main_pick: int,
    wider_pick: int,
) -> tuple[dict[str, float], dict]:
    start = max(450, len(records) - 180)
    test_indices = list(range(start, len(records), 2))
    evaluations = []
    for config in WEIGHT_CONFIGS:
        main_hits = 0
        wider_hits = 0
        total_actual = 0
        for index in test_indices:
            history = records[:index]
            actual = records[index]
            scores, _ = score_numbers(history, max_number, config)
            ranked = sorted(scores, key=scores.get, reverse=True)
            main_hits += len(actual.intersection(ranked[:main_pick]))
            wider_hits += len(actual.intersection(ranked[:wider_pick]))
            total_actual += len(actual)
        average_main = main_hits / max(1, len(test_indices))
        average_wider = wider_hits / max(1, len(test_indices))
        objective = average_main * 3 + average_wider
        evaluations.append(
            {
                "config": config,
                "objective": objective,
                "averageMainHits": average_main,
                "averageWiderHits": average_wider,
                "tests": len(test_indices),
            }
        )
    winner = max(evaluations, key=lambda row: row["objective"])
    return winner["config"], {
        "tests": winner["tests"],
        "averageMainHits": round(winner["averageMainHits"], 3),
        "averageWiderHits": round(winner["averageWiderHits"], 3),
        "objective": round(winner["objective"], 3),
        "selectedProfile": winner["config"]["name"],
    }


def pair_strength(records: list[set[int]], pool: list[int]) -> dict[tuple[int, int], float]:
    sample = records[-1200:]
    counts = Counter()
    singles = Counter()
    for draw in sample:
        for number in draw:
            if number in pool:
                singles[number] += 1
        for pair in itertools.combinations(sorted(draw.intersection(pool)), 2):
            counts[pair] += 1
    values = {}
    size = max(1, len(sample))
    for a, b in itertools.combinations(sorted(pool), 2):
        observed = counts[(a, b)] / size
        expected = (singles[a] / size) * (singles[b] / size)
        values[(a, b)] = math.log((observed + 1 / size) / (expected + 1 / size))
    return minmax(values)


def structure_profile(records: list[set[int]]) -> dict:
    sample = records[-1200:]
    sums = [sum(draw) for draw in sample]
    spans = [max(draw) - min(draw) for draw in sample]
    odd_counts = Counter(sum(n % 2 for n in draw) for draw in sample)
    low_counts = Counter(sum(n <= 17 for n in draw) for draw in sample)
    consecutive_counts = Counter(
        sum(b - a == 1 for a, b in zip(sorted(draw), sorted(draw)[1:]))
        for draw in sample
    )
    return {
        "sumMean": statistics.fmean(sums),
        "sumStd": statistics.pstdev(sums) or 1.0,
        "spanMean": statistics.fmean(spans),
        "spanStd": statistics.pstdev(spans) or 1.0,
        "odd": odd_counts,
        "low": low_counts,
        "consecutive": consecutive_counts,
        "total": len(sample),
    }


def gaussian(value: float, mean: float, std: float) -> float:
    return math.exp(-0.5 * ((value - mean) / std) ** 2)


def front_combo_scores(
    records: list[set[int]],
    number_scores: dict[int, float],
) -> list[tuple[tuple[int, ...], float]]:
    pool = sorted(number_scores, key=number_scores.get, reverse=True)[:16]
    number_norm = minmax(number_scores)
    pair_norm = pair_strength(records, pool)
    profile = structure_profile(records)
    scored = []
    for combo in itertools.combinations(sorted(pool), 5):
        number_component = statistics.fmean(number_norm[n] for n in combo)
        pair_component = statistics.fmean(
            pair_norm[tuple(sorted(pair))] for pair in itertools.combinations(combo, 2)
        )
        odd = sum(n % 2 for n in combo)
        low = sum(n <= 17 for n in combo)
        consecutive = sum(b - a == 1 for a, b in zip(combo, combo[1:]))
        frequency_shape = statistics.fmean(
            [
                profile["odd"][odd] / profile["total"],
                profile["low"][low] / profile["total"],
                profile["consecutive"][consecutive] / profile["total"],
            ]
        )
        shape_component = (
            0.35 * gaussian(sum(combo), profile["sumMean"], profile["sumStd"])
            + 0.25 * gaussian(combo[-1] - combo[0], profile["spanMean"], profile["spanStd"])
            + 0.40 * min(1.0, frequency_shape * 8)
        )
        total = 0.57 * number_component + 0.18 * pair_component + 0.25 * shape_component
        scored.append((combo, total))
    return sorted(scored, key=lambda row: row[1], reverse=True)


def back_pair_scores(
    records: list[set[int]],
    number_scores: dict[int, float],
) -> list[tuple[tuple[int, int], float]]:
    pool = sorted(number_scores, key=number_scores.get, reverse=True)[:8]
    number_norm = minmax(number_scores)
    pair_norm = pair_strength(records, pool)
    sums = [sum(draw) for draw in records[-1200:]]
    mean_sum = statistics.fmean(sums)
    std_sum = statistics.pstdev(sums) or 1.0
    scored = []
    for pair in itertools.combinations(sorted(pool), 2):
        total = (
            0.68 * statistics.fmean(number_norm[n] for n in pair)
            + 0.18 * pair_norm[pair]
            + 0.14 * gaussian(sum(pair), mean_sum, std_sum)
        )
        scored.append((pair, total))
    return sorted(scored, key=lambda row: row[1], reverse=True)


def select_diversified(
    front_scores: list[tuple[tuple[int, ...], float]],
    back_scores: list[tuple[tuple[int, int], float]],
) -> list[dict]:
    combined = []
    front_top = front_scores[:90]
    back_top = back_scores[:18]
    for front, front_score in front_top:
        for back, back_score in back_top:
            combined.append(
                {
                    "front": front,
                    "back": back,
                    "raw": 0.79 * front_score + 0.21 * back_score,
                }
            )
    combined.sort(key=lambda row: row["raw"], reverse=True)
    selected = []
    for candidate in combined:
        if all(
            len(set(candidate["front"]).intersection(existing["front"])) <= 3
            and len(set(candidate["back"]).intersection(existing["back"])) <= 1
            for existing in selected
        ):
            selected.append(candidate)
        if len(selected) == 3:
            break
    if len(selected) < 3:
        for candidate in combined:
            if candidate not in selected:
                selected.append(candidate)
            if len(selected) == 3:
                break
    best = combined[0]["raw"]
    floor = combined[min(len(combined) - 1, 400)]["raw"]
    span = best - floor or 1.0
    labels = ["主路径", "周期修正", "结构对冲"]
    for index, candidate in enumerate(selected):
        relative = max(0.0, min(1.0, (candidate["raw"] - floor) / span))
        candidate["fit"] = round(76.0 + 9.0 * relative - index * 0.7, 1)
        candidate["label"] = labels[index]
    return selected


def next_draw_day(last_date: str) -> str:
    cursor = date.fromisoformat(last_date) + timedelta(days=1)
    while cursor.weekday() not in {0, 2, 5}:
        cursor += timedelta(days=1)
    return cursor.isoformat()


def format_numbers(numbers) -> list[str]:
    return [f"{number:02d}" for number in numbers]


def reason(candidate: dict) -> str:
    front = candidate["front"]
    odd = sum(n % 2 for n in front)
    low = sum(n <= 17 for n in front)
    return (
        f"全历史先验与近期节奏共同评分；前区和值{sum(front)}、跨度{front[-1]-front[0]}、"
        f"奇偶{odd}:{5-odd}、低高区{low}:{5-low}，并保留不同的号码迁移路径。"
    )


def main() -> None:
    raw = fetch_json(SOURCE_URL)
    cleaned = [item for item in raw if valid_record(item)]
    if len(cleaned) < 1000:
        raise RuntimeError(f"Not enough valid history: {len(cleaned)}")
    cleaned.sort(key=lambda item: (item["date"], int(item["issue"])))

    front_records = [set(map(int, item["front"])) for item in cleaned]
    back_records = [set(map(int, item["back"])) for item in cleaned]

    front_weights, front_test = walk_forward_select(front_records, 35, 5, 10)
    back_weights, back_test = walk_forward_select(back_records, 12, 2, 5)

    front_number_scores, front_features = score_numbers(front_records, 35, front_weights)
    back_number_scores, back_features = score_numbers(back_records, 12, back_weights)

    front_combos = front_combo_scores(front_records, front_number_scores)
    back_pairs = back_pair_scores(back_records, back_number_scores)
    selected = select_diversified(front_combos, back_pairs)

    latest = cleaned[-1]
    output = {
        "modelVersion": MODEL_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "targetIssue": str(int(latest["issue"]) + 1),
        "targetDate": next_draw_day(latest["date"]),
        "historyCount": len(cleaned),
        "historyRange": {
            "earliestIssue": cleaned[0]["issue"],
            "earliestDate": cleaned[0]["date"],
            "latestIssue": latest["issue"],
            "latestDate": latest["date"],
        },
        "latestDraw": {
            "front": latest["front"],
            "back": latest["back"],
        },
        "calibration": {
            "front": front_test,
            "back": back_test,
            "frontWeights": {k: v for k, v in front_weights.items() if k != "name"},
            "backWeights": {k: v for k, v in back_weights.items() if k != "name"},
            "note": "匹配度是模型内部结构评分，不是中奖概率。",
        },
        "results": [
            {
                "rank": index + 1,
                "label": candidate["label"],
                "front": format_numbers(candidate["front"]),
                "back": format_numbers(candidate["back"]),
                "fit": candidate["fit"],
                "reason": reason(candidate),
            }
            for index, candidate in enumerate(selected)
        ],
        "signals": {
            "frontTop10": format_numbers(
                sorted(front_number_scores, key=front_number_scores.get, reverse=True)[:10]
            ),
            "backTop6": format_numbers(
                sorted(back_number_scores, key=back_number_scores.get, reverse=True)[:6]
            ),
        },
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

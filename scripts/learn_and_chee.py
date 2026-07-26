#!/usr/bin/env python3
"""Evaluate Feel the Chee predictions, learn conservatively, and generate two new candidates.

He Tu / Luo Shu mapping: 1/6 Water, 2/7 Fire, 3/8 Wood, 4/9 Metal, 0/5 Earth.
This is an auditable pattern-fitting experiment, not evidence that lottery draws are predictable.
"""
from __future__ import annotations

import itertools
import json
import math
import statistics
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAWS_FILE = ROOT / "data" / "draws.json"
FORECAST_FILE = ROOT / "data" / "chee-forecast.json"
HISTORY_FILE = ROOT / "data" / "chee-forecast-history.json"
LOG_FILE = ROOT / "data" / "chee-learning-log.json"
STATE_FILE = ROOT / "data" / "chee-model-state.json"
MODEL_VERSION = "v1.1-adaptive-chee"

ELEMENTS = ["木", "火", "土", "金", "水"]
DISPLAY_ELEMENTS = ["金", "火", "土", "木", "水"]
DIGIT_ELEMENT = {0: "土", 1: "水", 2: "火", 3: "木", 4: "金", 5: "土", 6: "水", 7: "火", 8: "木", 9: "金"}
GENERATES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
CONTROLS = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

PROFILES = [
    {"name": "balanced-repair", "label": "平衡补缺", "deficit": .34, "generation": .24, "recent": .14, "gap": .14, "transition": .14},
    {"name": "sheng-flow", "label": "生化流转", "deficit": .22, "generation": .38, "recent": .12, "gap": .10, "transition": .18},
    {"name": "cycle-return", "label": "周期回补", "deficit": .38, "generation": .16, "recent": .10, "gap": .24, "transition": .12},
    {"name": "long-harmony", "label": "长期和合", "deficit": .28, "generation": .22, "recent": .22, "gap": .12, "transition": .16},
]


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def number_list(value) -> list[str]:
    parts = value if isinstance(value, list) else str(value or "").split()
    return [f"{int(part):02d}" for part in parts]


def valid_record(row: dict) -> bool:
    try:
        front = [int(n) for n in row["front"]]
        back = [int(n) for n in row["back"]]
        date.fromisoformat(row["date"])
        return len(front) == 5 and len(set(front)) == 5 and all(1 <= n <= 35 for n in front) and len(back) == 2 and len(set(back)) == 2 and all(1 <= n <= 12 for n in back)
    except (KeyError, TypeError, ValueError):
        return False


def load_draws() -> list[dict]:
    payload = read_json(DRAWS_FILE, {})
    rows = payload if isinstance(payload, list) else payload.get("draws", [])
    cleaned = []
    for row in rows:
        try:
            item = {"issue": str(row["issue"]), "date": str(row["date"]), "front": number_list(row["front"]), "back": number_list(row["back"])}
        except (KeyError, TypeError, ValueError):
            continue
        if valid_record(item):
            cleaned.append(item)
    cleaned.sort(key=lambda item: (item["date"], int(item["issue"])))
    if len(cleaned) < 1000:
        raise RuntimeError(f"Not enough valid history: {len(cleaned)}")
    return cleaned


def element(number: int) -> str:
    return DIGIT_ELEMENT[number % 10]


def availability(max_number: int) -> dict[str, int]:
    counts = Counter(element(n) for n in range(1, max_number + 1))
    return {name: counts[name] for name in ELEMENTS}


def element_counts(numbers) -> dict[str, int]:
    counts = Counter(element(int(n)) for n in numbers)
    return {name: counts[name] for name in ELEMENTS}


def similarity(left: dict[str, int], right: dict[str, int]) -> float:
    total = max(1, sum(left.values()), sum(right.values()))
    distance = sum(abs(left[name] - right[name]) for name in ELEMENTS)
    return max(0.0, 1.0 - distance / (2 * total))


def minmax(values: dict) -> dict:
    low, high = min(values.values()), max(values.values())
    span = high - low or 1.0
    return {key: (value - low) / span for key, value in values.items()}


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


def transition_scores(records: list[set[int]], max_number: int) -> dict[int, float]:
    latest = records[-1]
    totals = Counter()
    hits = {source: Counter() for source in latest}
    for current, nxt in zip(records, records[1:]):
        for source in latest.intersection(current):
            totals[source] += 1
            for candidate in nxt:
                hits[source][candidate] += 1
    raw = {}
    for candidate in range(1, max_number + 1):
        probabilities = [hits[source][candidate] / totals[source] for source in latest if totals[source]]
        raw[candidate] = statistics.fmean(probabilities) if probabilities else 0.0
    return minmax(raw)


def element_strength(records: list[set[int]], max_number: int) -> dict[str, float]:
    available = availability(max_number)
    pick_count = statistics.fmean(len(draw) for draw in records[-200:])
    expected = {name: pick_count * available[name] / max_number for name in ELEMENTS}
    windows = [(12, .46), (36, .29), (120, .17), (360, .08)]
    strength = {name: 0.0 for name in ELEMENTS}
    for window, weight in windows:
        sample = records[-window:]
        observed = Counter(element(n) for draw in sample for n in draw)
        for name in ELEMENTS:
            per_draw = observed[name] / max(1, len(sample))
            strength[name] += weight * per_draw / max(.01, expected[name])
    return strength


def element_desirability(strength: dict[str, float]) -> tuple[dict[str, float], str, str]:
    dominant = max(strength, key=strength.get)
    weakest = min(strength, key=strength.get)
    raw = {}
    for name in ELEMENTS:
        deficit = max(0.0, 1.12 - strength[name])
        flow = 0.0
        if name == GENERATES[dominant]:
            flow += 1.0
        if GENERATES[name] == weakest:
            flow += .82
        if name == weakest:
            flow += .45
        if name == dominant:
            flow -= .18
        raw[name] = deficit + .55 * flow
    return minmax(raw), dominant, weakest


def number_scores(records: list[set[int]], max_number: int, profile: dict) -> tuple[dict[int, float], dict]:
    strength = element_strength(records, max_number)
    element_score, dominant, weakest = element_desirability(strength)
    recent = {n: sum(n in draw for draw in records[-36:]) / 36 for n in range(1, max_number + 1)}
    long = {n: sum(n in draw for draw in records[-360:]) / min(360, len(records)) for n in range(1, max_number + 1)}
    momentum = minmax({n: recent[n] - long[n] for n in recent})
    gaps = minmax({n: current_gap(records, n) / max(1.0, mean_gap(records, n)) for n in recent})
    transitions = transition_scores(records, max_number)
    scores = {}
    for n in range(1, max_number + 1):
        elem = element(n)
        flow = 1.0 if elem == GENERATES[dominant] else .75 if GENERATES[elem] == weakest else .35 if elem == weakest else 0.0
        scores[n] = profile["deficit"] * element_score[elem] + profile["generation"] * flow + profile["recent"] * momentum[n] + profile["gap"] * gaps[n] + profile["transition"] * transitions[n]
    return scores, {"strength": strength, "dominant": dominant, "weakest": weakest, "desirability": element_score}


def shape_profile(records: list[set[int]]) -> dict:
    sample = records[-1200:]
    sums = [sum(draw) for draw in sample]
    spans = [max(draw) - min(draw) for draw in sample]
    return {"sumMean": statistics.fmean(sums), "sumStd": statistics.pstdev(sums) or 1.0, "spanMean": statistics.fmean(spans), "spanStd": statistics.pstdev(spans) or 1.0}


def gaussian(value: float, mean: float, std: float) -> float:
    return math.exp(-.5 * ((value - mean) / std) ** 2)


def combo_scores(records: list[set[int]], number_score: dict[int, float], pick: int, pool_size: int) -> list[tuple[tuple[int, ...], float]]:
    pool = sorted(number_score, key=number_score.get, reverse=True)[:pool_size]
    normalized = minmax(number_score)
    shape = shape_profile(records)
    desirability, _, _ = element_desirability(element_strength(records, max(number_score)))
    total_desire = sum(desirability.values()) or 1.0
    target = {name: desirability[name] / total_desire for name in ELEMENTS}
    scored = []
    for combo in itertools.combinations(sorted(pool), pick):
        counts = element_counts(combo)
        proportions = {name: counts[name] / pick for name in ELEMENTS}
        balance = max(0.0, 1.0 - .5 * sum(abs(proportions[name] - target[name]) for name in ELEMENTS))
        elems = [element(n) for n in combo]
        sheng_pairs = sum(1 for a, b in itertools.combinations(elems, 2) if GENERATES[a] == b or GENERATES[b] == a)
        ke_pairs = sum(1 for a, b in itertools.combinations(elems, 2) if CONTROLS[a] == b or CONTROLS[b] == a)
        pair_total = max(1, pick * (pick - 1) / 2)
        generation = sheng_pairs / pair_total
        control_harmony = math.exp(-abs(ke_pairs - max(1, pick // 3)) / max(1, pick))
        shape_score = .58 * gaussian(sum(combo), shape["sumMean"], shape["sumStd"]) + .42 * gaussian(combo[-1] - combo[0], shape["spanMean"], shape["spanStd"])
        number_component = statistics.fmean(normalized[n] for n in combo)
        total = .42 * number_component + .29 * balance + .17 * generation + .07 * control_harmony + .05 * shape_score
        scored.append((combo, total))
    return sorted(scored, key=lambda row: row[1], reverse=True)


def select_two(front_rows, back_rows) -> list[dict]:
    combined = [{"front": front, "back": back, "raw": .79 * fs + .21 * bs} for front, fs in front_rows[:80] for back, bs in back_rows[:15]]
    combined.sort(key=lambda row: row["raw"], reverse=True)
    selected = []
    for candidate in combined:
        if all(len(set(candidate["front"]).intersection(other["front"])) <= 3 and len(set(candidate["back"]).intersection(other["back"])) <= 1 for other in selected):
            selected.append(candidate)
        if len(selected) == 2:
            break
    if len(selected) < 2:
        selected = combined[:2]
    best = combined[0]["raw"]
    floor = combined[min(300, len(combined) - 1)]["raw"]
    span = best - floor or 1.0
    labels = ["五行主衡", "生化对冲"]
    for index, row in enumerate(selected):
        relative = max(0.0, min(1.0, (row["raw"] - floor) / span))
        row["cheeValue"] = round(78.0 + 8.0 * relative - index * .8, 1)
        row["label"] = labels[index]
    return selected


def empty_state() -> dict:
    return {"version": 1, "updatedAt": None, "profiles": {}}


def update_state(state: dict, profile: str, reward: float) -> dict:
    current = state.setdefault("profiles", {}).get(profile, {})
    evaluations = int(current.get("evaluations", 0)) + 1
    previous = current.get("emaReward")
    ema = reward if previous is None else .72 * float(previous) + .28 * reward
    updated = {"evaluations": evaluations, "lastReward": round(reward, 6), "emaReward": round(ema, 6)}
    state["profiles"][profile] = updated
    return updated


def evaluate_previous(previous: dict, draws: list[dict], state: dict, logs: list[dict]) -> dict | None:
    issue = str(previous.get("targetIssue") or "")
    if not issue or not previous.get("results"):
        return None
    existing = next((row for row in logs if str(row.get("issue")) == issue), None)
    if existing:
        return existing
    actual = next((draw for draw in draws if draw["issue"] == issue), None)
    if not actual:
        return None
    actual_front, actual_back = set(actual["front"]), set(actual["back"])
    actual_elements = element_counts([*actual["front"], *actual["back"]])
    rows, rewards = [], []
    for result in previous["results"]:
        predicted_front = set(number_list(result.get("front", [])))
        predicted_back = set(number_list(result.get("back", [])))
        front_hits = sorted(actual_front.intersection(predicted_front))
        back_hits = sorted(actual_back.intersection(predicted_back))
        element_similarity = similarity(element_counts([*predicted_front, *predicted_back]), actual_elements)
        number_reward = .65 * len(front_hits) / 5 + .35 * len(back_hits) / 2
        reward = .68 * number_reward + .32 * element_similarity
        rewards.append(reward)
        rows.append({"rank": result.get("rank"), "label": result.get("label"), "frontHits": front_hits, "backHits": back_hits, "frontHitCount": len(front_hits), "backHitCount": len(back_hits), "elementSimilarity": round(element_similarity, 3), "reward": round(reward, 4)})
    profile = str(previous.get("calibration", {}).get("selectedProfile") or "balanced-repair")
    average_reward = statistics.fmean(rewards)
    evaluation = {
        "issue": issue,
        "date": actual["date"],
        "evaluatedAt": datetime.now(timezone.utc).isoformat(),
        "actual": {"front": actual["front"], "back": actual["back"], "elements": actual_elements},
        "predictionModelVersion": previous.get("modelVersion"),
        "results": rows,
        "summary": {
            "averageFrontHits": round(statistics.fmean(row["frontHitCount"] for row in rows), 3),
            "averageBackHits": round(statistics.fmean(row["backHitCount"] for row in rows), 3),
            "averageElementSimilarity": round(statistics.fmean(row["elementSimilarity"] for row in rows), 3),
            "averageReward": round(average_reward, 4),
        },
        "learningUpdate": {
            "profile": profile,
            "state": update_state(state, profile, average_reward),
            "rule": "Number hits and five-element distribution similarity update an exponential moving average with bounded influence.",
        },
    }
    logs.append(evaluation)
    return evaluation


def profile_selection(front_records, back_records, state: dict) -> tuple[dict, dict]:
    start = max(500, len(front_records) - 180)
    test_indices = list(range(start, len(front_records), 3))
    evaluations = []
    for profile in PROFILES:
        front_hits = back_hits = element_sims = 0.0
        for index in test_indices:
            front_scores, _ = number_scores(front_records[:index], 35, profile)
            back_scores, _ = number_scores(back_records[:index], 12, profile)
            predicted_front = sorted(front_scores, key=front_scores.get, reverse=True)[:5]
            predicted_back = sorted(back_scores, key=back_scores.get, reverse=True)[:2]
            actual_front, actual_back = front_records[index], back_records[index]
            front_hits += len(actual_front.intersection(predicted_front))
            back_hits += len(actual_back.intersection(predicted_back))
            element_sims += similarity(element_counts([*predicted_front, *predicted_back]), element_counts([*actual_front, *actual_back]))
        tests = max(1, len(test_indices))
        average_front = front_hits / tests
        average_back = back_hits / tests
        average_similarity = element_sims / tests
        historical = average_front * 1.7 + average_back * 2.2 + average_similarity * 1.1
        live = state.get("profiles", {}).get(profile["name"], {})
        live_evaluations = int(live.get("evaluations", 0))
        live_ema = float(live.get("emaReward", .22))
        reliability = min(1.0, live_evaluations / 8.0)
        bonus = max(-.16, min(.16, (live_ema - .22) * .65 * reliability))
        evaluations.append({"profile": profile, "tests": tests, "averageFrontHits": average_front, "averageBackHits": average_back, "averageElementSimilarity": average_similarity, "historicalObjective": historical, "adaptiveBonus": bonus, "objective": historical + bonus, "liveEvaluations": live_evaluations, "liveEmaReward": live_ema if live_evaluations else None})
    winner = max(evaluations, key=lambda row: row["objective"])
    info = {key: round(value, 4) if isinstance(value, float) else value for key, value in winner.items() if key != "profile"}
    info["selectedProfile"] = winner["profile"]["name"]
    info["selectedLabel"] = winner["profile"]["label"]
    return winner["profile"], info


def next_draw_day(last_date: str) -> str:
    cursor = date.fromisoformat(last_date) + timedelta(days=1)
    while cursor.weekday() not in {0, 2, 5}:
        cursor += timedelta(days=1)
    return cursor.isoformat()


def format_numbers(values) -> list[str]:
    return [f"{int(number):02d}" for number in values]


def reason(candidate: dict, analysis: dict) -> str:
    front_elements = element_counts(candidate["front"])
    active = "、".join(name for name in DISPLAY_ELEMENTS if front_elements[name])
    return f"以{analysis['weakest']}为回补重点，由{analysis['dominant']}势导出生化路径；前区覆盖{active}，兼顾五行平衡、相生关系与号码周期。"


def archive(previous: dict, evaluation: dict | None) -> None:
    if not previous.get("targetIssue"):
        return
    history = read_json(HISTORY_FILE, [])
    if not isinstance(history, list):
        history = []
    if any(str(row.get("targetIssue")) == str(previous["targetIssue"]) for row in history):
        return
    snapshot = dict(previous)
    if evaluation:
        snapshot["evaluation"] = evaluation
    history.append(snapshot)
    history.sort(key=lambda row: int(row.get("targetIssue", 0)))
    write_json(HISTORY_FILE, history)


def main() -> None:
    draws = load_draws()
    previous = read_json(FORECAST_FILE, {})
    logs = read_json(LOG_FILE, [])
    state = read_json(STATE_FILE, empty_state())
    if not isinstance(logs, list):
        logs = []
    if not isinstance(state, dict):
        state = empty_state()

    evaluation = evaluate_previous(previous, draws, state, logs)
    archive(previous, evaluation)

    front_records = [set(map(int, row["front"])) for row in draws]
    back_records = [set(map(int, row["back"])) for row in draws]
    profile, calibration = profile_selection(front_records, back_records, state)
    front_scores, front_analysis = number_scores(front_records, 35, profile)
    back_scores, back_analysis = number_scores(back_records, 12, profile)
    selected = select_two(combo_scores(front_records, front_scores, 5, 16), combo_scores(back_records, back_scores, 2, 8))

    combined_strength = {name: .72 * front_analysis["strength"][name] + .28 * back_analysis["strength"][name] for name in ELEMENTS}
    scaled = minmax(combined_strength)
    display_strength = {name: round(24 + 64 * scaled[name]) for name in DISPLAY_ELEMENTS}
    latest = draws[-1]
    generated_at = datetime.now(timezone.utc).isoformat()
    output = {
        "modelVersion": MODEL_VERSION,
        "generatedAt": generated_at,
        "targetIssue": str(int(latest["issue"]) + 1),
        "targetDate": next_draw_day(latest["date"]),
        "historyCount": len(draws),
        "historyRange": {"earliestIssue": draws[0]["issue"], "earliestDate": draws[0]["date"], "latestIssue": latest["issue"], "latestDate": latest["date"]},
        "mapping": {"水": [1, 6], "火": [2, 7], "木": [3, 8], "金": [4, 9], "土": [0, 5]},
        "elementStrengths": display_strength,
        "analysis": {"dominant": front_analysis["dominant"], "weakest": front_analysis["weakest"], "flowTarget": GENERATES[front_analysis["dominant"]]},
        "lastEvaluation": evaluation,
        "calibration": calibration,
        "results": [
            {
                "rank": index + 1,
                "label": row["label"],
                "front": format_numbers(row["front"]),
                "back": format_numbers(row["back"]),
                "cheeValue": row["cheeValue"],
                "elements": element_counts([*row["front"], *row["back"]]),
                "reason": reason(row, front_analysis),
            }
            for index, row in enumerate(selected)
        ],
        "note": "Chee值衡量五行结构与历史周期的内部匹配，不是中奖概率。",
    }
    state["updatedAt"] = generated_at
    write_json(STATE_FILE, state)
    write_json(LOG_FILE, logs[-200:])
    write_json(FORECAST_FILE, output)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

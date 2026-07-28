#!/usr/bin/env python3
"""Formula-only Feel the Chee calculator.

Only the target issue and target draw date enter the calculation. Historical draw
results and learning state are never read by the formula.
"""
from __future__ import annotations

import itertools
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAWS_FILE = ROOT / "data" / "draws.json"
AI_FORECAST_FILE = ROOT / "data" / "forecast.json"
OUTPUT_FILE = ROOT / "data" / "chee-forecast.json"
VERSION = "v2.1-formula-only"
FORMULA = "hetu-luoshu-date-issue-v2"
FRONT_POOL_SIZE = 16
BACK_POOL_SIZE = 10

ELEMENTS = ["木", "火", "土", "金", "水"]
DISPLAY_ELEMENTS = ["金", "火", "土", "木", "水"]
DIGIT_ELEMENT = {
    0: "土",
    1: "水",
    2: "火",
    3: "木",
    4: "金",
    5: "土",
    6: "水",
    7: "火",
    8: "木",
    9: "金",
}
GENERATES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
CONTROLS = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}
LUO_SHU = [4, 9, 2, 3, 5, 7, 8, 1, 6]


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


def digit_sum(value) -> int:
    return sum(int(character) for character in str(value) if character.isdigit())


def digital_root(value: int) -> int:
    return 9 if value % 9 == 0 else value % 9


def next_draw_day(last_date: str) -> str:
    cursor = date.fromisoformat(last_date) + timedelta(days=1)
    while cursor.weekday() not in {0, 2, 5}:
        cursor += timedelta(days=1)
    return cursor.isoformat()


def target() -> tuple[str, str]:
    ai_forecast = read_json(AI_FORECAST_FILE, {})
    if ai_forecast.get("targetIssue") and ai_forecast.get("targetDate"):
        return str(ai_forecast["targetIssue"]), str(ai_forecast["targetDate"])
    metadata = read_json(DRAWS_FILE, {}).get("meta", {})
    return (
        str(int(metadata["latestIssue"]) + 1),
        next_draw_day(metadata["latestDate"]),
    )


def elem(number: int) -> str:
    return DIGIT_ELEMENT[number % 10]


def circular_distance(first: int, second: int) -> int:
    difference = abs(first - second)
    return min(difference, 9 - difference)


def context(issue: str, draw_date: str) -> dict:
    parsed_date = date.fromisoformat(draw_date)
    compact_date = parsed_date.strftime("%Y%m%d")
    date_sum = digit_sum(compact_date)
    issue_sum = digit_sum(issue)
    heaven = digital_root(date_sum)
    earth = digital_root(issue_sum)
    human = digital_root(heaven + earth + parsed_date.day)
    moving_line = (heaven + earth + parsed_date.month + parsed_date.day) % 6 + 1
    primary_digit = (heaven + moving_line) % 10
    primary_element = DIGIT_ELEMENT[primary_digit]
    support_element = GENERATES[primary_element]
    balance_element = GENERATES[support_element]
    control_element = CONTROLS[primary_element]
    issue_tail = int(issue[-1])
    date_tail = int(compact_date[-1])

    return {
        "targetIssue": issue,
        "targetDate": draw_date,
        "dateDigits": compact_date,
        "dateDigitSum": date_sum,
        "issueDigitSum": issue_sum,
        "heavenNumber": heaven,
        "earthNumber": earth,
        "humanNumber": human,
        "movingLine": moving_line,
        "guaNumber": digital_root(heaven + earth + human + moving_line),
        "primaryDigit": primary_digit,
        "issueTailDigit": issue_tail,
        "dateTailDigit": date_tail,
        "yinYang": "阳" if (heaven + earth + moving_line + issue_tail) % 2 else "阴",
        "primaryElement": primary_element,
        "supportElement": support_element,
        "balanceElement": balance_element,
        "controlElement": control_element,
    }


def number_score(number: int, calculation: dict, variant: int) -> float:
    number_element = elem(number)
    element_weight = {
        calculation["primaryElement"]: 1.0,
        calculation["supportElement"]: 0.88,
        calculation["balanceElement"]: 0.66,
        calculation["controlElement"]: 0.30,
    }.get(number_element, 0.44)
    number_root = digital_root(number)

    def resonance(target_number: int) -> float:
        return 1 - circular_distance(number_root, target_number) / 4.5

    gua_match = (
        1.0
        if number_root == calculation["guaNumber"]
        else 0.70
        if number_root
        in {
            LUO_SHU[(calculation["guaNumber"] - 2) % 9],
            LUO_SHU[calculation["guaNumber"] % 9],
        }
        else 0.28
    )
    desired_parity = 1 if calculation["yinYang"] == "阳" else 0
    parity_match = 1.0 if number % 2 == desired_parity else 0.45
    tail_match = (
        1.0
        if number % 10
        in {
            calculation["primaryDigit"],
            calculation["issueTailDigit"],
            calculation["dateTailDigit"],
        }
        else 0.35
    )
    variant_resonance = resonance(
        digital_root(calculation["guaNumber"] + variant * calculation["movingLine"])
    )

    return (
        0.34 * element_weight
        + 0.14 * resonance(calculation["heavenNumber"])
        + 0.12 * resonance(calculation["earthNumber"])
        + 0.09 * resonance(calculation["humanNumber"])
        + 0.10 * gua_match
        + 0.08 * parity_match
        + 0.07 * tail_match
        + 0.06 * variant_resonance
    )


# Compatibility alias used by the historical audit.
nscore = number_score


def element_counts(numbers) -> dict[str, int]:
    return {
        element_name: sum(elem(int(number)) == element_name for number in numbers)
        for element_name in ELEMENTS
    }


def target_pattern(calculation: dict, pick: int, variant: int) -> dict[str, float]:
    weights = {element_name: 0.2 for element_name in ELEMENTS}
    if variant == 1:
        weights[calculation["primaryElement"]] += 0.70
        weights[calculation["supportElement"]] += 0.56
        weights[calculation["balanceElement"]] += 0.30
    else:
        weights[calculation["primaryElement"]] += 0.42
        weights[calculation["supportElement"]] += 0.72
        weights[calculation["balanceElement"]] += 0.48
        weights[calculation["controlElement"]] += 0.18
    total = sum(weights.values())
    return {
        element_name: pick * weights[element_name] / total
        for element_name in ELEMENTS
    }


# Compatibility alias used by the historical audit.
pattern = target_pattern


def combination_score(
    combination: tuple[int, ...],
    scores: dict[int, float],
    calculation: dict,
    variant: int,
    maximum_number: int,
) -> float:
    pick = len(combination)
    actual_elements = element_counts(combination)
    desired_elements = target_pattern(calculation, pick, variant)
    balance = max(
        0.0,
        1
        - sum(
            abs(actual_elements[element_name] - desired_elements[element_name])
            for element_name in ELEMENTS
        )
        / (2 * pick),
    )
    combination_root = digital_root(sum(combination))
    gua_match = (
        1.0
        if combination_root == calculation["guaNumber"]
        else max(
            0.0,
            1
            - circular_distance(combination_root, calculation["guaNumber"]) / 4.5,
        )
    )
    desired_odd = min(pick, 3 if calculation["yinYang"] == "阳" else 2)
    odd_match = math.exp(
        -abs(sum(number % 2 for number in combination) - desired_odd) / max(1, pick)
    )
    roots = {digital_root(number) for number in combination}
    coverage = len(
        roots
        & {
            calculation["heavenNumber"],
            calculation["earthNumber"],
            calculation["humanNumber"],
            calculation["guaNumber"],
        }
    ) / 4
    desired_span = 0.64 if pick == 5 else 0.48
    spacing = math.exp(
        -abs((combination[-1] - combination[0]) / maximum_number - desired_span)
        / 0.30
    )

    return (
        0.48 * sum(scores[number] for number in combination) / pick
        + 0.24 * balance
        + 0.10 * gua_match
        + 0.07 * odd_match
        + 0.06 * coverage
        + 0.05 * spacing
    )


# Compatibility alias used by the historical audit.
cscore = combination_score


def ranked_combinations(
    maximum_number: int,
    pick: int,
    calculation: dict,
    variant: int,
) -> list[tuple[tuple[int, ...], float]]:
    scores = {
        number: number_score(number, calculation, variant)
        for number in range(1, maximum_number + 1)
    }
    pool_size = FRONT_POOL_SIZE if maximum_number == 35 else BACK_POOL_SIZE
    candidate_pool = sorted(
        scores,
        key=lambda number: (scores[number], -number),
        reverse=True,
    )[:pool_size]
    rows = [
        (
            combination,
            combination_score(
                combination,
                scores,
                calculation,
                variant,
                maximum_number,
            ),
        )
        for combination in itertools.combinations(sorted(candidate_pool), pick)
    ]
    return sorted(rows, key=lambda row: row[1], reverse=True)


# Compatibility alias used by the historical audit.
rank = ranked_combinations


def select_candidate(
    front_rows,
    back_rows,
    previous: dict | None,
    variant: int,
) -> dict:
    previous_front = set(previous["front"]) if previous else set()
    previous_back = set(previous["back"]) if previous else set()
    for front, front_score in front_rows[:800]:
        if previous and len(set(front) & previous_front) > 2:
            continue
        for back, back_score in back_rows[:50]:
            if previous and len(set(back) & previous_back) > 1:
                continue
            return {
                "front": front,
                "back": back,
                "raw": 0.79 * front_score + 0.21 * back_score,
                "variant": variant,
            }
    front, front_score = front_rows[0]
    back, back_score = back_rows[0]
    return {
        "front": front,
        "back": back,
        "raw": 0.79 * front_score + 0.21 * back_score,
        "variant": variant,
    }


# Compatibility alias.
select = select_candidate


def element_strengths(calculation: dict) -> dict[str, int]:
    values = {element_name: 30 for element_name in ELEMENTS}
    values[calculation["primaryElement"]] += 58
    values[calculation["supportElement"]] += 42
    values[calculation["balanceElement"]] += 24
    values[calculation["controlElement"]] += 10
    return {
        element_name: min(100, values[element_name])
        for element_name in DISPLAY_ELEMENTS
    }


def format_numbers(numbers) -> list[str]:
    return [f"{number:02d}" for number in numbers]


def reason(calculation: dict) -> str:
    return (
        f"公式输入第{calculation['targetIssue']}期与{calculation['targetDate']}；"
        f"天数{calculation['heavenNumber']}、地数{calculation['earthNumber']}、"
        f"人数{calculation['humanNumber']}、动爻{calculation['movingLine']}。"
        f"按{calculation['primaryElement']}→{calculation['supportElement']}→"
        f"{calculation['balanceElement']}生化路径及河图洛书数位共振选取，"
        "不读取历史开奖。"
    )


def calculate(issue: str, draw_date: str) -> tuple[dict, list[dict]]:
    calculation = context(issue, draw_date)
    first = select_candidate(
        ranked_combinations(35, 5, calculation, 1),
        ranked_combinations(12, 2, calculation, 1),
        None,
        1,
    )
    second = select_candidate(
        ranked_combinations(35, 5, calculation, 2),
        ranked_combinations(12, 2, calculation, 2),
        first,
        2,
    )
    rows = [first, second]
    best_score = max(row["raw"] for row in rows)
    worst_score = min(row["raw"] for row in rows)
    score_span = best_score - worst_score or 1.0
    labels = ["五行主衡", "生化对冲"]

    results = []
    for index, row in enumerate(rows):
        results.append(
            {
                "rank": index + 1,
                "label": labels[index],
                "front": list(row["front"]),
                "back": list(row["back"]),
                "cheeValue": round(
                    80
                    + (row["raw"] - worst_score) / score_span * 6
                    - index * 0.4,
                    1,
                ),
            }
        )
    return calculation, results


def main() -> None:
    issue, draw_date = target()
    calculation, results = calculate(issue, draw_date)
    output = {
        "modelVersion": VERSION,
        "formulaVersion": FORMULA,
        "formulaOnly": True,
        "historyUsed": False,
        "learningEnabled": False,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "targetIssue": issue,
        "targetDate": draw_date,
        "mapping": {
            "水": [1, 6],
            "火": [2, 7],
            "木": [3, 8],
            "金": [4, 9],
            "土": [0, 5],
        },
        "candidatePool": {
            "front": FRONT_POOL_SIZE,
            "back": BACK_POOL_SIZE,
            "rule": "Formula-ranked shortlist only; no historical draw input.",
        },
        "elementStrengths": element_strengths(calculation),
        "calculation": calculation,
        "results": [
            {
                **result,
                "front": format_numbers(result["front"]),
                "back": format_numbers(result["back"]),
                "elements": element_counts([*result["front"], *result["back"]]),
                "reason": reason(calculation),
            }
            for result in results
        ],
        "note": (
            "Feel the Chee uses only target issue/date and the He Tu / Luo Shu "
            "formula. No historical draw learning is used; Chee value is not a "
            "winning probability."
        ),
    }
    write_json(OUTPUT_FILE, output)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

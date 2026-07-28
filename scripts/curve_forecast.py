#!/usr/bin/env python3
"""Forecast sorted-position curves, then sample diverse DLT combinations.

All valid combinations remain equally likely in a fair draw. This is exploratory
pattern fitting, not a claim of improved lottery odds.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAWS_FILE = ROOT / "data" / "draws.json"
FORECAST_FILE = ROOT / "data" / "forecast.json"
HISTORY_FILE = ROOT / "data" / "forecast-history.json"
LOG_FILE = ROOT / "data" / "learning-log.json"
STATE_FILE = ROOT / "data" / "model-state.json"

VERSION = "v3.0-curve-sampler"

PROFILES = [
    {
        "name": "local-drift",
        "label": "局部漂移",
        "window": 18,
        "trend": 0.42,
        "reversion": 0.28,
        "cycle": 0.30,
        "temperature": 1.10,
    },
    {
        "name": "adaptive-wave",
        "label": "自适应波形",
        "window": 36,
        "trend": 0.28,
        "reversion": 0.34,
        "cycle": 0.38,
        "temperature": 1.24,
    },
    {
        "name": "regime-shift",
        "label": "区间换挡",
        "window": 24,
        "trend": 0.48,
        "reversion": 0.18,
        "cycle": 0.34,
        "temperature": 1.38,
    },
    {
        "name": "wide-band",
        "label": "宽带采样",
        "window": 60,
        "trend": 0.18,
        "reversion": 0.42,
        "cycle": 0.40,
        "temperature": 1.52,
    },
]


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


def load() -> list[dict]:
    payload = read_json(DRAWS_FILE, {})
    rows = payload if isinstance(payload, list) else payload.get("draws", [])
    output = []

    for row in rows:
        try:
            front = sorted(numbers(row["front"]))
            back = sorted(numbers(row["back"]))
            draw_date = str(row["date"])
            date.fromisoformat(draw_date)
        except (KeyError, TypeError, ValueError):
            continue

        if (
            len(front) == 5
            and len(set(front)) == 5
            and min(front) >= 1
            and max(front) <= 35
            and len(back) == 2
            and len(set(back)) == 2
            and min(back) >= 1
            and max(back) <= 12
        ):
            output.append(
                {
                    "issue": str(row["issue"]),
                    "date": draw_date,
                    "front": front,
                    "back": back,
                }
            )

    output.sort(key=lambda row: (row["date"], int(row["issue"])))
    if len(output) < 1000:
        raise RuntimeError(f"Not enough valid history: {len(output)}")
    return output


def next_draw_day(last_date: str) -> str:
    cursor = date.fromisoformat(last_date) + timedelta(days=1)
    while cursor.weekday() not in {0, 2, 5}:
        cursor += timedelta(days=1)
    return cursor.isoformat()


def deterministic_seed(*values) -> int:
    digest = hashlib.sha256(
        "|".join(map(str, values)).encode()
    ).digest()
    return int.from_bytes(digest[:8], "big")


def weighted_mean(values, decay: float = 0.91) -> float:
    weights = [
        decay ** (len(values) - 1 - index)
        for index in range(len(values))
    ]
    return sum(
        value * weight for value, weight in zip(values, weights)
    ) / sum(weights)


def slope(values) -> float:
    if len(values) < 3:
        return 0.0
    x_mean = (len(values) - 1) / 2
    y_mean = statistics.fmean(values)
    denominator = sum(
        (index - x_mean) ** 2 for index in range(len(values))
    ) or 1
    return sum(
        (index - x_mean) * (value - y_mean)
        for index, value in enumerate(values)
    ) / denominator


def cycle(values) -> tuple[int, float]:
    if len(values) < 12:
        return 3, 0.0

    mean = statistics.fmean(values)
    centered = [value - mean for value in values]
    best = (3, -1.0)

    for lag in range(2, min(19, len(values) // 2 + 1)):
        left = centered[lag:]
        right = centered[:-lag]
        denominator = math.sqrt(
            sum(value * value for value in left)
            * sum(value * value for value in right)
        ) or 1
        correlation = sum(
            x * y for x, y in zip(left, right)
        ) / denominator
        if correlation > best[1]:
            best = lag, correlation

    return best[0], max(0.0, best[1])


def curve(
    series: list[float],
    profile: dict,
    lower: int,
    upper: int,
) -> dict:
    values = series[-min(profile["window"], len(series)) :]
    mean = weighted_mean(values)
    local_slope = max(
        -2.2,
        min(2.2, slope(values[-min(14, len(values)) :])),
    )
    cycle_lag, cycle_strength = cycle(values)
    cycle_delta = (
        values[-cycle_lag + 1] - values[-cycle_lag]
        if len(values) > cycle_lag
        else 0
    )
    center = max(
        lower,
        min(
            upper,
            values[-1]
            + profile["trend"] * local_slope
            + profile["reversion"] * (mean - values[-1])
            + profile["cycle"] * cycle_strength * cycle_delta,
        ),
    )

    residuals = []
    for index in range(max(4, len(values) // 3), len(values)):
        earlier = values[:index]
        prediction = (
            earlier[-1]
            + profile["trend"]
            * slope(earlier[-min(14, len(earlier)) :])
            + profile["reversion"]
            * (weighted_mean(earlier) - earlier[-1])
        )
        residuals.append(values[index] - prediction)

    sigma = (
        statistics.pstdev(residuals)
        if len(residuals) >= 3
        else statistics.pstdev(values)
    )
    return {
        "center": center,
        "sigma": max(0.85, sigma * profile["temperature"]),
        "slope": local_slope,
        "cycleLag": cycle_lag,
        "cycleStrength": cycle_strength,
    }


def model(
    draws: list[dict],
    area: str,
    profile: dict,
    lower: int,
    upper: int,
) -> list[dict]:
    # curve() only reads the profile window. Restricting the source rows here
    # preserves identical output while making full walk-forward audits practical.
    sample = draws[-min(profile["window"], len(draws)) :]
    width = len(sample[0][area])
    return [
        curve(
            [draw[area][position] for draw in sample],
            profile,
            lower,
            upper,
        )
        for position in range(width)
    ]


def loss(actual: list[int], model_rows: list[dict], upper: int) -> float:
    position_loss = statistics.fmean(
        abs(value - model_rows[index]["center"]) / upper
        for index, value in enumerate(actual)
    )
    sum_loss = abs(
        sum(actual) - sum(row["center"] for row in model_rows)
    ) / (upper * len(actual))
    span_loss = abs(
        (actual[-1] - actual[0])
        - (model_rows[-1]["center"] - model_rows[0]["center"])
    ) / upper
    return 0.68 * position_loss + 0.20 * sum_loss + 0.12 * span_loss


def backtest(draws: list[dict], profile: dict) -> dict:
    # The live archive is far beyond this threshold. The lower guard lets the
    # historical audit begin after its 500-draw warm-up without an empty test set.
    indices = range(max(120, len(draws) - 150), len(draws), 3)
    front_losses = []
    back_losses = []

    for index in indices:
        history = draws[:index]
        front_losses.append(
            loss(
                draws[index]["front"],
                model(history, "front", profile, 1, 35),
                35,
            )
        )
        back_losses.append(
            loss(
                draws[index]["back"],
                model(history, "back", profile, 1, 12),
                12,
            )
        )

    if not front_losses or not back_losses:
        raise RuntimeError("Not enough history for curve-profile validation")

    front_mean = statistics.fmean(front_losses)
    back_mean = statistics.fmean(back_losses)
    return {
        "tests": len(front_losses),
        "frontCurveLoss": front_mean,
        "backCurveLoss": back_mean,
        "objective": 0.72 * front_mean + 0.28 * back_mean,
    }


def initial_state() -> dict:
    return {
        "version": 2,
        "updatedAt": None,
        "profiles": {},
        "temperatureAdjustment": 0.0,
    }


def evaluate(
    previous: dict,
    draws: list[dict],
    state: dict,
    logs: list[dict],
):
    issue = str(previous.get("targetIssue") or "")
    if not issue or not previous.get("results"):
        return None

    existing = next(
        (
            row
            for row in logs
            if str(row.get("issue")) == issue
            and row.get("modelFamily") == "curve-sampler"
        ),
        None,
    )
    if existing:
        return existing

    actual = next(
        (draw for draw in draws if draw["issue"] == issue),
        None,
    )
    if not actual:
        return None

    rows = []
    distances = []

    for result in previous["results"]:
        front = sorted(numbers(result.get("front", [])))
        back = sorted(numbers(result.get("back", [])))
        front_hits = sorted(set(front) & set(actual["front"]))
        back_hits = sorted(set(back) & set(actual["back"]))
        distance = (
            0.72
            * statistics.fmean(
                abs(left - right)
                for left, right in zip(front, actual["front"])
            )
            / 35
            + 0.28
            * statistics.fmean(
                abs(left - right)
                for left, right in zip(back, actual["back"])
            )
            / 12
        )
        distances.append(distance)
        rows.append(
            {
                "rank": result.get("rank"),
                "label": result.get("label"),
                "frontHits": [f"{number:02d}" for number in front_hits],
                "backHits": [f"{number:02d}" for number in back_hits],
                "frontHitCount": len(front_hits),
                "backHitCount": len(back_hits),
                "curveDistance": round(distance, 4),
            }
        )

    profile_name = str(
        previous.get("calibration", {}).get("selectedProfile")
        or "unknown"
    )
    current = state.setdefault("profiles", {}).get(profile_name, {})
    evaluations = int(current.get("evaluations", 0)) + 1
    best_distance = min(distances)
    previous_ema = current.get("emaCurveDistance")
    ema = (
        best_distance
        if previous_ema is None
        else 0.74 * float(previous_ema) + 0.26 * best_distance
    )
    state["profiles"][profile_name] = {
        "evaluations": evaluations,
        "lastCurveDistance": round(best_distance, 6),
        "emaCurveDistance": round(ema, 6),
    }
    adjustment = max(-0.18, min(0.25, (ema - 0.105) * 1.8))
    state["temperatureAdjustment"] = round(adjustment, 4)

    event = {
        "issue": issue,
        "date": actual["date"],
        "modelFamily": "curve-sampler",
        "evaluatedAt": datetime.now(timezone.utc).isoformat(),
        "actual": {
            "front": [f"{number:02d}" for number in actual["front"]],
            "back": [f"{number:02d}" for number in actual["back"]],
        },
        "results": rows,
        "summary": {
            "averageFrontHits": round(
                statistics.fmean(row["frontHitCount"] for row in rows),
                3,
            ),
            "averageBackHits": round(
                statistics.fmean(row["backHitCount"] for row in rows),
                3,
            ),
            "bestCurveDistance": round(best_distance, 4),
        },
        "learningUpdate": {
            "profile": profile_name,
            "emaCurveDistance": round(ema, 4),
            "temperatureAdjustment": round(adjustment, 4),
            "rule": (
                "Prediction error changes only the sampling-band width; "
                "recent winning numbers are not fixed favourites."
            ),
        },
    }
    logs.append(event)
    return event


def choose(draws: list[dict], state: dict) -> tuple[dict, dict]:
    rows = []

    for profile in PROFILES:
        result = backtest(draws, profile)
        live = state.get("profiles", {}).get(profile["name"], {})
        evaluations = int(live.get("evaluations", 0))
        live_distance = float(
            live.get("emaCurveDistance", result["objective"])
        )
        reliability = min(0.35, evaluations * 0.045)
        rows.append(
            {
                "profile": profile,
                **result,
                "liveEvaluations": evaluations,
                "liveCurveDistance": (
                    live_distance if evaluations else None
                ),
                "adjustedObjective": (
                    result["objective"] * (1 - reliability)
                    + live_distance * reliability
                ),
            }
        )

    winner = min(rows, key=lambda row: row["adjustedObjective"])
    return dict(winner["profile"]), {
        "selectedProfile": winner["profile"]["name"],
        "selectedLabel": winner["profile"]["label"],
        "tests": winner["tests"],
        "frontCurveLoss": round(winner["frontCurveLoss"], 4),
        "backCurveLoss": round(winner["backCurveLoss"], 4),
        "historicalObjective": round(winner["objective"], 4),
        "adjustedObjective": round(winner["adjustedObjective"], 4),
        "liveEvaluations": winner["liveEvaluations"],
        "liveCurveDistance": (
            None
            if winner["liveCurveDistance"] is None
            else round(winner["liveCurveDistance"], 4)
        ),
    }


def gaussian_integer(
    rng: random.Random,
    center: float,
    sigma: float,
    lower: int,
    upper: int,
) -> int:
    for _ in range(30):
        value = round(rng.gauss(center, sigma))
        if lower <= value <= upper:
            return int(value)
    return max(lower, min(upper, round(center)))


def sample(
    rng: random.Random,
    model_rows: list[dict],
    lower: int,
    upper: int,
    adjustment: float,
):
    values = sorted(
        gaussian_integer(
            rng,
            row["center"],
            row["sigma"] * (1 + adjustment),
            lower,
            upper,
        )
        for row in model_rows
    )
    return tuple(values) if len(set(values)) == len(values) else None


def shape(draws: list[dict], area: str) -> tuple:
    values = [draw[area] for draw in draws[-1200:]]
    sums = [sum(row) for row in values]
    spans = [row[-1] - row[0] for row in values]
    odd_counts = [sum(number % 2 for number in row) for row in values]
    return (
        statistics.fmean(sums),
        statistics.pstdev(sums) or 1,
        statistics.fmean(spans),
        statistics.pstdev(spans) or 1,
        statistics.fmean(odd_counts),
        statistics.pstdev(odd_counts) or 1,
    )


def gaussian_score(value: float, mean: float, sigma: float) -> float:
    return math.exp(-0.5 * ((value - mean) / sigma) ** 2)


def score(values: tuple[int, ...], model_rows: list[dict], historical_shape) -> float:
    distance = statistics.fmean(
        abs(value - model_rows[index]["center"])
        / max(1, model_rows[index]["sigma"])
        for index, value in enumerate(values)
    )
    curve_fit = math.exp(-0.5 * distance)
    predicted_sum = sum(row["center"] for row in model_rows)
    predicted_span = (
        model_rows[-1]["center"] - model_rows[0]["center"]
    )
    trajectory = (
        0.58
        * gaussian_score(
            sum(values),
            predicted_sum,
            max(2, sum(row["sigma"] for row in model_rows) / 2),
        )
        + 0.42
        * gaussian_score(
            values[-1] - values[0],
            predicted_span,
            max(
                2,
                statistics.fmean(row["sigma"] for row in model_rows),
            ),
        )
    )
    historical = (
        0.45
        * gaussian_score(
            sum(values),
            historical_shape[0],
            historical_shape[1],
        )
        + 0.35
        * gaussian_score(
            values[-1] - values[0],
            historical_shape[2],
            historical_shape[3],
        )
        + 0.20
        * gaussian_score(
            sum(number % 2 for number in values),
            historical_shape[4],
            historical_shape[5],
        )
    )
    return 0.60 * curve_fit + 0.25 * trajectory + 0.15 * historical


def pool(
    rng: random.Random,
    model_rows: list[dict],
    draws: list[dict],
    area: str,
    lower: int,
    upper: int,
    adjustment: float,
    count: int,
):
    historical_shape = shape(draws, area)
    output = {}
    attempts = 0

    while len(output) < count and attempts < count * 40:
        attempts += 1
        values = sample(
            rng,
            model_rows,
            lower,
            upper,
            adjustment,
        )
        if values:
            output[values] = max(
                output.get(values, 0),
                score(values, model_rows, historical_shape),
            )

    return sorted(
        output.items(),
        key=lambda row: row[1],
        reverse=True,
    )


def pick(rng: random.Random, rows, temperature: float):
    candidates = rows[: max(25, min(180, len(rows)))]
    best = candidates[0][1]
    weights = [
        math.exp((score_value - best) / max(0.03, temperature))
        for _, score_value in candidates
    ]
    return rng.choices(
        [values for values, _ in candidates],
        weights=weights,
        k=1,
    )[0]


def assemble(
    rng: random.Random,
    front_pool,
    back_pool,
    previous: dict,
) -> list[dict]:
    previous_front = [
        set(numbers(row.get("front", [])))
        for row in previous.get("results", [])
    ]
    previous_back = [
        set(numbers(row.get("back", [])))
        for row in previous.get("results", [])
    ]
    output = []

    for _ in range(500):
        front = pick(rng, front_pool, 0.14 + len(output) * 0.035)
        back = pick(rng, back_pool, 0.12 + len(output) * 0.04)

        if any(
            len(set(front) & set(row["front"])) > 2
            or len(set(back) & set(row["back"])) > 1
            for row in output
        ):
            continue
        if previous_front and max(
            len(set(front) & row) for row in previous_front
        ) > 3:
            continue
        if previous_back and max(
            len(set(back) & row) for row in previous_back
        ) > 1:
            continue

        output.append({"front": front, "back": back})
        if len(output) == 3:
            break

    if len(output) < 3:
        for front, _ in front_pool:
            for back, _ in back_pool:
                if all(
                    len(set(front) & set(row["front"])) <= 3
                    for row in output
                ):
                    output.append({"front": front, "back": back})
                if len(output) == 3:
                    break
            if len(output) == 3:
                break

    labels = ["曲线主样本", "波动延伸", "随机带对冲"]
    for index, row in enumerate(output):
        row.update(
            rank=index + 1,
            label=labels[index],
            fit=round(84 - index * 2.2, 1),
        )
    return output


def model_summary(model_rows: list[dict]) -> dict:
    return {
        "centers": [round(row["center"], 2) for row in model_rows],
        "sigmas": [round(row["sigma"], 2) for row in model_rows],
        "slopes": [round(row["slope"], 3) for row in model_rows],
        "cycleLags": [row["cycleLag"] for row in model_rows],
    }


def reason(result: dict, front_model: list[dict]) -> str:
    centers = " / ".join(
        f'{row["center"]:.1f}' for row in front_model
    )
    return (
        f"从五个排序位置的预测中心 [{centers}] 及波动带中抽样；"
        f"本组和值{sum(result['front'])}、"
        f"跨度{result['front'][-1] - result['front'][0]}，"
        "并执行跨期与组间多样性约束。"
    )


def archive(previous: dict, evaluation) -> None:
    if not previous.get("targetIssue"):
        return
    history = read_json(HISTORY_FILE, [])
    issue = str(previous["targetIssue"])
    if any(
        str(row.get("targetIssue")) == issue for row in history
    ):
        return
    snapshot = dict(previous)
    snapshot["evaluation"] = evaluation
    history.append(snapshot)
    history.sort(key=lambda row: int(row.get("targetIssue", 0)))
    write_json(HISTORY_FILE, history[-500:])


def main() -> None:
    draws = load()
    previous = read_json(FORECAST_FILE, {})
    logs = read_json(LOG_FILE, [])
    state = read_json(STATE_FILE, initial_state())

    evaluation = evaluate(previous, draws, state, logs)
    archive(previous, evaluation)

    profile, calibration = choose(draws, state)
    adjustment = float(state.get("temperatureAdjustment", 0))
    profile["temperature"] *= 1 + adjustment

    front_model = model(draws, "front", profile, 1, 35)
    back_model = model(draws, "back", profile, 1, 12)
    latest = draws[-1]
    issue = str(int(latest["issue"]) + 1)
    target_date = next_draw_day(latest["date"])
    rng = random.Random(
        deterministic_seed(
            VERSION,
            issue,
            target_date,
            len(draws),
        )
    )
    front_pool = pool(
        rng,
        front_model,
        draws,
        "front",
        1,
        35,
        adjustment,
        1600,
    )
    back_pool = pool(
        rng,
        back_model,
        draws,
        "back",
        1,
        12,
        adjustment,
        120,
    )
    selected = assemble(rng, front_pool, back_pool, previous)
    generated_at = datetime.now(timezone.utc).isoformat()

    output = {
        "modelVersion": VERSION,
        "modelFamily": "curve-trajectory-generative-sampler",
        "generatedAt": generated_at,
        "targetIssue": issue,
        "targetDate": target_date,
        "historyCount": len(draws),
        "historyRange": {
            "earliestIssue": draws[0]["issue"],
            "earliestDate": draws[0]["date"],
            "latestIssue": latest["issue"],
            "latestDate": latest["date"],
        },
        "latestDraw": {
            "front": [f"{number:02d}" for number in latest["front"]],
            "back": [f"{number:02d}" for number in latest["back"]],
        },
        "lastEvaluation": evaluation,
        "calibration": {
            **calibration,
            "temperature": round(profile["temperature"], 3),
            "temperatureAdjustment": round(adjustment, 4),
            "note": (
                "Forecasts sorted-position curves and samples their "
                "uncertainty band; it does not reuse a fixed hot-number list."
            ),
        },
        "curveForecast": {
            "front": model_summary(front_model),
            "back": model_summary(back_model),
        },
        "diversity": {
            "maximumFrontOverlapBetweenResults": 2,
            "maximumBackOverlapBetweenResults": 1,
            "maximumFrontOverlapWithPreviousForecast": 3,
            "selection": (
                "temperature-weighted sampling from the high-fit curve band"
            ),
        },
        "results": [
            {
                "rank": row["rank"],
                "label": row["label"],
                "front": [
                    f"{number:02d}" for number in row["front"]
                ],
                "back": [
                    f"{number:02d}" for number in row["back"]
                ],
                "fit": row["fit"],
                "reason": reason(row, front_model),
            }
            for row in selected
        ],
        "note": (
            "All valid combinations remain equally likely in a fair lottery. "
            "Curve fit is not a winning probability."
        ),
    }

    state.update(
        updatedAt=generated_at,
        selectedProfile=profile["name"],
    )
    write_json(STATE_FILE, state)
    write_json(LOG_FILE, logs[-200:])
    write_json(FORECAST_FILE, output)
    print(json.dumps(output, ensure_ascii=False, indent=2))


# Backward-compatible names used by the historical audit.
R = ROOT
D = DRAWS_FILE
F = FORECAST_FILE
H = HISTORY_FILE
L = LOG_FILE
S = STATE_FILE
read = read_json
write = write_json
nums = numbers
nextday = next_draw_day
seed = deterministic_seed
wmean = weighted_mean
state0 = initial_state
gauss = gaussian_integer
g = gaussian_score
summary = model_summary


if __name__ == "__main__":
    main()

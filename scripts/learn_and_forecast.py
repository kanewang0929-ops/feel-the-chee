#!/usr/bin/env python3
"""Evaluate the previous forecast, update bounded adaptive state, and forecast the next DLT draw.

The pipeline is intentionally conservative. Live draw feedback can nudge a profile, but
walk-forward history remains the dominant signal. This is a pattern-fitting experiment,
not evidence that random lottery outcomes are predictable.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import generate_forecast as engine

ROOT = Path(__file__).resolve().parents[1]
DRAWS_FILE = ROOT / "data" / "draws.json"
FORECAST_FILE = ROOT / "data" / "forecast.json"
FORECAST_HISTORY_FILE = ROOT / "data" / "forecast-history.json"
LEARNING_LOG_FILE = ROOT / "data" / "learning-log.json"
MODEL_STATE_FILE = ROOT / "data" / "model-state.json"
MODEL_VERSION = "v2.1-adaptive"


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
    if isinstance(value, list):
        parts = value
    else:
        parts = str(value or "").split()
    return [f"{int(part):02d}" for part in parts]


def load_draws() -> list[dict]:
    payload = read_json(DRAWS_FILE, {})
    rows = payload if isinstance(payload, list) else payload.get("draws", [])
    cleaned = []
    for row in rows:
        try:
            normalized = {
                "issue": str(row["issue"]).strip(),
                "date": str(row["date"]).strip(),
                "front": number_list(row["front"]),
                "back": number_list(row["back"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if engine.valid_record(normalized):
            cleaned.append(normalized)
    cleaned.sort(key=lambda item: (item["date"], int(item["issue"])))
    if len(cleaned) < 1000:
        raise RuntimeError(f"Not enough valid history: {len(cleaned)}")
    return cleaned


def empty_state() -> dict:
    return {
        "version": 1,
        "updatedAt": None,
        "profiles": {"front": {}, "back": {}},
    }


def update_profile_state(state: dict, area: str, profile: str, reward: float) -> dict:
    profiles = state.setdefault("profiles", {}).setdefault(area, {})
    current = profiles.get(profile, {})
    evaluations = int(current.get("evaluations", 0)) + 1
    previous_ema = current.get("emaHitRate")
    ema = reward if previous_ema is None else 0.72 * float(previous_ema) + 0.28 * reward
    updated = {
        "evaluations": evaluations,
        "lastHitRate": round(reward, 6),
        "emaHitRate": round(ema, 6),
    }
    profiles[profile] = updated
    return updated


def evaluate_previous(previous: dict, draws: list[dict], state: dict, logs: list[dict]) -> dict | None:
    target_issue = str(previous.get("targetIssue") or "")
    if not target_issue or not previous.get("results"):
        return None
    if any(str(entry.get("issue")) == target_issue for entry in logs):
        return next((entry for entry in logs if str(entry.get("issue")) == target_issue), None)

    actual = next((draw for draw in draws if draw["issue"] == target_issue), None)
    if not actual:
        return None

    actual_front = set(actual["front"])
    actual_back = set(actual["back"])
    result_rows = []
    for result in previous.get("results", []):
        predicted_front = set(number_list(result.get("front", [])))
        predicted_back = set(number_list(result.get("back", [])))
        front_hits = sorted(actual_front.intersection(predicted_front))
        back_hits = sorted(actual_back.intersection(predicted_back))
        result_rows.append(
            {
                "rank": result.get("rank"),
                "label": result.get("label"),
                "frontHits": front_hits,
                "backHits": back_hits,
                "frontHitCount": len(front_hits),
                "backHitCount": len(back_hits),
            }
        )

    average_front_hits = statistics.fmean(row["frontHitCount"] for row in result_rows)
    average_back_hits = statistics.fmean(row["backHitCount"] for row in result_rows)
    front_reward = average_front_hits / 5.0
    back_reward = average_back_hits / 2.0

    front_profile = str(previous.get("calibration", {}).get("front", {}).get("selectedProfile") or "unknown")
    back_profile = str(previous.get("calibration", {}).get("back", {}).get("selectedProfile") or "unknown")
    front_state = update_profile_state(state, "front", front_profile, front_reward)
    back_state = update_profile_state(state, "back", back_profile, back_reward)

    evaluation = {
        "issue": target_issue,
        "date": actual["date"],
        "evaluatedAt": datetime.now(timezone.utc).isoformat(),
        "actual": {"front": actual["front"], "back": actual["back"]},
        "predictionModelVersion": previous.get("modelVersion"),
        "results": result_rows,
        "summary": {
            "averageFrontHits": round(average_front_hits, 3),
            "averageBackHits": round(average_back_hits, 3),
            "bestFrontHits": max(row["frontHitCount"] for row in result_rows),
            "bestBackHits": max(row["backHitCount"] for row in result_rows),
        },
        "learningUpdate": {
            "frontProfile": front_profile,
            "backProfile": back_profile,
            "frontReward": round(front_reward, 6),
            "backReward": round(back_reward, 6),
            "frontState": front_state,
            "backState": back_state,
            "rule": "Live feedback is an exponential moving average with a bounded influence on walk-forward selection.",
        },
    }
    logs.append(evaluation)
    return evaluation


def adaptive_walk_forward_select(
    records: list[set[int]],
    max_number: int,
    main_pick: int,
    wider_pick: int,
    state: dict,
    area: str,
) -> tuple[dict[str, float], dict]:
    start = max(450, len(records) - 180)
    test_indices = list(range(start, len(records), 2))
    evaluations = []
    random_baseline = main_pick / max_number

    for config in engine.WEIGHT_CONFIGS:
        main_hits = 0
        wider_hits = 0
        for index in test_indices:
            history = records[:index]
            actual = records[index]
            scores, _ = engine.score_numbers(history, max_number, config)
            ranked = sorted(scores, key=scores.get, reverse=True)
            main_hits += len(actual.intersection(ranked[:main_pick]))
            wider_hits += len(actual.intersection(ranked[:wider_pick]))

        average_main = main_hits / max(1, len(test_indices))
        average_wider = wider_hits / max(1, len(test_indices))
        historical_objective = average_main * 3 + average_wider

        live = state.get("profiles", {}).get(area, {}).get(config["name"], {})
        live_evaluations = int(live.get("evaluations", 0))
        live_ema = float(live.get("emaHitRate", random_baseline))
        reliability = min(1.0, 0.25 + live_evaluations / 8.0) if live_evaluations else 0.0
        adaptive_bonus = max(-0.22, min(0.22, (live_ema - random_baseline) * 0.9 * reliability))
        adjusted_objective = historical_objective + adaptive_bonus

        evaluations.append(
            {
                "config": config,
                "historicalObjective": historical_objective,
                "adjustedObjective": adjusted_objective,
                "adaptiveBonus": adaptive_bonus,
                "liveEvaluations": live_evaluations,
                "liveEmaHitRate": live_ema if live_evaluations else None,
                "averageMainHits": average_main,
                "averageWiderHits": average_wider,
                "tests": len(test_indices),
            }
        )

    winner = max(evaluations, key=lambda row: row["adjustedObjective"])
    return winner["config"], {
        "tests": winner["tests"],
        "averageMainHits": round(winner["averageMainHits"], 3),
        "averageWiderHits": round(winner["averageWiderHits"], 3),
        "historicalObjective": round(winner["historicalObjective"], 3),
        "adaptiveBonus": round(winner["adaptiveBonus"], 4),
        "objective": round(winner["adjustedObjective"], 3),
        "selectedProfile": winner["config"]["name"],
        "liveEvaluations": winner["liveEvaluations"],
        "liveEmaHitRate": None if winner["liveEmaHitRate"] is None else round(winner["liveEmaHitRate"], 4),
    }


def archive_previous(previous: dict, evaluation: dict | None) -> None:
    if not previous or not previous.get("targetIssue"):
        return
    history = read_json(FORECAST_HISTORY_FILE, [])
    if not isinstance(history, list):
        history = []
    issue = str(previous["targetIssue"])
    if any(str(item.get("targetIssue")) == issue for item in history):
        return
    snapshot = dict(previous)
    if evaluation:
        snapshot["evaluation"] = evaluation
    history.append(snapshot)
    history.sort(key=lambda item: int(item.get("targetIssue", 0)))
    write_json(FORECAST_HISTORY_FILE, history)


def main() -> None:
    draws = load_draws()
    previous = read_json(FORECAST_FILE, {})
    logs = read_json(LEARNING_LOG_FILE, [])
    if not isinstance(logs, list):
        logs = []
    state = read_json(MODEL_STATE_FILE, empty_state())
    if not isinstance(state, dict):
        state = empty_state()

    evaluation = evaluate_previous(previous, draws, state, logs)
    archive_previous(previous, evaluation)

    front_records = [set(map(int, item["front"])) for item in draws]
    back_records = [set(map(int, item["back"])) for item in draws]

    front_weights, front_test = adaptive_walk_forward_select(front_records, 35, 5, 10, state, "front")
    back_weights, back_test = adaptive_walk_forward_select(back_records, 12, 2, 5, state, "back")

    front_number_scores, _ = engine.score_numbers(front_records, 35, front_weights)
    back_number_scores, _ = engine.score_numbers(back_records, 12, back_weights)
    front_combos = engine.front_combo_scores(front_records, front_number_scores)
    back_pairs = engine.back_pair_scores(back_records, back_number_scores)
    selected = engine.select_diversified(front_combos, back_pairs)

    latest = draws[-1]
    generated_at = datetime.now(timezone.utc).isoformat()
    output = {
        "modelVersion": MODEL_VERSION,
        "generatedAt": generated_at,
        "targetIssue": str(int(latest["issue"]) + 1),
        "targetDate": engine.next_draw_day(latest["date"]),
        "historyCount": len(draws),
        "historyRange": {
            "earliestIssue": draws[0]["issue"],
            "earliestDate": draws[0]["date"],
            "latestIssue": latest["issue"],
            "latestDate": latest["date"],
        },
        "latestDraw": {"front": latest["front"], "back": latest["back"]},
        "lastEvaluation": evaluation,
        "calibration": {
            "front": front_test,
            "back": back_test,
            "frontWeights": {key: value for key, value in front_weights.items() if key != "name"},
            "backWeights": {key: value for key, value in back_weights.items() if key != "name"},
            "note": "匹配度是模型内部结构评分，不是中奖概率。实时反馈仅小幅修正，历史滚动回测仍占主导。",
        },
        "results": [
            {
                "rank": index + 1,
                "label": candidate["label"],
                "front": engine.format_numbers(candidate["front"]),
                "back": engine.format_numbers(candidate["back"]),
                "fit": candidate["fit"],
                "reason": engine.reason(candidate),
            }
            for index, candidate in enumerate(selected)
        ],
        "signals": {
            "frontTop10": engine.format_numbers(sorted(front_number_scores, key=front_number_scores.get, reverse=True)[:10]),
            "backTop6": engine.format_numbers(sorted(back_number_scores, key=back_number_scores.get, reverse=True)[:6]),
        },
    }

    state["updatedAt"] = generated_at
    write_json(MODEL_STATE_FILE, state)
    write_json(LEARNING_LOG_FILE, logs[-200:])
    write_json(FORECAST_FILE, output)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

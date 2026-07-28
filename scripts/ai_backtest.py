#!/usr/bin/env python3
"""Walk-forward audit of the AI curve model across the stored draw archive.

For every evaluated draw, the model is trained only on earlier draws. The actual
numbers are revealed after prediction for scoring. The first 500 draws are a
warm-up period and are never scored.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import curve_forecast as ai

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "data" / "ai-backtest.json"
BACKTEST_VERSION = "v1.0-walk-forward"
WARMUP_DRAWS = 500


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fmt(values) -> list[str]:
    return [f"{int(value):02d}" for value in values]


def hypergeometric_distribution(
    population: int,
    winners: int,
    picks: int,
) -> dict[str, float]:
    denominator = math.comb(population, picks)
    return {
        str(hits): (
            math.comb(winners, hits)
            * math.comb(population - winners, picks - hits)
            / denominator
        )
        for hits in range(min(winners, picks) + 1)
    }


def center_model(values) -> list[dict]:
    return [{"center": float(value)} for value in values]


def trailing_centers(history: list[dict], area: str, window: int = 60) -> list[dict]:
    sample = history[-min(window, len(history)) :]
    width = len(sample[0][area])
    return [
        {
            "center": statistics.fmean(draw[area][position] for draw in sample),
        }
        for position in range(width)
    ]


def curve_distance(front, back, actual_front, actual_back) -> float:
    front_distance = statistics.fmean(
        abs(left - right) for left, right in zip(front, actual_front)
    ) / 35
    back_distance = statistics.fmean(
        abs(left - right) for left, right in zip(back, actual_back)
    ) / 12
    return 0.72 * front_distance + 0.28 * back_distance


def forecast_for_history(
    history: list[dict],
    actual: dict,
    state: dict,
    previous: dict,
) -> tuple[dict, dict, dict]:
    profile, calibration = ai.choose(history, state)
    adjustment = float(state.get("temperatureAdjustment", 0.0))
    profile["temperature"] *= 1 + adjustment

    front_model = ai.model(history, "front", profile, 1, 35)
    back_model = ai.model(history, "back", profile, 1, 12)
    rng = ai.random.Random(
        ai.seed(
            ai.VERSION,
            actual["issue"],
            actual["date"],
            len(history),
        )
    )
    front_pool = ai.pool(
        rng,
        front_model,
        history,
        "front",
        1,
        35,
        adjustment,
        1600,
    )
    back_pool = ai.pool(
        rng,
        back_model,
        history,
        "back",
        1,
        12,
        adjustment,
        120,
    )
    chosen = ai.assemble(rng, front_pool, back_pool, previous)

    forecast = {
        "targetIssue": actual["issue"],
        "targetDate": actual["date"],
        "calibration": {
            **calibration,
            "temperature": round(profile["temperature"], 4),
            "temperatureAdjustment": round(adjustment, 4),
        },
        "curveForecast": {
            "front": ai.summary(front_model),
            "back": ai.summary(back_model),
        },
        "results": [
            {
                "rank": row["rank"],
                "label": row["label"],
                "front": fmt(row["front"]),
                "back": fmt(row["back"]),
                "fit": row["fit"],
            }
            for row in chosen
        ],
    }
    return forecast, front_model, back_model


def score_draw(
    actual: dict,
    forecast: dict,
    front_model: list[dict],
    back_model: list[dict],
    history: list[dict],
) -> dict:
    actual_front = set(actual["front"])
    actual_back = set(actual["back"])
    tickets = []

    for result in forecast["results"]:
        predicted_front = [int(number) for number in result["front"]]
        predicted_back = [int(number) for number in result["back"]]
        front_hits = sorted(actual_front & set(predicted_front))
        back_hits = sorted(actual_back & set(predicted_back))
        tickets.append(
            {
                "rank": result["rank"],
                "label": result["label"],
                "front": result["front"],
                "back": result["back"],
                "frontHits": fmt(front_hits),
                "backHits": fmt(back_hits),
                "frontHitCount": len(front_hits),
                "backHitCount": len(back_hits),
                "curveDistance": round(
                    curve_distance(
                        predicted_front,
                        predicted_back,
                        actual["front"],
                        actual["back"],
                    ),
                    6,
                ),
            }
        )

    best = max(
        tickets,
        key=lambda row: (
            row["frontHitCount"] + row["backHitCount"],
            row["frontHitCount"],
            row["backHitCount"],
            -row["curveDistance"],
        ),
    )

    model_front_loss = ai.loss(actual["front"], front_model, 35)
    model_back_loss = ai.loss(actual["back"], back_model, 12)
    model_loss = 0.72 * model_front_loss + 0.28 * model_back_loss

    persistence_front = center_model(history[-1]["front"])
    persistence_back = center_model(history[-1]["back"])
    persistence_loss = (
        0.72 * ai.loss(actual["front"], persistence_front, 35)
        + 0.28 * ai.loss(actual["back"], persistence_back, 12)
    )

    mean_front = trailing_centers(history, "front", 60)
    mean_back = trailing_centers(history, "back", 60)
    trailing_mean_loss = (
        0.72 * ai.loss(actual["front"], mean_front, 35)
        + 0.28 * ai.loss(actual["back"], mean_back, 12)
    )

    return {
        "issue": actual["issue"],
        "date": actual["date"],
        "trainingDraws": len(history),
        "actual": {
            "front": fmt(actual["front"]),
            "back": fmt(actual["back"]),
        },
        "profile": {
            "name": forecast["calibration"]["selectedProfile"],
            "label": forecast["calibration"]["selectedLabel"],
            "temperature": forecast["calibration"]["temperature"],
        },
        "curveCenters": forecast["curveForecast"],
        "curveLoss": {
            "model": round(model_loss, 6),
            "persistence": round(persistence_loss, 6),
            "trailingMean60": round(trailing_mean_loss, 6),
        },
        "tickets": tickets,
        "bestTicket": {
            "rank": best["rank"],
            "frontHitCount": best["frontHitCount"],
            "backHitCount": best["backHitCount"],
            "curveDistance": best["curveDistance"],
        },
    }


def update_simulated_state(
    forecast: dict,
    all_draws_to_actual: list[dict],
    state: dict,
) -> dict:
    event = ai.evaluate(
        forecast,
        all_draws_to_actual,
        state,
        [],
    )
    if event is None:
        raise RuntimeError(f'Could not evaluate issue {forecast["targetIssue"]}')
    return event


def aggregate(rows: list[dict]) -> dict:
    tickets = [ticket for row in rows for ticket in row["tickets"]]
    ticket_count = len(tickets)

    front_distribution = Counter(ticket["frontHitCount"] for ticket in tickets)
    back_distribution = Counter(ticket["backHitCount"] for ticket in tickets)
    pattern_distribution = Counter(
        f'{ticket["frontHitCount"]}+{ticket["backHitCount"]}'
        for ticket in tickets
    )
    best_front_distribution = Counter(
        row["bestTicket"]["frontHitCount"] for row in rows
    )
    best_back_distribution = Counter(
        row["bestTicket"]["backHitCount"] for row in rows
    )

    average_front = statistics.fmean(
        ticket["frontHitCount"] for ticket in tickets
    )
    average_back = statistics.fmean(
        ticket["backHitCount"] for ticket in tickets
    )
    average_ticket_curve_distance = statistics.fmean(
        ticket["curveDistance"] for ticket in tickets
    )

    model_curve_loss = statistics.fmean(
        row["curveLoss"]["model"] for row in rows
    )
    persistence_curve_loss = statistics.fmean(
        row["curveLoss"]["persistence"] for row in rows
    )
    trailing_mean_curve_loss = statistics.fmean(
        row["curveLoss"]["trailingMean60"] for row in rows
    )

    front_baseline = 5 * 5 / 35
    back_baseline = 2 * 2 / 12
    front_probabilities = hypergeometric_distribution(35, 5, 5)
    back_probabilities = hypergeometric_distribution(12, 2, 2)

    group_template = lambda: {
        "draws": 0,
        "tickets": 0,
        "frontHits": 0,
        "backHits": 0,
        "modelCurveLoss": 0.0,
    }
    by_year = defaultdict(group_template)
    by_profile = defaultdict(group_template)

    for row in rows:
        for group in (
            by_year[row["date"][:4]],
            by_profile[row["profile"]["label"]],
        ):
            group["draws"] += 1
            group["tickets"] += len(row["tickets"])
            group["frontHits"] += sum(
                ticket["frontHitCount"] for ticket in row["tickets"]
            )
            group["backHits"] += sum(
                ticket["backHitCount"] for ticket in row["tickets"]
            )
            group["modelCurveLoss"] += row["curveLoss"]["model"]

    def finish_groups(groups):
        output = {}
        for key, row in groups.items():
            ticket_total = max(1, row["tickets"])
            draw_total = max(1, row["draws"])
            output[key] = {
                "draws": row["draws"],
                "tickets": row["tickets"],
                "averageFrontHits": round(
                    row["frontHits"] / ticket_total,
                    4,
                ),
                "averageBackHits": round(
                    row["backHits"] / ticket_total,
                    4,
                ),
                "averageModelCurveLoss": round(
                    row["modelCurveLoss"] / draw_total,
                    6,
                ),
            }
        return output

    best_examples = sorted(
        rows,
        key=lambda row: (
            row["bestTicket"]["frontHitCount"]
            + row["bestTicket"]["backHitCount"],
            row["bestTicket"]["frontHitCount"],
            row["bestTicket"]["backHitCount"],
            -row["bestTicket"]["curveDistance"],
        ),
        reverse=True,
    )[:20]

    return {
        "drawsEvaluated": len(rows),
        "warmupDraws": WARMUP_DRAWS,
        "ticketsEvaluated": ticket_count,
        "dateRange": {
            "earliest": rows[0]["date"] if rows else None,
            "latest": rows[-1]["date"] if rows else None,
        },
        "observed": {
            "averageFrontHitsPerTicket": round(average_front, 6),
            "averageBackHitsPerTicket": round(average_back, 6),
            "averageTotalHitsPerTicket": round(
                average_front + average_back,
                6,
            ),
            "averageTicketCurveDistance": round(
                average_ticket_curve_distance,
                6,
            ),
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
            "bestOfThreeFrontDistribution": {
                str(hits): best_front_distribution[hits] for hits in range(6)
            },
            "bestOfThreeBackDistribution": {
                str(hits): best_back_distribution[hits] for hits in range(3)
            },
            "exactFivePlusTwo": pattern_distribution["5+2"],
        },
        "curveBenchmark": {
            "modelAverageLoss": round(model_curve_loss, 6),
            "persistenceAverageLoss": round(
                persistence_curve_loss,
                6,
            ),
            "trailingMean60AverageLoss": round(
                trailing_mean_curve_loss,
                6,
            ),
            "improvementVsPersistence": round(
                persistence_curve_loss - model_curve_loss,
                6,
            ),
            "improvementVsTrailingMean60": round(
                trailing_mean_curve_loss - model_curve_loss,
                6,
            ),
            "note": (
                "Lower curve loss is better. Persistence predicts the previous "
                "draw's sorted positions; trailingMean60 predicts the prior "
                "60-draw positional mean."
            ),
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
                "Exact per-ticket expectation under a fair draw. The three AI "
                "tickets are diversified, so this benchmark is used for "
                "per-ticket means and distributions, not best-of-three odds."
            ),
        },
        "comparison": {
            "frontMeanDifference": round(
                average_front - front_baseline,
                6,
            ),
            "backMeanDifference": round(
                average_back - back_baseline,
                6,
            ),
            "totalMeanDifference": round(
                average_front
                + average_back
                - front_baseline
                - back_baseline,
                6,
            ),
            "frontMeanRatio": round(
                average_front / front_baseline,
                6,
            ),
            "backMeanRatio": round(
                average_back / back_baseline,
                6,
            ),
        },
        "byYear": finish_groups(by_year),
        "byProfile": finish_groups(by_profile),
        "bestExamples": best_examples,
    }


def main() -> None:
    draws = ai.load()
    if len(draws) <= WARMUP_DRAWS:
        raise RuntimeError(
            f"Need more than {WARMUP_DRAWS} draws, found {len(draws)}"
        )

    state = ai.state0()
    previous = {"results": []}
    results = []

    for index in range(WARMUP_DRAWS, len(draws)):
        history = draws[:index]
        actual = draws[index]
        forecast, front_model, back_model = forecast_for_history(
            history,
            actual,
            state,
            previous,
        )
        scored = score_draw(
            actual,
            forecast,
            front_model,
            back_model,
            history,
        )
        event = update_simulated_state(
            forecast,
            draws[: index + 1],
            state,
        )
        scored["learningUpdate"] = event["learningUpdate"]
        results.append(scored)
        previous = forecast

        if len(results) % 100 == 0:
            print(
                f"Evaluated {len(results)} / {len(draws) - WARMUP_DRAWS} draws",
                flush=True,
            )

    output = {
        "backtestVersion": BACKTEST_VERSION,
        "modelVersion": ai.VERSION,
        "modelFamily": "curve-trajectory-generative-sampler",
        "walkForward": True,
        "futureLeakage": False,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "method": {
            "warmupDraws": WARMUP_DRAWS,
            "trainingRule": (
                "Each historical forecast uses only draws published before "
                "the target draw."
            ),
            "profileRule": (
                "Profile selection, curve fitting, temperature sampling, "
                "cross-ticket diversity, and bounded state updates mirror "
                "the live AI pipeline."
            ),
        },
        "summary": aggregate(results),
        "draws": results,
        "note": (
            "All valid lottery combinations remain equally likely in a fair "
            "draw. This audit measures historical model behaviour and does "
            "not establish future winning probability."
        ),
    }
    write_json(OUTPUT_FILE, output)
    print(
        json.dumps(
            {
                "backtestVersion": BACKTEST_VERSION,
                "modelVersion": ai.VERSION,
                "summary": output["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

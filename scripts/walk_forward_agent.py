#!/usr/bin/env python3
"""Strict no-lookahead walk-forward prediction engine for Feel the Chee.

For every historical target draw, prediction generation receives only the
chronological prefix before that draw. The prediction is written to a
prediction-only JSONL ledger before the target draw's winning numbers are read.
Only then is the result revealed, scored, and used to update the next-step state.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path

import curve_forecast as ai
import chee_formula as chee
import intuitive_agent_runtime as agent

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT_FILE = DATA / "walk-forward-agent.json"
PREDICTION_LEDGER_FILE = DATA / "walk-forward-agent-predictions.jsonl"
STATE_FILE = DATA / "walk-forward-agent-state.json"

VERSION = "v1.0-strict-walk-forward-agent"
WARMUP = int(os.environ.get("WALK_FORWARD_WARMUP", "500"))
RECALIBRATE_EVERY = 60
AUDIT_FRONT_POOL = 100
AUDIT_BACK_POOL = 25
LIVE_FRONT_POOL = 1600
LIVE_BACK_POOL = 120


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def clone(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def fmt(values) -> list[str]:
    return [f"{int(value):02d}" for value in values]


def digest_history(history: list[dict]) -> str:
    payload = [
        {
            "issue": row["issue"],
            "date": row["date"],
            "front": row["front"],
            "back": row["back"],
        }
        for row in history
    ]
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_ai_prediction(
    history: list[dict],
    target_issue: str,
    target_date: str,
    state: dict,
    profile_seed: dict,
    calibration_seed: dict,
    previous: dict | None,
    *,
    live: bool = False,
) -> tuple[dict, dict]:
    """Generate AI tickets using only history and known target metadata."""
    profile = dict(profile_seed)
    adjustment = float(state.get("temperatureAdjustment", 0.0) or 0.0)
    profile["temperature"] = float(profile["temperature"]) * (1.0 + adjustment)

    front_model = ai.model(history, "front", profile, 1, 35)
    back_model = ai.model(history, "back", profile, 1, 12)

    if live:
        million = state.get("millionSimulationTraining", {})
        if not isinstance(million, dict):
            million = {}
        relationship_training = state.get("relationshipTraining", {})
        if not isinstance(relationship_training, dict):
            relationship_training = {}
        mean_blend = float(million.get("meanAnchorBlend", 0.0) or 0.0)
        relationship_blend = float(relationship_training.get("blend", 1.0) or 1.0)
    else:
        # Historical replay starts from a clean state and uses only transitions
        # contained in the prefix before the target draw.
        mean_blend = 0.0
        relationship_blend = 1.0

    front_model = ai.apply_mean_anchor(
        front_model, history, "front", mean_blend
    )
    back_model = ai.apply_mean_anchor(
        back_model, history, "back", mean_blend
    )
    front_model = ai.apply_relationship_anchor(
        front_model, history, "front", relationship_blend, 1, 35
    )
    back_model = ai.apply_relationship_anchor(
        back_model, history, "back", relationship_blend, 1, 12
    )

    rng = random.Random(
        ai.seed(ai.VERSION, target_issue, target_date, len(history))
    )
    front_count = LIVE_FRONT_POOL if live else AUDIT_FRONT_POOL
    back_count = LIVE_BACK_POOL if live else AUDIT_BACK_POOL
    front_pool = ai.pool(
        rng, front_model, history, "front", 1, 35, adjustment, front_count
    )
    back_pool = ai.pool(
        rng, back_model, history, "back", 1, 12, adjustment, back_count
    )
    if len(front_pool) < 25 or len(back_pool) < 10:
        raise RuntimeError(
            f"Insufficient AI candidate pool for target {target_issue}: "
            f"front={len(front_pool)}, back={len(back_pool)}"
        )

    selected = ai.assemble(rng, front_pool, back_pool, previous or {"results": []})
    calibration = {
        **calibration_seed,
        "selectedProfile": profile_seed.get("name"),
        "selectedLabel": profile_seed.get("label"),
        "temperature": round(profile["temperature"], 4),
        "temperatureAdjustment": round(adjustment, 4),
        "meanAnchorBlend": round(mean_blend, 6),
        "relationshipBlend": round(relationship_blend, 6),
    }
    payload = {
        "modelVersion": ai.VERSION,
        "modelFamily": "curve-trajectory-generative-sampler",
        "targetIssue": str(target_issue),
        "targetDate": target_date,
        "historyCount": len(history),
        "calibration": calibration,
        "curveForecast": {
            "front": ai.model_summary(front_model),
            "back": ai.model_summary(back_model),
        },
        "results": [
            {
                "rank": row["rank"],
                "label": row["label"],
                "front": fmt(row["front"]),
                "back": fmt(row["back"]),
                "fit": row["fit"],
                "reason": ai.reason(row, front_model),
            }
            for row in selected
        ],
        "note": (
            "The target draw's winning numbers are not an input. "
            "Curve fit is not a winning probability."
        ),
    }
    return payload, {"front": front_model, "back": back_model}


def make_chee_prediction(target_issue: str, target_date: str) -> dict:
    """Formula-only Feng Shui result. No historical result or learned state."""
    calculation, results = chee.calculate(target_issue, target_date)
    return {
        "modelVersion": chee.VERSION,
        "formulaVersion": chee.FORMULA,
        "formulaOnly": True,
        "historyUsedForPrediction": False,
        "learningEnabled": False,
        "targetIssue": str(target_issue),
        "targetDate": target_date,
        "calculation": calculation,
        "elementStrengths": chee.element_strengths(calculation),
        "results": [
            {
                **row,
                "front": fmt(row["front"]),
                "back": fmt(row["back"]),
            }
            for row in results
        ],
    }


def score_tickets(results: list[dict], actual: dict) -> dict:
    actual_front = set(actual["front"])
    actual_back = set(actual["back"])
    tickets = []
    for position, result in enumerate(results, start=1):
        front = sorted(int(value) for value in result.get("front", []))
        back = sorted(int(value) for value in result.get("back", []))
        front_hits = sorted(actual_front & set(front))
        back_hits = sorted(actual_back & set(back))
        tickets.append(
            {
                "rank": int(result.get("rank") or position),
                "label": result.get("label"),
                "front": fmt(front),
                "back": fmt(back),
                "frontHits": fmt(front_hits),
                "backHits": fmt(back_hits),
                "frontHitCount": len(front_hits),
                "backHitCount": len(back_hits),
                "totalHitCount": len(front_hits) + len(back_hits),
            }
        )
    count = len(tickets)
    return {
        "tickets": tickets,
        "ticketsEvaluated": count,
        "averageFrontHitsPerTicket": round(
            statistics.fmean(row["frontHitCount"] for row in tickets), 6
        ) if tickets else 0.0,
        "averageBackHitsPerTicket": round(
            statistics.fmean(row["backHitCount"] for row in tickets), 6
        ) if tickets else 0.0,
        "averageTotalHitsPerTicket": round(
            statistics.fmean(row["totalHitCount"] for row in tickets), 6
        ) if tickets else 0.0,
    }


def aggregate_source(rows: list[dict], source: str) -> dict:
    tickets = [
        ticket
        for row in rows
        for ticket in row["evaluation"][source]["tickets"]
    ]
    count = len(tickets)
    return {
        "ticketsEvaluated": count,
        "averageFrontHits": round(
            statistics.fmean(row["frontHitCount"] for row in tickets), 6
        ) if tickets else 0.0,
        "averageBackHits": round(
            statistics.fmean(row["backHitCount"] for row in tickets), 6
        ) if tickets else 0.0,
        "averageTotalHits": round(
            statistics.fmean(row["totalHitCount"] for row in tickets), 6
        ) if tickets else 0.0,
    }


def optimized_live_agent_state(replay_state: dict) -> dict:
    """Use the existing million-cycle optimizer only for the next live draw.

    The historical replay always starts from agent.default_state(). Optimized
    weights are never fed backwards into an earlier historical prediction.
    """
    state = clone(replay_state)
    optimized = ai.read_json(DATA / "hybrid-model-state.json", {})
    if not isinstance(optimized, dict):
        return state

    for area in ("front", "back"):
        source_weights = optimized.get("sourceWeights", {}).get(area, {})
        if all(name in source_weights for name in agent.SOURCES):
            values = {
                name: max(0.0, float(source_weights[name]))
                for name in agent.SOURCES
            }
            total = sum(values.values())
            if total > 0:
                state["sourceWeights"][area] = {
                    name: values[name] / total for name in agent.SOURCES
                }

        strategy_weights = optimized.get("strategyWeights", {}).get(area, {})
        if all(name in strategy_weights for name in agent.CATEGORIES):
            state["strategyWeights"][area] = {
                name: max(0.0, float(strategy_weights[name]))
                for name in agent.CATEGORIES
            }

    state["liveWeightSource"] = "sequential replay plus accepted million-cycle optimization"
    return state


def main() -> None:
    draws = ai.load()
    if len(draws) <= WARMUP:
        raise RuntimeError(
            f"Need more than {WARMUP} valid draws; found {len(draws)}."
        )

    # Historical replay deliberately starts from neutral states. Existing live
    # model files and full-history optimizer weights are not read here.
    ai_state = ai.initial_state()
    agent_state = agent.default_state()
    ai_logs: list[dict] = []
    rows: list[dict] = []
    learning_curve: list[dict] = []
    previous_ai: dict = {"results": []}
    profile_seed = None
    calibration_seed = None

    PREDICTION_LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PREDICTION_LEDGER_FILE.open("w", encoding="utf-8") as ledger:
        for index in range(WARMUP, len(draws)):
            history = draws[:index]

            # The target issue/date are public scheduling metadata. The target
            # winning numbers are intentionally not read until after the
            # prediction-only event has been flushed to disk.
            target_issue = str(draws[index]["issue"])
            target_date = str(draws[index]["date"])

            if (
                profile_seed is None
                or (index - WARMUP) % RECALIBRATE_EVERY == 0
            ):
                profile_seed, calibration_seed = ai.choose(history, ai_state)

            ai_prediction, _ = make_ai_prediction(
                history,
                target_issue,
                target_date,
                ai_state,
                profile_seed,
                calibration_seed,
                previous_ai,
                live=False,
            )
            chee_prediction = make_chee_prediction(target_issue, target_date)
            agent_bundle = agent.generate_bundle(
                ai_prediction, chee_prediction, agent_state
            )
            instinct_prediction = agent_bundle["instinctInput"]
            agent_prediction = {
                "modelVersion": agent.VERSION,
                "targetIssue": target_issue,
                "targetDate": target_date,
                "results": agent_bundle["results"],
            }

            history_digest = digest_history(history)
            prediction_id = hashlib.sha256(
                f"{VERSION}|{target_issue}|{target_date}|{history_digest}".encode()
            ).hexdigest()[:24]
            locked_at = stamp()
            sealed_prediction = {
                "eventType": "prediction_locked",
                "predictionId": prediction_id,
                "modelVersion": VERSION,
                "issue": target_issue,
                "date": target_date,
                "trainingDrawCount": len(history),
                "trainingThroughIssue": history[-1]["issue"],
                "trainingThroughDate": history[-1]["date"],
                "historyDigest": history_digest,
                "predictionLockedAt": locked_at,
                "predictions": {
                    "ai": ai_prediction["results"],
                    "chee": chee_prediction["results"],
                    "instinct": instinct_prediction["results"],
                    "agent": agent_prediction["results"],
                },
                "futureLeakage": False,
            }
            ledger.write(json.dumps(sealed_prediction, ensure_ascii=False) + "\n")
            ledger.flush()
            os.fsync(ledger.fileno())

            # -------------------- RESULT REVEAL BOUNDARY --------------------
            # Only below this line may the target draw's winning numbers enter
            # scoring or model updates.
            target_draw = draws[index]
            actual = {
                "front": list(target_draw["front"]),
                "back": list(target_draw["back"]),
            }
            revealed_at = stamp()

            ai_metrics = score_tickets(ai_prediction["results"], actual)
            chee_metrics = score_tickets(chee_prediction["results"], actual)
            instinct_metrics = score_tickets(instinct_prediction["results"], actual)
            agent_evaluation = agent.evaluate_and_update(
                agent_state,
                ai_prediction["results"],
                chee_prediction["results"],
                instinct_prediction["results"],
                agent_prediction["results"],
                {"front": fmt(actual["front"]), "back": fmt(actual["back"])},
                alpha=0.035,
            )
            agent_metrics = score_tickets(agent_prediction["results"], actual)

            # AI learning is also strictly post-reveal. The current result is
            # appended to the visible prefix only for this update and later draws.
            ai_learning = ai.evaluate(
                ai_prediction,
                draws[: index + 1],
                ai_state,
                ai_logs,
            )
            if ai_learning is not None and ai_learning not in ai_logs:
                ai_logs.append(ai_learning)

            row = {
                "predictionId": prediction_id,
                "issue": target_issue,
                "date": target_date,
                "trainingDrawCount": len(history),
                "trainingThroughIssue": history[-1]["issue"],
                "trainingThroughDate": history[-1]["date"],
                "historyDigest": history_digest,
                "predictionLockedAt": locked_at,
                "actualRevealedAt": revealed_at,
                "actual": {
                    "front": fmt(actual["front"]),
                    "back": fmt(actual["back"]),
                },
                "prediction": {
                    "ai": ai_prediction["results"],
                    "chee": chee_prediction["results"],
                    "instinct": instinct_prediction["results"],
                    "agent": agent_prediction["results"],
                },
                "evaluation": {
                    "ai": ai_metrics,
                    "chee": chee_metrics,
                    "instinct": instinct_metrics,
                    "agent": agent_metrics,
                    "agentLearning": agent_evaluation,
                },
                "learningUpdate": {
                    "ai": ai_learning.get("learningUpdate") if ai_learning else None,
                    "agentWeightsBefore": agent_evaluation.get("weightsBefore"),
                    "agentWeightsAfter": agent_evaluation.get("weightsAfter"),
                },
                "futureLeakage": False,
            }
            rows.append(row)
            previous_ai = ai_prediction

            if (
                len(rows) == 1
                or len(rows) % 50 == 0
                or index == len(draws) - 1
            ):
                learning_curve.append(
                    {
                        "drawNumber": len(rows),
                        "issue": target_issue,
                        "date": target_date,
                        "sourceWeights": clone(agent_state["sourceWeights"]),
                        "strategyWeights": clone(agent_state["strategyWeights"]),
                        "averageFrontHits": round(
                            agent_state["cumulative"]["frontHits"]
                            / max(1, agent_state["cumulative"]["tickets"]),
                            6,
                        ),
                        "averageBackHits": round(
                            agent_state["cumulative"]["backHits"]
                            / max(1, agent_state["cumulative"]["tickets"]),
                            6,
                        ),
                        "observations": agent_state["observations"],
                    }
                )

            if len(rows) % 100 == 0:
                print(
                    f"Walk-forward Agent: {len(rows)}/{len(draws) - WARMUP} "
                    "draws predicted, revealed, scored, and learned.",
                    flush=True,
                )

    # The next live prediction may use the accepted million-cycle weights.
    # Those weights are applied only after the historical no-peek replay ends.
    latest = draws[-1]
    next_issue = str(int(latest["issue"]) + 1)
    next_date = ai.next_draw_day(latest["date"])

    live_ai_state = clone(ai_state)
    legacy_ai_state = ai.read_json(ai.STATE_FILE, {})
    if isinstance(legacy_ai_state, dict):
        for key in (
            "millionSimulationTraining",
            "relationshipTraining",
            "fullHistoryCycleTraining",
        ):
            if key in legacy_ai_state:
                live_ai_state[key] = legacy_ai_state[key]

    live_profile, live_calibration = ai.choose(draws, live_ai_state)
    ai_next, _ = make_ai_prediction(
        draws,
        next_issue,
        next_date,
        live_ai_state,
        live_profile,
        live_calibration,
        previous_ai,
        live=True,
    )
    ai_next["historyCount"] = len(draws)
    ai_next["historyRange"] = {
        "earliestIssue": draws[0]["issue"],
        "earliestDate": draws[0]["date"],
        "latestIssue": latest["issue"],
        "latestDate": latest["date"],
    }
    ai_next["latestDraw"] = {
        "front": fmt(latest["front"]),
        "back": fmt(latest["back"]),
    }
    ai_next["lastEvaluation"] = ({
        "issue": rows[-1]["issue"],
        "actual": rows[-1]["actual"],
        "summary": {
            "averageFrontHits": rows[-1]["evaluation"]["ai"]["averageFrontHitsPerTicket"],
            "averageBackHits": rows[-1]["evaluation"]["ai"]["averageBackHitsPerTicket"],
        },
    } if rows else None)

    chee_next = make_chee_prediction(next_issue, next_date)
    live_agent_state = optimized_live_agent_state(agent_state)
    agent_next_bundle = agent.generate_bundle(
        ai_next, chee_next, live_agent_state
    )
    agent_next = {
        "modelVersion": agent.VERSION,
        "modelFamily": "strict-walk-forward-three-source-agent",
        "targetIssue": next_issue,
        "targetDate": next_date,
        "sourceWeights": clone(live_agent_state["sourceWeights"]),
        "strategyWeights": clone(live_agent_state["strategyWeights"]),
        "observations": agent_state["observations"],
        "lastEvaluation": {
            "issue": rows[-1]["issue"],
            "actual": rows[-1]["actual"],
            "summary": {
                "averageFrontHits": rows[-1]["evaluation"]["agent"]["averageFrontHitsPerTicket"],
                "averageBackHits": rows[-1]["evaluation"]["agent"]["averageBackHitsPerTicket"],
            },
        } if rows else None,
        "sourceModels": {
            "ai": ai.VERSION,
            "chee": chee.VERSION,
            "instinct": agent_next_bundle["instinctInput"]["modelVersion"],
        },
        "results": agent_next_bundle["results"],
        "note": (
            "The Agent combines past-only AI curve signals, formula-only Feng Shui "
            "signals, and independent stochastic exploration. It does not see "
            "the target draw's winning numbers."
        ),
    }

    source_performance = {
        name: aggregate_source(rows, name)
        for name in ("ai", "chee", "instinct", "agent")
    }
    summary = {
        "drawsEvaluated": len(rows),
        "warmupDraws": WARMUP,
        "ticketsEvaluated": source_performance["agent"]["ticketsEvaluated"],
        "predictionLocks": len(rows),
        "averageFrontHitsPerTicket": source_performance["agent"]["averageFrontHits"],
        "averageBackHitsPerTicket": source_performance["agent"]["averageBackHits"],
        "averageTotalHitsPerTicket": source_performance["agent"]["averageTotalHits"],
        "observed": {
            "averageFrontHitsPerTicket": source_performance["agent"]["averageFrontHits"],
            "averageBackHitsPerTicket": source_performance["agent"]["averageBackHits"],
            "averageTotalHitsPerTicket": source_performance["agent"]["averageTotalHits"],
        },
        "agent": source_performance["agent"],
        "sourcePerformance": source_performance,
        "comparison": {"sourcePerformance": source_performance},
        "theoreticalFixedTicketBaseline": {
            "averageFrontHitsPerTicket": round(5 / 35, 6),
            "averageBackHitsPerTicket": round(2 / 12, 6),
            "averageTotalHitsPerTicket": round(5 / 35 + 2 / 12, 6),
            "note": "Expected hit counts for one uniformly random valid ticket in a fair draw.",
        },
        "dateRange": {
            "earliest": rows[0]["date"] if rows else None,
            "latest": rows[-1]["date"] if rows else None,
        },
        "futureLeakage": False,
    }

    output = {
        "modelVersion": VERSION,
        "modelFamily": "chronological-no-lookahead-prediction-agent",
        "generatedAt": stamp(),
        "walkForward": True,
        "futureLeakage": False,
        "method": {
            "warmupDraws": WARMUP,
            "profileRecalibrationInterval": RECALIBRATE_EVERY,
            "predictionOrder": [
                "read only the historical prefix before the target draw",
                "generate AI, Feng Shui, instinct, and final Agent tickets",
                "flush the prediction-only event to the pre-reveal ledger",
                "reveal the target draw's winning numbers",
                "score predictions",
                "update AI and Agent state for later draws only",
            ],
            "targetResultAccess": "The target draw's front/back numbers are accessed only after the prediction ledger is flushed.",
            "historyDigest": "SHA-256 of the exact historical prefix used for each prediction.",
            "fengShuiPolicy": "Formula-only. Uses target issue/date and never learns from historical results.",
            "liveOptimizationPolicy": "Accepted million-cycle weights may affect the next live forecast only, never earlier historical predictions.",
            "predictionLedger": "data/walk-forward-agent-predictions.jsonl",
        },
        "summary": summary,
        "learningCurve": learning_curve,
        "draws": rows,
        "nextForecast": {
            "targetIssue": next_issue,
            "targetDate": next_date,
            "historyCount": len(draws),
            "ai": ai_next,
            "chee": chee_next,
            "agent": agent_next,
            "agentState": live_agent_state,
        },
        "finalState": {
            "aiReplayState": ai_state,
            "agentReplayState": agent_state,
            "agentLiveState": live_agent_state,
        },
        "note": (
            "This is a historical walk-forward audit, not proof that a fair lottery "
            "can be predicted. All valid combinations remain equally likely in a fair draw."
        ),
    }

    write_json(STATE_FILE, output["finalState"])
    write_json(OUTPUT_FILE, output)
    print(
        json.dumps(
            {
                "modelVersion": VERSION,
                "drawsEvaluated": summary["drawsEvaluated"],
                "predictionLocks": summary["predictionLocks"],
                "averageFrontHitsPerTicket": summary["averageFrontHitsPerTicket"],
                "averageBackHitsPerTicket": summary["averageBackHitsPerTicket"],
                "nextTarget": f"{next_issue} / {next_date}",
                "futureLeakage": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

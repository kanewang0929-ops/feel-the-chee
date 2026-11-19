#!/usr/bin/env python3
"""Chronological holdout evaluation for Joy/Kane with a matched random baseline.

The archive is split after a fixed warm-up prefix. Candidate learning
configurations are compared on validation only; the selected configuration
continues from its validation state into the untouched final test. Test
outcomes may update that selected agent walk-forward, but never select or tune
the configuration being evaluated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import joy_kane_duel as duel
DRAW_FILE = ROOT / "data" / "draws.json"

# Predeclared before looking at validation or test outcomes.
CANDIDATES = (
    {"name": "baseline", "ema_rate": 0.035, "weight_sensitivity": 0.85},
    {"name": "fast_adaptation", "ema_rate": 0.070, "weight_sensitivity": 0.85},
    {"name": "conservative_adaptation", "ema_rate": 0.0175, "weight_sensitivity": 0.85},
    {"name": "high_weight_sensitivity", "ema_rate": 0.035, "weight_sensitivity": 1.20},
)
RANDOM_EXPECTED_HITS = (5 * 5 / 35) + (2 * 2 / 12)


def load_archive(path: Path = DRAW_FILE) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("draws", []) if isinstance(payload, dict) else payload
    rows = []
    seen = set()
    for row in raw:
        front = duel.parse_numbers(row.get("front"))
        back = duel.parse_numbers(row.get("back"))
        if len(front) != 5 or len(set(front)) != 5 or any(n < 1 or n > 35 for n in front):
            continue
        if len(back) != 2 or len(set(back)) != 2 or any(n < 1 or n > 12 for n in back):
            continue
        issue, draw_date = str(row.get("issue", "")), str(row.get("date", ""))
        key = (issue, draw_date)
        if not issue or not draw_date or key in seen:
            raise ValueError(f"Missing or duplicate issue/date in archive: {key}")
        seen.add(key)
        rows.append({"issue": issue, "date": draw_date, "front": sorted(front), "back": sorted(back)})
    rows.sort(key=lambda r: (r["date"], int(r["issue"] or 0)))
    if len(rows) < 10:
        raise ValueError(f"Archive is too small for holdout evaluation: {len(rows)} valid draws")
    return rows


def chronological_split(draws: list[dict], warmup: int = 200) -> dict:
    eligible = len(draws) - warmup
    if warmup < 1 or eligible < 5:
        raise ValueError(f"Need a warm-up prefix and at least five eligible draws; got {warmup} and {eligible}")
    train_count = int(eligible * 0.60)
    validation_count = int(eligible * 0.20)
    test_count = eligible - train_count - validation_count
    if min(train_count, validation_count, test_count) < 1:
        raise ValueError("Chronological split produced an empty segment")
    train_start = warmup
    validation_start = train_start + train_count
    test_start = validation_start + validation_count

    def boundary(start: int, end: int) -> dict:
        return {
            "count": end - start,
            "firstIssue": draws[start]["issue"],
            "firstDate": draws[start]["date"],
            "lastIssue": draws[end - 1]["issue"],
            "lastDate": draws[end - 1]["date"],
            "startIndex": start,
            "endIndexExclusive": end,
        }

    return {
        "warmup": boundary(0, warmup),
        "training": boundary(train_start, validation_start),
        "validation": boundary(validation_start, test_start),
        "finalTest": boundary(test_start, len(draws)),
        "counts": {
            "archiveDraws": len(draws),
            "warmupDraws": warmup,
            "eligibleDraws": eligible,
            "trainingDraws": train_count,
            "validationDraws": validation_count,
            "finalTestDraws": test_count,
        },
    }


def agent_seed(master_seed: int, name: str) -> int:
    raw = f"{master_seed}:{name}:chronological-holdout-v1".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def prediction_seed(name: str, history: list[dict], issue: str, draw_date: str, seed: int) -> int:
    material = [name, issue, draw_date, duel.digest(history), int(seed)]
    return int(duel.digest(material)[:16], 16)


def candidate_prediction(name: str, history: list[dict], state: dict, features: dict,
                         issue: str, draw_date: str, seed: int) -> tuple[list[dict], dict]:
    """Return one official ticket and signal diagnostic tickets for one agent."""
    bundles = duel.signal_ticket_bundles(name, features, history, seed, float(state["exploration"]))
    combined = {
        area: duel.weighted_scores(features[area], state["weights"][area])
        for area in duel.AREAS
    }
    rng = random.Random(seed ^ 0xD1A5E)
    picks = duel.generate_tickets(
        combined["front"], combined["back"], history, rng,
        balanced=(name == "kane"), exploration=float(state["exploration"]),
    )
    tickets = [{
        "rank": 1,
        "label": f"{name.title()} Main",
        "front": [f"{n:02d}" for n in picks[0]["front"]],
        "back": [f"{n:02d}" for n in picks[0]["back"]],
    }]
    return tickets, bundles


def update_candidate_state(state: dict, signal_hits: dict, candidate: dict) -> None:
    """Independent per-agent learning; no Joy-vs-Kane outcome drives either model."""
    alpha = float(candidate["ema_rate"])
    sensitivity = float(candidate["weight_sensitivity"])
    for area in duel.AREAS:
        for signal in duel.AGENTS[state["name"].lower()]:
            reward = float(signal_hits[area].get(signal, 0))
            old = float(state["signalEma"][area].get(signal, 0.8))
            state["signalEma"][area][signal] = (1.0 - alpha) * old + alpha * reward
        raw = {
            signal: pow(2.718281828459045, sensitivity * (state["signalEma"][area][signal] - 0.8))
            for signal in duel.AGENTS[state["name"].lower()]
        }
        state["weights"][area] = duel.normalize_weights(raw)
    state["observations"] += 1


def metric_row(scored: dict) -> dict:
    return {
        "frontHits": scored["bestFrontHits"],
        "backHits": scored["bestBackHits"],
        "totalHits": scored["bestTotalHits"],
    }


def mean_metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"draws": 0, "averageFrontHits": None, "averageBackHits": None, "averageTotalHits": None}
    return {
        "draws": len(rows),
        "averageFrontHits": round(statistics.fmean(r["frontHits"] for r in rows), 6),
        "averageBackHits": round(statistics.fmean(r["backHits"] for r in rows), 6),
        "averageTotalHits": round(statistics.fmean(r["totalHits"] for r in rows), 6),
    }


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot calculate percentile of an empty sample")
    position = (len(ordered) - 1) * pct
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def random_baseline(test_draws: list[dict], series_count: int, seed: int) -> dict:
    """Each replicate is one ticket per test draw, on the exact same dates."""
    if series_count < 100:
        raise ValueError("Use at least 100 random series for a stable comparison")
    rng = random.Random(seed)
    series_means = []
    aggregate = {"front": 0, "back": 0, "total": 0, "tickets": 0}
    for _ in range(series_count):
        front_total = back_total = 0
        for draw in test_draws:
            front = set(rng.sample(range(1, 36), 5))
            back = set(rng.sample(range(1, 13), 2))
            front_hits = len(front.intersection(draw["front"]))
            back_hits = len(back.intersection(draw["back"]))
            front_total += front_hits
            back_total += back_hits
        count = len(test_draws)
        total = front_total + back_total
        series_means.append(total / count)
        aggregate["front"] += front_total
        aggregate["back"] += back_total
        aggregate["total"] += total
        aggregate["tickets"] += count
    return {
        "seriesCount": series_count,
        "ticketsPerSeries": len(test_draws),
        "totalTickets": series_count * len(test_draws),
        "averageFrontHits": aggregate["front"] / aggregate["tickets"],
        "averageBackHits": aggregate["back"] / aggregate["tickets"],
        "averageTotalHits": aggregate["total"] / aggregate["tickets"],
        "seriesAverageTotalHitsP2_5": percentile(series_means, 0.025),
        "seriesAverageTotalHitsP97_5": percentile(series_means, 0.975),
        "seriesAverageTotalHits": series_means,
    }


def evaluate(draws: list[dict], warmup: int = 200, random_series: int = 1000,
             seed: int = 20261119) -> tuple[dict, list[dict]]:
    split = chronological_split(draws, warmup)
    train_end = split["training"]["endIndexExclusive"]
    validation_end = split["validation"]["endIndexExclusive"]
    test_start = split["finalTest"]["startIndex"]
    candidates = {name: {} for name in duel.AGENTS}
    seeds = {name: agent_seed(seed, name) for name in duel.AGENTS}

    # Candidate trajectories share the same information boundary and signal
    # diagnostics. Only the declared learning hyperparameters differ.
    states = {
        agent: {
            candidate["name"]: duel.default_state(agent)
            for candidate in CANDIDATES
        }
        for agent in duel.AGENTS
    }
    scores = {
        agent: {candidate["name"]: {"training": [], "validation": []} for candidate in CANDIDATES}
        for agent in duel.AGENTS
    }

    for index in range(warmup, validation_end):
        history = draws[:index]
        target = draws[index]
        actual = {"front": target["front"], "back": target["back"]}
        for agent in duel.AGENTS:
            features = {area: duel.number_signals(history, area) for area in duel.AREAS}
            seed_for_draw = prediction_seed(agent, history, target["issue"], target["date"], seeds[agent])
            # Bundles are candidate-independent and are generated once per agent/draw.
            shared_bundles = duel.signal_ticket_bundles(
                agent, features, history, seed_for_draw, 0.08
            )
            signal_hits = duel.score_signal_bundles(shared_bundles, actual)
            for candidate in CANDIDATES:
                name = candidate["name"]
                state = states[agent][name]
                combined = {
                    area: duel.weighted_scores(features[area], state["weights"][area])
                    for area in duel.AREAS
                }
                rng = random.Random(seed_for_draw ^ 0xD1A5E)
                picks = duel.generate_tickets(
                    combined["front"], combined["back"], history, rng,
                    balanced=(agent == "kane"), exploration=float(state["exploration"]),
                )
                ticket = [{
                    "rank": 1,
                    "label": f"{agent.title()} Main",
                    "front": [f"{n:02d}" for n in picks[0]["front"]],
                    "back": [f"{n:02d}" for n in picks[0]["back"]],
                }]
                scored = duel.score_tickets(ticket, actual)
                segment = "training" if index < train_end else "validation"
                scores[agent][name][segment].append(metric_row(scored))
                update_candidate_state(state, signal_hits, candidate)

    selected = {}
    validation_report = {}
    for agent in duel.AGENTS:
        ranked = []
        for candidate in CANDIDATES:
            name = candidate["name"]
            metrics = mean_metrics(scores[agent][name]["validation"])
            ranked.append((metrics["averageTotalHits"], metrics["averageFrontHits"], metrics["averageBackHits"], name))
            validation_report.setdefault(agent, {})[name] = {
                "training": mean_metrics(scores[agent][name]["training"]),
                "validation": metrics,
            }
        # Fixed candidate order is the final tie-breaker, declared before evaluation.
        best = max(ranked, key=lambda row: (row[0], row[1], row[2], -[c["name"] for c in CANDIDATES].index(row[3])))
        selected[agent] = best[3]

    # Only the validation winner for each agent crosses the boundary into test.
    test_rows = draws[test_start:]
    test_metrics = {agent: [] for agent in duel.AGENTS}
    trace = []
    selected_states = {agent: states[agent][selected[agent]] for agent in duel.AGENTS}
    for index in range(test_start, len(draws)):
        history = draws[:index]
        target = draws[index]
        actual = {"front": target["front"], "back": target["back"]}
        trace_row = {"issue": target["issue"], "date": target["date"], "actual": {
            "front": [f"{n:02d}" for n in target["front"]],
            "back": [f"{n:02d}" for n in target["back"]],
        }}
        for agent in duel.AGENTS:
            state = selected_states[agent]
            features = {area: duel.number_signals(history, area) for area in duel.AREAS}
            seed_for_draw = prediction_seed(agent, history, target["issue"], target["date"], seeds[agent])
            tickets, bundles = candidate_prediction(
                agent, history, state, features, target["issue"], target["date"], seed_for_draw
            )
            scored = duel.score_tickets(tickets, actual)
            row = metric_row(scored)
            test_metrics[agent].append(row)
            signal_hits = duel.score_signal_bundles(bundles, actual)
            trace_row[agent] = {"ticket": tickets[0], "score": row}
            update_candidate_state(state, signal_hits, next(c for c in CANDIDATES if c["name"] == selected[agent]))
        trace.append(trace_row)

    baseline = random_baseline(test_rows, random_series, seed ^ 0x5A17B453)
    baseline_means = baseline.pop("seriesAverageTotalHits")
    comparisons = {}
    for agent in duel.AGENTS:
        observed = mean_metrics(test_metrics[agent])
        exceedances = sum(value >= observed["averageTotalHits"] for value in baseline_means)
        comparisons[agent] = {
            "selectedConfiguration": selected[agent],
            "finalTest": observed,
            "matchedRandomBaseline": {
                **{k: v for k, v in baseline.items() if k not in ("seriesAverageTotalHitsP2_5", "seriesAverageTotalHitsP97_5")},
                "averageTotalHitsP2_5": baseline["seriesAverageTotalHitsP2_5"],
                "averageTotalHitsP97_5": baseline["seriesAverageTotalHitsP97_5"],
            },
            "differenceVsRandomMean": round(observed["averageTotalHits"] - baseline["averageTotalHits"], 6),
            "empiricalOneSidedPValue": round((exceedances + 1) / (random_series + 1), 6),
            "randomSeriesAtOrAboveAgent": exceedances,
        }

    archive_digest = hashlib.sha256(
        json.dumps(draws, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    report = {
        "evaluationVersion": "chronological-holdout-v1",
        "masterSeed": seed,
        "archive": {
            "path": str(DRAW_FILE.relative_to(ROOT)),
            "validDrawCount": len(draws),
            "normalizedArchiveSha256": archive_digest,
        },
        "split": split,
        "candidateConfigurations": list(CANDIDATES),
        "validationSelection": validation_report,
        "selectedConfigurations": selected,
        "finalTestComparisons": comparisons,
        "randomBaseline": {
            "seriesCount": random_series,
            "ticketsPerSeries": len(test_rows),
            "totalTickets": random_series * len(test_rows),
            "theoreticalExpectedTotalHitsPerTicket": round(RANDOM_EXPECTED_HITS, 9),
            "interpretation": "Empirical interval is the 2.5th to 97.5th percentile of matched random-series average scores on the exact final-test draw dates.",
        },
        "protocol": {
            "chronologicalOnly": True,
            "shuffle": False,
            "validationOnlyCandidateSelection": True,
            "finalTestUsedForSelection": False,
            "testWalkForwardLearning": True,
            "agentLearningIndependent": True,
            "oneOfficialTicketPerAgentPerDraw": True,
            "randomBaselineMatchedDatesAndTicketCount": True,
            "randomBaselineOneTicketPerDraw": True,
        },
        "limitations": [
            "Lottery draws are designed to be independent; historical patterns do not establish an edge on future draws.",
            "The random interval describes random-ticket variation conditional on these historical test dates, not uncertainty over all possible future draw sequences.",
            "The empirical p-value is a diagnostic against the matched random-ticket distribution, not proof of a persistent predictive advantage.",
        ],
    }
    return report, trace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warmup", type=int, default=200)
    parser.add_argument("--random-series", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261119)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "holdout-artifacts")
    args = parser.parse_args()
    draws = load_archive()
    report, trace = evaluate(draws, args.warmup, args.random_series, args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "holdout-evaluation-summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (args.output_dir / "holdout-final-test-trace.jsonl").open("w", encoding="utf-8") as handle:
        for row in trace:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({
        "summary": str(args.output_dir / "holdout-evaluation-summary.json"),
        "trace": str(args.output_dir / "holdout-final-test-trace.jsonl"),
        "split": report["split"]["counts"],
        "selectedConfigurations": report["selectedConfigurations"],
        "finalTestComparisons": {
            agent: report["finalTestComparisons"][agent] for agent in duel.AGENTS
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

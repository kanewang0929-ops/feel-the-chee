#!/usr/bin/env python3
"""Joy and Kane: independent, strict walk-forward lottery prediction agents.

Each historical prediction is generated from the chronological prefix only,
flushed to a prediction-only ledger, and only then scored against the revealed
draw. Joy and Kane keep separate learned states. Their daily one-million-cycle
search tunes signal weights using exact historical hit counts, never curve-fit
or pattern bonuses.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DRAW_FILE = DATA / "draws.json"
DASHBOARD_FILE = DATA / "joy-kane-dashboard.json"
AUDIT_FILE = DATA / "joy-kane-audit.json"
PREDICTION_LEDGER = DATA / "joy-kane-predictions.jsonl"
RESULT_LEDGER = DATA / "joy-kane-results.jsonl"
STATE_FILE = DATA / "joy-kane-model-state.json"
LIVE_LOCK_FILE = DATA / "joy-kane-live-lock.json"
TRAINING_LOG = DATA / "joy-kane-training-log.jsonl"

WARMUP = max(100, int(os.environ.get("DUEL_WARMUP_DRAWS", "200")))
CYCLES = max(1, int(os.environ.get("DUEL_CYCLES", "1000000")))
MIN_HOURS = max(0.0, float(os.environ.get("MIN_HOURS_BETWEEN_DUEL_TRAINING", "23")))
PICK_COUNT = 3
JOY_SIGNALS = ("curve", "transition", "frequency", "recency")
KANE_SIGNALS = ("frequency", "interval", "deviation", "distribution", "overdue")
AGENTS = {"joy": JOY_SIGNALS, "kane": KANE_SIGNALS}
AREAS = ("front", "back")
LIMITS = {"front": (1, 35, 5), "back": (1, 12, 2)}


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def append_jsonl(handle, payload) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def clone(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_numbers(value) -> list[int]:
    if isinstance(value, list):
        return [int(x) for x in value]
    return [int(x) for x in str(value or "").replace(",", " ").split()]


def load_draws() -> list[dict]:
    payload = read_json(DRAW_FILE, {})
    raw = payload.get("draws", []) if isinstance(payload, dict) else payload
    draws = []
    for row in raw:
        front, back = parse_numbers(row.get("front")), parse_numbers(row.get("back"))
        if len(front) != 5 or len(set(front)) != 5 or not all(1 <= n <= 35 for n in front):
            continue
        if len(back) != 2 or len(set(back)) != 2 or not all(1 <= n <= 12 for n in back):
            continue
        draws.append({
            "issue": str(row.get("issue", "")),
            "date": str(row.get("date", "")),
            "front": sorted(front),
            "back": sorted(back),
        })
    draws.sort(key=lambda row: (row["date"], int(row["issue"] or 0)))
    if len(draws) <= WARMUP:
        raise RuntimeError(f"Need more than {WARMUP} valid draws, found {len(draws)}.")
    return draws


def normalize_map(values: dict[int, float], low: int, high: int) -> dict[int, float]:
    vals = [float(values.get(n, 0.0)) for n in range(low, high + 1)]
    minimum, maximum = min(vals), max(vals)
    if maximum - minimum < 1e-12:
        return {n: 0.5 for n in range(low, high + 1)}
    return {n: (float(values.get(n, 0.0)) - minimum) / (maximum - minimum) for n in range(low, high + 1)}


def number_signals(history: list[dict], area: str) -> dict[str, dict[int, float]]:
    low, high, per_draw = LIMITS[area]
    window = history[-200:]
    recent = history[-40:]
    width = high - low + 1
    counts = {n: 0.0 for n in range(low, high + 1)}
    recent_counts = {n: 0.0 for n in range(low, high + 1)}
    decay_counts = {n: 0.0 for n in range(low, high + 1)}
    positions = {n: [] for n in range(low, high + 1)}

    for index, draw in enumerate(window):
        values = sorted(draw[area])
        for n in values:
            counts[n] += 1.0
            positions[n].append(index)
    for index, draw in enumerate(recent):
        age = len(recent) - 1 - index
        for n in draw[area]:
            recent_counts[n] += 1.0
            decay_counts[n] += 0.94 ** age

    expected = max(1e-9, len(window) * per_draw / width)
    frequency = {n: counts[n] / max(1, len(window)) for n in counts}
    recency = {n: decay_counts[n] for n in counts}
    deviation = {n: max(0.0, 1.0 - counts[n] / expected) for n in counts}
    interval, overdue, distribution = {}, {}, {}
    for n in range(low, high + 1):
        seen = positions[n]
        gap = (len(window) - 1 - seen[-1]) if seen else len(window)
        gaps = [seen[i] - seen[i - 1] for i in range(1, len(seen))]
        avg_gap = statistics.fmean(gaps) if gaps else max(1.0, len(window) / max(1, counts[n] + 1))
        p75 = sorted(gaps)[min(len(gaps) - 1, int(0.75 * (len(gaps) - 1)))] if gaps else avg_gap
        interval_ratio = min(3.0, gap / max(1.0, avg_gap))
        p75_ratio = min(3.0, gap / max(1.0, p75))
        interval[n] = interval_ratio
        overdue[n] = 0.55 * (p75_ratio / 3.0) + 0.45 * deviation[n]

        # Four-block evenness is a descriptive distribution signal only.
        bins = [0, 0, 0, 0]
        for pos in seen:
            bins[min(3, int(4 * pos / max(1, len(window))))] += 1
        if sum(bins) <= 1:
            distribution[n] = 0.0
        else:
            mean = statistics.fmean(bins)
            cv = statistics.pstdev(bins) / mean if mean else 1.0
            distribution[n] = 1.0 / (1.0 + cv)

    # Sorted-position curve: reward closeness to historical order-statistic centres.
    curve_raw = {n: 0.0 for n in counts}
    if window:
        sorted_rows = [sorted(row[area]) for row in window]
        centres = [
            statistics.fmean(row[position] for row in sorted_rows)
            for position in range(per_draw)
        ]
        for n in curve_raw:
            distances = [abs(n - centre) for centre in centres]
            curve_raw[n] = max(math.exp(-0.5 * (distance / max(2.0, width / (per_draw * 1.8))) ** 2) for distance in distances)

    # Transition signal: numbers that followed a historically similar prior draw.
    transition_raw = {n: 0.0 for n in counts}
    if len(history) >= 2:
        latest = set(history[-1][area])
        for index in range(1, len(history)):
            previous = set(history[index - 1][area])
            similarity = len(previous & latest) / max(1, per_draw)
            if similarity <= 0:
                continue
            for n in history[index][area]:
                transition_raw[n] += similarity

    return {
        "frequency": normalize_map(frequency, low, high),
        "recency": normalize_map(recency, low, high),
        "curve": normalize_map(curve_raw, low, high),
        "transition": normalize_map(transition_raw, low, high),
        "interval": normalize_map(interval, low, high),
        "deviation": normalize_map(deviation, low, high),
        "distribution": normalize_map(distribution, low, high),
        "overdue": normalize_map(overdue, low, high),
    }


def default_state(name: str) -> dict:
    signals = AGENTS[name]
    equal = {signal: 1.0 / len(signals) for signal in signals}
    return {
        "name": name.title(),
        "modelVersion": f"{name}-adaptive-hit-model-v1",
        "observations": 0,
        "weights": {area: dict(equal) for area in AREAS},
        "signalEma": {area: {signal: 0.8 for signal in signals} for area in AREAS},
        "exploration": 0.08,
        "duel": {"wins": 0, "losses": 0, "ties": 0, "opponentScoreTotal": 0.0},
        "updatedAt": None,
    }


def weighted_scores(signals: dict[str, dict[int, float]], weights: dict[str, float]) -> dict[int, float]:
    total = sum(max(0.0, float(weights.get(name, 0.0))) for name in signals) or 1.0
    numbers = next(iter(signals.values())).keys()
    return {
        n: sum(max(0.0, float(weights.get(name, 0.0))) * values[n] for name, values in signals.items()) / total
        for n in numbers
    }


def weighted_sample(rng: random.Random, scores: dict[int, float], count: int, pool_size: int, excluded: set[int], pool: list[int] | None = None, exploration: float = 0.08) -> list[int]:
    candidates = [n for n in (pool or [n for n, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:pool_size]]) if n not in excluded]
    if len(candidates) < count:
        candidates = [n for n in scores if n not in excluded]
    selected = []
    for _ in range(count):
        available = [n for n in candidates if n not in selected]
        if not available:
            break
        power = 2.2 - 1.4 * min(0.20, max(0.0, exploration))
        weights = [0.02 + max(0.0, scores[n]) ** power for n in available]
        pick = rng.choices(available, weights=weights, k=1)[0]
        selected.append(pick)
    return sorted(selected)


def balance_cost(front: list[int], back: list[int], target_sum: float) -> float:
    odd_front = sum(n % 2 for n in front)
    low_front = sum(n <= 18 for n in front)
    front_sum = sum(front)
    odd_back = sum(n % 2 for n in back)
    low_back = sum(n <= 6 for n in back)
    return (
        abs(odd_front - 2.5) * 1.0
        + abs(low_front - 2.5) * 0.8
        + abs(front_sum - target_sum) / 35.0
        + abs(odd_back - 1.0) * 0.5
        + abs(low_back - 1.0) * 0.5
    )


def generate_tickets(
    front_scores: dict[int, float],
    back_scores: dict[int, float],
    history: list[dict],
    rng: random.Random,
    *,
    balanced: bool,
    exploration: float = 0.08,
) -> list[dict]:
    tickets = []
    historical_sums = [sum(row["front"]) for row in history[-200:]]
    target_sum = statistics.fmean(historical_sums) if historical_sums else 90.0
    front_pool = [n for n, _ in sorted(front_scores.items(), key=lambda item: item[1], reverse=True)[:20]]
    back_pool = [n for n, _ in sorted(back_scores.items(), key=lambda item: item[1], reverse=True)[:8]]
    for _ in range(PICK_COUNT):
        candidates = []
        for _attempt in range(40 if balanced else 12):
            front = weighted_sample(rng, front_scores, 5, 20, set(), front_pool, exploration)
            back = weighted_sample(rng, back_scores, 2, 8, set(), back_pool, exploration)
            if len(front) != 5 or len(back) != 2:
                continue
            cost = balance_cost(front, back, target_sum) if balanced else 0.0
            signal = sum(front_scores[n] for n in front) + sum(back_scores[n] for n in back)
            tie_noise = rng.random() * 0.03
            candidates.append((cost - signal * 0.08 + tie_noise, front, back))
        if not candidates:
            raise RuntimeError("Unable to generate a valid ticket.")
        _, front, back = min(candidates, key=lambda row: row[0])
        tickets.append({"front": front, "back": back})
    return tickets


def signal_ticket_bundles(name: str, feature_maps: dict, history: list[dict], seed: int, exploration: float) -> dict:
    output = {}
    for index, signal in enumerate(AGENTS[name]):
        rng = random.Random(seed ^ ((index + 1) * 0x9E3779B1))
        output[signal] = generate_tickets(
            feature_maps["front"][signal],
            feature_maps["back"][signal],
            history,
            rng,
            balanced=(name == "kane"),
            exploration=exploration,
        )
    return output


def make_agent_prediction(name: str, history: list[dict], state: dict, target_issue: str, target_date: str):
    features = {area: number_signals(history, area) for area in AREAS}
    seed = int(digest([name, target_issue, target_date, digest(history)])[:16], 16)
    exploration = float(state.get("exploration", 0.08) or 0.08)
    signal_bundles = signal_ticket_bundles(name, features, history, seed, exploration)
    combined = {
        area: weighted_scores(features[area], state["weights"][area])
        for area in AREAS
    }
    rng = random.Random(seed ^ 0xD1A5E)
    picks = generate_tickets(
        combined["front"], combined["back"], history, rng, balanced=(name == "kane"), exploration=exploration
    )
    results = [
        {
            "rank": index + 1,
            "label": f"{name.title()} {'Main' if index == 0 else 'Alternative ' + str(index)}",
            "front": [f"{n:02d}" for n in ticket["front"]],
            "back": [f"{n:02d}" for n in ticket["back"]],
        }
        for index, ticket in enumerate(picks)
    ]
    return {
        "modelVersion": state["modelVersion"],
        "targetIssue": str(target_issue),
        "targetDate": target_date,
        "results": results,
    }, signal_bundles


def score_tickets(tickets: list[dict], actual: dict) -> dict:
    actual_front, actual_back = set(actual["front"]), set(actual["back"])
    scored = []
    for index, ticket in enumerate(tickets, start=1):
        front = sorted(int(n) for n in ticket["front"])
        back = sorted(int(n) for n in ticket["back"])
        front_hits = sorted(actual_front & set(front))
        back_hits = sorted(actual_back & set(back))
        scored.append({
            "rank": int(ticket.get("rank", index)),
            "label": ticket.get("label", f"Pick {index}"),
            "front": [f"{n:02d}" for n in front],
            "back": [f"{n:02d}" for n in back],
            "frontHits": [f"{n:02d}" for n in front_hits],
            "backHits": [f"{n:02d}" for n in back_hits],
            "frontHitCount": len(front_hits),
            "backHitCount": len(back_hits),
            "totalHitCount": len(front_hits) + len(back_hits),
        })
    best = max(scored, key=lambda row: (row["totalHitCount"], row["frontHitCount"], row["backHitCount"], -row["rank"]))
    return {
        "tickets": scored,
        "best": best,
        "bestFrontHits": best["frontHitCount"],
        "bestBackHits": best["backHitCount"],
        "bestTotalHits": best["totalHitCount"],
    }


def score_signal_bundles(bundles: dict, actual: dict) -> dict:
    output = {"front": {}, "back": {}}
    for signal, tickets in bundles.items():
        scored = score_tickets(tickets, actual)
        output["front"][signal] = scored["bestFrontHits"]
        output["back"][signal] = scored["bestBackHits"]
    return output


def normalize_weights(values: dict[str, float]) -> dict[str, float]:
    safe = {name: max(0.001, float(value)) for name, value in values.items()}
    total = sum(safe.values()) or 1.0
    return {name: safe[name] / total for name in safe}


def update_state(state: dict, signal_hits: dict, opponent_best: int, own_best: int) -> dict:
    before = clone(state["weights"])
    for area in AREAS:
        for signal in AGENTS[state["name"].lower()]:
            reward = float(signal_hits[area].get(signal, 0))
            old = float(state["signalEma"][area].get(signal, 0.8))
            state["signalEma"][area][signal] = 0.965 * old + 0.035 * reward
        raw = {
            signal: math.exp(0.85 * (state["signalEma"][area][signal] - 0.8))
            for signal in AGENTS[state["name"].lower()]
        }
        state["weights"][area] = normalize_weights(raw)

    if own_best > opponent_best:
        state["duel"]["wins"] += 1
        state["exploration"] = max(0.02, state["exploration"] * 0.995)
    elif own_best < opponent_best:
        state["duel"]["losses"] += 1
        state["exploration"] = min(0.20, state["exploration"] + 0.001)
    else:
        state["duel"]["ties"] += 1
    state["duel"]["opponentScoreTotal"] += float(opponent_best)
    state["observations"] += 1
    state["updatedAt"] = stamp()
    return {"weightsBefore": before, "weightsAfter": clone(state["weights"]), "explorationAfter": state["exploration"]}


def means_for(rows: list[dict], agent_name: str) -> dict:
    signals = AGENTS[agent_name]
    output = {area: {signal: 0.0 for signal in signals} for area in AREAS}
    if not rows:
        return output
    for row in rows:
        for area in AREAS:
            for signal in signals:
                output[area][signal] += float(row[agent_name][area].get(signal, 0))
    for area in AREAS:
        for signal in signals:
            output[area][signal] /= len(rows)
    return output


def weight_score(weights: dict, means: dict) -> float:
    return sum(
        float(weights[area].get(signal, 0.0)) * float(means[area].get(signal, 0.0))
        for area in AREAS for signal in means[area]
    )


def perturb_weights(current: dict, rng: random.Random, sigma: float) -> dict:
    return {
        area: normalize_weights({
            signal: max(0.001, float(current[area][signal]) * math.exp(rng.gauss(0.0, sigma)))
            for signal in current[area]
        })
        for area in AREAS
    }


def train_agent(name: str, state: dict, samples: list[dict], rng: random.Random) -> dict:
    if len(samples) < 30:
        return {"cycles": 0, "accepted": False, "reason": "Insufficient walk-forward samples."}
    n = len(samples)
    train_end = max(20, int(n * 0.70))
    validation_end = max(train_end + 5, int(n * 0.90))
    train_rows = samples[:train_end]
    validation_rows = samples[train_end:validation_end]
    test_rows = samples[validation_end:]
    train_means = means_for(train_rows, name)
    validation_means = means_for(validation_rows, name)
    test_means = means_for(test_rows, name)
    current = clone(state["weights"])
    before_train = weight_score(current, train_means)
    before_validation = weight_score(current, validation_means)
    before_test = weight_score(current, test_means)

    champion = clone(current)
    champion_train, champion_validation = before_train, before_validation
    accepted_trials = 0
    for index in range(CYCLES):
        progress = index / max(1, CYCLES - 1)
        sigma = 0.20 * (1.0 - progress) + 0.004
        candidate = perturb_weights(champion, rng, sigma)
        train_score = weight_score(candidate, train_means)
        validation_score = weight_score(candidate, validation_means)
        if (
            validation_score > champion_validation + 1e-12
            or (abs(validation_score - champion_validation) <= 1e-12 and train_score > champion_train + 1e-12)
        ):
            champion = candidate
            champion_train = train_score
            champion_validation = validation_score
            accepted_trials += 1

    accepted = champion_validation > before_validation + 1e-9 and champion_train >= before_train - 0.02
    final = champion if accepted else current
    after_train = weight_score(final, train_means)
    after_validation = weight_score(final, validation_means)
    after_test = weight_score(final, test_means)
    if accepted:
        state["weights"] = clone(final)
    state["dailyTraining"] = {
        "cyclesPerRun": CYCLES,
        "accepted": accepted,
        "acceptedTrials": accepted_trials,
        "trainScoreBefore": round(before_train, 6),
        "trainScoreAfter": round(after_train, 6),
        "validationScoreBefore": round(before_validation, 6),
        "validationScoreAfter": round(after_validation, 6),
        "untouchedTestScoreBefore": round(before_test, 6),
        "untouchedTestScoreAfter": round(after_test, 6),
        "trainingDraws": len(train_rows),
        "validationDraws": len(validation_rows),
        "untouchedTestDraws": len(test_rows),
        "objective": "weighted average of exact front/back hits from each signal's best historical ticket; no curve-fit, frequency, overdue, balance, or pattern bonus is added to hit score",
        "updatedAt": stamp(),
    }
    return clone(state["dailyTraining"])


def latest_training_age(logs: list[dict]) -> float | None:
    if not logs:
        return None
    value = logs[-1].get("generatedAt")
    try:
        then = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - then).total_seconds() / 3600.0)
    except (TypeError, ValueError):
        return None


def next_target(latest_draw: dict) -> tuple[str, str]:
    last_date = date.fromisoformat(latest_draw["date"])
    target = last_date + timedelta(days=1)
    while target.weekday() not in (0, 2, 5):
        target += timedelta(days=1)
    last_issue = latest_draw["issue"]
    year = int(last_issue[:2])
    sequence = int(last_issue[2:])
    target_year = target.year % 100
    if target_year != year:
        sequence = 0
    return f"{target_year:02d}{sequence + 1:03d}", target.isoformat()


def main() -> None:
    draws = load_draws()
    metadata = [{"issue": row["issue"], "date": row["date"]} for row in draws]
    outcomes = [{"front": row["front"], "back": row["back"]} for row in draws]
    states = {name: default_state(name) for name in AGENTS}
    samples: list[dict] = []
    audit_rows: list[dict] = []
    win_counts = {"joy": 0, "kane": 0, "tie": 0}
    score_totals = {
        name: {"front": 0, "back": 0, "total": 0, "draws": 0}
        for name in AGENTS
    }
    prior_live_lock = read_json(LIVE_LOCK_FILE, {})

    PREDICTION_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with PREDICTION_LEDGER.open("w", encoding="utf-8") as prediction_log, RESULT_LEDGER.open("w", encoding="utf-8") as result_log:
        for index in range(WARMUP, len(draws)):
            history = draws[:index]
            target_meta = metadata[index]
            issue, target_date = target_meta["issue"], target_meta["date"]

            history_hash = digest([
                {"issue": row["issue"], "date": row["date"], "front": row["front"], "back": row["back"]}
                for row in history
            ])
            use_live_lock = (
                prior_live_lock.get("issue") == issue
                and prior_live_lock.get("date") == target_date
                and prior_live_lock.get("historyDigest") == history_hash
                and isinstance(prior_live_lock.get("agents"), dict)
            )

            if use_live_lock:
                joy_prediction = clone(prior_live_lock["agents"]["joy"]["prediction"])
                kane_prediction = clone(prior_live_lock["agents"]["kane"]["prediction"])
                joy_signals = clone(prior_live_lock["agents"]["joy"]["signalBundles"])
                kane_signals = clone(prior_live_lock["agents"]["kane"]["signalBundles"])
                prediction_id = prior_live_lock["predictionId"]
                locked_at = prior_live_lock["predictionLockedAt"]
                sealed_agents = {
                    name: {
                        "modelVersion": prior_live_lock["agents"][name]["modelVersion"],
                        "weights": prior_live_lock["agents"][name]["weights"],
                        "tickets": prior_live_lock["agents"][name]["prediction"]["results"],
                    }
                    for name in AGENTS
                }
            else:
                joy_prediction, joy_signals = make_agent_prediction("joy", history, states["joy"], issue, target_date)
                kane_prediction, kane_signals = make_agent_prediction("kane", history, states["kane"], issue, target_date)
                prediction_id = digest(["joy-kane-v1", issue, target_date, history_hash])[:24]
                locked_at = stamp()
                sealed_agents = {
                    "joy": {"modelVersion": joy_prediction["modelVersion"], "weights": clone(states["joy"]["weights"]), "tickets": joy_prediction["results"]},
                    "kane": {"modelVersion": kane_prediction["modelVersion"], "weights": clone(states["kane"]["weights"]), "tickets": kane_prediction["results"]},
                }

            sealed = {
                "eventType": "prediction_locked",
                "predictionId": prediction_id,
                "issue": issue,
                "date": target_date,
                "trainingDrawCount": len(history),
                "trainingThroughIssue": history[-1]["issue"],
                "trainingThroughDate": history[-1]["date"],
                "historyDigest": history_hash,
                "predictionLockedAt": locked_at,
                "livePredictionLock": use_live_lock,
                "agents": sealed_agents,
                "futureLeakage": False,
            }
            append_jsonl(prediction_log, sealed)

            # The target outcome is deliberately accessed only after the prediction-only
            # event is flushed. Prediction functions receive no target outcome object.
            actual = outcomes[index]
            revealed_at = stamp()
            joy_metrics = score_tickets(joy_prediction["results"], actual)
            kane_metrics = score_tickets(kane_prediction["results"], actual)
            joy_best, kane_best = joy_metrics["bestTotalHits"], kane_metrics["bestTotalHits"]
            joy_rank = (joy_metrics["bestTotalHits"], joy_metrics["bestFrontHits"], joy_metrics["bestBackHits"])
            kane_rank = (kane_metrics["bestTotalHits"], kane_metrics["bestFrontHits"], kane_metrics["bestBackHits"])
            if joy_rank > kane_rank:
                winner = "joy"
                win_counts["joy"] += 1
            elif kane_rank > joy_rank:
                winner = "kane"
                win_counts["kane"] += 1
            else:
                winner = "tie"
                win_counts["tie"] += 1

            joy_signal_hits = score_signal_bundles(joy_signals, actual)
            kane_signal_hits = score_signal_bundles(kane_signals, actual)
            sample = {"joy": joy_signal_hits, "kane": kane_signal_hits}
            samples.append(sample)

            joy_update = update_state(states["joy"], joy_signal_hits, kane_best, joy_best)
            kane_update = update_state(states["kane"], kane_signal_hits, joy_best, kane_best)

            for name, metrics in (("joy", joy_metrics), ("kane", kane_metrics)):
                score_totals[name]["front"] += metrics["bestFrontHits"]
                score_totals[name]["back"] += metrics["bestBackHits"]
                score_totals[name]["total"] += metrics["bestTotalHits"]
                score_totals[name]["draws"] += 1

            result_event = {
                "eventType": "result_scored",
                "predictionId": prediction_id,
                "issue": issue,
                "date": target_date,
                "actual": {"front": [f"{n:02d}" for n in actual["front"]], "back": [f"{n:02d}" for n in actual["back"]]},
                "joy": joy_metrics,
                "kane": kane_metrics,
                "winner": winner,
                "learning": {"joy": joy_update, "kane": kane_update},
                "signalHits": sample,
                "predictionLockedAt": locked_at,
                "actualRevealedAt": revealed_at,
                "futureLeakage": False,
            }
            append_jsonl(result_log, result_event)

            audit_rows.append({
                "issue": issue,
                "date": target_date,
                "actual": result_event["actual"],
                "joy": joy_metrics,
                "kane": kane_metrics,
                "winner": winner,
                "predictionId": prediction_id,
                "predictionLockedAt": locked_at,
                "actualRevealedAt": revealed_at,
                "trainingThroughIssue": history[-1]["issue"],
                "futureLeakage": False,
                "usedLivePredictionLock": use_live_lock,
            })

    # The final historical replay state is a clean chronological state.
    # Daily optimizer weights are applied only to the next live forecast.
    existing_state = read_json(STATE_FILE, {})
    training_logs = []
    if TRAINING_LOG.exists():
        for line in TRAINING_LOG.read_text(encoding="utf-8").splitlines():
            try:
                training_logs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    age = latest_training_age(training_logs)
    should_train = age is None or age >= MIN_HOURS or os.environ.get("FORCE_DUEL_TRAINING") == "1"
    training_results = {}
    if should_train:
        run_stamp = stamp()
        for name in AGENTS:
            seed = int(digest([name, run_stamp, len(draws)])[:16], 16)
            training_results[name] = train_agent(name, states[name], samples, random.Random(seed))
        training_event = {
            "eventType": "daily_million_cycle_training",
            "generatedAt": run_stamp,
            "cyclesPerAgent": CYCLES,
            "agents": training_results,
            "rule": "Each agent searches one million independent signal-weight candidates. The objective is based only on exact historical front/back hit counts. Historical sealed predictions are not rewritten.",
        }
        with TRAINING_LOG.open("a", encoding="utf-8") as handle:
            append_jsonl(handle, training_event)
    else:
        for name in AGENTS:
            prior = existing_state.get("agents", {}).get(name, {})
            optimized = prior.get("optimizedWeights")
            if isinstance(optimized, dict):
                states[name]["weights"] = clone(optimized)
            training_results[name] = {
                **(prior.get("dailyTraining") or {}),
                "skipped": True,
                "reason": f"Daily million-cycle search already ran {age:.1f} hours ago.",
            }

    # Keep the upcoming draw's prediction immutable until its result is published.
    latest_draw = draws[-1]
    target_issue, target_date = next_target(latest_draw)
    live_history_hash = digest([
        {"issue": row["issue"], "date": row["date"], "front": row["front"], "back": row["back"]}
        for row in draws
    ])
    reuse_live_lock = (
        prior_live_lock.get("issue") == target_issue
        and prior_live_lock.get("date") == target_date
        and prior_live_lock.get("historyDigest") == live_history_hash
        and isinstance(prior_live_lock.get("agents"), dict)
    )
    if reuse_live_lock:
        live_lock = clone(prior_live_lock)
    else:
        live_agents = {}
        for name in AGENTS:
            prediction, signal_bundles = make_agent_prediction(name, draws, states[name], target_issue, target_date)
            live_agents[name] = {
                "modelVersion": prediction["modelVersion"],
                "weights": clone(states[name]["weights"]),
                "prediction": prediction,
                "signalBundles": signal_bundles,
            }
        live_lock = {
            "eventType": "prediction_locked",
            "predictionId": digest(["joy-kane-v1", target_issue, target_date, live_history_hash])[:24],
            "issue": target_issue,
            "date": target_date,
            "trainingDrawCount": len(draws),
            "trainingThroughIssue": latest_draw["issue"],
            "trainingThroughDate": latest_draw["date"],
            "historyDigest": live_history_hash,
            "predictionLockedAt": stamp(),
            "agents": live_agents,
            "futureLeakage": False,
        }

    next_forecasts = {
        name: clone(live_lock["agents"][name]["prediction"])
        for name in AGENTS
    }
    write_json(LIVE_LOCK_FILE, live_lock)
    with PREDICTION_LEDGER.open("a", encoding="utf-8") as prediction_log:
        append_jsonl(prediction_log, {
            "eventType": "prediction_locked",
            "predictionId": live_lock["predictionId"],
            "issue": live_lock["issue"],
            "date": live_lock["date"],
            "trainingDrawCount": live_lock["trainingDrawCount"],
            "trainingThroughIssue": live_lock["trainingThroughIssue"],
            "trainingThroughDate": live_lock["trainingThroughDate"],
            "historyDigest": live_lock["historyDigest"],
            "predictionLockedAt": live_lock["predictionLockedAt"],
            "livePredictionLock": True,
            "agents": {
                name: {
                    "modelVersion": live_lock["agents"][name]["modelVersion"],
                    "weights": live_lock["agents"][name]["weights"],
                    "tickets": live_lock["agents"][name]["prediction"]["results"],
                }
                for name in AGENTS
            },
            "futureLeakage": False,
        })

    def averages(name):
        row = score_totals[name]
        count = max(1, row["draws"])
        return {
            "draws": row["draws"],
            "averageBestFrontHits": round(row["front"] / count, 6),
            "averageBestBackHits": round(row["back"] / count, 6),
            "averageBestTotalHits": round(row["total"] / count, 6),
        }

    summary = {
        "drawsEvaluated": len(audit_rows),
        "warmupDraws": WARMUP,
        "dateRange": {"earliest": audit_rows[0]["date"] if audit_rows else None, "latest": audit_rows[-1]["date"] if audit_rows else None},
        "joy": averages("joy"),
        "kane": averages("kane"),
        "duelWins": win_counts,
        "scoreDefinition": "Per draw, each agent is scored by its single closest ticket: exact front matches plus exact back matches. Ties are broken by front hits, then back hits. No pattern, balance, frequency, overdue, or model-fit bonus is added.",
        "randomTicketBaseline": {
            "expectedFrontHits": round(25 / 35, 6),
            "expectedBackHits": round(4 / 12, 6),
            "expectedTotalHits": round(25 / 35 + 4 / 12, 6),
        },
    }
    state_payload = {
        "modelVersion": "v1.0-joy-kane-duel",
        "generatedAt": stamp(),
        "walkForward": True,
        "futureLeakage": False,
        "agents": {
            name: {
                **states[name],
                "optimizedWeights": clone(states[name]["weights"]),
                "dailyTraining": training_results[name],
            }
            for name in AGENTS
        },
        "crossLearning": "Agents compare their best-ticket hit counts after each reveal. Their model weights remain independent; each adjusts its own exploration rate from the head-to-head outcome.",
        "livePredictionLock": {"issue": live_lock["issue"], "date": live_lock["date"], "predictionId": live_lock["predictionId"], "lockedAt": live_lock["predictionLockedAt"]},
    }
    write_json(STATE_FILE, state_payload)

    dashboard = {
        "modelVersion": "v1.0-joy-kane-duel",
        "generatedAt": stamp(),
        "walkForward": True,
        "futureLeakage": False,
        "method": {
            "warmupDraws": WARMUP,
            "predictionOrder": [
                "read only the chronological prefix before the target draw",
                "generate Joy and Kane predictions from independent model states",
                "flush both sealed predictions to the prediction-only ledger",
                "reveal the target draw",
                "score each agent by its closest ticket using exact matches only",
                "update each agent and record the head-to-head result",
            ],
            "joySignals": list(JOY_SIGNALS),
            "kaneSignals": list(KANE_SIGNALS),
            "kaneMethod": "200-draw frequency, interval tracking, deviation from expected frequency, four-block distribution balance, and overdue interval signals; balanced ticket construction is a candidate-generation heuristic only.",
            "overdueCaveat": "Overdue is a historical absence description, not a probability increase. In a fair independent draw, a number's next-draw probability does not rise because it has been absent.",
            "scoreDefinition": summary["scoreDefinition"],
            "predictionLedger": "data/joy-kane-predictions.jsonl",
            "resultLedger": "data/joy-kane-results.jsonl",
            "liveLock": "data/joy-kane-live-lock.json",
            "auditFile": "data/joy-kane-audit.json",
            "dailyTraining": {
                "cyclesPerAgent": CYCLES if should_train else 0,
                "ranToday": should_train,
                "minimumHoursBetweenRuns": MIN_HOURS,
                "objective": "Exact best-ticket front plus back hit counts only.",
            },
        },
        "summary": summary,
        "nextForecast": {
            "targetIssue": target_issue,
            "targetDate": target_date,
            "historyCount": len(draws),
            "joy": next_forecasts["joy"],
            "kane": next_forecasts["kane"],
        },
        "agentStates": {
            name: {
                "observations": states[name]["observations"],
                "weights": states[name]["weights"],
                "duel": states[name]["duel"],
                "exploration": states[name]["exploration"],
                "dailyTraining": training_results[name],
            }
            for name in AGENTS
        },
        "livePredictionLock": {"issue": live_lock["issue"], "date": live_lock["date"], "predictionId": live_lock["predictionId"], "lockedAt": live_lock["predictionLockedAt"]},
        "audit": {"file": "data/joy-kane-audit.json", "rows": len(audit_rows)},
    }
    write_json(DASHBOARD_FILE, dashboard)
    write_json(AUDIT_FILE, {
        "modelVersion": dashboard["modelVersion"],
        "generatedAt": dashboard["generatedAt"],
        "futureLeakage": False,
        "rows": audit_rows,
    })
    print(json.dumps({
        "modelVersion": dashboard["modelVersion"],
        "drawsEvaluated": len(audit_rows),
        "warmupDraws": WARMUP,
        "targetIssue": target_issue,
        "targetDate": target_date,
        "dailyTrainingRan": should_train,
        "cyclesPerAgent": CYCLES if should_train else 0,
        "summary": summary,
        "dashboardBytes": DASHBOARD_FILE.stat().st_size,
        "auditBytes": AUDIT_FILE.stat().st_size,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

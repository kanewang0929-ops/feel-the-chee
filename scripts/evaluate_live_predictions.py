#!/usr/bin/env python3
"""Read-only evaluation of previously sealed live predictions. Never train or predict."""
from __future__ import annotations

import argparse
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

if __package__:
    from . import joy_kane_live as live, quantum_models as models, quantum_protocol as protocol
else:
    import joy_kane_live as live
    import quantum_models as models
    import quantum_protocol as protocol

REPORT_NAME = "joy-kane-live-evaluation.json"
SCOPE = "sealed_live_predictions_only"
EXPECTED = 25 / 35 + 4 / 12
UNIFORM_NLL = math.log(math.comb(35, 5) * math.comb(12, 2))
WINDOWS = (10, 30, 100)


def hypergeom(size: int, picks: int) -> np.ndarray:
    return np.array([math.comb(picks, hits) * math.comb(size - picks, picks - hits)
                     / math.comb(size, picks) for hits in range(picks + 1)])


@lru_cache(maxsize=32)
def null_distribution(draw_count: int) -> np.ndarray:
    """Distribution of summed hits under independent, fair front/back draws.

    The conditional hit distribution is identical for every pre-draw ticket,
    even when its selection adapts to previous draws. Do not pool the agents:
    they are scored against the same actual draws.
    """
    single = np.convolve(hypergeom(35, 5), hypergeom(12, 2))
    result = np.array([1.0])
    for _ in range(draw_count):
        result = np.convolve(result, single)
    return result / result.sum()


def chance_reference(draw_count: int, total_hits: int) -> dict | None:
    if not draw_count:
        return None
    if type(total_hits) is not int or not 0 <= total_hits <= 7 * draw_count:
        raise ValueError("Invalid total hits for chance reference.")
    pmf = null_distribution(draw_count)
    cdf = np.cumsum(pmf)
    lower = int(np.searchsorted(cdf, .025))
    upper = int(np.searchsorted(cdf, .975))
    return {"expectedTotalHits": draw_count * EXPECTED,
            "meanReference95": [lower / draw_count, upper / draw_count],
            "oneSidedTailAtLeastObserved": min(1.0, float(pmf[total_hits:].sum()))}


def identity(lock: dict) -> dict:
    return {"engineDigest": lock.get("engineDigest"),
            "versions": {name: lock["agents"][name]["modelVersion"] for name in protocol.AGENTS}}


def current_identity() -> dict:
    return {"engineDigest": protocol.engine_digest(),
            "versions": {name: protocol.MODEL_VERSION for name in protocol.AGENTS}}


def likelihood(lock: dict, name: str, actual: dict) -> float | None:
    agent = lock["agents"][name]
    if agent["modelVersion"] != protocol.MODEL_VERSION:
        # Legacy weights and unknown future model families are not probabilities.
        return None
    state = agent.get("state")
    if not isinstance(state, dict) or protocol.digest(state) != agent.get("stateDigest"):
        raise ValueError("A quantum prediction's sealed state digest is invalid.")
    probabilities = agent.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != {"front", "back"}:
        raise ValueError("A quantum prediction has no sealed probability distribution.")
    total = 0.0
    for area, size in (("front", 35), ("back", 12)):
        weights = probabilities[area]
        if (not isinstance(weights, list) or len(weights) != size
                or any(type(p) not in (int, float) or not math.isfinite(p) or p <= 0 for p in weights)
                or not math.isclose(sum(weights), 1.0, rel_tol=1e-9, abs_tol=1e-9)):
            raise ValueError("Invalid sealed quantum probability vector.")
        # Verify the distributions for the installed engine. Older engine
        # digests retain their original stored vectors without reinterpretation.
        if lock.get("engineDigest") == protocol.engine_digest():
            models.validate_state(state)
            if state["name"] != name or state["observations"] != lock["trainingDrawCount"]:
                raise ValueError("Quantum state provenance disagrees with the sealed prediction.")
            expected = models.distribution(state, area)
            if not np.allclose(weights, expected, rtol=1e-9, atol=1e-12):
                raise ValueError("Sealed probabilities disagree with the sealed quantum state.")
        total -= models.ticket_log_probability(weights, actual[area])
    if not math.isfinite(total):
        raise ValueError("Nonfinite sealed ticket likelihood.")
    return total


def parameter_shift(previous: dict | None, current: dict, name: str) -> float | None:
    """RMS wrapped angular difference between successive scored snapshots.

    This is not a gradient norm or a training trajectory: independently seeded
    replay batches can produce different parameters.
    """
    if previous is None or identity(previous) != identity(current):
        return None
    a, b = (lock["agents"][name] for lock in (previous, current))
    if a["modelVersion"] != protocol.MODEL_VERSION:
        return None
    if a.get("stateDigest") == b.get("stateDigest"):
        return 0.0
    av, bv = (agent["state"]["parameters"] for agent in (a, b))
    differences = []
    for area in ("front", "back"):
        if len(av[area]) != len(bv[area]):
            return None
        differences.extend(math.remainder(x - y, 2 * math.pi) for x, y in zip(bv[area], av[area]))
    return math.sqrt(sum(x * x for x in differences) / len(differences)) if differences else None


def agent_metrics(rows: list[dict], name: str) -> dict:
    n = len(rows)
    values = [row["agents"][name] for row in rows]
    sums = {area: sum(v[area + "Hits"] for v in values) for area in ("front", "back", "total")}
    nlls = [v["negativeLogLikelihood"] for v in values if v["negativeLogLikelihood"] is not None]
    shifts = [v["parameterShiftRmsRadians"] for v in values if v["parameterShiftRmsRadians"] is not None]
    return {"drawCount": n, "totalHits": sums["total"],
            "meanFrontHits": sums["front"] / n if n else None,
            "meanBackHits": sums["back"] / n if n else None,
            "meanTotalHits": sums["total"] / n if n else None,
            "deltaVsRandom": sums["total"] / n - EXPECTED if n else None,
            "chanceReference": chance_reference(n, sums["total"]),
            "nllDrawCount": len(nlls), "meanNegativeLogLikelihood": sum(nlls) / len(nlls) if nlls else None,
            "lastParameterShiftRmsRadians": shifts[-1] if shifts else None,
            "parameterComparisons": len(shifts),
            "rolling": {str(w): {"drawCount": w, "meanTotalHits": sum(
                v["totalHits"] for v in values[-w:]) / w} if n >= w else None for w in WINDOWS}}


def build_report(data_dir: Path) -> dict:
    """Read and revalidate the authoritative ledger; do not mutate any input."""
    data = Path(data_dir)
    draws = protocol.load_archive(data / "draws.json")
    with (data / live.LEDGER_NAME).open("rb") as handle:
        events = live._read_ledger(handle)
    if not events:
        raise ValueError("The live ledger has not been initialized.")
    ledger = live._replay_ledger(events, draws)
    dashboard = live._read_json(data / "joy-kane-dashboard.json")
    archive = protocol.archive_metadata(draws)
    coverage = dashboard["dataCoverage"]
    summary = dashboard["summary"]
    active = ledger["active"]
    lock_metadata = dashboard["livePredictionLock"]
    if (coverage["archiveSha256"] != archive["sha256"]
            or coverage["validDrawCount"] != archive["validDrawCount"]
            or summary["scope"] != "live_predictions_only"
            or summary["drawsEvaluated"] != len(ledger["scored"])
            or summary["missingPredictions"] != len(ledger["missing"])
            or (lock_metadata or {}).get("predictionId") != (active or {}).get("predictionId")):
        raise ValueError("The live dashboard and verified ledger are not from the same publication.")
    current = current_identity()
    groups = {}
    previous = {}
    def group_for(info: dict) -> dict:
        key = protocol.digest(info)
        if key not in groups:
            groups[key] = {"id": key, "identity": info, "isCurrent": info == current,
                           "rows": [], "wins": {"joy": 0, "kane": 0, "tie": 0}}
        return groups[key]
    group_for(current)
    if active:
        group_for(identity(active))
    for event in ledger["scored"]:
        lock = ledger["locks"][event["predictionId"]]
        group = group_for(identity(lock))
        key = group["id"]
        if event["winner"] != live._winner(event):
            raise ValueError("Ledger winner does not match recorded hits.")
        row = {"issue": event["actual"]["issue"], "date": event["actual"]["date"],
               "actual": event["actual"], "predictionId": event["predictionId"],
               "sealedAt": lock["predictionLockedAt"], "resultRecordedAt": event["recordedAt"],
               "batchId": lock.get("batchId"), "winner": event["winner"], "agents": {}}
        for name in protocol.AGENTS:
            score = event[name]
            row["agents"][name] = {
                "ticket": {area: score["best"][area] for area in ("front", "back")},
                "frontHits": score["bestFrontHits"], "backHits": score["bestBackHits"],
                "totalHits": score["bestTotalHits"],
                "negativeLogLikelihood": likelihood(lock, name, event["actual"]),
                "parameterShiftRmsRadians": parameter_shift(previous.get(key), lock, name)}
        group["rows"].append(row)
        group["wins"][event["winner"]] += 1
        previous[key] = lock
    for group in groups.values():
        rows = group["rows"]
        group["drawCount"] = len(rows)
        group["agents"] = {name: agent_metrics(rows, name) for name in protocol.AGENTS}
    pending = None if active is None else {"issue": active["issue"], "date": active["date"],
        "predictionId": active["predictionId"], "cohortId": protocol.digest(identity(active)),
        "sealedAt": active["predictionLockedAt"]}
    return {"schemaVersion": 1, "scope": SCOPE, "status": "available",
            "generatedAt": dashboard["generatedAt"], "archive": archive,
            "source": {"ledgerEventCount": len(events), "lastEventHash": events[-1]["eventHash"]},
            "baseline": {"meanFrontHits": 25 / 35, "meanBackHits": 4 / 12,
                         "meanTotalHits": EXPECTED, "negativeLogLikelihood": UNIFORM_NLL},
            "scoredDrawCount": len(ledger["scored"]), "missingDrawCount": len(ledger["missing"]),
            "missingPredictions": [{"issue": e["actual"]["issue"], "date": e["actual"]["date"],
                                    "reason": e["reason"]} for e in ledger["missing"]],
            "pending": pending, "currentCohortId": protocol.digest(current), "cohorts": list(groups.values()),
            "interpretation": "Exact fixed-sample fair-draw reference, descriptive only. Repeated looks and historical replays are not independent confirmation."}


def publish(data_dir: Path) -> dict:
    data = Path(data_dir)
    try:
        report = build_report(data)
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError) as error:
        # An evaluation-specific failure must never silently retain old metrics
        # or change the prediction gate. Publish an explicit unavailable report.
        print(f"Evaluation unavailable: {error}")
        report = {"schemaVersion": 1, "scope": SCOPE, "status": "unavailable",
                  "reason": "Ledger evaluation or publication consistency check failed."}
    live._write_json(data / REPORT_NAME, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=live.ROOT / "data")
    args = parser.parse_args()
    report = publish(args.data_dir)
    print(f"Live evaluation: {report['status']}")


if __name__ == "__main__":
    main()

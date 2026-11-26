#!/usr/bin/env python3
"""Settle sealed predictions and publish inference from a verified 100-cycle batch.

The append-only live ledger is authoritative. This module never trains a model.
Materialized JSON files can be rebuilt after a crash without rerolling a ticket.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

if __package__:
    from . import quantum_models as models
    from . import quantum_protocol as protocol
else:
    import quantum_models as models
    import quantum_protocol as protocol


ROOT = Path(__file__).resolve().parents[1]
LEDGER_NAME = "joy-kane-live-ledger.jsonl"
LOCK_NAME = "joy-kane-live-lock.json"
GENESIS = "0" * 64
PUBLICATION_TIMEZONE = ZoneInfo("Asia/Shanghai")
# National Sports Lottery notice: sales close at 21:00 from issue 23001,
# before the 21:25 draw. The previous sales deadline was 20:00.
CUTOFF_SOURCE = "https://m.lottery.gov.cn/xxgk/tzggz/20221220/10027143.html"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def publication_deadline(target_date: str) -> datetime:
    day = date.fromisoformat(target_date)
    hour = 21 if day >= date(2023, 1, 1) else 20
    return datetime.combine(day, time(hour), tzinfo=PUBLICATION_TIMEZONE)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Prediction timestamps must include a timezone.")
    return parsed


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _write_json(path: Path, payload) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _validate_lock(lock: dict) -> None:
    if not isinstance(lock, dict) or not isinstance(lock.get("predictionId"), str) or not lock["predictionId"]:
        raise ValueError("The live prediction lock has no valid identity.")
    protocol.normalize_draw({"issue": lock.get("issue"), "date": lock.get("date"),
                             "front": [1, 2, 3, 4, 5], "back": [1, 2]})
    locked_at = _timestamp(lock.get("predictionLockedAt"))
    if locked_at >= publication_deadline(lock["date"]):
        raise ValueError("A prediction must be sealed before the target draw's sales-close deadline.")
    if not isinstance(lock.get("historyDigest"), str) or len(lock["historyDigest"]) != 64:
        raise ValueError("The live prediction lock has no archive digest.")
    if type(lock.get("trainingDrawCount")) is not int or lock["trainingDrawCount"] < 1:
        raise ValueError("The live prediction lock has no valid training cutoff.")
    agents = lock.get("agents")
    if not isinstance(agents, dict) or set(agents) != set(protocol.AGENTS):
        raise ValueError("A live lock must contain exactly Joy and Kane.")
    for name in protocol.AGENTS:
        agent = agents[name]
        prediction = agent.get("prediction") if isinstance(agent, dict) else None
        if not isinstance(prediction, dict) or prediction.get("targetIssue") != lock["issue"] or prediction.get("targetDate") != lock["date"]:
            raise ValueError(f"{name.title()}'s locked prediction targets a different draw.")
        if not agent.get("modelVersion") or prediction.get("modelVersion") != agent["modelVersion"]:
            raise ValueError(f"{name.title()}'s locked model provenance is inconsistent.")
        tickets = prediction.get("results")
        if not isinstance(tickets, list) or len(tickets) != 1:
            raise ValueError("Each agent must have exactly one sealed ticket.")
        protocol.validate_ticket(tickets[0])


def _lock_prefix(lock: dict, draws: list[dict]) -> list[dict]:
    _validate_lock(lock)
    count = lock["trainingDrawCount"]
    if count > len(draws):
        raise ValueError("The archive is older than the sealed prediction's training cutoff.")
    prefix = draws[:count]
    if (protocol.digest(prefix) != lock["historyDigest"]
            or prefix[-1]["issue"] != lock.get("trainingThroughIssue")
            or prefix[-1]["date"] != lock.get("trainingThroughDate")
            or prefix[-1]["date"] >= lock["date"]):
        raise ValueError("The sealed prediction's historical archive has changed or its cutoff is invalid.")
    return prefix


def _read_ledger(handle) -> list[dict]:
    handle.seek(0)
    raw = handle.read()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("The live ledger has an incomplete final write; publication is blocked pending recovery.")
    events, previous = [], GENESIS
    for number, line in enumerate(raw.splitlines(), 1):
        try:
            event = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"The live ledger contains an invalid record at line {number}.") from error
        if not isinstance(event, dict):
            raise ValueError("The live ledger contains a non-object record.")
        unsigned = {key: value for key, value in event.items() if key != "eventHash"}
        if (event.get("schemaVersion") != 1 or event.get("sequence") != number
                or event.get("previousEventHash") != previous
                or event.get("eventHash") != protocol.digest(unsigned)):
            raise ValueError(f"The live ledger hash chain is invalid at line {number}.")
        _timestamp(event.get("recordedAt"))
        previous = event["eventHash"]
        events.append(event)
    return events


def _append_event(handle, events: list[dict], payload: dict, recorded_at: str) -> dict:
    event = {"schemaVersion": 1, "sequence": len(events) + 1,
             "previousEventHash": events[-1]["eventHash"] if events else GENESIS,
             "recordedAt": recorded_at, **payload}
    event["eventHash"] = protocol.digest(event)
    encoded = (json.dumps(event, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    handle.seek(0, os.SEEK_END)
    handle.write(encoded)
    handle.flush()
    os.fsync(handle.fileno())
    events.append(event)
    return event


def _replay_ledger(events: list[dict], draws: list[dict]) -> dict:
    state = {"active": None, "locks": {}, "outcomes": {}, "scored": [], "missing": [], "baseline": None}
    if not events:
        return state
    baseline = events[0].get("baselineArchive")
    count = baseline.get("validDrawCount") if isinstance(baseline, dict) else None
    if type(count) is not int or count < 1 or count > len(draws) or protocol.archive_metadata(draws[:count]) != baseline:
        raise ValueError("The live ledger's original archive boundary no longer matches the verified archive.")
    state["baseline"] = baseline
    archive_by_issue = {row["issue"]: row for row in draws}
    last_outcome_date = None
    for event in events:
        kind = event.get("eventType")
        if kind == "prediction_locked":
            lock = event.get("lock")
            _lock_prefix(lock, draws)
            if _timestamp(event["recordedAt"]) < _timestamp(lock["predictionLockedAt"]):
                raise ValueError("A ledger import cannot precede the prediction's sealing timestamp.")
            if state["active"] is not None or lock["predictionId"] in state["locks"]:
                raise ValueError("The live ledger contains overlapping or duplicate predictions.")
            if lock["issue"] in state["outcomes"]:
                raise ValueError("A live prediction was recorded after its target result.")
            if last_outcome_date and lock["date"] <= last_outcome_date:
                raise ValueError("A live prediction targets an already observed historical draw.")
            state["locks"][lock["predictionId"]] = lock
            state["active"] = lock
        elif kind in ("result_scored", "no_prior_prediction"):
            actual = protocol.normalize_draw(event.get("actual"))
            if archive_by_issue.get(actual["issue"]) != actual:
                raise ValueError("A recorded live outcome disagrees with the verified archive.")
            if actual["issue"] in state["outcomes"] or (last_outcome_date and actual["date"] <= last_outcome_date):
                raise ValueError("The live ledger contains duplicate or out-of-order outcomes.")
            if kind == "result_scored":
                lock = state["active"]
                if (lock is None or event.get("predictionId") != lock["predictionId"]
                        or (actual["issue"], actual["date"]) != (lock["issue"], lock["date"])):
                    raise ValueError("A recorded score has no matching previously sealed prediction.")
                if event.get("predictionLockedAt") != lock["predictionLockedAt"] or _timestamp(event["recordedAt"]) < _timestamp(lock["predictionLockedAt"]):
                    raise ValueError("A recorded result does not follow its original sealed prediction.")
                for name in protocol.AGENTS:
                    if event.get(name) != protocol.score_ticket(lock["agents"][name]["prediction"]["results"][0], actual):
                        raise ValueError("A recorded score does not match its sealed ticket.")
                state["scored"].append(event)
                state["active"] = None
            else:
                if state["active"] and actual["date"] >= state["active"]["date"]:
                    raise ValueError("A missing-prediction record bypasses an unresolved sealed prediction.")
                state["missing"].append(event)
            state["outcomes"][actual["issue"]] = event
            last_outcome_date = actual["date"]
        else:
            raise ValueError(f"Unknown live-ledger event type: {kind}.")
    return state


def _reconcile_lock(path: Path, disk_lock: dict | None, ledger: dict) -> None:
    if disk_lock is not None:
        _validate_lock(disk_lock)
        recorded = ledger["locks"].get(disk_lock["predictionId"])
        if recorded is None or protocol.digest(recorded) != protocol.digest(disk_lock):
            raise ValueError("The lock file conflicts with the authoritative live ledger.")
    active = ledger["active"]
    if active is not None and disk_lock != active:
        # Restore a durable event after a crash between ledger append and JSON publication.
        _write_json(path, active)


def _package_status(path: Path | None, draws: list[dict]) -> tuple[dict | None, dict]:
    if path is None or not path.exists():
        return None, {"status": "missing", "reason": "Waiting for a completed 100-cycle model package."}
    try:
        package = protocol.validate_package(_read_json(path), draws)
    except protocol.PackageValidationError as error:
        return None, {"status": "stale" if error.code in ("stale_archive", "engine_mismatch") else "invalid",
                      "reason": str(error), "code": error.code}
    except (OSError, ValueError, TypeError, KeyError) as error:
        return None, {"status": "invalid", "reason": f"The batch model package could not be validated: {error}"}
    batch = package["batch"]
    metadata = {"status": "ready", "reason": "The full 100-cycle batch matches the latest archive and engine.",
                "packageId": protocol.digest(package), **{key: batch[key] for key in (
                    "id", "cycleCount", "completedCycles", "selectedCycle", "selectionPolicy")},
                **{key: package[key] for key in ("modelVersion", "engineVersion", "engineDigest", "generatedAt", "archive")},
                "agents": {name: {key: package["agents"][name].get(key) for key in (
                    "name", "modelVersion", "modelFamily", "backend", "observations")} for name in protocol.AGENTS}}
    return package, metadata


def _new_lock(package: dict, draws: list[dict], recorded_at: str) -> dict:
    issue, target_date = protocol.next_target(draws[-1])
    package_id = protocol.digest(package)
    agents = {}
    for name in protocol.AGENTS:
        state = copy.deepcopy(package["agents"][name])
        before = protocol.digest(state)
        seed = int(protocol.digest([package_id, name, issue, target_date])[:16], 16)
        prediction, probabilities = models.make_prediction(name, state, issue, target_date, seed)
        if protocol.digest(state) != before:
            raise ValueError("Live inference unexpectedly changed a model's trained state.")
        agents[name] = {"modelVersion": state["modelVersion"], "modelFamily": state["modelFamily"],
                        "prediction": prediction, "probabilities": probabilities,
                        "state": state, "seed": seed, "stateDigest": before}
    lock = {"eventType": "prediction_locked", "modelVersion": protocol.MODEL_VERSION,
            "predictionId": protocol.digest(["joy-kane-live-v2", issue, target_date, package_id])[:24],
            "issue": issue, "date": target_date, "predictionLockedAt": recorded_at,
            "trainingDrawCount": len(draws), "trainingThroughIssue": draws[-1]["issue"],
            "trainingThroughDate": draws[-1]["date"], "historyDigest": protocol.digest(draws),
            "batchId": package["batch"]["id"], "packageId": package_id,
            "engineDigest": package["engineDigest"], "trainingBatch": copy.deepcopy(package["batch"]),
            "agents": agents, "futureLeakage": False}
    _validate_lock(lock)
    return lock


def _winner(scores: dict) -> str:
    key = lambda name: tuple(scores[name][field] for field in ("bestTotalHits", "bestFrontHits", "bestBackHits"))
    return "joy" if key("joy") > key("kane") else "kane" if key("kane") > key("joy") else "tie"


def _export(data: Path, draws: list[dict], ledger: dict, gate: dict, trained_batch: dict, now: str) -> dict:
    active, scored = ledger["active"], ledger["scored"]
    wins = {"joy": 0, "kane": 0, "tie": 0}
    for event in scored:
        wins[event["winner"]] += 1
    summary = {"scope": "live_predictions_only", "drawsEvaluated": len(scored),
               "missingPredictions": len(ledger["missing"]), "warmupDraws": protocol.WARMUP_DRAWS,
               "dateRange": {"earliest": scored[0]["actual"]["date"] if scored else None,
                             "latest": scored[-1]["actual"]["date"] if scored else None},
               "duelWins": wins,
               "scoreDefinition": "Exact front matches plus exact back matches for each agent's single previously sealed live ticket.",
               "randomTicketBaseline": {"expectedFrontHits": 25 / 35, "expectedBackHits": 4 / 12,
                                        "expectedTotalHits": 25 / 35 + 4 / 12}}
    for name in protocol.AGENTS:
        summary[name] = {"draws": len(scored), **{
            "averageBest" + label: sum(event[name][field] for event in scored) / len(scored) if scored else None
            for label, field in (("FrontHits", "bestFrontHits"), ("BackHits", "bestBackHits"), ("TotalHits", "bestTotalHits"))}}
    agents = {}
    for name in protocol.AGENTS:
        if active:
            sealed = active["agents"][name]
            agents[name] = copy.deepcopy(sealed.get("state") or {
                "name": name, "modelVersion": sealed["modelVersion"],
                "modelFamily": "legacy-adaptive-hit-model", "backend": "legacy_classical",
                "weights": sealed.get("weights", {}), "observations": None,
                "updatedAt": active["predictionLockedAt"]})
            agents[name]["stateScope"] = "locked_prediction_snapshot"
        else:
            agents[name] = {"name": name, "modelVersion": None, "observations": None,
                            "modelFamily": None, "backend": None, "stateScope": "awaiting_batch"}
        agents[name]["duel"] = {"wins": wins[name], "losses": wins["kane" if name == "joy" else "joy"], "ties": wins["tie"]}
    version = (protocol.MODEL_VERSION if active.get("modelVersion") == protocol.MODEL_VERSION else "legacy-locked-prediction") if active else "awaiting-batch"
    target_issue, target_date = (active["issue"], active["date"]) if active else protocol.next_target(draws[-1])
    next_forecast = {"targetIssue": target_issue, "targetDate": target_date,
                     "forecastScope": "upcoming_live_draw" if active else "awaiting_verified_batch",
                     "historyCount": active["trainingDrawCount"] if active else 0,
                     "historyThroughIssue": active["trainingThroughIssue"] if active else None,
                     "historyThroughDate": active["trainingThroughDate"] if active else None,
                     **{name: copy.deepcopy(active["agents"][name]["prediction"]) if active else {"results": []}
                        for name in protocol.AGENTS}}
    lock_metadata = {"issue": active["issue"], "date": active["date"],
                     "predictionId": active["predictionId"], "lockedAt": active["predictionLockedAt"]} if active else None
    coverage = {"latestIssue": draws[-1]["issue"], "latestDate": draws[-1]["date"],
                "validDrawCount": len(draws), "archiveSha256": protocol.digest(draws)}
    common = {"modelVersion": version, "runtimeVersion": protocol.MODEL_VERSION, "generatedAt": now,
              "walkForward": True, "futureLeakage": False, "predictionGate": gate,
              "trainedBatch": trained_batch, "dataCoverage": coverage, "livePredictionLock": lock_metadata,
              "optimizer": {"enabled": False, "status": "removed"}}
    state = {**common, "agents": agents, "trainingPolicy": "Only the 100-cycle chronological batch updates model parameters."}
    dashboard = {**common, "method": {"training": {"kind": "batch_only", "cycleCount": 100,
                    "selectionPolicy": "fixed_final_cycle", "liveTrainingEnabled": False},
                    "predictionLedger": "data/" + LEDGER_NAME, "resultLedger": "data/" + LEDGER_NAME,
                    "auditFile": "data/joy-kane-audit.json", "scoreDefinition": summary["scoreDefinition"]},
                 "summary": summary, "nextForecast": next_forecast, "agentStates": agents,
                 "audit": {"file": "data/joy-kane-audit.json", "rows": len(scored), "scope": "live_predictions_only"}}
    audit_rows = [{"issue": event["actual"]["issue"], "date": event["actual"]["date"],
                   "actual": event["actual"], **{name: event[name] for name in protocol.AGENTS},
                   "winner": event["winner"], "predictionId": event["predictionId"],
                   "predictionLockedAt": event["predictionLockedAt"], "actualRevealedAt": event["recordedAt"],
                   "trainingThroughIssue": ledger["locks"][event["predictionId"]]["trainingThroughIssue"],
                   "usedLivePredictionLock": True, "futureLeakage": False} for event in scored]
    _write_json(data / "joy-kane-model-state.json", state)
    _write_json(data / "joy-kane-dashboard.json", dashboard)
    _write_json(data / "joy-kane-audit.json", {"modelVersion": protocol.MODEL_VERSION,
                "generatedAt": now, "scope": "live_predictions_only", "rows": audit_rows,
                "missingPredictions": [{"issue": event["actual"]["issue"], "date": event["actual"]["date"],
                                        "reason": event["reason"]} for event in ledger["missing"]]})
    return dashboard


def run_live(data_dir: Path, batch_models: Path | None = None, now: datetime | None = None) -> dict:
    data = Path(data_dir)
    draws = protocol.load_archive(data / "draws.json")
    current = now or _utc_now()
    if current.tzinfo is None:
        raise ValueError("The live publication clock must include a timezone.")
    recorded_at = current.astimezone(timezone.utc).isoformat()
    data.mkdir(parents=True, exist_ok=True)
    lock_path = data / LOCK_NAME
    with (data / LEDGER_NAME).open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        events = _read_ledger(handle)
        disk_lock = _read_json(lock_path)
        if not events:
            if disk_lock is not None:
                prefix = _lock_prefix(disk_lock, draws)
                _append_event(handle, events, {"eventType": "prediction_locked", "origin": "legacy_import",
                              "baselineArchive": protocol.archive_metadata(prefix), "lock": disk_lock}, recorded_at)
            else:
                _append_event(handle, events, {"eventType": "no_prior_prediction", "actual": draws[-1],
                              "baselineArchive": protocol.archive_metadata(draws),
                              "reason": "No sealed forecast existed when the live ledger started."}, recorded_at)
        ledger = _replay_ledger(events, draws)
        _reconcile_lock(lock_path, disk_lock, ledger)
        boundary = ledger["baseline"]["lastDate"]
        missing_result = False
        for actual in draws:
            if actual["date"] <= boundary or actual["issue"] in ledger["outcomes"]:
                continue
            active = ledger["active"]
            if active and actual["date"] > active["date"]:
                missing_result = True
                break
            if active and (actual["issue"] == active["issue"] or actual["date"] == active["date"]):
                if (actual["issue"], actual["date"]) != (active["issue"], active["date"]):
                    raise ValueError("The actual draw identity conflicts with the pending prediction.")
                scores = {name: protocol.score_ticket(active["agents"][name]["prediction"]["results"][0], actual)
                          for name in protocol.AGENTS}
                _append_event(handle, events, {"eventType": "result_scored", "predictionId": active["predictionId"],
                              "predictionLockedAt": active["predictionLockedAt"], "actual": actual,
                              **scores, "winner": _winner(scores)}, recorded_at)
            else:
                _append_event(handle, events, {"eventType": "no_prior_prediction", "actual": actual,
                              "reason": "No prediction was sealed before this draw became available."}, recorded_at)
            ledger = _replay_ledger(events, draws)
        package, trained_batch = _package_status(Path(batch_models) if batch_models is not None else None, draws)
        active = ledger["active"]
        gate = {"requiredCycleCount": 100, "packageStatus": trained_batch["status"],
                "batchId": trained_batch.get("id"), "waitingForIssue": active["issue"] if active else None,
                "lastScoredIssue": ledger["scored"][-1]["actual"]["issue"] if ledger["scored"] else None,
                "publicationCutoff": publication_deadline(active["date"] if active else protocol.next_target(draws[-1])[1]).isoformat(),
                "cutoffPolicy": "seal_before_draw_day_sales_close", "cutoffSource": CUTOFF_SOURCE}
        if active:
            gate.update(status="awaiting_result", reason=(
                "The archive has advanced without the pending target result; the sealed predictions remain locked."
                if missing_result else "Waiting for the actual result before another prediction can be issued."))
        elif package is None:
            gate.update(status="awaiting_batch", reason=trained_batch["reason"])
        else:
            target_issue, target_date = protocol.next_target(draws[-1])
            deadline = publication_deadline(target_date)
            if current >= deadline:
                gate.update(status="blocked", waitingForIssue=target_issue,
                            reason=f"The target draw's {deadline:%H:%M} Asia/Shanghai publication cutoff has passed; waiting for the actual result.")
            else:
                lock = _new_lock(package, draws, recorded_at)
                # Check the clock again after inference; an evaluation that crosses
                # the deadline must not be backdated to the start of the process.
                sealed_at = now or _utc_now()
                if sealed_at < current:
                    raise ValueError("The publication clock moved backwards during prediction generation.")
                recorded_at = sealed_at.astimezone(timezone.utc).isoformat()
                if sealed_at >= deadline:
                    gate.update(status="blocked", waitingForIssue=target_issue,
                                reason=f"Prediction generation reached the {deadline:%H:%M} Asia/Shanghai publication cutoff; no new ticket was sealed.")
                else:
                    lock["predictionLockedAt"] = recorded_at
                    _validate_lock(lock)
                    _append_event(handle, events, {"eventType": "prediction_locked", "origin": "completed_batch", "lock": lock}, recorded_at)
                    ledger = _replay_ledger(events, draws)
                    _reconcile_lock(lock_path, _read_json(lock_path), ledger)
                    gate.update(status="prediction_locked", reason="The previous results are recorded and the next Joy and Kane predictions are sealed.", waitingForIssue=target_issue)
        return _export(data, draws, ledger, gate, trained_batch, recorded_at)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("DUEL_DATA_DIR", ROOT / "data")))
    parser.add_argument("--batch-models", type=Path)
    args = parser.parse_args()
    try:
        dashboard = run_live(args.data_dir, args.batch_models)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise SystemExit(f"Live prediction publication blocked: {error}") from error
    print(json.dumps({"predictionGate": dashboard["predictionGate"],
                      "targetIssue": dashboard["nextForecast"]["targetIssue"],
                      "modelVersion": dashboard["modelVersion"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

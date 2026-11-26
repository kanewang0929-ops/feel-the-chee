#!/usr/bin/env python3
"""Build the compact, public dashboard feed for daily simulation batches."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

METRIC_FIELDS = ("averageBestFrontHits", "averageBestBackHits", "averageBestTotalHits")
HISTORY_LIMIT = 30


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def metric_stats(rows: list[dict[str, Any]], agent: str) -> dict[str, dict[str, float | int]]:
    output: dict[str, dict[str, float | int]] = {}
    for field in METRIC_FIELDS:
        values = [float(row[agent][field]) for row in rows if isinstance(row.get(agent), dict) and row[agent].get(field) is not None]
        if not values:
            continue
        output[field] = {
            "mean": round(statistics.fmean(values), 6),
            "min": round(min(values), 6),
            "max": round(max(values), 6),
            "stdev": round(statistics.pstdev(values), 6),
        }
    return output


def build_batch(summary: dict[str, Any] | None, *, status: str, run_id: str, run_attempt: str,
                run_number: str, run_url: str, started_at: str | None, archive_path: Path) -> dict[str, Any]:
    finished_at = utc_now()
    started = parse_datetime(started_at)
    finished = parse_datetime(finished_at)
    if started and finished and started > finished:
        started = None
    duration = round((finished - started).total_seconds()) if started and finished else None
    normalized_status = "completed" if status == "success" and summary else (
        "failed" if status in {"failure", "cancelled", "timed_out"} or not summary else status
    )
    rows = summary.get("simulationSummaries", []) if summary else []
    duel_wins: dict[str, int] = {}
    for row in rows:
        for key, value in (row.get("duelWins") or {}).items():
            duel_wins[key] = duel_wins.get(key, 0) + int(value)
    first = rows[0] if rows else {}
    return {
        "batchId": str(run_id) + "." + str(run_attempt),
        "runId": str(run_id),
        "runAttempt": int(run_attempt or 1),
        "runNumber": int(run_number or 0),
        "workflowRunUrl": run_url,
        "status": normalized_status,
        "startedAt": started.isoformat() if started else None,
        "finishedAt": finished_at,
        "durationSeconds": duration,
        "engineVersion": summary.get("engineVersion") if summary else None,
        "modelVersion": summary.get("modelVersion") if summary else None,
        "selectedCycle": summary.get("selectedCycle") if summary else None,
        "selectionPolicy": summary.get("selectionPolicy") if summary else None,
        "archiveNormalizedSha256": (summary.get("archive") or {}).get("sha256") if summary else None,
        "batchSeed": summary.get("batchSeed") if summary else None,
        "archiveSha256": hashlib.sha256(archive_path.read_bytes()).hexdigest() if archive_path.exists() else None,
        "simulationCount": int(summary.get("simulationCount", len(rows))) if summary else 0,
        "independentFirstPredictions": int(summary.get("independentFirstPredictions", 0)) if summary else 0,
        "allFirstPredictionsDistinct": bool(summary.get("allFirstPredictionsDistinct", False)) if summary else False,
        "drawsEvaluatedPerSimulation": int(first.get("drawsEvaluated", 0)) if first else 0,
        "dateRange": first.get("dateRange") if first else None,
        "joy": metric_stats(rows, "joy"),
        "kane": metric_stats(rows, "kane"),
        "duelWins": duel_wins,
        "simulations": [
            {"simulationId": row.get("simulationId"), "drawsEvaluated": row.get("drawsEvaluated"),
             "trainedDrawCount": row.get("trainedDrawCount"), "finalModelHashes": row.get("finalModelHashes"),
             "joy": row.get("joy"), "kane": row.get("kane"), "duelWins": row.get("duelWins"),
             "firstPredictionFingerprint": row.get("firstPredictionFingerprint"),
             "fullReplayAuditRowsValidated": row.get("fullReplayAuditRowsValidated")}
            for row in rows
        ],
        "guardrails": summary.get("guardrails", {}) if summary else {},
    }


def update_feed(existing: dict[str, Any] | None, batch: dict[str, Any]) -> dict[str, Any]:
    feed = dict(existing or {})
    feed["schemaVersion"] = 1
    feed["updatedAt"] = utc_now()
    feed["schedule"] = {
        "enabled": True, "simulationsPerBatch": 100, "cronUtc": "0 10 * * *",
        "timeZone": "Asia/Shanghai", "localTime": "18:00",
        "description": "Daily 100-simulation full-history replay.",
    }
    batches = [row for row in list(feed.get("batches") or []) if row.get("batchId") != batch["batchId"]]
    batches.insert(0, batch)
    feed["batches"] = batches[:HISTORY_LIMIT]
    return feed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--existing-feed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive", type=Path, default=Path("data/draws.json"))
    parser.add_argument("--status", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", default="1")
    parser.add_argument("--run-number", default="0")
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--started-at")
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8")) if args.summary.exists() else None
    if args.status == "success" and summary is None:
        raise SystemExit("The batch completed without its expected summary file.")
    existing = json.loads(args.existing_feed.read_text(encoding="utf-8")) if args.existing_feed.exists() else None
    batch = build_batch(summary, status=args.status, run_id=args.run_id, run_attempt=args.run_attempt,
                        run_number=args.run_number, run_url=args.run_url, started_at=args.started_at,
                        archive_path=args.archive)
    feed = update_feed(existing, batch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

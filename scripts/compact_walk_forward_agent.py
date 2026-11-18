#!/usr/bin/env python3
"""One-time compactor for the first full walk-forward Agent output.

Moves post-reveal scoring and learning events into a separate JSONL ledger,
leaving the website dashboard with only forecasts, summary metrics, and the
learning curve. The prediction-only ledger remains untouched.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT_FILE = DATA / "walk-forward-agent.json"
RESULT_LEDGER_FILE = DATA / "walk-forward-agent-results.jsonl"


def write_json(path: Path, payload) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    payload = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    rows = payload.pop("draws", [])

    if rows:
        with RESULT_LEDGER_FILE.open("w", encoding="utf-8") as ledger:
            for row in rows:
                evaluation = row.get("evaluation", {})
                event = {
                    "eventType": "result_scored",
                    "predictionId": row.get("predictionId"),
                    "issue": row.get("issue"),
                    "date": row.get("date"),
                    "trainingDrawCount": row.get("trainingDrawCount"),
                    "trainingThroughIssue": row.get("trainingThroughIssue"),
                    "historyDigest": row.get("historyDigest"),
                    "predictionLockedAt": row.get("predictionLockedAt"),
                    "actualRevealedAt": row.get("actualRevealedAt"),
                    "actual": row.get("actual"),
                    "evaluation": {
                        key: evaluation[key]
                        for key in ("ai", "chee", "instinct", "agent")
                        if key in evaluation
                    },
                    "learningUpdate": row.get("learningUpdate", {}),
                    "futureLeakage": False,
                }
                ledger.write(json.dumps(event, ensure_ascii=False) + "\n")
            ledger.flush()

    summary = payload.setdefault("summary", {})
    summary["theoreticalFixedTicketBaseline"] = {
        "averageFrontHitsPerTicket": round(25 / 35, 6),
        "averageBackHitsPerTicket": round(4 / 12, 6),
        "averageTotalHitsPerTicket": round(25 / 35 + 4 / 12, 6),
        "note": "Expected hit counts for one uniformly random valid 5+2 ticket in a fair draw.",
    }
    payload["historyRecords"] = {
        "predictionLedger": "data/walk-forward-agent-predictions.jsonl",
        "resultLedger": "data/walk-forward-agent-results.jsonl",
    }
    summary["historyRecords"] = len(rows) or summary.get("drawsEvaluated", 0)

    write_json(OUTPUT_FILE, payload)
    print(
        json.dumps(
            {
                "dashboardFile": str(OUTPUT_FILE.relative_to(ROOT)),
                "dashboardBytes": OUTPUT_FILE.stat().st_size,
                "resultLedger": str(RESULT_LEDGER_FILE.relative_to(ROOT)),
                "resultLedgerBytes": RESULT_LEDGER_FILE.stat().st_size,
                "historicalRowsCompacted": len(rows),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

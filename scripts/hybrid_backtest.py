#!/usr/bin/env python3
"""Sequential historical simulation of the adaptive AI/Chee fusion agent.

The simulation consumes the already walk-forward AI predictions and the
formula-only Chee predictions for the same draw. The hybrid state is updated
only after that draw's actual result is revealed.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import hybrid_agent as agent

ROOT = Path(__file__).resolve().parents[1]
AI_FILE = ROOT / "data/ai-backtest.json"
CHEE_FILE = ROOT / "data/chee-backtest.json"
OUTPUT_FILE = ROOT / "data/hybrid-backtest.json"
VERSION = "v1.0-sequential-fusion-audit"


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


def hypergeometric(population: int, winners: int, picks: int) -> dict[str, float]:
    denominator = math.comb(population, picks)
    return {
        str(hits): (
            math.comb(winners, hits)
            * math.comb(population - winners, picks - hits)
            / denominator
        )
        for hits in range(min(winners, picks) + 1)
    }


def source_payload(row: dict, source: str) -> dict:
    results = []
    for position, ticket in enumerate(row.get("tickets", []), start=1):
        item = {
            "rank": int(ticket.get("rank") or position),
            "label": ticket.get("label") or f"{source}-{position}",
            "front": ticket.get("front", []),
            "back": ticket.get("back", []),
        }
        if source == "ai":
            item["fit"] = 84.0 - 2.2 * (position - 1)
        else:
            item["cheeValue"] = float(ticket.get("cheeValue", 86.0 - 6.4 * (position - 1)))
        results.append(item)
    return {
        "targetIssue": row.get("issue"),
        "targetDate": row.get("date"),
        "results": results,
    }


def actual_from(row: dict) -> dict:
    return {
        "issue": str(row["issue"]),
        "date": str(row["date"]),
        "front": agent.numbers(row["actual"]["front"]),
        "back": agent.numbers(row["actual"]["back"]),
    }


def aggregate(rows: list[dict], source_summaries: dict, learning_curve: list[dict]) -> dict:
    tickets = [ticket for row in rows for ticket in row["evaluation"]["results"]]
    ticket_count = len(tickets)
    front_distribution = Counter(ticket["frontHitCount"] for ticket in tickets)
    back_distribution = Counter(ticket["backHitCount"] for ticket in tickets)
    patterns = Counter(
        f'{ticket["frontHitCount"]}+{ticket["backHitCount"]}' for ticket in tickets
    )
    best_front = Counter(
        max(ticket["frontHitCount"] for ticket in row["evaluation"]["results"])
        for row in rows
    )
    best_back = Counter(
        max(ticket["backHitCount"] for ticket in row["evaluation"]["results"])
        for row in rows
    )
    mix_distribution = Counter()
    for ticket in tickets:
        front = ticket.get("sourceMix", {}).get("front", {})
        back = ticket.get("sourceMix", {}).get("back", {})
        key = (
            f"F-A{front.get('aiOnly',0)}-C{front.get('cheeOnly',0)}-B{front.get('both',0)}"
            f"|R-A{back.get('aiOnly',0)}-C{back.get('cheeOnly',0)}-B{back.get('both',0)}"
        )
        mix_distribution[key] += 1

    average_front = statistics.fmean(ticket["frontHitCount"] for ticket in tickets)
    average_back = statistics.fmean(ticket["backHitCount"] for ticket in tickets)
    front_probabilities = hypergeometric(35, 5, 5)
    back_probabilities = hypergeometric(12, 2, 2)
    front_baseline = 25 / 35
    back_baseline = 4 / 12

    by_year = defaultdict(lambda: {"draws": 0, "tickets": 0, "front": 0, "back": 0})
    for row in rows:
        year = row["date"][:4]
        group = by_year[year]
        group["draws"] += 1
        group["tickets"] += len(row["evaluation"]["results"])
        group["front"] += sum(
            ticket["frontHitCount"] for ticket in row["evaluation"]["results"]
        )
        group["back"] += sum(
            ticket["backHitCount"] for ticket in row["evaluation"]["results"]
        )

    yearly = {
        year: {
            "draws": values["draws"],
            "tickets": values["tickets"],
            "averageFrontHits": round(values["front"] / values["tickets"], 4),
            "averageBackHits": round(values["back"] / values["tickets"], 4),
        }
        for year, values in by_year.items()
    }

    best_examples = sorted(
        rows,
        key=lambda row: (
            max(
                ticket["frontHitCount"] + ticket["backHitCount"]
                for ticket in row["evaluation"]["results"]
            ),
            max(ticket["frontHitCount"] for ticket in row["evaluation"]["results"]),
            max(ticket["backHitCount"] for ticket in row["evaluation"]["results"]),
        ),
        reverse=True,
    )[:20]

    return {
        "drawsEvaluated": len(rows),
        "ticketsEvaluated": ticket_count,
        "dateRange": {
            "earliest": rows[0]["date"] if rows else None,
            "latest": rows[-1]["date"] if rows else None,
        },
        "observed": {
            "averageFrontHitsPerTicket": round(average_front, 6),
            "averageBackHitsPerTicket": round(average_back, 6),
            "averageTotalHitsPerTicket": round(average_front + average_back, 6),
            "frontHitDistribution": {
                str(hits): front_distribution[hits] for hits in range(6)
            },
            "backHitDistribution": {
                str(hits): back_distribution[hits] for hits in range(3)
            },
            "hitPatternDistribution": dict(sorted(patterns.items())),
            "bestOfTwoFrontDistribution": {
                str(hits): best_front[hits] for hits in range(6)
            },
            "bestOfTwoBackDistribution": {
                str(hits): best_back[hits] for hits in range(3)
            },
            "exactFivePlusTwo": patterns["5+2"],
        },
        "theoreticalFixedTicketBaseline": {
            "averageFrontHitsPerTicket": round(front_baseline, 6),
            "averageBackHitsPerTicket": round(back_baseline, 6),
            "averageTotalHitsPerTicket": round(front_baseline + back_baseline, 6),
            "expectedFrontHitCounts": {
                key: round(value * ticket_count, 3)
                for key, value in front_probabilities.items()
            },
            "expectedBackHitCounts": {
                key: round(value * ticket_count, 3)
                for key, value in back_probabilities.items()
            },
        },
        "comparison": {
            "frontMeanDifference": round(average_front - front_baseline, 6),
            "backMeanDifference": round(average_back - back_baseline, 6),
            "totalMeanDifference": round(
                average_front + average_back - front_baseline - back_baseline, 6
            ),
            "versusSourceModels": source_summaries,
        },
        "sourceMixDistribution": dict(mix_distribution.most_common()),
        "byYear": yearly,
        "learningCurve": learning_curve,
        "bestExamples": best_examples,
    }


def main() -> None:
    ai_payload = read_json(AI_FILE, {})
    chee_payload = read_json(CHEE_FILE, {})
    ai_rows = ai_payload.get("draws", [])
    chee_rows = chee_payload.get("drawResults", [])
    if not ai_rows or not chee_rows:
        raise RuntimeError("AI and Chee backtests must exist before fusion audit.")

    chee_by_issue = {str(row.get("issue")): row for row in chee_rows}
    aligned = [row for row in ai_rows if str(row.get("issue")) in chee_by_issue]
    state = agent.default_state()
    rows = []
    learning_curve = []

    for position, ai_row in enumerate(aligned, start=1):
        issue = str(ai_row["issue"])
        chee_row = chee_by_issue[issue]
        ai_source = source_payload(ai_row, "ai")
        chee_source = source_payload(chee_row, "chee")
        state_before = json.loads(json.dumps(state))
        results = agent.generate_results(ai_source, chee_source, state)
        actual = actual_from(ai_row)
        evaluation = agent.evaluate_and_update(
            state,
            ai_source["results"],
            chee_source["results"],
            results,
            actual,
            alpha=0.035,
        )
        rows.append(
            {
                "issue": issue,
                "date": ai_row["date"],
                "actual": evaluation["actual"],
                "sourceWeightsBefore": state_before["sourceWeights"],
                "strategyWeightsBefore": state_before["strategyWeights"],
                "results": results,
                "evaluation": evaluation,
            }
        )
        if position == 1 or position % 50 == 0 or position == len(aligned):
            cumulative = state["cumulative"]
            learning_curve.append(
                {
                    "drawNumber": position,
                    "issue": issue,
                    "date": ai_row["date"],
                    "sourceWeights": json.loads(json.dumps(state["sourceWeights"])),
                    "strategyWeights": json.loads(
                        json.dumps(state["strategyWeights"])
                    ),
                    "averageFrontHits": round(
                        cumulative["frontHits"] / max(1, cumulative["tickets"]), 6
                    ),
                    "averageBackHits": round(
                        cumulative["backHits"] / max(1, cumulative["tickets"]), 6
                    ),
                }
            )
        if position % 100 == 0:
            print(f"Fusion-audited {position}/{len(aligned)} draws", flush=True)

    ai_summary = ai_payload.get("summary", {}).get("observed", {})
    chee_summary = chee_payload.get("summary", {}).get("observed", {})
    source_summaries = {
        "ai": {
            "averageFrontHits": ai_summary.get("averageFrontHitsPerTicket"),
            "averageBackHits": ai_summary.get("averageBackHitsPerTicket"),
        },
        "chee": {
            "averageFrontHits": chee_summary.get("averageFrontHitsPerTicket"),
            "averageBackHits": chee_summary.get("averageBackHitsPerTicket"),
        },
    }
    summary = aggregate(rows, source_summaries, learning_curve)
    payload = {
        "backtestVersion": VERSION,
        "modelVersion": agent.VERSION,
        "modelFamily": "adaptive-source-fusion-agent",
        "sequentialLearning": True,
        "futureLeakage": False,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "method": {
            "inputs": [
                "walk-forward AI ticket candidates",
                "formula-only Chee ticket candidates",
            ],
            "selection": (
                "The agent scores every candidate number by source support, "
                "bounded source reliability, consensus category, curve fit when "
                "available, and ticket diversity."
            ),
            "learning": (
                "After each actual draw, source and source-category rewards update "
                "bounded exponential moving averages."
            ),
        },
        "summary": summary,
        "finalState": state,
        "draws": rows,
        "note": (
            "The audit measures historical behavior. It does not make a fair random "
            "draw predictable or turn the agent score into a winning probability."
        ),
    }
    write_json(OUTPUT_FILE, payload)
    print(
        json.dumps(
            {
                "backtestVersion": VERSION,
                "modelVersion": agent.VERSION,
                "summary": summary,
                "finalSourceWeights": state["sourceWeights"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

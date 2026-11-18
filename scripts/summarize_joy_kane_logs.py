#!/usr/bin/env python3
"""Compact Joy/Kane daily optimization logs older than seven days.

Per-draw prediction and result ledgers are intentionally never compacted:
they are the permanent audit trail shown in the Learning tab.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DETAIL = DATA / "joy-kane-training-log.jsonl"
WEEKLY = DATA / "joy-kane-weekly-summaries.jsonl"


def parse_stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def read_lines(path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def write_lines(path, rows):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    temp.replace(path)


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    details = read_lines(DETAIL)
    weekly_rows = read_lines(WEEKLY)
    recent, expired = [], []
    for row in details:
        created = parse_stamp(row.get("generatedAt"))
        if created and created < cutoff:
            expired.append(row)
        else:
            recent.append(row)

    if not expired:
        print(json.dumps({
            "compacted": 0,
            "retainedDailyRecords": len(recent),
            "weeklySummaryRecords": len(weekly_rows),
            "note": "No daily training records are older than seven days.",
        }, ensure_ascii=False, indent=2))
        return

    grouped = defaultdict(list)
    for row in expired:
        created = parse_stamp(row.get("generatedAt"))
        if not created:
            continue
        iso = created.isocalendar()
        week_start = (created.date() - timedelta(days=created.weekday())).isoformat()
        grouped[(iso.year, iso.week, week_start)].append(row)

    # Rebuild the compacted week from existing summary plus newly expired detail.
    index = {(row.get("isoYear"), row.get("isoWeek"), row.get("weekStart")): row for row in weekly_rows}
    for (year, week, week_start), rows in grouped.items():
        existing = index.get((year, week, week_start), {})
        summary_agents = {}
        for agent in ("joy", "kane"):
            old = existing.get("agents", {}).get(agent, {})
            events = [row.get("agents", {}).get(agent, {}) for row in rows]
            count_old = int(old.get("runs", 0))
            count_new = len(events)
            combined_count = count_old + count_new

            def avg(field):
                old_avg = float(old.get(field, 0.0) or 0.0)
                new_vals = [float(event.get(field, 0.0) or 0.0) for event in events if event.get(field) is not None]
                numerator = old_avg * count_old + sum(new_vals)
                denominator = count_old + len(new_vals)
                return round(numerator / denominator, 6) if denominator else 0.0

            summary_agents[agent] = {
                "runs": combined_count,
                "totalCycles": int(old.get("totalCycles", 0)) + sum(int(event.get("cyclesPerRun", 0) or 0) for event in events),
                "acceptedRuns": int(old.get("acceptedRuns", 0)) + sum(1 for event in events if event.get("accepted")),
                "averageValidationBefore": avg("validationScoreBefore"),
                "averageValidationAfter": avg("validationScoreAfter"),
                "averageUntouchedTestBefore": avg("untouchedTestScoreBefore"),
                "averageUntouchedTestAfter": avg("untouchedTestScoreAfter"),
                "latestAccepted": next((event.get("accepted") for event in reversed(events) if event), old.get("latestAccepted")),
            }

        timestamps = [parse_stamp(row.get("generatedAt")) for row in rows]
        timestamps = [value for value in timestamps if value]
        index[(year, week, week_start)] = {
            "eventType": "weekly_training_summary",
            "isoYear": year,
            "isoWeek": week,
            "weekStart": week_start,
            "weekEnd": (datetime.fromisoformat(week_start).date() + timedelta(days=6)).isoformat(),
            "summarizedAt": now.isoformat(),
            "firstRunAt": min(timestamps).isoformat() if timestamps else existing.get("firstRunAt"),
            "lastRunAt": max(timestamps).isoformat() if timestamps else existing.get("lastRunAt"),
            "agents": summary_agents,
            "sourceDailyRecords": int(existing.get("sourceDailyRecords", 0)) + len(rows),
            "auditPolicy": "Per-draw prediction and result ledgers remain untouched.",
        }

    compacted = sorted(index.values(), key=lambda row: (row.get("isoYear", 0), row.get("isoWeek", 0)))
    write_lines(WEEKLY, compacted)
    write_lines(DETAIL, recent)
    print(json.dumps({
        "compactedDailyRecords": len(expired),
        "retainedDailyRecords": len(recent),
        "weeklySummaryRecords": len(compacted),
        "cutoff": cutoff.isoformat(),
        "perDrawAuditPreserved": True,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Settle the previous Agent forecast against a newly published draw.

This runs before full-history cycle training so the newest real draw is included
in the live Agent state first. The million-cycle trainer then optimizes from that
updated state and its champion remains the final state used for the next forecast.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

import intuitive_agent_runtime as runtime

base = runtime.base


def main() -> None:
    state_payload = base.read_json(base.STATE_FILE, {})
    backtest = base.read_json(base.BACKTEST_FILE, {})
    state = base.ensure_state(state_payload or backtest.get("finalState", {}))
    draws = base.load_draws()
    previous = base.read_json(base.FORECAST_FILE, {})
    logs = base.read_json(base.LOG_FILE, [])
    if not isinstance(logs, list):
        logs = []

    previous_issue = str(previous.get("targetIssue") or "")
    if not previous_issue or not previous.get("results"):
        print(json.dumps({"settled": False, "reason": "No previous Agent forecast."}, ensure_ascii=False))
        return

    actual = next((draw for draw in draws if draw["issue"] == previous_issue), None)
    already = next((row for row in logs if str(row.get("issue")) == previous_issue), None)

    evaluation = already
    if actual and not already:
        inputs = previous.get("sourceInputs", {})
        evaluation = base.evaluate_and_update(
            state,
            inputs.get("ai", {}).get("results", []),
            inputs.get("chee", {}).get("results", []),
            inputs.get("instinct", {}).get("results", []),
            previous["results"],
            actual,
        )
        evaluation.update({
            "issue": previous_issue,
            "date": actual["date"],
            "evaluatedAt": datetime.now(timezone.utc).isoformat(),
            "modelVersion": previous.get("modelVersion"),
        })
        logs.append(evaluation)

    if actual:
        base.archive_previous(previous, evaluation)

    now = datetime.now(timezone.utc).isoformat()
    state["modelVersion"] = runtime.VERSION
    state["updatedAt"] = now
    base.write_json(base.STATE_FILE, state)
    base.write_json(base.LOG_FILE, logs)

    print(json.dumps({
        "settled": bool(actual),
        "issue": previous_issue,
        "alreadyEvaluated": bool(already),
        "evaluation": evaluation,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

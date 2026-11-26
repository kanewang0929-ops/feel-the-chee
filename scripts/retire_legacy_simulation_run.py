#!/usr/bin/env python3
"""Retire the one verified pre-quantum run left active during the migration.

This is deliberately not a general cancellation tool: no target can be supplied
through arguments or environment variables. Completed runs require no action.
"""
from __future__ import annotations

import json
import os
import subprocess


REPOSITORY = "kanewang0929-ops/feel-the-chee"
RUN_ID = 45838826149
HEAD_SHA = "94844f4e59b67c80dc11411aeac266919a045071"
WORKFLOW_ID = 423597154
WORKFLOW_PATH = ".github/workflows/daily-simulation-batch.yml"
WORKFLOW_NAME = "Daily 100-simulation batch"
ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}
ALLOWED_TRIGGERS = {"push", "workflow_dispatch"}


class RetirementError(RuntimeError):
    pass


def _invoke(arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *arguments], capture_output=True, text=True,
                          check=False, timeout=30)


def _read_verified_run() -> dict:
    try:
        response = _invoke(["api", "--method", "GET",
                            f"repos/{REPOSITORY}/actions/runs/{RUN_ID}"])
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RetirementError("GitHub run lookup failed; no further action was taken.") from error
    if response.returncode != 0:
        raise RetirementError(f"GitHub run lookup failed (exit {response.returncode}); no further action was taken.")
    try:
        run = json.loads(response.stdout)
    except (TypeError, ValueError) as error:
        raise RetirementError("GitHub returned an invalid run response; no further action was taken.") from error
    if not isinstance(run, dict):
        raise RetirementError("GitHub returned a non-object run response.")
    expected = {"id": RUN_ID, "head_sha": HEAD_SHA, "head_branch": "main",
                "workflow_id": WORKFLOW_ID, "path": WORKFLOW_PATH,
                "name": WORKFLOW_NAME, "event": "push"}
    for field, value in expected.items():
        if run.get(field) != value:
            raise RetirementError(f"The legacy run's {field} does not match the pinned migration identity.")
    for field in ("repository", "head_repository"):
        repository = run.get(field)
        if not isinstance(repository, dict) or repository.get("full_name") != REPOSITORY:
            raise RetirementError(f"The legacy run's {field} does not match the pinned repository.")
    if not isinstance(run.get("status"), str) or run["status"] not in ACTIVE_STATUSES | {"completed"}:
        raise RetirementError("The legacy run has an unrecognized status.")
    return run


def retire_legacy_run(environ: dict[str, str] | None = None) -> str:
    environment = os.environ if environ is None else environ
    if environment.get("GITHUB_EVENT_NAME") not in ALLOWED_TRIGGERS:
        return "skipped_trigger"
    if environment.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise RetirementError("Retirement must run in the pinned repository.")
    if environment.get("GITHUB_REF") != "refs/heads/main":
        raise RetirementError("Retirement must run from main.")
    if environment.get("GITHUB_RUN_ID") == str(RUN_ID):
        raise RetirementError("The retirement helper cannot cancel its own workflow run.")

    run = _read_verified_run()
    if run["status"] == "completed":
        return "already_completed"
    try:
        response = _invoke(["run", "cancel", str(RUN_ID), "--repo", REPOSITORY])
        accepted = response.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        accepted = False
    if accepted:
        return "cancellation_requested"

    # A run can finish after the checked GET and before GitHub accepts cancel.
    # Only a fresh, identity-verified completed response makes that race benign.
    # API failures, identity drift, or an active target all fail closed; never
    # broaden the target or retry cancellation against another run.
    if _read_verified_run()["status"] == "completed":
        return "completed_during_cancellation"
    raise RetirementError("Cancellation was not accepted and the verified legacy run is still active.")


def main() -> None:
    try:
        outcome = retire_legacy_run()
    except RetirementError as error:
        raise SystemExit(f"Legacy run retirement stopped: {error}") from error
    print(json.dumps({"legacyRunId": RUN_ID, "retirement": outcome}))


if __name__ == "__main__":
    main()

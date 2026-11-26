"""Shared data and model-package contracts for chronological quantum simulations."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_VERSION = "v2.0-quantum-chronological"
ENGINE_VERSION = "joy-kane-quantum-sim-v2"
AGENTS = ("joy", "kane")
WARMUP_DRAWS = 200
REQUIRED_CYCLES = 100


class PackageValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _numbers(value, count: int, upper: int, label: str) -> list[int]:
    values = value.replace(",", " ").split() if isinstance(value, str) else value
    if not isinstance(values, list) or len(values) != count:
        raise ValueError(f"{label} must contain exactly {count} numbers.")
    numbers = []
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (str, int)) or not re.fullmatch(r"[0-9]+", str(item)):
            raise ValueError(f"{label} contains a non-integer number.")
        numbers.append(int(item))
    if len(set(numbers)) != count or any(number < 1 or number > upper for number in numbers):
        raise ValueError(f"{label} contains duplicate or out-of-range numbers.")
    return sorted(numbers)


def validate_ticket(ticket: dict) -> dict:
    if not isinstance(ticket, dict):
        raise ValueError("A ticket must be an object.")
    return {"front": _numbers(ticket.get("front"), 5, 35, "Front selection"),
            "back": _numbers(ticket.get("back"), 2, 12, "Back selection")}


def normalize_draw(row: dict) -> dict:
    if not isinstance(row, dict):
        raise ValueError("Each archive row must be an object.")
    issue = str(row.get("issue", ""))
    if not re.fullmatch(r"[0-9]+", issue):
        raise ValueError("Every draw must have a numeric issue identifier.")
    day = row.get("date")
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
        raise ValueError(f"Draw {issue} has an invalid ISO date.")
    return {"issue": issue, "date": day, **validate_ticket(row)}


def load_archive(path: Path) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("draws") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise ValueError("The historical draw archive must be a non-empty list.")
    draws = [normalize_draw(row) for row in rows]
    if len({row["issue"] for row in draws}) != len(draws):
        raise ValueError("The historical archive contains duplicate issue identifiers.")
    if len({row["date"] for row in draws}) != len(draws):
        raise ValueError("The historical archive contains duplicate draw dates.")
    return sorted(draws, key=lambda row: (row["date"], int(row["issue"])))


def archive_metadata(draws: list[dict]) -> dict:
    if not draws:
        raise ValueError("Cannot identify an empty draw archive.")
    return {"sha256": digest(draws), "validDrawCount": len(draws),
            "lastIssue": draws[-1]["issue"], "lastDate": draws[-1]["date"]}


def engine_digest() -> str:
    names = ("quantum_models.py", "quantum_protocol.py", "run_simulation_batch.py")
    contents = {f"scripts/{name}": hashlib.sha256((ROOT / "scripts" / name).read_bytes()).hexdigest()
                for name in names}
    contents["requirements.txt"] = hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()
    return digest(contents)


def next_target(latest: dict) -> tuple[str, str]:
    target = date.fromisoformat(latest["date"]) + timedelta(days=1)
    while target.weekday() not in (0, 2, 5):
        target += timedelta(days=1)
    issue = str(latest["issue"])
    if len(issue) != 5:
        raise ValueError("Cannot determine the next target from a nonstandard issue identifier.")
    sequence = int(issue[2:]) if int(issue[:2]) == target.year % 100 else 0
    return f"{target.year % 100:02d}{sequence + 1:03d}", target.isoformat()


def score_ticket(ticket: dict, actual: dict) -> dict:
    selected, observed = validate_ticket(ticket), validate_ticket(actual)
    matched = {area: sorted(set(selected[area]) & set(observed[area])) for area in ("front", "back")}
    scored = {**ticket,
              "front": [f"{number:02d}" for number in selected["front"]],
              "back": [f"{number:02d}" for number in selected["back"]],
              "frontMatches": [f"{number:02d}" for number in matched["front"]],
              "backMatches": [f"{number:02d}" for number in matched["back"]],
              "frontHits": [f"{number:02d}" for number in matched["front"]],
              "backHits": [f"{number:02d}" for number in matched["back"]],
              "frontHitCount": len(matched["front"]), "backHitCount": len(matched["back"]),
              "totalHitCount": len(matched["front"]) + len(matched["back"])}
    return {"tickets": [scored], "best": scored,
            "bestFrontHits": scored["frontHitCount"], "bestBackHits": scored["backHitCount"],
            "bestTotalHits": scored["totalHitCount"]}


def validate_package(package: dict, draws: list[dict]) -> dict:
    if not isinstance(package, dict) or type(package.get("schemaVersion")) is not int or package["schemaVersion"] != 2:
        raise PackageValidationError("invalid_schema", "A version-2 batch model package is required.")
    if package.get("modelVersion") != MODEL_VERSION or package.get("engineVersion") != ENGINE_VERSION:
        raise PackageValidationError("invalid_model", "The package was produced by a different model or simulation engine.")
    batch = package.get("batch")
    if not isinstance(batch, dict) or batch.get("status") != "complete":
        raise PackageValidationError("incomplete_batch", "The 100-cycle training batch has not completed.")
    for key in ("cycleCount", "completedCycles", "selectedCycle"):
        if type(batch.get(key)) is not int or batch[key] != REQUIRED_CYCLES:
            raise PackageValidationError("incomplete_batch", "Exactly 100 complete cycles and the fixed final cycle are required.")
    if batch.get("selectionPolicy") != "fixed_final_cycle":
        raise PackageValidationError("invalid_selection", "The package must use the predeclared final-cycle selection policy.")
    if not isinstance(batch.get("id"), str) or not batch["id"] or not isinstance(batch.get("seed"), (str, int)) or isinstance(batch["seed"], bool):
        raise PackageValidationError("invalid_batch", "The batch identity and reproducible seed are required.")
    if type(package.get("warmupDraws")) is not int or package["warmupDraws"] != WARMUP_DRAWS or len(draws) <= WARMUP_DRAWS:
        raise PackageValidationError("invalid_warmup", "The package must use the documented 200-draw warm-up.")
    if package.get("archive") != archive_metadata(draws):
        raise PackageValidationError("stale_archive", "The batch does not contain the exact latest verified draw archive.")
    if package.get("engineDigest") != engine_digest():
        raise PackageValidationError("engine_mismatch", "The batch was trained with different engine source files.")
    if not isinstance(package.get("generatedAt"), str) or not package["generatedAt"]:
        raise PackageValidationError("invalid_provenance", "The package completion timestamp is missing.")
    try:
        completed_at = datetime.fromisoformat(package["generatedAt"].replace("Z", "+00:00"))
        if completed_at.tzinfo is None:
            raise ValueError("Timezone missing.")
    except (TypeError, ValueError) as error:
        raise PackageValidationError("invalid_provenance", "The package completion timestamp is invalid.") from error
    if not isinstance(package.get("sourceCommit"), str) or not package["sourceCommit"]:
        raise PackageValidationError("invalid_provenance", "The package source commit is missing.")
    agents = package.get("agents")
    if not isinstance(agents, dict) or set(agents) != set(AGENTS):
        raise PackageValidationError("invalid_models", "The package must contain exactly Joy and Kane.")
    if __package__:
        from . import quantum_models
    else:
        import quantum_models
    for name in AGENTS:
        state = agents[name]
        try:
            quantum_models.validate_state(state)
        except (TypeError, ValueError, KeyError) as error:
            raise PackageValidationError("invalid_state", f"Invalid {name.title()} model state: {error}") from error
        if state.get("name") != name or state.get("modelVersion") != MODEL_VERSION:
            raise PackageValidationError("invalid_state", "The package model identities do not match their declared agents.")
        if state.get("observations") != len(draws):
            raise PackageValidationError("invalid_state", "Each selected model must have learned every draw in the completed cycle.")
    return package

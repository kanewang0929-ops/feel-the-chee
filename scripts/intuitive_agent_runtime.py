#!/usr/bin/env python3
"""Runtime patch for the intuitive Agent's seven source signatures."""
from __future__ import annotations

import intuitive_agent as base

CATEGORIES = (
    "allThree",
    "aiChee",
    "aiInstinct",
    "cheeInstinct",
    "aiOnly",
    "cheeOnly",
    "instinctOnly",
)
base.CATEGORIES = CATEGORIES


def category(has_ai: bool, has_chee: bool, has_instinct: bool) -> str:
    if has_ai and has_chee and has_instinct:
        return "allThree"
    if has_ai and has_chee:
        return "aiChee"
    if has_ai and has_instinct:
        return "aiInstinct"
    if has_chee and has_instinct:
        return "cheeInstinct"
    if has_ai:
        return "aiOnly"
    if has_chee:
        return "cheeOnly"
    return "instinctOnly"


def candidate_records(ai_results, chee_results, instinct_results, area: str, state: dict):
    supports = {
        "ai": base.result_support(ai_results, area, "ai"),
        "chee": base.result_support(chee_results, area, "chee"),
        "instinct": base.result_support(instinct_results, area, "instinct"),
    }
    source_weights = state["sourceWeights"][area]
    strategy_weights = state["strategyWeights"][area]
    universe = sorted(set().union(*(set(row) for row in supports.values())))
    output = {}
    for number in universe:
        presence = {source: number in supports[source] for source in base.SOURCES}
        group = category(presence["ai"], presence["chee"], presence["instinct"])
        score = sum(source_weights[source] * supports[source].get(number, 0.0) for source in base.SOURCES)
        present = [source for source in base.SOURCES if presence[source]]
        if len(present) > 1:
            score += 0.05 * (len(present) - 1)
        score *= strategy_weights.get(group, 1.0)
        output[number] = {
            "number": number,
            "score": score,
            "category": group,
            "sources": present,
            "support": {source: supports[source].get(number, 0.0) for source in base.SOURCES},
        }
    return output


def category_sets(ai_results, chee_results, instinct_results, area):
    ai = {number for result in ai_results for number in base.numbers(result.get(area, []))}
    chee = {number for result in chee_results for number in base.numbers(result.get(area, []))}
    instinct = {number for result in instinct_results for number in base.numbers(result.get(area, []))}
    universe = ai | chee | instinct
    output = {name: set() for name in CATEGORIES}
    for number in universe:
        output[category(number in ai, number in chee, number in instinct)].add(number)
    return output


base.category = category
base.candidate_records = candidate_records
base.category_sets = category_sets

VERSION = base.VERSION
SOURCES = base.SOURCES
default_state = base.default_state
ensure_state = base.ensure_state
numbers = base.numbers
formatted = base.formatted
generate_bundle = base.generate_bundle
generate_results = base.generate_results
evaluate_and_update = base.evaluate_and_update
main = base.main


if __name__ == "__main__":
    main()

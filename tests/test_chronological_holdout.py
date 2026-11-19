import copy
import unittest

from scripts import evaluate_chronological_holdout as holdout


def synthetic_draws(count=90):
    rows = []
    for index in range(count):
        front = sorted({((index * 7 + offset * 11) % 35) + 1 for offset in range(5)})
        back = sorted({((index * 5 + offset * 7) % 12) + 1 for offset in range(2)})
        rows.append({
            "issue": f"26{index + 1:03d}",
            "date": f"2026-{(index // 28) + 1:02d}-{(index % 28) + 1:02d}",
            "front": front,
            "back": back,
        })
    return rows


class ChronologicalHoldoutTests(unittest.TestCase):
    def test_split_is_chronological_disjoint_and_complete(self):
        draws = synthetic_draws(100)
        split = holdout.chronological_split(draws, warmup=20)
        warmup = split["warmup"]
        train = split["training"]
        validation = split["validation"]
        test = split["finalTest"]
        self.assertEqual(warmup["endIndexExclusive"], train["startIndex"])
        self.assertEqual(train["endIndexExclusive"], validation["startIndex"])
        self.assertEqual(validation["endIndexExclusive"], test["startIndex"])
        self.assertEqual(test["endIndexExclusive"], len(draws))
        self.assertEqual(
            warmup["count"] + train["count"] + validation["count"] + test["count"],
            len(draws),
        )
        self.assertGreater(train["count"], validation["count"])
        self.assertGreater(validation["count"], 0)
        self.assertGreater(test["count"], 0)

    def test_candidate_selection_cannot_see_final_test_outcomes(self):
        draws = synthetic_draws(90)
        split = holdout.chronological_split(draws, warmup=20)
        changed = copy.deepcopy(draws)
        for index in range(split["finalTest"]["startIndex"], len(changed)):
            # Replace only final-test outcomes with other valid DLT combinations.
            changed[index]["front"] = sorted({((index * 13 + offset * 3) % 35) + 1 for offset in range(5)})
            changed[index]["back"] = sorted({((index * 11 + offset * 5) % 12) + 1 for offset in range(2)})

        first, _ = holdout.evaluate(draws, warmup=20, random_series=100, seed=77)
        second, _ = holdout.evaluate(changed, warmup=20, random_series=100, seed=77)
        self.assertEqual(first["selectedConfigurations"], second["selectedConfigurations"])
        self.assertEqual(
            first["validationSelection"],
            second["validationSelection"],
        )

    def test_matched_random_baseline_is_reproducible_and_one_ticket_per_date(self):
        draws = synthetic_draws(30)
        test_draws = draws[-10:]
        first = holdout.random_baseline(test_draws, series_count=500, seed=123)
        second = holdout.random_baseline(test_draws, series_count=500, seed=123)
        self.assertEqual(first, second)
        self.assertEqual(first["ticketsPerSeries"], len(test_draws))
        self.assertEqual(first["totalTickets"], 500 * len(test_draws))
        self.assertAlmostEqual(
            first["averageTotalHits"],
            holdout.RANDOM_EXPECTED_HITS,
            delta=0.10,
        )

    def test_split_rejects_empty_or_invalid_periods(self):
        with self.assertRaises(ValueError):
            holdout.chronological_split(synthetic_draws(12), warmup=10)
        with self.assertRaises(ValueError):
            holdout.chronological_split(synthetic_draws(30), warmup=0)


if __name__ == "__main__":
    unittest.main()

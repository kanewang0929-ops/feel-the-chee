import copy
import itertools
import json
import math
import unittest

import numpy as np

from scripts import quantum_models as models


ACTUAL = {"issue": "26135", "date": "2026-11-25",
          "front": [1, 7, 15, 22, 35], "back": [2, 11]}


class QuantumModelTests(unittest.TestCase):
    def test_families_have_distinct_evolution_and_normalized_states(self):
        for area, (count, _picks) in models.LIMITS.items():
            joy = models.initial_state("joy", 42)
            kane = models.initial_state("kane", 42)
            joy_amplitudes = models._joy_amplitudes(np.asarray(joy["parameters"][area]), area)
            kane_amplitudes = models._kane_amplitudes(np.asarray(kane["parameters"][area]), area)
            self.assertEqual(joy_amplitudes.shape, (2 ** models.QUBITS[area],))
            self.assertEqual(kane_amplitudes.shape, (2, count))
            self.assertAlmostEqual(float(np.sum(abs(joy_amplitudes) ** 2)), 1.0, places=12)
            self.assertAlmostEqual(float(np.sum(abs(kane_amplitudes) ** 2)), 1.0, places=12)
            self.assertGreater(float(np.max(abs(joy_amplitudes.imag))), 0.0)
            self.assertGreater(float(np.max(abs(kane_amplitudes.imag))), 0.0)
            self.assertNotEqual(joy["modelFamily"], kane["modelFamily"])
            self.assertFalse(np.allclose(models.distribution(joy, area), models.distribution(kane, area)))

    def test_phase_parameters_change_measurement_probabilities(self):
        for name in models.MODEL_FAMILIES:
            state = models.initial_state(name, 81)
            initial = models.distribution(state, "front")
            # Joy's even parameters are Rz phases; Kane's odd parameters are
            # site-specific coin phases. Test probability-level interference.
            index = 0 if name == "joy" else 1
            state["parameters"]["front"][index] += 0.7
            self.assertFalse(np.allclose(initial, models.distribution(state, "front")))

    def test_full_support_probabilities_and_single_valid_ticket(self):
        for name in models.MODEL_FAMILIES:
            state = models.initial_state(name, 42)
            prediction, probabilities = models.make_prediction(name, state, "26136", "2026-11-28", 123)
            self.assertEqual(prediction["modelVersion"], models.MODEL_VERSION)
            self.assertEqual(len(prediction["results"]), 1)
            ticket = prediction["results"][0]
            self.assertEqual(ticket["label"], f"{name.title()} Main")
            for area, (count, picks) in models.LIMITS.items():
                self.assertEqual(len(probabilities[area]), count)
                self.assertAlmostEqual(sum(probabilities[area]), 1.0, places=12)
                self.assertTrue(all(value >= models.SMOOTHING / count - 1e-15 for value in probabilities[area]))
                self.assertEqual(len(ticket[area]), picks)
                self.assertEqual(len(set(ticket[area])), picks)
                self.assertTrue(all(len(number) == 2 and 1 <= int(number) <= count for number in ticket[area]))

    def test_inference_is_pure_seeded_and_survives_serialization(self):
        for name in models.MODEL_FAMILIES:
            state = models.initial_state(name, "cycle-100")
            snapshot = copy.deepcopy(state)
            prediction = models.make_prediction(name, state, "26136", "2026-11-28", "locked-seed")
            repeated = models.make_prediction(name, json.loads(json.dumps(state)), "26136", "2026-11-28", "locked-seed")
            self.assertEqual(prediction, repeated)
            self.assertEqual(state, snapshot)
            models.distribution(state, "front")
            self.assertEqual(state, snapshot)
            other = models.make_prediction(name, state, "26136", "2026-11-28", "another-seed")
            self.assertNotEqual(prediction[0]["results"], other[0]["results"])

    def test_training_changes_only_state_after_reveal_and_is_reproducible(self):
        for name in models.MODEL_FAMILIES:
            state = models.initial_state(name, 99)
            before = copy.deepcopy(state)
            other = json.loads(json.dumps(state))
            _prediction, probabilities = models.make_prediction(name, state, "26135", "2026-11-25", 1)
            first = models.train_on_draw(state, ACTUAL, probabilities)
            repeated = models.train_on_draw(other, ACTUAL, probabilities)
            self.assertEqual(state, other)
            self.assertEqual(first, repeated)
            self.assertEqual(state["observations"], 1)
            self.assertEqual(state["randomness"]["trainingCounter"], 1)
            self.assertNotEqual(state["parameters"], before["parameters"])
            self.assertEqual(first["updates"], 1)
            self.assertEqual(first["objective"], models.OBJECTIVE)
            self.assertTrue(math.isfinite(first["negativeLogLikelihoodBefore"]))
            for area in models.AREAS:
                change = np.asarray(state["parameters"][area]) - np.asarray(before["parameters"][area])
                change = (change + math.pi) % (2.0 * math.pi) - math.pi
                bound = first["learningRate"] * state["configuration"]["learning"]["maxGradientNormPerArea"]
                self.assertLessEqual(float(np.linalg.norm(change)), bound + 1e-12)
            models.validate_state(state)

    def test_failed_training_is_atomic(self):
        for name in models.MODEL_FAMILIES:
            state = models.initial_state(name, 88)
            before = copy.deepcopy(state)
            for actual in ({**ACTUAL, "back": [2, 2]}, {**ACTUAL, "front": [0, 2, 3, 4, 5]},
                           {**ACTUAL, "back": [2.5, 3]}, {**ACTUAL, "front": [True, 2, 3, 4, 5]}):
                with self.assertRaises(ValueError):
                    models.train_on_draw(state, actual)
                self.assertEqual(state, before)

    def test_validation_rejects_invalid_identity_dimensions_and_finiteness(self):
        state = models.initial_state("joy", 11)
        variants = []
        for key, value in (("name", "unknown"), ("modelVersion", "old"), ("modelFamily", models.MODEL_FAMILIES["kane"]),
                           ("backend", "quantum_hardware"), ("observations", -1), ("seed", True)):
            variant = copy.deepcopy(state)
            variant[key] = value
            variants.append(variant)
        for value in (float("nan"), float("inf"), "0.1", True):
            variant = copy.deepcopy(state)
            variant["parameters"]["front"][0] = value
            variants.append(variant)
        variant = copy.deepcopy(state)
        variant["parameters"]["back"].pop()
        variants.append(variant)
        variant = copy.deepcopy(state)
        variant["configuration"]["uniformSmoothing"] = 0
        variants.append(variant)
        variant = copy.deepcopy(state)
        variant["randomness"]["trainingCounter"] = 1
        variants.append(variant)
        for variant in variants:
            with self.assertRaises(ValueError):
                models.validate_state(variant)

    def test_finite_extreme_angles_and_exact_coin_period(self):
        for name in models.MODEL_FAMILIES:
            state = models.initial_state(name, 18)
            original = models.distribution(state, "front")
            for index in range(len(state["parameters"]["front"])):
                changed = copy.deepcopy(state)
                changed["parameters"]["front"][index] += 2.0 * math.pi
                self.assertTrue(np.allclose(original, models.distribution(changed, "front"), atol=1e-12))
            for area in models.AREAS:
                state["parameters"][area] = [1e300 if i % 2 else -1e300
                                               for i in range(len(state["parameters"][area]))]
                values = models.distribution(state, area)
                self.assertTrue(all(math.isfinite(value) and value > 0 for value in values))
            diagnostics = models.train_on_draw(state, ACTUAL)
            self.assertTrue(math.isfinite(diagnostics["negativeLogLikelihoodBefore"]))
            models.validate_state(state)


class TicketLikelihoodTests(unittest.TestCase):
    def test_exact_likelihood_matches_independent_brute_force(self):
        probabilities = [0.07, 0.13, 0.31, 0.49]
        expected = 0.0
        for order in itertools.permutations([1, 3, 4]):
            remaining = dict(enumerate(probabilities, 1))
            probability = 1.0
            for number in order:
                denominator = math.fsum(remaining.values())
                probability *= remaining.pop(number) / denominator
            expected += probability
        self.assertAlmostEqual(math.exp(models.ticket_log_probability(probabilities, [1, 3, 4])), expected, places=13)

    def test_unordered_set_probabilities_sum_to_one(self):
        probabilities = [0.03, 0.11, 0.19, 0.27, 0.40]
        total = sum(math.exp(models.ticket_log_probability(probabilities, list(ticket)))
                    for ticket in itertools.combinations(range(1, 6), 3))
        self.assertAlmostEqual(total, 1.0, places=12)

    def test_uniform_ticket_probability_is_combinatorial(self):
        for count, picks in ((35, 5), (12, 2), (5, 3)):
            likelihood = models.ticket_log_probability([1.0 / count] * count, list(range(1, picks + 1)))
            self.assertAlmostEqual(likelihood, -math.log(math.comb(count, picks)), places=12)

    def test_extreme_weights_zero_mass_and_complete_set(self):
        self.assertEqual(models.ticket_log_probability([0.2, 0.3, 0.5], []), 0.0)
        self.assertAlmostEqual(models.ticket_log_probability([1e300, 1e-300, 2e-300], [1, 2, 3]), 0.0, places=12)
        self.assertTrue(math.isfinite(models.ticket_log_probability([1e300, 1e-300, 2e-300], [2, 3])))
        self.assertEqual(models.ticket_log_probability([1, 0, 0], [2]), -math.inf)
        for weights, ticket in (([0, 0], [1]), ([1, -1], [1]), ([1, math.inf], [1]),
                                ([1, math.nan], [1]), ([1, 2], [1, 1]), ([1, 2], [0])):
            with self.assertRaises(ValueError):
                models.ticket_log_probability(weights, ticket)


if __name__ == "__main__":
    unittest.main()

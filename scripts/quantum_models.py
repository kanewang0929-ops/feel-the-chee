#!/usr/bin/env python3
"""Two distinct quantum probability models, simulated on a classical CPU.

Joy is a shallow circuit Born machine. Kane is a split-step quantum walk with
position-dependent complex coins. Neither model uses quantum hardware or claims
a predictive advantage for independent random draws.

Only ``train_on_draw`` changes model state. The chronological batch runner must
call it after revealing a draw; inference has no training or random-state side
effects. Training minimizes exact unordered-ticket negative log likelihood for
the same successive weighted-without-replacement sampler used by inference.
Official ticket hit counts are a separate evaluation metric.

Model-family references (the lottery adaptation is specific to this project):
https://arxiv.org/abs/1804.04168 -- quantum circuit Born machines
https://arxiv.org/abs/2504.13532 -- trainable split-step quantum walks
"""
from __future__ import annotations

import hashlib
import itertools
import math
from functools import lru_cache

import numpy as np


MODEL_VERSION = "v2.0-quantum-chronological"
MODEL_FAMILIES = {
    "joy": "quantum-circuit-born-machine",
    "kane": "split-step-quantum-walk",
}
BACKEND = "classical_statevector"
AREAS = ("front", "back")
LIMITS = {"front": (35, 5), "back": (12, 2)}
QUBITS = {"front": 6, "back": 4}
CIRCUIT_LAYERS = 2
WALK_STEPS = 3
SMOOTHING = 0.02
OBJECTIVE = "exact-unordered-ticket-negative-log-likelihood"


def _configuration(name: str) -> dict:
    return {
        "schemaVersion": 1,
        "model": (
            {
                "circuitLayers": CIRCUIT_LAYERS,
                "qubits": dict(QUBITS),
                "initialState": "uniform-superposition",
                "gates": "position-local-Rz-Ry-and-ring-CNOT",
                "eligibleBasisLabels": "zero-based-first-numberCount-states",
            }
            if name == "joy"
            else {
                "walkSteps": WALK_STEPS,
                "coinDimension": 2,
                "topology": "cycle-graph-in-numeric-label-order",
                "initialState": "uniform-position-and-coin-superposition",
                "coin": "position-dependent-full-angle-complex-SU2",
                "step": "coin1-shiftCoin1Forward-coin2-shiftCoin0Backward",
            }
        ),
        "areas": {
            area: {"numberCount": count, "pickCount": picks}
            for area, (count, picks) in LIMITS.items()
        },
        "uniformSmoothing": SMOOTHING,
        "sampler": "successive-weighted-without-replacement",
        "objective": OBJECTIVE,
        "learning": {
            "method": "bounded-SPSA",
            "updatesPerRevealedDraw": 1,
            "learningRate": 0.04,
            "learningRateDecayExponent": 0.602,
            "learningRateDecayScale": 1000.0,
            "perturbation": 0.05,
            "maxGradientNormPerArea": 3.0,
            "anglePeriod": 2.0 * math.pi,
        },
    }


def _parameter_count(name: str, area: str) -> int:
    return (
        CIRCUIT_LAYERS * QUBITS[area] * 2
        if name == "joy"
        else 2 * LIMITS[area][0] * 2
    )


def _seed(*parts) -> int:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _generator(seed: int) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(seed))


def initial_state(name: str, seed: int | str) -> dict:
    """Return a fresh JSON-serializable state; the two agents never share state."""
    if not isinstance(name, str) or name not in MODEL_FAMILIES:
        raise ValueError("Model name must be 'joy' or 'kane'.")
    resolved_seed = _seed(MODEL_VERSION, "initialization", name, seed)
    rng = _generator(resolved_seed)
    parameters = {}
    for area in AREAS:
        values = rng.normal(0.0, 0.035, size=_parameter_count(name, area))
        if name == "kane":
            # Each site has its own rotation and phase. Uniform coin parameters
            # alone would not break the symmetry of a uniform position state.
            values.reshape(2, LIMITS[area][0], 2)[:, :, 0] += math.pi / 4.0
        parameters[area] = values.tolist()
    state = {
        "name": name,
        "modelVersion": MODEL_VERSION,
        "modelFamily": MODEL_FAMILIES[name],
        "backend": BACKEND,
        "observations": 0,
        "parameters": parameters,
        "seed": resolved_seed,
        "configuration": _configuration(name),
        "randomness": {
            "generator": "numpy.PCG64",
            "seedDerivation": "sha256-domain-separated-v1",
            "trainingCounter": 0,
        },
    }
    validate_state(state)
    return state


def validate_state(state: dict) -> None:
    """Reject incompatible, malformed, or nonfinite persisted model packages."""
    if not isinstance(state, dict):
        raise ValueError("Model state must be an object.")
    name = state.get("name")
    if not isinstance(name, str) or name not in MODEL_FAMILIES:
        raise ValueError("Unknown quantum model name.")
    if state.get("modelVersion") != MODEL_VERSION:
        raise ValueError("Quantum model version mismatch.")
    if state.get("modelFamily") != MODEL_FAMILIES[name]:
        raise ValueError("Quantum model family does not match its agent.")
    if state.get("backend") != BACKEND:
        raise ValueError("This package requires the classical statevector backend.")
    observations = state.get("observations")
    if type(observations) is not int or not 0 <= observations < 2**63:
        raise ValueError("Model observations must be a nonnegative signed 64-bit integer.")
    seed = state.get("seed")
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError("Model seed must be an unsigned 64-bit integer.")
    if state.get("configuration") != _configuration(name):
        raise ValueError("Model configuration does not match the versioned contract.")
    randomness = state.get("randomness")
    if not isinstance(randomness, dict) or randomness != {
        "generator": "numpy.PCG64",
        "seedDerivation": "sha256-domain-separated-v1",
        "trainingCounter": observations,
    }:
        raise ValueError("Model randomness metadata or training counter is invalid.")
    parameters = state.get("parameters")
    if not isinstance(parameters, dict) or set(parameters) != set(AREAS):
        raise ValueError("Model parameters must contain front and back areas.")
    for area in AREAS:
        values = parameters[area]
        if not isinstance(values, list) or len(values) != _parameter_count(name, area):
            raise ValueError(f"Invalid {name} {area} parameter dimensions.")
        try:
            finite = all(type(value) in (int, float) and math.isfinite(value) for value in values)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError(f"Nonfinite or invalid {area} model parameters.")


@lru_cache(maxsize=None)
def _qubit_indices(qubits: int, qubit: int) -> tuple[np.ndarray, np.ndarray]:
    indices = np.arange(1 << qubits)
    zero = indices[(indices & (1 << qubit)) == 0]
    return zero, zero | (1 << qubit)


@lru_cache(maxsize=None)
def _cnot_permutation(qubits: int, control: int, target: int) -> np.ndarray:
    indices = np.arange(1 << qubits)
    return indices ^ (((indices >> control) & 1) << target)


def _joy_amplitudes(parameters: np.ndarray, area: str) -> np.ndarray:
    qubits = QUBITS[area]
    angles = parameters.reshape(CIRCUIT_LAYERS, qubits, 2)
    amplitudes = np.full(1 << qubits, 1.0 / math.sqrt(1 << qubits), dtype=np.complex128)
    for layer in angles:
        for qubit, (phase, rotation) in enumerate(layer):
            zero, one = _qubit_indices(qubits, qubit)
            phase_factor = np.exp(0.5j * phase)
            left = amplitudes[zero] / phase_factor
            right = amplitudes[one] * phase_factor
            cosine, sine = math.cos(rotation / 2.0), math.sin(rotation / 2.0)
            amplitudes[zero] = cosine * left - sine * right
            amplitudes[one] = sine * left + cosine * right
        for control in range(qubits):
            amplitudes = amplitudes[_cnot_permutation(qubits, control, (control + 1) % qubits)]
    return amplitudes


def _apply_coin(amplitudes: np.ndarray, angles: np.ndarray) -> np.ndarray:
    rotation, phase = angles[:, 0], angles[:, 1]
    cosine, sine = np.cos(rotation), np.sin(rotation)
    phase_factor = np.exp(1j * phase)
    left, right = amplitudes[0], amplitudes[1]
    # Full angles give each position's coin an exact 2*pi period, including
    # relative phases between different positions of the walker.
    return np.stack((cosine * left - sine * phase_factor.conj() * right,
                     sine * phase_factor * left + cosine * right))


def _kane_amplitudes(parameters: np.ndarray, area: str) -> np.ndarray:
    count = LIMITS[area][0]
    angles = parameters.reshape(2, count, 2)
    amplitudes = np.full((2, count), 1.0 / math.sqrt(2 * count), dtype=np.complex128)
    for _ in range(WALK_STEPS):
        amplitudes = _apply_coin(amplitudes, angles[0])
        amplitudes[1] = np.roll(amplitudes[1], 1)
        amplitudes = _apply_coin(amplitudes, angles[1])
        amplitudes[0] = np.roll(amplitudes[0], -1)
    return amplitudes


def _distribution(name: str, area: str, parameters: np.ndarray) -> np.ndarray:
    count = LIMITS[area][0]
    # Reducing arbitrary persisted finite angles prevents overflow in exp and
    # preserves both models' exact measurement-equivalent angular period.
    parameters = np.remainder(parameters, 2.0 * math.pi)
    if name == "joy":
        probabilities = np.abs(_joy_amplitudes(parameters, area)[:count]) ** 2
    else:
        probabilities = np.sum(np.abs(_kane_amplitudes(parameters, area)) ** 2, axis=0)
    mass = float(probabilities.sum())
    if not math.isfinite(mass) or mass <= 0.0:
        raise ValueError("Quantum model assigned no finite mass to eligible numbers.")
    probabilities = (1.0 - SMOOTHING) * probabilities / mass + SMOOTHING / count
    return probabilities / probabilities.sum()


def distribution(state: dict, area: str) -> list[float]:
    """Return first-choice categorical probabilities, not inclusion marginals."""
    validate_state(state)
    if area not in AREAS:
        raise ValueError("Area must be front or back.")
    return _distribution(state["name"], area, np.asarray(state["parameters"][area])).tolist()


def _sample_ticket(probabilities: np.ndarray, count: int, rng: np.random.Generator) -> list[str]:
    remaining = probabilities.copy()
    selected = []
    for _ in range(count):
        cumulative = np.cumsum(remaining)
        # Rounding must not put the draw at the closed upper endpoint, including
        # when a previously selected final label leaves a zero-mass suffix.
        threshold = min(rng.random() * cumulative[-1], np.nextafter(cumulative[-1], -np.inf))
        index = int(np.searchsorted(cumulative, threshold, side="right"))
        selected.append(index + 1)
        remaining[index] = 0.0
    return [f"{number:02d}" for number in sorted(selected)]


def make_prediction(name: str, state: dict, target_issue: str, target_date: str,
                    seed: int | str) -> tuple[dict, dict]:
    """Generate one reproducible ticket without altering the model or counters."""
    validate_state(state)
    if name != state["name"]:
        raise ValueError("Prediction agent does not match the provided state.")
    probabilities = {
        area: _distribution(name, area, np.asarray(state["parameters"][area]))
        for area in AREAS
    }
    rng = _generator(_seed(MODEL_VERSION, "prediction", name, state["seed"],
                           target_issue, target_date, seed))
    ticket = {"rank": 1, "label": f"{name.title()} Main"}
    for area, (_number_count, pick_count) in LIMITS.items():
        ticket[area] = _sample_ticket(probabilities[area], pick_count, rng)
    prediction = {
        "modelVersion": MODEL_VERSION,
        "modelFamily": MODEL_FAMILIES[name],
        "backend": BACKEND,
        "targetIssue": str(target_issue),
        "targetDate": str(target_date),
        "results": [ticket],
    }
    return prediction, {area: values.tolist() for area, values in probabilities.items()}


@lru_cache(maxsize=None)
def _orderings(count: int) -> np.ndarray:
    return np.asarray(list(itertools.permutations(range(count))), dtype=np.intp)


def _numbers(numbers, maximum: int, expected_count: int | None = None) -> list[int]:
    if not isinstance(numbers, (list, tuple)):
        raise ValueError("Ticket numbers must be a list.")
    result = []
    for number in numbers:
        if isinstance(number, str):
            if not number.isdigit():
                raise ValueError("Ticket numbers must be integer labels.")
            value = int(number)
        elif type(number) is int:
            value = number
        else:
            raise ValueError("Ticket numbers must be integer labels.")
        if not 1 <= value <= maximum:
            raise ValueError("Ticket number is outside its valid range.")
        result.append(value)
    if len(set(result)) != len(result):
        raise ValueError("Ticket numbers must be unique.")
    if expected_count is not None and len(result) != expected_count:
        raise ValueError("Ticket has an incorrect number of selections.")
    return sorted(result)


def ticket_log_probability(probabilities, numbers) -> float:
    """Exact log P(unordered set) for successive weighted sampling.

    Labels are one-based. Nonnegative weights need not sum to one. Summing all
    sampling orders in log space avoids both underflow and cancellation in
    ``1 - already_selected_mass``. At most seven selections are supported; the
    production ticket has five front and two back numbers.
    """
    values = np.asarray(probabilities, dtype=float)
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Probabilities must be a finite nonnegative vector.")
    if not (values > 0).any():
        raise ValueError("Probability vector has no positive mass.")
    selected = _numbers(numbers, values.size)
    if len(selected) > 7:
        raise ValueError("Exact ticket likelihood supports at most seven selections.")
    if not selected:
        return 0.0
    indices = np.asarray(selected, dtype=np.intp) - 1
    if (values[indices] == 0).any():
        return -math.inf
    included = np.zeros(values.size, dtype=bool)
    included[indices] = True
    log_weights = np.full(values.size, -math.inf)
    positive = values > 0
    log_weights[positive] = np.log(values[positive])
    outside = log_weights[~included]
    log_outside = float(np.logaddexp.reduce(outside)) if outside.size else -math.inf
    ordered = log_weights[indices][_orderings(len(selected))]
    remaining = np.logaddexp.accumulate(ordered[:, ::-1], axis=1)[:, ::-1]
    denominators = np.logaddexp(remaining, log_outside)
    log_orders = np.sum(ordered - denominators, axis=1)
    result = float(np.logaddexp.reduce(log_orders))
    # A complete set has probability one; tiny positive roundoff is harmless.
    return min(0.0, result)


def train_on_draw(state: dict, actual: dict, probabilities: dict | None = None) -> dict:
    """Apply one bounded, reproducible SPSA update after one revealed draw.

    All validation and finite calculations finish before committing state, so a
    rejected draw cannot partially train one area. Optional probabilities are
    pre-update diagnostics from inference; perturbed losses always use freshly
    evaluated quantum states. An individual noisy step need not reduce loss.
    """
    validate_state(state)
    if not isinstance(actual, dict):
        raise ValueError("Actual draw must be an object.")
    targets = {
        area: _numbers(actual.get(area), maximum, count)
        for area, (maximum, count) in LIMITS.items()
    }
    if probabilities is not None:
        if not isinstance(probabilities, dict) or set(probabilities) != set(AREAS):
            raise ValueError("Prediction probabilities require front and back areas.")
        for area, (maximum, _count) in LIMITS.items():
            values = np.asarray(probabilities[area], dtype=float)
            if (values.shape != (maximum,) or not np.isfinite(values).all()
                    or (values <= 0).any() or not math.isclose(float(values.sum()), 1.0, abs_tol=1e-10)):
                raise ValueError("Invalid pre-update prediction probabilities.")
    name, observations = state["name"], state["observations"]
    learning = state["configuration"]["learning"]
    rate = learning["learningRate"] / (
        1.0 + observations / learning["learningRateDecayScale"]
    ) ** learning["learningRateDecayExponent"]
    perturbation = learning["perturbation"]
    new_parameters, area_diagnostics = {}, {}
    for area in AREAS:
        parameters = np.remainder(np.asarray(state["parameters"][area], dtype=float), 2.0 * math.pi)
        rng = _generator(_seed(MODEL_VERSION, "SPSA", name, area, state["seed"], observations))
        delta = 2.0 * rng.integers(0, 2, size=parameters.size) - 1.0
        plus = _distribution(name, area, parameters + perturbation * delta)
        minus = _distribution(name, area, parameters - perturbation * delta)
        loss_plus = -ticket_log_probability(plus, targets[area])
        loss_minus = -ticket_log_probability(minus, targets[area])
        gradient = ((loss_plus - loss_minus) / (2.0 * perturbation)) * delta
        gradient_norm = float(np.linalg.norm(gradient))
        bound = learning["maxGradientNormPerArea"]
        if gradient_norm > bound:
            gradient *= bound / gradient_norm
        updated = (parameters - rate * gradient + math.pi) % (2.0 * math.pi) - math.pi
        current = (
            probabilities[area] if probabilities is not None
            else _distribution(name, area, parameters)
        )
        loss_before = -ticket_log_probability(current, targets[area])
        if not np.isfinite(updated).all() or not all(math.isfinite(value) for value in
                                                    (loss_before, loss_plus, loss_minus, gradient_norm)):
            raise ValueError("Nonfinite quantum training update.")
        new_parameters[area] = updated.tolist()
        area_diagnostics[area] = {
            "negativeLogLikelihoodBefore": loss_before,
            "perturbedLossPlus": loss_plus,
            "perturbedLossMinus": loss_minus,
            "gradientNormBeforeClipping": gradient_norm,
            "gradientClipped": gradient_norm > bound,
        }
    state["parameters"] = new_parameters
    state["observations"] = observations + 1
    state["randomness"] = {**state["randomness"], "trainingCounter": observations + 1}
    return {
        "objective": OBJECTIVE,
        "method": "bounded-SPSA",
        "updates": 1,
        "observation": observations + 1,
        "learningRate": rate,
        "negativeLogLikelihoodBefore": sum(
            entry["negativeLogLikelihoodBefore"] for entry in area_diagnostics.values()
        ),
        "areas": area_diagnostics,
    }

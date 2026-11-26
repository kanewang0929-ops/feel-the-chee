# Joy and Kane v2: chronological quantum model specification

Implementation version: `v2.0-quantum-chronological`. Simulation engine:
`joy-kane-quantum-sim-v2`. Both mathematical models run on the
`classical_statevector` backend. This document describes the implemented code;
a live ticket's own recorded model version determines whether that ticket was
produced by this version or by the earlier adaptive model.

## 1. Preserved simulation contract

A 100-simulation batch is exactly 100 complete chronological cycles over one
frozen, validated historical draw archive. One cycle is not one ticket, one
parameter trial, or an ensemble member.

Each cycle initializes separate Joy and Kane states from a deterministic cycle
seed. It learns from the first 200 draws as warm-up without adding them to
reported hit scores. Every later historical draw follows this order:

1. Expose only the preceding historical prefix.
2. Create exactly one valid ticket for Joy and one for Kane.
3. Seal the ticket records with the training cutoff and prediction identity.
4. Reveal the target's actual numbers.
5. Score the two sealed tickets.
6. Update each model from that revealed outcome.
7. Continue to the next historical draw.

Model state never transfers from the end of one cycle to the start of another.
All 100 metrics remain available. The checkpoint from **cycle 100** is selected
by a fixed rule after all 100 cycles pass validation. Its selection is independent
of the scores. There is no ensemble or search for the best historical seed.

## 2. Distinct model families

| Property | Joy | Kane |
| --- | --- | --- |
| Family | Quantum circuit Born machine | Split-step quantum walk |
| Family identifier | `quantum-circuit-born-machine` | `split-step-quantum-walk` |
| State | Complex qubit amplitudes | Complex position-and-coin amplitudes |
| Front domain | 6 qubits, first 35 basis labels eligible | 35 positions with a 2-state coin |
| Back domain | 4 qubits, first 12 basis labels eligible | 12 positions with a 2-state coin |
| Evolution | 2 layers of Rz/Ry rotations and ring CNOT gates | 3 split-step rounds with position-dependent SU(2) coins and conditional shifts |
| Parameters | 24 front + 16 back = 40 | 140 front + 48 back = 188 |
| Measurement | Squared amplitude magnitudes over eligible labels | Coin-marginalized position probabilities |

### Joy: circuit Born machine

Joy starts with a uniform superposition. Parameterized rotations and entangling
CNOT operations change complex amplitudes before measurement. Invalid basis
labels are removed and the remaining number distribution is normalized.

The model is a small application-specific circuit inspired by the quantum
circuit Born machine family. It is not a claim of quantum hardware execution or
of predictive effectiveness for lottery outcomes.

Reference: [Liu and Wang, Differentiable Learning of Quantum Circuit Born
Machine](https://arxiv.org/abs/1804.04168).

### Kane: split-step quantum walk

Kane starts with a uniform position-and-coin superposition. The model uses a
cycle graph in numeric-label order. Position-dependent complex SU(2) coin
operations and conditional forward/backward shifts create interference before
position measurement. The coin parameters vary by position, allowing the model
to break the symmetry of the uniform initial state.

The choice to put numeric labels on a cycle is a modeling assumption. It does
not imply a physical relationship between neighboring lottery numbers.

Reference: [Chang et al., Quantum Walks-Based Adaptive Distribution
Generation](https://arxiv.org/abs/2504.13532).

## 3. Ticket sampling and the learning objective

Each model has separate front and back distributions. A fixed 2% uniform mixture
keeps every valid label eligible. The sampler draws successively without
replacement, renormalizing over labels that remain available. It returns one
sorted set of five front numbers and one sorted set of two back numbers.

The probability of an **unordered** ticket is the sum of the probabilities of
all sampling orders that lead to its set. Training computes this exact set
probability rather than treating sorted positions as independently sampled
numbers or using a marginal-probability proxy.

The fitting objective is:

`negative log P(actual front set) - log P(actual back set)`.

After one actual draw is revealed, each agent takes one bounded SPSA update,
with separate front and back losses. The initial learning rate is 0.04, with
decay exponent 0.602 and scale 1000 observations; the symmetric perturbation is
0.05. Each area's gradient norm is capped at 3.0 and angles wrap with period
2π. These settings belong to the versioned configuration. There is no separate
optimizer job or silent live parameter adjustment.

The official result comparison remains **front hit count + back hit count** for
the single sealed ticket. Likelihood is the fitting objective; exact hits are
the public score. A noisy parameter update need not reduce loss on every draw,
and a better training likelihood is not proof of a future hit-rate advantage.

## 4. Training-only-in-batch boundary

Only the 100-cycle simulation process may update parameters. The live publisher
can read models, compute probabilities, sample a ticket, validate records and
calculate actual-result scores. None of these live operations trains a model.

The million-candidate weight optimizer, its persisted-weight reload, the old
formula predictor, and the separate research training workflow are absent from
the active prediction path.

The package identifies its normalized archive, engine digest, model versions,
cycle count, completed cycles, fixed selected cycle, configuration and model
states. A changed or incomplete archive, missing cycle, wrong engine, invalid
state or mismatched content identity makes the package ineligible.

## 5. Live comparison and publication gate

The gate has explicit public states:

| State | Meaning |
| --- | --- |
| `awaiting_result` | Keep the current sealed tickets while waiting for their verified actual draw. |
| `awaiting_batch` | The next ticket is pending until a complete eligible 100-cycle package is available. |
| `prediction_locked` | A new Joy and Kane ticket pair has been generated and sealed. |
| `blocked` | Validation prevents publication; no substitute ticket is issued. |

When a result arrives, the publisher scores the **exact tickets originally
issued**, appends the comparison to the live ledger, and makes the result part
of the archive required for the next package. It generates the next tickets only
after an eligible batch includes that result. Missing or stale packages leave
the next prediction pending.

A repeated run does not reroll an unresolved ticket or duplicate its score.
If a draw had no genuinely issued prediction, the ledger records that absence.
Historical replay predictions are never reconstructed as prospective evidence.

New live tickets must be sealed strictly before 21:00 Asia/Shanghai on the
target draw date, using the official sales deadline. The publisher checks the
clock before and after inference; crossing the deadline blocks the new lock.
Already sealed tickets remain unchanged while results are pending. Historical
lock validation uses the former 20:00 deadline for dates before January 1, 2023.
The gate exports its cutoff, policy and official source URL.

The runtime can be upgraded while a previous ticket remains unresolved. During
that transition, `runtimeVersion` is v2 and the published `modelVersion` can be
`legacy-locked-prediction`. The old ticket's model family, timestamp and numbers
remain intact. `trainedBatch` separately describes a ready quantum package; it
never changes the provenance of the current lock.

## 6. Public reporting

The website has exactly two official prediction cards. Pending and blocked
states suppress tickets, even if stale ticket fields remain in a data object.
The display requires a matching issue/date lock and a single valid ticket.
There is no formula or browser-generated fallback.

The operations page distinguishes:

- the model states behind the current sealed predictions;
- the latest eligible 100-cycle package and its fixed final checkpoint;
- the verified archive cutoff;
- the last genuinely scored live draw;
- historical batch scores labeled by engine.

The quantum score chart includes only `joy-kane-quantum-sim-v2` batches. Legacy
adaptive scores remain in the table with explicit engine labels. The old
holdout report is retained as a legacy record and is not presented as an
evaluation of either new quantum model. The retired research registry is not
fetched as an active training source.

## 7. Limits of the experiment

These models simulate quantum state evolution on classical computers. They do
not use quantum hardware or certified physical quantum randomness. Under a
fair, uniform, independent draw process, past results provide no information
that makes one valid future ticket more likely than another. Historical replay
metrics therefore remain training diagnostics; genuinely prospective sealed
predictions are the evidence for later empirical comparison.

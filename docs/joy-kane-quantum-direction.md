# Joy and Kane: confirmed simulation contract and quantum model direction

Status: architecture direction, recorded 26 November 2026. The optimizer-removal
release does not implement or deploy the quantum models or the batch-to-live
training pipeline described below.

## Confirmed requirements

- Official predictions must come only from Joy and Kane.
- The training workload is 100 complete cycles of chronological simulation over
  the historical draw archive. One cycle is one full historical replay, not one
  ticket, one parameter-search trial, or an assumed ensemble member.
- Within each cycle, preserve the established sequence: use the preceding
  history, create exactly one ticket per agent, seal both tickets, reveal the
  actual result, score, update each model, then move to the next historical draw.
- Keep the existing warm-up and valid ticket rules: five distinct front numbers
  from 1–35, and two distinct back numbers from 1–12.
- Add every new verified actual draw to the archive used by subsequent cycles.
- All model training in the target architecture must occur inside those cycles.
- Score the current sealed live predictions against the actual draw before
  issuing the next predictions. Preserve the actual issued tickets and their
  original provenance.
- Joy and Kane must use different quantum model families.
- Remove the separate million-candidate optimizer and persisted optimizer
  weight reloads. Retain old records as historical evidence.

The existing runner starts each cycle with isolated state and a reproducible
seed. This removal release preserves that behavior. The previously suggested
equal-weight ensemble was a proposal, not an agreed part of the cycle definition,
and is not introduced by this release.

## Proposed distinct model families

### Joy: quantum circuit Born machine

Use a shallow parameterized circuit whose rotations and entangling operations
produce complex amplitudes. Measurement probabilities come from squared
amplitude magnitudes. A small classical statevector simulation can use six
qubits for front-number labels and four for back-number labels. Invalid labels
must be excluded before generating a valid ticket without replacement.

This is a proposed adaptation of the quantum circuit Born machine family,
not evidence of lottery predictive effectiveness. Reference:
[Liu and Wang, Differentiable Learning of Quantum Circuit Born Machine](https://arxiv.org/abs/1804.04168).

### Kane: trainable split-step quantum walk

Use position-and-coin amplitudes over 35 front positions and 12 back positions.
Parameterized coin operations and conditional shifts move and interfere with
amplitudes; position measurement yields a number distribution. The model must
be capable of breaking a uniform symmetry, and its chosen topology must be
documented as a modeling assumption.

This is a different parameterization from Joy's circuit. Reference:
[Chang et al., Quantum Walks-Based Adaptive Distribution Generation](https://arxiv.org/abs/2504.13532).

Both proposals initially simulate quantum mathematics on ordinary computers.
They do not imply quantum hardware or a quantum-certified random source.
Neither model gains information about a fair, independent future draw merely
by using quantum mathematics.

## Implementation decisions still required

Specify the circuit and walk layouts, bounded after-reveal parameter updates,
and exact valid-ticket sampling rules. Keep official scoring based on exact
front and back matches. Any different fitting objective must be stated
explicitly rather than silently replacing that scoring contract.

Specify which reproducible trained checkpoint produces the live forecast. Do
not select the best retrospective seed or introduce an ensemble by assumption.
If cycle state carryover is later introduced, later-cycle scores must be marked
as training scores because those states have already encountered the archive.

The target publication gate is: compare and record the previous live result;
add it to the verified archive; complete a qualifying 100-cycle batch; publish
the resulting versioned model packages; generate and seal the next tickets.
No new ticket is issued when the required result or batch is missing.

## What the removal release changes

The release removes the million-candidate search, its cached weight imports,
obsolete executable trainers, workflow settings, and active optimizer UI.
It preserves historical records, the chronological replay implementation,
and current prediction locks. The existing live replay and separate research
training remain implementation gaps relative to the target batch-only design;
this release must not be reported as completing that migration.

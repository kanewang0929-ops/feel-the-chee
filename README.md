# Feel the Chee · Joy and Kane

A static prediction and audit website served by Render. GitHub Actions validates
the draw archive, runs chronological training and publishes content-addressed
model packages and sealed prediction records. The frontend never generates
replacement numbers.

## Official predictions

Only **Joy** and **Kane** produce official tickets. Each supplies five distinct
front numbers from 1–35 and two distinct back numbers from 1–12. The formula
forecast panel and its runtime have been removed from the public page.

- **Joy:** quantum circuit Born machine.
- **Kane:** split-step quantum walk.
- Both use classical statevector simulation. This is not quantum hardware or a
  quantum-certified source of randomness.
- Existing unresolved tickets retain their original model version. A quantum
  runtime or a ready quantum training package never relabels an old ticket.

## The 100-simulation definition

One simulation is one complete chronological cycle through the verified draw
archive. A batch contains exactly 100 such cycles, each with fresh independent
model state and a reproducible seed.

Inside each cycle, the first 200 draws are learned as warm-up and excluded from
reported hit scores. For every subsequent draw: predict exactly one ticket per
agent, seal the predictions, reveal the actual result, score the tickets, update
the models, then continue. No future outcome enters an earlier prediction.

All parameter learning occurs inside these cycles. The fixed final checkpoint
from cycle 100 supplies the next live models after all 100 cycles pass their
checks. The selection rule is declared in advance; there is no best-seed choice
or ensemble. All 100 cycle metrics are retained.

Training minimizes exact unordered-ticket negative log likelihood after each
reveal. The public comparison score remains exact front matches plus exact back
matches. The million-cycle optimizer and separate research training workflow
are retired.

## Closed-loop publication

1. Keep the current Joy and Kane tickets sealed until the actual draw is known.
2. Validate the result and record the comparison with those exact tickets.
3. Include the result in the verified archive used by the 100-cycle batch.
4. Validate the completed package, archive identity, engine identity and final
   cycle selection.
5. Generate and seal one next-draw ticket from each trained model.

The live publisher does not train. Missing results, incomplete or stale batches,
or failed validation leave the next prediction pending. Reruns are idempotent:
they do not change an unresolved ticket or score a result twice. A missing prior
prediction is recorded as missing, never reconstructed as a live forecast.

New tickets must be sealed before 21:00 Beijing time on the target draw date.
The publisher checks the clock again after inference. A delayed result feed
cannot permit a late ticket; an already sealed ticket stays locked.

The scheduled 100-cycle batch and draw-sync jobs retain their workflow-defined
cadence. A batch can prepare a model package while a ticket is pending, but it
cannot replace that ticket.

## Website

- [Prediction center and historical draw archive](./index.html)
- [Model operations](./simulation.html)
- [Model and protocol specification](./docs/joy-kane-quantum-direction.md)

The homepage displays the publication gate and exact ticket provenance. Browser
edits to archive rows remain local to the browser and never change training data.
The operations view separates current sealed models from eligible batch models,
shows the actual-draw gate, and records each batch's model engine. Quantum charts
exclude older adaptive-model runs. Earlier holdout reports remain explicitly
labeled legacy and do not validate the quantum models.

## Main implementation

- `scripts/quantum_models.py`: distinct Joy and Kane mathematical models, valid
  ticket sampling and bounded after-reveal updates.
- `scripts/run_simulation_batch.py`: 100 complete chronological cycles and the
  fixed final-cycle package.
- `scripts/quantum_protocol.py`: archive, model-package and engine contracts.
- `scripts/joy_kane_live.py`: actual-result comparison, append-only live evidence,
  package checks and prediction locking; no parameter training.
- `scripts/publish_simulation_dashboard.py`: compact public batch history.

## Local checks

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests
node --test tests/test_homepage.js tests/test_dashboard_ui.js
```

Render serves the committed static files. Scheduled compute runs in GitHub
Actions; no additional Render worker or database is required.

## Interpretation

The 100 cycles replay the same historical archive. They are not 100 independent
lottery histories. Quantum mathematics can model and sample probabilities; it
does not provide information about a fair, independent future draw. Historical
training results and genuinely prospective live results are reported separately.

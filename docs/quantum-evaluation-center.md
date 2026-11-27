# Phase 4: Quantum Model Evaluation Center

The evaluation center is read-only. It does not create tickets, select
checkpoints, change model parameters, or launch any training. The existing
100 independently initialized chronological cycles and fixed cycle-100
checkpoint remain the sole training path.

After each live publication, the evaluator revalidates the append-only ledger
hash chain, archive boundary, sealed tickets and exact scores using the live
ledger's existing checks. It compares coverage, scored/missing counts and
pending prediction ID with the published dashboard. The report and publication
records are committed together. On an evaluation-specific validation error the
report is explicitly unavailable; the evaluator does not change the live gate.
The UI also checks the publication timestamp, archive digest and counts before
showing metrics.

Cohorts are separated by the pair of actual sealed model versions and engine
digest. A pending legacy prediction remains legacy even if a quantum package
is ready. Missing predictions are counted separately; historical replays do not
enter live results. Zero scored observations produce null means, not zeros.

For a uniform independent draw, exact hits follow independent hypergeometric
distributions (35,5,5) and (12,2,2) for the two areas. Convolution gives the
exact summed-hit reference for each agent's number of scored draws. The
displayed 95% range is a central chance reference, not a confidence interval for
the model's true mean. The one-sided tail is descriptive at the observed sample
size, not a sequential significance or release test. Do not pool the two agents
or the 100 replay seeds as independent real-world observations.

Negative log likelihood is computed on the actual unordered number sets using
the originally sealed first-choice probability vectors and the existing exact
without-replacement likelihood. The uniform reference is log(C(35,5)*C(12,2)).
Legacy or unknown versions have no likelihood metric. Current-engine
distributions are checked against the stored model state; old engine vectors
are not reinterpreted with new model code.

Rolling averages appear only once their full 10, 30 or 100 scored observations
exist within the cohort. Angular RMS drift compares consecutive scored sealed
quantum checkpoints within the same cohort, with angles wrapped modulo 2pi.
It is not an estimate of a single gradient step or monotonic learning.

The historical cycle browser uses the existing simulation feed, not a new
trainer or a new simulation run. It displays the retained individual rows,
separates legacy engines, and labels the predeclared final quantum checkpoint.

## Next gates (not implemented by Phase 4)

- Verify the first complete actual-result -> 100-cycle -> new sealed quantum
  prediction transition using the real draw, not only fixtures.
- Predeclare a prospective champion/challenger protocol. Any learning of a
  challenger must occur within the authorized 100-cycle process; do not
  resurrect an independent trainer. Keep challenger predictions out of the
  official prediction cards and record them before results. Choose the sample
  size and review rule before examining outcomes; account for repeated testing
  and multiple comparisons. Never select a best historical seed.
- Require explicit review, provenance and rollback before model promotion.
  No autonomous promotion is enabled by this phase.

Fair independent lottery draws have no established predictive advantage from
past results. Quantum mathematics is simulated on classical hardware.

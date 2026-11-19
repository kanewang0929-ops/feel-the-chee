# Feel the Chee: daily simulation dashboard

## Production dashboard

The static dashboard is served by the existing Render Static Site at `/simulation.html". It reads the latest 30 batch records from `data/simulation-dashboard-history.json" on the separate `simulation-data" Git branch. This keeps routine result publishing out of the Render `main" branch and avoids a daily static-site redeploy.

## Daily schedule

- Workload: 100 independently seeded complete historical simulations per batch.
- Schedule: `20 18 * * *" UTC, equal to 03:20 Asia/Seoul.
- First batch: automatically triggered by the production merge push.
- Other triggers: manual `workflow_dispatch" and the daily schedule.
- Runner: one GitHub Actions hosted Ubuntu runner, sequential execution, 180-minute job limit.
- Concurrency: one batch at a time; a running batch is not cancelled by a later trigger.

## Publication and retention

On completion, the workflow publishes aggregate Joy/Kane score statistics, seed-level ranges, archive SHA-256, audit counts, runtime and run links. The dashboard retains the 30 latest batch records. The downloadable workflow artifact retains the compact per-simulation summary and one representative full trace for 30 days.

Failed or cancelled runs also publish a status record when the runner reaches the reporting step. Workflow logs remain the source of truth for diagnosing failed runs.

## Isolation and interpretation

The batch runner uses a separate temporary data directory for every simulation. It does not read or write the live prediction lock, live prediction ledger, or live model state. Prediction, result and audit records are checked chronologically for every replay.

These 100 simulations replay the same historical draw archive with different seeds. They measure seed sensitivity, implementation stability and historical replay outcomes. They are not 100 independent lottery histories, and a high-scoring simulation is not evidence of a future predictive edge. The dashboard displays the theoretical random-ticket expectation as context, not as a performance guarantee.

## Infrastructure

The dashboard and schedule use the existing static Render site and GitHub Actions. No Render web service, database, object storage, paid worker or new persistent infrastructure is provisioned for this implementation. The first 100-run production batch supplies the actual runtime and resource measurements for any later optimization decision.

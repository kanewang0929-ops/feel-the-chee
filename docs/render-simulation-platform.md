# Render-Native Simulation Platform: Joy & Kane

Status: implementation design. No paid services have been created or scaled.

## Decision

Keep the Feel the Chee frontend and application backend on Render. Do not provision AWS.

Use Render's native services:
- Static Site: existing website.
- Web Service: public read-only API for the website and protected admin endpoints.
- Render Workflows: distributed simulation orchestration and task execution.
- Cron Job: daily trigger for the workflow (Workflows does not currently provide native scheduling).
- Render Postgres: persistent operational database and model registry.
- Render Key Value: optional only if a conventional background-worker queue is later needed; Workflows already manages its own task queue.

For large compressed Parquet audit/summary files, use an S3-compatible object store such as Cloudflare R2 as an optional external file-storage layer. This does not move compute or the app off Render. If the requirement is absolutely no external storage vendor, start with Postgres for summaries and selected audit records, but review storage growth and query performance before scaling to one million runs every day.

## Goals

- Preserve the current Render-hosted website and URL.
- Keep the current draw synchronization and live prediction workflow operating during migration.
- Run 1,000,000 independent complete chronological historical replays per daily batch.
- Each agent emits exactly one official ticket per draw: 5 front numbers (1-35) and 2 back numbers (1-12).
- Seal both agents' predictions before revealing the target draw, then score and update each agent independently.
- Store a compact summary for every run; retain full draw-level traces only for the global best run and canonical published-model audits.
- Make jobs deterministic, retryable, observable, and safe to run in parallel.

## Current-state findings

- Current `render.yaml` configures a static site only; there is no application backend or persistent database in the repository's Render configuration.
- The existing GitHub Actions workflow synchronizes draws and runs the current Joy/Kane script successfully, but GitHub Actions should not host the million-replay workload.
- The current `scripts/joy_kane_duel.py` originally had `PICK_COUNT = 3`. The implementation branch changes it to `PICK_COUNT = 1` and adds contract tests.
- Existing JSONL files should not remain the long-term storage system for large simulation output.
- The current Render site should remain live while the new backend is built and validated in parallel.

## Proposed Render architecture

1. **Render Cron Job** starts once daily and triggers the workflow through the Render SDK/API. The cron command should submit the batch and exit quickly. Render Cron Jobs have a single-run guarantee and a 12-hour maximum, so the heavy computation belongs in Workflows, not in the cron process.
2. **Render Workflows** orchestrates the daily batch. It manages task queuing, on-demand task instances, retries, and task lifecycle.
3. **Parallel workflow tasks** process deterministic shards. Do not create one million individual task runs. Each task handles a configurable chunk of simulation IDs, for example 500-2,000 runs per task during initial benchmarking. Chunk size must be tuned from real throughput.
4. **Render Postgres** stores batch metadata, shard status, model registry, promotion decisions, official predictions, and selected dashboard summaries.
5. **S3-compatible object storage (optional but recommended at scale)** stores date-partitioned Parquet summaries for all runs, immutable draw archive snapshots, and compressed full audit files for selected simulations/models.
6. **Render Web Service** exposes the API to the existing static site over HTTPS. Services in the same Render region can use private networking for database and internal service connections.
7. **Cloud monitoring and budget controls** use Render service/workflow metrics, run history, alerts where available, workspace limits, and billing usage. Add application-level limits and a manual kill switch.

### Render Workflows limits to design around

Render Workflows is currently documented as public beta. The current documentation describes:
- Task runs can execute for up to 24 hours (default 2 hours unless configured).
- Hundreds of concurrent task instances, subject to workspace plan and purchased concurrency.
- Base concurrent task runs: Hobby 20, Pro 50, Scale 100; documented maximums with added concurrency: Hobby 200, Pro 200, Scale 300, Enterprise 300+.
- Workflow task compute currently includes 0.5 CPU / 512 MB, 1 CPU / 2 GB, and 2 CPU / 4 GB plans; larger plans can be requested.
- Added concurrency has a separate monthly charge, and task compute is billed by instance type and runtime.
- Workflows currently supports Python and TypeScript tasks.
- Workflows does not yet provide native scheduling; use a Render Cron Job to trigger the daily workflow.

These limits and prices can change. Recheck the current Render docs and dashboard before provisioning or approving spend. Do not assume the maximum concurrency is included in the base workspace plan.

## Batch design

A daily batch contains one million independent simulations. Each simulation has:
- unique simulation ID;
- deterministic seed derived from batch ID, simulation ID, and engine version;
- independent initial Joy and Kane states;
- immutable engine/configuration version;
- fixed archive digest and warm-up setting.

The workflow creates a bounded number of shard tasks. Each shard processes a range of simulation IDs and writes output in bulk. Shard size should be selected after benchmark runs. The first pilots should use 100, 1,000, and 10,000 simulations before testing larger batches.

## Strict chronological simulation flow

1. Freeze a versioned draw archive and calculate its SHA-256 digest.
2. Create a batch record with engine version, archive digest, warm-up count, run count, and configuration.
3. Dispatch independent simulation IDs to workflow shard tasks.
4. For each historical target draw, expose only the chronological prefix to the prediction function.
5. Generate one Joy ticket and one Kane ticket.
6. Persist/seal the prediction event before loading the target outcome into the scoring step.
7. Reveal and score the actual result; update the two agent states independently.
8. Continue to the next draw.
9. Write one compact summary per simulation, including seed, configuration, scores, head-to-head record, model-state fingerprints, and runtime.
10. Each shard may stage its local champion trace temporarily. A final aggregation task selects the global champion and removes non-winning temporary traces.
11. Aggregate daily metrics, evaluate the promotion policy, and publish the selected model through the API.

## Option B storage policy

### Every simulation

Store one compact summary per simulation. Recommended at scale: write summaries in bulk to date-partitioned Parquet files in object storage. Keep a compact top-N ranking and daily aggregate in Postgres for fast dashboard queries.

Fields:
- batch_id, simulation_id, seed, engine_version, config_hash;
- archive_digest, warmup_draws, evaluated_draws;
- Joy and Kane front/back/total hit counts and average hits per draw;
- Joy/Kane wins, losses, and ties;
- training, validation, and untouched-test metrics;
- final Joy/Kane model-state fingerprints;
- worker/shard ID, runtime, completion status, and timestamp.

### Selected full traces

Retain full draw-level prediction/result/learning records only for:
- the global best simulation selected under the documented validation policy;
- canonical audits for each promoted/published Joy model;
- canonical audits for each promoted/published Kane model.

Shard-local champion traces are temporary staging objects and are deleted after global aggregation. Do not commit bulk simulation output to Git.

## Database design

Postgres tables:
- `simulation_batches`: batch ID, date, requested/completed/failed runs, status, archive digest, engine version, configuration, timestamps.
- `simulation_shards`: shard ID, batch ID, workflow run ID, run range, status, attempts, output object key, runtime.
- `simulation_top_runs`: top-ranked run summaries for dashboard display.
- `daily_aggregates`: daily batch metrics and agent comparison.
- `model_versions`: agent, version, configuration hash, model-state reference, validation metrics, test metrics, promotion status.
- `promotion_events`: candidate version, previous version, decision, policy version, evidence, timestamp.
- `published_predictions`: target issue/date, prediction ID, model version, sealed ticket, history digest, lock timestamp.
- `audit_objects`: batch/model reference, audit type, object key, checksum, retention status.

Use bulk inserts/upserts and partitioning for high-volume relational data. Avoid one transaction per draw. Add indexes only for actual dashboard/API query patterns.

## Optional object storage layout

- `draw-archives/YYYY-MM-DD/<archive-digest>.json.gz`
- `simulation-summaries/date=YYYY-MM-DD/batch=<batch-id>/part-*.parquet`
- `simulation-staging/<batch-id>/<shard-id>/champion-trace.jsonl.gz`
- `simulation-champions/<batch-id>/<simulation-id>/trace.jsonl.gz`
- `model-audits/<agent>/<model-version>/walk-forward.jsonl.gz`

Use lifecycle rules for temporary staging and retained audit objects. If using Cloudflare R2, keep credentials in Render secret environment variables and access it through the S3-compatible API.

## API outline

- `GET /health`
- `GET /v1/simulations/latest`
- `GET /v1/simulations/{batch_id}`
- `GET /v1/simulations/{batch_id}/summary`
- `GET /v1/simulations/{batch_id}/top-runs`
- `GET /v1/agents/current`
- `GET /v1/predictions/current`
- `GET /v1/models/{agent}/{version}/audit`

Administrative batch creation and model promotion endpoints require authentication. Public website endpoints are read-only.

## Evaluation and promotion safeguards

- Treat lottery draws as independent random events. Historical frequencies, overdue status, or patterns are not treated as evidence that a number has a higher probability in the next draw.
- Every prediction uses only information available before the target draw.
- Prediction and result events remain separate. The outcome cannot be passed into ticket-generation functions.
- Every run is reproducible from its seed, engine version, configuration hash, and archive digest.
- Use chronological training, validation, and untouched-test periods. Candidate selection may use validation only. Test metrics are reported but never used to select or promote a candidate.
- Do not promote a model simply because it is the highest-scoring one among one million trials. Use predeclared promotion thresholds, compare against a random-ticket baseline, and report uncertainty and the number of candidates tested.
- After candidate configuration is frozen, generate the canonical published model by a clean chronological replay through the available archive. Preserve that replay as the model's official audit.

## Security and reliability

- Keep database credentials and object-storage keys in Render secret environment variables.
- Use Render private networking for service-to-database communication.
- Make writes idempotent with unique keys such as (batch_id, simulation_id) and (batch_id, shard_id).
- A retried shard must not duplicate summaries or overwrite a newer published model.
- Checkpoint at shard boundaries and write outputs atomically.
- Add explicit maximum batch size, maximum concurrency, daily spend ceiling, and a manual kill switch.
- Keep the live prediction service isolated from heavy simulation tasks so the website remains responsive.

## Rollout

1. Correct the one-ticket contract and add tests for prediction sealing, chronological cutoff, independent states, scoring, and reproducibility.
2. Refactor the simulation engine into a reusable workflow task and benchmark one complete replay.
3. Run local/container pilots with a small number of shards.
4. Add Render Postgres schema and API service while leaving the existing static site unchanged.
5. Add Render Workflow and a daily Render Cron trigger with conservative concurrency.
6. Run 100, 1,000, and 10,000-run pilots. Measure runtime, CPU, memory, storage, retry behavior, and cost.
7. Enable the million-run daily schedule only after the benchmark and spend review.

## Before provisioning or scaling

Confirm:
- the existing Render workspace plan and region;
- the approved daily/monthly spend ceiling;
- whether external S3-compatible object storage (recommended for bulk Parquet and full audit files) is acceptable.

No paid services should be created or scaled until the user approves the cost and configuration.

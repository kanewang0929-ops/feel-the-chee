# AWS Simulation Platform: Joy & Kane

Status: architecture approved for implementation planning. No AWS resources are provisioned by this document.

## Goals

- Preserve the existing Render-hosted static website.
- Keep the current draw-sync/live-prediction workflow running during migration.
- Run 1,000,000 independent, complete chronological historical replays per daily batch.
- Each agent emits exactly one official ticket per draw: 5 front numbers (1-35) and 2 back numbers (1-12).
- Seal both agents' predictions before revealing the target draw, then score and update each agent independently.
- Store a compact result summary for every run; retain full draw-level traces only for the global best run (after batch comparison) and canonical published-model audits.
- Make jobs deterministic, retryable, observable, and safe to run in parallel.

## Current-state findings

- Render currently serves a static site only (`render.yaml`); it has no application backend or persistent database.
- The existing GitHub Actions workflow synchronizes draws and runs the current Joy/Kane script successfully, but it is not a suitable host for the million-replay workload.
- The current `main` branch still has `PICK_COUNT = 3`; the feature branch changes this to `PICK_COUNT = 1` and adds passing contract tests. The one-ticket change must be merged before the new baseline is used.
- Existing Joy/Kane audit and JSONL files are already large enough that they should not remain the long-term storage system.
- The latest scheduled workflow checked during planning completed successfully. The current `main` branch was left unchanged.

## AWS deployment region

- Initial target region: **US East (N. Virginia), `us-east-1`**.
- Keep the AWS region configurable through Terraform variables and deployment environment settings.
- The region is a planning default; actual provisioning remains blocked until the AWS account, access, and spending ceiling are confirmed.

## Proposed AWS architecture

1. **EventBridge Scheduler** starts a daily orchestration workflow.
2. **Step Functions** creates a batch record, starts the AWS Batch array job, waits for completion, and invokes result aggregation.
3. **AWS Batch** runs containerized simulation workers on an EC2 compute environment. Use Spot capacity where appropriate, with configurable limits and an On-Demand fallback policy.
4. **Amazon S3** stores:
   - one compact summary for every simulation, partitioned by batch date;
   - temporary per-worker champion traces during aggregation;
   - the retained global-best simulation trace;
   - canonical full audits for each published Joy/Kane model version;
   - immutable draw-archive snapshots and checksums used by each batch.
5. **Amazon RDS for PostgreSQL** stores operational metadata: batch status, shard/job status, model registry, promotion decisions, canonical prediction metadata, and S3 object references. It should not receive one database transaction per historical draw.
6. **Amazon ECS on Fargate** hosts the API used by the Render frontend.
7. **CloudWatch** collects logs, metrics, alarms, and cost/throughput telemetry. AWS Budgets and service quotas provide spending and capacity guardrails.

### Batch sizing

AWS Batch array jobs support up to 10,000 child jobs. A starting design is one daily array job with up to 10,000 child workers, each processing a configurable chunk of simulations. The initial chunk size is a benchmark parameter, not a fixed production assumption. The worker count, vCPU, memory, Spot percentage, and chunk size must be chosen from measured throughput and cost.

Each simulation receives a deterministic unique seed derived from the batch ID, simulation ID, and engine version. Each run initializes its own Joy and Kane state. No state is shared between simulations.

### Processing flow

1. Freeze a versioned draw archive and calculate its SHA-256 digest.
2. Create a batch record with engine version, archive digest, warm-up count, run count, and configuration.
3. Dispatch independent simulation IDs to workers.
4. For each historical target draw, expose only the chronological prefix to the prediction function.
5. Generate one Joy ticket and one Kane ticket.
6. Persist/seal the prediction event before loading the target outcome into the scoring step.
7. Reveal and score the actual result; update the two agent states independently.
8. Continue to the next draw.
9. Write one compact summary per simulation, including seed, configuration, scores, head-to-head record, model-state fingerprints, and runtime.
10. Each worker may stage its local champion trace temporarily. The aggregator selects the global champion and removes non-winning temporary traces.
11. Aggregate daily metrics, update the model registry only if the promotion policy passes, and publish the selected model through the API.

## Option B storage policy

### Every simulation (compact summary)

Store one record per simulation in a date-partitioned Parquet dataset in S3. Fields should include:

- batch_id, simulation_id, seed, engine_version, config_hash;
- archive_digest, warmup_draws, evaluated_draws;
- Joy and Kane front/back/total hit counts and average hits per draw;
- Joy/Kane wins, losses, and ties;
- train, validation, and untouched-test metrics;
- final Joy/Kane model-state fingerprints;
- worker/shard ID, runtime, completion status, and timestamp.

Keep a small top-N ranking and daily aggregates in PostgreSQL for fast dashboard queries. Use Athena or an equivalent analytical query path for the full Parquet history.

### Selected runs (full trace)

Retain full draw-level prediction/result/learning records only for:
- the global best simulation selected under the documented validation policy;
- canonical audits for each promoted/published Joy model;
- canonical audits for each promoted/published Kane model.

Worker-local champion traces are temporary staging objects and are deleted after global aggregation. Do not commit bulk simulation output to Git.

## Evaluation and promotion safeguards

- The lottery is treated as an independent random process. Historical frequencies, overdue status, or patterns are not treated as evidence that a number has a higher next-draw probability.
- All predictions use only information available before the target draw.
- Prediction and result events remain separate. The result/outcome cannot be passed into ticket-generation functions.
- Every run is reproducible from its seed, engine version, configuration hash, and archive digest.
- Use chronological training, validation, and untouched-test periods. Candidate selection may use validation only. Test metrics are reported but never used to select or promote a candidate.
- After the candidate configuration is frozen, generate the canonical published model by a clean chronological replay through the available archive. Preserve that replay as the model's official audit.
- Do not promote a model simply because it is the highest-scoring one among one million trials. Use predeclared promotion thresholds and compare against a random-ticket baseline; report uncertainty and the number of candidates tested.

## Suggested data model

PostgreSQL tables:
- `simulation_batches`: batch ID, date, requested/completed/failed runs, status, archive digest, engine version, configuration, timestamps.
- `simulation_shards`: shard ID, batch ID, job ID, run range, status, attempts, output S3 key, runtime.
- `model_versions`: agent, version, configuration hash, model-state S3 key, validation metrics, test metrics, promotion status.
- `promotion_events`: candidate version, previous version, decision, policy version, evidence, timestamp.
- `published_predictions`: target issue/date, prediction ID, model version, sealed ticket, history digest, lock timestamp.
- `audit_objects`: batch/model reference, audit type, S3 key, checksum, retention status.

S3 layout (illustrative):
- `draw-archives/YYYY-MM-DD/<archive-digest>.json.gz`
- `simulation-summaries/date=YYYY-MM-DD/batch=<batch-id>/part-*.parquet`
- `simulation-staging/<batch-id>/<shard-id>/champion-trace.jsonl.gz`
- `simulation-champions/<batch-id>/<simulation-id>/trace.jsonl.gz`
- `model-audits/<agent>/<model-version>/walk-forward.jsonl.gz`

## API outline

- `GET /health`
- `GET /v1/simulations/latest`
- `GET /v1/simulations/{batch_id}`
- `GET /v1/simulations/{batch_id}/summary`
- `GET /v1/simulations/{batch_id}/top-runs`
- `GET /v1/agents/current`
- `GET /v1/predictions/current`
- `GET /v1/models/{agent}/{version}/audit`

Administrative batch creation and model promotion endpoints must require authentication. Public website endpoints should be read-only.

## Security and cost controls

- No AWS access keys or database passwords in GitHub.
- Use IAM task roles, Secrets Manager, private database networking, TLS, and least-privilege S3 access.
- Keep RDS private; expose only the API through a controlled HTTPS endpoint.
- Add AWS Budgets, CloudWatch alarms, Batch vCPU limits, maximum array size, and a kill switch.
- Start with small pilot batches. Do not schedule one million runs until measured runtime and cost fit the approved budget.
- Use S3 lifecycle policies for temporary staging and retained audit objects.

## Rollout

1. Correct the one-ticket contract and add tests for prediction sealing, chronological cutoff, independent states, scoring, and reproducibility.
2. Refactor the simulation engine into a reusable worker interface and benchmark one complete replay.
3. Build a local/container pilot with a small number of parallel workers.
4. Add Terraform for AWS infrastructure, initially with conservative quotas and no daily million-run schedule.
5. Deploy API and worker images; run 100, 1,000, and 10,000-run pilots.
6. Validate data integrity, retries, costs, and dashboard API responses.
7. Enable the million-run daily schedule only after an explicit budget and capacity review.

## Open deployment inputs

Before provisioning AWS resources, confirm:
- the AWS account ID and confirmation that the user can authorize deployments;
- confirmation of `us-east-1` as the initial region (already selected as the default);
- the approved monthly/daily spend ceiling;
- who will hold AWS billing and IAM administrator access.

No paid resources should be created until those are confirmed.

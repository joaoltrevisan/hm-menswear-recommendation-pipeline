# Reproducible operation and historical scheduling

This independent case study simulates a service using historical authorized files. It has no current H&M feed or production deployment. Source dates stop at September 22,2020. A seven-day recommendation horizon after that date is an unobserved historical forecast, not a current recommendation or measured accuracy result.

## Setup and complete command sequence

Use Python3.12.14, uv0.13.6 and PostgreSQL18.6, with the committed lock and image digest. Read the setup and pipeline runbooks for private libpq service/pass files, least-privilege logins and the mandatory server-log gate. The application reads environment variables but never auto-loads .env. Run commands from the checkout.

```sh
.tooling/bin/uv sync --locked --no-install-project
.tooling/bin/uv sync --locked --no-editable --no-build-isolation --reinstall-package hm-menswear-recommendation-pipeline
set -a
. ./.env
set +a
.venv/bin/hm-menswear check-config
.venv/bin/hm-menswear db migrate
.venv/bin/hm-menswear verify-log-settings
.venv/bin/hm-menswear inspect --output ../hm-menswear-work/reports/source-inspection.json
.venv/bin/hm-menswear prepare
```

Capture the preparation UUID from the safe JSON response, then use it explicitly:

```sh
.venv/bin/hm-menswear load-next --preparation PREPARATION_UUID
.venv/bin/hm-menswear load --preparation PREPARATION_UUID --start 2018-09-20 --end 2018-09-27
.venv/bin/hm-menswear load-all --preparation PREPARATION_UUID
.venv/bin/hm-menswear status
.venv/bin/hm-menswear compare-models --output ../hm-menswear-work/reports/model-validation.json
.venv/bin/hm-menswear final-test --comparison ../hm-menswear-work/reports/model-validation.json --output ../hm-menswear-work/reports/final-test.json
.venv/bin/hm-menswear retrain-selected --session TEST_SESSION_UUID --cutoff 2020-09-22
.venv/bin/hm-menswear recommend --model-id MODEL_SHA256 --customer-stdin --k 12
```

For stdin recommendation, enter one private customer ID and EOF, or pipe from a protected local source; avoid a real ID in shell history/process arguments. Output omits that customer ID. A known cold customer receives the declared popularity filler; an unknown identity is never inserted. Existing reports are not overwritten. Use a new output filename for an intentional rerun; final-test completed replay reads stored results only under its original verified code. Later releases can export a completed receipt through `export-test` without evaluating labels again.

A historical load publishes facts and observation identities. It never trains a model. `retrain-selected` uses the immutable validation-selected recipe associated with a completed test session; it does not inspect test scores to choose parameters. Training writes an immutable model package. Recommendation generation reads one explicit model package and does not update it. Serving predictions are in the private package; the optional serving table is not populated by CLI queries. No live API, HTTP service, image retrieval or frontend is included.

## Incremental job and opt-in schedules

`load-next` finds the earliest uncovered date inside the prepared source calendar and publishes at most one seven-day half-open window. Overlapping completed windows are merged; an upcoming covered interval clips the new window. At source end it returns `source_exhausted` and performs no publication. Two concurrent invocations may choose the same gap; the underlying serialized/idempotent loader turns the second into a no-op. It retries transient connection/serialization/deadlock failures at most three attempts with1s/2s backoff; data/contract failures are never retried automatically. The invocation freezes its chosen date window before publication; every publication retry repeats that same window as a fresh owned attempt. An uncertain committed outcome becomes a no-op, and cannot advance another week. A lost connection cannot resume a publishing transaction.

Use the example wrapper after setting its project/preparation placeholders. The examples are not installed. For Linux cron, adapt [the cron example](../examples/historical-load.cron) for a daily historical arrival and protected stdout files outside Git. For macOS, substitute [the launchd example](../examples/historical-load.plist)'s absolute project/script/private-log paths before loading it yourself. Disable the schedule once the source is exhausted. A scheduler may continue invoking the no-op end check until disabled; no fresh source is invented. Retaining historical schedules after this finite replay provides no new data.

Model retraining must be scheduled separately with an explicit source cutoff and selected recipe/session. Recommendation generation must reference the resulting model ID explicitly. The project provides command examples, not an automatically installed production scheduler or monitoring service.

## Synthetic demonstration and verification

Run `HM_TEST_CONTAINER=YOUR_LOCAL_POSTGRES_CONTAINER ./scripts/demo.sh` after private `.env` configuration. `scripts/demo.sh` runs the integrated CLI walkthrough against independently fabricated CSVs and an isolated PostgreSQL database. It uses synthetic contract/provenance injection inside the test fixture only; production preparation/train commands retain source hash and clean-code guards. It requires the private test admin DSN and container log target, creates only UUID-named synthetic databases/logins, and cleans them up. It does not read/download competition files and never changes their source release. No Kaggle login is needed for this demonstration.

The walkthrough exercises CLI migration, preparation, incremental and repeated load, comparison, durable final-test receipt, stored result export and recommendation with stdin. Full verification additionally includes actual PostgreSQL privilege, lock, atomicity/recovery and log-sentinel checks. Do not treat an unconfigured skipped integration suite as a successful full verification.

## Errors, recovery and privacy

Exit codes:0success;2configuration/contract/input/IO error;3database failure;4unexpected safe failure;130interruption. Errors return safe static codes, never database exception strings or customer rows. For loader failure, inspect safe run status and call `recover --run UUID`; a live owned attempt is protected. Retry the dated window as a new attempt. Source/artifact corruption requires exact verified restoration or a reviewed new isolated generation; immutable complete preparation is not silently rebuilt.

For an interrupted final-test workflow, retain its original comparison JSON and original code/lock: only that frozen recipe can resume. Results are stored for all ten models atomically. If only report export failed, use the same receipt and a new output path; never clear the session or change protocol names to claim untouched labels. An administrator's manual label query/database rebuild can invalidate the evaluation protocol and must be disclosed. Retries cannot restore holdout independence after a changed algorithm has seen its results.

Keep source CSVs, source snapshots, staging artifacts, model arrays/mappings, logs, reports and all credentials under private owner-only storage outside Git. Do not redistribute data with the code. PostgreSQL suppresses ordinary statement/error payload logging to pass the verified sentinel gate; this intentionally reduces server diagnostics. Catastrophic/admin-reconfigured logging is outside that guarantee. The reader role is a local job role, not per-user authentication or row-level access control for a web service.

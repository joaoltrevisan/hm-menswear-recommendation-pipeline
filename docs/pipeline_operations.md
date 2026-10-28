# Historical pipeline operation and source integrity

Stage 3 implements preparation and atomic temporal publication. The source is historical; these jobs simulate arrival from one immutable three-file snapshot, not a live H&M feed. Remaining stages are authorized to continue without additional start approvals; independent review and verified private commits remain required per stage.

## Security gate before source loading

The pinned Compose service suppresses ordinary PostgreSQL ERROR diagnostics and statement/parameter logging. `log_min_messages=panic` deliberately trades verbose database error logs for privacy; safe application reason codes and UUIDs provide operational diagnostics. Terse error verbosity alone is insufficient because error messages themselves can echo input. The loader checks every required logging setting before preparation and publication, not merely once during setup. See [PostgreSQL logging documentation](https://www.postgresql.org/docs/18/runtime-config-logging.html).

The integration gate sends independently fabricated markers through a failed conversion, failed COPY conversion and failed COPY constraint, then searches actual container stdout/stderr since the test started. The application separately catches errors without printing raw diagnostics/tracebacks. This verifies ordinary failing row cases; it does not claim that arbitrary administrator changes or catastrophic server failures can never disclose anything. Do not enable verbose statement/row logging on a database containing restricted records.

```sh
set -a
. ./.env
set +a
docker compose up -d --wait
.venv/bin/hm-menswear db migrate
.venv/bin/hm-menswear db provision --confirm-database hm_menswear
.venv/bin/hm-menswear verify-log-settings
# Set HM_TEST_ADMIN_DSN privately, using the isolated administrative service.
export HM_TEST_ADMIN_DSN="$HM_ADMIN_DSN"
export HM_TEST_CONTAINER=hm-menswear-local-postgres-1
.venv/bin/pytest -q --require-postgres --require-log-safety
```

Tests create and remove only their own synthetic databases/principals. Test fixtures support libpq services/password files without printing credentials. Runtime loading uses the separate loader login, never the administrator. Defaults without required flags may skip unavailable infrastructure; such a run does not certify the pre-load gate.

## Intake and preparation

The packaged `source_manifest.json` pins the authorized files' byte sizes, SHA-256 hashes, ordered headers, scope and contract versions. Original files are opened read-only. Intake copies use private temporary files, flush/fsync, a SHA-256-addressed final filename, owner-only access, and a read-only completed file. Before/after hashes protect the actual captured bytes. Parsing never depends on changing original paths after intake.

A strict standard-library CSV structural pass checks ordered headers, UTF-8, NULs, duplicate/missing columns and logical record widths, including quoted multiline fields. Pandas then reads bounded chunks as strings with NA inference/blank-line skipping disabled; independent counts must agree. Source ordinals are assigned before filtering. Unexpected structure aborts the whole preparation; no bad-line skipping is supported.

A private SQLite artifact is an indexed intermediate file, not a substitute for PostgreSQL. It stores source catalog/customer metadata, accepted Menswear occurrences, minimal identity/date/reference observations and reason-coded rejects. Chunk-local reference lookups and a bounded 64 MiB SQLite page cache avoid holding transaction history in memory. This concretizes the approved private preparation layer without adding a server/dependency. PostgreSQL remains the publication/serving database and the target of all transaction/concurrency tests.

Empty optional values become null, with absent FN/Active preserved as unknown. Literal `None`/`NONE` text remains text. Integral source ages such as `49.0` are validated exactly before SQL integer storage, without rounding; malformed metadata rejects its dimension/referencing purchases. Exact finite nonnegative Decimal prices use an explicit ASCII decimal/scientific syntax (no Unicode digits or separators). Their written encoding is conservatively bounded to PostgreSQL numeric storage sizes: at most 131,072 digits before the decimal point and 16,383 fractional digits, including zero encodings. Age uses the same ASCII lexical rule and must be an exact nonnegative PostgreSQL integer. These are technical representation limits, not business price/age caps. Invalid tokens receive stable row/dimension rejection reasons before COPY. Raw channel codes 1/2 have no currency or store/online labels. Scope is exactly Menswear. Minimal customer observations ignore financial fields/metadata by the approved separate contract; they never certify an accepted purchase.

```sh
# Output must be a new private file inside HM_WORK_DIR.
.venv/bin/hm-menswear inspect --output ../hm-menswear-work/inspections/source.json
.venv/bin/hm-menswear prepare
```

Prepare returns technical run/preparation/release UUIDs and aggregate counts, never customer rows or paths. Keep the preparation UUID for load commands. Optional `--articles-file`, `--customers-file`, `--transactions-file` aliases must resolve inside HM_RAW_DIR; unchanged bytes under another filename reuse source identity. Canonical role names remain unchanged in the manifest. Source fingerprints/contracts that differ from the active lineage are blocked from additive publication; no business-field hash is used to infer overlap.

Each preparation invocation owns a dedicated connection/session advisory lock. Once the manifest is known, it registers a durable attempt and preparation reference. Pre-registration capture failures are logged locally with their new attempt UUID, because no trustworthy release exists yet. A separate preparation lock serializes preparation/reuse decisions. Staging COPY, count reconciliation, preparation completion and its prepared-attempt outcome commit together. Partial local artifacts/staging cannot qualify as complete. Repeating preparation verifies/reuses the existing complete artifact under the same release; it still records a new attempt.

## Temporal publication, idempotency and recovery

```sh
.venv/bin/hm-menswear load --preparation <uuid> --start 2018-09-20 --end 2018-09-27
# Reexecute the same definition: no new facts.
.venv/bin/hm-menswear load --preparation <uuid> --start 2018-09-20 --end 2018-09-27
# Simulate the entire historical arrival in seven-day batches.
.venv/bin/hm-menswear load-all --preparation <uuid> --batch-days 7
.venv/bin/hm-menswear status
.venv/bin/hm-menswear recover --run <uuid>
```

Dates are half-open, validated ISO dates. `load-all` derives bounds from the checksummed indexed artifact, not mutable unverified JSON. A zero-row window is an explicitly reconciled completed batch. A completed matching window records a no-op attempt. Overlapping windows reuse matching `(transaction_file_id, source_record_number)` identities and retain separate memberships; global facts are never counted by summing overlapping memberships. Identical purchases at different ordinals remain separate facts.

A dedicated session ownership lock spans validation, waiting and publication. The singleton lineage row serializes publication. Existing dimensions, purchase identities and observation provenance must have equal payloads. Publication inserts scoped catalog data, only customers referenced in the window, accepted facts, date-gated first observations and batch memberships; counters and terminal success commit atomically. Failure rolls back the whole batch, retaining previous successful batches.

Reconciliation: source = rejected + valid out-of-scope + valid Menswear; accepted window = inserted + reused = memberships; global fact delta under the lock = inserted. Preparation rejects are counted once, never added repeatedly per temporal batch. Staging dimensions/observations/reject counts also reconcile independently. The operational JSONL ledger contains UUIDs, stage/status, safe codes and numeric counts only; raw rows, identifiers, prices, DSNs and personal paths are excluded.

Recovery first tries the attempt ownership lock, then locks lineage. A live preparing/waiting worker reports `owned`, even if old; age is never proof of death. Once an abandoned owner is gone, recovery preserves any committed success, otherwise records interruption. A lost connection cannot reconnect and continue its old attempt. Retrying uses a new UUID. If the client loses a commit response, the committed ledger determines outcome; success is never overwritten by a transport failure. SQLite artifacts and hashes are checked again before every load.

Completed source/contract identity is pinned. New snapshots/reformatted files need a reviewed isolated-generation rebuild and atomic switch; automatic additive replacement remains unsupported. No command deletes the active lineage or deduplicates equal business fields. If an immutable completed artifact is missing or corrupt, rerunning prepare refuses that same complete preparation; it does not repair it automatically. Restore the exact verified artifact from a private backup, or perform a reviewed isolated-generation rebuild. Never edit its stored checksum or clear lineage to bypass verification. Private failed `.partial` artifacts are nonloadable and may be retained for local diagnosis; remove only a confirmed failed attempt's local artifact after checking its ledger.

## Stage boundaries

Data updates do not retrain models or generate recommendations. Temporal model datasets, baselines, item-item comparison, holdout metrics and final command/scheduling integration belong to Stages 4–6. Original/derived CSVs, SQLite files, staging dumps, operational logs and customer-level outputs remain outside Git. This code license context does not license the source data.

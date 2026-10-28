# Delivery stages, acceptance, and operation

Stages 1–2 are delivered. The user authorized continuing through Stages 3–6 without further start approvals. The Stage 2 delivery implements the project/configuration/schema foundation only. Exactly one independent technical reviewer reads files without altering them; the implementer fixes required findings and returns corrections to the same reviewer. From Stage 2, each authorized stage requires meaningful checks, review, required fixes and re-review, inspected diff, coherent English commit(s), private push, and a user-facing report before asking to start the next stage. No force push or rewritten history.

| Stage | Authorized work after its gate | Acceptance evidence |
| --- | --- | --- |
| 1 | Source reconciliation, business rules, architecture, dictionary, evaluation proposal | Independent full-source inspection report, documentation checks, one review, user approval before Stage 2 |
| 2 | Project skeleton, exact dependency lock, configuration, PostgreSQL schema/migrations and role provisioning | Clean environment install; empty-database migration; constraints; actual least-privilege checks; no loader/model implementation yet |
| 3 | File extraction, preparation/validation, automatic dated loading, reconciliation, idempotency, concurrency and recovery | Mandatory pre-load application and PostgreSQL/container log sentinel checks; synthetic unit tests; real PostgreSQL integrated/failure/concurrency tests; full-source reconciliation; unchanged raw digests |
| 4 | Cutoff-only datasets, recent popularity and repeat-history baselines, metric implementation | Window-boundary/leakage fixtures, manual known metrics, deterministic lists, baseline validation report; no final test scoring |
| 5 | Sparse item-item challenger, validation comparison, frozen winner, retraining and reserved final evaluation | Sparse-bound checks; candidate/label isolation; warm/cold/future-first reports; recorded frozen recipe before one final test; measured results only |
| 6 | Unified CLI, scheduling examples, operational docs and reproducible demonstration | Clean synthetic end-to-end walkthrough, verified documented commands, local authorized-data run and recovery procedure; no schedule installation/deployment |

## Verification obligations

| Area | Required cases |
| --- | --- |
| Parsing and scope | Exact Menswear exclusion of Sport/Divided; text/leading zeros end to end; strict headers, wrong column counts, corrupted/truncated CSV, encoding; quoted multiline logical ordinals invariant to chunk size |
| Values and references | Canonical/leap/impossible/heterogeneous/missing dates; missing required IDs/price/channel; null optional FN/Active; literal NA; exact Decimal; nonfinite/negative rejection; zero accepted; unknown refs; duplicate dimension keys |
| Purchase identity | Two identical occurrences retained; same file renamed reused; completed-batch no-op; changed/reordered snapshots or contracts blocked; overlap retains union of ordinals and correct memberships; payload mismatch fails |
| Atomicity/recovery | Fail after dimensions, during COPY/facts and before completion; no partial completed publication; partial preparation blocked; uncertain commit resolved from ledger; killed owner cannot reconnect/resume; new attempt retry |
| Concurrency | Coordinated independent PostgreSQL sessions (events/barriers, not sleep-only races); same batch -> success/no-op; overlap -> correct insert/reuse totals; recovery cannot interrupt live preparing/waiting owner |
| Reconciliation | Full disposition equations, source scope counts, accepted/rejected denominators, empty and all-rejected preparations/windows, batch and global fact deltas under lock |
| Temporal integrity | Cutoff endpoints, no gaps in committed history, candidate first purchase <= cutoff, observation-registry as-of filter, future-only labels retained as misses, metadata excluded, frozen final-test settings |
| Ranking | Manual AP/MAP/Recall/coverage example; >12 relevance; empty/no-hit cases; unique predictions; duplicate labels collapse; fallback/cold start; deterministic ties; repeat products allowed |
| Sparse model | Binary pair support, diagonal removed, minimum support, top-N pruning, outgoing neighbor convention, training-only normalization, block-bound resource use |
| Security/operations | Real role restrictions, parameterization, secret/customer sentinels absent from application and PostgreSQL/container normal/error logs, including failing COPY/constraints before any real-data load, clean Git allowlist, immutable complete model artifacts, documented exit codes and failure recovery |
| Integration | Small explicitly synthetic fixture through preparation -> PostgreSQL -> cutoff snapshot -> baseline/challenger -> metrics -> CLI; no source customer copied into fixture |

Local file inspection is separate from pytest tests of the future implementation. Tests must run against actual PostgreSQL for lock, transaction and privilege behavior; SQLite/mocks cannot certify those. Record commands, versions, outcomes, skipped checks and limits at each delivery. Do not invent benchmark throughput or model scores.

## Proposed CLI, not executable yet

The future executable is `hm-menswear`. Environment: `HM_RAW_DIR`, `HM_WORK_DIR`, `HM_DATABASE_DSN`, and role-specific migration/read DSNs as required; `.env.example` will contain placeholders, never local personal paths or credentials.

```text
hm-menswear inspect --output <private-report>
hm-menswear prepare --release <manifest>
hm-menswear load --release <manifest> --start 2018-09-20 --end 2018-09-27
hm-menswear load --release <manifest> --start 2018-09-20 --end 2018-09-27
hm-menswear status
hm-menswear recover --run <uuid>
hm-menswear train --cutoff 2020-09-08 --model popularity
hm-menswear evaluate --split validation --config <versioned-config>
hm-menswear select --validation-report <private-report>
hm-menswear train --cutoff 2020-09-15 --selected-recipe <frozen-manifest>
hm-menswear evaluate --split test --selected-recipe <frozen-manifest>
hm-menswear recommend --model <model-id> --customer <synthetic-customer-id> --k 12
```

The repeated load demonstrates idempotency. Exact executable commands, argument semantics and exit codes are Stage 6 deliverables. No command in this document is claimed runnable now. Dates are half-open; initial partial week and end-of-source windows are explicit. All periods must be loaded without gaps through a model cutoff. CLI use for real customers stays local.

Data publication, model retraining and recommendation generation are separate jobs. A successful load does not silently retrain or replace the selected model. Train writes an immutable artifact; explicit generation references that model. Schedule examples (opt-in macOS launchd and Linux cron) will process the next historical window, retry only transient failures with bounded backoff, stop at source end, and retain safe operational counts. No live update claims or installed timers. Failed jobs return nonzero and never mark incomplete batches/models complete.

## Git and privacy

Use an isolated project directory and private `joaoltrevisan/hm-menswear-recommendation-pipeline` repository, checking name availability first. Configure identity locally for this repository with the authenticated account's verified GitHub noreply identity; never inherit personal email. Stage 1 may commit documentation only. From Stage 2, commits follow required review corrections; meaningful intermediate commits are welcome when verified. Before every push inspect actual staged/committed paths and diffs for original/derived files, customer IDs, secrets, personal paths and misleading claims. Never broadly add the parent workspace.

Authorization covers this private repository and its project commits. Public visibility, dataset publication, deployment and Kaggle submission require separate specific authorization. No existing repository may be reused solely because its name matches.

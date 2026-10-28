# Stage 3 verification and independent review

Status: verified; the same sole read-only reviewer resolved P2 on final re-review with no remaining mandatory findings. User authorization now covers continued work through Stages 3–6 without repeated start approvals. Per-stage checks, required corrections/re-review and private commits remain in force.

Implemented: immutable pinned intake, independent strict CSV structural/count gate, bounded pandas string chunks, private disk-indexed preparation, exact value validation, source ordinals, preserved equal occurrences, independent observation registry, durable preparation/load attempts, staged COPY, atomic dated publication, payload equality checks, overlap/no-op handling, ownership-based recovery, safe CLI/status/logging and simulated full-history arrival.

Initial regression and actual container log-safety gate: 71 tests passed in 5.49 seconds, no skips. The broader initial synthetic unit/integration suite then passed 100 tests in 17.48 seconds, no skips. The expanded source/preparation/load cases passed 106 tests in 7.78 seconds. A real worker-termination test was then added; its initial synchronization query was corrected to find the uncommitted final state before SIGKILL, and final verification follows below. These checks are separate from the full-source preparation/reconciliation; no model results are claimed.

Logging gate: failed synthetic conversion, COPY conversion and COPY constraint markers did not appear in the actual recreated PostgreSQL container logs. Runtime code checks required server settings before source preparation/publication. Application errors emit safe codes instead of input-bearing database diagnostics.

Full-source execution, review findings/corrections, final verification counts and operational limitations are recorded below. The original CSVs remain untouched. Model training/evaluation is not part of this stage.

## Full-source preparation

The actual pinned source completed private preparation and PostgreSQL staging reconciliation: 31,788,324 source records; 30,017,271 valid out-of-scope records; 1,771,053 accepted Menswear occurrences; zero transaction or dimension rejections; 12,553 scoped products; 339,126 distinct related customers; 123,650 identical-field groups and 162,214 additional occurrences preserved. The first-observation registry contains 1,362,281 identities across all segments through the source end, not an assertion that every undated customer registry entry existed historically. Coverage is 2018-09-20 through 2020-09-22. No source data, artifact or credential is committed.

Full-history publication completed in 105 nonoverlapping weekly batches: 1,771,053 inserted facts, 1,771,053 memberships, zero reused rows on first publication, zero incomplete batches. Reexecuting the first completed window returned no-op with 0 inserted and 15,450 reused rows; total facts remained 1,771,053. Final SQL reconciliation is recorded below.

## Initial independent review and correction

The sole reviewer independently ran 107 tests (9.26 seconds), including real worker SIGKILL recovery and container-log safety. One mandatory P2 finding: Python Decimal accepted Unicode numeric digits and extreme finite exponents that PostgreSQL numeric/integer inputs cannot store, which could abort COPY rather than reject a row. The implementer added ASCII numeric syntax and conservative technical PostgreSQL encoding/integer bounds, with explicit invalid-price/metadata rejection reasons. New end-to-end tests put bad Unicode/extreme-exponent prices and bad Unicode ages between valid neighbors and verify that good rows still publish. No business currency, price or age assumption was introduced. Final expanded verification and re-review follow below.

The optional clarification about completed-artifact corruption was incorporated: restore the exact verified artifact or use a reviewed isolated rebuild; ordinary prepare retry is not an automatic repair for an immutable complete artifact.

## Final correction, independent verification and actual-data reconciliation

The first numeric correction passed 115 tests. Re-review found that a zero age with an extreme negative exponent still reached the raw SQL numeric/integer cast; age now reuses the same lexical/storage validator before integer checks. End-to-end tests include both positive and negative extreme zero encodings. Final local suite: **117 passed in 12.62 seconds**, no skips. The reviewer independently confirmed **117 passed in 11.27 seconds**, no skips; installed source/resources, Ruff, formatting, offline lock and diff checks passed. P2 resolved; optional artifact-recovery clarification addressed; no remaining mandatory findings.

An independent read-only numeric-token check across the complete source found 9,857 distinct price tokens and 85 age tokens including empty, with zero incompatibilities under the corrected validator. This confirms that the synthetic-edge correction leaves the pinned corpus unchanged; it is an actual-source inspection, not a substitute for automated tests.

Final PostgreSQL aggregates: 1,771,053 purchase occurrences, 12,553 scoped catalog products, 339,126 referenced Menswear customers, 1,362,281 first-observed customer identities across all segments, 14 null Menswear descriptions, zero rejected records and zero incomplete batches. Grouping stored purchase fields found the same 123,650 repeated groups and 162,214 additional occurrences. The source date range remains 2018-09-20 through 2020-09-22. Only reviewed aggregate evidence is committed; all source/derived rows, customer mappings, run logs, credentials and private artifacts remain local.

Commands exercised: `db migrate`, `db provision`, `verify-log-settings`, `prepare`, `load-all --batch-days 7`, explicit repeated `load`, `status`, synthetic recover calls, and `pytest --require-postgres --require-log-safety`. Full history was simulated from immutable local files; no API/live integration or recommendation performance is claimed.

Stages 4–6 continue under the user's standing authorization. Data publication is complete; model preparation/training/evaluation remains separate.

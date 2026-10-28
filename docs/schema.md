# Implemented PostgreSQL foundation dictionary

Stage 2 schema is defined by the packaged [foundation SQL](../src/hm_menswear/sql/0001_foundation.sql), [integrity guards](../src/hm_menswear/sql/0002_integrity.sql), and [explicit grants](../src/hm_menswear/sql/0003_permissions.sql). These SQL files are the complete column/type/constraint dictionary; the tables below describe their operational meaning. No order IDs are invented. See the [approved design](architecture.md) for the flow and ER diagrams.

## Types and common columns

`article_id` is ten-digit text and `customer_id` is 64-character lowercase hex text, both with C collation for reproducible lexical order. Codes remain text. `sha256` is validated 64-character lowercase hex text; `file_role` is articles/customers/transactions. Null is permitted by domains but forbidden explicitly on required table columns. UUIDs are technical control identities supplied by the caller. Source ordinals and counts are positive/nonnegative bigint. Dates are finite calendar dates, technical timestamps are timestamptz. PostgreSQL numeric stores exact source price without a guessed currency/scale; nonfinite/negative values are forbidden.

## Provenance and control

| Table / key | Columns and interpretation |
| --- | --- |
| `control.schema_migrations` / name | SQL filename, SHA-256, applied timestamp; owner-only checksummed prefix ledger |
| `control.source_files` / file_id | namespace, role, CSV SHA-256, byte_size, private_location, acquired_at; unique namespace/role/hash; immutable |
| `control.releases` / release_id | manifest digest and parser/validation/scope/contract versions; immutable; a deferred guard requires all three file roles in one namespace |
| `control.release_files` / release_id, role | file_id with a role-matching composite FK; immutable source-role associations |
| `control.lineage` / singleton=true | active_release_id; exactly one seeded row; once pinned, release cannot change or be cleared; runtime cannot insert/delete the singleton |
| `control.preparations` / preparation_id | release, status, private artifact location/digest, source/rejected/out-of-scope/Menswear counts, completion time; complete status requires balanced nonnull counts and digest |
| `control.batches` / batch_id | release, complete preparation, finite start/end dates, status, accepted/inserted/reused counts and completion time; unique release/window; half-open dates; complete status balances declared and actual memberships/facts |
| `control.runs` / run_id | release, optional batch, status, start/end, safe error code; terminal state requires end time; success/noop requires a completed batch; terminal rows immutable |
| `control.batch_records` / batch, file, ordinal | release-bound fact membership with FK to canonical file/ordinal identity; immutable; only pending matching date windows accept new membership |

Preparing preparations may receive staged/rejected rows. Complete/failed preparation, completed batch, terminal run and complete/failed model records cannot be changed/deleted through normal DML. Facts and observation rows require their first publication batch to be completed at commit; a deferred check prevents a pending publication from committing them visibly. Complete batches reconcile their actual inserted facts and memberships, including mandatory membership for each new fact. Overlap reuse and worker ownership protocol still require the Stage 3 loader; SQL constraints are not an implementation of those workflows.

## Private staging and quality

| Table / key | Contents |
| --- | --- |
| `quality.rejections` / preparation, role, ordinal | One primary safe reason and additional reason-code array; no raw payload in operational logs |
| `staging.articles` / preparation, ordinal | Original article token and private JSON object preserving source field tokens |
| `staging.customers` / preparation, ordinal | Original customer token and private JSON object; no exposure to model/reader roles |
| `staging.purchase_records` / preparation, ordinal | Parsed nullable date/IDs/price/channel and one rejected/out_of_scope/menswear disposition |
| `staging.customer_observations` / preparation, customer | Earliest valid ID/date/reference observation and canonical source ordinal, independent of financial-field acceptance |

Invalid tokens can remain in staging so reasons can be traced. Mart domain constraints apply only to accepted records. Triggers prohibit staging/rejection changes once preparation is not preparing, including concurrent completion protected by row locks. File-structure validation, optional-field parsing and actual preparation row reconciliation are Stage 3 responsibilities; schema alone cannot certify external artifact contents.

## Menswear mart

| Table / key | Fields and provenance |
| --- | --- |
| `mart.articles` / release, article_id | Source ordinal plus all remaining 24 catalog fields as source text/null; index_group_name must be Menswear; ordinal unique per release |
| `mart.customers` / release, customer_id | Source ordinal; nullable fn/active source codes (`1.0` when present), club_member_status, fashion_news_frequency, nonnegative integer age; postal_code excluded |
| `mart.customer_observations` / release, customer_id | First-observed date, canonical transaction-file/ordinal provenance, first_batch_id; **no FK to Menswear customer dimension**, allowing customers without Menswear history |
| `mart.purchase_events` / transaction_file_id, source_record_number | release, article/customer FKs, purchase_date, exact price_source_units, sales_channel_code 1/2 and first_batch_id; repeated equal field values at different ordinals are valid |

Composite file-role FKs ensure transaction provenance belongs to the pinned release and is not an article/customer file. Mart inserts require the active release. All canonical facts, dimensions and observations are immutable. A fact/observation first batch must be pending and match its date at insertion, then completed in the same transaction. Batch membership may reuse an already committed fact for an overlapping window without inserting the purchase again. Leading zeros and missing optional flags survive storage. A source row remains a purchase occurrence, not an order.

## Model and serving structures

| Table / key | Contents and limits |
| --- | --- |
| `control.models` / manifest-derived model_id | release/cutoff/family, config/input/lock hashes, code commit, private manifest/location, build status/completion; immutable after terminal state |
| `serving.recommendations` / model, customer, rank | release, article, finite nonnegative score and optional safe fallback reason; rank 1–12 and unique article per model/customer |
| `evaluation.test_sessions` / session UUID | Unique protocol hash, frozen selected validation model and recipe hash, timestamp; Stage 5 adds release FK, full immutable recipe/allowed-refit JSON and a unique source-release constraint |
| `evaluation.runs` / evaluation UUID | model, protocol/config hashes, split, aggregate cohort/metric JSON objects, timestamp and required test-session reference for test split |

Serving inserts require a complete model, a customer observed by cutoff, and an article with purchase evidence by cutoff. Persisted serving rows represent known-customer populations; CLI fallback for an entirely unknown ID will be computed locally without inserting a registry/customer record. Catalog inclusion alone cannot authorize recommendation of a future-only item. Ranking, training history completeness, manifests/artifact checksums, metric formulas, selection and execution of the final test are later-stage application obligations; these JSON structures do not certify them.

A test session can contain one result per frozen model/protocol, so the selected model and already frozen baselines can be reported without choosing a new winner from test outcomes. This refines the Stage 1 `evaluation.runs` proposal into separate session/results structures. Test sessions/results are immutable. The application must freeze one declared protocol and disclose any post-test correction; a new protocol identifier cannot make previously inspected labels untouched.

## Permission dictionary

| Group | Granted access | Excluded access |
| --- | --- | --- |
| hm_owner | NOLOGIN object owner | Not assigned to runtime principals |
| hm_migrator | CONNECT; can explicitly SET ROLE hm_owner, without inheriting owner privileges | No superuser/role/database creation |
| hm_loader | Insert/read provenance and mart; limited lifecycle-column updates; private staging/rejection DML | No DDL, owner escalation, migration ledger, model publication or deletion/update of canonical facts |
| hm_model | Read cutoff-required mart identity/date columns and input control metadata; insert models, rankings, evaluation; update model lifecycle | No customer demographics, raw/staging, price/channel features, source locations, DDL or purchase writes |
| hm_reader | Read catalog, recommendations and selected model status/cutoff fields | No customer metadata, source/staging, purchase history, model artifact locations, DML or DDL |

All five groups are NOLOGIN and lack superuser/createdb/createrole/replication/bypass-RLS flags. Login accounts inherit only their matching group. PUBLIC has no project schema/table/function/domain or dedicated-database connect/temp/create privileges. No default grant applies to future tables; migrations must explicitly grant minimum access. These are local job-role boundaries, not a multi-tenant authentication service or per-customer row-level authorization layer.

Provisioning audits effective privileges against the packaged [permission policy](../src/hm_menswear/permission_policy.json), including table/column rights, PUBLIC/inherited access, schema usage, callable project functions and sequences. Excess access is rejected transactionally with preexisting ACLs preserved. This supplements the DDL/TEMP/ownership checks; role flags alone are insufficient. Future permission changes must update both SQL grants and this policy in the same reviewed delivery.

## Frozen holdout migration

[Migration 0005](../src/hm_menswear/sql/0005_reserved_test.sql) strengthens the previously empty test-session structure: each source release can have only one reservation even if protocol text changes. Existing immutability triggers and INSERT/SELECT-only model privileges protect the receipt. The receipt contains the exact ten refitted model IDs and the validation-selected recipe; `evaluation.runs` stores aggregate results atomically for all ten. The app commits the reservation before reading test labels, serializes by a release advisory lock and returns stored results on completed replay. A new recipe cannot make inspected labels untouched. This is an application evaluation protocol, not protection against an administrator manually querying labels or rebuilding the database.

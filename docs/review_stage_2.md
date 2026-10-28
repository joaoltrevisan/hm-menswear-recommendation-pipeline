# Stage 2 verification and independent review

Status: final independent re-review complete; P1 resolved, no remaining mandatory findings or optional suggestions. The same sole read-only `technical_reviewer` reviewed the current files and both correction rounds without editing them. No source data was loaded, no recommendation algorithm was implemented, and no model performance was measured.

Implemented: Python package/module boundaries, locked runtime/test/build dependencies, explicit safe environment configuration, administrative database CLI, three checksummed atomic SQL migrations, source/release/lineage and publication constraints, private model/serving structures, role provisioning/grants, pinned local PostgreSQL Compose definition, synthetic unit/integration tests and operational/dictionary documentation.

Initial complete PostgreSQL run: 47 tests passed in 2.89 seconds. A new initially empty environment was then installed from the lock, including locked build dependencies and a noneditable wheel build with build isolation disabled. Its full real-PostgreSQL run passed 52 tests in 3.08 seconds, with no skips. The additional cases cover migration-resource gaps, active outer transactions, unsafe preexisting groups, denied PUBLIC access and sanitized CLI database errors. Ruff lint/format and lock consistency checks passed. Review findings, corrections and final re-review are recorded below.

Initial setup issue: editable package import failed because the local runtime skipped an OS-hidden .pth file. The documented wheel-based installation replaced that path, and the 47-test run used the installed wheel. This was an installation failure, not a passing test; no Python protection was disabled. Ruff checks and formatting checks passed before the additional tests.

Limitations: Stage 2 tests certify schema/configuration behavior and migration concurrency only. End-to-end source parsing/loading, purchase-batch idempotency/overlap, session-loss recovery, temporal datasets and model evaluation remain later-stage work. Original CSVs were not used by this test suite.

## Initial mandatory finding and correction

The reviewer independently reproduced [P1] in `src/hm_menswear/db.py`: a preexisting explicit `CREATE ON SCHEMA public TO hm_loader` grant survived PUBLIC revocation, but provisioning still reported success. Role flags/memberships alone were insufficient to certify minimum privilege. No optional suggestions were raised in the initial review.

The implementer added transactional effective CREATE/TEMP checks for the target database, effective CREATE checks across schemas, and catalog ownership checks for target/shared objects of nonowner groups. Unknown memberships remain rejected. Incompatible grants/ownership cause a safe failure instead of silent privilege removal. New synthetic cases cover direct schema/database grants, PUBLIC/inherited grants, schema/table/database ownership, unexpected memberships, ACL rollback preservation, and successful re-provisioning of a clean migrated database. Final test and re-review outcomes are recorded below.

## Stage 3 pre-load security gate

The reviewer identified PostgreSQL server error logging as a mandatory Stage 3 pre-load gate, not an additional Stage 2 blocker: this stage loads only synthetic records and does not certify server-log redaction. Before any real CSV load, configure and prove application plus PostgreSQL/container log safety using failing synthetic COPY and constraint cases with customer/secret sentinels. PostgreSQL ERROR/DETAIL may include values even when statements are suppressed. This obligation is now explicit in the delivery/operations documents.

The first P1 correction passed 61 tests (3.61 seconds locally; 3.84 seconds independently), but re-review found a second path of the same issue: a preexisting customer-table SELECT grant to the reader was still accepted. The implementer added a packaged effective-access allowlist and table/column/schema/function/sequence checks across the six project schemas. New cases cover reader customer data, PUBLIC column reads, model price reads, unintended writes, TRUNCATE, REFERENCES, TRIGGER and callable functions, with retained ACLs on rejection. Final re-review confirmed this complete correction resolves P1.

## Final verification and delivery boundary

- Full current installed-wheel suite: **70 passed in 4.78 seconds**, zero skips. The same reviewer independently ran it: **70 passed in 4.86 seconds**, zero skips.
- Ruff lint/format, offline uv lock consistency and whitespace/diff checks passed. Reviewer confirmed installed Python files, SQL and permission policy match current source.
- Initial empty-environment install from the lock verified Python 3.12.14, locked runtime/test/build dependencies, and wheel construction without unlocked build isolation. Final permission corrections add no dependencies and were rebuilt/tested in the installed wheel.
- The dedicated local development database was initialized through the actual safe CLI using distinct administrator/migrator credentials: provision succeeded, all three migrations applied, rerun applied none, and post-migration permission re-audit succeeded. PostgreSQL reports 18.6. Source-file and purchase-event tables both contain zero rows. Synthetic temporary databases and login principals were cleaned up.
- Separate persistent local login principals have only their matching group roles. Their generated passwords and libpq service/pass files are owner-readable outside the repository; the local `.env` is ignored and contains service references. No credential value was printed or committed.
- Independent final verdict: P1 resolved; no remaining mandatory findings or optional suggestions. Review authorizes private commit/push of Stage 2, not implementation of Stage 3.

Commands exercised include `uv sync --locked --no-install-project`, `uv sync --locked --no-editable --no-build-isolation`, `hm-menswear --version`, `hm-menswear check-config`, `hm-menswear db provision --confirm-database hm_menswear`, `hm-menswear db migrate` twice, `pytest -q --require-postgres`, `ruff check src tests`, `ruff format --check src tests`, and `uv lock --check --offline`. Environment DSNs/passwords were supplied privately, not in committed command lines.

No real source CSV was loaded, no loader/recovery workflow was implemented, and no model was trained or scored. The original source inspection remains separate from automated implementation tests. The next user gate is Stage 3 only, including the mandatory server/application log-safety checks before source loading.

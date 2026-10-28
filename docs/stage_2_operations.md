# Stage 2 setup and database operations

This foundation is an independent educational simulation. No source CSV is loaded by these commands and no recommender is fitted. Only use the bootstrap procedure against a dedicated project database. Never provision permissions in a shared application database.

## Pinned environment

| Component | Version |
| --- | --- |
| Python | 3.12.14 (`.python-version`; package supports Python 3.12 only) |
| uv | 0.13.6 (enforced in project configuration) |
| PostgreSQL | 18.6, official image pinned by immutable multi-platform digest in `compose.yaml` |
| pandas / NumPy / SciPy | 3.1.0 / 2.5.4 / 1.18.1 |
| Psycopg / binary distribution | 3.3.6 / 3.3.6 |
| pytest / Ruff / Hatchling | 9.2.0 / 0.17.3 / 1.33.0 |

`uv.lock` pins transitive versions and distribution hashes for runtime, tests and build dependencies. Bootstrap uv is installed at its explicit version from PyPI. Build dependencies are installed from the lock before building without isolation, so Hatchling cannot resolve fresh, unlocked transitive dependencies. `--locked` refuses lock drift. The database runtime rejects non-18 major versions; exact 18.6 reproduction uses the pinned Compose image. Updating a patch/digest is a deliberate reviewed change, never a mutable `latest` tag.

From the repository directory, with a supported Python bootstrap and Docker Desktop/Engine already installed:

```sh
python3 -m venv .tooling
.tooling/bin/python -m pip install uv==0.13.6
.tooling/bin/uv python install 3.12.14
.tooling/bin/uv sync --locked --no-install-project
.tooling/bin/uv sync --locked --no-editable --no-build-isolation
.venv/bin/hm-menswear --version
```

The first sync installs locked build/runtime/test dependencies; the second installs the project as a wheel. On this macOS inspection runtime, the initial editable installation produced an OS-hidden `.pth` file that Python skipped. The wheel-based route avoids that environment-specific issue and tests the actual distributable package. It does not modify Python's protections or require `PYTHONPATH`. After changing application files, rebuild with:

```sh
.tooling/bin/uv sync --locked --no-editable --no-build-isolation --reinstall-package hm-menswear-recommendation-pipeline
```

No pipeline/model code is implemented inside the reserved extraction, transformation, validation, loading, recommendation and evaluation packages. Stage 2 CLI supports `--version`, `check-config`, `db provision` and `db migrate` only. Unsupported later-stage commands fail argument validation.

## Configuration and private local database

Use the existing private local `.env` if one has been prepared; otherwise copy `.env.example` to an ignored local `.env`, edit locally, and explicitly load this trusted file in the current shell. The program does not auto-read `.env`, echo DSNs, or create directories during configuration validation. Set `HM_RAW_DIR` and `HM_WORK_DIR` to disjoint paths; neither may contain the other. `HM_CHUNK_SIZE` must be an integer in [100, 1,000,000]. No data is read by `check-config`.

```sh
cp -n .env.example .env
# Edit .env locally before sourcing it. It contains environment-specific placeholders.
set -a
. ./.env
set +a
.venv/bin/hm-menswear check-config --purpose loader
```

The example uses libpq service names. Configure the service entries and owner-readable password file outside Git, or supply environment DSNs locally. Use local sockets or `sslmode=verify-full` for nonlocal connections; Compose is an isolated localhost-only test/development exception. Do not put secrets into shell command arguments, terminal examples, connection URLs in Git, or logs. File paths and DSNs are excluded from configuration representations and safe command output.

Create a private password file for the isolated database without displaying its contents, set `HM_PG_PASSWORD_FILE` to it, then start Compose:

```sh
# The secret directory and filename are local choices outside the repository.
# Ensure the directory is private and the password file is readable only by its owner.
python3 -c 'import secrets,pathlib,os; p=pathlib.Path(os.environ["HM_PG_PASSWORD_FILE"]); p.parent.mkdir(parents=True,exist_ok=True); p.parent.chmod(0o700); p.write_text(secrets.token_urlsafe(36)); p.chmod(0o600)'
docker compose up -d --wait
```

Run password-file generation once, before first initialization. Regenerating the file does not rotate an existing database password. The default service is `127.0.0.1:55432`, database `hm_menswear`, bootstrap superuser `hm_bootstrap`; the password is read from the mounted file. `hm_bootstrap` is for local provisioning and integration-test database creation only, never runtime loading/training. The PostgreSQL volume persists when stopping the service; do not delete it as routine cleanup.

## Provisioning and migrating

With `HM_ADMIN_DSN` configured locally for the dedicated database:

```sh
.venv/bin/hm-menswear db provision --confirm-database hm_menswear
```

The command refuses `postgres`, `template0`, `template1` and mismatched confirmations. Provisioning creates five NOLOGIN group roles, validates that existing same-named groups have no elevated flags, incompatible memberships, effective runtime DDL/TEMP privileges, target/shared-object ownership, or excess project table/column/function/sequence privileges, revokes PUBLIC database connect/temp/create and PUBLIC-schema rights, and grants only explicit project access. Existing incompatible roles cause a failure; they are not silently overwritten. After the intended PUBLIC revocations, provisioning checks effective permissions (including remaining PUBLIC/inherited access), all-schema CREATE, target/shared-object ownership, and effective data/DML privileges across the six project schemas against the packaged permission policy before reporting success. Table and column checks include inherited and PUBLIC access; unexpected INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER/MAINTAIN, callable functions and sequence rights are rejected. The policy rejects excess access; it does not repair missing grants or certify privileges in unrelated databases. Update the policy and SQL grants together in future reviewed migrations. Rejection rolls back its own changes and preserves preexisting explicit grants and ownership for an operator to investigate; it does not silently remove them. Roles are cluster-scoped; use a dedicated cluster to avoid collisions. Do not give these groups access to other applications.

Create separate login principals for administration/migration, loading, modeling and reading. Assign each runtime principal only its matching group; never make a runtime principal a member of `hm_owner` or `hm_migrator`. Use an interactive password prompt or your environment's credential manager instead of SQL password literals. Example inside an authenticated administrative `psql` session:

```text
CREATE ROLE hm_migration_login LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS IN ROLE hm_migrator;
\password hm_migration_login
CREATE ROLE hm_loader_login LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS IN ROLE hm_loader;
\password hm_loader_login
CREATE ROLE hm_model_login LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS IN ROLE hm_model;
\password hm_model_login
CREATE ROLE hm_reader_login LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS IN ROLE hm_reader;
\password hm_reader_login
```

Configure `HM_MIGRATION_DSN` for the migration login, then:

```sh
.venv/bin/hm-menswear db migrate
.venv/bin/hm-menswear db migrate
# Reaudit effective privileges after installing the schema.
.venv/bin/hm-menswear db provision --confirm-database hm_menswear
```

The second run reports an empty `applied` list. Migration takes a transaction advisory lock, switches locally to the NOLOGIN object owner, verifies the complete checksum ledger/prefix, and applies all pending migrations and ledger rows in one transaction. It requires an idle connection so it owns its transaction boundary. A failure rolls back the entire pending set, including a new ledger/schema on first installation. Changed, unknown or out-of-sequence history fails. Never edit an applied SQL migration; add the next numbered migration. Runtime groups cannot access/modify the ledger or apply DDL. There is no automatic destructive down-migration; recovery is correction of the failed unapplied migration followed by rerun, or a reviewed forward migration for already committed changes.

Exit codes: 0 success; 2 configuration/contract or argument error; 3 database operation failure. Expected errors use stable safe codes, never raw libpq error text. Unexpected programming errors are not falsely reported as successful. Provisioning and migration are separate administrative actions; loading never provisions permissions implicitly.

## Verification commands and boundaries

```sh
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.tooling/bin/uv lock --check
.venv/bin/pytest -q tests/unit
# Set HM_TEST_ADMIN_DSN privately for a dedicated isolated PostgreSQL 18 instance.
.venv/bin/pytest -q --require-postgres
```

Integration fixtures create fresh `hm_test_<random>` databases and temporary login principals, use only synthetic records, and remove only those fixture-owned objects. They do not read raw CSVs or touch an existing source-data mart. The bootstrap test account must have database/role creation privileges on that isolated server. Do not point `HM_TEST_ADMIN_DSN` to a shared/production cluster. `--require-postgres` fails when the DSN is missing; a plain run without it explicitly skips integration tests and cannot certify database behavior.

Before any Stage 3 real-data load, a mandatory security gate must configure and verify both application and PostgreSQL/container error logging using failing synthetic COPY and constraint cases with customer/secret sentinels. Default PostgreSQL messages/DETAIL can contain values, so suppressing SQL statements alone is insufficient. Stage 2 verifies safe expected CLI error output; it does not certify server-log redaction. The current isolated database contains only synthetic test records.

The tests verify migration serialization and schema publication constraints. End-to-end loader retries, real purchase-batch overlap, ownership-loss recovery, temporal dataset creation and model metrics remain Stage 3–5 work, even where structural prerequisites are already constrained in SQL. No live data feed, scheduling, deployment, speed improvement or ranking performance is claimed.

Stop this project's service when it is not needed:

```sh
docker compose stop
```

Stopping preserves the volume. Schedule installation and unified pipeline commands remain Stage 6 work and require the appropriate stage approval.

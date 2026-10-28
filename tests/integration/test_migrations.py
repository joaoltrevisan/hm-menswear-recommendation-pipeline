"""Schema install, transactional failure, checksum history, and real role boundaries."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest

from hm_menswear import db
from hm_menswear.db import DatabaseContractError, migrate, provision

pytestmark = pytest.mark.integration


def test_install_rerun_and_real_migrator_identity(migrated):
    with migrated.connect("migrator", autocommit=True) as conn:
        assert conn.execute("SELECT session_user = current_user").fetchone()[0]
        assert migrate(conn) == []
        with conn.transaction():
            conn.execute("SET LOCAL ROLE hm_owner")
            assert conn.execute("SELECT count(*) FROM control.schema_migrations").fetchone()[
                0
            ] == len(db.migration_sources())
            assert conn.execute("SELECT count(*) FROM control.lineage").fetchone()[0] == 1


def test_corrupted_history_is_detected(migrated):
    with migrated.connect() as conn:
        conn.execute("UPDATE control.schema_migrations SET sha256=%s", ("f" * 64,))
    with migrated.connect("migrator") as conn:
        with pytest.raises(DatabaseContractError, match="migration_history_mismatch"):
            migrate(conn)


def test_failed_migration_rolls_back_all_schema(database, monkeypatch):
    original = db.migration_sources()
    monkeypatch.setattr(
        db,
        "migration_sources",
        lambda: (
            original
            + [
                (
                    f"{len(original) + 1:04d}_synthetic_failure.sql",
                    "CREATE TABLE mart.synthetic_failure(id int); SELECT 1/0;",
                    "f" * 64,
                )
            ]
        ),
    )
    with database.connect("migrator") as conn:
        with pytest.raises(psycopg.errors.DivisionByZero):
            migrate(conn)
    with database.connect() as conn:
        assert conn.execute("SELECT to_regnamespace('control') IS NULL").fetchone()[0]
        assert conn.execute("SELECT to_regnamespace('mart') IS NULL").fetchone()[0]
    monkeypatch.setattr(db, "migration_sources", lambda: original)
    with database.connect("migrator") as conn:
        assert len(migrate(conn)) == len(db.migration_sources())


def test_two_migrators_are_serialized(database):
    barrier = Barrier(2)

    def worker():
        with database.connect("migrator") as conn:
            barrier.wait(timeout=10)
            return migrate(conn)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert sorted(map(len, results)) == [0, len(db.migration_sources())]


def test_provision_requires_dedicated_database_confirmation(database):
    with database.connect() as conn:
        with pytest.raises(DatabaseContractError, match="confirmation"):
            provision(conn, "wrong-synthetic-name")
        provision(conn, database.name)


@pytest.mark.parametrize("role", ["loader", "model", "reader"])
def test_runtime_principals_cannot_escalate_or_ddl(migrated, role):
    with migrated.connect(role) as conn:
        flags = conn.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls "
            "FROM pg_roles WHERE rolname=session_user"
        ).fetchone()
        assert not any(flags)
        for statement in [
            "CREATE SCHEMA synthetic_forbidden",
            "CREATE ROLE synthetic_forbidden",
            "SET ROLE hm_owner",
            "CREATE TABLE public.synthetic_forbidden(id int)",
            "SELECT * FROM control.schema_migrations",
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(statement)


def test_reader_and_model_do_not_see_customer_metadata(migrated):
    for role in ["reader", "model"]:
        with migrated.connect(role) as conn:
            for statement in [
                "SELECT * FROM staging.customers",
                "SELECT age FROM mart.customers",
                "SELECT private_location FROM control.source_files",
            ]:
                with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                    conn.execute(statement)
    with migrated.connect("reader") as conn:
        assert conn.execute("SELECT count(*) FROM serving.recommendations").fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("DELETE FROM serving.recommendations")
    with migrated.connect("model") as conn:
        conn.execute("SELECT article_id,customer_id,purchase_date FROM mart.purchase_events")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT price_source_units FROM mart.purchase_events")


def test_gap_or_missing_resources_cannot_masquerade_as_success(database, monkeypatch):
    original = db.migration_sources()
    for sources in [[], [original[0], original[2]]]:
        monkeypatch.setattr(db, "migration_sources", lambda sources=sources: sources)
        with database.connect("migrator") as conn:
            with pytest.raises(DatabaseContractError, match="invalid_migration_sequence"):
                migrate(conn)
    with database.connect() as conn:
        assert conn.execute("SELECT to_regnamespace('control') IS NULL").fetchone()[0]


def test_outer_transaction_is_rejected(database):
    with database.connect("migrator") as conn:
        conn.execute("SELECT 1")
        with pytest.raises(DatabaseContractError, match="idle_connection"):
            migrate(conn)


def test_existing_unsafe_group_is_rejected(database):
    with database.connect() as conn:
        conn.execute("ALTER ROLE hm_reader LOGIN")
    try:
        with database.connect() as conn:
            with pytest.raises(DatabaseContractError, match="incompatible_existing_group_role"):
                provision(conn, database.name)
    finally:
        with database.connect() as conn:
            conn.execute("ALTER ROLE hm_reader NOLOGIN")


def test_loader_cannot_publish_models_and_public_cannot_connect(migrated):
    import secrets
    import uuid

    from psycopg import sql

    username = "hm_test_" + uuid.uuid4().hex
    with migrated.connect(autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(username), sql.Literal(secrets.token_urlsafe(32))
            )
        )
        try:
            assert not conn.execute(
                "SELECT has_database_privilege(%s,%s,'CONNECT')", (username, migrated.name)
            ).fetchone()[0]
        finally:
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(username)))
    with migrated.connect("loader") as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT * FROM control.models")
        owners = conn.execute(
            "SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname "
            "IN ('control','staging','quality','mart','serving','evaluation')"
        ).fetchall()
        assert owners == [("hm_owner",)]


@pytest.mark.parametrize(
    "conflict",
    [
        "schema_create",
        "database_create",
        "database_temp",
        "public_inherited",
        "schema_ownership",
        "table_ownership",
        "database_ownership",
    ],
)
def test_existing_ddl_grants_or_ownership_are_rejected_without_erasure(database, conflict):
    from psycopg import sql

    with database.connect() as conn:
        if conflict == "schema_create":
            conn.execute("GRANT CREATE ON SCHEMA public TO hm_loader")
        elif conflict in {"database_create", "database_temp"}:
            privilege = sql.SQL("CREATE" if conflict == "database_create" else "TEMPORARY")
            conn.execute(
                sql.SQL("GRANT {} ON DATABASE {} TO hm_loader").format(
                    privilege, sql.Identifier(database.name)
                )
            )
        elif conflict == "public_inherited":
            conn.execute("CREATE SCHEMA synthetic_leftover")
            conn.execute("GRANT CREATE ON SCHEMA synthetic_leftover TO PUBLIC")
        elif conflict == "schema_ownership":
            conn.execute("CREATE SCHEMA synthetic_leftover AUTHORIZATION hm_loader")
        elif conflict == "table_ownership":
            conn.execute("CREATE TABLE public.synthetic_leftover(id integer)")
            conn.execute("ALTER TABLE public.synthetic_leftover OWNER TO hm_loader")
        else:
            conn.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO hm_loader").format(
                    sql.Identifier(database.name)
                )
            )
        # This intentionally preexisting PUBLIC grant must survive a rejected setup.
        conn.execute(
            sql.SQL("GRANT TEMPORARY ON DATABASE {} TO PUBLIC").format(
                sql.Identifier(database.name)
            )
        )
        acl_before = conn.execute(
            "SELECT datacl::text FROM pg_database WHERE datname=%s", (database.name,)
        ).fetchone()[0]
    with database.connect() as conn:
        with pytest.raises(DatabaseContractError, match="incompatible_existing_group_privileges"):
            provision(conn, database.name)
    with database.connect() as conn:
        assert (
            conn.execute(
                "SELECT datacl::text FROM pg_database WHERE datname=%s", (database.name,)
            ).fetchone()[0]
            == acl_before
        )
        assert conn.execute(
            "SELECT has_database_privilege('hm_reader',%s,'TEMPORARY')", (database.name,)
        ).fetchone()[0]
        if conflict == "schema_create":
            assert conn.execute(
                "SELECT has_schema_privilege('hm_loader','public','CREATE')"
            ).fetchone()[0]


def test_unexpected_inherited_role_is_rejected(database):
    import uuid

    from psycopg import sql

    parent = "hm_test_" + uuid.uuid4().hex
    with database.connect(autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(parent)))
        try:
            conn.execute(sql.SQL("GRANT {} TO hm_loader").format(sql.Identifier(parent)))
            with pytest.raises(
                DatabaseContractError, match="incompatible_existing_role_membership"
            ):
                provision(conn, database.name)
        finally:
            conn.execute(sql.SQL("REVOKE {} FROM hm_loader").format(sql.Identifier(parent)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(parent)))


def test_reprovision_clean_migrated_database_keeps_boundaries(migrated):
    with migrated.connect() as conn:
        provision(conn, migrated.name)
        assert not conn.execute(
            "SELECT has_schema_privilege('hm_loader','public','CREATE')"
        ).fetchone()[0]
    with migrated.connect("reader") as conn:
        assert conn.execute("SELECT count(*) FROM serving.recommendations").fetchone()[0] == 0


@pytest.mark.parametrize(
    "grant",
    [
        "GRANT SELECT ON mart.customers TO hm_reader",
        "GRANT SELECT(age) ON mart.customers TO PUBLIC",
        "GRANT SELECT(price_source_units) ON mart.purchase_events TO hm_model",
        "GRANT UPDATE ON mart.purchase_events TO hm_reader",
        "GRANT INSERT(customer_id) ON mart.customers TO hm_model",
        "GRANT TRUNCATE ON staging.customers TO hm_reader",
        "GRANT REFERENCES(article_id) ON mart.articles TO hm_reader",
        "GRANT TRIGGER ON mart.purchase_events TO hm_loader",
        "GRANT EXECUTE ON FUNCTION control.deny_mutation() TO hm_reader",
    ],
)
def test_forbidden_effective_data_or_write_grants_reject_and_remain_intact(migrated, grant):
    with migrated.connect() as conn:
        conn.execute(grant)
        before = conn.execute(
            "SELECT c.oid,c.relacl::text,a.attnum,a.attacl::text "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "LEFT JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 "
            "WHERE n.nspname IN ('mart','staging','control') "
            "ORDER BY c.oid,a.attnum"
        ).fetchall()
    with migrated.connect() as conn:
        with pytest.raises(DatabaseContractError, match="incompatible_existing_group_privileges"):
            provision(conn, migrated.name)
    with migrated.connect() as conn:
        after = conn.execute(
            "SELECT c.oid,c.relacl::text,a.attnum,a.attacl::text "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "LEFT JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 "
            "WHERE n.nspname IN ('mart','staging','control') "
            "ORDER BY c.oid,a.attnum"
        ).fetchall()
        assert after == before

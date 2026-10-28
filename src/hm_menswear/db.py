"""Connection and migration primitives; no purchase loading is implemented here."""

import hashlib
import re
from importlib.resources import files

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus

from hm_menswear.permissions import has_excess_project_privileges

MIGRATION_LOCK = 684_221_902_117
GROUP_ROLES = ("hm_owner", "hm_migrator", "hm_loader", "hm_model", "hm_reader")


class DatabaseContractError(RuntimeError):
    """Safe database contract violation."""


def connect(dsn: str, *, autocommit: bool = False) -> psycopg.Connection:
    conn = psycopg.connect(dsn, autocommit=autocommit, connect_timeout=10)
    if conn.info.server_version // 10000 != 18:
        conn.close()
        raise DatabaseContractError("postgresql_18_required")
    return conn


def provision(conn: psycopg.Connection, confirmed_database: str) -> None:
    """Provision groups in an explicitly named dedicated database as an administrator."""
    with conn.transaction():
        database = conn.execute("SELECT current_database()").fetchone()[0]
        if database != confirmed_database or database in {"postgres", "template0", "template1"}:
            raise DatabaseContractError("dedicated_database_confirmation_required")
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
        for role in GROUP_ROLES:
            existing = conn.execute(
                "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
                (role,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(role))
                )
            elif any(existing):
                raise DatabaseContractError("incompatible_existing_group_role")
        memberships = conn.execute(
            "SELECT parent.rolname, child.rolname, m.admin_option, m.inherit_option, m.set_option "
            "FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid "
            "JOIN pg_roles child ON child.oid=m.member WHERE child.rolname = ANY(%s)",
            (list(GROUP_ROLES),),
        ).fetchall()
        if any(row != ("hm_owner", "hm_migrator", False, False, True) for row in memberships):
            raise DatabaseContractError("incompatible_existing_role_membership")
        conn.execute("GRANT hm_owner TO hm_migrator WITH INHERIT FALSE, SET TRUE")
        conn.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
        )
        conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        incompatible_privileges = conn.execute(
            "SELECT bool_or("
            "has_database_privilege(r.oid, current_database(), 'CREATE') OR "
            "has_database_privilege(r.oid, current_database(), 'TEMPORARY') OR "
            "EXISTS (SELECT 1 FROM pg_namespace n "
            "WHERE has_schema_privilege(r.oid, n.oid, 'CREATE')) OR "
            "EXISTS (SELECT 1 FROM pg_shdepend d "
            "WHERE d.refclassid = 'pg_authid'::regclass AND d.refobjid = r.oid "
            "AND d.deptype = 'o' AND (d.dbid = 0 OR d.dbid = "
            "(SELECT oid FROM pg_database WHERE datname = current_database())))) "
            "FROM pg_roles r WHERE r.rolname = ANY(%s)",
            ([role for role in GROUP_ROLES if role != "hm_owner"],),
        ).fetchone()[0]
        if incompatible_privileges or has_excess_project_privileges(conn):
            raise DatabaseContractError("incompatible_existing_group_privileges")
        for role in GROUP_ROLES:
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database), sql.Identifier(role)
                )
            )
        conn.execute(
            sql.SQL("GRANT CREATE ON DATABASE {} TO hm_owner").format(sql.Identifier(database))
        )


def migration_sources() -> list[tuple[str, str, str]]:
    result = []
    for resource in sorted(files("hm_menswear").joinpath("sql").iterdir(), key=lambda p: p.name):
        if re.fullmatch(r"[0-9]{4}_[a-z_]+\.sql", resource.name):
            raw = resource.read_bytes()
            result.append((resource.name, raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()))
    return result


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply all pending numbered migrations atomically, with checksums and serialization."""
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise DatabaseContractError("migration_requires_idle_connection")
    sources = migration_sources()
    if not sources or any(
        int(name[:4]) != ordinal for ordinal, (name, _, _) in enumerate(sources, 1)
    ):
        raise DatabaseContractError("invalid_migration_sequence")
    applied = []
    with conn.transaction():
        conn.execute("SET LOCAL ROLE hm_owner")
        conn.execute("SET LOCAL search_path = pg_catalog")
        conn.execute("SET LOCAL timezone = 'UTC'")
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
        conn.execute("CREATE SCHEMA IF NOT EXISTS control AUTHORIZATION hm_owner")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS control.schema_migrations ("
            "name text PRIMARY KEY, sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'), "
            "applied_at timestamptz NOT NULL DEFAULT clock_timestamp())"
        )
        ledger = dict(conn.execute("SELECT name, sha256 FROM control.schema_migrations").fetchall())
        known = {name: digest for name, _, digest in sources}
        if any(name not in known or known[name] != digest for name, digest in ledger.items()):
            raise DatabaseContractError("migration_history_mismatch")
        applied_names = [name for name, _, _ in sources if name in ledger]
        if applied_names != [name for name, _, _ in sources][: len(ledger)]:
            raise DatabaseContractError("migration_history_gap")
        for name, source, digest in sources:
            if name not in ledger:
                conn.execute(source, prepare=False)
                conn.execute(
                    "INSERT INTO control.schema_migrations(name, sha256) VALUES (%s, %s)",
                    (name, digest),
                )
                applied.append(name)
    return applied

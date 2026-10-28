"""Reject excess effective project privileges without silently editing old grants."""

import json
from importlib.resources import files

import psycopg

PROJECT_SCHEMAS = ["control", "quality", "staging", "mart", "serving", "evaluation"]
NONOWNER_GROUPS = ["hm_migrator", "hm_loader", "hm_model", "hm_reader"]


def has_excess_project_privileges(conn: psycopg.Connection) -> bool:
    policy = json.loads(files("hm_menswear").joinpath("permission_policy.json").read_text())
    for role, schema in conn.execute(
        "SELECT r.rolname,n.nspname FROM pg_roles r CROSS JOIN pg_namespace n "
        "WHERE r.rolname=ANY(%s) AND n.nspname=ANY(%s) "
        "AND has_schema_privilege(r.oid,n.oid,'USAGE')",
        (NONOWNER_GROUPS, PROJECT_SCHEMAS),
    ):
        if schema not in policy["schemas"][role]:
            return True
    table_permissions = conn.execute(
        "SELECT r.rolname,n.nspname||'.'||c.relname,p.privilege "
        "FROM pg_roles r CROSS JOIN pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES',"
        "'TRIGGER','MAINTAIN']) p(privilege) WHERE r.rolname=ANY(%s) AND n.nspname=ANY(%s) "
        "AND c.relkind IN ('r','p','v','m','f') "
        "AND has_table_privilege(r.oid,c.oid,p.privilege)",
        (NONOWNER_GROUPS, PROJECT_SCHEMAS),
    ).fetchall()
    for role, table, privilege in table_permissions:
        allowed = policy["tables"].get(table, {}).get(role, {}).get(privilege, [])
        if allowed != "*":
            return True
    column_permissions = conn.execute(
        "SELECT r.rolname,n.nspname||'.'||c.relname,a.attname,p.privilege "
        "FROM pg_roles r CROSS JOIN pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=c.oid "
        "CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) p(privilege) "
        "WHERE r.rolname=ANY(%s) AND n.nspname=ANY(%s) AND c.relkind IN ('r','p','v','m','f') "
        "AND a.attnum>0 AND NOT a.attisdropped "
        "AND has_column_privilege(r.oid,c.oid,a.attnum,p.privilege)",
        (NONOWNER_GROUPS, PROJECT_SCHEMAS),
    ).fetchall()
    for role, table, column, privilege in column_permissions:
        allowed = policy["tables"].get(table, {}).get(role, {}).get(privilege, [])
        if allowed != "*" and column not in allowed:
            return True
    # No project sequence or directly callable function is part of a runtime grant.
    # Trigger execution itself does not require a caller EXECUTE grant.
    return conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_roles r CROSS JOIN pg_proc p "
        "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE r.rolname=ANY(%s) "
        "AND n.nspname=ANY(%s) AND has_function_privilege(r.oid,p.oid,'EXECUTE')) OR "
        "EXISTS (SELECT 1 FROM pg_roles r CROSS JOIN pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE r.rolname=ANY(%s) "
        "AND n.nspname=ANY(%s) AND c.relkind='S' "
        "AND has_sequence_privilege(r.oid,c.oid,'SELECT,USAGE,UPDATE'))",
        (NONOWNER_GROUPS, PROJECT_SCHEMAS, NONOWNER_GROUPS, PROJECT_SCHEMAS),
    ).fetchone()[0]

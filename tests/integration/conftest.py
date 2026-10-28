"""Real PostgreSQL fixtures, dedicated databases, and synthetic principals only."""

import os
import secrets
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from hm_menswear.db import connect, migrate, migration_sources, provision


@dataclass
class Database:
    admin_dsn: str = field(repr=False)
    name: str
    logins: dict[str, tuple[str, str]] = field(repr=False)

    def connect(self, role="admin", *, autocommit=False):
        dsn = self.admin_dsn
        if role != "admin":
            user, password = self.logins[role]
            dsn = make_conninfo(dsn, user=user, password=password)
        return connect(dsn, autocommit=autocommit)


@pytest.fixture
def database(request):
    dsn = os.environ.get("HM_TEST_ADMIN_DSN")
    if not dsn:
        pytest.skip("real isolated PostgreSQL not configured")
    name = "hm_test_" + uuid.uuid4().hex
    logins = {}
    with connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
        target = make_conninfo(dsn, dbname=name, password=admin.info.password)
        try:
            with connect(target) as conn:
                provision(conn, name)
            for role in ["migrator", "loader", "model", "reader"]:
                username = "hm_test_" + uuid.uuid4().hex
                password = secrets.token_urlsafe(32)
                admin.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE {}").format(
                        sql.Identifier(username),
                        sql.Literal(password),
                        sql.Identifier("hm_" + role),
                    )
                )
                logins[role] = (username, password)
            yield Database(target, name, logins)
        finally:
            # Only this fixture's explicitly synthetic database/principals can be removed.
            assert name.startswith("hm_test_")
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            for username, _ in logins.values():
                admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(username)))


@pytest.fixture
def migrated(database):
    with database.connect("migrator") as conn:
        assert len(migrate(conn)) == len(migration_sources())
    return database


@contextmanager
def rejected(conn, error=psycopg.IntegrityError):
    """A failed nested transaction must leave its surrounding synthetic fixture usable."""
    with pytest.raises(error), conn.transaction():
        yield


def synthetic_release(conn, *, activate=True, namespace="synthetic"):
    release = uuid.uuid4()
    file_ids = {}
    conn.execute(
        "INSERT INTO control.releases VALUES (%s, %s, '1', '1', '1', '1', DEFAULT)",
        (release, secrets.token_hex(32)),
    )
    for index, role in enumerate(["articles", "customers", "transactions"], 1):
        file_id = uuid.uuid4()
        file_ids[role] = file_id
        conn.execute(
            "INSERT INTO control.source_files(file_id, namespace, role, sha256, byte_size, "
            "private_location) VALUES (%s, %s, %s, %s, 10, 'synthetic-not-a-source-file')",
            (file_id, namespace, role, str(index) * 64),
        )
        conn.execute(
            "INSERT INTO control.release_files VALUES (%s, %s, %s)", (release, role, file_id)
        )
    if activate:
        conn.execute("UPDATE control.lineage SET active_release_id=%s", (release,))
    return release, file_ids


def synthetic_preparation(conn, release, *, complete=True):
    prep = uuid.uuid4()
    conn.execute(
        "INSERT INTO control.preparations(preparation_id, release_id, status, private_location) "
        "VALUES (%s, %s, 'preparing', 'synthetic-preparation')",
        (prep, release),
    )
    if complete:
        conn.execute(
            "UPDATE control.preparations SET status='complete', artifact_sha256=%s, "
            "source_rows=2, rejected_rows=0, valid_out_of_scope_rows=0, valid_menswear_rows=2, "
            "completed_at=clock_timestamp() WHERE preparation_id=%s",
            ("d" * 64, prep),
        )
    return prep


def synthetic_batch(conn, release, prep, start="2020-09-01", end="2020-09-08"):
    batch = uuid.uuid4()
    conn.execute(
        "INSERT INTO control.batches(batch_id, release_id, preparation_id, start_date, "
        "end_date, status) VALUES (%s,%s,%s,%s,%s,'pending')",
        (batch, release, prep, start, end),
    )
    return batch


def synthetic_dimensions(conn, release):
    conn.execute(
        "INSERT INTO mart.articles(release_id,article_id,source_record_number, "
        "index_group_name) VALUES (%s,'0000000001',1,'Menswear')",
        (release,),
    )
    conn.execute(
        "INSERT INTO mart.customers(release_id,customer_id,source_record_number) VALUES (%s,%s,1)",
        (release, "a" * 64),
    )


def synthetic_fact(conn, release, files, batch, ordinal, **changes):
    values = {
        "article": "0000000001",
        "customer": "a" * 64,
        "date": "2020-09-01",
        "price": "0.01234567890123456789",
        "channel": "1",
    }
    values.update(changes)
    conn.execute(
        "INSERT INTO mart.purchase_events(transaction_file_id,source_record_number,release_id, "
        "article_id,customer_id,purchase_date,price_source_units,sales_channel_code,first_batch_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            files["transactions"],
            ordinal,
            release,
            values["article"],
            values["customer"],
            values["date"],
            values["price"],
            values["channel"],
            batch,
        ),
    )


def complete_batch(conn, release, files, batch, ordinals):
    for ordinal in ordinals:
        conn.execute(
            "INSERT INTO control.batch_records VALUES (%s,%s,%s,%s)",
            (batch, release, files["transactions"], ordinal),
        )
    conn.execute(
        "UPDATE control.batches SET status='completed',accepted_rows=%s, inserted_rows=%s, "
        "reused_rows=0,completed_at=clock_timestamp() WHERE batch_id=%s",
        (len(ordinals), len(ordinals), batch),
    )

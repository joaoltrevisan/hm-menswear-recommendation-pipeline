"""Synthetic occurrence, referential, temporal, and publication schema contracts."""

import secrets
import uuid
from decimal import Decimal

import psycopg
import pytest
from conftest import (
    complete_batch,
    rejected,
    synthetic_batch,
    synthetic_dimensions,
    synthetic_fact,
    synthetic_preparation,
    synthetic_release,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def prepared(migrated):
    with migrated.connect("loader") as conn:
        release, files = synthetic_release(conn)
        prep = synthetic_preparation(conn, release)
        synthetic_dimensions(conn, release)
    return migrated, release, files, prep


def test_equal_occurrences_survive_and_zero_prefixed_ids_and_decimals_roundtrip(prepared):
    database, release, files, prep = prepared
    with database.connect("loader") as conn:
        batch = synthetic_batch(conn, release, prep)
        for ordinal in [1, 2]:
            synthetic_fact(conn, release, files, batch, ordinal)
        with rejected(conn, psycopg.errors.UniqueViolation):
            synthetic_fact(conn, release, files, batch, 1)
        complete_batch(conn, release, files, batch, [1, 2])
    with database.connect("loader") as conn:
        rows = conn.execute(
            "SELECT article_id,price_source_units FROM mart.purchase_events"
        ).fetchall()
        assert rows == [("0000000001", Decimal("0.01234567890123456789"))] * 2
        assert conn.execute("SELECT fn, active, age FROM mart.customers").fetchone() == (None,) * 3
        with rejected(conn):
            conn.execute("UPDATE control.batches SET accepted_rows=3 WHERE batch_id=%s", (batch,))


@pytest.mark.parametrize(
    "field,value",
    [
        ("article", "1"),
        ("article", "0000000002"),
        ("customer", "b" * 64),
        ("date", "2020-08-31"),
        ("date", "2020-09-08"),
        ("date", "2020-02-30"),
        ("price", "-1"),
        ("price", "NaN"),
        ("price", "Infinity"),
        ("price", "-Infinity"),
        ("price", None),
        ("channel", "3"),
        ("channel", None),
    ],
)
def test_invalid_or_out_of_window_facts_rejected(prepared, field, value):
    database, release, files, prep = prepared
    with database.connect("loader") as conn:
        batch = synthetic_batch(conn, release, prep)
        with rejected(conn, psycopg.Error):
            synthetic_fact(conn, release, files, batch, 1, **{field: value})
        complete_batch(conn, release, files, batch, [])


def test_pending_publication_cannot_commit_visible_facts(prepared):
    database, release, files, prep = prepared
    with pytest.raises(psycopg.errors.CheckViolation), database.connect("loader") as conn:
        batch = synthetic_batch(conn, release, prep)
        synthetic_fact(conn, release, files, batch, 1)
    with database.connect("loader") as conn:
        assert conn.execute("SELECT count(*) FROM mart.purchase_events").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM control.batches").fetchone()[0] == 0


def test_completion_reconciles_actual_membership_and_rolls_back(prepared):
    database, release, files, prep = prepared
    with pytest.raises(psycopg.errors.CheckViolation), database.connect("loader") as conn:
        batch = synthetic_batch(conn, release, prep)
        synthetic_fact(conn, release, files, batch, 1)
        conn.execute(
            "UPDATE control.batches SET status='completed',accepted_rows=1,inserted_rows=1,"
            "reused_rows=0,completed_at=clock_timestamp() WHERE batch_id=%s",
            (batch,),
        )
    with database.connect("loader") as conn:
        assert conn.execute("SELECT count(*) FROM mart.purchase_events").fetchone()[0] == 0


def test_full_release_required_and_original_files_immutable(migrated):
    with pytest.raises(psycopg.errors.CheckViolation), migrated.connect("loader") as conn:
        conn.execute(
            "INSERT INTO control.releases VALUES (%s,%s,'1','1','1','1',DEFAULT)",
            (uuid.uuid4(), "e" * 64),
        )
    with migrated.connect("loader") as conn:
        release, _ = synthetic_release(conn)
    with migrated.connect() as conn:
        with rejected(conn):
            conn.execute("UPDATE control.source_files SET byte_size=11")
        with rejected(conn):
            conn.execute("UPDATE control.lineage SET active_release_id=NULL")
        with rejected(conn):
            conn.execute(
                "UPDATE control.releases SET parser_version='2' WHERE release_id=%s", (release,)
            )


def test_candidate_release_cannot_become_active_or_prepare(migrated):
    with migrated.connect("loader") as conn:
        synthetic_release(conn)
        candidate, _ = synthetic_release(conn, activate=False, namespace="synthetic-replacement")
        with rejected(conn):
            conn.execute("UPDATE control.lineage SET active_release_id=%s", (candidate,))
        with rejected(conn):
            synthetic_preparation(conn, candidate)


def test_incomplete_preparation_and_frozen_staging(migrated):
    with migrated.connect("loader") as conn:
        release, _ = synthetic_release(conn)
        prep = synthetic_preparation(conn, release, complete=False)
        with rejected(conn):
            synthetic_batch(conn, release, prep)
        conn.execute("INSERT INTO staging.articles VALUES (%s,1,'synthetic', '{}'::jsonb)", (prep,))
        conn.execute(
            "UPDATE control.preparations SET status='complete',artifact_sha256=%s,"
            "source_rows=0,rejected_rows=0,valid_out_of_scope_rows=0,valid_menswear_rows=0,"
            "completed_at=clock_timestamp() WHERE preparation_id=%s",
            ("d" * 64, prep),
        )
        with rejected(conn):
            conn.execute(
                "INSERT INTO staging.articles VALUES (%s,2,'synthetic', '{}'::jsonb)", (prep,)
            )
        with rejected(conn):
            conn.execute(
                "UPDATE control.preparations SET status='preparing' WHERE preparation_id=%s",
                (prep,),
            )


def test_success_run_requires_committed_batch(prepared):
    database, release, _, prep = prepared
    with pytest.raises(psycopg.errors.CheckViolation), database.connect("loader") as conn:
        batch = synthetic_batch(conn, release, prep)
        conn.execute(
            "INSERT INTO control.runs(run_id,release_id,batch_id,status,ended_at) "
            "VALUES (%s,%s,%s,'succeeded',clock_timestamp())",
            (uuid.uuid4(), release, batch),
        )


def test_scoped_article_required(prepared):
    database, release, _, _ = prepared
    with database.connect("loader") as conn, rejected(conn):
        conn.execute(
            "INSERT INTO mart.articles(release_id,article_id,source_record_number,"
            "index_group_name) VALUES (%s,'0000000002',2,'Sport')",
            (release,),
        )


def test_known_cold_customer_does_not_require_menswear_dimension(prepared):
    database, release, files, prep = prepared
    with database.connect("loader") as conn:
        batch = synthetic_batch(conn, release, prep)
        conn.execute(
            "INSERT INTO mart.customer_observations(release_id,customer_id,first_observed_date,"
            "transaction_file_id,source_record_number,first_batch_id) "
            "VALUES (%s,%s,'2020-09-01',%s,3,%s)",
            (release, "c" * 64, files["transactions"], batch),
        )
        complete_batch(conn, release, files, batch, [])
    with database.connect("model") as conn:
        assert conn.execute("SELECT customer_id FROM mart.customer_observations").fetchone() == (
            "c" * 64,
        )


def test_model_and_serving_constraints_use_only_past(prepared):
    database, release, files, prep = prepared
    customer = "a" * 64
    with database.connect("loader") as conn:
        batch = synthetic_batch(conn, release, prep)
        synthetic_fact(conn, release, files, batch, 1)
        conn.execute(
            "INSERT INTO mart.customer_observations(release_id,customer_id,first_observed_date,"
            "transaction_file_id,source_record_number,first_batch_id) "
            "VALUES (%s,%s,'2020-09-01',%s,1,%s)",
            (release, customer, files["transactions"], batch),
        )
        complete_batch(conn, release, files, batch, [1])
        conn.execute(
            "INSERT INTO mart.articles(release_id,article_id,source_record_number,"
            "index_group_name) VALUES (%s,'0000000002',2,'Menswear')",
            (release,),
        )
    model_id = secrets.token_hex(32)
    with database.connect("model") as conn:
        conn.execute(
            "INSERT INTO control.models(model_id,release_id,cutoff_date,family,config_sha256,"
            "input_snapshot_sha256,dependency_lock_sha256,code_commit,manifest,"
            "private_location,status,completed_at) VALUES (%s,%s,'2020-09-08','popularity',"
            "%s,%s,%s,%s,'{}','synthetic-artifact','complete',clock_timestamp())",
            (model_id, release, "d" * 64, "e" * 64, "f" * 64, "a" * 40),
        )

        def recommend(rank, article):
            conn.execute(
                "INSERT INTO serving.recommendations(model_id,release_id,customer_id,rank,"
                "article_id,score) VALUES (%s,%s,%s,%s,%s,1)",
                (model_id, release, customer, rank, article),
            )

        recommend(1, "0000000001")
        with rejected(conn):
            recommend(13, "0000000001")
        with rejected(conn):
            recommend(2, "0000000001")
        with rejected(conn):
            recommend(2, "0000000002")
    with database.connect("reader") as conn:
        assert conn.execute("SELECT article_id FROM serving.recommendations").fetchone() == (
            "0000000001",
        )

"""Real PostgreSQL pipeline tests use independently generated small CSVs only."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest

from hm_menswear.config import Settings
from hm_menswear.loading.lifecycle import owned_connection, recover_run
from hm_menswear.loading.preparation import prepare_dataset
from hm_menswear.loading.publish import load_window
from hm_menswear.safety import PipelineError
from tests.synthetic_source import write_source

pytestmark = pytest.mark.integration


@pytest.fixture
def pipeline(migrated, tmp_path):
    contract = write_source(tmp_path / "raw")
    role, password = migrated.logins["loader"]
    from psycopg.conninfo import make_conninfo

    settings = Settings(
        tmp_path / "raw",
        tmp_path / "work",
        100,
        make_conninfo(migrated.admin_dsn, user=role, password=password),
        "loader",
    )
    result = prepare_dataset(settings, contract=contract, pinned=False)
    return migrated, settings, result, contract


def test_integrated_load_noop_overlap_and_cold_registry(pipeline):
    database, settings, prepared, _ = pipeline
    prep = prepared["preparation_id"]
    first = load_window(settings, prep, "2020-09-01", "2020-09-08")
    assert (first["accepted_rows"], first["inserted_rows"]) == (2, 2)
    assert load_window(settings, prep, "2020-09-01", "2020-09-08")["status"] == "noop"
    with database.connect("loader") as conn:
        assert conn.execute("SELECT count(*) FROM mart.customers").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM mart.customer_observations").fetchone()[0] == 2
    overlap = load_window(settings, prep, "2020-09-01", "2020-09-10")
    assert (overlap["inserted_rows"], overlap["reused_rows"]) == (2, 2)
    with database.connect("loader") as conn:
        assert conn.execute("SELECT count(*) FROM mart.purchase_events").fetchone()[0] == 4
        assert conn.execute("SELECT count(*) FROM control.batch_records").fetchone()[0] == 6


@pytest.mark.parametrize(
    "point", ["after_dimensions", "after_facts", "before_completion", "before_commit"]
)
def test_failure_rolls_back_whole_publication_then_retry(pipeline, point):
    database, settings, prepared, _ = pipeline

    def fail(stage, conn):
        if stage == point:
            raise PipelineError("synthetic_failure")

    with pytest.raises(PipelineError):
        load_window(settings, prepared["preparation_id"], "2020-09-01", "2020-09-08", hook=fail)
    with database.connect("loader") as conn:
        assert conn.execute("SELECT count(*) FROM mart.purchase_events").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM mart.articles").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM control.batches").fetchone()[0] == 0
    assert (
        load_window(settings, prepared["preparation_id"], "2020-09-01", "2020-09-08")[
            "inserted_rows"
        ]
        == 2
    )


@pytest.mark.parametrize("overlap", [False, True])
def test_two_workers_same_or_overlapping_windows(pipeline, overlap):
    database, settings, prepared, _ = pipeline
    barrier = Barrier(2)

    def hook(stage, conn):
        if stage == "waiting":
            barrier.wait(timeout=10)

    def run(end):
        return load_window(settings, prepared["preparation_id"], "2020-09-01", end, hook=hook)

    ends = ["2020-09-08", "2020-09-10" if overlap else "2020-09-08"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ends))
    assert sum(r["inserted_rows"] for r in results) == (4 if overlap else 2)
    if not overlap:
        assert sorted(r["status"] for r in results) == ["noop", "succeeded"]
    with database.connect("loader") as conn:
        assert conn.execute("SELECT count(*) FROM mart.purchase_events").fetchone()[0] == (
            4 if overlap else 2
        )


def test_live_waiter_owned_and_abandoned_attempt_recovered(pipeline):
    database, settings, prepared, _ = pipeline
    run = uuid.uuid4()
    conn = owned_connection(settings, run)
    conn.execute(
        "INSERT INTO control.runs(run_id,release_id,preparation_id,status,operation) VALUES(%s,%s,%s,'waiting_to_publish','load')",
        (run, uuid.UUID(prepared["release_id"]), uuid.UUID(prepared["preparation_id"])),
    )
    assert recover_run(settings, run)["status"] == "owned"
    conn.close()
    assert recover_run(settings, run)["status"] == "interrupted"
    assert recover_run(settings, run)["status"] == "interrupted"


def test_lost_connection_never_resumes_old_attempt(pipeline):
    database, settings, prepared, _ = pipeline

    def disconnect(stage, conn):
        if stage == "after_facts":
            with database.connect(autocommit=True) as admin:
                admin.execute("SELECT pg_terminate_backend(%s)", (conn.info.backend_pid,))

    with pytest.raises(psycopg.Error):
        load_window(
            settings, prepared["preparation_id"], "2020-09-01", "2020-09-08", hook=disconnect
        )
    assert (
        load_window(settings, prepared["preparation_id"], "2020-09-01", "2020-09-08")[
            "inserted_rows"
        ]
        == 2
    )


def test_uncertain_client_outcome_is_read_from_committed_ledger(pipeline):
    _, settings, prepared, _ = pipeline

    def uncertain(stage, conn):
        if stage == "after_commit":
            conn.close()
            raise psycopg.OperationalError("synthetic lost response")

    result = load_window(
        settings, prepared["preparation_id"], "2020-09-01", "2020-09-08", hook=uncertain
    )
    assert result["status"] == "succeeded" and result["commit_verified"]
    assert (
        load_window(settings, prepared["preparation_id"], "2020-09-01", "2020-09-08")["status"]
        == "noop"
    )


def test_preparation_rerun_reuses_complete_artifact_and_changed_source_blocked(pipeline):
    _, settings, prepared, contract = pipeline
    again = prepare_dataset(settings, contract=contract, pinned=False)
    assert (
        again["preparation_id"] == prepared["preparation_id"]
        and again["run_id"] != prepared["run_id"]
    )
    path = settings.raw_dir / "transactions_train.csv"
    with path.open("a") as stream:
        stream.write("2020-09-09," + "a" * 64 + ",0000000001,0.01,1\n")
    with pytest.raises(PipelineError, match="changed_snapshot_or_contract_requires_replacement"):
        prepare_dataset(settings, contract=contract, pinned=False)


def test_renamed_file_bytes_reuse_canonical_release(pipeline):
    _, settings, prepared, contract = pipeline
    (settings.raw_dir / "transactions_train.csv").rename(settings.raw_dir / "renamed.csv")
    result = prepare_dataset(
        settings,
        contract=contract,
        pinned=False,
        filenames={"transactions_train.csv": "renamed.csv"},
    )
    assert result["preparation_id"] == prepared["preparation_id"] and result["reused"]


@pytest.mark.parametrize("point", ["after_artifact", "after_staging"])
def test_preparation_failure_cannot_leave_complete_staging(migrated, tmp_path, point):
    from psycopg.conninfo import make_conninfo

    contract = write_source(tmp_path / "raw")
    role, password = migrated.logins["loader"]
    settings = Settings(
        tmp_path / "raw",
        tmp_path / "work",
        100,
        make_conninfo(migrated.admin_dsn, user=role, password=password),
        "loader",
    )

    def fail(stage, conn):
        if stage == point:
            raise PipelineError("synthetic_preparation_failure")

    with pytest.raises(PipelineError):
        prepare_dataset(settings, contract=contract, pinned=False, hook=fail)
    with migrated.connect("loader") as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM control.preparations WHERE status='complete'"
            ).fetchone()[0]
            == 0
        )
        assert conn.execute("SELECT count(*) FROM staging.purchase_records").fetchone()[0] == 0
    assert prepare_dataset(settings, contract=contract, pinned=False)["status"] == "prepared"


def test_empty_window_and_corrupt_preparation_artifact(pipeline):
    database, settings, prepared, _ = pipeline
    prep = prepared["preparation_id"]
    result = load_window(settings, prep, "2020-09-03", "2020-09-04")
    assert result["accepted_rows"] == 0
    with database.connect("loader") as conn:
        from pathlib import Path

        path = Path(
            conn.execute(
                "SELECT private_location FROM control.preparations WHERE preparation_id=%s",
                (uuid.UUID(prep),),
            ).fetchone()[0]
        )
    path.chmod(0o600)
    with path.open("ab") as stream:
        stream.write(b"synthetic-corruption")
    with pytest.raises(PipelineError, match="artifact_digest_mismatch"):
        load_window(settings, prep, "2020-09-01", "2020-09-08")


def test_existing_dimension_payload_must_match(pipeline):
    database, settings, prepared, _ = pipeline
    with database.connect("loader") as conn:
        conn.execute(
            "INSERT INTO mart.articles(release_id,article_id,source_record_number,index_group_name,detail_desc) VALUES(%s,'0000000001',1,'Menswear','Synthetic conflicting payload')",
            (uuid.UUID(prepared["release_id"]),),
        )
    with pytest.raises(PipelineError, match="existing_dimension_payload_mismatch"):
        load_window(settings, prepared["preparation_id"], "2020-09-01", "2020-09-08")


def test_killed_worker_rolls_back_and_can_be_recovered(pipeline):
    import json
    import os
    import select
    import subprocess
    import sys
    import time

    database, settings, prepared, _ = pipeline
    env = os.environ.copy()
    env.update(
        HM_DATABASE_DSN=settings.dsn,
        HM_RAW_DIR=str(settings.raw_dir),
        HM_WORK_DIR=str(settings.work_dir),
        HM_SYNTHETIC_PREP=prepared["preparation_id"],
    )
    code = """import os,signal,json
from hm_menswear.config import Settings
from hm_menswear.loading.publish import load_window
def hook(stage,conn):
    if stage=='before_commit':
        run=conn.execute("SELECT run_id FROM control.runs WHERE operation='load' ORDER BY started_at DESC LIMIT 1").fetchone()[0]
        print(json.dumps({'run_id':str(run)}),flush=True)
        signal.pause()
load_window(Settings.from_env('loader'),os.environ['HM_SYNTHETIC_PREP'],'2020-09-01','2020-09-08',hook=hook)
"""
    worker = subprocess.Popen(
        [sys.executable, "-c", code],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert select.select([worker.stdout], [], [], 10)[0], (
            "synthetic worker did not reach commit barrier"
        )
        line = worker.stdout.readline()
        assert line, "synthetic worker failed before the commit barrier"
        event = json.loads(line)
        worker.kill()
        worker.wait(timeout=10)
        deadline = time.monotonic() + 10
        result = recover_run(settings, event["run_id"])
        while result["status"] == "owned" and time.monotonic() < deadline:
            time.sleep(0.01)
            result = recover_run(settings, event["run_id"])
        assert result["status"] == "interrupted"
        with database.connect("loader") as conn:
            assert conn.execute("SELECT count(*) FROM mart.purchase_events").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM control.batches").fetchone()[0] == 0
        assert (
            load_window(settings, prepared["preparation_id"], "2020-09-01", "2020-09-08")[
                "inserted_rows"
            ]
            == 2
        )
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.communicate(timeout=10)


@pytest.mark.parametrize("invalid_price", ["١", "1e1000000", "1e-1000000"])
def test_invalid_numeric_tokens_reject_one_row_and_good_neighbors_load(
    migrated, tmp_path, invalid_price
):
    from psycopg.conninfo import make_conninfo

    rows = [
        ["2020-09-01", "a" * 64, "0000000001", "0.01", "1"],
        ["2020-09-02", "b" * 64, "0000000001", invalid_price, "1"],
        ["2020-09-03", "a" * 64, "0000000001", "0.02", "2"],
    ]
    contract = write_source(tmp_path / "raw", transactions=rows)
    role, password = migrated.logins["loader"]
    settings = Settings(
        tmp_path / "raw",
        tmp_path / "work",
        100,
        make_conninfo(migrated.admin_dsn, user=role, password=password),
        "loader",
    )
    prepared = prepare_dataset(settings, contract=contract, pinned=False)
    assert prepared["summary"]["rejected_rows"] == 1
    assert prepared["summary"]["valid_menswear_rows"] == 2
    result = load_window(settings, prepared["preparation_id"], "2020-09-01", "2020-09-08")
    assert result["inserted_rows"] == 2
    with migrated.connect("loader") as conn:
        assert conn.execute(
            "SELECT primary_reason FROM quality.rejections WHERE role='transactions'"
        ).fetchall() == [("invalid_price",)]


@pytest.mark.parametrize("invalid_age", ["٤٩", "0e-1000000", "0e1000000"])
def test_unicode_age_rejects_metadata_without_aborting_good_neighbors(
    migrated, tmp_path, invalid_age
):
    import csv

    from psycopg.conninfo import make_conninfo

    rows = [
        ["2020-09-01", "a" * 64, "0000000001", "0.01", "1"],
        ["2020-09-02", "b" * 64, "0000000001", "0.03", "1"],
        ["2020-09-03", "a" * 64, "0000000001", "0.02", "2"],
    ]
    contract = write_source(tmp_path / "raw", transactions=rows)
    path = tmp_path / "raw" / "customers.csv"
    with path.open(newline="") as stream:
        customers = list(csv.reader(stream))
    customers[2][5] = invalid_age
    with path.open("w", newline="") as stream:
        csv.writer(stream).writerows(customers)
    role, password = migrated.logins["loader"]
    settings = Settings(
        tmp_path / "raw",
        tmp_path / "work",
        100,
        make_conninfo(migrated.admin_dsn, user=role, password=password),
        "loader",
    )
    prepared = prepare_dataset(settings, contract=contract, pinned=False)
    assert prepared["summary"]["dimension_rejections"] == {"customers": 1}
    assert prepared["summary"]["rejected_rows"] == 1
    assert (
        load_window(settings, prepared["preparation_id"], "2020-09-01", "2020-09-08")[
            "inserted_rows"
        ]
        == 2
    )

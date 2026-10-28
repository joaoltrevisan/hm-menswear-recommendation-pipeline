"""CLI walkthrough uses independent synthetic source/provenance, isolated DB only."""

import copy
import io
import json

import pytest
from psycopg.conninfo import make_conninfo

import hm_menswear.cli as cli
from hm_menswear.evaluation.protocol import load_protocol
from hm_menswear.loading.preparation import prepare_dataset
from tests.integration.test_baselines import SYNTHETIC_CODE
from tests.synthetic_source import write_source

pytestmark = pytest.mark.integration


def test_synthetic_cli_walkthrough(migrated, tmp_path, monkeypatch, capsys):
    rows = [
        ["2020-09-01", "a" * 64, "0000000001", "0.01", "1"],
        ["2020-09-01", "a" * 64, "0000000001", "0.01", "1"],
        ["2020-09-08", "a" * 64, "0000000001", "0.01", "1"],
        ["2020-09-02", "b" * 64, "0000000002", "0.02", "2"],
        ["2020-09-09", "a" * 64, "0000000001", "0.01", "1"],
        ["2020-09-16", "a" * 64, "0000000001", "0.01", "1"],
        ["2020-09-22", "c" * 64, "0000000004", "0.01", "2"],
    ]
    contract = write_source(tmp_path / "raw", transactions=rows)
    work = tmp_path / "work"
    monkeypatch.setenv("HM_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("HM_WORK_DIR", str(work))
    monkeypatch.setenv("HM_CHUNK_SIZE", "100")
    for role, var in [
        ("migrator", "HM_MIGRATION_DSN"),
        ("loader", "HM_DATABASE_DSN"),
        ("model", "HM_MODEL_DSN"),
        ("reader", "HM_READER_DSN"),
    ]:
        user, password = migrated.logins[role]
        monkeypatch.setenv(var, make_conninfo(migrated.admin_dsn, user=user, password=password))
    # Only this synthetic test fixture substitutes the source contract and fabricated provenance.
    monkeypatch.setattr(
        cli,
        "prepare_dataset",
        lambda settings, **kwargs: prepare_dataset(settings, contract=contract, pinned=False),
    )
    protocol = copy.deepcopy(load_protocol())
    protocol["source_start"] = "2020-09-01"
    monkeypatch.setattr(cli, "load_protocol", lambda: protocol)
    for module in ["workflow", "comparison"]:
        monkeypatch.setattr(
            f"hm_menswear.recommendation.{module}.code_identity", lambda: SYNTHETIC_CODE
        )
    monkeypatch.setattr("hm_menswear.evaluation.holdout.code_identity", lambda: SYNTHETIC_CODE)
    monkeypatch.setattr("hm_menswear.recommendation.selected.code_identity", lambda: SYNTHETIC_CODE)
    outputs = []

    def run(*args):
        assert cli.main(list(args)) == 0
        raw = capsys.readouterr().out
        outputs.append(raw)
        return json.loads(raw)

    assert run("db", "migrate")["applied"] == []
    prepared = run("prepare")
    prep = prepared["preparation_id"]
    first = run("load-next", "--preparation", prep)
    assert first["inserted_rows"] == 2
    assert (
        run("load", "--preparation", prep, "--start", "2020-09-01", "--end", "2020-09-08")["status"]
        == "noop"
    )
    run("load-all", "--preparation", prep)
    assert run("load-next", "--preparation", prep)["status"] == "source_exhausted"
    comparison = work / "reports" / "validation.json"
    run("compare-models", "--output", str(comparison))
    final = work / "reports" / "test.json"
    run("final-test", "--comparison", str(comparison), "--output", str(final))
    receipt = json.loads(final.read_text())
    session = receipt["test_session_id"]
    out = work / "reports" / "export.json"
    run("export-test", "--session", session, "--output", str(out))
    assert json.loads(out.read_text()) == receipt
    retrained = run("retrain-selected", "--session", session, "--cutoff", "2020-09-22")
    assert (
        retrained["horizon_measured"] is False
        and retrained["horizon_end_exclusive"] == "2020-09-30"
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("a" * 64 + "\n"))
    recommendation = run("recommend", "--model-id", retrained["model_id"], "--customer-stdin")
    assert recommendation["articles"] == ["0000000001", "0000000004"]
    for token in [
        "a" * 64,
        "b" * 64,
        "c" * 64,
        *[password for user, password in migrated.logins.values()],
    ]:
        assert token not in "".join(outputs)


def test_uncertain_scheduled_commit_retries_only_the_original_window(
    migrated, tmp_path, monkeypatch
):
    import psycopg

    import hm_menswear.jobs as jobs
    from hm_menswear.config import Settings
    from hm_menswear.db import connect

    contract = write_source(tmp_path / "raw")
    user, password = migrated.logins["loader"]
    settings = Settings(
        tmp_path / "raw",
        tmp_path / "work",
        100,
        make_conninfo(migrated.admin_dsn, user=user, password=password),
        "loader",
    )
    prep = prepare_dataset(settings, contract=contract, pinned=False)["preparation_id"]
    real = jobs.publish_planned_window
    calls = []

    def uncertain(settings, preparation, window):
        calls.append(window)
        result = real(settings, preparation, window)
        if len(calls) == 1:
            raise psycopg.OperationalError("synthetic outcome lost after successful commit")
        return result

    monkeypatch.setattr(jobs, "publish_planned_window", uncertain)
    result = jobs.load_next(settings, prep, sleep=lambda _: None)
    assert result["retry_count"] == 1 and result["status"] == "noop"
    assert len(calls) == 2 and calls[0] == calls[1]
    with connect(settings.dsn, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT start_date::text,end_date::text FROM control.batches WHERE status='completed'"
        ).fetchall()
        assert rows == [("2020-09-01", "2020-09-08")]
        assert conn.execute("SELECT count(*) FROM mart.purchase_events").fetchone()[0] == 2

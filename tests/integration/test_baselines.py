"""Synthetic PostgreSQL-to-model-to-metric integration; no actual customer fixtures."""

import copy

import pytest
from psycopg.conninfo import make_conninfo

from hm_menswear.config import Settings
from hm_menswear.evaluation.evaluate import evaluate_model
from hm_menswear.evaluation.protocol import load_protocol
from hm_menswear.loading.preparation import prepare_dataset
from hm_menswear.loading.publish import load_window
from hm_menswear.recommendation.artifacts import load_registered_model, recommend
from hm_menswear.recommendation.snapshot import build_snapshot
from hm_menswear.recommendation.workflow import train_baseline
from hm_menswear.safety import PipelineError
from tests.synthetic_source import write_source

pytestmark = pytest.mark.integration
SYNTHETIC_CODE = {
    "code_commit": "a" * 40,
    "source_tree_sha256": "b" * 64,
    "dependency_lock_sha256": "c" * 64,
    "python": "3.12.14",
}


@pytest.fixture
def modeling(migrated, tmp_path):
    rows = [
        ["2020-09-01", "a" * 64, "0000000001", "0.01", "1"],
        ["2020-09-08", "a" * 64, "0000000001", "0.01", "1"],
        ["2020-09-02", "b" * 64, "0000000002", "0.02", "2"],
        ["2020-09-09", "a" * 64, "0000000001", "0.01", "1"],
        ["2020-09-09", "c" * 64, "0000000004", "0.01", "2"],
        ["2020-09-22", "b" * 64, "0000000002", "0.02", "2"],
    ]
    contract = write_source(tmp_path / "raw", transactions=rows)

    def settings(role):
        user, password = migrated.logins[role]
        return Settings(
            tmp_path / "raw",
            tmp_path / "work",
            100,
            make_conninfo(migrated.admin_dsn, user=user, password=password),
            "model" if role == "model" else "loader",
        )

    loader = settings("loader")
    prepared = prepare_dataset(loader, contract=contract, pinned=False)
    load_window(loader, prepared["preparation_id"], "2020-09-01", "2020-09-23")
    protocol = copy.deepcopy(load_protocol())
    protocol["source_start"] = "2020-09-01"
    return migrated, settings("model"), protocol


def test_cutoff_snapshot_baselines_metrics_and_cold_fallback(modeling):
    db, settings, protocol = modeling
    from hm_menswear.db import connect

    with connect(settings.dsn, autocommit=True) as conn:
        snapshot = build_snapshot(conn, "2020-09-08", protocol)
    assert len(snapshot.known_ids) == 2 and len(snapshot.warm_ids) == 1
    assert snapshot.articles.tolist() == [b"0000000001"]
    assert len(snapshot.items) == 2
    model = train_baseline(
        settings,
        "repeat_history",
        "2020-09-08",
        7,
        protocol,
        identity=SYNTHETIC_CODE,
        snapshot=snapshot,
    )
    with connect(settings.dsn, autocommit=True) as conn:
        loaded = load_registered_model(conn, settings.work_dir, model["model_id"])
        report = evaluate_model(conn, loaded, protocol)
        with pytest.raises(PipelineError, match="reserved_test"):
            evaluate_model(conn, loaded, protocol, split="test")
    assert report["cohorts"]["primary"]["map_at_12"] == 0.5
    assert report["cohorts"]["primary"]["recall_at_12"] == 0.5
    assert report["cohorts"]["buyers_known"]["map_at_12"] == 1
    assert report["cohorts"]["future_first_buyers"]["map_at_12"] == 0
    assert recommend(loaded, "b" * 64)["strategy"] == "no_menswear_history"
    assert recommend(loaded, "f" * 64)["strategy"] == "unobserved_customer"
    assert recommend(loaded, "a" * 64)["articles"] == ["0000000001"]


def test_missing_committed_history_fails_before_training(modeling):
    _, settings, protocol = modeling
    from hm_menswear.db import connect

    bad = copy.deepcopy(protocol)
    bad["source_start"] = "2020-08-31"
    with (
        connect(settings.dsn, autocommit=True) as conn,
        pytest.raises(PipelineError, match="incomplete_temporal_coverage"),
    ):
        build_snapshot(conn, "2020-09-08", bad)


def test_retraining_is_deterministic_and_artifact_corruption_is_refused(modeling):
    _, settings, protocol = modeling
    from pathlib import Path

    from hm_menswear.db import connect

    first = train_baseline(
        settings, "popularity", "2020-09-08", 7, protocol, identity=SYNTHETIC_CODE
    )
    second = train_baseline(
        settings, "popularity", "2020-09-08", 7, protocol, identity=SYNTHETIC_CODE
    )
    assert first["model_id"] == second["model_id"]
    path = Path(settings.work_dir) / "models" / first["model_id"] / "arrays.npz"
    with path.open("ab") as stream:
        stream.write(b"synthetic-corruption")
    with (
        connect(settings.dsn, autocommit=True) as conn,
        pytest.raises(PipelineError, match="artifact_digest"),
    ):
        load_registered_model(conn, settings.work_dir, first["model_id"])


def test_unregistered_artifact_cannot_serve(modeling):
    _, settings, protocol = modeling
    import psycopg

    from hm_menswear.db import connect

    identity = {**SYNTHETIC_CODE, "code_commit": "not-a-commit"}
    with pytest.raises(psycopg.IntegrityError):
        train_baseline(settings, "popularity", "2020-09-08", 7, protocol, identity=identity)
    directories = list((settings.work_dir / "models").iterdir())
    assert len(directories) == 1
    with (
        connect(settings.dsn, autocommit=True) as conn,
        pytest.raises(PipelineError, match="complete_registered"),
    ):
        load_registered_model(conn, settings.work_dir, directories[0].name)

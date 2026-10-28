"""Synthetic complete search, durable freeze-before-labels and safe replay."""

import copy

import pytest

from hm_menswear.db import connect
from hm_menswear.evaluation.evaluate import read_labels
from hm_menswear.evaluation.holdout import frozen_final_test
from hm_menswear.recommendation.artifacts import load_registered_model
from hm_menswear.recommendation.comparison import compare_models
from hm_menswear.safety import PipelineError
from tests.integration.test_baselines import SYNTHETIC_CODE
from tests.integration.test_baselines import modeling as modeling

pytestmark = pytest.mark.integration


def test_complete_search_freezes_before_labels_and_replays_without_read(modeling, monkeypatch):
    _, settings, protocol = modeling
    report = compare_models(settings, protocol, identity=SYNTHETIC_CODE)
    assert len(report["reports"]) == 10 and report["final_test_consumed"] is False
    with connect(settings.dsn, autocommit=True) as conn:
        model = load_registered_model(conn, settings.work_dir, report["reports"][0]["model_id"])
        with pytest.raises(PipelineError, match="owned_frozen_reservation"):
            read_labels(conn, model, "test", protocol)

    def check_reserved(conn, session):
        assert (
            conn.execute(
                "SELECT count(*) FROM evaluation.test_sessions WHERE test_session_id=%s", (session,)
            ).fetchone()[0]
            == 1
        )
        with pytest.raises(PipelineError, match="already_owned"):
            frozen_final_test(settings, report, protocol, identity=SYNTHETIC_CODE)
        # A separate connection proves the reservation has committed before labels.
        with connect(settings.dsn, autocommit=True) as other:
            assert other.execute("SELECT count(*) FROM evaluation.test_sessions").fetchone()[0] == 1

    result = frozen_final_test(
        settings, report, protocol, identity=SYNTHETIC_CODE, before_labels=check_reserved
    )
    assert len(result["reports"]) == 10 and sum(r["selected"] for r in result["reports"]) == 1
    assert result["test_reselection_permitted"] is False
    import uuid

    import psycopg

    with connect(settings.dsn, autocommit=True) as conn:
        with (
            pytest.raises(psycopg.errors.UniqueViolation, match="one_reserved_test_per_release"),
            conn.transaction(),
        ):
            conn.execute(
                "INSERT INTO evaluation.test_sessions(test_session_id,protocol_sha256,selected_model_id,frozen_recipe_sha256,release_id,recipe,allowed_models) SELECT %s,%s,selected_model_id,frozen_recipe_sha256,release_id,recipe,allowed_models FROM evaluation.test_sessions",
                (uuid.uuid4(), "f" * 64),
            )

    def forbidden(*args, **kwargs):
        pytest.fail("completed frozen test must not read labels again")

    monkeypatch.setattr("hm_menswear.evaluation.holdout.read_labels", forbidden)
    assert frozen_final_test(settings, report, protocol, identity=SYNTHETIC_CODE) == result
    changed = copy.deepcopy(report)
    changed["status"] = "changed-recipe"
    with pytest.raises(PipelineError, match="already_reserved_for_other_recipe"):
        frozen_final_test(settings, changed, protocol, identity=SYNTHETIC_CODE)
    with connect(settings.dsn, autocommit=True) as conn:
        assert (
            conn.execute("SELECT count(*) FROM evaluation.runs WHERE split='test'").fetchone()[0]
            == 10
        )


def test_failed_reserved_test_can_only_resume_same_recipe(modeling):
    _, settings, protocol = modeling
    report = compare_models(settings, protocol, identity=SYNTHETIC_CODE)

    def interrupted(conn, session):
        raise RuntimeError("synthetic interruption after durable reservation")

    with pytest.raises(RuntimeError, match="synthetic interruption"):
        frozen_final_test(
            settings, report, protocol, identity=SYNTHETIC_CODE, before_labels=interrupted
        )
    with connect(settings.dsn, autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM evaluation.test_sessions").fetchone()[0] == 1
        assert (
            conn.execute("SELECT count(*) FROM evaluation.runs WHERE split='test'").fetchone()[0]
            == 0
        )
    result = frozen_final_test(settings, report, protocol, identity=SYNTHETIC_CODE)
    assert len(result["reports"]) == 10


@pytest.mark.parametrize("mutation", ["metric", "selection", "grid", "code"])
def test_modified_comparison_refused_before_holdout_reservation(modeling, mutation):
    _, settings, protocol = modeling
    report = compare_models(settings, protocol, identity=SYNTHETIC_CODE)
    if mutation == "metric":
        report["reports"][0]["cohorts"]["primary"]["map_at_12"] = 0.123
    if mutation == "selection":
        report["selected_model_id"] = "0" * 64
    if mutation == "grid":
        report["reports"].pop()
    if mutation == "code":
        report["code_identity"]["source_tree_sha256"] = "f" * 64
    with pytest.raises(PipelineError):
        frozen_final_test(settings, report, protocol, identity=SYNTHETIC_CODE)
    with connect(settings.dsn, autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM evaluation.test_sessions").fetchone()[0] == 0

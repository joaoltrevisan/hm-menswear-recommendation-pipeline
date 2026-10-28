"""Export immutable aggregate results and retrain the preselected recipe explicitly."""

import uuid
from datetime import date, timedelta

from hm_menswear.db import connect
from hm_menswear.evaluation.holdout import sha
from hm_menswear.evaluation.protocol import validate_protocol
from hm_menswear.recommendation.artifacts import code_identity
from hm_menswear.recommendation.comparison import train_item_item
from hm_menswear.recommendation.snapshot import build_snapshot
from hm_menswear.recommendation.workflow import train_baseline
from hm_menswear.safety import PipelineError
from hm_menswear.validation.values import valid_date


def completed_session(conn, session):
    session = uuid.UUID(str(session))
    row = conn.execute(
        "SELECT release_id,protocol_sha256,selected_model_id,frozen_recipe_sha256,recipe,allowed_models FROM evaluation.test_sessions WHERE test_session_id=%s",
        (session,),
    ).fetchone()
    if row is None:
        raise PipelineError("frozen_test_session_required")
    release, protocol_hash, selected, recipe_hash, recipe, allowed = row
    if sha(recipe) != recipe_hash:
        raise PipelineError("frozen_recipe_digest_mismatch")
    results = conn.execute(
        "SELECT metrics FROM evaluation.runs WHERE test_session_id=%s AND split='test'", (session,)
    ).fetchall()
    by_id = {r[0]["model_id"]: r[0] for r in results}
    if len(by_id) != len(allowed) or set(by_id) != {m["model_id"] for m in allowed}:
        raise PipelineError("complete_frozen_test_results_required")
    reports = [by_id[m["model_id"]] for m in allowed]
    if (
        sum(bool(r["selected"]) for r in reports) != 1
        or next(r for r in reports if r["selected"])["validation_model_id"] != selected
    ):
        raise PipelineError("stored_selection_mismatch")
    return {
        "session": session,
        "release": str(release),
        "protocol_hash": protocol_hash,
        "selected": selected,
        "recipe_hash": recipe_hash,
        "recipe": recipe,
        "reports": reports,
    }


def export_test(settings, session):
    with connect(settings.dsn, autocommit=True) as conn:
        saved = completed_session(conn, session)
    return {
        "status": "frozen_final_test_complete",
        "test_session_id": str(saved["session"]),
        "frozen_recipe_sha256": saved["recipe_hash"],
        "selected_validation_model_id": saved["selected"],
        "reports": saved["reports"],
        "selection_uses_validation_only": True,
        "test_reselection_permitted": False,
    }


def retrain_selected(settings, session, cutoff, protocol, *, identity=None):
    validate_protocol(protocol)
    if not valid_date(cutoff) or cutoff < protocol["test"]["cutoff"]:
        raise PipelineError("selected_retrain_cutoff_must_follow_validation")
    identity = code_identity() if identity is None else identity
    with connect(settings.dsn, autocommit=True) as conn:
        saved = completed_session(conn, session)
        if saved["protocol_hash"] != sha(protocol):
            raise PipelineError("selection_protocol_mismatch")
        config = next(
            c
            for c in saved["recipe"]["configurations"]
            if c["validation_model_id"] == saved["selected"]
        )
        snapshot = build_snapshot(conn, cutoff, protocol)
    if snapshot.release_id != saved["release"]:
        raise PipelineError("selection_source_release_mismatch")
    identity = {
        **identity,
        "selection_test_session_id": str(saved["session"]),
        "selection_recipe_sha256": saved["recipe_hash"],
        "selection_validation_model_id": saved["selected"],
    }
    if config["family"] == "item_item":
        model = train_item_item(
            settings, cutoff, config["parameters"], protocol, identity=identity, snapshot=snapshot
        )
    else:
        model = train_baseline(
            settings,
            config["family"],
            cutoff,
            config["parameters"]["window_days"],
            protocol,
            identity=identity,
            snapshot=snapshot,
        )
    return {
        "status": "selected_recipe_retrained",
        "model_id": model["model_id"],
        "family": config["family"],
        "parameters": config["parameters"],
        "cutoff": cutoff,
        "horizon_start": (date.fromisoformat(cutoff) + timedelta(days=1)).isoformat(),
        "horizon_end_exclusive": (date.fromisoformat(cutoff) + timedelta(days=8)).isoformat(),
        "horizon_measured": False,
        "selection_uses_validation_only": True,
    }

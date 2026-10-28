"""Immutable source-release holdout reservation and resumable frozen evaluation."""

import hashlib
import uuid

import numpy as np
from psycopg.types.json import Jsonb

from hm_menswear.db import connect
from hm_menswear.evaluation.evaluate import evaluate_rankings, read_labels
from hm_menswear.evaluation.protocol import validate_protocol
from hm_menswear.extraction.source import canonical_json
from hm_menswear.recommendation.artifacts import code_identity, load_registered_model
from hm_menswear.recommendation.comparison import train_item_item
from hm_menswear.recommendation.snapshot import build_snapshot
from hm_menswear.recommendation.workflow import selection_key, train_baseline
from hm_menswear.safety import PipelineError


def sha(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def validate_comparison(conn, settings, comparison, protocol, identity):
    validate_protocol(protocol)
    reports = comparison["reports"]
    if (
        len(reports) != 10
        or len({r["model_id"] for r in reports}) != 10
        or comparison["protocol_sha256"] != sha(protocol)
    ):
        raise PipelineError("complete_ten_model_validation_required")
    baselines = [r for r in reports if r["family"] in ("popularity", "repeat_history")]
    if {(r["family"], canonical_json(r["parameters"])) for r in baselines} != {
        (family, canonical_json({"window_days": w, "k": 12}))
        for family in ("popularity", "repeat_history")
        for w in protocol["popularity_windows"]
    }:
        raise PipelineError("baseline_grid_mismatch")
    best_pop = min(
        (r for r in baselines if r["family"] == "popularity"),
        key=lambda r: selection_key(r, protocol),
    )
    best_hist = min(
        (r for r in baselines if r["family"] == "repeat_history"),
        key=lambda r: selection_key(r, protocol),
    )
    item_expected = {
        canonical_json(
            {
                "training_days": days,
                "neighbors": n,
                "popularity_days": best_pop["parameters"]["window_days"],
                "history_days": best_hist["parameters"]["window_days"],
                "minimum_pair_support": 2,
                "k": 12,
            }
        )
        for days in (90, 180)
        for n in (20, 50)
    }
    if {
        canonical_json(r["parameters"]) for r in reports if r["family"] == "item_item"
    } != item_expected:
        raise PipelineError("item_item_grid_mismatch")
    selected = min(reports, key=lambda r: selection_key(r, protocol))
    if (
        comparison["selected_model_id"] != selected["model_id"]
        or comparison["selected_family"] != selected["family"]
        or comparison["selected_parameters"] != selected["parameters"]
    ):
        raise PipelineError("validation_selection_mismatch")
    release = None
    fingerprint = None
    for report in reports:
        expected = {key: value for key, value in report.items() if key != "elapsed_seconds"}
        registered = conn.execute(
            "SELECT metrics FROM evaluation.runs WHERE model_id=%s AND split='validation' AND protocol_sha256=%s",
            (report["model_id"], sha(protocol)),
        ).fetchall()
        if not any(row[0] == expected for row in registered):
            raise PipelineError("validation_report_not_registered")
        model = load_registered_model(conn, settings.work_dir, report["model_id"])
        manifest = model["manifest"]
        if (
            manifest["cutoff"] != protocol["validation"]["cutoff"]
            or manifest["parameters"] != report["parameters"]
            or manifest["family"] != report["family"]
            or manifest["protocol_sha256"] != sha(protocol)
        ):
            raise PipelineError("validation_model_mismatch")
        for key in [
            "source_tree_sha256",
            "dependency_lock_sha256",
            "python",
            "platform",
            "architecture",
        ]:
            if manifest.get(key) != identity.get(key) or comparison["code_identity"].get(
                key
            ) != identity.get(key):
                raise PipelineError("frozen_evaluation_code_mismatch")
        if release is None:
            release = manifest["release_id"]
            fingerprint = manifest["input_snapshot_sha256"]
        if manifest["release_id"] != release or manifest["input_snapshot_sha256"] != fingerprint:
            raise PipelineError("inconsistent_validation_inputs")
    return {
        "comparison_sha256": sha(comparison),
        "protocol_sha256": sha(protocol),
        "release_id": release,
        "selected_validation_model_id": selected["model_id"],
        "validation_code_identity": comparison["code_identity"],
        "configurations": [
            {
                "validation_model_id": r["model_id"],
                "family": r["family"],
                "parameters": r["parameters"],
            }
            for r in reports
        ],
    }


def frozen_final_test(settings, comparison, protocol, *, identity=None, before_labels=None):
    identity = code_identity() if identity is None else identity
    with connect(settings.dsn, autocommit=True) as conn:
        recipe = validate_comparison(conn, settings, comparison, protocol, identity)
        release = uuid.UUID(recipe["release_id"])
        key = int.from_bytes(
            hashlib.sha256(b"hm_final_test" + release.bytes).digest()[:8], "big", signed=True
        )
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]:
            raise PipelineError("final_test_workflow_already_owned")
        try:
            existing = conn.execute(
                "SELECT test_session_id,frozen_recipe_sha256,recipe,allowed_models FROM evaluation.test_sessions WHERE release_id=%s",
                (release,),
            ).fetchone()
            if existing:
                session, recipe_hash, saved_recipe, allowed = existing
                if recipe_hash != sha(recipe) or saved_recipe != recipe:
                    raise PipelineError("source_release_test_already_reserved_for_other_recipe")
            else:
                snapshot = build_snapshot(conn, protocol["test"]["cutoff"], protocol)
                if snapshot.release_id != recipe["release_id"]:
                    raise PipelineError("active_release_changed_before_test")
                allowed = []
                for config in recipe["configurations"]:
                    if config["family"] == "item_item":
                        model = train_item_item(
                            settings,
                            protocol["test"]["cutoff"],
                            config["parameters"],
                            protocol,
                            identity=identity,
                            snapshot=snapshot,
                        )
                    else:
                        model = train_baseline(
                            settings,
                            config["family"],
                            protocol["test"]["cutoff"],
                            config["parameters"]["window_days"],
                            protocol,
                            identity=identity,
                            snapshot=snapshot,
                        )
                    allowed.append(
                        {
                            "model_id": model["model_id"],
                            "validation_model_id": config["validation_model_id"],
                            "family": config["family"],
                            "parameters": config["parameters"],
                        }
                    )
                session = uuid.uuid4()
                with conn.transaction():
                    conn.execute(
                        "INSERT INTO evaluation.test_sessions(test_session_id,protocol_sha256,selected_model_id,frozen_recipe_sha256,release_id,recipe,allowed_models) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                        (
                            session,
                            sha(protocol),
                            recipe["selected_validation_model_id"],
                            sha(recipe),
                            release,
                            Jsonb(recipe),
                            Jsonb(allowed),
                        ),
                    )
            stored = conn.execute(
                "SELECT metrics FROM evaluation.runs WHERE test_session_id=%s AND split='test'",
                (session,),
            ).fetchall()
            if stored:
                reports = {row[0]["model_id"]: row[0] for row in stored}
                if set(reports) != {x["model_id"] for x in allowed}:
                    raise PipelineError("incomplete_frozen_test_result_set")
                results = [reports[x["model_id"]] for x in allowed]
            else:
                # Reservation is already committed before this point; failure can only resume this recipe.
                if before_labels is not None:
                    before_labels(conn, session)
                results = []
                labels = None
                label_hash = None
                first = None
                for config in allowed:
                    model = load_registered_model(conn, settings.work_dir, config["model_id"])
                    manifest = model["manifest"]
                    if (
                        manifest["release_id"] != recipe["release_id"]
                        or manifest["cutoff"] != protocol["test"]["cutoff"]
                        or manifest["parameters"] != config["parameters"]
                        or manifest["family"] != config["family"]
                        or manifest["protocol_sha256"] != sha(protocol)
                    ):
                        raise PipelineError("frozen_test_model_mismatch")
                    if first is None:
                        first = model
                        labels, label_hash = read_labels(
                            conn, model, "test", protocol, test_session=session
                        )
                    elif manifest["input_snapshot_sha256"] != first["manifest"][
                        "input_snapshot_sha256"
                    ] or not all(
                        np.array_equal(model["arrays"][key], first["arrays"][key])
                        for key in ["known_ids", "warm_ids", "articles"]
                    ):
                        raise PipelineError("inconsistent_refit_test_population")
                    report = evaluate_rankings(model, labels, protocol["k"])
                    report.update(
                        model_id=model["model_id"],
                        validation_model_id=config["validation_model_id"],
                        family=config["family"],
                        parameters=config["parameters"],
                        split="test",
                        label_snapshot_sha256=label_hash,
                        protocol_sha256=sha(protocol),
                        test_session_id=str(session),
                        selected=config["validation_model_id"]
                        == recipe["selected_validation_model_id"],
                    )
                    results.append(report)
                with conn.transaction():
                    for report in results:
                        conn.execute(
                            "INSERT INTO evaluation.runs(evaluation_id,model_id,protocol_sha256,config_sha256,split,test_session_id,cohort_counts,metrics) VALUES(%s,%s,%s,%s,'test',%s,%s,%s)",
                            (
                                uuid.uuid4(),
                                report["model_id"],
                                sha(protocol),
                                sha(report["parameters"]),
                                session,
                                Jsonb(
                                    {
                                        key: value["population"]
                                        for key, value in report["cohorts"].items()
                                    }
                                ),
                                Jsonb(report),
                            ),
                        )
            return {
                "status": "frozen_final_test_complete",
                "test_session_id": str(session),
                "frozen_recipe_sha256": sha(recipe),
                "selected_validation_model_id": recipe["selected_validation_model_id"],
                "reports": results,
                "selection_uses_validation_only": True,
                "test_reselection_permitted": False,
            }
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (key,))

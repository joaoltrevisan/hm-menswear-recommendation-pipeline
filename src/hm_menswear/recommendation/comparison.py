"""Predeclared ten-configuration validation comparison, never selected on test."""

import time

from hm_menswear.db import connect
from hm_menswear.evaluation.evaluate import evaluate_model
from hm_menswear.evaluation.protocol import validate_protocol
from hm_menswear.recommendation.artifacts import code_identity, save_model
from hm_menswear.recommendation.item_item import fit_item_item
from hm_menswear.recommendation.snapshot import build_snapshot
from hm_menswear.recommendation.workflow import compare_baselines, selection_key


def train_item_item(settings, cutoff, parameters, protocol, *, identity=None, snapshot=None):
    validate_protocol(protocol)
    identity = code_identity() if identity is None else identity
    with connect(settings.dsn, autocommit=True) as conn:
        snapshot = build_snapshot(conn, cutoff, protocol) if snapshot is None else snapshot
        fitted = fit_item_item(snapshot, **parameters)
        return save_model(
            conn, settings.work_dir, snapshot, "item_item", parameters, fitted, protocol, identity
        )


def compare_models(settings, protocol, *, identity=None):
    identity = code_identity() if identity is None else identity
    report = compare_baselines(settings, protocol, identity=identity)
    reports = report["reports"]
    best_pop = min(
        (x for x in reports if x["family"] == "popularity"),
        key=lambda x: selection_key(x, protocol),
    )
    best_hist = min(
        (x for x in reports if x["family"] == "repeat_history"),
        key=lambda x: selection_key(x, protocol),
    )
    with connect(settings.dsn, autocommit=True) as conn:
        snapshot = build_snapshot(conn, protocol["validation"]["cutoff"], protocol)
    for training_days in protocol["item_training_windows"]:
        for neighbors in protocol["neighbors"]:
            parameters = {
                "training_days": training_days,
                "neighbors": neighbors,
                "popularity_days": best_pop["parameters"]["window_days"],
                "history_days": best_hist["parameters"]["window_days"],
                "minimum_pair_support": protocol["minimum_pair_support"],
                "k": protocol["k"],
            }
            started = time.perf_counter()
            model = train_item_item(
                settings,
                protocol["validation"]["cutoff"],
                parameters,
                protocol,
                identity=identity,
                snapshot=snapshot,
            )
            with connect(settings.dsn, autocommit=True) as conn:
                result = evaluate_model(conn, model, protocol)
            result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            reports.append(result)
    selected = min(reports, key=lambda x: selection_key(x, protocol))
    report.update(
        status="model_validation_complete",
        selected_model_id=selected["model_id"],
        selected_family=selected["family"],
        selected_parameters=selected["parameters"],
    )
    return report

"""Baseline training/evaluation orchestration; final test requires a frozen session."""

import hashlib
import time
from pathlib import Path

from hm_menswear.db import connect
from hm_menswear.evaluation.evaluate import evaluate_model
from hm_menswear.evaluation.protocol import validate_protocol
from hm_menswear.extraction.source import canonical_json
from hm_menswear.recommendation.artifacts import code_identity, save_model
from hm_menswear.recommendation.baselines import fit_baseline
from hm_menswear.recommendation.snapshot import build_snapshot
from hm_menswear.safety import PipelineError


def train_baseline(
    settings, family, cutoff, window_days, protocol, *, identity=None, snapshot=None
):
    validate_protocol(protocol)
    identity = code_identity() if identity is None else identity
    with connect(settings.dsn, autocommit=True) as conn:
        snapshot = build_snapshot(conn, cutoff, protocol) if snapshot is None else snapshot
        fitted = fit_baseline(snapshot, family, window_days, protocol["k"])
        return save_model(
            conn,
            settings.work_dir,
            snapshot,
            family,
            {"window_days": window_days, "k": protocol["k"]},
            fitted,
            protocol,
            identity,
        )


def selection_key(report, protocol):
    score = report["cohorts"]["primary"]
    if score["map_at_12"] is None:
        raise PipelineError("empty_primary_evaluation_population")
    return (
        -score["map_at_12"],
        -score["recall_at_12"],
        protocol["family_tie_order"].index(report["family"]),
        canonical_json(report["parameters"]),
    )


def compare_baselines(settings, protocol, *, identity=None):
    validate_protocol(protocol)
    identity = code_identity() if identity is None else identity
    with connect(settings.dsn, autocommit=True) as conn:
        snapshot = build_snapshot(conn, protocol["validation"]["cutoff"], protocol)
    reports = []
    for family in ["popularity", "repeat_history"]:
        for window in protocol["popularity_windows"]:
            started = time.perf_counter()
            model = train_baseline(
                settings,
                family,
                protocol["validation"]["cutoff"],
                window,
                protocol,
                identity=identity,
                snapshot=snapshot,
            )
            with connect(settings.dsn, autocommit=True) as conn:
                report = evaluate_model(conn, model, protocol)
            report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            reports.append(report)
    selected = min(reports, key=lambda report: selection_key(report, protocol))
    return {
        "status": "baseline_validation_complete",
        "protocol_sha256": hashlib.sha256(canonical_json(protocol).encode()).hexdigest(),
        "code_identity": identity,
        "reports": reports,
        "selected_baseline_model_id": selected["model_id"],
        "selected_baseline_family": selected["family"],
        "selected_baseline_parameters": selected["parameters"],
        "final_test_consumed": False,
    }


def save_private_report(settings, path, report):
    path = Path(path).expanduser().resolve()
    if not path.is_relative_to(settings.work_dir):
        raise PipelineError("report_must_be_inside_private_work_directory")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("x") as stream:
        stream.write(canonical_json(report) + "\n")
    path.chmod(0o600)

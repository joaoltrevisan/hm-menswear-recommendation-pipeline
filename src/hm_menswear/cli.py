"""Reproducible administrative and historical pipeline commands."""

import argparse
import json
from pathlib import Path

import psycopg

from hm_menswear import __version__
from hm_menswear.config import ConfigurationError, Settings
from hm_menswear.db import DatabaseContractError, connect, migrate, provision
from hm_menswear.evaluation.evaluate import evaluate_model
from hm_menswear.evaluation.holdout import frozen_final_test
from hm_menswear.evaluation.protocol import load_protocol
from hm_menswear.extraction.source import canonical_json, capture_sources
from hm_menswear.jobs import load_next
from hm_menswear.loading.lifecycle import recover_run
from hm_menswear.loading.preparation import prepare_dataset
from hm_menswear.loading.publish import load_all, load_window
from hm_menswear.recommendation.artifacts import load_registered_model, recommend
from hm_menswear.recommendation.comparison import compare_models
from hm_menswear.recommendation.selected import export_test, retrain_selected
from hm_menswear.recommendation.workflow import (
    compare_baselines,
    report_path,
    save_private_report,
    train_baseline,
)
from hm_menswear.safety import PipelineError, assert_log_safety


def parser():
    root = argparse.ArgumentParser(prog="hm-menswear")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check-config")
    check.add_argument(
        "--purpose", choices=["loader", "migration", "admin", "model", "reader"], default="loader"
    )
    db = commands.add_parser("db")
    actions = db.add_subparsers(dest="action", required=True)
    setup = actions.add_parser("provision")
    setup.add_argument("--confirm-database", required=True)
    actions.add_parser("migrate")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--output", required=True)
    prepare = commands.add_parser("prepare")
    for entry in (inspect, prepare):
        for name in ("articles", "customers", "transactions"):
            entry.add_argument("--" + name + "-file")
    load = commands.add_parser("load")
    load.add_argument("--preparation", required=True)
    load.add_argument("--start", required=True)
    load.add_argument("--end", required=True)
    all_batches = commands.add_parser("load-all")
    all_batches.add_argument("--preparation", required=True)
    all_batches.add_argument("--batch-days", type=int, default=7)
    step = commands.add_parser("load-next")
    step.add_argument("--preparation", required=True)
    step.add_argument("--batch-days", type=int, default=7)
    step.add_argument("--attempts", type=int, default=3)
    recover = commands.add_parser("recover")
    recover.add_argument("--run", required=True)
    commands.add_parser("status")
    commands.add_parser("verify-log-settings")
    train = commands.add_parser("train")
    train.add_argument("--model", choices=["popularity", "repeat_history"], required=True)
    train.add_argument("--cutoff", required=True)
    train.add_argument("--window-days", type=int, default=14)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--model-id", required=True)
    evaluate.add_argument("--split", choices=["validation", "test"], default="validation")
    evaluate.add_argument("--output", required=True)
    compare = commands.add_parser("compare-baselines")
    compare.add_argument("--output", required=True)
    full = commands.add_parser("compare-models")
    full.add_argument("--output", required=True)
    final = commands.add_parser("final-test")
    final.add_argument("--comparison", required=True)
    final.add_argument("--output", required=True)
    retrain = commands.add_parser("retrain-selected")
    retrain.add_argument("--session", required=True)
    retrain.add_argument("--cutoff", required=True)
    export = commands.add_parser("export-test")
    export.add_argument("--session", required=True)
    export.add_argument("--output", required=True)
    recommendations = commands.add_parser("recommend")
    recommendations.add_argument("--model-id", required=True)
    customer = recommendations.add_mutually_exclusive_group(required=True)
    customer.add_argument("--customer")
    customer.add_argument("--customer-stdin", action="store_true")
    recommendations.add_argument("--k", type=int, default=12)
    return root


def source_names(args):
    return {
        canonical: getattr(args, role + "_file", None) or canonical
        for role, canonical in [
            ("articles", "articles.csv"),
            ("customers", "customers.csv"),
            ("transactions", "transactions_train.csv"),
        ]
    }


def execute(args, settings):
    if args.command == "load-next":
        return load_next(
            settings, args.preparation, batch_days=args.batch_days, attempts=args.attempts
        )
    if args.command == "retrain-selected":
        return retrain_selected(settings, args.session, args.cutoff, load_protocol())
    if args.command == "export-test":
        report_path(settings, args.output)
        report = export_test(settings, args.session)
        save_private_report(settings, args.output, report)
        return {
            "status": report["status"],
            "test_session_id": report["test_session_id"],
            "stored_reports": len(report["reports"]),
        }
    if args.command == "train":
        model = train_baseline(settings, args.model, args.cutoff, args.window_days, load_protocol())
        return {
            "status": "trained",
            "model_id": model["model_id"],
            **{
                key: model["manifest"][key]
                for key in [
                    "cutoff",
                    "family",
                    "candidate_count",
                    "known_customers",
                    "warm_customers",
                ]
            },
        }
    if args.command in ("compare-baselines", "compare-models", "final-test"):
        report_path(settings, args.output)
        if args.command == "final-test":
            path = Path(args.comparison).expanduser().resolve()
            if not path.is_relative_to(settings.work_dir):
                raise PipelineError("comparison_must_be_inside_private_work_directory")
            report = frozen_final_test(settings, json.loads(path.read_text()), load_protocol())
            save_private_report(settings, args.output, report)
            selected = next(r for r in report["reports"] if r["selected"])
            return {
                "status": report["status"],
                "selected_model_id": selected["model_id"],
                "family": selected["family"],
                "parameters": selected["parameters"],
                "test_reselection_permitted": False,
            }
        report = (compare_baselines if args.command == "compare-baselines" else compare_models)(
            settings, load_protocol()
        )
        save_private_report(settings, args.output, report)
        return {
            "status": report["status"],
            "selected_model_id": report.get(
                "selected_model_id", report["selected_baseline_model_id"]
            ),
            "family": report.get("selected_family", report["selected_baseline_family"]),
            "parameters": report.get("selected_parameters", report["selected_baseline_parameters"]),
            "final_test_consumed": False,
        }
    if args.command in ("evaluate", "recommend"):
        with connect(settings.dsn, autocommit=True) as conn:
            model = load_registered_model(conn, settings.work_dir, args.model_id)
            if args.command == "recommend":
                import sys

                customer = sys.stdin.read(67).strip() if args.customer_stdin else args.customer
                return recommend(model, customer, args.k)
            report_path(settings, args.output)
            report = evaluate_model(conn, model, load_protocol(), split=args.split)
        save_private_report(settings, args.output, report)
        return report
    if args.command == "check-config":
        return {"status": "valid", "purpose": settings.purpose, "chunk_size": settings.chunk_size}
    if args.command == "db":
        with connect(settings.dsn) as conn:
            if args.action == "provision":
                provision(conn, args.confirm_database)
                return {"status": "provisioned"}
            return {"status": "migrated", "applied": migrate(conn)}
    if args.command == "inspect":
        output = Path(args.output).expanduser().resolve()
        if not output.is_relative_to(settings.work_dir):
            raise PipelineError("report_must_be_inside_private_work_directory")
        if output.exists():
            raise PipelineError("report_already_exists")
        manifest = capture_sources(
            settings.raw_dir, settings.work_dir, filenames=source_names(args)
        )
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with output.open("x") as stream:
            stream.write(canonical_json(manifest) + "\n")
        output.chmod(0o600)
        return {
            "status": "inspected",
            "manifest_sha256": manifest["manifest_sha256"],
            "files": {
                name: {k: v for k, v in info.items() if k != "path"}
                for name, info in manifest["files"].items()
            },
        }
    if args.command == "prepare":
        return prepare_dataset(settings, filenames=source_names(args))
    if args.command == "load":
        return load_window(settings, args.preparation, args.start, args.end)
    if args.command == "load-all":
        return load_all(settings, args.preparation, batch_days=args.batch_days)
    if args.command == "recover":
        return recover_run(settings, args.run)
    with connect(settings.dsn, autocommit=True) as conn:
        if args.command == "verify-log-settings":
            assert_log_safety(conn)
            return {"status": "safe_server_log_settings"}
        rows = conn.execute("SELECT status,count(*) FROM control.runs GROUP BY status").fetchall()
        counts = conn.execute(
            "SELECT (SELECT count(*) FROM mart.purchase_events),(SELECT count(*) FROM control.batches WHERE status='completed'),(SELECT count(*) FROM control.preparations WHERE status='complete')"
        ).fetchone()
        return {
            "status": "ok",
            "attempts": dict(rows),
            "purchase_rows": counts[0],
            "completed_batches": counts[1],
            "complete_preparations": counts[2],
        }


def main(argv=None):
    args = parser().parse_args(argv)
    purpose = (
        args.purpose
        if args.command == "check-config"
        else (
            "admin"
            if args.command == "db" and args.action == "provision"
            else "migration"
            if args.command == "db"
            else "model"
            if args.command
            in (
                "train",
                "evaluate",
                "compare-baselines",
                "compare-models",
                "final-test",
                "retrain-selected",
                "export-test",
            )
            else "reader"
            if args.command == "recommend"
            else "loader"
        )
    )
    try:
        settings = Settings.from_env(purpose)
        result = execute(args, settings)
    except (ConfigurationError, DatabaseContractError, PipelineError) as exc:
        print(json.dumps({"status": "error", "code": str(exc)}))
        return 2
    except psycopg.Error:
        print(json.dumps({"status": "error", "code": "database_operation_failed"}))
        return 3
    except (OSError, ValueError, KeyError):
        print(json.dumps({"status": "error", "code": "invalid_input_or_io_failure"}))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "code": "operation_interrupted"}))
        return 130
    except Exception:
        # Unexpected bugs still fail, without a traceback containing restricted values.
        print(json.dumps({"status": "error", "code": "unexpected_operation_failure"}))
        return 4
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

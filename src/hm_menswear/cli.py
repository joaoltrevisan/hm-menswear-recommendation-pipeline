"""Reproducible administrative and historical pipeline commands."""

import argparse
import json
from pathlib import Path

import psycopg

from hm_menswear import __version__
from hm_menswear.config import ConfigurationError, Settings
from hm_menswear.db import DatabaseContractError, connect, migrate, provision
from hm_menswear.extraction.source import canonical_json, capture_sources
from hm_menswear.loading.lifecycle import recover_run
from hm_menswear.loading.preparation import prepare_dataset
from hm_menswear.loading.publish import load_all, load_window
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
    recover = commands.add_parser("recover")
    recover.add_argument("--run", required=True)
    commands.add_parser("status")
    commands.add_parser("verify-log-settings")
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

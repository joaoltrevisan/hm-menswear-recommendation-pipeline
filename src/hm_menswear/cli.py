"""Stage 2 configuration and database commands only."""

import argparse
import json

import psycopg

from hm_menswear import __version__
from hm_menswear.config import ConfigurationError, Settings
from hm_menswear.db import DatabaseContractError, connect, migrate, provision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hm-menswear")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check-config", help="Validate configuration without echoing secrets"
    )
    check.add_argument(
        "--purpose", choices=["loader", "migration", "admin", "model", "reader"], default="loader"
    )
    db = commands.add_parser("db", help="Provision permissions or apply schema migrations")
    actions = db.add_subparsers(dest="action", required=True)
    setup = actions.add_parser("provision")
    setup.add_argument("--confirm-database", required=True)
    actions.add_parser("migrate")
    args = parser.parse_args(argv)
    purpose = (
        args.purpose
        if args.command == "check-config"
        else ("admin" if args.action == "provision" else "migration")
    )
    try:
        settings = Settings.from_env(purpose)
        if args.command == "check-config":
            result = {"status": "valid", "purpose": purpose, "chunk_size": settings.chunk_size}
        else:
            with connect(settings.dsn) as conn:
                if args.action == "provision":
                    provision(conn, args.confirm_database)
                    result = {"status": "provisioned"}
                else:
                    result = {"status": "migrated", "applied": migrate(conn)}
    except (ConfigurationError, DatabaseContractError) as exc:
        print(json.dumps({"status": "error", "code": str(exc)}))
        return 2
    except psycopg.Error:
        print(json.dumps({"status": "error", "code": "database_operation_failed"}))
        return 3
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/bin/sh
# Synthetic CLI demonstration: isolated databases and fabricated data only.
set -eu
cd "$(dirname "$0")/.."
set -a
. ./.env
set +a
: "${HM_ADMIN_DSN:?Configure the private local admin service}"
: "${HM_TEST_CONTAINER:?Set the isolated PostgreSQL container name for log verification}"
export HM_TEST_ADMIN_DSN="$HM_ADMIN_DSN"
exec .venv/bin/pytest -q tests/integration/test_cli_workflow.py --require-postgres --require-log-safety

#!/bin/sh
# Opt-in scheduler wrapper; set project and preparation explicitly in the local environment.
set -eu
: "${HM_PROJECT_DIR:?Set the absolute project checkout path}"
: "${HM_PREPARATION_ID:?Set the completed preparation UUID}"
cd "$HM_PROJECT_DIR"
set -a
. ./.env
set +a
exec .venv/bin/hm-menswear load-next --preparation "$HM_PREPARATION_ID" --attempts 3

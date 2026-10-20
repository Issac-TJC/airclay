#!/bin/sh
# Installed into .venv/bin/airclay by bootstrap.sh; run that installed copy.
# Python skips hidden .pth files, so explicitly expose this checkout's sources.
set -eu
AIRCLAY_PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
export PYTHONPATH="$AIRCLAY_PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$AIRCLAY_PROJECT_ROOT/.venv/bin/python" -m airclay.cli "$@"

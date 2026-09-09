#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${AIRCLAY_PYTHON:-/Users/issactjc/dev/tools/miniconda3/bin/python3.12}"
if [ ! -d .venv ]; then "$PYTHON_BIN" -m venv .venv; fi
if [ -f requirements.lock ]; then
  .venv/bin/python -m pip install -r requirements.lock
  .venv/bin/python -m pip install --no-deps -e .
else
  .venv/bin/python -m pip install -e '.[dev]'
fi
.venv/bin/python scripts/download_model.py
.venv/bin/airclay doctor

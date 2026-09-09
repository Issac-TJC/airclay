#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
BLENDER_BIN="${AIRCLAY_BLENDER:-$HOME/Library/Application Support/Steam/steamapps/common/Blender/Blender.app/Contents/MacOS/Blender}"
exec "$BLENDER_BIN" --factory-startup --python "$PWD/scripts/launch_blender.py"

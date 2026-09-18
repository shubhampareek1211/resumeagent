#!/bin/bash
# Usage: ./build.sh --type resume <name> "Company" "Role"
# Default: validate PDF, log application, sync precisely that application to Notion.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Project environment missing. Run ./scripts/setup.sh first." >&2
  exit 2
fi
exec "$PYTHON" "$ROOT/scripts/build_resume.py" "$@"

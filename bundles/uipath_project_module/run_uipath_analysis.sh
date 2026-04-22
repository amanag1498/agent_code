#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: ./run_uipath_analysis.sh /path/to/uipath/project [output.json]"
  exit 2
fi

PROJECT_PATH="$1"
OUTPUT_PATH="${2:-uipath_report.json}"
PYTHON_BIN="${PYTHON_BIN:-}"

if [ -z "$PYTHON_BIN" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "Python is required. Install Python 3 or set PYTHON_BIN=/path/to/python."
    exit 127
  fi
fi

"$PYTHON_BIN" "$(dirname "$0")/uipath_project_module.py" "$PROJECT_PATH" --output "$OUTPUT_PATH"
echo "Wrote $OUTPUT_PATH"

#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
PATCH_FILE="$ROOT_DIR/bundles/auth_prompt_validator/auth_prompt_validator.patch"

if [ ! -f "$PATCH_FILE" ]; then
  echo "Patch file not found: $PATCH_FILE" >&2
  exit 1
fi

cd "$ROOT_DIR"
git apply "$PATCH_FILE"
echo "Bundle applied successfully."
echo "Next step: restart the app and verify /login, /setup, logout, and the Prompt Validator tab."

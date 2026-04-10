#!/bin/sh
set -eu

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <remote-name> <branch-name>" >&2
  exit 1
fi

REMOTE_NAME="$1"
BRANCH_NAME="$2"
ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"

cd "$ROOT_DIR"

git checkout -b "$BRANCH_NAME"
git add \
  ai_repo_agent/db/database.py \
  ai_repo_agent/integration_modules \
  ai_repo_agent/tests/test_portable_modules.py \
  ai_repo_agent/web/server.py \
  ai_repo_agent/web/static/app.css \
  ai_repo_agent/web/static/app.js \
  ai_repo_agent/web/static/auth.css \
  ai_repo_agent/web/templates/index.html \
  ai_repo_agent/web/templates/login.html \
  ai_repo_agent/web/templates/setup.html \
  bundles/auth_prompt_validator \
  docs/auth_prompt_validator_integration.md \
  docs/portable_modules.md

git commit -m "Add SQLite auth and prompt validator bundle"
git push "$REMOTE_NAME" "$BRANCH_NAME"

echo "Pushed branch '$BRANCH_NAME' to remote '$REMOTE_NAME'."
echo "Next step: open a PR in the target repository."

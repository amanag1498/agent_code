# Auth + Prompt Validator Bundle

This bundle groups the authentication and prompt-validator changes added to this project so they can be applied to another laptop that has the same base code.

## What is included

- SQLite-backed username/password authentication
- dedicated `/setup` and `/login` pages
- authenticated workspace access
- visible logout action in the main UI
- dedicated Prompt Validator workspace tab
- LLM-backed prompt validation with stronger local heuristics

## Files in this bundle

- `auth_prompt_validator.patch`
- `manifest.txt`
- `MANUAL_INTEGRATION.md`
- `apply_bundle.sh`
- `push_to_same_code_repo.sh`
- `GITHUB_PUSH.md`

## Fastest way to apply on another laptop

From the root of the same project version:

```bash
./bundles/auth_prompt_validator/apply_bundle.sh
```

Then restart the app.

You can also apply the patch manually:

```bash
git apply bundles/auth_prompt_validator/auth_prompt_validator.patch
```

## If `git apply` fails

Use `manifest.txt` to copy the listed files manually from this laptop to the target laptop.

For full manual step-by-step integration, use:

- `bundles/auth_prompt_validator/MANUAL_INTEGRATION.md`

## Important assumption

This patch is intended for another checkout of the same repository at a matching or very similar revision. If the target laptop has diverged significantly, apply the changes manually using the docs in:

- `docs/auth_prompt_validator_integration.md`

## GitHub transfer

If you want to push the same feature set to another GitHub repo that has the same codebase:

1. Add the other repository as a remote.
2. Create a feature branch.
3. Commit the bundle changes.
4. Push the branch.

See:

- `bundles/auth_prompt_validator/GITHUB_PUSH.md`

Or use the helper script:

```bash
./bundles/auth_prompt_validator/push_to_same_code_repo.sh <remote-name> <branch-name>
```

# Push To Another GitHub Repo

Use this when another GitHub repository has the same codebase and you want to move the auth + prompt-validator feature set there directly.

## Option 1: Push with the helper script

From the repo root:

```bash
./bundles/auth_prompt_validator/push_to_same_code_repo.sh <remote-name> <branch-name>
```

Example:

```bash
git remote add other-repo git@github.com:your-org/other-repo.git
./bundles/auth_prompt_validator/push_to_same_code_repo.sh other-repo feature/auth-prompt-validator
```

## Option 2: Push manually

```bash
git remote add other-repo git@github.com:your-org/other-repo.git
git checkout -b feature/auth-prompt-validator
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
git push other-repo feature/auth-prompt-validator
```

## Recommended target verification

After pushing and applying in the target repo:

1. Start the app.
2. Confirm `/setup` appears when no user exists.
3. Create a user and sign in.
4. Confirm logout is visible.
5. Confirm the Prompt Validator tab works.

## Notes

- This assumes the target repo has the same or very similar code.
- If the target repo has drifted, use the bundle patch and manual integration guide instead of pushing blindly.

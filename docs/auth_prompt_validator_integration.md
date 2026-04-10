# Auth + Prompt Validator Integration Guide

This guide explains how to move the authentication and prompt-validator feature set to another laptop that has the same project.

## What this feature set adds

### Authentication

- username/password login
- SQLite-backed user storage in the app database
- first-user setup flow
- dedicated `/setup` and `/login` pages
- logout support from the main workspace
- API protection through session-cookie auth

### Prompt Validator

- a reusable prompt validator module
- local heuristic checks for:
  - prompt injection patterns
  - dangerous instructions
  - suspicious secret/data requests
  - malformed or low-quality prompts
- optional LLM-backed structured validation
- a dedicated Prompt Validator tab in the UI
- chat flow validation before repo-chat LLM requests

## Best migration option

If the target laptop has the same codebase revision or a very similar one, use the bundled patch:

```bash
git apply bundles/auth_prompt_validator/auth_prompt_validator.patch
```

Then restart the app.

## Manual migration option

If patch application is not clean, move the files listed in:

- [/Users/amanagarwal/Desktop/AGENT_AI/bundles/auth_prompt_validator/manifest.txt](/Users/amanagarwal/Desktop/AGENT_AI/bundles/auth_prompt_validator/manifest.txt)

## Files and their purpose

### Database and storage

- [database.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/db/database.py)
  Adds the `auth_users` table to SQLite schema.

- [auth_module.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/integration_modules/auth_module.py)
  Contains portable auth logic plus both `SQLiteUserStore` and `JsonFileUserStore`.

- [__init__.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/integration_modules/__init__.py)
  Re-exports portable module types.

### Validation logic

- [prompt_validator_module.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/integration_modules/prompt_validator_module.py)
  Contains prompt validation request/response models, heuristic checks, and optional LLM validation.

### Server integration

- [server.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/web/server.py)
  Wires:
  - login and setup pages
  - login/logout/setup handlers
  - session cookies
  - API authentication middleware
  - `/api/prompt/validate`
  - repo-chat prompt validation

### Frontend integration

- [index.html](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/web/templates/index.html)
  Adds:
  - visible logout button
  - Prompt Validator nav item
  - Prompt Validator page

- [login.html](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/web/templates/login.html)
  Dedicated sign-in page.

- [setup.html](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/web/templates/setup.html)
  Dedicated first-user setup page.

- [app.js](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/web/static/app.js)
  Adds Prompt Validator tab behavior and API calls.

- [app.css](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/web/static/app.css)
  Styles logout button and Prompt Validator page controls.

- [auth.css](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/web/static/auth.css)
  Styles login and setup pages.

### Tests and docs

- [test_portable_modules.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/tests/test_portable_modules.py)
  Covers auth stores and prompt validator behavior.

- [portable_modules.md](/Users/amanagarwal/Desktop/AGENT_AI/docs/portable_modules.md)
  Documents the portable modules themselves.

## How login works after integration

1. If there are no users, `/` redirects to `/setup`.
2. The first account is created and stored in SQLite.
3. After setup, the user signs in on `/login`.
4. A session cookie is issued.
5. Protected APIs require an authenticated session.

Optional bootstrap environment variables:

```bash
export AI_REPO_ANALYST_ADMIN_USERNAME="admin"
export AI_REPO_ANALYST_ADMIN_PASSWORD="change-me"
```

These can pre-seed a user when the database has no users yet.

## How prompt validation works after integration

### Direct page usage

The new Prompt Validator tab lets you test prompts with:

- prompt text
- use case
- blocked terms
- strict mode

It shows:

- accepted or rejected
- risk level
- recommendation
- categories
- local flags
- issues
- sanitized prompt
- reasoning

### Programmatic usage

You can call:

```text
POST /api/prompt/validate
```

with a payload like:

```json
{
  "prompt": "Summarize the repository architecture.",
  "use_case": "general",
  "blocked_terms": ["rm -rf", "drop database"],
  "strict_mode": true
}
```

## Verification steps on the target laptop

1. Start the app.
2. Open `/setup` if no user exists.
3. Create the first account.
4. Sign in through `/login`.
5. Confirm the workspace loads.
6. Confirm the `Sign Out` button is visible.
7. Open the `Prompt Validator` tab.
8. Validate a normal prompt and a blocked prompt.

## Troubleshooting

### `git apply` fails

The target repo has likely diverged. Use the manifest and copy files manually.

### Login page loops

Check whether:

- the browser is accepting cookies
- the app is using the updated `server.py`
- the `auth_users` table exists in SQLite

### Prompt Validator tab is missing

Check that these files were updated together:

- `web/templates/index.html`
- `web/static/app.js`
- `web/static/app.css`

## Recommendation

For another laptop with the same project, the patch-based approach is the cleanest option. For a repo that has diverged, use the manifest plus this guide and apply the files manually.

# Portable Modules

This project now includes two portable modules under [ai_repo_agent/integration_modules](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/integration_modules):

- `auth_module.py`
- `prompt_validator_module.py`

These are designed to be copied into another deployment and integrated manually with minimal dependencies.

## 1. Username/Password Login Module

File:
- [auth_module.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/integration_modules/auth_module.py)

What it provides:
- `SQLiteUserStore`
- `JsonFileUserStore`
- `LoginService`
- `UserAccount`
- `AuthResult`

Behavior:
- stores users in SQLite for the integrated app flow
- also supports a JSON file store for portable copy/paste usage
- hashes passwords using PBKDF2-HMAC-SHA256 with a random salt
- supports register, authenticate, enable, and disable flows

SQLite example:

```python
import sqlite3

from ai_repo_agent.integration_modules.auth_module import SQLiteUserStore, LoginService

connection = sqlite3.connect("ai_repo_analyst.db")
connection.row_factory = sqlite3.Row
store = SQLiteUserStore(connection)
service = LoginService(store)

service.register_user("admin", "strong-password-123")
result = service.authenticate("admin", "strong-password-123")
print(result.success, result.message)
```

JSON example:

```python
from ai_repo_agent.integration_modules.auth_module import JsonFileUserStore, LoginService

store = JsonFileUserStore("users.json")
service = LoginService(store)

service.register_user("admin", "strong-password-123")
result = service.authenticate("admin", "strong-password-123")
print(result.success, result.message)
```

## 2. Prompt Validator Module

File:
- [prompt_validator_module.py](/Users/amanagarwal/Desktop/AGENT_AI/ai_repo_agent/integration_modules/prompt_validator_module.py)

What it provides:
- `PromptValidatorService`
- `PromptValidationRequest`
- `PromptValidationResponse`
- `PromptValidationDecision`

Behavior:
- runs local validation first
- optionally calls the configured LLM provider through the shared `ProviderBase` interface
- returns accepted/rejected status, risk level, sanitized prompt, issues, and reasoning

Example:

```python
from ai_repo_agent.core.models import AppSettings
from ai_repo_agent.llm.factory import create_provider
from ai_repo_agent.integration_modules.prompt_validator_module import (
    PromptValidationRequest,
    PromptValidatorService,
)

settings = AppSettings(
    llm_provider="gemini",
    llm_api_key="YOUR_KEY",
    llm_model="gemini-2.5-flash",
)
provider = create_provider(settings)
validator = PromptValidatorService(provider)

response = validator.validate(
    PromptValidationRequest(
        prompt="Generate a concise architecture summary for leadership.",
        use_case="presentation",
        blocked_terms=["drop database", "steal credentials"],
    )
)
print(response.accepted, response.sanitized_prompt)
```

## Manual Integration Notes

- These modules are intentionally not wired into the web server.
- You can import them where needed on another device and connect them to your own routes, CLI tools, or services.
- The login module is fully local and portable, with SQLite now used by the integrated app flow.
- The prompt validator reuses the project’s existing LLM provider abstraction, so it plugs into any provider already supported by the project.

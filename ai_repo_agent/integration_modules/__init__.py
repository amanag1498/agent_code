"""Portable integration modules for manual wiring into other deployments."""

from ai_repo_agent.integration_modules.auth_module import (
    AuthResult,
    JsonFileUserStore,
    LoginService,
    SQLiteUserStore,
    UserAccount,
)
from ai_repo_agent.integration_modules.prompt_validator_module import (
    PromptValidationDecision,
    PromptValidationRequest,
    PromptValidationResponse,
    PromptValidatorService,
)
from ai_repo_agent.integration_modules.uipath_project_module import (
    OpenAICompatibleLLMClient,
    UiPathFinding,
    UiPathProjectAnalysis,
    UiPathProjectAnalyzer,
    UiPathWorkflowSummary,
    analyze_uipath_project,
)

__all__ = [
    "AuthResult",
    "JsonFileUserStore",
    "LoginService",
    "SQLiteUserStore",
    "UserAccount",
    "PromptValidationDecision",
    "PromptValidationRequest",
    "PromptValidationResponse",
    "PromptValidatorService",
    "OpenAICompatibleLLMClient",
    "UiPathFinding",
    "UiPathProjectAnalysis",
    "UiPathProjectAnalyzer",
    "UiPathWorkflowSummary",
    "analyze_uipath_project",
]

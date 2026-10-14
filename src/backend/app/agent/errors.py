"""Typed failure codes for the US4 routing graph.

Every code here is produced by exactly one node or dispatch step and is recorded
on ``FailureInfo``, so a reviewer reads a stable code rather than prose. The
codes follow `plans/LANGGRAPH_HARNESS_PLAN.md` §9.1 and the `invalid_model_output`
code named by `plans/us4-four-person-task-split.md` §API.
"""

from __future__ import annotations

from app.agent.contracts import FailureInfo

INVALID_MODEL_OUTPUT = "invalid_model_output"
MODEL_UNAVAILABLE = "model_unavailable"
MODEL_CONFIGURATION_ERROR = "model_configuration_error"
MODEL_REFUSED = "model_refused"
MODEL_CALL_BUDGET_EXHAUSTED = "model_call_budget_exhausted"
TOOL_BUDGET_EXHAUSTED = "tool_budget_exhausted"
EMPTY_INVENTORY = "empty_inventory"
INVALID_STATE_UPDATE = "invalid_state_update"


class AgentFailure(Exception):
    """A node-terminating failure carrying the typed code that gets persisted."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_failure_info(self) -> FailureInfo:
        return FailureInfo(code=self.code, message=self.message, retryable=self.retryable)


class ModelConfigurationError(AgentFailure):
    """`GENLEDGE_MODEL_MODE=live` without usable provider configuration."""

    def __init__(self, message: str) -> None:
        super().__init__(MODEL_CONFIGURATION_ERROR, message, retryable=False)


class ModelUnavailableError(AgentFailure):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(MODEL_UNAVAILABLE, message, retryable=retryable)


class InvalidModelOutputError(AgentFailure):
    def __init__(self, message: str) -> None:
        super().__init__(INVALID_MODEL_OUTPUT, message, retryable=False)

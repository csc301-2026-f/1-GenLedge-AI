"""Framework-neutral API error envelope."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.agent.contracts import StrictModel


class ApiError(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class ApiErrorEnvelope(StrictModel):
    error: ApiError


def make_error(code: str, message: str, details: dict[str, Any] | None = None) -> ApiErrorEnvelope:
    return ApiErrorEnvelope(error=ApiError(code=code, message=message, details=details or {}))

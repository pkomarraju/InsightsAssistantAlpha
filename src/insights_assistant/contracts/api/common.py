"""Base model config and small shared shapes."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from insights_assistant.contracts.api.enums import ErrorCode


class ApiModel(BaseModel):
    """Base for every API contract model: snake_case in Python, camelCase on
    the wire (`model_dump(by_alias=True)`), matching
    frontend/src/api/contracts.ts and docs/api/openapi.yaml exactly.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        use_enum_values=False,
    )


class IdLabel(ApiModel):
    id: str
    label: str


class ErrorDetail(ApiModel):
    code: ErrorCode
    message: str
    details: dict | None = None


class ErrorResponse(ApiModel):
    error: ErrorDetail

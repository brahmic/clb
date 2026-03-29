from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.modules.shared.schemas import DashboardModel

_ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}


class DashboardChatTextPart(DashboardModel):
    type: Literal["text"]
    text: str = Field(min_length=1)


class DashboardChatImagePart(DashboardModel):
    type: Literal["image"]
    data_url: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    filename: str = Field(min_length=1)

    @field_validator("mime_type")
    @classmethod
    def _validate_mime_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_IMAGE_MIME_TYPES:
            raise ValueError("Unsupported image MIME type")
        return normalized

    @field_validator("data_url")
    @classmethod
    def _validate_data_url(cls, value: str) -> str:
        if not value.startswith("data:"):
            raise ValueError("Image data must be provided as a data URL")
        return value


class DashboardChatMessage(DashboardModel):
    role: Literal["system", "user", "assistant"]
    content: list[DashboardChatTextPart | DashboardChatImagePart] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_content(self) -> "DashboardChatMessage":
        if self.role != "user" and any(isinstance(part, DashboardChatImagePart) for part in self.content):
            raise ValueError("Image parts are only supported for user messages")
        return self


class DashboardChatResponsesRequest(DashboardModel):
    account_id: str | None = None
    model: str = Field(min_length=1)
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    messages: list[DashboardChatMessage] = Field(min_length=1)

    @field_validator("account_id")
    @classmethod
    def _normalize_account_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("model")
    @classmethod
    def _normalize_model(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Model is required")
        return stripped

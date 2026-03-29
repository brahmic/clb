from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from app.core.types import JsonObject
from app.modules.shared.schemas import DashboardModel

_ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}


class DashboardImageAttachment(DashboardModel):
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


class DashboardImageEditTarget(DashboardModel):
    file_id: str = Field(min_length=1)
    original_gen_id: str | None = None

    @field_validator("file_id")
    @classmethod
    def _normalize_file_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("fileId is required")
        return stripped

    @field_validator("original_gen_id")
    @classmethod
    def _normalize_original_gen_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class DashboardImagesConversationRequest(DashboardModel):
    account_id: str | None = None
    model: str = Field(min_length=1)
    conversation_id: str | None = None
    parent_message_id: str | None = None
    timezone_offset_min: int = 0
    timezone: str = Field(default="UTC", min_length=1)
    client_context: JsonObject = Field(default_factory=dict)
    prompt: str = Field(min_length=1)
    attachments: list[DashboardImageAttachment] = Field(default_factory=list, max_length=3)
    edit_target: DashboardImageEditTarget | None = None

    @field_validator("account_id", "conversation_id", "parent_message_id")
    @classmethod
    def _normalize_optional_ids(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("model", "prompt", "timezone")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value is required")
        return stripped


class DashboardImagesStartedEvent(DashboardModel):
    type: Literal["dashboard.images.started"] = "dashboard.images.started"
    mode: Literal["auto", "account"]
    requested_account_id: str | None
    resolved_account_id: str | None


class DashboardImagesProgressEvent(DashboardModel):
    type: Literal["dashboard.images.progress"] = "dashboard.images.progress"
    phase: str = Field(min_length=1)
    message: str | None = None


class DashboardGeneratedImage(DashboardModel):
    data_url: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    file_id: str = Field(min_length=1)
    original_gen_id: str | None = None
    revised_prompt: str | None = None


class DashboardImagesCompletedEvent(DashboardModel):
    type: Literal["dashboard.images.completed"] = "dashboard.images.completed"
    conversation_id: str = Field(min_length=1)
    assistant_message_id: str = Field(min_length=1)
    parent_message_id: str = Field(min_length=1)
    assistant_text: str | None = None
    images: list[DashboardGeneratedImage] = Field(min_length=1)


class DashboardImagesFailedEvent(DashboardModel):
    type: Literal["dashboard.images.failed"] = "dashboard.images.failed"
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)

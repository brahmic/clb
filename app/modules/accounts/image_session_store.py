from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.core.config.settings import get_settings

logger = logging.getLogger(__name__)

ImageSessionStatusValue = Literal["disconnected", "ready", "error"]


@dataclass(frozen=True, slots=True)
class ChatGPTImageSessionStatus:
    status: ImageSessionStatusValue
    last_validated_at: datetime | None
    last_error: str | None


class AccountImageSessionStore:
    def get(self, account_id: str) -> ChatGPTImageSessionStatus:
        path = self._path_for_account(account_id)
        if not path.exists():
            return _default_status()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read ChatGPT image session metadata account_id=%s", account_id, exc_info=True)
            return _default_status()
        return _status_from_payload(payload)

    def statuses(self, account_ids: list[str]) -> dict[str, ChatGPTImageSessionStatus]:
        return {account_id: self.get(account_id) for account_id in account_ids}

    def set_ready(self, account_id: str, *, validated_at: datetime | None = None) -> ChatGPTImageSessionStatus:
        status = ChatGPTImageSessionStatus(
            status="ready",
            last_validated_at=_normalize_datetime(validated_at or datetime.now(UTC)),
            last_error=None,
        )
        self._write(account_id, status)
        return status

    def set_error(self, account_id: str, *, message: str) -> ChatGPTImageSessionStatus:
        status = ChatGPTImageSessionStatus(
            status="error",
            last_validated_at=None,
            last_error=message.strip() or "Unknown error",
        )
        self._write(account_id, status)
        return status

    def clear(self, account_id: str) -> ChatGPTImageSessionStatus:
        path = self._path_for_account(account_id)
        if path.exists():
            path.unlink()
        return _default_status()

    def _write(self, account_id: str, status: ChatGPTImageSessionStatus) -> None:
        path = self._path_for_account(account_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": status.status,
            "last_validated_at": status.last_validated_at.isoformat() if status.last_validated_at else None,
            "last_error": status.last_error,
        }
        path.write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")

    def profile_dir_for(self, account_id: str) -> Path:
        return get_settings().chatgpt_image_sessions_dir / "profiles" / hashlib.sha256(account_id.encode("utf-8")).hexdigest()

    def _path_for_account(self, account_id: str) -> Path:
        digest = hashlib.sha256(account_id.encode("utf-8")).hexdigest()
        return get_settings().chatgpt_image_sessions_dir / "metadata" / f"{digest}.json"


def _default_status() -> ChatGPTImageSessionStatus:
    return ChatGPTImageSessionStatus(
        status="disconnected",
        last_validated_at=None,
        last_error=None,
    )


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _status_from_payload(payload: object) -> ChatGPTImageSessionStatus:
    if not isinstance(payload, dict):
        return _default_status()
    raw_status = payload.get("status")
    status: ImageSessionStatusValue
    if raw_status in {"disconnected", "ready", "error"}:
        status = raw_status
    else:
        status = "disconnected"
    return ChatGPTImageSessionStatus(
        status=status,
        last_validated_at=_parse_datetime(payload.get("last_validated_at")),
        last_error=payload.get("last_error").strip() if isinstance(payload.get("last_error"), str) else None,
    )

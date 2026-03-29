from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config.settings import get_settings
from app.core.crypto import TokenEncryptor

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChatGPTImageCredentials:
    login_email: str
    password: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ChatGPTImageCredentialsStatus:
    configured: bool
    login_email: str | None
    updated_at: datetime | None


class AccountImageCredentialsStore:
    def __init__(self) -> None:
        self._encryptor = TokenEncryptor()

    def get(self, account_id: str) -> ChatGPTImageCredentials | None:
        path = self._path_for_account(account_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(self._encryptor.decrypt(path.read_bytes()))
        except Exception:
            logger.warning("Failed to read ChatGPT image credentials account_id=%s", account_id, exc_info=True)
            return None
        login_email = payload.get("login_email")
        password = payload.get("password")
        updated_at_raw = payload.get("updated_at")
        if not isinstance(login_email, str) or not login_email.strip():
            return None
        if not isinstance(password, str) or not password.strip():
            return None
        if not isinstance(updated_at_raw, str):
            return None
        try:
            updated_at = datetime.fromisoformat(updated_at_raw)
        except ValueError:
            return None
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        return ChatGPTImageCredentials(
            login_email=login_email.strip(),
            password=password,
            updated_at=updated_at.astimezone(UTC),
        )

    def status(self, account_id: str) -> ChatGPTImageCredentialsStatus:
        credentials = self.get(account_id)
        if credentials is None:
            return ChatGPTImageCredentialsStatus(configured=False, login_email=None, updated_at=None)
        return ChatGPTImageCredentialsStatus(
            configured=True,
            login_email=credentials.login_email,
            updated_at=credentials.updated_at,
        )

    def statuses(self, account_ids: list[str]) -> dict[str, ChatGPTImageCredentialsStatus]:
        return {account_id: self.status(account_id) for account_id in account_ids}

    def put(self, account_id: str, *, login_email: str, password: str) -> ChatGPTImageCredentialsStatus:
        normalized_email = login_email.strip()
        normalized_password = password.strip()
        if not normalized_email:
            raise ValueError("login_email must not be empty")
        if not normalized_password:
            raise ValueError("password must not be empty")
        updated_at = datetime.now(UTC)
        payload = {
            "login_email": normalized_email,
            "password": normalized_password,
            "updated_at": updated_at.isoformat(),
        }
        path = self._path_for_account(account_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self._encryptor.encrypt(json.dumps(payload, ensure_ascii=True, separators=(",", ":"))))
        return ChatGPTImageCredentialsStatus(
            configured=True,
            login_email=normalized_email,
            updated_at=updated_at,
        )

    def delete(self, account_id: str) -> ChatGPTImageCredentialsStatus:
        path = self._path_for_account(account_id)
        if path.exists():
            path.unlink()
        return ChatGPTImageCredentialsStatus(configured=False, login_email=None, updated_at=None)

    def _path_for_account(self, account_id: str) -> Path:
        digest = hashlib.sha256(account_id.encode("utf-8")).hexdigest()
        return get_settings().chatgpt_image_credentials_dir / f"{digest}.bin"

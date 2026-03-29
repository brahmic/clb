from __future__ import annotations

from app.core.clients.chatgpt_image_worker import (
    ChatGPTImageWorkerClient,
    ChatGPTImageWorkerError,
)
from app.core.clients.chatgpt_images import (
    ChatGPTImageConversationRequest,
    ChatGPTImageConversationResult,
)
from app.modules.accounts.image_credentials_store import AccountImageCredentialsStore
from app.modules.accounts.image_session_store import (
    AccountImageSessionStore,
    ChatGPTImageSessionStatus,
)


class ImageSessionUnavailableError(Exception):
    def __init__(self, message: str, *, code: str = "image_session_unavailable") -> None:
        super().__init__(message)
        self.code = code


class ChatGPTImageSessionsService:
    def __init__(
        self,
        *,
        worker_client: ChatGPTImageWorkerClient | None = None,
        session_store: AccountImageSessionStore | None = None,
        credentials_store: AccountImageCredentialsStore | None = None,
    ) -> None:
        self._worker_client = worker_client or ChatGPTImageWorkerClient()
        self._session_store = session_store or AccountImageSessionStore()
        self._credentials_store = credentials_store or AccountImageCredentialsStore()

    def status_for_account(self, account_id: str) -> ChatGPTImageSessionStatus:
        return self._session_store.get(account_id)

    def statuses_for_accounts(self, account_ids: list[str]) -> dict[str, ChatGPTImageSessionStatus]:
        return {account_id: self.status_for_account(account_id) for account_id in account_ids}

    def can_auto_bootstrap(self, account_id: str) -> bool:
        return self._credentials_store.status(account_id).configured

    def is_account_routable(self, account_id: str) -> bool:
        status = self.status_for_account(account_id)
        return status.status == "ready" or self.can_auto_bootstrap(account_id)

    async def disconnect_account(self, *, account_id: str) -> ChatGPTImageSessionStatus:
        try:
            await self._worker_client.disconnect_account_session(account_id=account_id)
        except ChatGPTImageWorkerError as exc:
            self._session_store.set_error(account_id, message=exc.message)
            raise ImageSessionUnavailableError(exc.message, code=exc.code) from exc
        return self._session_store.clear(account_id)

    async def execute_image_conversation(
        self,
        *,
        account_id: str,
        proxy_url: str | None,
        request: ChatGPTImageConversationRequest,
    ) -> ChatGPTImageConversationResult:
        status = self._session_store.get(account_id)
        credentials = self._credentials_store.get(account_id)
        if status.status != "ready" and credentials is None:
            raise ImageSessionUnavailableError(
                "Selected account does not have ChatGPT Images automation configured",
            )
        try:
            result = await self._worker_client.execute_conversation(
                account_id=account_id,
                proxy_url=proxy_url,
                request=request,
                login_email=credentials.login_email if credentials is not None else None,
                password=credentials.password if credentials is not None else None,
            )
            self._session_store.set_ready(account_id)
            return result
        except ChatGPTImageWorkerError as exc:
            if exc.code in {
                "session_not_ready",
                "image_login_failed",
            }:
                self._session_store.set_error(account_id, message=exc.message)
                raise ImageSessionUnavailableError(exc.message, code=exc.code) from exc
            raise

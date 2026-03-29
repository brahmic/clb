from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Account, AccountStatus


class DashboardImagesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active_account_ids(self) -> list[str]:
        result = await self._session.execute(
            select(Account.id).where(Account.status == AccountStatus.ACTIVE)
        )
        return [row[0] for row in result.all()]

    async def get_active_account(self, account_id: str) -> Account | None:
        result = await self._session.execute(
            select(Account).where(Account.id == account_id).where(Account.status == AccountStatus.ACTIVE).limit(1)
        )
        return result.scalar_one_or_none()

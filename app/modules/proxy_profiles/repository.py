from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Account, DashboardSettings, ProxyProfile


class ProxyProfilesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_profiles(self) -> list[ProxyProfile]:
        result = await self._session.execute(select(ProxyProfile).order_by(ProxyProfile.name.asc()))
        return list(result.scalars().all())

    async def get_by_id(self, profile_id: str) -> ProxyProfile | None:
        return await self._session.get(ProxyProfile, profile_id)

    async def get_by_name(self, name: str) -> ProxyProfile | None:
        result = await self._session.execute(select(ProxyProfile).where(ProxyProfile.name == name).limit(1))
        return result.scalar_one_or_none()

    async def list_used_ports(self) -> list[int]:
        result = await self._session.execute(select(ProxyProfile.local_proxy_port))
        return [int(value) for value in result.scalars().all()]

    async def create(self, profile: ProxyProfile) -> ProxyProfile:
        self._session.add(profile)
        await self._session.commit()
        await self._session.refresh(profile)
        return profile

    async def save(self, profile: ProxyProfile) -> ProxyProfile:
        await self._session.commit()
        await self._session.refresh(profile)
        return profile

    async def delete(self, profile_id: str) -> bool:
        profile = await self.get_by_id(profile_id)
        if profile is None:
            return False
        await self._session.delete(profile)
        await self._session.commit()
        return True

    async def clear_default_profile(self, profile_id: str) -> None:
        await self._session.execute(
            update(DashboardSettings)
            .where(DashboardSettings.default_proxy_profile_id == profile_id)
            .values(default_proxy_profile_id=None)
        )

    async def reset_account_assignments(self, profile_id: str) -> None:
        await self._session.execute(
            update(Account)
            .where(Account.proxy_assignment_mode == "proxy_profile")
            .where(Account.proxy_profile_id == profile_id)
            .values(proxy_assignment_mode="inherit_default", proxy_profile_id=None)
        )


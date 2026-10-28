from datetime import UTC, datetime

from app.core import site_limits
from app.db import AsyncSession
from app.db.crud.site_limit import get_user_site_limit, get_user_site_limits
from app.db.models import UserSiteLimit
from app.models.admin import AdminDetails
from app.models.site_limit import (
    SITE_LIMIT_PRESETS,
    SiteLimitCreate,
    SiteLimitListResponse,
    SiteLimitModify,
    SiteLimitPreset,
    SiteLimitResponse,
)
from app.operation import BaseOperation
from app.utils.logger import get_logger
from config import site_limit_settings

logger = get_logger("site-limits")


class SiteLimitOperation(BaseOperation):
    @staticmethod
    def get_presets() -> list[SiteLimitPreset]:
        return [SiteLimitPreset(name=name, domains=domains) for name, domains in SITE_LIMIT_PRESETS.items()]

    async def _get_limit(self, db: AsyncSession, user_id: int, limit_id: int) -> UserSiteLimit:
        db_limit = await get_user_site_limit(db, user_id, limit_id)
        if db_limit is None:
            await self.raise_error(message="Site limit not found", code=404)
        return db_limit

    async def get_user_site_limits(self, db: AsyncSession, user_id: int, admin: AdminDetails) -> SiteLimitListResponse:
        db_user = await self.get_validated_user_by_id(db, user_id, admin, scope_action="read")
        limits = await get_user_site_limits(db, db_user.id)
        return SiteLimitListResponse(
            site_limits=[SiteLimitResponse.model_validate(limit) for limit in limits],
            timezone=site_limit_settings.timezone,
            next_reset=site_limits.midnight_after_days(1),
        )

    async def create_site_limit(
        self, db: AsyncSession, user_id: int, new_limit: SiteLimitCreate, admin: AdminDetails
    ) -> SiteLimitResponse:
        db_user = await self.get_validated_user_by_id(db, user_id, admin, scope_action="update")
        db_limit = UserSiteLimit(
            user_id=db_user.id,
            name=new_limit.name,
            domains=new_limit.domains,
            quota=new_limit.quota,
            slow_speed=new_limit.slow_speed,
            throttled=new_limit.quota == 0,
            expire_at=site_limits.midnight_after_days(new_limit.days) if new_limit.days else None,
        )
        db.add(db_limit)
        await db.commit()
        await db.refresh(db_limit)
        logger.info(f'Site limit "{db_limit.name}" added for user "{db_user.username}" by admin "{admin.username}"')
        site_limits.push_to_nodes_soon()
        return SiteLimitResponse.model_validate(db_limit)

    async def modify_site_limit(
        self, db: AsyncSession, user_id: int, limit_id: int, modified: SiteLimitModify, admin: AdminDetails
    ) -> SiteLimitResponse:
        db_user = await self.get_validated_user_by_id(db, user_id, admin, scope_action="update")
        db_limit = await self._get_limit(db, db_user.id, limit_id)

        for field in ("name", "domains", "quota", "slow_speed"):
            value = getattr(modified, field)
            if value is not None:
                setattr(db_limit, field, value)
        if modified.days is not None:
            db_limit.expire_at = site_limits.midnight_after_days(modified.days) if modified.days else None
        db_limit.throttled = db_limit.used_traffic >= db_limit.quota

        await db.commit()
        await db.refresh(db_limit)
        site_limits.push_to_nodes_soon()
        return SiteLimitResponse.model_validate(db_limit)

    async def reset_site_limit(
        self, db: AsyncSession, user_id: int, limit_id: int, admin: AdminDetails
    ) -> SiteLimitResponse:
        db_user = await self.get_validated_user_by_id(db, user_id, admin, scope_action="reset_usage")
        db_limit = await self._get_limit(db, db_user.id, limit_id)
        was_throttled = db_limit.throttled
        db_limit.used_traffic = 0
        db_limit.throttled = db_limit.quota == 0
        db_limit.reset_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(db_limit)
        if was_throttled != db_limit.throttled:
            site_limits.push_to_nodes_soon()
        return SiteLimitResponse.model_validate(db_limit)

    async def remove_site_limit(self, db: AsyncSession, user_id: int, limit_id: int, admin: AdminDetails) -> None:
        db_user = await self.get_validated_user_by_id(db, user_id, admin, scope_action="update")
        db_limit = await self._get_limit(db, db_user.id, limit_id)
        await db.delete(db_limit)
        await db.commit()
        logger.info(f'Site limit "{db_limit.name}" removed from user "{db_user.username}" by admin "{admin.username}"')
        site_limits.push_to_nodes_soon()

from datetime import UTC, datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserSiteLimit


async def get_user_site_limits(db: AsyncSession, user_id: int) -> list[UserSiteLimit]:
    stmt = select(UserSiteLimit).where(UserSiteLimit.user_id == user_id).order_by(UserSiteLimit.id)
    return list((await db.execute(stmt)).scalars().all())


async def get_user_site_limit(db: AsyncSession, user_id: int, limit_id: int) -> UserSiteLimit | None:
    stmt = select(UserSiteLimit).where(UserSiteLimit.user_id == user_id, UserSiteLimit.id == limit_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_active_site_limits(db: AsyncSession) -> list[UserSiteLimit]:
    """Limits that nodes must enforce: everything not yet expired."""
    now = datetime.now(UTC)
    stmt = (
        select(UserSiteLimit)
        .where(or_(UserSiteLimit.expire_at.is_(None), UserSiteLimit.expire_at > now))
        .order_by(UserSiteLimit.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def add_site_limit_usages(db: AsyncSession, usages: dict[int, int]) -> list[int]:
    """Add traffic to limits and mark the ones that crossed their quota.

    Returns the ids that became throttled by this call.
    """
    if not usages:
        return []
    for limit_id, value in usages.items():
        await db.execute(
            update(UserSiteLimit)
            .where(UserSiteLimit.id == limit_id)
            .values(used_traffic=UserSiteLimit.used_traffic + value)
            .execution_options(synchronize_session=False)
        )
    over = select(UserSiteLimit.id).where(
        UserSiteLimit.id.in_(list(usages)),
        UserSiteLimit.throttled.is_(False),
        UserSiteLimit.used_traffic >= UserSiteLimit.quota,
    )
    newly_throttled = list((await db.execute(over)).scalars().all())
    if newly_throttled:
        await db.execute(
            update(UserSiteLimit)
            .where(UserSiteLimit.id.in_(newly_throttled))
            .values(throttled=True)
            .execution_options(synchronize_session=False)
        )
    await db.commit()
    return newly_throttled


async def remove_expired_site_limits(db: AsyncSession, now: datetime) -> int:
    result = await db.execute(
        delete(UserSiteLimit).where(UserSiteLimit.expire_at.is_not(None), UserSiteLimit.expire_at <= now)
    )
    return result.rowcount or 0


async def reset_site_limits_before(db: AsyncSession, boundary: datetime, now: datetime) -> tuple[int, int]:
    """Reset usage of limits last reset before ``boundary``.

    Returns (reset count, how many of them were throttled).
    """
    stale = UserSiteLimit.reset_at < boundary
    throttled = (
        await db.execute(select(UserSiteLimit.id).where(stale, UserSiteLimit.throttled.is_(True)))
    ).scalars().all()
    result = await db.execute(
        update(UserSiteLimit)
        .where(stale)
        .values(used_traffic=0, throttled=False, reset_at=now)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0, len(throttled)

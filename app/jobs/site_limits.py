from datetime import UTC, datetime as dt, timedelta as td

from app import scheduler
from app.core import site_limits
from app.db import GetDB
from app.db.crud.site_limit import remove_expired_site_limits, reset_site_limits_before
from app.utils.logger import get_logger
from config import runtime_settings

logger = get_logger("jobs")


async def review_site_limits():
    """Daily reset at 00:00 (SITE_LIMIT_TIMEZONE) and removal of expired limits.

    Runs every minute and compares against the last midnight, so a reset missed while the
    panel was down still happens on the next run.
    """
    now = dt.now(UTC)
    async with GetDB() as db:
        removed = await remove_expired_site_limits(db, now)
        reset, unthrottled = await reset_site_limits_before(db, site_limits.last_midnight(now), now)
        await db.commit()

    if removed:
        logger.info(f"Removed {removed} expired site limit(s)")
    if reset:
        logger.info(f"Daily reset of {reset} site limit(s), {unthrottled} back to full speed")
    if removed or unthrottled:
        await site_limits.push_to_nodes()


if runtime_settings.role.runs_node:
    scheduler.add_job(
        review_site_limits,
        "interval",
        seconds=60,
        coalesce=True,
        start_date=dt.now(UTC) + td(seconds=30),
        max_instances=1,
        id="review_site_limits",
        replace_existing=True,
    )

from fastapi import APIRouter, Depends, status

from app.db import AsyncSession, get_db
from app.models.admin import AdminDetails
from app.models.site_limit import (
    SiteLimitCreate,
    SiteLimitListResponse,
    SiteLimitModify,
    SiteLimitPreset,
    SiteLimitResponse,
)
from app.operation import OperatorType
from app.operation.site_limit import SiteLimitOperation
from app.utils import responses

from .authentication import require_permission

site_limit_operator = SiteLimitOperation(operator_type=OperatorType.API)
router = APIRouter(tags=["User Site Limits"], prefix="/api", responses={401: responses._401})


@router.get("/site-limits/presets", response_model=list[SiteLimitPreset])
async def get_site_limit_presets(_: AdminDetails = Depends(require_permission("users", "read"))):
    """Ready-made domain lists for common sites"""
    return site_limit_operator.get_presets()


@router.get(
    "/user/{user_id}/site-limits",
    response_model=SiteLimitListResponse,
    responses={403: responses._403, 404: responses._404},
)
async def get_user_site_limits(
    user_id: int, db: AsyncSession = Depends(get_db), admin: AdminDetails = Depends(require_permission("users", "read"))
):
    """List the user's site limits"""
    return await site_limit_operator.get_user_site_limits(db, user_id=user_id, admin=admin)


@router.post(
    "/user/{user_id}/site-limits",
    response_model=SiteLimitResponse,
    status_code=status.HTTP_201_CREATED,
    responses={403: responses._403, 404: responses._404},
)
async def create_user_site_limit(
    user_id: int,
    new_limit: SiteLimitCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminDetails = Depends(require_permission("users", "update")),
):
    """Give the user full speed for some sites up to a daily quota, then a slow speed"""
    return await site_limit_operator.create_site_limit(db, user_id=user_id, new_limit=new_limit, admin=admin)


@router.put(
    "/user/{user_id}/site-limits/{limit_id}",
    response_model=SiteLimitResponse,
    responses={403: responses._403, 404: responses._404},
)
async def modify_user_site_limit(
    user_id: int,
    limit_id: int,
    modified: SiteLimitModify,
    db: AsyncSession = Depends(get_db),
    admin: AdminDetails = Depends(require_permission("users", "update")),
):
    """Change a site limit"""
    return await site_limit_operator.modify_site_limit(
        db, user_id=user_id, limit_id=limit_id, modified=modified, admin=admin
    )


@router.post(
    "/user/{user_id}/site-limits/{limit_id}/reset",
    response_model=SiteLimitResponse,
    responses={403: responses._403, 404: responses._404},
)
async def reset_user_site_limit(
    user_id: int,
    limit_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AdminDetails = Depends(require_permission("users", "reset_usage")),
):
    """Reset today's usage of a site limit (back to full speed)"""
    return await site_limit_operator.reset_site_limit(db, user_id=user_id, limit_id=limit_id, admin=admin)


@router.delete(
    "/user/{user_id}/site-limits/{limit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={403: responses._403, 404: responses._404},
)
async def remove_user_site_limit(
    user_id: int,
    limit_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AdminDetails = Depends(require_permission("users", "update")),
):
    """Remove a site limit"""
    await site_limit_operator.remove_site_limit(db, user_id=user_id, limit_id=limit_id, admin=admin)

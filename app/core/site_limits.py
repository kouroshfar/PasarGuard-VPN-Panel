"""Per-user site limits: full speed for some sites until a daily quota, then a slow speed.

Every active limit adds to the Xray config sent to nodes:

* two SOCKS outbounds to the local throttling proxy (pg-site-limiter), ``sl-<id>-full`` and
  ``sl-<id>-slow``. Both carry the limit id as the proxy's rate-limit key and the speed in bytes
  per second (0 = unlimited) in the SOCKS username, so the proxy shares one token bucket between
  all of the limit's connections and slows the open ones too once a slow connection arrives;
* a routing rule sending the user's traffic for the limit's domains to one of them;
* a rule dropping that traffic over UDP, so QUIC falls back to TCP through the proxy.

Switching between full and slow only changes routing rules, which nodes apply to the running
Xray without a restart. Usage comes from the two outbounds' traffic counters.
"""

import asyncio
import json
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.db import GetDB
from app.db.crud.site_limit import get_active_site_limits
from app.db.models import UserSiteLimit
from app.utils.logger import get_logger
from config import site_limit_settings

logger = get_logger("site-limits")

TAG_PREFIX = "sl-"
BLOCK_TAG = "sl-block"


def full_tag(limit_id: int) -> str:
    return f"{TAG_PREFIX}{limit_id}-full"


def slow_tag(limit_id: int) -> str:
    return f"{TAG_PREFIX}{limit_id}-slow"


def limit_id_from_tag(tag: str) -> int | None:
    """``sl-12-full`` / ``sl-12-slow`` -> 12."""
    if not tag.startswith(TAG_PREFIX):
        return None
    limit_id, _, kind = tag[len(TAG_PREFIX) :].partition("-")
    if kind not in ("full", "slow") or not limit_id.isdigit():
        return None
    return int(limit_id)


def timezone() -> ZoneInfo:
    return ZoneInfo(site_limit_settings.timezone)


def last_midnight(now: datetime | None = None) -> datetime:
    """The most recent 00:00 in SITE_LIMIT_TIMEZONE, in UTC."""
    local = (now or datetime.now(UTC)).astimezone(timezone())
    return datetime.combine(local.date(), time.min, tzinfo=local.tzinfo).astimezone(UTC)


def midnight_after_days(days: int, now: datetime | None = None) -> datetime:
    """00:00 that ends the ``days``-th day, counting today as day 1, in UTC."""
    local = (now or datetime.now(UTC)).astimezone(timezone())
    return datetime.combine(local.date() + timedelta(days=days), time.min, tzinfo=local.tzinfo).astimezone(UTC)


def _limiter_outbound(tag: str, limit_id: int, rate: int) -> dict:
    return {
        "tag": tag,
        "protocol": "socks",
        "settings": {
            "address": site_limit_settings.limiter_address,
            "port": site_limit_settings.limiter_port,
            "user": f"k={limit_id};r={rate}",
            "pass": "pg",
        },
    }


def build_config(config: dict, limits: list[UserSiteLimit]) -> dict:
    """Return ``config`` with the outbounds and routing rules for ``limits``."""
    if not limits:
        return config

    outbounds = [o for o in config.get("outbounds", []) if not str(o.get("tag", "")).startswith(TAG_PREFIX)]
    for limit in limits:
        outbounds.append(_limiter_outbound(full_tag(limit.id), limit.id, 0))
        outbounds.append(_limiter_outbound(slow_tag(limit.id), limit.id, limit.slow_speed))
    outbounds.append({"tag": BLOCK_TAG, "protocol": "blackhole"})

    routing = dict(config.get("routing") or {})
    rules = [r for r in routing.get("rules", []) if not str(r.get("ruleTag", "")).startswith(TAG_PREFIX)]
    limit_rules = []
    for limit in limits:
        match = {"type": "field", "user": [str(limit.user_id)], "domain": list(limit.domains)}
        limit_rules.append({**match, "network": "udp", "outboundTag": BLOCK_TAG, "ruleTag": f"{TAG_PREFIX}{limit.id}-udp"})
        limit_rules.append(
            {
                **match,
                "outboundTag": slow_tag(limit.id) if limit.throttled else full_tag(limit.id),
                "ruleTag": f"{TAG_PREFIX}{limit.id}",
            }
        )
    routing["rules"] = limit_rules + rules

    # Nodes always enable outbound stats, which usage counting relies on. Only outbounds and
    # routing change here, so nodes can apply this without restarting Xray.
    return {**config, "outbounds": outbounds, "routing": routing}


async def apply_to_config(config_str: str) -> str:
    """Add active site limits to an Xray config JSON string bound for nodes."""
    try:
        async with GetDB() as db:
            limits = await get_active_site_limits(db)
    except Exception:
        logger.exception("Failed to load site limits; sending config without them")
        return config_str
    if not limits:
        return config_str
    return json.dumps(build_config(json.loads(config_str), limits))


_push_lock = asyncio.Lock()


async def push_to_nodes() -> None:
    """Send the current site limits to every connected node (applied live when possible)."""
    from app.jobs.dependencies import SYSTEM_ADMIN
    from app.operation import OperatorType
    from app.operation.node import NodeOperation

    async with _push_lock:
        try:
            async with GetDB() as db:
                await NodeOperation(operator_type=OperatorType.SYSTEM).restart_all_node(
                    db, SYSTEM_ADMIN, stop_first=False
                )
        except Exception:
            logger.exception("Failed to push site limits to nodes")


_push_tasks: set[asyncio.Task] = set()


def push_to_nodes_soon() -> None:
    task = asyncio.create_task(push_to_nodes())
    _push_tasks.add(task)
    task.add_done_callback(_push_tasks.discard)


async def record_usages(node_params: dict[int, list[dict]]) -> None:
    """Add per-limit traffic from outbound stats and throttle limits that used their quota."""
    usages: dict[int, int] = {}
    for params in node_params.values():
        for param in params:
            limit_id = limit_id_from_tag(param.get("name") or "")
            if limit_id is not None:
                usages[limit_id] = usages.get(limit_id, 0) + param["up"] + param["down"]
    if not usages:
        return

    from app.db.crud.site_limit import add_site_limit_usages

    try:
        async with GetDB() as db:
            newly_throttled = await add_site_limit_usages(db, usages)
    except Exception:
        logger.exception("Failed to record site limit usages")
        return
    if newly_throttled:
        logger.info(f"Site limits {newly_throttled} used their quota; switching them to slow speed")
        push_to_nodes_soon()

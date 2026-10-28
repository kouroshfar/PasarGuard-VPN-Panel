from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core import site_limits
from app.models.site_limit import normalize_domains


def _limit(**kwargs):
    defaults = dict(id=3, user_id=7, domains=["domain:instagram.com"], slow_speed=65536, throttled=False)
    return SimpleNamespace(**(defaults | kwargs))


def test_normalize_domains():
    assert normalize_domains(["Instagram.com", "https://www.x.com/home", "*.cdninstagram.com", "geosite:tiktok"]) == [
        "domain:instagram.com",
        "domain:www.x.com",
        "domain:cdninstagram.com",
        "geosite:tiktok",
    ]
    with pytest.raises(ValueError):
        normalize_domains(["not a domain"])
    with pytest.raises(ValueError):
        normalize_domains(["regexp:("])


def test_tag_round_trip():
    assert site_limits.limit_id_from_tag(site_limits.full_tag(12)) == 12
    assert site_limits.limit_id_from_tag(site_limits.slow_tag(12)) == 12
    assert site_limits.limit_id_from_tag("sl-block") is None
    assert site_limits.limit_id_from_tag("direct") is None


def test_build_config_routes_and_outbounds():
    config = {
        "outbounds": [{"tag": "DIRECT", "protocol": "freedom"}],
        "routing": {"rules": [{"type": "field", "ip": ["geoip:private"], "outboundTag": "BLOCK"}]},
    }
    built = site_limits.build_config(config, [_limit(), _limit(id=4, user_id=8, throttled=True)])

    tags = [o["tag"] for o in built["outbounds"]]
    assert tags[0] == "DIRECT"  # the default outbound stays first
    assert {"sl-3-full", "sl-3-slow", "sl-4-full", "sl-4-slow", "sl-block"} <= set(tags)
    slow = next(o for o in built["outbounds"] if o["tag"] == "sl-3-slow")
    assert slow["settings"]["user"] == "k=3;r=65536"

    rules = built["routing"]["rules"]
    assert rules[-1]["outboundTag"] == "BLOCK"  # admin rules keep their order after ours
    by_tag = {r.get("ruleTag"): r for r in rules}
    assert by_tag["sl-3"]["outboundTag"] == "sl-3-full" and by_tag["sl-3"]["user"] == ["7"]
    assert by_tag["sl-4"]["outboundTag"] == "sl-4-slow"
    assert by_tag["sl-3-udp"]["network"] == "udp" and by_tag["sl-3-udp"]["outboundTag"] == "sl-block"
    assert config["outbounds"] == [{"tag": "DIRECT", "protocol": "freedom"}]  # input untouched

    # Rebuilding from an already-built config does not duplicate anything.
    again = site_limits.build_config(built, [_limit()])
    assert [o["tag"] for o in again["outbounds"]].count("sl-3-full") == 1
    assert "sl-4" not in {r.get("ruleTag") for r in again["routing"]["rules"]}


def test_day_boundaries(monkeypatch):
    monkeypatch.setattr(site_limits.site_limit_settings, "timezone", "Asia/Tehran")
    now = datetime(2026, 10, 28, 19, 0, tzinfo=UTC)  # 22:30 in Tehran
    assert site_limits.last_midnight(now) == datetime(2026, 10, 27, 20, 30, tzinfo=UTC)
    assert site_limits.midnight_after_days(1, now) == datetime(2026, 10, 28, 20, 30, tzinfo=UTC)
    assert site_limits.midnight_after_days(7, now) == datetime(2026, 11, 3, 20, 30, tzinfo=UTC)

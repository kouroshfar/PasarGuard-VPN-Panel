import re
from datetime import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.helpers import fix_datetime_timezone

# Xray routing domain matchers accepted in a site limit. A bare domain becomes "domain:<value>",
# which matches the domain and all of its subdomains.
_DOMAIN_PREFIXES = ("domain:", "full:", "keyword:", "regexp:", "geosite:")
_BARE_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$")

SITE_LIMIT_PRESETS: dict[str, list[str]] = {
    "Instagram": [
        "domain:instagram.com",
        "domain:cdninstagram.com",
        "domain:ig.me",
        "domain:instagr.am",
        "domain:igcdn.com",
        "domain:igsonar.com",
        r"regexp:^instagram\..*\.fbcdn\.net$",
    ],
    "YouTube": [
        "domain:youtube.com",
        "domain:youtu.be",
        "domain:googlevideo.com",
        "domain:ytimg.com",
        "domain:ggpht.com",
        "domain:youtube-nocookie.com",
        "domain:youtubei.googleapis.com",
    ],
    "TikTok": [
        "domain:tiktok.com",
        "domain:tiktokv.com",
        "domain:tiktokcdn.com",
        "domain:tiktokcdn-us.com",
        "domain:ttwstatic.com",
        "domain:byteoversea.com",
        "domain:ibytedtos.com",
        "domain:ibyteimg.com",
        "domain:muscdn.com",
    ],
    "Facebook": [
        "domain:facebook.com",
        "domain:fb.com",
        "domain:fbcdn.net",
        "domain:messenger.com",
    ],
    "WhatsApp": ["domain:whatsapp.com", "domain:whatsapp.net"],
    "X (Twitter)": ["domain:twitter.com", "domain:x.com", "domain:twimg.com", "domain:t.co"],
    "Telegram (web/CDN)": ["domain:telegram.org", "domain:t.me", "domain:telegram.me", "domain:telesco.pe"],
    "Netflix": ["domain:netflix.com", "domain:nflxvideo.net", "domain:nflximg.net", "domain:nflxso.net"],
    "Twitch": ["domain:twitch.tv", "domain:ttvnw.net", "domain:jtvnw.net"],
    "Spotify": ["domain:spotify.com", "domain:scdn.co", "domain:spotifycdn.com"],
    # Test servers are run by ISPs under their own domains; most have "speedtest" in the hostname.
    "Speedtest (Ookla)": [
        "domain:speedtest.net",
        "domain:ookla.com",
        "domain:ooklaserver.net",
        "domain:speedtestcustom.com",
        "keyword:speedtest",
    ],
}


def normalize_domains(domains: list[str]) -> list[str]:
    result: list[str] = []
    for raw in domains:
        value = raw.strip()
        if not value:
            continue
        if value.lower().startswith(_DOMAIN_PREFIXES):
            prefix, _, rest = value.partition(":")
            if not rest.strip():
                raise ValueError(f"empty matcher: {raw!r}")
            if prefix.lower() == "regexp":
                try:
                    re.compile(rest)
                except re.error as exc:
                    raise ValueError(f"invalid regexp {rest!r}: {exc}") from exc
            value = f"{prefix.lower()}:{rest.strip()}"
        else:
            value = value.lower().removeprefix("http://").removeprefix("https://").split("/")[0].removeprefix("*.")
            if not _BARE_DOMAIN.match(value):
                raise ValueError(f"invalid domain: {raw!r}")
            value = f"domain:{value}"
        if value not in result:
            result.append(value)
    if not result:
        raise ValueError("at least one domain is required")
    return result


class SiteLimitBase(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    domains: list[str] = Field(min_length=1, max_length=200)
    quota: int = Field(ge=0, description="Bytes per day at full speed")
    slow_speed: int = Field(ge=1024, description="Bytes per second after the quota is used")

    @field_validator("domains")
    @classmethod
    def validate_domains(cls, value: list[str]) -> list[str]:
        return normalize_domains(value)


class SiteLimitCreate(SiteLimitBase):
    days: int | None = Field(
        default=1,
        ge=1,
        le=3650,
        description="Remove the limit at 00:00 after this many days (1 = today only); null keeps it",
    )


class SiteLimitModify(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    domains: list[str] | None = Field(default=None, min_length=1, max_length=200)
    quota: int | None = Field(default=None, ge=0)
    slow_speed: int | None = Field(default=None, ge=1024)
    days: int | None = Field(default=None, ge=0, le=3650, description="0 keeps the limit forever")

    @field_validator("domains")
    @classmethod
    def validate_domains(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else normalize_domains(value)


class SiteLimitResponse(BaseModel):
    id: int
    user_id: int
    name: str
    domains: list[str]
    quota: int
    slow_speed: int
    used_traffic: int
    throttled: bool
    expire_at: dt | None
    reset_at: dt
    created_at: dt
    model_config = ConfigDict(from_attributes=True)

    @field_validator("expire_at", "reset_at", "created_at", mode="before")
    @classmethod
    def validate_dates(cls, value):
        return None if value is None else fix_datetime_timezone(value)


class SiteLimitListResponse(BaseModel):
    site_limits: list[SiteLimitResponse]
    timezone: str
    next_reset: dt


class SiteLimitPreset(BaseModel):
    name: str
    domains: list[str]

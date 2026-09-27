"""Exchange/session calendars — explicit venue semantics (EU + US + crypto 24/7).

Never treat all of Europe as one exchange. Missing calendar → fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .universe import SessionCalendarDay


# Canonical venue registry — timezone + session hours (local). Half-days/holidays
# must be supplied via calendar days; absence is not "open".
EXCHANGE_VENUES: dict[str, dict[str, Any]] = {
    "XNYS": {
        "name": "New York Stock Exchange",
        "mic": "XNYS",
        "timezone": "America/New_York",
        "asset_family": "equity",
        "open_local": "09:30",
        "close_local": "16:00",
        "weekend": ("Saturday", "Sunday"),
        "currency": "USD",
        "region": "US",
    },
    "XNAS": {
        "name": "NASDAQ",
        "mic": "XNAS",
        "timezone": "America/New_York",
        "asset_family": "equity",
        "open_local": "09:30",
        "close_local": "16:00",
        "weekend": ("Saturday", "Sunday"),
        "currency": "USD",
        "region": "US",
    },
    "XAMS": {
        "name": "Euronext Amsterdam",
        "mic": "XAMS",
        "timezone": "Europe/Amsterdam",
        "asset_family": "equity",
        "open_local": "09:00",
        "close_local": "17:30",
        "weekend": ("Saturday", "Sunday"),
        "currency": "EUR",
        "region": "EU",
    },
    "XETR": {
        "name": "Xetra",
        "mic": "XETR",
        "timezone": "Europe/Berlin",
        "asset_family": "equity",
        "open_local": "09:00",
        "close_local": "17:30",
        "weekend": ("Saturday", "Sunday"),
        "currency": "EUR",
        "region": "EU",
    },
    "XLON": {
        "name": "London Stock Exchange",
        "mic": "XLON",
        "timezone": "Europe/London",
        "asset_family": "equity",
        "open_local": "08:00",
        "close_local": "16:30",
        "weekend": ("Saturday", "Sunday"),
        "currency": "GBP",
        "region": "EU",
    },
    "XPAR": {
        "name": "Euronext Paris",
        "mic": "XPAR",
        "timezone": "Europe/Paris",
        "asset_family": "equity",
        "open_local": "09:00",
        "close_local": "17:30",
        "weekend": ("Saturday", "Sunday"),
        "currency": "EUR",
        "region": "EU",
    },
    "XMIL": {
        "name": "Borsa Italiana",
        "mic": "XMIL",
        "timezone": "Europe/Rome",
        "asset_family": "equity",
        "open_local": "09:00",
        "close_local": "17:30",
        "weekend": ("Saturday", "Sunday"),
        "currency": "EUR",
        "region": "EU",
    },
    "CRYPTO_24_7": {
        "name": "Crypto continuous",
        "mic": "CRYPTO_24_7",
        "timezone": "UTC",
        "asset_family": "crypto_spot",
        "open_local": "00:00",
        "close_local": "23:59",
        "weekend": (),
        "currency": "USDT",
        "region": "GLOBAL",
        "continuous": True,
    },
}


@dataclass(frozen=True)
class ExchangeVenue:
    mic: str
    name: str
    timezone: str
    asset_family: str
    open_local: str
    close_local: str
    currency: str
    region: str
    weekend: tuple[str, ...] = ("Saturday", "Sunday")
    continuous: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "mic": self.mic,
            "name": self.name,
            "timezone": self.timezone,
            "asset_family": self.asset_family,
            "open_local": self.open_local,
            "close_local": self.close_local,
            "currency": self.currency,
            "region": self.region,
            "weekend": list(self.weekend),
            "continuous": self.continuous,
            "metadata": dict(self.metadata),
            "truth": {
                "europe_is_not_one_exchange": self.region == "EU",
                "missing_calendar_fail_closed": True,
            },
        }


def get_venue(mic: str) -> ExchangeVenue:
    key = str(mic or "").strip().upper()
    raw = EXCHANGE_VENUES.get(key)
    if raw is None:
        raise KeyError(f"unknown exchange venue mic={mic!r}")
    return ExchangeVenue(
        mic=str(raw["mic"]),
        name=str(raw["name"]),
        timezone=str(raw["timezone"]),
        asset_family=str(raw["asset_family"]),
        open_local=str(raw["open_local"]),
        close_local=str(raw["close_local"]),
        currency=str(raw["currency"]),
        region=str(raw["region"]),
        weekend=tuple(raw.get("weekend") or ()),
        continuous=bool(raw.get("continuous")),
        metadata=dict(raw.get("metadata") or {}),
    )


def list_venues(*, region: str | None = None, asset_family: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for mic in EXCHANGE_VENUES:
        v = get_venue(mic)
        if region and v.region.upper() != str(region).upper():
            continue
        if asset_family and v.asset_family != str(asset_family).lower():
            continue
        out.append(v.public_dict())
    return out


def session_status_for_day(
    *,
    mic: str,
    date: str,
    calendar: Mapping[str, SessionCalendarDay] | None = None,
) -> dict[str, Any]:
    """Resolve session for a venue/date. Missing calendar entry → UNMEASURED/fail-closed."""
    venue = get_venue(mic)
    if venue.continuous:
        return {
            "mic": venue.mic,
            "date": date,
            "session": "open",
            "timezone": venue.timezone,
            "status": "MEASURED",
            "reason": "continuous_market",
            "currency": venue.currency,
        }
    cal = calendar or {}
    day = cal.get(date)
    if day is None:
        return {
            "mic": venue.mic,
            "date": date,
            "session": None,
            "timezone": venue.timezone,
            "status": "UNMEASURED",
            "reason": "calendar_day_missing_fail_closed",
            "currency": venue.currency,
            "truth": {"missing_calendar_is_not_open": True},
        }
    return {
        "mic": venue.mic,
        "date": date,
        "session": day.session,
        "open_ts": day.open_ts,
        "close_ts": day.close_ts,
        "timezone": day.timezone or venue.timezone,
        "status": "MEASURED",
        "currency": venue.currency,
        "half_day": day.session == "half_day",
        "holiday": day.session == "holiday",
    }


def european_equity_venues() -> list[str]:
    return [m for m, v in EXCHANGE_VENUES.items() if v.get("region") == "EU"]

#!/usr/bin/env python3
"""Non-interactive HADES bridge for HunxByts/GhostTrack OSINT helpers.

Upstream GhostTR.py is an interactive stdin menu. This bridge exposes the same
public-info lookups (ipwho.is, phonenumbers, social URL probes, ipify) as
JSON tools that Plugin Manager can invoke with argv arrays and shell=False.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = "HADES-GhostTrack/0.1 (+local plugin; OSINT)"
DEFAULT_TIMEOUT = 12.0

# Same site list as upstream GhostTR.py TrackLu (kept for behavioral parity).
SOCIAL_MEDIA = [
    {"url": "https://www.facebook.com/{}", "name": "Facebook"},
    {"url": "https://www.twitter.com/{}", "name": "Twitter"},
    {"url": "https://www.instagram.com/{}", "name": "Instagram"},
    {"url": "https://www.linkedin.com/in/{}", "name": "LinkedIn"},
    {"url": "https://www.github.com/{}", "name": "GitHub"},
    {"url": "https://www.pinterest.com/{}", "name": "Pinterest"},
    {"url": "https://www.tumblr.com/{}", "name": "Tumblr"},
    {"url": "https://www.youtube.com/{}", "name": "Youtube"},
    {"url": "https://soundcloud.com/{}", "name": "SoundCloud"},
    {"url": "https://www.snapchat.com/add/{}", "name": "Snapchat"},
    {"url": "https://www.tiktok.com/@{}", "name": "TikTok"},
    {"url": "https://www.behance.net/{}", "name": "Behance"},
    {"url": "https://www.medium.com/@{}", "name": "Medium"},
    {"url": "https://www.quora.com/profile/{}", "name": "Quora"},
    {"url": "https://www.flickr.com/people/{}", "name": "Flickr"},
    {"url": "https://www.periscope.tv/{}", "name": "Periscope"},
    {"url": "https://www.twitch.tv/{}", "name": "Twitch"},
    {"url": "https://www.dribbble.com/{}", "name": "Dribbble"},
    {"url": "https://www.stumbleupon.com/stumbler/{}", "name": "StumbleUpon"},
    {"url": "https://www.ello.co/{}", "name": "Ello"},
    {"url": "https://www.producthunt.com/@{}", "name": "Product Hunt"},
    {"url": "https://www.telegram.me/{}", "name": "Telegram"},
    {"url": "https://www.weheartit.com/{}", "name": "We Heart It"},
]


def emit(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def ghosttr_path() -> Path:
    return Path(__file__).resolve().parent / "GhostTR.py"


def http_get_json(url: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-provided OSINT URL
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def http_get_text(url: str, timeout: float = DEFAULT_TIMEOUT) -> tuple[int, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            status = int(getattr(response, "status", 200) or 200)
            body = response.read(4096).decode("utf-8", errors="replace")
            return status, body
    except HTTPError as exc:
        return int(exc.code), str(exc.reason or "")


def doctor() -> dict[str, Any]:
    import cli_bridge

    payload = cli_bridge.doctor(["requests", "phonenumbers"], ["python", "python3"])
    upstream = ghosttr_path()
    payload["upstream"] = {
        "GhostTR.py": str(upstream) if upstream.is_file() else None,
        "present": upstream.is_file(),
    }
    payload["notes"] = [
        "Public OSINT only: IP geolocation, phone metadata, and username URL probes.",
        "Does not unlock phones, bypass accounts, or reveal private GPS from a number alone.",
        "Network required for IP and username tools; phone lookup is mostly offline via phonenumbers.",
    ]
    return payload


def track_ip(ip: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    ip = (ip or "").strip()
    if not ip:
        raise ValueError("ip is required")
    data = http_get_json(f"http://ipwho.is/{ip}", timeout=timeout)
    if data.get("success") is False:
        return {
            "ok": False,
            "ip": ip,
            "error": data.get("message") or "ipwho.is lookup failed",
            "raw": data,
        }
    lat = data.get("latitude")
    lon = data.get("longitude")
    maps = None
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        maps = f"https://www.google.com/maps/@{lat},{lon},8z"
    connection = data.get("connection") if isinstance(data.get("connection"), dict) else {}
    timezone_info = data.get("timezone") if isinstance(data.get("timezone"), dict) else {}
    flag = data.get("flag") if isinstance(data.get("flag"), dict) else {}
    country = data.get("country")
    org = connection.get("org") or connection.get("isp")
    has_coords = isinstance(lat, (int, float)) and isinstance(lon, (int, float))
    if not (country or has_coords or org):
        return {
            "ok": False,
            "ip": ip,
            "error": "empty_geolocation",
            "raw": data,
            "source": "http://ipwho.is/",
        }
    return {
        "ok": True,
        "ip": ip,
        "type": data.get("type"),
        "country": country,
        "country_code": data.get("country_code"),
        "city": data.get("city"),
        "continent": data.get("continent"),
        "continent_code": data.get("continent_code"),
        "region": data.get("region"),
        "region_code": data.get("region_code"),
        "latitude": lat,
        "longitude": lon,
        "maps": maps,
        "is_eu": data.get("is_eu"),
        "postal": data.get("postal"),
        "calling_code": data.get("calling_code"),
        "capital": data.get("capital"),
        "borders": data.get("borders"),
        "flag_emoji": flag.get("emoji"),
        "asn": connection.get("asn"),
        "org": connection.get("org"),
        "isp": connection.get("isp"),
        "domain": connection.get("domain"),
        "timezone": {
            "id": timezone_info.get("id"),
            "abbr": timezone_info.get("abbr"),
            "is_dst": timezone_info.get("is_dst"),
            "offset": timezone_info.get("offset"),
            "utc": timezone_info.get("utc"),
            "current_time": timezone_info.get("current_time"),
        },
        "source": "http://ipwho.is/",
    }


def show_ip(timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    request = Request("https://api.ipify.org/", headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        value = response.read().decode("utf-8", errors="replace").strip()
    if not value:
        return {
            "ok": False,
            "ip": "",
            "error": "empty_ip_response",
            "source": "https://api.ipify.org/",
        }
    return {"ok": True, "ip": value, "source": "https://api.ipify.org/"}


def track_phone(phone: str, default_region: str = "ID") -> dict[str, Any]:
    phone = (phone or "").strip()
    if not phone:
        raise ValueError("phone is required")

    import phonenumbers
    from phonenumbers import PhoneNumberFormat, PhoneNumberType, carrier, geocoder, timezone

    region = (default_region or "ID").strip().upper() or "ID"
    parsed = phonenumbers.parse(phone, region)
    number_type = phonenumbers.number_type(parsed)
    type_label = {
        PhoneNumberType.MOBILE: "mobile",
        PhoneNumberType.FIXED_LINE: "fixed_line",
        PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_line_or_mobile",
        PhoneNumberType.TOLL_FREE: "toll_free",
        PhoneNumberType.PREMIUM_RATE: "premium_rate",
        PhoneNumberType.SHARED_COST: "shared_cost",
        PhoneNumberType.VOIP: "voip",
        PhoneNumberType.PERSONAL_NUMBER: "personal_number",
        PhoneNumberType.PAGER: "pager",
        PhoneNumberType.UAN: "uan",
        PhoneNumberType.VOICEMAIL: "voicemail",
    }.get(number_type, "other")
    zones = timezone.time_zones_for_number(parsed)
    valid = phonenumbers.is_valid_number(parsed)
    possible = phonenumbers.is_possible_number(parsed)
    payload = {
        "ok": bool(valid),
        "input": phone,
        "default_region": region,
        "location": geocoder.description_for_number(parsed, "en"),
        "region_code": phonenumbers.region_code_for_number(parsed),
        "timezones": list(zones),
        "carrier": carrier.name_for_number(parsed, "en"),
        "valid": valid,
        "possible": possible,
        "international": phonenumbers.format_number(parsed, PhoneNumberFormat.INTERNATIONAL),
        "e164": phonenumbers.format_number(parsed, PhoneNumberFormat.E164),
        "national_number": parsed.national_number,
        "country_code": parsed.country_code,
        "type": type_label,
        "source": "phonenumbers",
        "note": "Carrier/region metadata only — not live device location.",
    }
    if not valid:
        payload["error"] = "invalid phone number"
    return payload


def track_username(username: str, timeout: float = 8.0, max_sites: int = 0) -> dict[str, Any]:
    username = (username or "").strip().lstrip("@")
    if not username:
        raise ValueError("username is required")
    if any(ch.isspace() for ch in username) or "/" in username:
        raise ValueError("username must be a single handle without spaces or slashes")

    sites = SOCIAL_MEDIA
    if max_sites and max_sites > 0:
        sites = SOCIAL_MEDIA[:max_sites]

    found: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for site in sites:
        url = site["url"].format(username)
        try:
            status, _body = http_get_text(url, timeout=timeout)
            row = {"name": site["name"], "url": url, "status": status}
            # Upstream treats HTTP 200 as "present". Preserve that heuristic.
            if status == 200:
                found.append(row)
            else:
                missing.append(row)
        except (URLError, TimeoutError, OSError) as exc:
            errors.append({"name": site["name"], "url": url, "error": str(exc)})

    checked = len(sites)
    # All probes errored (timeouts/network) — not a legitimate empty find.
    # HTTP 404/non-200 responses remain ok=True with found_count=0.
    all_probes_failed = checked > 0 and len(errors) == checked and len(found) == 0
    return {
        "ok": not all_probes_failed,
        "username": username,
        "checked": checked,
        "found_count": len(found),
        "found": found,
        "missing": missing,
        "errors": errors,
        "error": (
            "all username probes failed (network/timeout)"
            if all_probes_failed
            else None
        ),
        "heuristic": "HTTP 200 treated as possible profile (same as upstream GhostTrack; false positives possible).",
        "source": "GhostTrack TrackLu site list",
    }


def launch_terminal() -> dict[str, Any]:
    script = ghosttr_path()
    if not script.is_file():
        raise RuntimeError("GhostTR.py not found in plugin source; repack from upstream.")
    python = sys.executable
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        process = subprocess.Popen([python, str(script)], cwd=str(script.parent), creationflags=flags, close_fds=True)
        return {"launched": True, "pid": process.pid, "terminal": "new-console", "script": str(script)}
    if sys.platform == "darwin":
        temp = Path(tempfile.gettempdir()) / "hades-ghosttrack.command"
        temp.write_text(f'#!/bin/sh\ncd "{script.parent}"\n"{python}" "{script}"\nexec "$SHELL"\n', encoding="utf-8")
        temp.chmod(0o700)
        process = subprocess.Popen(["open", "-a", "Terminal", str(temp)], close_fds=True)
        return {"launched": True, "pid": process.pid, "terminal": "Terminal.app", "script": str(script)}

    candidates = [
        (["x-terminal-emulator", "-e", python, str(script)], "x-terminal-emulator"),
        (["gnome-terminal", "--", python, str(script)], "gnome-terminal"),
        (["konsole", "-e", python, str(script)], "konsole"),
    ]
    for command, name in candidates:
        if shutil.which(command[0]):
            process = subprocess.Popen(command, cwd=str(script.parent), close_fds=True)
            return {"launched": True, "pid": process.pid, "terminal": name, "script": str(script)}
    raise RuntimeError("No supported terminal launcher found. Run: python GhostTR.py")


def main() -> int:
    parser = argparse.ArgumentParser(description="HADES GhostTrack bridge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor")

    p_ip = sub.add_parser("track_ip")
    p_ip.add_argument("--ip", required=True)
    p_ip.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)

    p_show = sub.add_parser("show_ip")
    p_show.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)

    p_phone = sub.add_parser("track_phone")
    p_phone.add_argument("--phone", required=True)
    p_phone.add_argument("--default-region", default="ID")

    p_user = sub.add_parser("track_username")
    p_user.add_argument("--username", required=True)
    p_user.add_argument("--timeout", type=float, default=8.0)
    p_user.add_argument("--max-sites", type=int, default=0)

    sub.add_parser("open_terminal")

    args = parser.parse_args()
    try:
        if args.cmd == "doctor":
            return emit(doctor())
        if args.cmd == "track_ip":
            payload = track_ip(args.ip, timeout=args.timeout)
            return emit(payload, exit_code=0 if payload.get("ok") else 1)
        if args.cmd == "show_ip":
            payload = show_ip(timeout=args.timeout)
            return emit(payload, exit_code=0 if payload.get("ok") else 1)
        if args.cmd == "track_phone":
            payload = track_phone(args.phone, default_region=args.default_region)
            return emit(payload, exit_code=0 if payload.get("ok") else 1)
        if args.cmd == "track_username":
            payload = track_username(args.username, timeout=args.timeout, max_sites=args.max_sites)
            return emit(payload, exit_code=0 if payload.get("ok") else 1)
        if args.cmd == "open_terminal":
            return emit(launch_terminal())
        return emit({"ok": False, "error": f"unknown command: {args.cmd}"}, exit_code=2)
    except Exception as exc:  # noqa: BLE001 - surface operator-visible failure as JSON
        return emit({"ok": False, "error": str(exc), "command": args.cmd}, exit_code=1)


if __name__ == "__main__":
    raise SystemExit(main())

"""robots.txt helpers."""

from __future__ import annotations

import urllib.parse
import urllib.robotparser
from typing import Awaitable, Callable

FetchText = Callable[[str], Awaitable[str | None]]


class RobotsCache:
    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._parsers: dict[str, urllib.robotparser.RobotFileParser] = {}

    async def allowed(self, url: str, fetch_text: FetchText, *, enabled: bool = True) -> bool:
        if not enabled:
            return True
        parsed = urllib.parse.urlsplit(url)
        host_key = f"{parsed.scheme}://{parsed.netloc}".lower()
        if host_key not in self._parsers:
            robots_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            body = await fetch_text(robots_url)
            if body is None:
                # Fail open only for fetch errors (network); empty means allow.
                rp.parse([])
            else:
                rp.parse(body.splitlines())
            self._parsers[host_key] = rp
        return self._parsers[host_key].can_fetch(self.user_agent, url)

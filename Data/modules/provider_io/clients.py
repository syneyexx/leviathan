"""Process-local reusable HTTP clients for provider workers."""

from __future__ import annotations

import threading
from typing import Any

import httpx

from .policy import ProviderIoSettings


class ProviderClientPool:
    """One pool per OS worker process — never share across processes."""

    def __init__(self, settings: ProviderIoSettings | None = None) -> None:
        self.settings = settings or ProviderIoSettings.load()
        self._clients: dict[str, httpx.Client] = {}
        self._lock = threading.Lock()
        self._closed = False

    def client(self, *, name: str = "default", trust_env: bool = True) -> httpx.Client:
        if self._closed:
            raise RuntimeError("ProviderClientPool is closed")
        with self._lock:
            existing = self._clients.get(name)
            if existing is not None:
                return existing
            timeout = httpx.Timeout(
                connect=self.settings.connect_timeout_seconds,
                read=self.settings.read_timeout_seconds,
                write=self.settings.read_timeout_seconds,
                pool=self.settings.connect_timeout_seconds,
            )
            client = httpx.Client(
                timeout=timeout,
                follow_redirects=False,
                trust_env=trust_env,
                limits=httpx.Limits(
                    max_connections=32,
                    max_keepalive_connections=16,
                    keepalive_expiry=30.0,
                ),
            )
            self._clients[name] = client
            return client

    def close(self) -> None:
        with self._lock:
            self._closed = True
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> ProviderClientPool:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

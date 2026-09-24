"""Process-local loopback port allocator for managed model workers."""

from __future__ import annotations

import socket
import threading
from typing import Iterable


class PortAllocator:
    """Allocate loopback ports from a configured range with collision detection."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port_start: int = 29100,
        port_end: int = 29200,
    ) -> None:
        if port_end < port_start:
            raise ValueError("port_end must be >= port_start")
        self.host = host
        self.port_start = int(port_start)
        self.port_end = int(port_end)
        self._lock = threading.Lock()
        self._leased: set[int] = set()

    def allocate(self, *, retries: int = 32) -> int:
        with self._lock:
            candidates = list(range(self.port_start, self.port_end + 1))
            # Prefer ports not currently leased by us.
            free = [p for p in candidates if p not in self._leased]
            if not free:
                raise RuntimeError("PORT_EXHAUSTED: no ports left in configured range")
            attempts = 0
            for port in free:
                attempts += 1
                if attempts > retries:
                    break
                if self._can_bind(port):
                    self._leased.add(port)
                    return port
            raise RuntimeError("PORT_EXHAUSTED: could not bind any free port in range")

    def release(self, port: int) -> None:
        with self._lock:
            self._leased.discard(int(port))

    def leased_ports(self) -> frozenset[int]:
        with self._lock:
            return frozenset(self._leased)

    def _can_bind(self, port: int) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, port))
            return True
        except OSError:
            return False
        finally:
            try:
                sock.close()
            except OSError:
                pass


def allocate_ephemeral_loopback(host: str = "127.0.0.1") -> int:
    """Allocate an ephemeral free loopback port (not range-bounded)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()

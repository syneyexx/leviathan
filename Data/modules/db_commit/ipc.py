"""Windows-compatible local IPC for CommitIntent fast path.

Uses localhost-only TCP loopback (works on Windows + Linux). Correctness never
depends on IPC — durable spool is the recovery source.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
from pathlib import Path
from typing import Any, Callable

from Data.modules.common.atomic import atomic_write_text, ensure_dir

from .types import CommitIntent, WriterAck

_MAX_MESSAGE_BYTES = 256 * 1024  # intents are refs — bounded
_HEADER = struct.Struct("!I")


def ipc_endpoint_path(database_path: Path) -> Path:
    return Path(database_path).resolve().parent / "db_commit_ipc.json"


def write_endpoint(database_path: Path, host: str, port: int, token: str) -> Path:
    path = ipc_endpoint_path(database_path)
    ensure_dir(path.parent)
    atomic_write_text(
        path,
        json.dumps({"host": host, "port": port, "token": token}, separators=(",", ":")),
    )
    return path


def read_endpoint(database_path: Path) -> dict[str, Any] | None:
    path = ipc_endpoint_path(database_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except (OSError, json.JSONDecodeError):
        return None


def clear_endpoint(database_path: Path) -> None:
    path = ipc_endpoint_path(database_path)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("socket closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send_message(sock: socket.socket, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > _MAX_MESSAGE_BYTES:
        raise ValueError("IPC message too large")
    sock.sendall(_HEADER.pack(len(raw)) + raw)


def recv_message(sock: socket.socket) -> dict[str, Any]:
    header = _recv_exact(sock, _HEADER.size)
    (length,) = _HEADER.unpack(header)
    if length <= 0 or length > _MAX_MESSAGE_BYTES:
        raise ValueError("invalid IPC frame length")
    raw = _recv_exact(sock, length)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("IPC payload must be object")
    return data


class CommitIpcServer:
    """Localhost-only accept loop. Authenticated with a per-endpoint token."""

    def __init__(
        self,
        database_path: Path,
        *,
        on_intent: Callable[[CommitIntent], WriterAck],
        token: str,
        host: str = "127.0.0.1",
    ) -> None:
        self.database_path = Path(database_path)
        self.on_intent = on_intent
        self.token = token
        self.host = host
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.port: int | None = None

    def start(self) -> tuple[str, int]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, 0))
        sock.listen(64)
        sock.settimeout(0.5)
        self._sock = sock
        self.port = int(sock.getsockname()[1])
        write_endpoint(self.database_path, self.host, self.port, self.token)
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, name="db-commit-ipc", daemon=True)
        self._thread.start()
        return self.host, self.port

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        clear_endpoint(self.database_path)

    def _serve(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                client, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle_client(client)
            except Exception:  # noqa: BLE001
                try:
                    client.close()
                except OSError:
                    pass

    def _handle_client(self, client: socket.socket) -> None:
        with client:
            client.settimeout(2.0)
            msg = recv_message(client)
            if str(msg.get("token") or "") != self.token:
                send_message(
                    client,
                    WriterAck(
                        status="REJECTED",
                        commit_id=str(msg.get("intent", {}).get("commit_id") or ""),
                        message="IPC_AUTH_FAILED",
                    ).to_dict(),
                )
                return
            intent_data = msg.get("intent")
            if not isinstance(intent_data, dict):
                send_message(
                    client,
                    WriterAck(status="REJECTED", commit_id="", message="INVALID_INTENT").to_dict(),
                )
                return
            intent = CommitIntent.from_dict(intent_data)
            ack = self.on_intent(intent)
            send_message(client, ack.to_dict())


class CommitIpcClient:
    def __init__(
        self,
        database_path: Path,
        *,
        timeout_seconds: float = 1.0,
    ) -> None:
        self.database_path = Path(database_path)
        self.timeout_seconds = float(timeout_seconds)

    def submit(self, intent: CommitIntent) -> WriterAck | None:
        endpoint = read_endpoint(self.database_path)
        if not endpoint:
            return None
        host = str(endpoint.get("host") or "127.0.0.1")
        port = int(endpoint.get("port") or 0)
        token = str(endpoint.get("token") or "")
        if not port:
            return None
        try:
            with socket.create_connection((host, port), timeout=self.timeout_seconds) as sock:
                sock.settimeout(self.timeout_seconds)
                send_message(sock, {"token": token, "intent": intent.to_dict()})
                reply = recv_message(sock)
            return WriterAck(
                status=str(reply.get("status") or "REJECTED"),
                commit_id=str(reply.get("commit_id") or intent.commit_id),
                message=str(reply.get("message") or ""),
                receipt=reply.get("receipt") if isinstance(reply.get("receipt"), dict) else None,
            )
        except (OSError, ValueError, ConnectionError, TimeoutError, json.JSONDecodeError):
            return None

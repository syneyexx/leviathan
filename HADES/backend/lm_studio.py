from __future__ import annotations

import asyncio
import threading
from typing import Any, AsyncIterator

import httpx

from reasoning.tool_protocol import StreamingToolCallAssembler

_REGISTRY_LOCK = threading.RLock()
_CANCELLED_RUNS: dict[str, None] = {}
_RUN_CLIENTS: dict[str, list["LmStudioClient"]] = {}
_CANCELLED_RUN_CAP = 256


class LmStudioError(RuntimeError):
    """Raised when the local LM Studio API cannot fulfil a request."""


def remember_cancelled_run(run_id: str) -> None:
    """Public fence: mark a run cancelled so later attach/chat fail closed."""
    _remember_cancelled_run(run_id)


def _remember_cancelled_run(run_id: str) -> None:
    if not run_id:
        return
    with _REGISTRY_LOCK:
        _CANCELLED_RUNS.pop(run_id, None)
        _CANCELLED_RUNS[run_id] = None
        while len(_CANCELLED_RUNS) > _CANCELLED_RUN_CAP:
            _CANCELLED_RUNS.pop(next(iter(_CANCELLED_RUNS)))


def run_is_cancelled(run_id: str | None) -> bool:
    if not run_id:
        return False
    with _REGISTRY_LOCK:
        return run_id in _CANCELLED_RUNS


def attach_lm_run(client: "LmStudioClient", run_id: str | None) -> "LmStudioClient":
    """Bind a client to a chat/work/coding run so cancel can stop inflight httpx.

    Test doubles may omit ``attach_run``; production ``LmStudioClient`` always has it.
    """
    if not run_id:
        return client
    attach = getattr(client, "attach_run", None)
    if callable(attach):
        attach(run_id)
    return client


def detach_lm_run(client: "LmStudioClient", run_id: str | None = None) -> None:
    """Remove a client from the run registry after the run finishes."""
    rid = run_id or getattr(client, "run_id", None)
    if not rid:
        return
    with _REGISTRY_LOCK:
        bucket = _RUN_CLIENTS.get(rid)
        if not bucket:
            return
        try:
            bucket.remove(client)
        except ValueError:
            pass
        if not bucket:
            _RUN_CLIENTS.pop(rid, None)


def run_client_count(run_id: str | None = None) -> int:
    with _REGISTRY_LOCK:
        if run_id:
            return len(_RUN_CLIENTS.get(run_id) or [])
        return sum(len(v) for v in _RUN_CLIENTS.values())


async def cancel_lm_run(run_id: str) -> dict[str, Any]:
    """Mark a run cancelled and stop inflight work.

    Marks the fence first (thread-safe). Client ``cancel()`` prefers cancelling
    requests via the owner event loop; foreign-loop ``aclose()`` is avoided when
    an owner loop is known — Task cancellation unwinds ``async with AsyncClient``.
    """
    if not run_id:
        return {"ok": False, "cancelled": False, "run_id": run_id, "clients": 0}
    _remember_cancelled_run(run_id)
    with _REGISTRY_LOCK:
        clients = list(_RUN_CLIENTS.get(run_id) or [])
    for item in clients:
        await item.cancel()
    return {"ok": True, "cancelled": True, "run_id": run_id, "clients": len(clients)}


def assert_chat_completion(payload: Any) -> dict[str, Any]:
    """HTTP 200 with empty choices/content is a failed completion, not a reply.

    Null content with native tool_calls is allowed (the tool loop continues).
    finish_reason=length with empty content is passed through for EMPTY_RECOVERABLE.
    """
    if not isinstance(payload, dict):
        raise LmStudioError("LM Studio gaf HTTP 200 zonder JSON-object.")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LmStudioError("LM Studio gaf HTTP 200 zonder choices.")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content = str(message.get("content") or choice.get("text") or "").strip()
    tool_calls = message.get("tool_calls")
    has_tools = isinstance(tool_calls, list) and bool(tool_calls)
    if content or has_tools:
        return payload
    if str(choice.get("finish_reason") or "") == "length":
        return payload
    raise LmStudioError("LM Studio gaf HTTP 200 met lege content.")


class LmStudioClient:
    def __init__(self, base_url: str, api_key: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.timeout = timeout
        self.run_id: str | None = None
        self._cancelled = False
        self._inflight: list[httpx.AsyncClient] = []
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._inflight_lock = threading.Lock()

    def attach_run(self, run_id: str) -> None:
        self.run_id = run_id
        with _REGISTRY_LOCK:
            bucket = _RUN_CLIENTS.setdefault(run_id, [])
            if self not in bucket:
                bucket.append(self)
        if run_is_cancelled(run_id):
            self._cancelled = True

    def detach_run(self) -> None:
        detach_lm_run(self, self.run_id)

    def _raise_if_cancelled(self) -> None:
        if self._cancelled or run_is_cancelled(self.run_id):
            self._cancelled = True
            raise LmStudioError("Aanvraag geannuleerd.")

    def _track_owner_loop(self) -> None:
        try:
            self._owner_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

    async def _aclose_inflight(self) -> None:
        with self._inflight_lock:
            clients = list(self._inflight)
            self._inflight.clear()
        for item in clients:
            try:
                await item.aclose()
            except Exception:
                pass

    async def cancel(self) -> None:
        """Stop inflight httpx; subsequent chat/stream calls fail closed.

        Always sets the sync cancel flag. Closes AsyncClient instances only on
        their owner loop (or the current loop when it *is* the owner). Cross-loop
        aclose is not performed — callers should cancel the owning asyncio Task
        (Coding model runtime / Chat cancel) so ``async with`` unwinds locally.
        """
        self._cancelled = True
        if self.run_id:
            _remember_cancelled_run(self.run_id)
        owner = self._owner_loop
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if owner is not None and current is not None and owner is not current and owner.is_running():
            # Schedule close on the owner loop; do not aclose from a foreign loop.
            try:
                fut = asyncio.run_coroutine_threadsafe(self._aclose_inflight(), owner)
                fut.result(timeout=5.0)
            except Exception:
                pass
            return
        await self._aclose_inflight()

    async def models(self) -> dict[str, Any]:
        return await self._request("GET", "/models")

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._raise_if_cancelled()
        return assert_chat_completion(await self._request("POST", "/chat/completions", json=payload))

    async def chat_stream(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        """Yield content deltas (legacy text-only stream helper)."""
        async for item in self.chat_stream_events(payload):
            if item.get("type") == "content_delta":
                yield str(item.get("delta") or "")

    async def chat_stream_events(self, payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Yield structured stream events including tool_call fragments."""
        self._raise_if_cancelled()
        body = {**payload, "stream": True}
        assembler = StreamingToolCallAssembler()
        saw_done = False
        self._track_owner_loop()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                with self._inflight_lock:
                    self._inflight.append(client)
                try:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        headers=self.headers,
                        json=body,
                    ) as response:
                        self._raise_if_cancelled()
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            self._raise_if_cancelled()
                            if not line:
                                continue
                            if line.startswith("data:"):
                                data = line[5:].strip()
                                if data == "[DONE]":
                                    saw_done = True
                                    break
                                try:
                                    import json

                                    chunk = json.loads(data)
                                except (TypeError, ValueError) as exc:
                                    raise LmStudioError("Ongeldige JSON-chunk in LM Studio streamingrespons.") from exc
                                if not isinstance(chunk, dict):
                                    raise LmStudioError("LM Studio streamingchunk is geen JSON-object.")
                                assembler.ingest_chunk(chunk)
                                delta = (
                                    (chunk.get("choices") or [{}])[0]
                                    .get("delta", {})
                                )
                                if isinstance(delta, dict) and delta.get("content"):
                                    yield {"type": "content_delta", "delta": str(delta["content"])}
                                tool_deltas = delta.get("tool_calls") if isinstance(delta, dict) else None
                                if isinstance(tool_deltas, list) and tool_deltas:
                                    yield {"type": "tool_call_delta", "delta": tool_deltas}
                        self._raise_if_cancelled()
                        if not saw_done and not assembler.finish_reason:
                            raise LmStudioError(
                                "LM Studio streamingrespons eindigde zonder [DONE] of expliciete finish_reason."
                            )
                        assembled = assembler.build_response()
                        assert_chat_completion(assembled)
                        yield {"type": "completed", "response": assembled}
                finally:
                    with self._inflight_lock:
                        if client in self._inflight:
                            self._inflight.remove(client)
        except asyncio.CancelledError:
            raise
        except LmStudioError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            if self._cancelled or run_is_cancelled(self.run_id):
                raise LmStudioError("Aanvraag geannuleerd.") from exc
            raise LmStudioError(str(exc)) from exc

    async def chat_stream_complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Consume a stream and return an assembled OpenAI-compatible response."""
        final: dict[str, Any] | None = None
        async for event in self.chat_stream_events(payload):
            if event.get("type") == "completed":
                final = event.get("response")
        if not isinstance(final, dict):
            raise LmStudioError("Streaming completion leverde geen eindrespons.")
        return assert_chat_completion(final)

    async def embeddings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Call OpenAI-compatible ``POST /embeddings`` (local LM Studio)."""
        return await self._request("POST", "/embeddings", json=payload)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self._raise_if_cancelled()
        self._track_owner_loop()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                with self._inflight_lock:
                    self._inflight.append(client)
                try:
                    self._raise_if_cancelled()
                    response = await client.request(method, f"{self.base_url}{path}", headers=self.headers, **kwargs)
                    self._raise_if_cancelled()
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise LmStudioError("LM Studio gaf HTTP 200 zonder JSON-object.")
                    return payload
                finally:
                    with self._inflight_lock:
                        if client in self._inflight:
                            self._inflight.remove(client)
        except asyncio.CancelledError:
            raise
        except LmStudioError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            if self._cancelled or run_is_cancelled(self.run_id):
                raise LmStudioError("Aanvraag geannuleerd.") from exc
            raise LmStudioError(str(exc)) from exc

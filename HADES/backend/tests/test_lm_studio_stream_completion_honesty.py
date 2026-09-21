from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from lm_studio import LmStudioClient, LmStudioError, assert_chat_completion, cancel_lm_run


class _FakeResponse:
    status_code = 200

    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamContext:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response

    async def __aenter__(self) -> _FakeResponse:
        return self.response

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeClient:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def stream(self, *args, **kwargs) -> _FakeStreamContext:
        return _FakeStreamContext(_FakeResponse(self.lines))


class LmStudioStreamCompletionHonestyTests(unittest.TestCase):
    def _complete(self, lines: list[str]) -> dict:
        client = LmStudioClient("http://127.0.0.1:1234/v1", "local", 5.0)
        with patch("lm_studio.httpx.AsyncClient", return_value=_FakeClient(lines)):
            return asyncio.run(client.chat_stream_complete({"model": "test"}))

    def test_done_marker_allows_completed_stream(self) -> None:
        result = self._complete(
            [
                'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}',
                "data: [DONE]",
            ]
        )
        self.assertEqual(result["choices"][0]["message"]["content"], "hello")

    def test_explicit_finish_reason_allows_compatible_stream_without_done_marker(self) -> None:
        result = self._complete(
            [
                'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            ]
        )
        self.assertEqual(result["choices"][0]["finish_reason"], "stop")
        self.assertEqual(result["choices"][0]["message"]["content"], "hello")

    def test_truncated_stream_without_done_or_finish_reason_fails_closed(self) -> None:
        with self.assertRaises(LmStudioError):
            self._complete(
                ['data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}']
            )

    def test_malformed_data_chunk_is_protocol_error(self) -> None:
        with self.assertRaises(LmStudioError):
            self._complete(["data: {not-json", "data: [DONE]"])

    def test_http_200_empty_choices_is_not_a_completion(self) -> None:
        with self.assertRaises(LmStudioError) as ctx:
            assert_chat_completion({"choices": []})
        self.assertIn("choices", str(ctx.exception).lower())

    def test_http_200_empty_content_is_not_a_completion(self) -> None:
        with self.assertRaises(LmStudioError) as ctx:
            assert_chat_completion({"choices": [{"message": {"role": "assistant", "content": "  "}, "finish_reason": "stop"}]})
        self.assertIn("lege content", str(ctx.exception).lower())

    def test_empty_stream_with_done_marker_fails_closed(self) -> None:
        with self.assertRaises(LmStudioError) as ctx:
            self._complete(
                [
                    'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                    "data: [DONE]",
                ]
            )
        self.assertIn("lege content", str(ctx.exception).lower())

    def test_tool_calls_without_content_remain_valid(self) -> None:
        payload = assert_chat_completion(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "p__t", "arguments": "{}"}}],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        )
        self.assertTrue(payload["choices"][0]["message"]["tool_calls"])

    def test_cancel_before_stream_fails_closed(self) -> None:
        client = LmStudioClient("http://127.0.0.1:1234/v1", "local", 5.0)

        async def _run() -> None:
            await client.cancel()
            await client.chat_stream_complete({"model": "test"})

        with self.assertRaises(LmStudioError) as ctx:
            asyncio.run(_run())
        self.assertIn("geannuleerd", str(ctx.exception).lower())

    def test_cancel_mid_stream_does_not_complete(self) -> None:
        client = LmStudioClient("http://127.0.0.1:1234/v1", "local", 5.0)
        lines = [
            'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{"content":" there"},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ]
        original_aiter = _FakeResponse.aiter_lines

        async def _aiter(self):
            first = True
            async for line in original_aiter(self):
                if first:
                    first = False
                    yield line
                    client._cancelled = True
                    continue
                yield line

        with patch.object(_FakeResponse, "aiter_lines", _aiter):
            with patch("lm_studio.httpx.AsyncClient", return_value=_FakeClient(lines)):
                with self.assertRaises(LmStudioError) as ctx:
                    asyncio.run(client.chat_stream_complete({"model": "test"}))
        self.assertIn("geannuleerd", str(ctx.exception).lower())

    def test_cancel_lm_run_marks_attached_client(self) -> None:
        client = LmStudioClient("http://127.0.0.1:1234/v1", "local", 5.0)
        client.attach_run("chat-run-1")

        async def _run() -> None:
            result = await cancel_lm_run("chat-run-1")
            self.assertTrue(result["cancelled"])
            await client.chat({"model": "test"})

        with self.assertRaises(LmStudioError) as ctx:
            asyncio.run(_run())
        self.assertIn("geannuleerd", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()

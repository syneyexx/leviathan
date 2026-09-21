"""Coding Agent A–Z model runtime: timeout, cancel, registry, OmniRoute, selector.

These tests prove the underlying coroutine stops — not merely that a meta flag
was set. No real LM Studio / network.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
import time
import unittest
import warnings
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coding_model_runtime import (
    active_coding_call_count,
    broker_thread_name,
    cancel_coding_run,
    clear_coding_run_fence,
    coding_broker_worker_count,
    fence_coding_run,
    invoke_coding_chat_fn,
    invoke_coding_model,
    is_coding_run_cancelled,
    new_coding_run_id,
)
from coding_omniroute import OmniRouteCodingChat, OmniRouteCodingProvider, STATUS_COMPLETION_FAILED
from investigate_selector import InvestigateSelectorCancelled, propose_investigate_action
from lm_studio import LmStudioClient, LmStudioError, attach_lm_run, cancel_lm_run, detach_lm_run, run_client_count


class HardTimeoutCancelsCoroutineTests(unittest.TestCase):
    """Test A — hard timeout cancels actual coroutine."""

    def test_timeout_cancels_underlying_coro_and_runs_finally(self) -> None:
        started = threading.Event()
        finally_executed = threading.Event()
        cancelled = threading.Event()
        run_id = new_coding_run_id(prefix="test-a")

        async def forever() -> Any:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            finally:
                finally_executed.set()

        outcome = invoke_coding_model(forever, run_id=run_id, timeout_s=0.05, phase="test_a")
        self.assertEqual(outcome.kind, "timeout")
        self.assertTrue(started.wait(2.0))
        self.assertTrue(cancelled.wait(2.0))
        self.assertTrue(finally_executed.wait(2.0))
        self.assertEqual(active_coding_call_count(run_id), 0)
        self.assertTrue(outcome.meta.get("underlying_cancelled"))


class RepeatedTimeoutNoLeakTests(unittest.TestCase):
    """Test B — repeated timeout does not leak broker workers."""

    def test_repeated_timeout_no_linear_broker_growth(self) -> None:
        before = coding_broker_worker_count()

        async def forever() -> Any:
            await asyncio.Event().wait()

        for i in range(25):
            rid = f"test-b-{i}"
            outcome = invoke_coding_model(forever, run_id=rid, timeout_s=0.02, phase="test_b")
            self.assertEqual(outcome.kind, "timeout")
            self.assertEqual(active_coding_call_count(rid), 0)

        after = coding_broker_worker_count()
        # At most one dedicated broker thread — never 25 residual workers.
        self.assertLessEqual(after, max(1, before + 1))
        self.assertEqual(active_coding_call_count(), 0)


class CancelWhileModelActiveTests(unittest.TestCase):
    """Test C — cancellation while model active."""

    def test_cancel_while_active_unwinds_and_no_retry(self) -> None:
        from coding_jobs import reset_coding_job_store_for_tests
        from coding_job_control import CodingJobCancelled

        started = threading.Event()
        finally_ok = threading.Event()
        cancelled_flag = threading.Event()
        schema_retry = {"n": 0}
        repair_calls = {"n": 0}

        with tempfile.TemporaryDirectory() as tmp:
            store = reset_coding_job_store_for_tests(tmp)

            async def blocked_chat(_payload: dict[str, Any]) -> Any:
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled_flag.set()
                    raise
                finally:
                    finally_ok.set()

            def runner(params: dict[str, Any]) -> dict[str, Any]:
                job_id = str(params.get("job_id") or "")
                outcome = invoke_coding_chat_fn(
                    blocked_chat,
                    {"messages": [{"role": "user", "content": "x"}]},
                    run_id=job_id,
                    timeout_s=30.0,
                    phase="propose_edits",
                )
                if outcome.kind == "cancelled":
                    raise CodingJobCancelled(phase="propose_edits")
                schema_retry["n"] += 1
                repair_calls["n"] += 1
                return {"status": "verified", "id": "should-not"}

            job = store.start(runner=runner, params={"goal": "g", "source_repo": tmp})
            self.assertTrue(started.wait(5.0))
            store.request_cancel(job["id"])
            deadline = time.time() + 10
            final = store.get(job["id"])
            while time.time() < deadline and final.get("status") not in {"cancelled", "failed", "verified"}:
                time.sleep(0.05)
                final = store.get(job["id"])
            self.assertEqual(final["status"], "cancelled")
            self.assertTrue(cancelled_flag.wait(5.0))
            self.assertTrue(finally_ok.wait(5.0))
            self.assertEqual(schema_retry["n"], 0)
            self.assertEqual(repair_calls["n"], 0)
            self.assertEqual(active_coding_call_count(job["id"]), 0)
            kinds = [e.get("kind") for e in store.list_events(job["id"], limit=200)]
            self.assertIn("CANCEL_REQUESTED", kinds)
            self.assertNotIn("JOB_COMPLETED", kinds)
            store._executor.shutdown(wait=False, cancel_futures=True)


class CancelBeforeRegisterTests(unittest.TestCase):
    """Test D — cancel-before-register race fails closed."""

    def test_cancel_before_register_never_enters_model(self) -> None:
        entered = {"n": 0}
        run_id = new_coding_run_id(prefix="test-d")
        fence_coding_run(run_id)

        async def should_not_run() -> Any:
            entered["n"] += 1
            return {"ok": True}

        outcome = invoke_coding_model(should_not_run, run_id=run_id, timeout_s=5.0, phase="test_d")
        self.assertEqual(outcome.kind, "cancelled")
        self.assertEqual(entered["n"], 0)
        clear_coding_run_fence(run_id)


class CancellationIsolationTests(unittest.TestCase):
    """Test E — cancellation of A does not poison B."""

    def test_cancel_isolation_between_runs(self) -> None:
        run_a = new_coding_run_id(prefix="test-e-a")
        run_b = new_coding_run_id(prefix="test-e-b")
        fence_coding_run(run_a)

        async def ok() -> Any:
            return {"choices": [{"message": {"content": "b-ok"}}]}

        outcome_a = invoke_coding_model(ok, run_id=run_a, timeout_s=5.0, phase="a")
        self.assertEqual(outcome_a.kind, "cancelled")

        outcome_b = invoke_coding_model(ok, run_id=run_b, timeout_s=5.0, phase="b")
        self.assertEqual(outcome_b.kind, "ok")
        self.assertEqual(outcome_b.response["choices"][0]["message"]["content"], "b-ok")
        self.assertFalse(is_coding_run_cancelled(run_b))
        clear_coding_run_fence(run_a)


class NaturalCompletionCleanupTests(unittest.TestCase):
    """Test F — natural completion cleans registry."""

    def test_natural_completion_clears_registry(self) -> None:
        run_id = new_coding_run_id(prefix="test-f")

        async def ok() -> Any:
            return {"ok": True}

        outcome = invoke_coding_model(ok, run_id=run_id, timeout_s=5.0, phase="f")
        self.assertEqual(outcome.kind, "ok")
        self.assertEqual(active_coding_call_count(run_id), 0)
        self.assertFalse(is_coding_run_cancelled(run_id))


class AsyncInvestigateSelectorTests(unittest.TestCase):
    """Test G — async investigate selector awaits chat_fn."""

    def test_async_chat_fn_parsed_without_coroutine_warning(self) -> None:
        called = {"n": 0}

        async def async_chat(payload: dict[str, Any]) -> dict[str, Any]:
            called["n"] += 1
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"kind":"search_code","args":{"query":"add"},"rationale":"model"}'
                        }
                    }
                ]
            }

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            choice = propose_investigate_action(
                goal="fix add",
                observations=[],
                open_questions=[{"id": "q1", "question": "where?"}],
                allowed=[{"kind": "search_code", "args": {"query": "", "limit": 8}}],
                chat_fn=async_chat,
                model_id="test-model",
                run_id=new_coding_run_id(prefix="test-g"),
                timeout_s=5.0,
            )
        coro_warns = [w for w in caught if "coroutine" in str(w.message).lower() and "never awaited" in str(w.message).lower()]
        self.assertEqual(coro_warns, [])
        self.assertEqual(called["n"], 1)
        self.assertIsNotNone(choice)
        assert choice is not None
        self.assertEqual(choice["kind"], "search_code")
        self.assertEqual(choice["args"]["query"], "add")


class InvestigateSelectorCancellationTests(unittest.TestCase):
    """Test H — selector cancel does not heuristic-fallback."""

    def test_selector_cancel_raises_not_heuristic(self) -> None:
        started = threading.Event()

        async def blocked(_payload: dict[str, Any]) -> Any:
            started.set()
            await asyncio.Event().wait()

        run_id = new_coding_run_id(prefix="test-h")

        def _worker() -> None:
            time.sleep(0.05)
            self.assertTrue(started.wait(2.0))
            cancel_coding_run(run_id)

        threading.Thread(target=_worker, daemon=True).start()
        with self.assertRaises(InvestigateSelectorCancelled):
            propose_investigate_action(
                goal="fix",
                observations=[{"note": "assertionerror"}],
                open_questions=[],
                allowed=[{"kind": "search_code", "args": {"query": "x"}}],
                chat_fn=blocked,
                run_id=run_id,
                timeout_s=10.0,
            )


def _ready_plugin(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "omniroute",
        "enabled": True,
        "status": "ready",
        "trust": "verified",
        "health": "prepared",
        "failure_state": None,
        "permissions": ["subprocess", "network"],
        "capabilities": {"effects": ["subprocess", "network"]},
        "manifest": {"autonomous": True, "capabilities": {"effects": ["subprocess", "network"]}},
    }
    row.update(overrides)
    return row


def _inventory() -> dict[str, Any]:
    return {
        "ok": True,
        "local": {
            "ok": True,
            "base_url": "http://127.0.0.1:1234/v1",
            "local": True,
            "models": [{"id": "model-0", "context_length": 8000}],
            "count": 1,
        },
        "extra": [],
    }


class _FakeInvoke:
    def __init__(self, inventory: dict[str, Any]) -> None:
        self.inventory = inventory

    def __call__(self, plugin_id: str, tool_name: str, input_data: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        import json as _json

        return {"status": "completed", "stdout": _json.dumps(self.inventory)}


def _omni_provider(complete_fn: Any) -> OmniRouteCodingProvider:
    from coding_omniroute import clear_omniroute_inventory_cache

    clear_omniroute_inventory_cache()
    return OmniRouteCodingProvider(
        plugin_lookup=lambda _pid: _ready_plugin(),
        plugin_tools=lambda _pid: [
            {
                "name": "chat",
                "enabled": True,
                "metadata": {"autonomous": True},
                "capabilities": {"effects": ["network", "subprocess"]},
            }
        ],
        invoke=_FakeInvoke(_inventory()),
        complete_fn=complete_fn,
        settings=lambda: {"allow_cloud_model_fallback": False, "lm_studio_api_key": "lm-studio"},
    )


class OmniRouteActiveCancelTests(unittest.TestCase):
    """Test I — OmniRoute active cancellation unwinds."""

    def test_omniroute_active_cancel_unwinds(self) -> None:
        started = threading.Event()
        finally_ok = threading.Event()
        cancelled = threading.Event()

        async def slow_complete(payload, selection):  # noqa: ANN001
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            finally:
                finally_ok.set()

        provider = _omni_provider(slow_complete)
        chat = OmniRouteCodingChat(lambda _p: {"choices": [{"message": {"content": "fb"}}]}, provider, allow_fallback=True)
        run_id = new_coding_run_id(prefix="test-i")

        def _cancel() -> None:
            self.assertTrue(started.wait(3.0))
            cancel_coding_run(run_id)

        threading.Thread(target=_cancel, daemon=True).start()
        outcome = invoke_coding_model(lambda: chat.chat({"messages": [{"role": "user", "content": "x"}]}), run_id=run_id, timeout_s=10.0)
        self.assertEqual(outcome.kind, "cancelled")
        self.assertTrue(cancelled.wait(3.0))
        self.assertTrue(finally_ok.wait(3.0))


class OmniRouteFallbackCancelTests(unittest.TestCase):
    """Test J — OmniRoute fallback remains cancellable."""

    def test_fallback_cancel_stops_lm(self) -> None:
        started = threading.Event()
        cancelled = threading.Event()
        finally_ok = threading.Event()

        async def fail_complete(payload, selection):  # noqa: ANN001
            return {"ok": False, "error": STATUS_COMPLETION_FAILED}

        async def blocked_fallback(_payload: dict[str, Any]) -> Any:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            finally:
                finally_ok.set()

        provider = _omni_provider(fail_complete)
        chat = OmniRouteCodingChat(blocked_fallback, provider, allow_fallback=True)
        run_id = new_coding_run_id(prefix="test-j")

        def _cancel() -> None:
            self.assertTrue(started.wait(3.0))
            cancel_coding_run(run_id)

        threading.Thread(target=_cancel, daemon=True).start()
        outcome = invoke_coding_model(lambda: chat.chat({"messages": [{"role": "user", "content": "x"}]}), run_id=run_id, timeout_s=10.0)
        self.assertEqual(outcome.kind, "cancelled")
        self.assertTrue(cancelled.wait(3.0))
        self.assertTrue(finally_ok.wait(3.0))


class TimeoutPreventsSideEffectsTests(unittest.TestCase):
    """Test K — timeout prevents late sentinel mutation."""

    def test_no_late_sentinel_mutation_after_timeout(self) -> None:
        sentinel = {"mutated": False}
        gate = asyncio.Event()

        async def slow() -> Any:
            await asyncio.sleep(0.5)
            sentinel["mutated"] = True
            return {"ok": True}

        outcome = invoke_coding_model(slow, run_id=new_coding_run_id(prefix="test-k"), timeout_s=0.05)
        self.assertEqual(outcome.kind, "timeout")
        time.sleep(0.7)
        self.assertFalse(sentinel["mutated"])


class LateResultFenceTests(unittest.TestCase):
    """Test L — late response after fence is not accepted."""

    def test_late_response_fenced(self) -> None:
        run_id = new_coding_run_id(prefix="test-l")
        release = threading.Event()

        async def almost_done() -> Any:
            # Simulate provider finishing while cancel fence races in.
            await asyncio.sleep(0.05)
            fence_coding_run(run_id)
            return {"choices": [{"message": {"content": '{"edits":[]}'}}]}

        outcome = invoke_coding_model(almost_done, run_id=run_id, timeout_s=5.0)
        self.assertEqual(outcome.kind, "cancelled")
        self.assertIn(outcome.error, {"late_response_fenced", "cancelled_at_register", "cancel_before_register", "task_cancelled"})
        clear_coding_run_fence(run_id)


class LmStudioCancelCleanupTests(unittest.TestCase):
    """LM client: cancel clears inflight; detach prevents registry growth."""

    def test_task_cancel_exits_request_and_clears_inflight(self) -> None:
        client = LmStudioClient("http://127.0.0.1:9/v1", "k", 5.0)
        attach_lm_run(client, "lm-test-1")
        started = asyncio.Event()
        cleaned = {"n": 0}

        class _HangClient:
            def __init__(self, *a, **k):  # noqa: ANN001
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                cleaned["n"] += 1
                return False

            async def request(self, *a, **k):  # noqa: ANN001
                started.set()
                await asyncio.Event().wait()

        async def _run() -> None:
            import lm_studio as mod

            orig = mod.httpx.AsyncClient
            mod.httpx.AsyncClient = _HangClient  # type: ignore[misc,assignment]
            try:
                task = asyncio.create_task(client.chat({"model": "t"}))
                await started.wait()
                task.cancel()
                with self.assertRaises((asyncio.CancelledError, LmStudioError)):
                    await task
            finally:
                mod.httpx.AsyncClient = orig  # type: ignore[misc]

        asyncio.run(_run())
        self.assertEqual(len(client._inflight), 0)
        self.assertEqual(cleaned["n"], 1)
        detach_lm_run(client, "lm-test-1")
        self.assertEqual(run_client_count("lm-test-1"), 0)

        # Independent subsequent run still works (fence isolation).
        client2 = LmStudioClient("http://127.0.0.1:9/v1", "k", 5.0)
        attach_lm_run(client2, "lm-test-2")
        self.assertFalse(client2._cancelled)
        detach_lm_run(client2, "lm-test-2")

    def test_registry_does_not_grow_per_successful_attach_detach(self) -> None:
        before = run_client_count()
        for i in range(20):
            c = LmStudioClient("http://127.0.0.1:9/v1", "k", 5.0)
            rid = f"reg-{i}"
            attach_lm_run(c, rid)
            detach_lm_run(c, rid)
        self.assertEqual(run_client_count(), before)


class InvokeChatFnLegacyAdapterTests(unittest.TestCase):
    def test_legacy_invoke_reports_joined_not_stranded(self) -> None:
        from coding_agent import _invoke_chat_fn

        async def ok() -> dict[str, Any]:
            return {"choices": [{"message": {"content": "x"}}]}

        response, meta = _invoke_chat_fn(
            None,
            ok,
            timeout_s=5.0,
            run_id=new_coding_run_id(prefix="legacy"),
            phase="legacy",
        )
        self.assertIsNotNone(response)
        self.assertEqual(meta.get("worker_ownership"), "joined")
        self.assertNotEqual(meta.get("worker_ownership"), "stranded_best_effort_cancel")


class BrokerNameTests(unittest.TestCase):
    def test_broker_name_stable(self) -> None:
        self.assertEqual(broker_thread_name(), "hades-coding-lm-broker")


if __name__ == "__main__":
    unittest.main()

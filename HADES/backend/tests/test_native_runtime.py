"""Tests for the native companion Python bridge and API."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from native_runtime import (
    NativeRuntimeClient,
    NativeRuntimeError,
    locate_native_executable,
    set_native_client,
)


REPO = Path(__file__).resolve().parents[2]
NATIVE_BIN = locate_native_executable(REPO)


class FakeNativeProtocol:
    """Minimal line-JSON protocol process for isolated bridge failure-path tests."""

    def __init__(self, *, protocol_version: int = 1, die_after: int | None = None) -> None:
        self.protocol_version = protocol_version
        self.die_after = die_after
        self.calls = 0
        self._closed = False

    def __call__(self, request: dict) -> dict:
        self.calls += 1
        if self.die_after is not None and self.calls > self.die_after:
            raise BrokenPipeError("simulated crash")
        method = request.get("method")
        rid = request.get("id")
        if method == "runtime.hello":
            return {
                "version": 1,
                "id": rid,
                "ok": True,
                "result": {"version": "fake-0", "protocol_version": self.protocol_version, "runtime": "fake"},
                "meta": {"duration_ms": 0},
            }
        if method == "runtime.capabilities":
            return {
                "version": 1,
                "id": rid,
                "ok": True,
                "result": {"process": True, "filesystem": False},
                "meta": {"duration_ms": 0},
            }
        if method == "runtime.health":
            return {"version": 1, "id": rid, "ok": True, "result": {"healthy": True}, "meta": {"duration_ms": 0}}
        if method == "process.run":
            return {
                "version": 1,
                "id": rid,
                "ok": True,
                "result": {
                    "status": "exited",
                    "pid": 1,
                    "exit_code": 0,
                    "stdout": "ok\n",
                    "stderr": "",
                    "timed_out": False,
                    "cancelled": False,
                    "duration_ms": 1,
                },
                "meta": {"duration_ms": 1},
            }
        return {
            "version": 1,
            "id": rid,
            "ok": False,
            "error": {"code": "UNKNOWN_METHOD", "message": str(method), "details": {}},
        }


def _spawn_fake_server(handler: FakeNativeProtocol):
    """Return a Popen-like fake using threads + pipes via a tiny Python subprocess."""
    script = r"""
import json, sys
handler_version = int(sys.argv[1])
die_after = None if sys.argv[2] == "none" else int(sys.argv[2])
calls = 0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    calls += 1
    if die_after is not None and calls > die_after:
        sys.exit(1)
    req = json.loads(line)
    method = req.get("method")
    rid = req.get("id")
    if method == "runtime.hello":
        out = {"version":1,"id":rid,"ok":True,"result":{"version":"fake-0","protocol_version":handler_version,"runtime":"fake"},"meta":{"duration_ms":0}}
    elif method == "runtime.capabilities":
        out = {"version":1,"id":rid,"ok":True,"result":{"process":True,"filesystem":False},"meta":{"duration_ms":0}}
    elif method == "runtime.health":
        out = {"version":1,"id":rid,"ok":True,"result":{"healthy":True},"meta":{"duration_ms":0}}
    elif method == "process.run":
        out = {"version":1,"id":rid,"ok":True,"result":{"status":"exited","pid":1,"exit_code":0,"stdout":"ok\n","stderr":"","timed_out":False,"cancelled":False,"duration_ms":1},"meta":{"duration_ms":1}}
    elif method == "runtime.shutdown":
        out = {"version":1,"id":rid,"ok":True,"result":{"shutdown":True},"meta":{"duration_ms":0}}
        print(json.dumps(out), flush=True)
        break
    else:
        out = {"version":1,"id":rid,"ok":False,"error":{"code":"UNKNOWN_METHOD","message":str(method),"details":{}}}
    print(json.dumps(out), flush=True)
"""
    import subprocess

    die = "none" if handler.die_after is None else str(handler.die_after)
    return subprocess.Popen(
        [sys.executable, "-c", script, str(handler.protocol_version), die],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )


class _ControlledStdout:
    def __init__(self) -> None:
        self._allow_end = threading.Event()
        self._started = threading.Event()

    def __iter__(self):
        self._started.set()
        self._allow_end.wait(timeout=5)
        return iter(())

    def release(self) -> None:
        self._allow_end.set()

    def wait_started(self) -> None:
        self._started.wait(timeout=5)


class _FixedStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)


class _FakeProc:
    def __init__(self, stdout) -> None:
        self.stdout = stdout
        self.stdin = None
        self.stderr = None

    def poll(self):
        return None


class NativeBridgeUnitTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_native_client(None)

    def test_disabled_mode_uses_fallback(self) -> None:
        client = NativeRuntimeClient(mode="disabled", repo=REPO)
        self.assertFalse(client.ensure_started())
        status = client.status()
        self.assertEqual(status.mode, "disabled")
        self.assertTrue(status.fallback_active)
        self.assertFalse(status.connected)

    def test_missing_binary_auto_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeRuntimeClient(mode="auto", repo=Path(tmp))
            self.assertFalse(client.ensure_started())
            self.assertTrue(client.status().fallback_active)

    def test_missing_binary_enabled_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeRuntimeClient(mode="enabled", repo=Path(tmp))
            with self.assertRaises(NativeRuntimeError) as ctx:
                client.ensure_started()
            self.assertEqual(ctx.exception.code, "EXECUTABLE_NOT_FOUND")

    def test_fake_protocol_handshake_and_process(self) -> None:
        handler = FakeNativeProtocol()
        proc = _spawn_fake_server(handler)
        client = NativeRuntimeClient(mode="enabled", repo=REPO)
        client.attach_external_process(proc)
        hello = client._handshake()
        self.assertEqual(hello.get("protocol_version"), 1)
        client._supervisor._hello = hello  # noqa: SLF001 — test inject after handshake
        result = client.process_run(executable="/bin/echo", argv=["x"], timeout_ms=2000)
        self.assertEqual(result.get("exit_code"), 0)
        client.shutdown()

    def test_protocol_mismatch(self) -> None:
        proc = _spawn_fake_server(FakeNativeProtocol(protocol_version=99))
        client = NativeRuntimeClient(mode="auto", repo=REPO)
        client.attach_external_process(proc)
        with self.assertRaises(NativeRuntimeError) as ctx:
            client._handshake()
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_PROTOCOL")
        client.shutdown()

    def test_stale_reader_close_does_not_fail_new_generation_waiters(self) -> None:
        client = NativeRuntimeClient(mode="auto", repo=REPO)
        supervisor = client._supervisor
        transport = client._transport
        old_stdout = _ControlledStdout()
        old_proc = _FakeProc(old_stdout)
        new_proc = _FakeProc(_FixedStdout([]))
        waiter_new = {"event": threading.Event(), "response": None, "error": None, "generation": 2}
        with supervisor._lock:
            supervisor._proc = old_proc
            supervisor._state.generation = 1
            transport._generation = 1
        reader = threading.Thread(target=supervisor._read_loop, args=(old_proc, 1), daemon=True)
        reader.start()
        old_stdout.wait_started()
        with supervisor._lock:
            supervisor._proc = new_proc
            supervisor._state.generation = 2
            transport._generation = 2
            transport._pending["req-new"] = waiter_new
        old_stdout.release()
        reader.join(timeout=5)
        self.assertFalse(waiter_new["event"].is_set(), "stale generation closed newer waiter")
        with transport._lock:
            self.assertIn("req-new", transport._pending)

    def test_stale_generation_response_is_not_delivered_to_new_waiter(self) -> None:
        client = NativeRuntimeClient(mode="auto", repo=REPO)
        supervisor = client._supervisor
        transport = client._transport
        req_id = "req-shared"
        old_proc = _FakeProc(_FixedStdout([json.dumps({"id": req_id, "ok": True, "result": {"x": 1}}) + "\n"]))
        with supervisor._lock:
            supervisor._proc = _FakeProc(_FixedStdout([]))
            supervisor._state.generation = 2
            transport._generation = 2
            transport._pending[req_id] = {
                "event": threading.Event(),
                "response": None,
                "error": None,
                "generation": 2,
            }
        supervisor._read_loop(old_proc, 1)
        with transport._lock:
            waiter = transport._pending.get(req_id)
        self.assertIsNotNone(waiter)
        self.assertFalse(waiter["event"].is_set())
        self.assertIsNone(waiter["response"])

    def test_call_registers_generation_atomically_under_lock(self) -> None:
        """call() binds generation inside the same lock as pending registration + send."""
        from infrastructure.native.transport import RpcTransport

        transport = RpcTransport()
        observed: dict[str, Any] = {}
        registered = threading.Event()

        def write_fn(line: str) -> None:
            with transport._lock:
                waiter = next(iter(transport._pending.values()))
                observed["waiter_generation"] = waiter.get("generation")
                observed["transport_generation"] = transport._generation
                observed["line"] = line
            registered.set()

        transport.attach(write_fn, generation=5)
        errors: list[BaseException] = []

        def caller() -> None:
            try:
                transport.call("runtime.hello", {}, timeout_s=0.4)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        t = threading.Thread(target=caller)
        t.start()
        self.assertTrue(registered.wait(2))
        self.assertEqual(observed.get("waiter_generation"), 5)
        self.assertEqual(observed.get("transport_generation"), 5)
        t.join(timeout=3)
        self.assertTrue(errors)  # timeout expected — no response delivered

    def test_stale_reader_does_not_note_crash_for_new_generation(self) -> None:
        client = NativeRuntimeClient(mode="auto", repo=REPO)
        supervisor = client._supervisor
        old_stdout = _ControlledStdout()
        old_proc = _FakeProc(old_stdout)
        new_proc = _FakeProc(_FixedStdout([]))
        with supervisor._lock:
            supervisor._proc = old_proc
            supervisor._state.generation = 1
            supervisor._state.crash_count = 0
            supervisor._hello = {"protocol_version": 1}
        reader = threading.Thread(target=supervisor._read_loop, args=(old_proc, 1), daemon=True)
        reader.start()
        old_stdout.wait_started()
        with supervisor._lock:
            supervisor._proc = new_proc
            supervisor._state.generation = 2
            supervisor._hello = {"protocol_version": 1, "fresh": True}
            client._transport.attach(lambda _line: None, generation=2)
        old_stdout.release()
        reader.join(timeout=5)
        state = supervisor.state
        self.assertEqual(state.crash_count, 0)
        self.assertEqual(supervisor.hello.get("fresh"), True)
        self.assertIs(supervisor._proc, new_proc)

    def test_teardown_of_old_generation_does_not_detach_new_transport(self) -> None:
        client = NativeRuntimeClient(mode="auto", repo=REPO)
        supervisor = client._supervisor
        transport = client._transport
        old_proc = _FakeProc(_FixedStdout([]))
        writes: list[str] = []

        def new_write(line: str) -> None:
            writes.append(line)

        with supervisor._lock:
            supervisor._proc = old_proc
            supervisor._state.generation = 1
            transport.attach(lambda _line: None, generation=1)
        # Simulate reconnect: new generation attached, then old teardown runs.
        with supervisor._lock:
            supervisor._proc = _FakeProc(_FixedStdout([]))
            supervisor._state.generation = 2
            transport.attach(new_write, generation=2)
        # Old teardown with stale generation must not clear the new write path.
        detached = transport.detach(generation=1)
        self.assertFalse(detached)
        with transport._lock:
            self.assertTrue(transport._alive)
            self.assertEqual(transport._generation, 2)
            self.assertIsNotNone(transport._write)
            assert transport._write is not None
            transport._write("x\n")
        self.assertEqual(writes, ["x\n"])


@unittest.skipUnless(NATIVE_BIN is not None, "native binary not built under runtime/native/")
class NativeBridgeIntegrationTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_native_client(None)

    def test_real_hello_process_and_metrics(self) -> None:
        client = NativeRuntimeClient(executable=NATIVE_BIN, mode="auto", repo=REPO)
        self.assertTrue(client.ensure_started())
        status = client.status()
        self.assertTrue(status.connected)
        self.assertFalse(status.fallback_active)
        self.assertEqual(status.protocol_version, 1)
        if os.name == "nt":
            result = client.process_run(executable=os.environ.get("COMSPEC", "cmd.exe"), argv=["/c", "echo", "hades"], timeout_ms=5000)
        else:
            result = client.process_run(executable="/bin/echo", argv=["hades-native"], timeout_ms=5000)
        self.assertEqual(result.get("exit_code"), 0)
        stdout = (result.get("stdout") or "").lower()
        self.assertTrue("hades" in stdout)
        metrics = client.system_metrics()
        self.assertIsInstance(metrics, dict)
        digest = client.fs_hash(str(NATIVE_BIN))
        self.assertEqual(len(digest.get("sha256") or ""), 64)
        client.shutdown()

    def test_status_api(self) -> None:
        import main
        from database import Database
        from fastapi.testclient import TestClient

        class _FakeLm:
            async def models(self):
                return {"object": "list", "data": []}

            async def chat(self, payload):
                return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp.cleanup)
        main.database = Database(str(Path(temp.name) / "native-api.db"))
        main.runner = main.TaskRunner()
        with patch.object(main, "lm_client", return_value=_FakeLm()):
            with TestClient(main.app) as client:
                response = client.get("/api/native/status")
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertIn("mode", body)
                self.assertIn("connected", body)
                self.assertIn("fallback_active", body)
                self.assertTrue(body.get("available"))
                self.assertTrue(body.get("connected"))


if __name__ == "__main__":
    unittest.main()

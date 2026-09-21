from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from tools.frontend_runtime import frontend_shell_command
from tools.hades_tray import TrayRuntime, run_win32_tray, tray_supported
from tools.launcher_lifecycle import LauncherLifecycle, transactional_startup_failed
from tools.local_startup_health import FRONTEND_URL, wait_for_local_hades


def application_root(
    *,
    frozen: bool | None = None,
    executable: str | Path | None = None,
    script_file: str | Path | None = None,
) -> Path:
    """Resolve the HADES install root for source and PyInstaller execution.

    PyInstaller one-file bundles execute the entry script from a temporary bundle
    directory, while ``sys.executable`` remains the actual HADES.exe path. HADES
    runtime assets are intentionally external and live next to that executable.
    """

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if is_frozen:
        return Path(executable or sys.executable).resolve().parent
    return Path(script_file or __file__).resolve().parent


ROOT = application_root()
BACKEND = ROOT / "backend"
PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"
VITE = ROOT / "node_modules" / ".bin" / "vite.cmd"


def fail(message: str) -> None:
    import ctypes

    try:
        ctypes.windll.user32.MessageBoxW(0, message, "HADES", 0x10)
    except Exception:
        print(message)
    raise SystemExit(1)


def main() -> None:
    if os.name != "nt":
        fail("Deze launcher is bedoeld voor Windows. Gebruik START_HADES.bat op andere systemen.")
    if not PYTHON.exists() or not VITE.exists():
        prepare = ROOT / "PREPARE_HADES.bat"
        code = subprocess.call(["cmd", "/c", str(prepare)], cwd=ROOT)
        if code != 0:
            fail("HADES voorbereiden/verifieren is mislukt. Bekijk het PREPARE_HADES venster.")

    creation = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    lifecycle = LauncherLifecycle()
    lifecycle.open_job_object_if_available()
    backend = subprocess.Popen(
        [
            str(PYTHON),
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        cwd=BACKEND,
        creationflags=creation,
        env={
            **os.environ,
            "HADES_BIND_HOST": "127.0.0.1",
        },
    )
    lifecycle.track("backend", backend)
    frontend = subprocess.Popen(
        frontend_shell_command(ROOT),
        cwd=ROOT,
        creationflags=creation,
    )
    lifecycle.track("frontend", frontend)

    if not wait_for_local_hades():
        report = transactional_startup_failed(lifecycle, reason="readiness_timeout")
        detail = (
            "HADES backend en/of frontend werd niet binnen de starttimeout bereikbaar. "
            "Controleer de backend- en frontendvensters voor de echte foutmelding."
        )
        if report.get("orphan_alive"):
            detail += " Waarschuwing: niet alle HADES-processen konden worden gestopt."
        else:
            detail += " Gestarte HADES-processen zijn gestopt (geen wezenprocessen)."
        fail(detail)

    runtime = TrayRuntime(root=ROOT, frontend_url=FRONTEND_URL)
    runtime.track("backend", backend)
    runtime.track("frontend", frontend)
    runtime.open_ui()

    if tray_supported():
        # Keep backend/frontend alive without requiring an open browser tab.
        # Tray menu: Open UI / Quit HADES (explicit quit stops managed processes).
        try:
            raise SystemExit(run_win32_tray(runtime))
        except Exception as exc:
            print(f"HADES tray unavailable ({exc}); backend blijft draaien tot vensters worden gesloten.")
            try:
                backend.wait()
            except KeyboardInterrupt:
                runtime.quit_hades()
            return

    webbrowser.open(FRONTEND_URL)


if __name__ == "__main__":
    main()

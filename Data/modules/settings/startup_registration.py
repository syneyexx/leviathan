"""Windows-first OS startup registration for ``ui.start_with_system``.

Desired preference is persisted by the Settings Control Plane.
Measured OS registration is reported separately so UI never pretends
registration succeeded when the OS disagrees.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_RUN_VALUE_NAME = "LeviathanAI"
_APP_ID = "Leviathan AI Control Center"


@dataclass(frozen=True)
class StartupRegistrationState:
    platform: str
    supported: bool
    desired: bool
    registered: bool | None
    status: str
    detail: str
    launch_command: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "supported": self.supported,
            "desired": self.desired,
            "registered": self.registered,
            "status": self.status,
            "detail": self.detail,
            "launch_command": self.launch_command,
        }


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def resolve_launch_command() -> str | None:
    """Best-effort absolute command used for OS autostart entries."""
    env_cmd = (os.environ.get("LEVIATHAN_STARTUP_COMMAND") or "").strip()
    if env_cmd:
        return env_cmd
    # Prefer packaged launcher when present next to the repo / install root.
    roots = [
        Path.cwd(),
        Path(__file__).resolve().parents[3],
    ]
    for root in roots:
        for name in ("run_leviathan.bat", "leviathan.py"):
            candidate = root / name
            if candidate.is_file():
                return str(candidate.resolve())
    # Fall back to current interpreter + -m entry if available.
    try:
        return f'"{sys.executable}" -m Data.backend.main'
    except Exception:  # noqa: BLE001
        return None


def measure_registration(*, desired: bool) -> StartupRegistrationState:
    if not _is_windows():
        return StartupRegistrationState(
            platform=sys.platform,
            supported=False,
            desired=desired,
            registered=None,
            status="unsupported",
            detail="OS startup registration is Windows-first; this host does not support it.",
            launch_command=resolve_launch_command(),
        )
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return StartupRegistrationState(
            platform=sys.platform,
            supported=False,
            desired=desired,
            registered=None,
            status="unsupported",
            detail="winreg unavailable — cannot measure Windows Run key state.",
            launch_command=resolve_launch_command(),
        )
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        ) as key:
            try:
                value, _ = winreg.QueryValueEx(key, _RUN_VALUE_NAME)
                registered = bool(str(value or "").strip())
            except FileNotFoundError:
                registered = False
    except OSError as exc:
        return StartupRegistrationState(
            platform=sys.platform,
            supported=True,
            desired=desired,
            registered=None,
            status="unknown",
            detail=f"Failed to read Windows Run key: {exc}",
            launch_command=resolve_launch_command(),
        )
    if desired and registered:
        status = "enabled"
        detail = "Registered in HKCU Run."
    elif desired and not registered:
        status = "registration_missing"
        detail = "Preference enabled but OS registration is absent."
    elif (not desired) and registered:
        status = "stale_registration"
        detail = "OS registration present while preference is disabled."
    else:
        status = "disabled"
        detail = "Not registered."
    return StartupRegistrationState(
        platform=sys.platform,
        supported=True,
        desired=desired,
        registered=registered,
        status=status,
        detail=detail,
        launch_command=resolve_launch_command(),
    )


def apply_registration(*, enabled: bool) -> StartupRegistrationState:
    """Apply desired startup registration. Never uses shell concatenation."""
    if not _is_windows():
        return measure_registration(desired=enabled)
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return measure_registration(desired=enabled)

    launch = resolve_launch_command()
    if enabled and not launch:
        return StartupRegistrationState(
            platform=sys.platform,
            supported=True,
            desired=True,
            registered=False,
            status="registration_failure",
            detail="No launch command resolved for startup registration.",
            launch_command=None,
        )
    access = winreg.KEY_SET_VALUE | winreg.KEY_READ
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            access,
        ) as key:
            if enabled:
                # Quote path when it contains spaces; argv-safe single string for Run key.
                cmd = launch if launch.startswith('"') else (f'"{launch}"' if " " in launch else launch)
                winreg.SetValueEx(key, _RUN_VALUE_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, _RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
    except OSError as exc:
        return StartupRegistrationState(
            platform=sys.platform,
            supported=True,
            desired=enabled,
            registered=None,
            status="permission_failure" if getattr(exc, "winerror", None) in {5, 13} else "registration_failure",
            detail=f"Windows Run key update failed: {exc}",
            launch_command=launch,
        )
    return measure_registration(desired=enabled)


__all__ = [
    "StartupRegistrationState",
    "apply_registration",
    "measure_registration",
    "resolve_launch_command",
    "_APP_ID",
]

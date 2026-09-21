"""Windows-first tray host so HADES can run without an open browser tab.

Uses Win32 Shell_NotifyIcon via ctypes (no extra dependency). On non-Windows
hosts this module reports unavailable and leaves START_HADES.bat as the path.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


FRONTEND_URL_DEFAULT = "http://127.0.0.1:3000"


@dataclass
class ManagedProcess:
    name: str
    popen: subprocess.Popen[Any]


@dataclass
class TrayRuntime:
    root: Path
    frontend_url: str = FRONTEND_URL_DEFAULT
    processes: list[ManagedProcess] = field(default_factory=list)
    _quit_requested: bool = False

    def track(self, name: str, popen: subprocess.Popen[Any]) -> None:
        self.processes.append(ManagedProcess(name=name, popen=popen))

    def open_ui(self) -> None:
        webbrowser.open(self.frontend_url)

    def quit_hades(self) -> None:
        self._quit_requested = True
        for item in list(reversed(self.processes)):
            proc = item.popen
            if proc.poll() is not None:
                continue
            try:
                proc.terminate()
            except OSError:
                pass
        deadline = time.time() + 8
        for item in self.processes:
            proc = item.popen
            remaining = max(0.1, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except Exception:
                try:
                    proc.kill()
                except OSError:
                    pass

    @property
    def quit_requested(self) -> bool:
        return self._quit_requested


def tray_supported() -> bool:
    return os.name == "nt"


def run_win32_tray(
    runtime: TrayRuntime,
    *,
    on_ready: Callable[[], None] | None = None,
) -> int:
    """Block with a NotifyIcon menu: Open UI / Quit HADES."""
    if not tray_supported():
        raise RuntimeError("Tray runtime is Windows-only.")

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32

    class NOTIFYICONDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", wintypes.HICON),
        ]

    WM_USER = 0x0400
    WM_TRAY = WM_USER + 42
    WM_DESTROY = 0x0002
    WM_COMMAND = 0x0111
    WM_RBUTTONUP = 0x0205
    WM_LBUTTONDBLCLK = 0x0203
    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    NIM_ADD = 0x00000000
    NIM_DELETE = 0x00000002
    ID_OPEN = 1001
    ID_QUIT = 1002

    wc_atom = None
    hwnd = None
    nid = NOTIFYICONDATA()

    def _cleanup() -> None:
        try:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        except Exception:
            pass
        if hwnd:
            user32.DestroyWindow(hwnd)

    def wndproc(hWnd, msg, wParam, lParam):  # noqa: N803
        if msg == WM_TRAY:
            if lParam in (WM_RBUTTONUP, WM_LBUTTONDBLCLK):
                menu = user32.CreatePopupMenu()
                user32.AppendMenuW(menu, 0, ID_OPEN, "Open UI")
                user32.AppendMenuW(menu, 0, ID_QUIT, "Quit HADES")
                pt = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                user32.SetForegroundWindow(hWnd)
                cmd = user32.TrackPopupMenu(menu, 0x0100, pt.x, pt.y, 0, hWnd, None)
                user32.DestroyMenu(menu)
                if cmd == ID_OPEN or lParam == WM_LBUTTONDBLCLK:
                    runtime.open_ui()
                elif cmd == ID_QUIT:
                    runtime.quit_hades()
                    user32.PostMessageW(hWnd, WM_DESTROY, 0, 0)
            return 0
        if msg == WM_COMMAND:
            if wParam == ID_OPEN:
                runtime.open_ui()
            elif wParam == ID_QUIT:
                runtime.quit_hades()
                user32.PostMessageW(hWnd, WM_DESTROY, 0, 0)
            return 0
        if msg == WM_DESTROY:
            _cleanup()
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hWnd, msg, wParam, lParam)

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    proc = WNDPROC(wndproc)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HCURSOR),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    h_instance = kernel32.GetModuleHandleW(None)
    class_name = "HADESTrayHost"
    wc = WNDCLASS()
    wc.lpfnWndProc = proc
    wc.hInstance = h_instance
    wc.lpszClassName = class_name
    wc_atom = user32.RegisterClassW(ctypes.byref(wc))
    if not wc_atom:
        raise OSError("RegisterClassW failed for HADES tray")

    hwnd = user32.CreateWindowExW(0, class_name, "HADES", 0, 0, 0, 0, 0, 0, 0, h_instance, None)
    if not hwnd:
        raise OSError("CreateWindowExW failed for HADES tray")

    nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
    nid.hWnd = hwnd
    nid.uID = 1
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    nid.uCallbackMessage = WM_TRAY
    nid.hIcon = user32.LoadIconW(None, 32512)  # IDI_APPLICATION
    nid.szTip = "HADES"

    if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
        raise OSError("Shell_NotifyIconW failed")

    atexit.register(_cleanup)
    if on_ready:
        on_ready()

    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
        if runtime.quit_requested:
            break
    return 0

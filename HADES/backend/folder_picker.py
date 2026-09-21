"""Native local folder picker for HADES (Windows-first).

The Plugins UI uses this so a user can choose a source folder on the HADES
machine without typing a path. Dialogs run in a subprocess or toolkit call so
uvicorn worker threads do not have to be STA/COM-initialized.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class FolderPickerUnavailable(RuntimeError):
    """Raised when no native folder dialog can be shown in this environment."""


_POWERSHELL_FOLDER_PICKER = r"""
Add-Type -AssemblyName System.Windows.Forms | Out-Null
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $env:HADES_FOLDER_PICKER_TITLE
$dialog.ShowNewFolderButton = $false
try { $dialog.UseDescriptionForTitle = $true } catch { }
$dialog.RootFolder = [System.Environment+SpecialFolder]::MyComputer
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.TopMost = $true
$form.ShowInTaskbar = $false
$form.WindowState = 'Minimized'
$form.Show()
$result = $dialog.ShowDialog($form)
$form.Close()
$form.Dispose()
if ($result -eq [System.Windows.Forms.DialogResult]::OK -and $dialog.SelectedPath) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($dialog.SelectedPath)
    $stdout = [Console]::OpenStandardOutput()
    $stdout.Write($bytes, 0, $bytes.Length)
}
"""


def pick_directory(title: str = "Selecteer pluginmap") -> str | None:
    """Open a native folder dialog. Returns the selected path, or None if cancelled."""
    errors: list[str] = []
    pickers = ((_pick_windows_powershell, _pick_tkinter) if os.name == "nt" else (_pick_tkinter,))
    for picker in pickers:
        try:
            return picker(title)
        except FolderPickerUnavailable as exc:
            errors.append(str(exc))
    detail = " ".join(errors).strip()
    raise FolderPickerUnavailable(detail or "Mapkiezer is niet beschikbaar in deze omgeving.")


def _powershell_executable() -> Path:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if candidate.is_file():
        return candidate
    found = shutil.which("powershell") or shutil.which("powershell.exe")
    if found:
        return Path(found)
    raise FolderPickerUnavailable("PowerShell ontbreekt; de Windows-mapkiezer kan niet worden geopend.")


def _pick_windows_powershell(title: str) -> str | None:
    if os.name != "nt":
        raise FolderPickerUnavailable("PowerShell-mapkiezer is alleen beschikbaar op Windows.")
    env = os.environ.copy()
    env["HADES_FOLDER_PICKER_TITLE"] = title
    try:
        completed = subprocess.run(
            [
                str(_powershell_executable()),
                "-NoProfile",
                "-STA",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _POWERSHELL_FOLDER_PICKER,
            ],
            capture_output=True,
            timeout=900,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise FolderPickerUnavailable("De mapkiezer is verlopen zonder selectie.") from exc
    except OSError as exc:
        raise FolderPickerUnavailable(f"PowerShell-mapkiezer kon niet starten: {exc}") from exc
    if completed.returncode not in {0, None}:
        detail = (completed.stderr or completed.stdout or b"").decode("utf-8", errors="replace").strip()
        raise FolderPickerUnavailable(detail or "PowerShell-mapkiezer is mislukt.")
    selected = (completed.stdout or b"").decode("utf-8", errors="replace").strip()
    return selected or None


def _pick_tkinter(title: str) -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise FolderPickerUnavailable("tkinter-mapkiezer is niet beschikbaar.") from exc
    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    try:
        selected = filedialog.askdirectory(title=title, mustexist=True)
    except Exception as exc:
        raise FolderPickerUnavailable(f"Mapkiezer kon niet worden geopend: {exc}") from exc
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    return selected or None


__all__ = ["FolderPickerUnavailable", "pick_directory"]
